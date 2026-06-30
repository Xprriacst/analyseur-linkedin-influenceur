"""Outreach Engagement Hunter — cron de détection de leads LinkedIn.

Entrypoint : python -m src.outreach_detector
Schedule conseillé : 0 6 * * *  (une fois par jour, 6h UTC)

Pour chaque utilisateur ayant des mots-clés actifs :
  1. Apify harvestapi/linkedin-post-search → upsert monitored_posts
  2. Pour chaque post (si engagers non récupérés depuis 24h) :
     Apify scraping_solutions/linkedin-posts-engagers → insert outreach_leads
  3. Mise à jour des stats du keyword (last_run_at, leads_found_total)

Aucun envoi, aucune IA — détection pure, zéro risque de ban.
"""
from __future__ import annotations

import datetime
import logging
import os
import sys

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


# ── Actors Apify ────────────────────────────────────────────────────────────

POSTS_SEARCH_ACTOR = "harvestapi/linkedin-post-search"
ENGAGERS_ACTOR = (
    "scraping_solutions/linkedin-posts-engagers-likers-and-commenters-no-cookies"
)

# Mapping date_posted (DB) → postedLimit (Apify input)
_DATE_POSTED_MAP = {
    "past_24h": "24h",
    "past_week": "week",
    "past_month": "month",
}


def _apify_client():
    try:
        from apify_client import ApifyClient
    except ImportError:
        logger.error("apify_client non installé")
        return None
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        logger.error("APIFY_TOKEN manquant")
        return None
    return ApifyClient(token)


def _run_actor(client, actor: str, run_input: dict, timeout_secs: int = 300) -> list[dict]:
    """Lance un actor Apify et retourne les items du dataset."""
    try:
        run = client.actor(actor).call(run_input=run_input, timeout_secs=timeout_secs)
        if not run or run.get("status") != "SUCCEEDED":
            logger.warning("Actor %s terminé avec statut %s", actor, run and run.get("status"))
            return []
        dataset_id = run.get("defaultDatasetId")
        if not dataset_id:
            return []
        items = list(
            client.dataset(dataset_id).iterate_items()
        )
        return items
    except Exception as exc:
        logger.error("Actor %s erreur : %s", actor, exc)
        return []


# ── Normalisation ────────────────────────────────────────────────────────────

def _extract_author_id(item: dict) -> str | None:
    """Extraire le slug LinkedIn de l'auteur."""
    author = item.get("author") or {}
    pid = author.get("publicIdentifier")
    if pid:
        return pid
    url = author.get("url") or ""
    import re
    m = re.search(r"/in/([^/?#]+)", url)
    return m.group(1) if m else None


def _normalize_post(item: dict, keyword_id: str, user_id: str) -> dict:
    social_id = (
        item.get("shareUrn")
        or item.get("entityId")
        or item.get("id")
        or item.get("linkedinUrl")
        or ""
    )
    author = item.get("author") or {}
    engagement = item.get("engagement") or {}
    posted_at = (item.get("postedAt") or {}).get("date")
    return {
        "user_id": user_id,
        "social_id": social_id,
        "share_url": item.get("linkedinUrl"),
        "text_content": (item.get("content") or "")[:5000],
        "author_public_id": _extract_author_id(item),
        "author_name": author.get("name"),
        "author_headline": author.get("info"),
        "author_is_company": author.get("type") == "company",
        "reaction_counter": engagement.get("likes", 0) or 0,
        "comment_counter": engagement.get("comments", 0) or 0,
        "parsed_datetime": posted_at,
        "monitored_keyword_id": keyword_id,
    }


def _normalize_lead(item: dict, keyword_id: str, post_id: str, keyword_text: str, user_id: str) -> dict:
    name = item.get("name") or ""
    parts = name.split(" ", 1)
    return {
        "user_id": user_id,
        "name": name,
        "first_name": parts[0] if parts else None,
        "last_name": parts[1] if len(parts) > 1 else None,
        "headline": item.get("subtitle"),
        "linkedin_profile_url": item.get("url_profile") or "",
        "signal": "engaged-content",
        "signal_text": f'A liké un post sur « {keyword_text} »',
        "score": 2,
        "status": "to-validate",
        "engagement_type": "reaction",
        "monitored_keyword_id": keyword_id,
        "source_post_id": post_id,
    }


