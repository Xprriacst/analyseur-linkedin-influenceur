"""Garde-fou SSRF générique pour les téléchargements serveur de fichiers tiers.

Un serveur qui va chercher un fichier à une URL fournie par un tiers (webhook,
contenu saisi par un utilisateur, lien scrapé…) ne doit jamais faire confiance
à cette URL : elle pourrait cibler une adresse interne (SSRF). Réutilisé par
la transcription des notes vocales Instagram (`transcription.py`) et par le
téléchargement d'images de référence pour la génération d'image IA
(`image_gen.py`).
"""
from __future__ import annotations

import ipaddress
import os
import socket
import urllib.request
from urllib.parse import urlparse


class NetGuardError(RuntimeError):
    """Levée par défaut quand une URL est refusée ou son téléchargement échoue."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Bloque tout suivi de redirection (un 3xx ne doit pas contourner la
    validation d'URL vers une cible interne — SSRF)."""

    def __init__(self, error_cls: type[Exception]) -> None:
        self._error_cls = error_cls

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise self._error_cls(f"Redirection refusée ({code} → {newurl}).")


def _allowed_hosts(allowed_hosts_env: str | None) -> list[str]:
    """Suffixes de domaines autorisés (optionnel, via la variable d'env donnée)."""
    if not allowed_hosts_env:
        return []
    raw = os.environ.get(allowed_hosts_env, "")
    return [h.strip().lower() for h in raw.split(",") if h.strip()]


def validate_url(
    url: str,
    *,
    allowed_hosts_env: str | None = None,
    error_cls: type[Exception] = NetGuardError,
) -> None:
    """Garde-fou SSRF : https only, host non-privé, allowlist optionnelle.

    On ne fait pas confiance à une URL fournie par un tiers pour un fetch
    serveur : on refuse les schémas non-https et toute IP interne
    (loopback/privée/link-local/réservée). Redirections désactivées à part.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise error_cls("URL refusée : https requis.")
    host = parsed.hostname or ""
    if not host:
        raise error_cls("URL invalide : hôte manquant.")
    allow = _allowed_hosts(allowed_hosts_env)
    if allow and not any(host.lower() == h or host.lower().endswith("." + h) for h in allow):
        raise error_cls("URL refusée : hôte hors allowlist.")
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise error_cls(f"Résolution DNS échouée : {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise error_cls("URL refusée : cible interne (SSRF).")


def guarded_download(
    url: str,
    *,
    allowed_exts: set[str],
    default_ext: str,
    max_bytes: int,
    allowed_hosts_env: str | None = None,
    content_type_ext_map: dict[str, str] | None = None,
    error_cls: type[Exception] = NetGuardError,
    filename_stem: str = "file",
    user_agent: str = "lkd-outreach/net-guard",
    timeout: int = 30,
) -> tuple[str, bytes, str]:
    """Télécharger une URL tierce → (filename, bytes, content_type).

    Valide l'URL (cf. `validate_url`) et borne la taille. L'extension est
    déduite en priorité du header Content-Type de la réponse quand
    `content_type_ext_map` est fourni (les URLs signées type CDN n'ont
    souvent pas de suffixe de fichier dans le path), avec repli sur le
    suffixe de l'URL puis sur `default_ext`.
    """
    validate_url(url, allowed_hosts_env=allowed_hosts_env, error_cls=error_cls)
    opener = urllib.request.build_opener(_NoRedirectHandler(error_cls))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with opener.open(req, timeout=timeout) as resp:
            content_type = resp.headers.get_content_type() or ""
            data = resp.read(max_bytes + 1)
    except error_cls:
        raise
    except Exception as exc:  # noqa: BLE001
        raise error_cls(f"Téléchargement échoué : {exc}") from exc
    if not data:
        raise error_cls("Fichier vide.")
    if len(data) > max_bytes:
        raise error_cls(f"Fichier > {max_bytes // (1024 * 1024)} Mo (limite).")

    ext = (content_type_ext_map or {}).get(content_type.lower(), "")
    if not ext:
        path = urlparse(url).path
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if ext not in allowed_exts:
        ext = default_ext
    return (f"{filename_stem}.{ext}", data, content_type or f"application/{ext}")
