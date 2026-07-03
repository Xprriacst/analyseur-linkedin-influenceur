"""Thin Zernio API client (multi-platform publishing: LinkedIn, X/Twitter).

A single server-side API key (ZERNIO_API_KEY) drives one Zernio "profile" per
app user. Each profile can connect multiple platforms (LinkedIn, X) via OAuth
handled by Zernio. We store one account id per platform.

Uses stdlib urllib to avoid adding an HTTP dependency (matches api.py).
"""
from __future__ import annotations

import json
import os
import base64
import binascii
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BASE_URL = "https://zernio.com/api/v1"
PLATFORM = "linkedin"  # default / legacy constant
MAX_LINKEDIN_IMAGES = 20
MAX_LINKEDIN_IMAGE_BYTES = 8 * 1024 * 1024
# ALE-186 : LinkedIn accepte 1 document (PDF → carrousel) par post, jamais
# mélangé avec des images. Zernio plafonne à 100 Mo / 300 pages ; on limite à
# 20 Mo car le fichier transite en base64 dans le JSON de l'API.
MAX_LINKEDIN_DOCUMENT_BYTES = 20 * 1024 * 1024
IMAGE_CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
DOCUMENT_CONTENT_TYPES = {
    "application/pdf": "pdf",
}
_DATA_URL_RE = re.compile(r"^data:(?P<content_type>[-\w.]+/[-+\w.]+);base64,(?P<data>.+)$", re.DOTALL)


class ZernioError(RuntimeError):
    """Raised when the Zernio API returns an error or is not configured."""


def enabled() -> bool:
    return bool(os.environ.get("ZERNIO_API_KEY"))


def _api_key() -> str:
    key = os.environ.get("ZERNIO_API_KEY")
    if not key:
        raise ZernioError("ZERNIO_API_KEY manquant dans l'environnement serveur.")
    return key


def _request(method: str, path: str, *, params: dict | None = None, body: dict | None = None) -> Any:
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {_api_key()}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(detail)
            detail = parsed.get("error") or parsed.get("message") or detail
        except Exception:
            pass
        raise ZernioError(f"Zernio {method} {path} a échoué ({exc.code}) : {detail}") from exc
    except urllib.error.URLError as exc:
        raise ZernioError(f"Zernio injoignable : {exc.reason}") from exc
    return json.loads(raw) if raw else {}


def _sanitize_filename(filename: str | None, default_ext: str, index: int = 1) -> str:
    name = (filename or "").strip().split("/")[-1].split("\\")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    if not name:
        name = f"linkedin-image-{index}.{default_ext}"
    if "." not in name:
        name = f"{name}.{default_ext}"
    return name[:120]


