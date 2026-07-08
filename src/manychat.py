"""Thin ManyChat API client — transport DM Instagram (ALE-201).

ManyChat sert de tuyau conforme entre les DM Instagram et notre backend :
- entrant : ManyChat pousse un DM (action « External Request ») vers notre webhook ;
- sortant : on renvoie du texte au prospect via l'API ManyChat (`sendContent`).

Le cerveau (Claude), le garde-fou et le mode supervisé/autopilot vivent dans NOTRE
code — ManyChat ne fait que transporter. Texte uniquement (l'agent répond en texte ;
les vocaux entrants sont transcrits côté 203).

Contraintes de la voie conforme Meta/ManyChat :
- fenêtre de réponse **24 h** après le dernier message du prospect ;
- quota **~200 msg/h/compte** → petit throttle en mémoire + backoff sur 429/5xx.

Utilise urllib (stdlib) pour ne pas ajouter de dépendance HTTP (comme zernio.py).
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from typing import Any

# Extensions de fichiers audio que ManyChat peut pousser pour une note vocale IG.
# ManyChat range l'URL du fichier audio dans « Last Text Input » (le même champ que
# le texte) — les vocaux Instagram sortent en .ogg, on garde les autres par sûreté.
_AUDIO_URL_EXTS = {"ogg", "oga", "mp3", "m4a", "wav", "webm", "mpeg", "mpga", "flac"}

# Pièces jointes de la messagerie Meta (Instagram/Messenger). Une note vocale IG
# arrive sous cette forme, **sans extension dans le path** : l'identifiant est dans
# la query (`?asset_id=…&signature=…`) et le vrai nom (`audioclip-….ogg`) n'est que
# dans l'en-tête Content-Disposition à la récupération. On la reconnaît donc à
# l'hôte + un marqueur de chemin, pas à l'extension.
_META_ATTACHMENT_HOST = "fbsbx.com"
_META_ATTACHMENT_MARKERS = ("messaging_cdn", "attachment")

# Base API ManyChat. Surchargeable par env si le compte utilise un autre host.
BASE_URL = os.environ.get("MANYCHAT_BASE_URL", "https://api.manychat.com").rstrip("/")

# Fenêtre de réponse conforme (Meta) : 24 h après le dernier message entrant.
RESPONSE_WINDOW_SECONDS = 24 * 3600

# Quota indicatif ~200 msg/h/compte. On se garde une marge (180) et on lisse.
_MAX_SENDS_PER_HOUR = int(os.environ.get("MANYCHAT_MAX_SENDS_PER_HOUR", "180"))
_RATE_WINDOW_SECONDS = 3600

# Backoff sur erreurs transitoires (429 / 5xx).
_MAX_RETRIES = 4
_BASE_BACKOFF_SECONDS = 1.5

_send_times: deque[float] = deque()
_send_lock = threading.Lock()


class ManyChatError(RuntimeError):
    """Levée quand l'API ManyChat renvoie une erreur ou n'est pas configurée."""


def enabled() -> bool:
    """True si un token ManyChat global est configuré (compte propriétaire/legacy).

    En multi-client, chaque utilisateur fournit SA clé (cf. `send_text(api_token=…)`) ;
    ce global sert de repli pour le compte propriétaire mono-compte historique.
    """
    return bool(os.environ.get("MANYCHAT_API_TOKEN"))


def _api_token(api_token: str | None = None) -> str:
    """Token à utiliser : celui fourni (clé du client) sinon le global d'environnement."""
    token = api_token or os.environ.get("MANYCHAT_API_TOKEN")
    if not token:
        raise ManyChatError("Aucune clé API ManyChat (ni utilisateur ni globale).")
    return token


def _throttle() -> None:
    """File d'envoi simple : bloque tant qu'on dépasse le quota horaire.

    Fenêtre glissante d'une heure en mémoire (par process). Suffisant pour le
    volume v1 (un compte, envois déclenchés à la main en supervisé). Si le volume
    monte franchement, remplacer par une vraie file persistée.
    """
    with _send_lock:
        now = time.monotonic()
        while _send_times and now - _send_times[0] >= _RATE_WINDOW_SECONDS:
            _send_times.popleft()
        if len(_send_times) >= _MAX_SENDS_PER_HOUR:
            wait = _RATE_WINDOW_SECONDS - (now - _send_times[0])
            if wait > 0:
                time.sleep(min(wait, _RATE_WINDOW_SECONDS))
            now = time.monotonic()
            while _send_times and now - _send_times[0] >= _RATE_WINDOW_SECONDS:
                _send_times.popleft()
        _send_times.append(time.monotonic())


def _request(method: str, path: str, *, body: dict | None = None, api_token: str | None = None) -> Any:
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    token = _api_token(api_token)
    last_error: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            status = exc.code
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            # 429 / 5xx = transitoire → backoff exponentiel puis retry.
            if status == 429 or 500 <= status < 600:
                last_error = ManyChatError(f"ManyChat {status}: {detail[:300]}")
                time.sleep(_BASE_BACKOFF_SECONDS * (2 ** attempt))
                continue
            raise ManyChatError(f"ManyChat {status}: {detail[:300]}") from exc
        except urllib.error.URLError as exc:
            last_error = ManyChatError(f"ManyChat injoignable: {exc}")
            time.sleep(_BASE_BACKOFF_SECONDS * (2 ** attempt))
            continue
    raise last_error or ManyChatError("ManyChat: échec après plusieurs tentatives.")


