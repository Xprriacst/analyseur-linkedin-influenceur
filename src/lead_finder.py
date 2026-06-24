"""Lead finder : détection de signaux d'intention sur LinkedIn.

MVP — on récupère les personnes qui ont commenté un post donné (commenter =
signal d'intention chaud) via l'actor Apify `harvestapi/linkedin-post-comments`
(no-cookies, même éditeur que le scraper de posts). Chaque commentateur devient
un lead : nom, accroche/poste, URL de profil, texte du commentaire, date.

Pas de compte LinkedIn requis. Coût ~0,002 $/commentaire (mode `short`).
"""
from __future__ import annotations

import os
from typing import Any

from src.scraper import _call_actor, _client, _default_dataset_id
from src.usage import track_apify


COMMENTS_ACTOR = "harvestapi/linkedin-post-comments"

# Garde-fous : on borne le nombre de commentaires scrappés par recherche pour
# éviter une facture Apify surprise sur un post à des milliers de commentaires.
MAX_ITEMS_CAP = 500
DEFAULT_MAX_ITEMS = 50


def _commenter_from_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Normalise un item de l'actor en lead. Retourne None si pas exploitable.

    L'auteur du commentaire est dans `actor` (name/linkedinUrl/position) ;
    le texte dans `commentary`, l'horodatage dans `createdAt`, et les likes
    reçus par le commentaire dans `engagement.likes`.
    """
    actor = item.get("actor") or {}
    profile_url = (actor.get("linkedinUrl") or "").strip()
    name = (actor.get("name") or "").strip()
    if not profile_url and not name:
        return None  # item d'erreur / vide

    engagement = item.get("engagement") or {}
    likes = engagement.get("likes")
    if likes is None:
        # fallback : somme des compteurs de réactions s'il n'y a pas de `likes`
        likes = sum(r.get("count", 0) or 0 for r in engagement.get("reactions") or [])

    return {
        "name": name or None,
        "headline": (actor.get("position") or "").strip() or None,
        "profile_url": profile_url or None,
        "comment_text": (item.get("commentary") or "").strip() or None,
        "commented_at": item.get("createdAt"),
        "reaction_count": int(likes or 0),
    }


def fetch_post_commenters(
    post_url: str, max_items: int = DEFAULT_MAX_ITEMS
) -> list[dict[str, Any]]:
    """Récupère les commentateurs d'un post LinkedIn, dédupliqués par profil.

    Retourne une liste de leads normalisés (cf. `_commenter_from_item`), triés
    par engagement décroissant (commentaires les plus likés d'abord).
    """
    post_url = (post_url or "").strip()
    if not post_url:
        return []
    max_items = max(1, min(int(max_items or DEFAULT_MAX_ITEMS), MAX_ITEMS_CAP))

    run_input = {
        "posts": [post_url],
        "maxItems": max_items,
        "postedLimit": "any",
        "scrapeReplies": False,
        "profileScraperMode": "short",
    }
    run = _call_actor(COMMENTS_ACTOR, run_input, timeout_secs=300)
    items = list(_client().dataset(_default_dataset_id(run)).iterate_items())
    track_apify(COMMENTS_ACTOR, len(items), cached=False)

    leads: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        lead = _commenter_from_item(item)
        if not lead:
            continue
        # Dédup par profil (un même profil peut commenter plusieurs fois).
        key = lead.get("profile_url") or lead.get("name") or ""
        if key in seen:
            continue
        seen.add(key)
        leads.append(lead)

    leads.sort(key=lambda l: l.get("reaction_count") or 0, reverse=True)
    return leads


def commenters_actor_available() -> bool:
    """True si Apify est configuré (token présent)."""
    return bool(os.environ.get("APIFY_TOKEN"))
