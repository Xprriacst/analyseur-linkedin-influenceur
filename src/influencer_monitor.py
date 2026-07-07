"""Monitoring influenceurs (ALE-214) : détecte les nouveaux posts des influenceurs suivis.

Cron Render (`python -m src.influencer_monitor`), ~2×/semaine.
Pour chaque handle suivi (dédupliqué tous utilisateurs confondus — le cache est
partagé, un scrape sert tout le monde) :
- scrape les ~10 derniers posts (MONITOR_POSTS_LIMIT), sans cache disque ;
- n'insère que le neuf dans `cached_posts` (dédup URL), avec `media_items`
  et `detected_by_monitor=true` ;
- re-relève l'engagement des posts récents déjà connus (fenêtre
  MONITOR_REFRESH_DAYS) : l'engagement d'un post frais n'est pas stabilisé.

Aucun appel LLM : coût = Apify uniquement (~0,002 $/post scrapé).
Isolation par influenceur : un échec ne bloque pas les autres.
"""
from __future__ import annotations

import datetime
import os
import sys

from src import db
from src.normalize import normalize_posts
from src.scraper import fetch_posts, normalize_url

POSTS_LIMIT = int(os.environ.get("MONITOR_POSTS_LIMIT", "10"))
REFRESH_DAYS = int(os.environ.get("MONITOR_REFRESH_DAYS", "14"))


def _is_recent(posted_at: str | None, now: datetime.datetime) -> bool:
    if not posted_at:
        return False
    try:
        dt = datetime.datetime.fromisoformat(str(posted_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return (now - dt).days <= REFRESH_DAYS


def run_for_handle(handle: str, platform: str = "linkedin") -> dict:
    """Détecte les nouveaux posts d'un influenceur. Retourne {new, refreshed}."""
    profile_url = normalize_url(f"https://www.linkedin.com/in/{handle}/")
    raw = fetch_posts(profile_url, limit=POSTS_LIMIT, use_cache=False)
    posts = normalize_posts(raw)
    if not posts:
        return {"new": 0, "refreshed": 0}

    cache = db.get_influencer_from_cache(handle, platform)
    if cache:
        cache_id = cache["id"]
    else:
        # Influenceur suivi mais jamais passé par le pipeline d'analyse depuis
        # la mise en place du cache : entrée minimale (pas de scrape profil).
        cache_id = db.upsert_influencer_cache(handle, platform, {"profile_url": profile_url})
    if not cache_id:
        return {"new": 0, "refreshed": 0}

    existing_urls = {
        row["url"] for row in db.get_cached_posts_for_influencer(cache_id) if row.get("url")
    }
    new_posts = [p for p in posts if p.get("url") and p["url"] not in existing_urls]
    if new_posts:
        db.upsert_cached_posts(
            cache_id,
            [{"post": p, "classification": None} for p in new_posts],
            detected_by_monitor=True,
        )

    # Relevé d'engagement des posts récents déjà connus.
    now = datetime.datetime.now(datetime.timezone.utc)
    refreshed = 0
    for p in posts:
        url = p.get("url")
        if not url or url not in existing_urls:
            continue
        date = p.get("date")
        posted_at = date.isoformat() if hasattr(date, "isoformat") else date
        if _is_recent(posted_at, now):
            db.refresh_cached_post_metrics(cache_id, p)
            refreshed += 1

    return {"new": len(new_posts), "refreshed": refreshed}


def run_for_user(user_id: str) -> dict:
    """Détection à la demande (bouton « Vérifier maintenant ») pour un utilisateur."""
    totals = {"handles": 0, "new": 0, "refreshed": 0}
    for handle in db.list_followed_handles_for_user(user_id):
        try:
            result = run_for_handle(handle)
        except Exception as exc:  # noqa: BLE001 — isolation par influenceur
            print(f"[monitor] {handle}: échec {exc}", file=sys.stderr)
            continue
        totals["handles"] += 1
        totals["new"] += result["new"]
        totals["refreshed"] += result["refreshed"]
    return totals


def main() -> int:
    if not db.admin_enabled():
        print("SUPABASE_SERVICE_ROLE_KEY manquant — cron désactivé.", file=sys.stderr)
        return 1
    if not os.environ.get("APIFY_TOKEN"):
        print("APIFY_TOKEN manquant — cron désactivé.", file=sys.stderr)
        return 1

    handles = db.list_all_followed_handles()
    print(f"Monitoring influenceurs — {len(handles)} handle(s) suivi(s)")

    total_new = 0
    for handle in handles:
        try:
            result = run_for_handle(handle)
        except Exception as exc:  # noqa: BLE001 — isolation par influenceur
            print(f"  ✗ {handle}: {exc}", file=sys.stderr)
            continue
        total_new += result["new"]
        print(f"  ✓ {handle}: {result['new']} nouveau(x), {result['refreshed']} relevé(s) d'engagement")

    print(f"Terminé : {total_new} nouveau(x) post(s) détecté(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
