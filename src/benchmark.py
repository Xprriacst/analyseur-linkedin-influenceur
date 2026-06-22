"""Build benchmark inputs (top posts + summary) from a user's corpus.

Extracted from `api.py` so the same logic is reusable by the daily-idea cron
(`src/daily_ideas.py`), which has no FastAPI request context. Behaviour is
unchanged: `api.py` keeps thin `_enrich_influencers` / `_build_benchmark`
aliases that delegate here.
"""
from __future__ import annotations

from collections import Counter

from src.patterns import analyze_patterns
from src.stats import compute_stats


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


def _select_diverse_top_posts(all_posts: list[dict], n: int = 8) -> list[dict]:
    """Pick n posts that cover as many distinct hook_types and formats as
    possible, while still favouring high-engagement posts within each bucket.

    Pass 1 – best-engagement post per hook_type.
    Pass 2 – best-engagement post per unseen format.
    Pass 3 – fill remaining slots by engagement rank.
    """
    by_engagement = sorted(all_posts, key=lambda x: x.get("engagement", 0), reverse=True)

    selected: set[int] = set()
    seen_hooks: set[str] = set()
    seen_formats: set[str] = set()

    def _add(i: int, p: dict) -> None:
        selected.add(i)
        seen_hooks.add(p.get("hook_type", "other"))
        seen_formats.add(p.get("format", "text"))

    for i, p in enumerate(by_engagement):
        if len(selected) >= n:
            break
        if p.get("hook_type", "other") not in seen_hooks:
            _add(i, p)

    for i, p in enumerate(by_engagement):
        if len(selected) >= n:
            break
        if i not in selected and p.get("format", "text") not in seen_formats:
            _add(i, p)

    for i, p in enumerate(by_engagement):
        if len(selected) >= n:
            break
        if i not in selected:
            _add(i, p)

    return [by_engagement[i] for i in sorted(selected, key=lambda i: -by_engagement[i].get("engagement", 0))]


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

    top_posts = _select_diverse_top_posts(all_posts, n=8)
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
