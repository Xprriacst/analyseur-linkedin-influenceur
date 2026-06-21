"""Monitoring influenceurs (ALE-32) — détecte les nouveaux posts automatiquement.

Entrypoint cron : python -m src.monitor
Schedule recommandé : 0 6 * * * (6h UTC, après daily_ideas à 5h)

Pour chaque influenceur surveillé (is_active=True dans influencer_monitoring) :
  1. Vérifie si assez de temps s'est écoulé depuis last_monitored_at.
  2. Scrape les derniers posts via Apify (run_analysis, sans LLM = pas de coût Anthropic).
  3. Déduplique contre les posts existants (par URL).
  4. Insère uniquement les nouveaux posts sans toucher aux anciens.
  5. Met à jour last_monitored_at + new_posts_since_last.
  6. Débite 5 crédits par vérification.

Isolation par influenceur : un échec ne bloque pas les autres.
Idempotent : si la même vérification est relancée dans la fenêtre MIN_HOURS, elle est skippée.

Variables d'environnement requises :
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, APIFY_API_TOKEN
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from src import db
from src.pipeline import run_analysis

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

CREDIT_COST = 5
MIN_HOURS: dict[str, int] = {"daily": 20, "weekly": 6 * 24}


def _should_check(last_at: str | None, frequency: str) -> bool:
    if not last_at:
        return True
    dt = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
    elapsed_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    return elapsed_h >= MIN_HOURS.get(frequency, 20)


def _monitor_one(entry: dict) -> int:
    """Vérifie et sauvegarde les nouveaux posts d'un influenceur. Retourne le nombre ajouté."""
    monitor_id = entry["id"]
    user_id = entry["user_id"]
    influencer_id = entry["influencer_id"]
    handle = entry.get("handle", "?")
    profile_url = entry.get("profile_url") or f"https://www.linkedin.com/in/{handle}"

    # Garde-fou crédits
    balance = db.get_user_credits_admin(user_id)
    if balance < CREDIT_COST:
        log.warning(f"  {handle}: crédits insuffisants ({balance} < {CREDIT_COST}) — skipped")
        return 0

    log.info(f"  Scraping {handle} (profile_url={profile_url})…")
    result = run_analysis(profile_url, limit=25, no_cache=True, with_llm=False)

    # Déduplication en mémoire avant insertion
    existing_urls = db.get_post_urls_for_influencer(influencer_id)
    new_posts = [
        p for p in result.get("posts", [])
        if p.get("url") and p["url"] not in existing_urls
    ]

    new_count = 0
    if new_posts:
        new_count = db.save_new_posts_for_influencer(influencer_id, new_posts)
        log.info(f"  {handle}: {new_count} nouveau(x) post(s) ajouté(s)")
    else:
        log.info(f"  {handle}: aucun nouveau post détecté")

    db.update_monitoring_last_checked(monitor_id, new_count)
    db.debit_credits_admin(user_id, CREDIT_COST, "monitor_check")
    return new_count


def main() -> None:
    if not db.admin_enabled():
        log.error("SUPABASE_SERVICE_ROLE_KEY non configurée — monitoring annulé")
        sys.exit(1)

    log.info("=== Démarrage monitoring influenceurs (ALE-32) ===")
    entries = db.list_active_monitoring_entries()
    log.info(f"{len(entries)} influenceur(s) surveillé(s)")

    ok = 0
    new_total = 0
    for entry in entries:
        frequency = entry.get("frequency", "daily")
        if not _should_check(entry.get("last_monitored_at"), frequency):
            log.info(f"  {entry.get('handle', '?')}: dernière vérification trop récente, skipped")
            continue
        try:
            new_total += _monitor_one(entry)
            ok += 1
        except Exception as exc:
            log.exception(f"  {entry.get('handle', '?')}: erreur — {exc}")

    log.info(f"Terminé : {ok}/{len(entries)} influenceur(s) vérifiés, {new_total} nouveau(x) post(s) ajouté(s)")


if __name__ == "__main__":
    main()
