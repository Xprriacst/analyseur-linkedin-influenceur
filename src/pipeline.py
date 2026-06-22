from __future__ import annotations

from typing import Callable

from src import db as _db
from src.llm import classify_posts, synthesize_strategy
from src.normalize import normalize_posts, normalize_profile
from src.patterns import analyze_patterns
from src.report import render_markdown, save_report
from src.scraper import extract_handle, fetch_posts, fetch_profile
from src.stats import compute_stats, compute_ig_stats, cta_breakdown, engagement_by_classification
from src.usage import get_usage, reset_usage

ProgressCallback = Callable[[float, str], None]

# Re-synthesize strategy only when ≥ this many new posts since last analysis.
# Below this threshold, the cached synthesis is reused (saves one LLM call).
RESYNTHESIS_THRESHOLD = 2


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

    tick(0.05, "Scraping profile")
    raw_profile = fetch_profile(url, use_cache=not no_cache)
    profile = normalize_profile(raw_profile)

    tick(0.25, f"Fetching last {limit} posts")
    raw = fetch_posts(url, limit=limit, use_cache=not no_cache)
    posts = normalize_posts(raw)
    if not posts:
        raise RuntimeError("Aucun post exploitable. Profil privé ou URL incorrecte ?")

    tick(0.45, "Computing stats")
    stats = compute_stats(posts, profile=profile)

    tick(0.55, "Detecting patterns")
    patterns = analyze_patterns(posts)
    cta_stats = cta_breakdown(patterns["posts_enriched"])
    stats["cta_effect"] = cta_stats

    cached_cls_by_url: dict[str, dict] = {}
    n_new = 0

    if with_llm:
        # --- ALE-109: incremental classification via global cache ---
        # Load cached classifications from the cross-user cache (service-role).
        # Posts already classified by any user skip the LLM call.
        cached_cls_by_url = _db.get_post_classifications_cache(handle)

        new_posts = [p for p in posts if p.get("url", "") not in cached_cls_by_url]
        n_new = len(new_posts)

        if new_posts:
            tick(0.7, f"Classifying {n_new} new / {len(posts)} posts")
            new_classifications = classify_posts(new_posts)
        else:
            tick(0.7, f"All {len(posts)} posts already classified (cache hit)")
            new_classifications = []

        # Build url→classification for the new batch
        new_cls_by_url: dict[str, dict] = {}
        for i, p in enumerate(new_posts):
            url_p = p.get("url", "")
            if url_p and i < len(new_classifications):
                new_cls_by_url[url_p] = new_classifications[i]

        # Merge cached + new, preserving original post order
        classifications = []
        for p in posts:
            url_p = p.get("url", "")
            if url_p in new_cls_by_url:
                classifications.append(new_cls_by_url[url_p])
            elif url_p in cached_cls_by_url:
                classifications.append(cached_cls_by_url[url_p])

        stats["stage_engagement"] = engagement_by_classification(classifications, posts, "stage")
        stats["hook_engagement"] = engagement_by_classification(classifications, posts, "hook_type")

        # Re-synthesize only when there was no prior cache (first run) or delta is significant.
        # With < RESYNTHESIS_THRESHOLD new posts the existing synthesis is still accurate enough.
        needs_synthesis = (not cached_cls_by_url) or (n_new >= RESYNTHESIS_THRESHOLD)
        if needs_synthesis:
            tick(0.85, "Generating strategic synthesis")
            synthesis = synthesize_strategy(stats, classifications, patterns["posts_enriched"])
        else:
            tick(0.85, "Reusing cached synthesis (no new posts)")
            synthesis = _db.get_cached_synthesis(handle) or synthesize_strategy(
                stats, classifications, patterns["posts_enriched"]
            )

        # Persist new classifications to the global cache for future incremental runs
        if new_cls_by_url:
            _db.save_post_classifications_cache(handle, new_cls_by_url)

    else:
        classifications = []
        synthesis = empty_synthesis()

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
        "incremental": {"cached": len(cached_cls_by_url), "new": n_new},
    }
