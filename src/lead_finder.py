"""Prospection LinkedIn (ALE-227) : commentateurs d'un post lead-magnet.

Un commentaire sous un post « commente X pour recevoir le guide » est un signal
d'intention chaud : on récupère les commentateurs d'un post concurrent via
l'actor Apify `harvestapi/linkedin-post-comments` (no-cookies, même éditeur que
le scraper de posts, ~0,002 $/commentaire en mode `short`). Chaque commentateur
devient un lead : nom, intitulé de poste, URL de profil, texte du commentaire.

Le verdict « lead magnet ou non » est rendu par le LLM (`llm.classify_lead_magnet`) ;
`looks_like_lead_magnet` sert de pré-filtre gratuit côté veille pour ne pas payer
un appel LLM sur chaque nouveau post scrapé.
"""
from __future__ import annotations

import os
import re
from typing import Any

from src import actor_health
from src.scraper import _call_actor, _client, _default_dataset_id
from src.usage import track_apify


COMMENTS_ACTOR = "harvestapi/linkedin-post-comments"

# Garde-fous coût : on borne le nombre de commentaires scrappés par collecte
# pour éviter une facture Apify surprise sur un post à des dizaines de milliers
# de commentaires. Depuis ALE-240, l'utilisateur choisit le volume au curseur
# (avec le coût en crédits affiché) et la collecte tourne en tâche de fond — le
# vrai garde-fou est donc le pré-check du solde, pas ce plafond. On le garde haut
# comme filet anti-emballement (post viral à 50k commentaires).
MAX_ITEMS_CAP = 5000
DEFAULT_MAX_ITEMS = 100

# Pré-filtre gratuit pour la veille : un CTA lead-magnet mentionne toujours le
# commentaire ("commente CLOUD", "écris GUIDE en commentaire", "comment below").
# Volontairement large — le verdict final revient au LLM.
_COMMENT_CTA_RE = re.compile(r"\bcomment", re.IGNORECASE)


def looks_like_lead_magnet(text: str | None) -> bool:
    """Pré-filtre heuristique : le post peut-il être un lead magnet ?"""
    return bool(text and _COMMENT_CTA_RE.search(text))


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

    actor = os.environ.get("APIFY_COMMENTS_ACTOR", COMMENTS_ACTOR)
    run_input = {
        "posts": [post_url],
        "maxItems": max_items,
        "postedLimit": "any",
        "scrapeReplies": False,
        "profileScraperMode": "short",
    }
    # Timeout large : la collecte tourne en tâche de fond (ALE-240) et un gros
    # volume (milliers de commentaires) prend plusieurs minutes côté Apify.
    try:
        run = _call_actor(actor, run_input, timeout_secs=1500)
        items = list(_client().dataset(_default_dataset_id(run)).iterate_items())
    except Exception as exc:
        actor_health.record_call(
            actor, ok=False, error=str(exc), context="fetch_post_commenters"
        )
        raise
    track_apify(actor, len(items), cached=False)

    leads: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        lead = _commenter_from_item(item)
        if not lead:
            continue
        # Dédup par profil (une même personne peut commenter plusieurs fois).
        key = lead.get("profile_url") or lead.get("name") or ""
        if key in seen:
            continue
        seen.add(key)
        leads.append(lead)

    leads.sort(key=lambda l: l.get("reaction_count") or 0, reverse=True)
    # Ce post a passé le pré-filtre `looks_like_lead_magnet` (un CTA à
    # commenter) — 0 lead ramené alors qu'on en attend est le symptôme exact
    # de l'incident #407 (run "réussi", résultat vide) : signalé sans lever.
    actor_health.record_call(
        actor,
        ok=True,
        item_count=len(leads),
        expected_min_items=1,
        context="fetch_post_commenters",
    )
    return leads


# Facturation de la collecte (ALE-239) : l'appel Apify est payant (~0,002 $/
# commentaire). On débite proportionnellement au volume RÉELLEMENT récupéré. Au
# calibrage actuel (~0,006 $/crédit) 3 commentateurs ≈ 1 crédit couvre le coût.
LEAD_COMMENTERS_PER_CREDIT = 3


