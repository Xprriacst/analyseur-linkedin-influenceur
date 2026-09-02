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


def _unipile_own_posts_memory(account_id: str | None) -> list[dict]:
    """Posts live du compte Unipile → mémoire. Fail-safe, 0 Apify.

    Uniquement quand le profil n'a pas encore été analysé dans Cibl : Unipile
    n'est PAS appelé à chaque `/generate` (JWT). Cron + bootstrap seulement.
    """
    if not account_id:
        return []
    try:
        from src import unipile
        if not unipile.enabled():
            return []
        items = unipile.list_own_posts(account_id, limit=10)
        return unipile.own_posts_to_memory(items, text_cap=db.POST_MEMORY_TEXT_CAP)
    except Exception as exc:
        print(f"[daily_ideas] posts Unipile illisibles ({exc})", flush=True)
        return []


def recent_posts_for_generation(
    *,
    user_id: str | None = None,
    access_token: str | None = None,
) -> list[dict] | None:
    """Mémoire pour le post du jour : corpus Cibl, Unipile seulement en repli.

    Si la mémoire contient déjà un « publié sur LinkedIn » (profil analysé),
    Unipile n'est pas appelé. Liste vide ⇒ None (generate_posts omet le bloc).
    """
    account_id = None
    if access_token:
        entries = db.get_recent_post_memory(access_token) or []
        account = db.get_linkedin_outreach_account(access_token) or {}
        account_id = account.get("unipile_account_id")
    elif user_id:
        entries = db.get_recent_post_memory_for_user(user_id) or []
        account = db.admin_linkedin_outreach_account(user_id) or {}
        account_id = account.get("unipile_account_id")
    else:
        return None
    if db.has_own_linkedin_memory(entries):
        return entries or None
    extra = _unipile_own_posts_memory(account_id)
    if extra:
        entries = db.dedupe_post_memory(list(extra) + list(entries))
    return entries or None


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
    # Photos jointes manuellement sur la seed (Joëlle) : utilisées si l'annonce
    # n'en fournit pas, sinon l'annonce prime (c'est la source de vérité du bien).
    image_url = source_url = None
    origin = "seed" if seed else "benchmark"
    seed_media = (seed.get("media_items") or []) if seed else []
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
    if not image_url and seed_media:
        first = seed_media[0] if isinstance(seed_media[0], dict) else {}
        image_url = (first.get("url") or "").strip() or None

    # Commentaire d'orientation saisi par l'utilisateur (annonces) : on l'ajoute
    # au sujet pour guider la génération sans écraser l'annonce elle-même.
    seed_comment = (seed.get("comment") or "").strip() if seed else ""
    if seed_text and seed_comment:
        seed_text += f"\n\nOrientation demandée par l'utilisateur : {seed_comment}"

    # Rôle éditorial déterministe basé sur le jour (7 rôles → 1 rôle différent/semaine,
    # idempotence garantie : même date = même rôle même si le cron tourne plusieurs fois).
    _roles = list(ROLE_SPECS.keys())
    daily_role = _roles[datetime.date.fromisoformat(today).toordinal() % len(_roles)]

    # ALE-136 : on génère un VRAI post complet (postable), plus un simple concept.
    posts = generate_posts(
        seed_text,
        top_posts,
        benchmark,
        user_context=context,
        editorial_role=daily_role,
        count=1,
        # Mémoire : posts live LinkedIn (profil analysé, sinon Unipile) + Cibl.
        recent_posts=recent_posts_for_generation(user_id=user_id),
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


def maybe_bootstrap_daily_idea(access_token: str) -> bool:
    """Premier post du jour pour un compte neuf — gratuit, best-effort, jamais d'exception.

    Le cron matinal ne tourne qu'une fois par jour ; un compte créé l'après-midi
    n'a ni corpus analysé ni idée en base. Sans ce bootstrap, la vue Pilote promet
    « 1 post / jour » mais affiche un écran vide jusqu'au lendemain.
    """
    try:
        if not os.environ.get("ANTHROPIC_API_KEY") or not db.admin_enabled():
            return False
        user = db.get_user(access_token)
        if not user:
            return False
        user_id = user["id"]
        today = datetime.date.today().isoformat()
        if db.daily_idea_exists(user_id, today):
            return False
        profile = db.get_editorial_profile(access_token)
        if not profile or not profile.get("daily_ideas_enabled"):
            return False
        prior_ideas = db.list_daily_ideas(access_token, limit=1)
        if prior_ideas:
            # Compte déjà servi par le cron — pas de rattrapage à chaque ouverture.
            return False
        generated = db.list_generated_posts(access_token, limit=30, platform="linkedin")
        if any(
            (row.get("post") or "").strip()
            and row.get("platform") in (None, "", "linkedin")
            and not row.get("zernio_post_id")
            for row in generated
        ):
            return False

        corpus = db.get_corpus_for_user(user_id)
        influencers = enrich_influencers(corpus) if corpus else []
        if influencers:
            return _generate_for_user(user_id, today)

        context = db.get_user_ai_context(access_token)
        if not context:
            return False
        roles = list(ROLE_SPECS.keys())
        daily_role = roles[datetime.date.fromisoformat(today).toordinal() % len(roles)]
        empty_benchmark = {"benchmarks": [], "top_hook_types": {}, "corpus_insights": {}}
        posts = generate_posts(
            None,
            [],
            empty_benchmark,
            user_context=context,
            editorial_role=daily_role,
            count=1,
            recent_posts=recent_posts_for_generation(access_token=access_token),
        )
        if not posts:
            return False
        post = posts[0]
        markdown = post.get("post") or ""
        if not markdown.strip():
            return False
        db.replace_daily_idea(access_token, markdown, today, post=post)
        print(f"[daily_ideas] bootstrap {user_id}: premier post (profil éditorial)", flush=True)
        return True
    except Exception as exc:
        print(f"[daily_ideas] bootstrap échoué : {exc}", flush=True)
        return False


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
