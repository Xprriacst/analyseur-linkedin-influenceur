"""Build benchmark inputs (top posts + summary) from a user's corpus.

Extracted from `api.py` so the same logic is reusable by the daily-idea cron
(`src/daily_ideas.py`), which has no FastAPI request context. Behaviour is
unchanged: `api.py` keeps thin `_enrich_influencers` / `_build_benchmark`
aliases that delegate here.
"""
from __future__ import annotations

from collections import Counter
from typing import Sequence

from src.patterns import analyze_patterns
from src.stats import compute_stats

_TOP_POSTS_LIMIT = 6
_MIN_DISTINCT_CATEGORIES = 3


def _select_diverse_top_posts(all_posts: list[dict], limit: int = _TOP_POSTS_LIMIT) -> list[dict]:
    """Select up to `limit` posts covering ≥ MIN_DISTINCT_CATEGORIES hook_types/formats.

    Within each bucket (hook_type first, then format as tiebreaker) we keep
    the best-performing post. If the corpus is too homogeneous we fall back to
    the plain top-N-by-engagement.
    """
    if not all_posts:
        return []

    by_hook: dict[str, list[dict]] = {}
    for p in all_posts:
        key = p.get("hook_type") or "other"
        by_hook.setdefault(key, []).append(p)

    # Best post per hook_type, sorted by their hook's top engagement.
    hook_slots: list[dict] = [
        max(posts, key=lambda p: p.get("engagement", 0))
        for posts in by_hook.values()
    ]
    hook_slots.sort(key=lambda p: p.get("engagement", 0), reverse=True)

    selected: list[dict] = hook_slots[:limit]

    # If we still have room and haven't hit the format-diversity target, fill
    # with best posts per format that aren't already selected.
    if len(selected) < limit:
        seen_ids = {id(p) for p in selected}
        by_format: dict[str, list[dict]] = {}
        for p in all_posts:
            if id(p) not in seen_ids:
                key = p.get("format") or "text"
                by_format.setdefault(key, []).append(p)

        format_slots = [
            max(posts, key=lambda p: p.get("engagement", 0))
            for posts in by_format.values()
        ]
        format_slots.sort(key=lambda p: p.get("engagement", 0), reverse=True)
        for p in format_slots:
            if len(selected) >= limit:
                break
            selected.append(p)

    # Fallback: if we still don't have MIN_DISTINCT_CATEGORIES across hook+format,
    # the corpus is homogeneous — plain top-N is fine.
    distinct = len({p.get("hook_type", "other") for p in selected} |
                   {p.get("format", "text") for p in selected})
    if distinct < _MIN_DISTINCT_CATEGORIES:
        return sorted(all_posts, key=lambda x: x.get("engagement", 0), reverse=True)[:limit]

    return selected


def enrich_influencers(corpus: list[dict]) -> list[dict]:
    """Compute stats + patterns on a raw corpus of {handle, profile, posts}."""
    result = []
    for inf in corpus:
        posts = inf["posts"]
        if not posts:
            continue
        result.append({
            "handle": inf["handle"],
            "profile": inf["profile"],
            "posts": posts,
            "stats": compute_stats(posts, profile=inf["profile"]),
            "patterns": analyze_patterns(posts),
        })
    return result


def build_benchmark(influencers: list[dict]) -> tuple[list[dict], dict]:
    """Build top posts list and benchmark summary."""
    all_posts: list[dict] = []
    hook_totals: Counter = Counter()
    for inf in influencers:
        name = inf["profile"].get("name", inf["handle"])
        enriched = inf["patterns"].get("posts_enriched", inf["posts"])
        for p in enriched:
            all_posts.append({**p, "influencer": name})
        for hook, count in inf["patterns"].get("hook_distribution", {}).items():
            hook_totals[hook] += count

    top_posts = _select_diverse_top_posts(all_posts)
    benchmarks = []
    for inf in influencers:
        s = inf["stats"].get("engagement", {})
        benchmarks.append({
            "influencer": inf["profile"].get("name", inf["handle"]),
            "followers": inf["profile"].get("follower_count", 0),
            "avg_engagement": round(s.get("mean_engagement", 0), 1),
            "avg_comments": round(s.get("mean_comments", 0), 1),
        })
    benchmark = {
        "benchmarks": benchmarks,
        "top_hook_types": dict(hook_totals.most_common(6)),
        "proven_insights": [
            "Hook stat+contrarian : combo sous-exploité, +40-80% vs post standard",
            "Triple CTA (comment+repost+save) : multiplicateur x2-3 prouvé sur le corpus",
            "Format image/carousel : 2x plus d'engagement que texte seul",
            "Longueur optimale : 1 400-1 800 caractères",
            "Hook question : quasi absent du corpus = alpha, +150% engagement potentiel",
        ],
    }
    return top_posts, benchmark
