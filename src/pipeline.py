from __future__ import annotations

from typing import Callable

from src.llm import classify_posts, synthesize_strategy
from src.normalize import normalize_posts, normalize_profile
from src.patterns import analyze_patterns
from src.report import render_markdown, save_report
from src.scraper import extract_handle, fetch_posts, fetch_profile
from src.stats import compute_stats, cta_breakdown
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

    if with_llm:
        tick(0.7, "Classifying TOFU/MOFU/BOFU")
        classifications = classify_posts(posts)
        tick(0.85, "Generating strategic synthesis")
        synthesis = synthesize_strategy(stats, classifications, posts)
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