def lead_collect_credit_cost(n_commenters: int) -> int:
    """Crédits à débiter pour une collecte, proportionnels au volume (min 1)."""
    n = max(0, int(n_commenters))
    if n == 0:
        return 0
    return max(1, (n + LEAD_COMMENTERS_PER_CREDIT - 1) // LEAD_COMMENTERS_PER_CREDIT)


def effective_max_comments(requested: int | None, allow_volume: bool) -> int:
    """Volume effectif d'une collecte (ALE-240).

    Le choix du volume (curseur >100) est en bêta, réservé aux comptes portant le
    flag `lead_volume`. Sans le flag, on plafonne au défaut (100) — le gating n'est
    PAS que cosmétique : un compte non concerné qui appellerait l'endpoint avec un
    gros `max_comments` reste borné côté serveur.
    """
    n = int(requested or DEFAULT_MAX_ITEMS)
    if not allow_volume:
        n = min(n, DEFAULT_MAX_ITEMS)
    return max(1, n)


def _score_leads_for_source(access_token: str, source: dict, counts: dict) -> None:
    """Note (ICP) les leads fraîchement touchés par une collecte, si un ciblage
    est configuré. Best-effort : un échec de scoring ne casse pas la collecte."""
    from src import db
    from src.llm import score_leads

    ids_by_url = (counts or {}).get("ids_by_url") or {}
    if not ids_by_url:
        return
    targeting = db.get_lead_targeting(access_token)
    if not targeting:
        return  # pas de ciblage → on n'invente pas de score (tous les leads restent visibles)
    try:
        leads = db.list_leads_for_scoring(access_token)
        by_id = {l["id"]: l for l in leads}
        to_score = [by_id[lid] for lid in ids_by_url.values() if lid in by_id]
        lead_inputs = [
            {
                "headline": l.get("headline"),
                "comment_text": l.get("comment_text"),
                "trigger_keyword": (source or {}).get("trigger_keyword"),
                "author": (source or {}).get("author"),
            }
            for l in to_score
        ]
        scores = score_leads(targeting, lead_inputs, source_post_text=(source or {}).get("post_text"))
        scored = [
            {"id": l["id"], "score": s.get("score"), "reason": s.get("reason")}
            for l, s in zip(to_score, scores)
        ]
        db.update_lead_scores(access_token, scored)
    except Exception as exc:  # noqa: BLE001
        print(f"[leads] scoring à l'ingestion échoué : {exc}", flush=True)


def collect_and_persist(
    access_token: str, source: dict, max_comments: int
) -> dict[str, Any]:
    """Scrape les commentateurs d'une source, persiste les leads dédupliqués,
    les note (ICP) et met à jour la source. Débite les crédits proportionnellement
    au volume RÉELLEMENT récupéré (jamais plus que demandé).

    Ne fait PAS le pré-check du solde : il est fait à la création du job (le débit
    réel est toujours <= au pire cas pré-vérifié, donc il ne peut pas échouer
    après avoir payé le scrape). Zéro commentateur récupéré = zéro débit.

    Retourne {comments_count, leads, credits}. Lève sur échec réseau/actor.
    """
    from datetime import datetime, timezone
    from src import db

    commenters = fetch_post_commenters(source["post_url"], max_items=max_comments)
    credits_balance: int | None = None
    if commenters:
        # ok toujours True : le pré-check garantit solde >= coût du pire cas >= coût réel.
        _ok, credits_balance = db.debit_credits(
            access_token, "collect_leads", lead_collect_credit_cost(len(commenters))
        )
    counts = db.save_leads(access_token, source, commenters)
    _score_leads_for_source(access_token, source, counts)
    db.update_lead_source(
        access_token,
        source["id"],
        {
            "comments_count": len(commenters),
            "collected_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    print(
        f"[leads] source {source['id']} ({source['post_url']}): "
        f"{len(commenters)} commentaire(s) récupéré(s), leads {counts}",
        flush=True,
    )
    # `counts` porte `ids_by_url` (interne au scoring) — on ne l'expose pas au job.
    public_counts = {k: v for k, v in (counts or {}).items() if k != "ids_by_url"}
    return {
        "comments_count": len(commenters),
        "leads": public_counts,
        "credits": credits_balance,
    }
