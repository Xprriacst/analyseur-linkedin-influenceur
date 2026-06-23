from __future__ import annotations

from typing import Callable

from src.llm import classify_posts, synthesize_strategy
from src.normalize import normalize_posts, normalize_profile
from src.patterns import analyze_patterns
from src.report import render_markdown, save_report
from src.scraper import extract_handle, fetch_posts, fetch_profile
from src.stats import compute_stats, compute_ig_stats, cta_breakdown, engagement_by_classification
from src.usage import get_usage, reset_usage

ProgressCallback = Callable[[float, str], None]

# Seuil pour l'analyse incrémentale (ALE-109)
RESYNTHESIS_THRESHOLD = 2  # Nb de nouveaux posts minimum pour refaire la synthèse LLM


def empty_synthesis() -> dict:
    return {
        "positioning": "Synthèse LLM désactivée.",
        "audience": "—",
        "content_pillars": [],
        "hook_patterns": [],
        "structural_patterns": [],
        "cta_strategy": "—",
        "strengths": [],
        "gaps": [],
        "actions_to_replicate": [],
    }


def _build_url_classif_map(
    new_posts: list[dict],
    new_classifs: list[dict],
    cached_url_to_classif: dict[str, dict],
) -> dict[str, dict]:
    """Fusionne les nouvelles classifications LLM avec celles du cache global.

    new_classifs : résultat de classify_posts(new_posts), indices relatifs à new_posts.
    cached_url_to_classif : {url → classif_dict} depuis le cache global.
    Retourne {url → classif_dict} couvrant l'union des deux sources.
    """
    url_to_classif: dict[str, dict] = dict(cached_url_to_classif)
    for c in new_classifs:
        idx = c.get("index", -1)
        if 0 <= idx < len(new_posts):
            url = new_posts[idx].get("url")
            if url:
                url_to_classif[url] = {
                    "stage": c.get("stage", "TOFU"),
                    "hook_type": c.get("hook_type", "other"),
                    "topic": c.get("topic", ""),
                    "angle": c.get("angle", ""),
                }
    return url_to_classif


def _reconstruct_classifications(
    posts: list[dict], url_to_classif: dict[str, dict]
) -> list[dict]:
    """Reconstruit la liste de classifications indexée sur `posts`.

    L'index i dans le résultat correspond à posts[i], ce qui est ce
    qu'attendent synthesize_strategy et engagement_by_classification.
    """
    result = []
    for i, post in enumerate(posts):
        url = post.get("url")
        classif = url_to_classif.get(url) if url else None
        if classif:
            result.append({"index": i, **classif})
    return result


def run_analysis(
    url: str,
    limit: int = 30,
    no_cache: bool = False,
    with_llm: bool = True,
    progress: ProgressCallback | None = None,
) -> dict:
    def tick(value: float, message: str) -> None:
        if progress:
            progress(value, message)

    reset_usage()
    handle = extract_handle(url)

    # ── Cache global cross-user (ALE-109) ─────────────────────────────────── #
    # Import local pour éviter un import circulaire (db importe pipeline indirectement).
    from src import db as _db

    cache_entry: dict | None = None
    cached_post_rows: list[dict] = []
    cached_url_to_classif: dict[str, dict] = {}

    if not no_cache:
        try:
            cache_entry = _db.get_influencer_from_cache(handle, platform="linkedin")
            if cache_entry:
                cached_post_rows = _db.get_cached_posts_for_influencer(cache_entry["id"])
                cached_url_to_classif = {
                    row["url"]: {
                        "stage": row["stage"],
                        "hook_type": row.get("hook_type", "other"),
                        "topic": row.get("topic", ""),
                        "angle": row.get("angle", ""),
                    }
                    for row in cached_post_rows
                    if row.get("url") and row.get("stage")
                }
        except Exception:
            cache_entry = None
            cached_post_rows = []
            cached_url_to_classif = {}
    # ──────────────────────────────────────────────────────────────────────── #

    tick(0.05, "Scraping profile")
    raw_profile = fetch_profile(url, use_cache=not no_cache)
    profile = normalize_profile(raw_profile)

    tick(0.25, f"Fetching last {limit} posts")
    raw = fetch_posts(url, limit=limit, use_cache=not no_cache)
    posts = normalize_posts(raw)
    if not posts:
        raise RuntimeError("Aucun post exploitable. Profil privé ou URL incorrecte ?")

    # Posts à (re)classifier = ceux qui n'ont PAS encore de classification en cache.
    # On se base sur les URLs réellement classifiées (cached_url_to_classif), pas sur
    # la simple présence en cache : un post mis en cache sans classification (ex. run
    # `with_llm=False`) doit être reclassifié, pas ignoré.
    classified_urls: set[str] = set(cached_url_to_classif.keys())
    new_posts: list[dict] = (
        [p for p in posts if p.get("url") and p["url"] not in classified_urls]
        if cache_entry
        else list(posts)
    )

    tick(0.45, "Computing stats")
    stats = compute_stats(posts, profile=profile)

    tick(0.55, "Detecting patterns")
    patterns = analyze_patterns(posts)
    cta_stats = cta_breakdown(patterns["posts_enriched"])
    stats["cta_effect"] = cta_stats

    url_to_classif: dict[str, dict] = {}
    new_classifs: list[dict] = []
    classifications: list[dict] = []
    synthesis: dict = empty_synthesis()

    if with_llm:
        if new_posts:
            tick(0.7, f"Classifying {len(new_posts)} new post(s) — TOFU/MOFU/BOFU")
            new_classifs = classify_posts(new_posts)
        else:
            tick(0.7, f"Tous les posts sont déjà classifiés ({len(cached_url_to_classif)} en cache)")

        url_to_classif = _build_url_classif_map(new_posts, new_classifs, cached_url_to_classif)
        classifications = _reconstruct_classifications(posts, url_to_classif)

        stats["stage_engagement"] = engagement_by_classification(classifications, posts, "stage")
        stats["hook_engagement"] = engagement_by_classification(classifications, posts, "hook_type")

        needs_synthesis = len(new_posts) >= RESYNTHESIS_THRESHOLD or not cache_entry
        cached_synthesis: dict | None = (cache_entry or {}).get("synthesis") if cache_entry else None

        if needs_synthesis:
            tick(0.85, "Generating strategic synthesis")
            synthesis = synthesize_strategy(stats, classifications, patterns["posts_enriched"])
        elif cached_synthesis:
            tick(0.85, "Synthèse existante réutilisée (delta < seuil de re-synthèse)")
            synthesis = cached_synthesis
        else:
            tick(0.85, "Generating strategic synthesis")
            synthesis = synthesize_strategy(stats, classifications, patterns["posts_enriched"])
    else:
        classifications = []
        synthesis = empty_synthesis()

    # ── Mise à jour du cache global ───────────────────────────────────────── #
    # On n'écrit le cache QUE si l'IA a tourné : la table cached_posts est insert-only,
    # donc un post inséré sans classification (run with_llm=False) ne récupérerait jamais
    # sa classification ensuite. On évite ainsi d'empoisonner le cache cross-user.
    if with_llm:
        try:
            cache_id = _db.upsert_influencer_cache(handle, "linkedin", profile, synthesis=synthesis)
            if cache_id:
                posts_for_cache = [
                    {
                        "post": p,
                        "classification": url_to_classif.get(p.get("url")) if url_to_classif else None,
                    }
                    for p in posts
                    if p.get("url")
                ]
                _db.upsert_cached_posts(cache_id, posts_for_cache)
        except Exception:
            pass  # La persistance du cache ne doit jamais interrompre l'analyse
    # ──────────────────────────────────────────────────────────────────────── #

    usage = get_usage()
    tick(0.95, "Rendering report")
    markdown = render_markdown(
        handle,
        url,
        stats,
        classifications,
        synthesis,
        posts,
        profile=profile,
        patterns=patterns,
        cta_stats=cta_stats,
        usage=usage,
    )
    path = save_report(handle, markdown)
    tick(1.0, "Done")

    return {
        "handle": handle,
        "url": url,
        "platform": "linkedin",
        "profile": profile,
        "posts": posts,
        "stats": stats,
        "patterns": patterns,
        "cta_stats": cta_stats,
        "classifications": classifications,
        "synthesis": synthesis,
        "usage": usage,
        "markdown": markdown,
        "path": str(path),
    }