def _decode_data_url(data_url: str) -> tuple[str, bytes]:
    match = _DATA_URL_RE.match(data_url.strip())
    if not match:
        raise ZernioError("Image invalide : format data URL base64 attendu.")
    content_type = match.group("content_type").lower()
    if content_type not in IMAGE_CONTENT_TYPES:
        raise ZernioError("Format image non supporté. Utilise JPG, PNG, WebP ou GIF.")
    try:
        data = base64.b64decode(match.group("data"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ZernioError("Image invalide : base64 illisible.") from exc
    if not data:
        raise ZernioError("Image invalide : fichier vide.")
    if len(data) > MAX_LINKEDIN_IMAGE_BYTES:
        raise ZernioError("Image trop volumineuse pour LinkedIn (8 Mo maximum).")
    return content_type, data


def upload_media_bytes(filename: str, content_type: str, data: bytes) -> str:
    """Upload media bytes to Zernio storage and return the public URL."""
    presign = _request(
        "POST",
        "/media/presign",
        body={"filename": filename, "contentType": content_type, "size": len(data)},
    )
    upload_url = presign.get("uploadUrl")
    public_url = presign.get("publicUrl")
    if not upload_url or not public_url:
        raise ZernioError("Réponse Zernio inattendue : URL d'upload média manquante.")

    req = urllib.request.Request(upload_url, data=data, method="PUT")
    req.add_header("Content-Type", content_type)
    req.add_header("Content-Length", str(len(data)))
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise ZernioError(f"Upload média Zernio échoué ({exc.code}) : {detail}") from exc
    except urllib.error.URLError as exc:
        raise ZernioError(f"Upload média Zernio injoignable : {exc.reason}") from exc
    return public_url


def _is_document_item(item: dict[str, Any]) -> bool:
    if str(item.get("type") or "").strip().lower() == "document":
        return True
    source = str(item.get("data_url") or item.get("url") or "").strip()
    if source.startswith("data:"):
        return source[5:].split(";", 1)[0].strip().lower() in DOCUMENT_CONTENT_TYPES
    return urllib.parse.urlparse(source).path.lower().endswith(".pdf")


def _prepare_document_item(doc: dict[str, Any]) -> dict[str, Any]:
    """Convert a PDF attachment into a Zernio `document` mediaItem.

    LinkedIn affiche le PDF en carrousel feuilletable ; Zernio utilise le
    `title` de l'item comme titre du document (fallback : nom du fichier)."""
    source = str(doc.get("data_url") or doc.get("url") or "").strip()
    if not source:
        raise ZernioError("Document invalide : URL ou data_url manquante.")

    if source.startswith("data:"):
        match = _DATA_URL_RE.match(source)
        if not match:
            raise ZernioError("Document invalide : format data URL base64 attendu.")
        content_type = match.group("content_type").lower()
        if content_type not in DOCUMENT_CONTENT_TYPES:
            raise ZernioError("Format document non supporté. Utilise un PDF.")
        try:
            data = base64.b64decode(match.group("data"), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ZernioError("Document invalide : base64 illisible.") from exc
        if not data:
            raise ZernioError("Document invalide : fichier vide.")
        if len(data) > MAX_LINKEDIN_DOCUMENT_BYTES:
            raise ZernioError("PDF trop volumineux (20 Mo maximum).")
        filename = _sanitize_filename(doc.get("filename"), DOCUMENT_CONTENT_TYPES[content_type])
        media_url = upload_media_bytes(filename, content_type, data)
    else:
        parsed = urllib.parse.urlparse(source)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ZernioError("Document invalide : URL publique http(s) attendue.")
        media_url = source

    item: dict[str, Any] = {"type": "document", "url": media_url}
    title = str(doc.get("title") or doc.get("filename") or "").strip()
    if title:
        item["title"] = title[:200]
    return item


def prepare_media_items(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Convert app attachments (images OU un document PDF) into Zernio mediaItems.

    Contrainte LinkedIn : un post contient soit jusqu'à 20 images, soit 1 seul
    document — jamais les deux (ALE-186)."""
    if not items:
        return []
    documents = [item for item in items if _is_document_item(item)]
    images = [item for item in items if not _is_document_item(item)]
    if documents and images:
        raise ZernioError("LinkedIn n'accepte pas d'images en plus d'un document PDF dans le même post.")
    if len(documents) > 1:
        raise ZernioError("LinkedIn accepte un seul document PDF par post.")
    if documents:
        return [_prepare_document_item(documents[0])]
    return prepare_image_media_items(images)


def prepare_image_media_items(images: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Convert app image attachments into Zernio mediaItems."""
    if not images:
        return []
    if len(images) > MAX_LINKEDIN_IMAGES:
        raise ZernioError(f"LinkedIn accepte {MAX_LINKEDIN_IMAGES} images maximum par post.")

    media_items: list[dict[str, Any]] = []
    for index, image in enumerate(images, start=1):
        source = str(image.get("data_url") or image.get("url") or "").strip()
        if not source:
            raise ZernioError("Image invalide : URL ou data_url manquante.")

        if source.startswith("data:"):
            content_type, data = _decode_data_url(source)
            filename = _sanitize_filename(image.get("filename"), IMAGE_CONTENT_TYPES[content_type], index)
            media_url = upload_media_bytes(filename, content_type, data)
        else:
            parsed = urllib.parse.urlparse(source)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ZernioError("Image invalide : URL publique http(s) attendue.")
            media_url = source

        item: dict[str, Any] = {"type": "image", "url": media_url}
        title = str(image.get("title") or image.get("filename") or "").strip()
        if title:
            item["title"] = title[:200]
        media_items.append(item)
    return media_items


def create_profile(name: str, description: str | None = None) -> str:
    """Create a Zernio profile and return its id."""
    body: dict[str, Any] = {"name": name[:120] or "Client"}
    if description:
        body["description"] = description[:500]
    data = _request("POST", "/profiles", body=body)
    profile = data.get("profile") or data
    profile_id = profile.get("_id")
    if not profile_id:
        raise ZernioError("Réponse Zernio inattendue : pas d'_id de profile.")
    return profile_id


def get_connect_url(profile_id: str, redirect_url: str | None = None, platform: str = PLATFORM) -> str:
    """Return the OAuth authorization URL for the given platform (default: linkedin)."""
    data = _request(
        "GET",
        f"/connect/{platform}",
        params={"profileId": profile_id, "redirect_url": redirect_url},
    )
    auth_url = data.get("authUrl")
    if not auth_url:
        raise ZernioError("Réponse Zernio inattendue : pas d'authUrl.")
    return auth_url


def find_account_id(profile_id: str, platform: str = PLATFORM) -> str | None:
    """Return the connected account id for the given platform, if any."""
    data = _request("GET", "/accounts", params={"profileId": profile_id})
    for account in data.get("accounts", []):
        if account.get("platform") == platform:
            return account.get("_id")
    return None


# Backward-compat alias
def find_linkedin_account_id(profile_id: str) -> str | None:
    return find_account_id(profile_id, "linkedin")


def create_post(
    content: str,
    account_id: str,
    *,
    publish_now: bool = True,
    is_draft: bool = False,
    media_items: list[dict[str, Any]] | None = None,
    platform: str = PLATFORM,
) -> dict[str, Any]:
    """Publish or save as draft a post on the given account."""
    body: dict[str, Any] = {
        "content": content,
        "platforms": [{"platform": platform, "accountId": account_id}],
    }
    if media_items:
        body["mediaItems"] = media_items
    if is_draft:
        body["isDraft"] = True
    else:
        body["publishNow"] = publish_now
    return _request("POST", "/posts", body=body)
