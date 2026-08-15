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

Endpoints v3 supplémentaires pour le Digital Twin (même `POST /v3/avatars`,
`type: "digital_twin"` — entraîné sur une vidéo au lieu d'une photo, doc
publique HeyGen sur les digital twins) :
- POST /v3/avatars               (type "digital_twin" : vidéo d'entraînement)
- POST /v3/avatars/{group_id}/consent  (demande d'un lien de consentement)
- GET  /v3/avatars/{group_id}/consent  (statut du consentement)

⚠️ Ces 3 derniers appels n'ont JAMAIS été exécutés contre la vraie API HeyGen
(HEYGEN_API_KEY n'est accessible ni en local ni via les MCP de cette session)
— endpoints, noms de champs et statuts sont déduits de la doc publique HeyGen
sur les digital twins et calqués sur le patron déjà vérifié du photo avatar.
À confirmer au premier test réel (Alex, compte HeyGen configuré). Le
consentement d'un digital twin se fait sur une page hébergée par HeyGen
(webcam), lien valable ~24h : uploader une vidéo de consentement déjà
enregistrée depuis notre propre tunnel est réservé aux comptes HeyGen
Enterprise — hors de portée ici, d'où le renvoi vers leur page hébergée.

Uses stdlib urllib to avoid adding an HTTP dependency (matches zernio.py).
"""
from __future__ import annotations

import base64
import binascii
import datetime
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BASE_URL = "https://api.heygen.com"

# Types d'avatar supportés par POST /v3/avatars (champ `type`).
AVATAR_TYPE_PHOTO = "photo"
AVATAR_TYPE_DIGITAL_TWIN = "digital_twin"

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
        "type": AVATAR_TYPE_PHOTO,
        "name": (name or "Avatar").strip()[:120] or "Avatar",
        "file": _file_payload(image_source),
    }
    data = _request("POST", "/v3/avatars", body=body, timeout=120)
    return _normalize_avatar(data if isinstance(data, dict) else {})


def get_avatar_look(look_id: str) -> dict[str, Any]:
    """Return the training status of an avatar look (photo or digital twin,
    once consent has been given for the latter)."""
    data = _request("GET", f"/v3/avatars/looks/{urllib.parse.quote(look_id)}")
    return _normalize_avatar(data if isinstance(data, dict) else {})


def _video_url_payload(video_source: str) -> dict[str, Any]:
    """Build the `file` field of POST /v3/avatars for a digital twin.

    Volontairement URL-only (pas de branche `data:` comme pour la photo) : un
    clip d'entraînement de 2 min en 720p+ ferait plusieurs dizaines de Mo en
    base64 dans un body JSON — la vidéo est TOUJOURS déjà hébergée (Zernio, via
    `POST /me/avatar/digital-twin/video` côté API) avant d'arriver ici, même
    logique que les images de référence/reels (net_guard, zernio) : jamais de
    gros binaire non borné dans le process web.
    """
    source = (video_source or "").strip()
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HeygenError(
            "Vidéo d'entraînement invalide : URL publique https attendue (upload-la d'abord)."
        )
    return {"type": "url", "url": source}


def create_digital_twin_avatar(name: str, video_source: str) -> dict[str, Any]:
    """Create a digital twin avatar (Avatar IV) from a training video.

    `video_source` : URL publique https (vidéo déjà hébergée — cf.
    `_video_url_payload`). HeyGen recommande ≥2 min de plan continu, sans
    coupe, en 720p ou plus — rien de tout cela n'est vérifiable côté serveur
    sans décoder la vidéo (hors périmètre) : un footage trop court/coupé se
    solde simplement par un statut `failed` à l'entraînement, revu par le
    client via un nouvel upload.

    ⚠️ Contrairement au photo avatar, la création NE lance PAS l'entraînement :
    HeyGen exige un consentement filmé au préalable (`request_avatar_consent`).
    Le `status` renvoyé ici précède donc ce consentement — l'appelant doit
    l'écraser par son propre état `pending_consent` plutôt que de le prendre
    au pied de la lettre (cf. `api.py::me_avatar_digital_twin_create`).
    """
    body = {
        "type": AVATAR_TYPE_DIGITAL_TWIN,
        "name": (name or "Avatar").strip()[:120] or "Avatar",
        "file": _video_url_payload(video_source),
    }
    data = _request("POST", "/v3/avatars", body=body, timeout=180)
    return _normalize_avatar(data if isinstance(data, dict) else {})


def request_avatar_consent(group_id: str) -> dict[str, Any]:
    """Ask HeyGen for a hosted consent-recording link for a digital twin group.

    Renvoie `{consent_url, expires_at}` — page hébergée par HeyGen (webcam),
    valable ~24h d'après leur doc publique. Peut être rappelée à volonté pour
    renouveler un lien expiré (le groupe d'avatar, lui, n'est pas recréé).
    """
    if not (group_id or "").strip():
        raise HeygenError("Identifiant de groupe d'avatar manquant pour la demande de consentement.")
    data = _request("POST", f"/v3/avatars/{urllib.parse.quote(group_id)}/consent", body={})
    if not isinstance(data, dict):
        raise HeygenError("Réponse HeyGen inattendue pour la demande de consentement.")
    consent_url = data.get("consent_url") or data.get("url") or data.get("link")
    if not consent_url:
        raise HeygenError("Réponse HeyGen inattendue : pas de lien de consentement.")
    return {
        "consent_url": str(consent_url),
        "expires_at": data.get("expires_at") or data.get("expire_at") or data.get("expiry"),
    }


_CONSENT_GIVEN_STATUSES = {"given", "granted", "approved", "completed", "confirmed", "success"}
_CONSENT_EXPIRED_STATUSES = {"expired", "timeout", "timed_out"}


def get_avatar_consent_status(group_id: str) -> dict[str, Any]:
    """Read the current consent status for a digital twin group.

    Statut normalisé en `pending` | `given` | `expired`. Toute valeur inconnue
    ou schéma inattendu retombe sur `pending` (fail-safe : mieux vaut re-poller
    au prochain passage que déclarer à tort un consentement acquis ou expiré —
    l'expiration réelle des 24h est de toute façon recoupée côté appelant avec
    l'horodatage local `expires_at`, indépendamment de ce que renvoie ce statut).
    """
    if not (group_id or "").strip():
        raise HeygenError("Identifiant de groupe d'avatar manquant pour lire le consentement.")
    data = _request("GET", f"/v3/avatars/{urllib.parse.quote(group_id)}/consent")
    raw_status = str((data or {}).get("status") or "").strip().lower() if isinstance(data, dict) else ""
    if raw_status in _CONSENT_GIVEN_STATUSES:
        status = "given"
    elif raw_status in _CONSENT_EXPIRED_STATUSES:
        status = "expired"
    else:
        status = "pending"
    return {
        "status": status,
        "consent_url": (data.get("consent_url") if isinstance(data, dict) else None),
        "expires_at": (data.get("expires_at") if isinstance(data, dict) else None),
    }


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


def is_consent_expired(expires_at: Any) -> bool:
    """True when a digital-twin consent link has passed its known deadline.

    Calculée localement (indépendante d'un rappel HeyGen) : les ~24h de
    validité sont une contrainte documentée et non négociable côté produit —
    mieux vaut l'appliquer nous-mêmes dès qu'on connaît l'échéance que de
    rester bloqué en attendant que l'API le confirme (best-effort côté
    appelant : `get_avatar_consent_status` reste tenté en complément).
    Absence/format inattendu ⇒ False (fail open sur l'affichage seulement —
    ça n'affecte que l'étiquette « expiré », jamais un accès).

    Extraite en fonction pure (testable sans FastAPI/réseau) plutôt que laissée
    en ligne dans l'endpoint, patron `outreach_engine`/`outreach_autopilot`
    (décide/exécute séparés) déjà en place ailleurs dans ce dépôt.
    """
    if not expires_at:
        return False
    try:
        exp_dt = datetime.datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    return exp_dt < datetime.datetime.now(datetime.timezone.utc)


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
