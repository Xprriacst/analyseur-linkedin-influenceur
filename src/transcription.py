"""Transcription des notes vocales entrantes — Speech-to-Text (ALE-195 / 203).

Les prospects Instagram envoient souvent des **notes vocales**. ManyChat expose
l'URL du fichier audio (« Last Text Input » → External Request). Claude n'ingère
pas l'audio nativement : on transcrit via **OpenAI Whisper** (FR OK, ~0,006 $/min)
avant d'injecter le texte dans le même pipeline que les DM texte.

Réutilise `OPENAI_API_KEY` (déjà présent sur Render, cf. génération d'image).
Client stdlib pour le téléchargement (urllib), SDK OpenAI pour Whisper.
"""
from __future__ import annotations

import io
import ipaddress
import os
import socket
import urllib.request
from urllib.parse import urlparse

from openai import OpenAI

# Whisper accepte mp3/m4a/ogg/wav/webm… On déduit l'extension de l'URL, défaut mp3.
_AUDIO_EXTS = {"mp3", "m4a", "ogg", "oga", "wav", "webm", "mp4", "mpeg", "mpga", "flac"}
# Garde-fou taille : Whisper plafonne à 25 Mo par fichier.
_MAX_AUDIO_BYTES = 25 * 1024 * 1024


class TranscriptionError(RuntimeError):
    """Levée quand la transcription échoue ou n'est pas configurée."""


def enabled() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def _model() -> str:
    return os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Bloque tout suivi de redirection (un 3xx ne doit pas contourner la
    validation d'URL vers une cible interne — SSRF)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise TranscriptionError(f"Redirection audio refusée ({code} → {newurl}).")


# Opener SANS suivi de redirection.
_no_redirect_opener = urllib.request.build_opener(_NoRedirectHandler())


def _allowed_hosts() -> list[str]:
    """Suffixes de domaines autorisés (optionnel, via IG_AUDIO_ALLOWED_HOSTS)."""
    raw = os.environ.get("IG_AUDIO_ALLOWED_HOSTS", "")
    return [h.strip().lower() for h in raw.split(",") if h.strip()]


def _validate_url(url: str) -> None:
    """Garde-fou SSRF : https only, host non-privé, allowlist optionnelle.

    Le webhook est déjà authentifié (secret partagé) et l'URL vient de ManyChat,
    mais on ne fait pas confiance à une URL fournie de l'extérieur pour un fetch
    serveur : on refuse les schémas non-https et toute IP interne
    (loopback/privée/link-local/réservée). Redirections désactivées par ailleurs.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise TranscriptionError("URL audio refusée : https requis.")
    host = parsed.hostname or ""
    if not host:
        raise TranscriptionError("URL audio invalide : hôte manquant.")
    allow = _allowed_hosts()
    if allow and not any(host.lower() == h or host.lower().endswith("." + h) for h in allow):
        raise TranscriptionError("URL audio refusée : hôte hors allowlist.")
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise TranscriptionError(f"Résolution DNS échouée : {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise TranscriptionError("URL audio refusée : cible interne (SSRF).")


def _download(url: str) -> tuple[str, bytes]:
    """Télécharger l'audio → (filename, bytes). Valide l'URL (SSRF) et borne la taille."""
    _validate_url(url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "lkd-outreach/ig-agent"})
        with _no_redirect_opener.open(req, timeout=30) as resp:
            data = resp.read(_MAX_AUDIO_BYTES + 1)
    except TranscriptionError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise TranscriptionError(f"Téléchargement audio échoué : {exc}") from exc
    if not data:
        raise TranscriptionError("Fichier audio vide.")
    if len(data) > _MAX_AUDIO_BYTES:
        raise TranscriptionError("Fichier audio > 25 Mo (limite Whisper).")
    ext = urlparse(url).path.rsplit(".", 1)[-1].lower()
    if ext not in _AUDIO_EXTS:
        ext = "mp3"
    return (f"audio.{ext}", data)


def transcribe_audio_url(url: str, *, language: str = "fr") -> str:
    """Transcrire une note vocale depuis son URL → texte (français par défaut)."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise TranscriptionError("OPENAI_API_KEY manquant dans l'environnement serveur.")
    filename, data = _download(url)
    client = OpenAI(api_key=api_key)
    try:
        resp = client.audio.transcriptions.create(
            model=_model(),
            file=(filename, io.BytesIO(data)),
            language=language,
        )
    except Exception as exc:  # noqa: BLE001
        raise TranscriptionError(f"Transcription Whisper échouée : {exc}") from exc
    text = getattr(resp, "text", "") or ""
    return text.strip()