def run_analysis_instagram(
    url: str,
    limit: int = 30,
    no_cache: bool = False,
    with_llm: bool = True,
    progress: ProgressCallback | None = None,
) -> dict:
    """Run the full Instagram analysis pipeline for a given URL or handle."""
    from src.llm import classify_reels_instagram, synthesize_ig_strategy
    from src.normalize_instagram import normalize_ig_reels, normalize_ig_profile
    from src.patterns_instagram import analyze_ig_patterns
    from src.report_instagram import render_ig_markdown, save_ig_report
    from src.scraper_instagram import extract_ig_handle, fetch_ig_profile, fetch_ig_reels

    def tick(value: float, message: str) -> None:
        if progress:
            progress(value, message)

    reset_usage()
    handle = extract_ig_handle(url)
    # Canonical URL for an Instagram profile
    canonical_url = f"https://www.instagram.com/{handle}/"

    tick(0.05, "Scraping Instagram profile")
    raw_profile = fetch_ig_profile(handle, use_cache=not no_cache)
    profile = normalize_ig_profile(raw_profile)

    tick(0.25, f"Fetching last {limit} reels")
    raw_reels = fetch_ig_reels(handle, limit=limit, use_cache=not no_cache)
    posts = normalize_ig_reels(raw_reels)
    if not posts:
        raise RuntimeError("Aucun reel exploitable. Profil privé ou handle incorrect ?")

    tick(0.45, "Computing Instagram stats")
    stats = compute_ig_stats(posts, profile=profile)

    tick(0.55, "Detecting Instagram patterns")
    patterns = analyze_ig_patterns(posts)
    cta_stats = cta_breakdown(patterns["posts_enriched"])
    stats["cta_effect"] = cta_stats

    if with_llm:
        tick(0.70, "Classifying Awareness/Engagement/Conversion")
        classifications = classify_reels_instagram(posts)
        stats["stage_engagement"] = engagement_by_classification(classifications, posts, "stage")
        stats["hook_engagement"] = engagement_by_classification(classifications, posts, "hook_type")
        tick(0.85, "Generating Instagram strategic synthesis")
        synthesis = synthesize_ig_strategy(stats, classifications, patterns["posts_enriched"])
    else:
        classifications = []
        synthesis = empty_synthesis()

    usage = get_usage()
    tick(0.95, "Rendering Instagram report")
    markdown = render_ig_markdown(
        handle,
        canonical_url,
        stats,
        classifications,
        synthesis,
        posts,
        profile=profile,
        patterns=patterns,
        cta_stats=cta_stats,
        usage=usage,
    )
    path = save_ig_report(handle, markdown)
    tick(1.0, "Done")

    return {
        "handle": handle,
        "url": canonical_url,
        "platform": "instagram",
        "profile": profile,
        "posts": posts,
        "stats": stats,
        "patterns": patterns,
        "cta_stats": cta_stats,
        "classifications": classifications,
        "synthesis": synthesis,
        "usage": usage,
        "markdown": markdown,
        "path": str(path),
    }