# ── Détection par keyword ────────────────────────────────────────────────────

def _process_keyword(client, keyword: dict, user_id: str) -> tuple[int, int]:
    """Traite un mot-clé actif : recherche posts + engagers → leads.

    Retourne (posts_count, leads_count) pour la mise à jour des stats.
    """
    from src import db

    keyword_id = keyword["id"]
    keyword_text = keyword["keyword"]
    date_posted = keyword.get("date_posted", "past_week")
    sort_by = keyword.get("sort_by", "date")

    # 1. Recherche des posts LinkedIn
    posts_input = {
        "searchQueries": [keyword_text],
        "sortBy": sort_by,
        "postedLimit": _DATE_POSTED_MAP.get(date_posted, "week"),
    }
    raw_posts = _run_actor(client, POSTS_SEARCH_ACTOR, posts_input)
    if not raw_posts:
        logger.info("Keyword «%s» : aucun post trouvé", keyword_text)
        return 0, 0

    posts_count = 0
    leads_count = 0

    for raw in raw_posts:
        row = _normalize_post(raw, keyword_id, user_id)
        if not row["social_id"]:
            continue

        # Upsert du post (dedup par user_id + social_id)
        saved = db.upsert_monitored_post(user_id, row)
        if not saved:
            continue
        posts_count += 1
        post_id = saved["id"]

        # 2. Engagers — skip si récupérés il y a moins de 24h
        fetched_at_str = saved.get("engagers_fetched_at")
        if fetched_at_str:
            try:
                fetched_at = datetime.datetime.fromisoformat(
                    fetched_at_str.replace("Z", "+00:00")
                )
                age = datetime.datetime.now(datetime.timezone.utc) - fetched_at
                if age.total_seconds() < 86400:
                    continue
            except Exception:
                pass

        share_url = saved.get("share_url") or ""
        if not share_url:
            continue

        engagers_input = {
            "url": share_url,
            "type": "likers",
            "start": 0,
            "iterations": 5,
        }
        engagers = _run_actor(client, ENGAGERS_ACTOR, engagers_input, timeout_secs=120)
        db.mark_post_engagers_fetched(post_id, len(engagers))

        for eng in engagers:
            url_profile = eng.get("url_profile") or ""
            if not url_profile:
                continue
            lead_row = _normalize_lead(eng, keyword_id, post_id, keyword_text, user_id)
            inserted = db.insert_outreach_lead(user_id, lead_row)
            if inserted:
                leads_count += 1

    return posts_count, leads_count


# ── Entrypoint ───────────────────────────────────────────────────────────────

def run() -> None:
    from src import db

    if not db.admin_enabled():
        logger.error("SUPABASE_SERVICE_ROLE_KEY manquant — cron impossible")
        sys.exit(1)

    client = _apify_client()
    if not client:
        sys.exit(1)

    users = db.list_outreach_keyword_users()
    logger.info("Outreach detector : %d utilisateur(s) avec keywords actifs", len(users))

    for user_id in users:
        keywords = db.list_active_keywords_for_user(user_id)
        logger.info("  user %s : %d keyword(s)", user_id[:8], len(keywords))
        for kw in keywords:
            try:
                posts, leads = _process_keyword(client, kw, user_id)
                db.update_keyword_run_stats(kw["id"], posts, leads)
                logger.info(
                    "    «%s» → %d posts, %d leads", kw["keyword"], posts, leads
                )
            except Exception as exc:
                logger.error("    «%s» erreur : %s", kw.get("keyword"), exc)
                db.update_keyword_run_stats(kw["id"], 0, 0, error=str(exc))

    logger.info("Outreach detector terminé")


if __name__ == "__main__":
    run()
