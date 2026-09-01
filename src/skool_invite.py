"""Lien d'invitation Skool du groupe privé (missions + stratégies d'acquisition).

Le groupe vit **hors Cibl** : Cibl vend l'accès, le cercle se présente comme
un groupe freelance. Le lien n'est **jamais** rendu sur la page de vente
publique — seulement à un compte authentifié (`GET /pilote/invite`).

Sans `SKOOL_INVITE_URL`, `invite_url()` vaut `None` : pas de bouton mort.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse


def invite_url() -> str | None:
    """URL https d'invitation, ou None si absente / non https.

    `javascript:` et `http://` sont refusés : ce lien s'ouvre dans le
    navigateur du nouvel inscrit. Une valeur malformée se comporte comme
    une variable absente (pas de bouton), jamais comme un href dangereux.
    """
    raw = (os.environ.get("SKOOL_INVITE_URL") or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return raw
