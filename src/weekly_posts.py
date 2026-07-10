"""Weekly posts cron: generate + schedule 3 posts/week per opted-in user.

Run every Friday morning on Render (`python -m src.weekly_posts`).
Scheduled posts land the following week (Mon/Wed/Fri by default) and await
Slack validation before the existing scheduler cron publishes them.
Users without Slack connected get their posts auto-validated (ALE-272):
the Slack webhook is the only path to 'validated', so a pending post would
otherwise never be publishable.

Per-user isolation: one user failing never blocks the others.
Idempotent: if a non-cancelled post already exists for a given date, it is
skipped, so re-running the cron the same Friday costs nothing.
"""
from __future__ import annotations

import datetime
import os
import sys
import zoneinfo

from src import db
from src.benchmark import build_benchmark, enrich_influencers
from src.listing import ListingError, build_listing_topic, fetch_listing_preview, is_listing_url
from src.llm import generate_posts
from src import slack as slack_client


# --------------------------------------------------------------------------- #
# Date helpers                                                                  #
# --------------------------------------------------------------------------- #

def _next_week_slot_utc(
    run_date: datetime.date,
    day_of_week: int,
    hour: int,
    tz: str,
) -> tuple[datetime.datetime, str]:
    """Return (UTC datetime, local date string YYYY-MM-DD) for the next-week slot.

    day_of_week: 0=Monday … 6=Sunday (same convention as weekly_post_schedule).
    """
    # Find Monday of next week relative to run_date.
    days_since_monday = run_date.weekday()
    days_to_next_monday = 7 - days_since_monday
    next_monday = run_date + datetime.timedelta(days=days_to_next_monday)
    target_local = next_monday + datetime.timedelta(days=day_of_week)
    local_tz = zoneinfo.ZoneInfo(tz)
    local_dt = datetime.datetime(
        target_local.year, target_local.month, target_local.day,
        hour, 0, 0, tzinfo=local_tz,
    )
    utc_dt = local_dt.astimezone(datetime.timezone.utc)
    return utc_dt, target_local.isoformat()


# --------------------------------------------------------------------------- #
# Per-user logic                                                                #
# --------------------------------------------------------------------------- #

def _generate_for_user(user_id: str, run_date: datetime.date) -> int:
    """Generate and schedule this week's posts for one user. Returns count created."""
    schedule = db.get_weekly_schedule_for_user(user_id)
    if not schedule:
        print(f"  · {user_id}: aucun planning configuré, skip")
        return 0

    corpus = db.get_corpus_for_user(user_id)
    influencers = enrich_influencers(corpus)
    if not influencers:
        print(f"  · {user_id}: aucun corpus analysé, skip")
        return 0

    top_posts, benchmark = build_benchmark(influencers)
    context = db.get_ai_context_for_user(user_id)
    slack_cfg = db.get_slack_config_for_user(user_id)

    created = 0
    for slot in schedule:
        day_of_week = int(slot["day_of_week"])
        hour = int(slot.get("hour", 9))
        tz = slot.get("timezone", "Europe/Paris")

        utc_dt, local_date = _next_week_slot_utc(run_date, day_of_week, hour, tz)
        utc_date = utc_dt.date().isoformat()

        # Idempotency: skip if a post already exists for this date.
        if db.weekly_post_exists(user_id, utc_date):
            print(f"  · {user_id}: post déjà planifié pour {local_date}, skip")
            continue

        # Pick a seed topic from the reservoir, then fall back to pure generation.
        seed = db.pop_unused_seed(user_id)
        seed_text = seed["text"] if seed else None

        # Lien d'annonce : ancrer le post sur le bien (comme l'idée du jour).
        if seed_text and is_listing_url(seed_text):
            try:
                seed_text = build_listing_topic(fetch_listing_preview(seed_text, download_image=False))
            except ListingError as exc:
                print(f"  · {user_id}: annonce illisible ({exc}) → post benchmark", file=sys.stderr)
                seed_text = None

        # Commentaire d'orientation saisi par l'utilisateur (annonces).
        seed_comment = (seed.get("comment") or "").strip() if seed else ""
        if seed_text and seed_comment:
            seed_text += f"\n\nOrientation demandée par l'utilisateur : {seed_comment}"

        posts = generate_posts(
            seed_text,
            top_posts,
            benchmark,
            user_context=context,
            count=1,
        )
        if not posts:
            print(f"  · {user_id}: génération vide pour {local_date}, skip")
            continue

        post_text = posts[0].get("post") or ""
        if not post_text:
            print(f"  · {user_id}: post vide pour {local_date}, skip")
            continue

        scheduled_at_iso = utc_dt.isoformat()
        # Sans Slack connecté, le webhook Slack (seul chemin vers 'validated')
        # n'existe pas : un post 'pending' resterait bloqué pour toujours.
        # On l'auto-valide donc → il partira au créneau choisi via le
        # scheduler de publication (ALE-272). Avec Slack : flux inchangé
        # (pending + message de validation).
        slack_status = "pending" if slack_cfg else "validated"
        row = db.create_scheduled_post_admin(
            user_id, post_text, scheduled_at_iso, slack_status=slack_status
        )
        if row is None:
            print(f"  · {user_id}: échec d'insertion pour {local_date}", file=sys.stderr)
            continue

        if seed:
            db.mark_seed_used(seed["id"])

        # Send Slack validation request if the user has Slack connected.
        if slack_cfg:
            bot_token = slack_cfg.get("access_token") or ""
            channel_id = slack_cfg.get("channel_id") or ""
            if bot_token and channel_id:
                try:
                    ts = slack_client.send_scheduled_post_for_validation(bot_token, channel_id, row)
                    db.set_scheduled_post_slack_ts_admin(row["id"], ts)
                except slack_client.SlackError as exc:
                    print(f"  ⚠ {user_id}: Slack KO pour {local_date}: {exc}", file=sys.stderr)
            else:
                print(f"  · {user_id}: Slack incomplet pour {local_date}, post créé sans notification")
        else:
            print(
                f"  · {user_id}: Slack non connecté pour {local_date}, "
                "post auto-validé (publication au créneau choisi)"
            )

        origin = "seed" if seed else "benchmark"
        print(f"  ✓ {user_id}: post semaine prochaine planifié {local_date} ({origin})")
        created += 1

    return created


# --------------------------------------------------------------------------- #
# Déclenchement manuel (ALE-212)                                                #
# --------------------------------------------------------------------------- #

def run_for_user(user_id: str, run_date: datetime.date | None = None) -> int:
    """Génère les posts hebdo pour un seul utilisateur (déclenchement manuel).

    Même logique que le cron du vendredi (créneaux de la semaine suivante,
    validation Slack, idempotent). Retourne le nombre de posts créés.
    """
    return _generate_for_user(user_id, run_date or datetime.date.today())


# --------------------------------------------------------------------------- #
# Entry-point                                                                   #
# --------------------------------------------------------------------------- #

def main() -> int:
    if not db.admin_enabled():
        print("SUPABASE_SERVICE_ROLE_KEY manquant — cron désactivé.", file=sys.stderr)
        return 1
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY manquant — cron désactivé.", file=sys.stderr)
        return 1

    run_date = datetime.date.today()
    users = db.list_weekly_posts_users()
    print(f"Posts hebdo {run_date} — {len(users)} utilisateur(s) opt-in")

    total = 0
    for user_id in users:
        try:
            total += _generate_for_user(user_id, run_date)
        except Exception as exc:
            print(f"  ✗ {user_id}: {exc}", file=sys.stderr)

    print(f"Terminé : {total} post(s) planifié(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
