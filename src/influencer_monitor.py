"""Monitoring influenceurs (ALE-214) : détecte les nouveaux posts des influenceurs suivis.

Cron Render (`python -m src.influencer_monitor`), ~2×/semaine.
Pour chaque handle suivi (dédupliqué tous utilisateurs confondus — le cache est
partagé, un scrape sert tout le monde) :
- scrape les ~10 derniers posts (MONITOR_POSTS_LIMIT), sans cache disque ;
- n'insère que le neuf dans `cached_posts` (dédup URL), avec `media_items`
  et `detected_by_monitor=true` ;
- re-relève l'engagement des posts récents déjà connus (fenêtre
  MONITOR_REFRESH_DAYS) : l'engagement d'un post frais n'est pas stabilisé.

Coût = Apify (~0,002 $/post scrapé) + depuis ALE-227 un appel LLM léger par
nouveau post qui ressemble à un lead magnet (pré-filtre gratuit avant) : un
post concurrent suivi détecté « lead magnet » crée une source de prospection
pour chaque utilisateur qui suit ce handle. La collecte des commentateurs
(payante) reste déclenchée à la main depuis l'app.
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


def _detect_lead_magnets(handle: str, new_posts: list[dict], platform: str = "linkedin") -> int:
    """Nouveau post concurrent suivi → verdict lead-magnet → source auto (ALE-227).

    Pré-filtre heuristique gratuit avant l'appel LLM ; ne crée que la source
    (verdict + mot-clé) — jamais de collecte Apify automatique des commentateurs.
    Retourne le nombre de sources créées (tous utilisateurs suiveurs confondus).
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return 0
    from src.lead_finder import looks_like_lead_magnet

    candidates = [p for p in new_posts if looks_like_lead_magnet(p.get("text"))]
    if not candidates:
        return 0
    followers = db.list_user_ids_following_handle(handle, platform)
    if not followers:
        return 0

    from src.llm import classify_lead_magnet

    created = 0
    for post in candidates:
        try:
            verdict = classify_lead_magnet(post["text"])
        except Exception as exc:  # noqa: BLE001 — best-effort, ne bloque pas le monitoring
            print(f"[monitor] {handle}: classification lead-magnet échouée: {exc}", file=sys.stderr)
            continue
        if not verdict["is_lead_magnet"]:
            continue
        for user_id in followers:
            if db.add_lead_source_admin(
                user_id,
                post["url"],
                author=handle,
                post_text=post.get("text"),
                trigger_keyword=verdict["trigger_keyword"],
            ):
                created += 1
    return created


def run_for_handle(handle: str, platform: str = "linkedin") -> dict:
    """Détecte les nouveaux posts d'un influenceur. Retourne {new, refreshed, lead_sources}."""
    profile_url = normalize_url(f"https://www.linkedin.com/in/{handle}/")
    raw = fetch_posts(profile_url, limit=POSTS_LIMIT, use_cache=False)
    posts = normalize_posts(raw)
    if not posts:
        return {"new": 0, "refreshed": 0, "lead_sources": 0}

    cache = db.get_influencer_from_cache(handle, platform)
    if cache:
        cache_id = cache["id"]
    else:
        # Influenceur suivi mais jamais passé par le pipeline d'analyse depuis
        # la mise en place du cache : entrée minimale (pas de scrape profil).
        cache_id = db.upsert_influencer_cache(handle, platform, {"profile_url": profile_url})
    if not cache_id:
        return {"new": 0, "refreshed": 0, "lead_sources": 0}

    existing_urls = {
        row["url"] for row in db.get_cached_posts_for_influencer(cache_id) if row.get("url")
    }
    new_posts = [p for p in posts if p.get("url") and p["url"] not in existing_urls]
    lead_sources = 0
    if new_posts:
        db.upsert_cached_posts(
            cache_id,
            [{"post": p, "classification": None} for p in new_posts],
            detected_by_monitor=True,
        )
        try:
            lead_sources = _detect_lead_magnets(handle, new_posts, platform)
        except Exception as exc:  # noqa: BLE001 — la prospection ne casse jamais la veille
            print(f"[monitor] {handle}: détection lead-magnet échouée: {exc}", file=sys.stderr)

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

    return {"new": len(new_posts), "refreshed": refreshed, "lead_sources": lead_sources}


def run_for_user(user_id: str) -> dict:
    """Détection à la demande (bouton « Vérifier maintenant ») pour un utilisateur."""
    totals = {"handles": 0, "new": 0, "refreshed": 0, "lead_sources": 0}
    for handle in db.list_followed_handles_for_user(user_id):
        try:
            result = run_for_handle(handle)
        except Exception as exc:  # noqa: BLE001 — isolation par influenceur
            print(f"[monitor] {handle}: échec {exc}", file=sys.stderr)
            continue
        totals["handles"] += 1
        totals["new"] += result["new"]
        totals["refreshed"] += result["refreshed"]
        totals["lead_sources"] += result.get("lead_sources", 0)
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
        extra = f", {result['lead_sources']} source(s) lead-magnet" if result.get("lead_sources") else ""
        print(f"  ✓ {handle}: {result['new']} nouveau(x), {result['refreshed']} relevé(s) d'engagement{extra}")

    print(f"Terminé : {total_new} nouveau(x) post(s) détecté(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
