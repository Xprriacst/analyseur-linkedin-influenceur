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
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

BASE_URL = "https://zernio.com/api/v1"
PLATFORM = "linkedin"  # default / legacy constant
# Slug Zernio pour X : leur API n'accepte que "twitter" — "x" est rejeté en 400
# ("Platform not supported" sur /connect, "invalid_field_value" sur /posts).
PLATFORM_X = "twitter"
MAX_LINKEDIN_IMAGES = 20
MAX_LINKEDIN_IMAGE_BYTES = 8 * 1024 * 1024
MEDIA_READY_RETRIES = 5
MEDIA_READY_DELAY_S = 0.6
IMAGE_CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
# ALE-293 : upload de la vidéo tournée pour un reel Instagram. Meta accepte
# jusqu'à 300 Mo, mais on plafonne plus bas (100 Mo) pour protéger la mémoire
# du web service Render — un fichier de cette taille traverse entièrement le
# process (lecture + upload vers Zernio) avant d'être libéré, et l'historique
# d'OOM du service (2026-06-25, 2026-07-10) rend une marge large nécessaire.
# Un reel de 90 s (le max Instagram) tient largement dans cette limite à un
# bitrate raisonnable.
VIDEO_CONTENT_TYPES = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
}
MAX_REEL_VIDEO_BYTES = 100 * 1024 * 1024
_DATA_URL_RE = re.compile(r"^data:(?P<content_type>[-\w.]+/[-+\w.]+);base64,(?P<data>.+)$", re.DOTALL)


DEFAULT_TIMEOUT_S = 30
# Publication synchrone (`publishNow: true`) : Zernio télécharge d'abord chaque
# média puis le pousse vers le réseau DANS LA MÊME REQUÊTE (doc : « publish
# synchronously, inside this request »). Mesuré en prod le 2026-09-08 : sur 18
# posts programmés en échec, 14 étaient des « The read operation timed out » à
# 30 s, 13 d'entre eux avec une image. 30 s convient à un appel de lecture, pas
# à une publication avec média.
PUBLISH_TIMEOUT_DEFAULT_S = 120


def _publish_timeout() -> int:
    raw = os.environ.get("ZERNIO_PUBLISH_TIMEOUT_S", "").strip()
    try:
        value = int(raw) if raw else PUBLISH_TIMEOUT_DEFAULT_S
    except ValueError:
        value = PUBLISH_TIMEOUT_DEFAULT_S
    return max(DEFAULT_TIMEOUT_S, value)


class ZernioError(RuntimeError):
    """Raised when the Zernio API returns an error or is not configured."""


class ZernioTimeout(ZernioError):
    """Zernio n'a pas répondu à temps.

    ⚠️ Ce n'est PAS un échec : la requête a peut-être abouti côté Zernio (et le
    post être en ligne). L'appelant ne doit jamais la traiter comme « rien n'est
    parti » ni rejouer sans garde-fou d'idempotence.
    """


class ZernioDuplicate(ZernioError):
    """409 Zernio : ce contenu est déjà publié (ou en cours) sur ce compte.

    Dédoublonnage par empreinte `(platform, accountId, content + media)` sur
    24 h. `existing_post_id` est l'id Zernio du post déjà en ligne.
    """

    def __init__(self, message: str, *, existing_post_id: str | None = None):
        super().__init__(message)
        self.existing_post_id = existing_post_id


def enabled() -> bool:
    return bool(os.environ.get("ZERNIO_API_KEY"))


def _api_key() -> str:
    key = os.environ.get("ZERNIO_API_KEY")
    if not key:
        raise ZernioError("ZERNIO_API_KEY manquant dans l'environnement serveur.")
    return key


def _is_timeout(exc: BaseException) -> bool:
    # Python < 3.10 : socket.timeout est distinct de TimeoutError ; ≥ 3.10 c'est
    # le même objet. urllib lève l'un OU l'autre selon la phase (connexion vs
    # lecture), parfois enveloppé dans URLError.reason.
    return isinstance(exc, (socket.timeout, TimeoutError))


