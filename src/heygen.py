"""Thin HeyGen API client (AI avatar videos).

Une seule clé serveur (HEYGEN_API_KEY) porte les avatars de tous les clients de
l'app (pas de notion de seat côté API HeyGen) : chaque client crée SON photo
avatar depuis Cibl, et les vidéos sont générées avec le `look_id` stocké sur
son profil. Facturation HeyGen en pay-as-you-go (~1 $ la création d'avatar,
~0,05 $/s de vidéo en Avatar IV) — indépendante des crédits Cibl.

Endpoints v3 utilisés (docs developers.heygen.com, vérifiés le 2026-08-12) :
- POST /v3/avatars               (type "photo" : création sans consentement)
- GET  /v3/avatars/looks/{id}    (statut d'entraînement du look)
- GET  /v3/voices                (voix stock, filtrables par langue)
- POST /v3/videos                (type "avatar", aspect_ratio 9:16)
- GET  /v3/videos/{id}           (statut + video_url pré-signée)

⚠️ L'URL `video_url` renvoyée à la complétion est PRÉ-SIGNÉE et expire : la
télécharger immédiatement et re-héberger (Zernio), ne jamais la persister telle
quelle.

Uses stdlib urllib to avoid adding an HTTP dependency (matches zernio.py).
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BASE_URL = "https://api.heygen.com"

IMAGE_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
MAX_AVATAR_PHOTO_BYTES = 8 * 1024 * 1024
# Même plafond que l'upload de reel (zernio.MAX_REEL_VIDEO_BYTES) : la vidéo
# téléchargée traverse entièrement la mémoire du process avant d'être
# re-hébergée — l'historique d'OOM du service impose une borne dure.
MAX_VIDEO_DOWNLOAD_BYTES = 100 * 1024 * 1024
# Longueur max du script acceptée par HeyGen : 5 000 caractères. On borne un
# peu en dessous pour garder la marge d'un éventuel préambule.
MAX_SCRIPT_CHARS = 4800

_DATA_URL_RE = re.compile(r"^data:(?P<content_type>[-\w.]+/[-+\w.]+);base64,(?P<data>.+)$", re.DOTALL)

# Statuts normalisés (avatar comme vidéo) : "processing" | "completed" | "failed"
_FAILED_STATUSES = {"failed", "error", "fail"}
_COMPLETED_STATUSES = {"completed", "done", "success", "ready"}


class HeygenError(RuntimeError):
    """Raised when the HeyGen API returns an error or is not configured."""


def enabled() -> bool:
    return bool(os.environ.get("HEYGEN_API_KEY"))


def _api_key() -> str:
    key = os.environ.get("HEYGEN_API_KEY")
    if not key:
        raise HeygenError("HEYGEN_API_KEY manquant dans l'environnement serveur.")
    return key


def _request(method: str, path: str, *, params: dict | None = None, body: dict | None = None,
             timeout: int = 60) -> Any:
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-Api-Key", _api_key())
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(detail)
            err = parsed.get("error")
            if isinstance(err, dict):
                detail = err.get("message") or err.get("code") or detail
            else:
                detail = err or parsed.get("message") or detail
        except Exception:
            pass
        raise HeygenError(f"HeyGen {method} {path} a échoué ({exc.code}) : {detail}") from exc
    except urllib.error.URLError as exc:
        raise HeygenError(f"HeyGen injoignable : {exc.reason}") from exc
    parsed = json.loads(raw) if raw else {}
    # Les réponses v3 enveloppent le payload dans {"data": …} ; certains
    # endpoints renvoient l'objet à plat. On tolère les deux.
    if isinstance(parsed, dict) and "data" in parsed and parsed.get("data") is not None:
        return parsed["data"]
    return parsed


def _normalize_status(raw: Any) -> str:
    status = str(raw or "").strip().lower()
    if status in _COMPLETED_STATUSES:
        return "completed"
    if status in _FAILED_STATUSES:
        return "failed"
    return "processing"


def _file_payload(image_source: str) -> dict[str, Any]:
    """Build the `file` field of POST /v3/avatars from a data URL or public URL."""
    source = (image_source or "").strip()
    if not source:
        raise HeygenError("Photo invalide : URL ou data URL attendue.")
    if source.startswith("data:"):
        match = _DATA_URL_RE.match(source)
        if not match:
            raise HeygenError("Photo invalide : format data URL base64 attendu.")
        content_type = match.group("content_type").lower()
        if content_type not in IMAGE_CONTENT_TYPES:
            raise HeygenError("Format photo non supporté. Utilise JPG, PNG ou WebP.")
        payload = match.group("data")
        try:
            decoded = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HeygenError("Photo invalide : base64 illisible.") from exc
        if not decoded:
            raise HeygenError("Photo invalide : fichier vide.")
        if len(decoded) > MAX_AVATAR_PHOTO_BYTES:
            raise HeygenError("Photo trop volumineuse (8 Mo maximum).")
        return {"type": "base64", "media_type": content_type, "data": payload}
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HeygenError("Photo invalide : URL publique https attendue.")
    return {"type": "url", "url": source}


def _normalize_avatar(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize a create-avatar / get-look response into our shape."""
    item = data.get("avatar_item") if isinstance(data.get("avatar_item"), dict) else data
    group = data.get("avatar_group") if isinstance(data.get("avatar_group"), dict) else {}
    look_id = item.get("id") or item.get("look_id") or item.get("avatar_id")
    if not look_id:
        raise HeygenError("Réponse HeyGen inattendue : pas d'identifiant d'avatar.")
    return {
        "look_id": str(look_id),
        "group_id": str(item.get("group_id") or group.get("id") or "") or None,
        "status": _normalize_status(item.get("status")),
        "preview_image_url": item.get("preview_image_url") or item.get("image_url"),
        "default_voice_id": item.get("default_voice_id") or group.get("default_voice_id"),
    }


