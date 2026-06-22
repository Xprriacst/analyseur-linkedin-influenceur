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

    if with_llm:
        tick(0.7, "Classifying TOFU/MOFU/BOFU")
        classifications = classify_posts(posts)
        stats["stage_engagement"] = engagement_by_classification(classifications, posts, "stage")
        stats["hook_engagement"] = engagement_by_classification(classifications, posts, "hook_type")
        tick(0.85, "Generating strategic synthesis")
        synthesis = synthesize_strategy(stats, classifications, patterns["posts_enriched"])
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
    }