def _request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    body: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT_S,
) -> Any:
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {_api_key()}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        parsed: Any = None
        try:
            parsed = json.loads(detail)
            detail = parsed.get("error") or parsed.get("message") or detail
        except Exception:
            pass
        if exc.code == 409:
            existing = None
            if isinstance(parsed, dict):
                details = parsed.get("details") if isinstance(parsed.get("details"), dict) else {}
                existing = details.get("existingPostId") or parsed.get("existingPostId")
            raise ZernioDuplicate(
                f"Zernio {method} {path} : contenu déjà publié sur ce compte ({detail})",
                existing_post_id=str(existing) if existing else None,
            ) from exc
        raise ZernioError(f"Zernio {method} {path} a échoué ({exc.code}) : {detail}") from exc
    except urllib.error.URLError as exc:
        if _is_timeout(exc.reason):
            raise ZernioTimeout(f"Zernio n'a pas répondu en {timeout} s ({method} {path}).") from exc
        raise ZernioError(f"Zernio injoignable : {exc.reason}") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise ZernioTimeout(f"Zernio n'a pas répondu en {timeout} s ({method} {path}).") from exc
    return json.loads(raw) if raw else {}


def _sanitize_filename(filename: str | None, default_ext: str, index: int = 1) -> str:
    name = (filename or "").strip().split("/")[-1].split("\\")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    if not name:
        name = f"media-{index}.{default_ext}"
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


