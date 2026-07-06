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
from src.listing import ListingError, build_listing_topic, fetch_listing_preview, is_listing_url
from src.llm import ROLE_SPECS, generate_posts


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

    # ALE-156 : si la seed est un lien d'annonce immobilière, on lit l'annonce
    # (image + infos du bien) et on ancre le post dessus, avec la photo rattachée.
    image_url = source_url = None
    origin = "seed" if seed else "benchmark"
    if seed_text and is_listing_url(seed_text):
        try:
            preview = fetch_listing_preview(seed_text, download_image=False)
            seed_text = build_listing_topic(preview)
            image_url = preview.get("image_url")
            source_url = preview.get("source_url")
            origin = "annonce"
        except ListingError as exc:
            # Échec propre : on consomme quand même la seed pour ne pas bloquer la
            # file, et on génère un post benchmark. Le lien défaillant est loggé.
            print(f"  · {user_id}: annonce illisible ({exc}) → post benchmark", file=sys.stderr)
            seed_text = None

    # Commentaire d'orientation saisi par l'utilisateur (annonces) : on l'ajoute
    # au sujet pour guider la génération sans écraser l'annonce elle-même.
    seed_comment = (seed.get("comment") or "").strip() if seed else ""
    if seed_text and seed_comment:
        seed_text += f"\n\nOrientation demandée par l'utilisateur : {seed_comment}"

    # Rôle éditorial déterministe basé sur le jour (7 rôles → 1 rôle différent/semaine,
    # idempotence garantie : même date = même rôle même si le cron tourne plusieurs fois).
    _roles = list(ROLE_SPECS.keys())
    daily_role = _roles[datetime.date.fromisoformat(today).toordinal() % len(_roles)]

    # ALE-181 : en génération à froid (aucun sujet imposé par une seed), on passe
    # l'historique des sujets récents pour éviter de reproposer le même thème jour
    # après jour. Avec une seed le sujet est imposé → on ne filtre pas.
    avoid_topics = None
    if not seed_text:
        avoid_topics = db.get_recent_daily_idea_topics(user_id)

    # ALE-136 : on génère un VRAI post complet (postable), plus un simple concept.
    posts = generate_posts(
        seed_text,
        top_posts,
        benchmark,
        user_context=context,
        editorial_role=daily_role,
        count=1,
        avoid_topics=avoid_topics,
    )
    if not posts:
        print(f"  · {user_id}: génération vide, skip")
        return False

    post = posts[0]
    # idea_markdown = texte du post (rétro-compat des consommateurs existants).
    markdown = post.get("post") or ""
    db.insert_daily_idea(
        user_id,
        markdown,
        today,
        seed_id=seed["id"] if seed else None,
        post=post,
        image_url=image_url,
        source_url=source_url,
    )
    if seed:
        db.mark_seed_used(seed["id"])
    print(f"  ✓ {user_id}: post du jour généré ({origin})")
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
