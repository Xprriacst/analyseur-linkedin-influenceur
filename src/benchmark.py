"""Build benchmark inputs (top posts + summary) from a user's corpus.

Extracted from `api.py` so the same logic is reusable by the daily-idea cron
(`src/daily_ideas.py`), which has no FastAPI request context. Behaviour is
unchanged: `api.py` keeps thin `_enrich_influencers` / `_build_benchmark`
aliases that delegate here.
"""
from __future__ import annotations

from collections import Counter
from statistics import median as _median

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


def _compute_corpus_insights(all_posts: list[dict]) -> list[str]:
    """Derive data-driven insights from the enriched post corpus.

    Replaces the 5 hardcoded lines that used to live in build_benchmark.
    Returns an empty list when the corpus is too small to assert anything.
    """
    if len(all_posts) < 5:
        return []

    engagements = [int(p.get("engagement", 0) or 0) for p in all_posts]
    overall_med = int(_median(engagements)) if engagements else 0
    insights: list[str] = []

    # -- Format --
    fmt_groups: dict[str, list[int]] = {}
    for p in all_posts:
        fmt = p.get("format") or "text"
        eng = int(p.get("engagement", 0) or 0)
        fmt_groups.setdefault(fmt, []).append(eng)

    fmt_medians = {
        fmt: int(_median(vals))
        for fmt, vals in fmt_groups.items()
        if len(vals) >= 5
    }
    if fmt_medians and overall_med > 0:
        best_fmt = max(fmt_medians, key=lambda k: fmt_medians[k])
        best_med = fmt_medians[best_fmt]
        if best_med >= overall_med * 1.3:
            ratio = round(best_med / overall_med, 1)
            insights.append(
                f"Format « {best_fmt} » : {ratio}× l'engagement médian global "
                f"({best_med} vs {overall_med} toutes catégories)"
            )

    # -- Hook type: best performer + underused alpha --
    hook_groups: dict[str, list[int]] = {}
    for p in all_posts:
        hook = p.get("hook_type") or "other"
        eng = int(p.get("engagement", 0) or 0)
        hook_groups.setdefault(hook, []).append(eng)

    hook_medians = {
        hook: int(_median(vals))
        for hook, vals in hook_groups.items()
        if len(vals) >= 5
    }
    if hook_medians:
        best_hook = max(hook_medians, key=lambda k: hook_medians[k])
        best_hook_med = hook_medians[best_hook]
        if best_hook_med > 0:
            insights.append(
                f"Hook le plus engageant sur ce corpus : « {best_hook} » "
                f"(médiane {best_hook_med})"
            )

    alpha_hooks = [
        h for h, vals in hook_groups.items()
        if len(vals) < 3 and h not in ("other",)
    ]
    if alpha_hooks:
        insights.append(
            f"Hook(s) quasi absent(s) = levier de différenciation potentiel : "
            f"{', '.join(alpha_hooks[:2])}"
        )

    # -- Optimal character-length bucket --
    _BUCKETS = [("<1000", 0, 1000), ("1000–1500", 1000, 1500),
                ("1500–2000", 1500, 2000), (">2000", 2000, 99999)]
    len_groups: dict[str, list[int]] = {}
    for p in all_posts:
        chars = int(p.get("length_chars", 0) or 0)
        eng = int(p.get("engagement", 0) or 0)
        for label, lo, hi in _BUCKETS:
            if lo <= chars < hi:
                len_groups.setdefault(label, []).append(eng)
                break

    len_medians = {
        label: int(_median(vals))
        for label, vals in len_groups.items()
        if len(vals) >= 5
    }
    if len_medians:
        best_len = max(len_medians, key=lambda k: len_medians[k])
        insights.append(
            f"Longueur optimale sur ce corpus : {best_len} caractères "
            f"(engagement médian {len_medians[best_len]})"
        )

    # -- CTA effect (organic likes vs inflated comments) --
    cta_posts = [p for p in all_posts if p.get("has_cta")]
    no_cta_posts = [p for p in all_posts if not p.get("has_cta")]
    if len(cta_posts) >= 3 and len(no_cta_posts) >= 3:
        cta_comments = int(_median([int(p.get("comments", 0) or 0) for p in cta_posts]))
        no_cta_comments = int(_median([int(p.get("comments", 0) or 0) for p in no_cta_posts]))
        cta_likes = int(_median([int(p.get("likes", 0) or 0) for p in cta_posts]))
        no_cta_likes = int(_median([int(p.get("likes", 0) or 0) for p in no_cta_posts]))
        if cta_comments > no_cta_comments * 1.5:
            insights.append(
                f"CTA commentaire : gonfle les commentaires ({cta_comments} vs {no_cta_comments} médianes) "
                f"mais pas les likes ({cta_likes} vs {no_cta_likes}) — engagement organique à surveiller"
            )
        elif no_cta_likes > cta_likes * 1.2:
            insights.append(
                f"Engagement organique (sans CTA) : {no_cta_likes} likes médianes vs {cta_likes} avec CTA"
            )

    return insights


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
        "corpus_insights": _compute_corpus_insights(all_posts),
    }
    return top_posts, benchmark