def _wait_media_ready(public_url: str) -> None:
    """Poll the freshly-uploaded media URL until it is actually readable.

    Le PUT sur l'URL présignée répond en 2xx dès que Zernio a accepté le
    fichier, mais son stockage peut mettre un court instant à le rendre lisible
    (propagation) — un POST /posts trop rapide échoue alors avec "Some media
    files failed to upload" malgré un upload réussi. Best-effort : on ne fait
    jamais échouer l'upload sur ce contrôle, on donne juste un peu de temps
    avant l'appel à create_post.
    """
    for attempt in range(MEDIA_READY_RETRIES):
        req = urllib.request.Request(public_url, method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = getattr(resp, "status", 200)
                if 200 <= status < 300:
                    return
        except urllib.error.HTTPError as exc:
            if 200 <= exc.code < 300:
                return
        except Exception:
            pass
        if attempt < MEDIA_READY_RETRIES - 1:
            time.sleep(MEDIA_READY_DELAY_S)


def upload_media_bytes(filename: str, content_type: str, data: bytes, timeout: int = 120) -> str:
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise ZernioError(f"Upload média Zernio échoué ({exc.code}) : {detail}") from exc
    except urllib.error.URLError as exc:
        raise ZernioError(f"Upload média Zernio injoignable : {exc.reason}") from exc
    _wait_media_ready(public_url)
    return public_url


def upload_reel_video(filename: str | None, content_type: str, data: bytes) -> str:
    """Upload une vidéo de reel (bytes bruts, pas de data URL — trop volumineux
    pour transiter en base64 dans un JSON) et retourne son URL publique."""
    content_type = (content_type or "").lower().strip()
    if content_type not in VIDEO_CONTENT_TYPES:
        raise ZernioError("Format vidéo non supporté. Utilise MP4 ou MOV.")
    if not data:
        raise ZernioError("Vidéo invalide : fichier vide.")
    if len(data) > MAX_REEL_VIDEO_BYTES:
        mb = MAX_REEL_VIDEO_BYTES // (1024 * 1024)
        raise ZernioError(f"Vidéo trop volumineuse ({len(data) // (1024 * 1024)} Mo, {mb} Mo maximum).")
    safe_name = _sanitize_filename(filename, VIDEO_CONTENT_TYPES[content_type])
    return upload_media_bytes(safe_name, content_type, data, timeout=300)


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


def find_account(profile_id: str, platform: str = PLATFORM) -> dict[str, Any] | None:
    """Return the connected account object for the given platform, if any."""
    data = _request("GET", "/accounts", params={"profileId": profile_id})
    for account in data.get("accounts", []):
        if account.get("platform") == platform:
            return account
    return None


def find_account_id(profile_id: str, platform: str = PLATFORM) -> str | None:
    """Return the connected account id for the given platform, if any."""
    account = find_account(profile_id, platform)
    return account.get("_id") if account else None


def account_display_name(account: dict[str, Any] | None) -> str | None:
    """Best-effort human name of a connected account.

    Le schéma exact de Zernio pour /accounts n'est pas garanti : on teste les
    clés usuelles (et un éventuel objet imbriqué) et on renvoie la 1re non vide.
    """
    if not isinstance(account, dict):
        return None
    for key in ("name", "displayName", "fullName", "username", "handle", "screenName", "profileName"):
        val = account.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    for nested_key in ("profile", "user", "account", "details"):
        nested = account.get(nested_key)
        if isinstance(nested, dict):
            name = account_display_name(nested)
            if name:
                return name
    return None


def account_type(account: dict[str, Any] | None) -> str | None:
    """Best-effort type de compte (profil personnel vs page entreprise/organisation).

    Dépend de ce que Zernio expose ; renvoie la valeur brute en minuscules si
    présente, sinon None (le front n'affiche alors pas de mention de type).
    """
    if not isinstance(account, dict):
        return None
    for key in ("type", "accountType", "entityType", "kind", "category"):
        val = account.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().lower()
    return None


# Backward-compat alias
def find_linkedin_account_id(profile_id: str) -> str | None:
    return find_account_id(profile_id, "linkedin")


# ── ALE-59 : Reddit — vérification de subreddit + flairs ─────────────────────

def validate_subreddit(name: str, account_id: str | None = None) -> dict[str, Any]:
    """Vérifie l'existence d'un subreddit via Zernio (« l'IA propose, Reddit confirme »).

    Renvoie {"exists": bool, "subreddit": {...}} (title, subscribers, isNSFW,
    type…). Avec `account_id`, Zernio interroge l'API Reddit OAuth du compte
    connecté (fiable) ; sinon il retombe sur l'API JSON publique de Reddit.
    """
    params: dict[str, Any] = {"name": name.strip().removeprefix("r/")}
    if account_id:
        params["accountId"] = account_id
    return _request("GET", "/tools/validate/subreddit", params=params)


def list_reddit_flairs(account_id: str, subreddit: str) -> list[dict[str, Any]]:
    """Liste les flairs disponibles d'un subreddit (certains l'exigent)."""
    data = _request(
        "GET",
        f"/accounts/{account_id}/reddit-flairs",
        params={"subreddit": subreddit.strip().removeprefix("r/")},
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        flairs = data.get("flairs") or data.get("data")
        if isinstance(flairs, list):
            return flairs
    return []


def create_post(
    content: str,
    account_id: str,
    *,
    publish_now: bool = True,
    is_draft: bool = False,
    media_items: list[dict[str, Any]] | None = None,
    platform: str = PLATFORM,
    platform_specific_data: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Publish or save as draft a post on the given account.

    `platform_specific_data` (ALE-59) porte les options propres au réseau, dans
    l'entrée du tableau `platforms` (schéma OpenAPI Zernio) : `threadItems` pour
    un thread X, `{subreddit, title, flairId…}` pour Reddit.

    `request_id` = clé d'idempotence (en-tête `x-request-id`, fenêtre ~5 min
    chez Zernio). Passer un identifiant STABLE par publication logique (id du
    post programmé, du post sauvegardé…) : c'est ce qui rend le rejeu après un
    timeout sûr — Zernio renvoie alors le post déjà créé (`existingPost`) au
    lieu d'en publier un second. Sans valeur fournie, un UUID par appel protège
    au moins le rejeu interne de cette fonction.

    Lève `ZernioTimeout` si Zernio n'a pas confirmé après deux tentatives (le
    post est PEUT-ÊTRE en ligne), `ZernioDuplicate` (409) si ce contenu est déjà
    publié sur ce compte, `ZernioError` sinon — y compris quand Zernio répond
    2xx (207) avec `post.status == "failed"` : urllib ne distingue pas un 207
    d'un 201, et un client qui ne regarde que le code lirait « publié ».
    """
    platform_entry: dict[str, Any] = {"platform": platform, "accountId": account_id}
    if platform_specific_data:
        platform_entry["platformSpecificData"] = platform_specific_data
    body: dict[str, Any] = {
        "content": content,
        "platforms": [platform_entry],
    }
    if media_items:
        body["mediaItems"] = media_items
    if is_draft:
        body["isDraft"] = True
    else:
        body["publishNow"] = publish_now
    request_id = (request_id or "").strip() or f"cibl-{uuid.uuid4()}"
    publishes_now = bool(publish_now) and not is_draft
    timeout = _publish_timeout() if publishes_now else DEFAULT_TIMEOUT_S

    def send(rid: str) -> dict[str, Any]:
        return _request("POST", "/posts", body=body, headers={"x-request-id": rid}, timeout=timeout)

    try:
        result = send(request_id)
    except ZernioTimeout:
        # Rejeu SÛR : même x-request-id ⇒ si la première requête a abouti
        # pendant qu'on n'attendait plus, Zernio renvoie ce post-là (200,
        # `existingPost`) au lieu d'en créer un second ; sinon il la traite.
        try:
            result = send(request_id)
        except ZernioTimeout as exc:
            raise ZernioTimeout(
                f"Zernio n'a pas confirmé la publication {platform} en {2 * timeout} s. "
                "Le post est PEUT-ÊTRE déjà en ligne : vérifie sur le réseau avant de relancer "
                f"(x-request-id {request_id})."
            ) from exc
    except ZernioError as exc:
        if media_items and "failed to upload" in str(exc).lower():
            # Filet de sécurité si _wait_media_ready n'a pas suffi : Zernio a
            # eu besoin d'un peu plus de temps pour rendre le média lisible.
            # Nouvel id : la 1re tentative a été REFUSÉE (400, rien de créé),
            # rejouer son x-request-id pourrait nous rendre ce refus au lieu de
            # retenter. Le dédoublonnage par contenu (409) protège toujours.
            time.sleep(MEDIA_READY_DELAY_S * MEDIA_READY_RETRIES)
            result = send(f"{request_id}-r2")
        else:
            raise
    return _accept_publish_result(result, platform=platform)


def _accept_publish_result(result: Any, *, platform: str) -> dict[str, Any]:
    """Normalise la réponse de POST /posts et refuse un « 2xx qui a échoué ».

    - Rejeu idempotent : Zernio répond 200 avec le post d'origine dans
      `existingPost` → on le remonte comme `post` (l'appelant lit `post._id`).
    - 207 : le post est créé mais la publication inline n'a pas abouti ;
      `post.status == "failed"` est terminal (« nothing will be retried »). Le
      remonter comme un succès marquerait « publié » un post que personne ne
      verra jamais — exactement la panne silencieuse à éviter. (`scheduled` =
      erreur transitoire, Zernio republie seul : ce n'est PAS un échec.)
    """
    if not isinstance(result, dict):
        return {"post": {}}
    existing = result.get("existingPost")
    if isinstance(existing, dict) and existing:
        result = {**result, "post": existing, "replayed": True}
    post = result.get("post") if isinstance(result.get("post"), dict) else {}
    if (post or {}).get("status") == "failed":
        detail = result.get("error")
        if not detail:
            for entry in result.get("platformResults") or []:
                if isinstance(entry, dict) and entry.get("error"):
                    detail = entry["error"]
                    break
        if not detail:
            for entry in post.get("platforms") or []:
                if isinstance(entry, dict) and entry.get("errorMessage"):
                    detail = entry["errorMessage"]
                    break
        raise ZernioError(f"Publication {platform} refusée par le réseau : {detail or 'motif non précisé par Zernio'}")
    return result
