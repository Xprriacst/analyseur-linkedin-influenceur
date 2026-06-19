"""Daily-idea cron: generate one post idea per opted-in user.

Run once a day on Render (`python -m src.daily_ideas`). Uses the Supabase
service-role client (`db.admin_client`) because there is no user session here:
it reads every opted-in user's corpus/seeds and writes their `daily_ideas` row.

Per-user isolation: one user failing (no corpus, LLM error…) never blocks the
others. Idempotent: a user who already has today's idea is skipped, so re-running
the cron the same day costs nothing.
"""
from __future__ import annotations

import datetime
import os
import sys

from src import db
from src.benchmark import build_benchmark, enrich_influencers
from src.llm import generate_ideas


def _render_idea_markdown(idea: dict, seed_text: str | None) -> str:
    """Render a single idea dict into the markdown stored in `daily_ideas`."""
    title = idea.get("title") or "Idée du jour"
    lines = [f"## {title}", ""]
    if idea.get("hook"):
        lines += [f"**Accroche :** {idea['hook']}", ""]
    if idea.get("angle"):
        lines += [idea["angle"], ""]
    if idea.get("why_it_works"):
        lines += [f"**Pourquoi ça marche :** {idea['why_it_works']}", ""]

    meta = []
    if idea.get("hook_type"):
        meta.append(f"hook _{idea['hook_type']}_")
    if idea.get("funnel"):
        meta.append(idea["funnel"])
    if idea.get("estimated_lift"):
        meta.append(idea["estimated_lift"])
    if meta:
        lines.append("· ".join(meta))
    if seed_text:
        lines += ["", f"_Inspirée de votre réservoir : « {seed_text} »_"]
    return "\n".join(lines).strip()


def _generate_for_user(user_id: str, today: str) -> bool:
    """Generate and persist one idea for a user. Returns True on success."""
    if db.daily_idea_exists(user_id, today):
        print(f"  · {user_id}: idée déjà présente pour {today}, skip")
        return False

    corpus = db.get_corpus_for_user(user_id)
    influencers = enrich_influencers(corpus)
    if not influencers:
        print(f"  · {user_id}: aucun corpus analysé, skip")
        return False

    top_posts, benchmark = build_benchmark(influencers)
    context = db.get_ai_context_for_user(user_id)
    seed = db.pop_unused_seed(user_id)
    seed_text = seed["text"] if seed else None

    ideas = generate_ideas(
        top_posts,
        benchmark,
        count=1,
        user_context=context,
        seed_topic=seed_text,
    )
    if not ideas:
        print(f"  · {user_id}: génération vide, skip")
        return False

    markdown = _render_idea_markdown(ideas[0], seed_text)
    db.insert_daily_idea(user_id, markdown, today, seed_id=seed["id"] if seed else None)
    if seed:
        db.mark_seed_used(seed["id"])
    print(f"  ✓ {user_id}: idée générée" + (" (seed)" if seed else " (benchmark)"))
    return True


def main() -> int:
    if not db.admin_enabled():
        print("SUPABASE_SERVICE_ROLE_KEY manquant — cron désactivé.", file=sys.stderr)
        return 1
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY manquant — cron désactivé.", file=sys.stderr)
        return 1

    today = datetime.date.today().isoformat()
    users = db.list_daily_idea_users()
    print(f"Idée du jour {today} — {len(users)} utilisateur(s) opt-in")

    ok = 0
    for user_id in users:
        try:
            if _generate_for_user(user_id, today):
                ok += 1
        except Exception as exc:  # isolation par user : un échec ne bloque pas les autres
            print(f"  ✗ {user_id}: {exc}", file=sys.stderr)

    print(f"Terminé : {ok}/{len(users)} idée(s) générée(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