def create_photo_avatar(name: str, image_source: str) -> dict[str, Any]:
    """Create a photo avatar (Avatar IV) from a client photo. No consent step.

    `image_source` : data URL base64 (upload direct) ou URL publique https
    (ex. une photo déjà hébergée par « Mes photos »).
    """
    body = {
        "type": "photo",
        "name": (name or "Avatar").strip()[:120] or "Avatar",
        "file": _file_payload(image_source),
    }
    data = _request("POST", "/v3/avatars", body=body, timeout=120)
    return _normalize_avatar(data if isinstance(data, dict) else {})


def get_avatar_look(look_id: str) -> dict[str, Any]:
    """Return the training status of a photo avatar look."""
    data = _request("GET", f"/v3/avatars/looks/{urllib.parse.quote(look_id)}")
    return _normalize_avatar(data if isinstance(data, dict) else {})


def list_voices(language: str = "French", limit: int = 50) -> list[dict[str, Any]]:
    """List stock voices for the given language (normalized, tolerant schema)."""
    data = _request("GET", "/v3/voices", params={"language": language, "limit": limit})
    raw_voices: Any = data
    if isinstance(data, dict):
        raw_voices = data.get("voices") or data.get("items") or data.get("list") or []
    voices: list[dict[str, Any]] = []
    for voice in raw_voices if isinstance(raw_voices, list) else []:
        if not isinstance(voice, dict):
            continue
        voice_id = voice.get("voice_id") or voice.get("id")
        if not voice_id:
            continue
        voices.append({
            "voice_id": str(voice_id),
            "name": str(voice.get("name") or "Voix") or "Voix",
            "gender": (str(voice.get("gender")).lower() if voice.get("gender") else None),
            "preview_audio_url": voice.get("preview_audio_url") or voice.get("preview_url"),
        })
    return voices


def create_avatar_video(
    look_id: str,
    script: str,
    voice_id: str,
    *,
    title: str | None = None,
    aspect_ratio: str = "9:16",
    resolution: str = "720p",
    engine: str = "avatar_iv",
) -> str:
    """Launch an avatar video render and return its video_id (async)."""
    text = (script or "").strip()
    if not text:
        raise HeygenError("Script vide : rien à faire dire à l'avatar.")
    if len(text) > MAX_SCRIPT_CHARS:
        raise HeygenError(f"Script trop long pour HeyGen ({len(text)} caractères, max {MAX_SCRIPT_CHARS}).")
    if not voice_id:
        raise HeygenError("Aucune voix sélectionnée pour l'avatar.")
    body: dict[str, Any] = {
        "type": "avatar",
        "avatar_id": look_id,
        "script": text,
        "voice_id": voice_id,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "engine": {"type": engine},
    }
    if title:
        body["title"] = title.strip()[:120]
    data = _request("POST", "/v3/videos", body=body, timeout=120)
    video_id = None
    if isinstance(data, dict):
        video_id = data.get("video_id") or data.get("id")
    if not video_id:
        raise HeygenError("Réponse HeyGen inattendue : pas de video_id.")
    return str(video_id)


def get_video(video_id: str) -> dict[str, Any]:
    """Return normalized video status: {status, video_url, duration, error}."""
    data = _request("GET", f"/v3/videos/{urllib.parse.quote(video_id)}")
    if not isinstance(data, dict):
        raise HeygenError("Réponse HeyGen inattendue sur le statut vidéo.")
    status = _normalize_status(data.get("status"))
    error = data.get("failure_message") or data.get("error")
    duration = data.get("duration")
    try:
        duration = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    return {
        "status": status,
        # Préférer la version sous-titrée si HeyGen l'expose (sous-titres
        # incrustés = norme des Reels) ; sinon la vidéo brute.
        "video_url": data.get("captioned_video_url") or data.get("video_url"),
        "thumbnail_url": data.get("thumbnail_url"),
        "duration": duration,
        "error": (str(error) if error else None),
    }


def download_video(url: str) -> bytes:
    """Download the finished video (pre-signed URL) with a hard size cap."""
    parsed = urllib.parse.urlparse(url or "")
    if parsed.scheme != "https" or not parsed.netloc:
        raise HeygenError("URL de vidéo HeyGen invalide.")
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = resp.read(MAX_VIDEO_DOWNLOAD_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise HeygenError(f"Téléchargement de la vidéo HeyGen échoué ({exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise HeygenError(f"Téléchargement de la vidéo HeyGen injoignable : {exc.reason}") from exc
    if not data:
        raise HeygenError("Vidéo HeyGen vide au téléchargement.")
    if len(data) > MAX_VIDEO_DOWNLOAD_BYTES:
        raise HeygenError("Vidéo HeyGen trop volumineuse pour être re-hébergée (100 Mo max).")
    return data