def send_text(subscriber_id: str, text: str, *, api_token: str | None = None) -> dict:
    """Envoyer un message texte à un prospect via ManyChat (`sendContent`).

    `subscriber_id` = identifiant ManyChat du prospect (stocké en
    `ig_conversations.prospect_id`). `api_token` = clé du client (multi-client) ;
    sinon repli sur la clé globale. Respecte le throttle horaire + backoff.
    """
    text = (text or "").strip()
    if not text:
        raise ManyChatError("Message vide : rien à envoyer.")
    _throttle()
    payload = {
        "subscriber_id": subscriber_id,
        "data": {
            "version": "v2",
            "content": {
                # Sans `type`, ManyChat cible Facebook Messenger par défaut — or nos
                # prospects sont des DM Instagram (le canal Messenger n'existe pas
                # pour eux → l'envoi est rejeté).
                "type": os.environ.get("MANYCHAT_CHANNEL", "instagram"),
                "messages": [{"type": "text", "text": text}],
            },
        },
    }
    # Meta a supprimé les message tags (ManyChat renvoie 400 si on en envoie un).
    # On répond dans la fenêtre 24 h, qui n'exige aucun tag. `MANYCHAT_MESSAGE_TAG`
    # reste honorée si explicitement définie (secours si l'API réintroduit un mécanisme).
    tag = os.environ.get("MANYCHAT_MESSAGE_TAG", "").strip()
    if tag:
        payload["message_tag"] = tag
    return _request("POST", "/fb/sending/sendContent", body=payload, api_token=api_token)


def validate_token(api_token: str) -> dict:
    """Vérifier qu'une clé API ManyChat est valide en appelant `getInfo`.

    Renvoie les infos de page côté ManyChat, ou lève `ManyChatError` si la clé
    est invalide/refusée (401/403) — utilisé au moment où le client relie son
    compte, pour attraper une faute de frappe plutôt que d'échouer au 1er envoi.
    """
    token = (api_token or "").strip()
    if not token:
        raise ManyChatError("Clé API ManyChat vide.")
    return _request("GET", "/fb/page/getInfo", api_token=token)


def _looks_like_media_url(value: str) -> bool:
    """True si `value` est une URL http(s) vers une pièce jointe / un fichier audio.

    Cas ManyChat Instagram : une note vocale arrive avec l'URL du fichier
    **dans le champ « Last Text Input »** (ManyChat n'a pas de champ dédié pour
    l'audio entrant). Deux formes reconnues, sans confondre avec un lien texte
    que le prospect aurait tapé (qui n'est ni un CDN Meta, ni un fichier audio) :
      1. l'URL signée d'une pièce jointe de la messagerie Meta (sans extension) ;
      2. une URL directe avec extension audio explicite (autres middlewares).
    """
    value = (value or "").strip()
    if " " in value or not value.lower().startswith(("http://", "https://")):
        return False
    parsed = urllib.parse.urlparse(value)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if host.endswith(_META_ATTACHMENT_HOST) and any(m in path for m in _META_ATTACHMENT_MARKERS):
        return True
    ext = path.rsplit(".", 1)[-1] if "." in path else ""
    return ext in _AUDIO_URL_EXTS


def parse_inbound(payload: dict) -> dict:
    """Normaliser un webhook entrant ManyChat en champs exploités par le backend.

    ManyChat (« External Request ») est entièrement configurable côté flow : on
    accepte plusieurs alias de clés pour rester robuste à la façon dont le champ
    est mappé. Renvoie {prospect_id, prospect_name, text, audio_url}.
    `text` OU `audio_url` peut être vide ; l'appelant décide (203 gère l'audio).

    Note vocale : ManyChat pousse l'URL du fichier audio dans « Last Text Input »
    (donc dans `text`). Si `text` est une URL de pièce jointe / audio et qu'aucun
    `audio_url` dédié n'est fourni, on la bascule vers `audio_url` → transcription
    au lieu d'afficher l'URL brute comme un message texte (et de laisser l'IA y
    répondre comme si c'était un vrai message).
    """
    payload = payload or {}

    def _first(*keys: str) -> str:
        for key in keys:
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""

    prospect_id = _first(
        "subscriber_id", "subscriberId", "prospect_id", "id", "user_id", "psid"
    )
    prospect_name = _first("name", "prospect_name", "first_name", "full_name")
    text = _first("text", "last_text_input", "lastTextInput", "message", "last_input_text")
    audio_url = _first("audio_url", "audioUrl", "voice_url", "attachment_url", "file_url")

    if not audio_url and _looks_like_media_url(text):
        audio_url = text
        text = ""

    return {
        "prospect_id": prospect_id,
        "prospect_name": prospect_name,
        "text": text,
        "audio_url": audio_url,
    }
