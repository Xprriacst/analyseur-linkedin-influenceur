"""Build benchmark inputs (top posts + summary) from a user's corpus.

Extracted from `api.py` so the same logic is reusable by the daily-idea cron
(`src/daily_ideas.py`), which has no FastAPI request context. Behaviour is
unchanged: `api.py` keeps thin `_enrich_influencers` / `_build_benchmark`
aliases that delegate here.
"""
from __future__ import annotations

import statistics as _statistics
from collections import Counter

from src.patterns import analyze_patterns
from src.stats import compute_stats


# Minimum posts per group to assert a data-driven insight.
_MIN_N = 5

_FORMAT_LABELS: dict[str, str] = {
    "text": "texte seul",
    "image": "image",
    "carousel": "carrousel",
    "video": "vidéo",
    "document": "document",
    "poll": "sondage",
}

_HOOK_LABELS: dict[str, str] = {
    "stat": "Chiffre choc",
    "list": "Liste numérotée",
    "question": "Question",
    "contrarian": "Point de vue contrarian",
    "result": "Résultat / preuve",
    "bold_claim": "Affirmation tranchée",
    "story": "Histoire",
}


def _compute_corpus_insights(influencers: list[dict]) -> list[str]:
    """Derive data-driven insights from the actual corpus.

    Returns an empty list when the corpus is too thin to assert anything.
    All figures come from real data; nothing is hardcoded.
    """
    all_posts: list[dict] = []
    for inf in influencers:
        enriched = inf["patterns"].get("posts_enriched", inf.get("posts", []))
        all_posts.extend(enriched)

    if len(all_posts) < _MIN_N:
        return []

    insights: list[str] = []

    # ── 1. Engagement by format ──────────────────────────────────────────────
    fmt_groups: dict[str, list[int]] = {}
    for p in all_posts:
        fmt = p.get("format", "")
        eng = int(p.get("engagement", 0))
        if fmt:
            fmt_groups.setdefault(fmt, []).append(eng)

    valid_fmts = {f: v for f, v in fmt_groups.items() if len(v) >= _MIN_N}
    if len(valid_fmts) >= 2:
        best_fmt = max(valid_fmts, key=lambda f: _statistics.median(valid_fmts[f]))
        worst_fmt = min(valid_fmts, key=lambda f: _statistics.median(valid_fmts[f]))
        best_med = _statistics.median(valid_fmts[best_fmt])
        worst_med = _statistics.median(valid_fmts[worst_fmt])
        if worst_med > 0 and best_med / worst_med >= 1.3:
            ratio = best_med / worst_med
            insights.append(
                f"Format le plus engageant : {_FORMAT_LABELS.get(best_fmt, best_fmt)} "
                f"(médiane {int(best_med)} vs {int(worst_med)} pour {_FORMAT_LABELS.get(worst_fmt, worst_fmt)}, "
                f"×{ratio:.1f} — {len(valid_fmts[best_fmt])} posts)"
            )

    # ── 2. Engagement by length bucket ──────────────────────────────────────
    len_groups: dict[str, list[int]] = {}
    for p in all_posts:
        chars = int(p.get("length_chars", 0) or 0)
        eng = int(p.get("engagement", 0))
        if chars > 0:
            if chars < 1000:
                bucket = "<1 000"
            elif chars < 1500:
                bucket = "1 000-1 500"
            elif chars < 2000:
                bucket = "1 500-2 000"
            else:
                bucket = "2 000+"
            len_groups.setdefault(bucket, []).append(eng)

    valid_lens = {b: v for b, v in len_groups.items() if len(v) >= _MIN_N}
    if len(valid_lens) >= 2:
        best_len = max(valid_lens, key=lambda b: _statistics.median(valid_lens[b]))
        best_len_med = int(_statistics.median(valid_lens[best_len]))
        insights.append(
            f"Longueur la plus performante : {best_len} caractères "
            f"(médiane {best_len_med} eng — {len(valid_lens[best_len])} posts)"
        )
    else:
        chars_vals = [int(p.get("length_chars", 0)) for p in all_posts if p.get("length_chars", 0)]
        if chars_vals:
            insights.append(f"Longueur médiane du corpus : {int(_statistics.median(chars_vals))} caractères")

    # ── 3. Engagement by hook type (heuristic) ──────────────────────────────
    hook_groups: dict[str, list[int]] = {}
    for p in all_posts:
        hook = p.get("hook_type", "other")
        eng = int(p.get("engagement", 0))
        if hook and hook != "other":
            hook_groups.setdefault(hook, []).append(eng)

    valid_hooks = {h: v for h, v in hook_groups.items() if len(v) >= _MIN_N}
    if valid_hooks:
        best_hook = max(valid_hooks, key=lambda h: _statistics.median(valid_hooks[h]))
        best_hook_med = int(_statistics.median(valid_hooks[best_hook]))
        insights.append(
            f"Hook le plus performant : {_HOOK_LABELS.get(best_hook, best_hook)} "
            f"(médiane {best_hook_med} eng — {len(valid_hooks[best_hook])} posts)"
        )

    # Mention alpha hook (high potential, under-used)
    all_hook_counts = Counter(p.get("hook_type", "") for p in all_posts if p.get("hook_type", ""))
    for alpha in ["question", "contrarian", "stat"]:
        if alpha not in valid_hooks and all_hook_counts.get(alpha, 0) < 3:
            insights.append(
                f"Hook '{_HOOK_LABELS.get(alpha, alpha)}' quasi absent du corpus "
                f"({all_hook_counts.get(alpha, 0)} posts) — potentiel de différenciation."
            )
            break

    # ── 4. CTA effect (organic) ──────────────────────────────────────────────
    cta_eng = [int(p.get("engagement", 0)) for p in all_posts if p.get("has_cta")]
    no_cta_eng = [int(p.get("engagement", 0)) for p in all_posts if not p.get("has_cta")]
    if len(cta_eng) >= _MIN_N and len(no_cta_eng) >= _MIN_N:
        cta_med = int(_statistics.median(cta_eng))
        no_cta_med = int(_statistics.median(no_cta_eng))
        if no_cta_med > 0:
            ratio = cta_med / no_cta_med
            if ratio >= 1.2:
                insights.append(
                    f"Posts avec CTA commentaire : médiane {cta_med} vs {no_cta_med} sans CTA "
                    f"(×{ratio:.1f} — attention : les CTA gonflent les commentaires, pas l'organique)."
                )
            elif ratio < 0.85:
                insights.append(
                    f"Posts sans CTA commentaire plus performants sur ce corpus "
                    f"(médiane {no_cta_med} vs {cta_med} avec CTA)."
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

    top_posts = sorted(all_posts, key=lambda x: x.get("engagement", 0), reverse=True)[:6]
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
        "corpus_insights": _compute_corpus_insights(influencers),
    }
    return top_posts, benchmark
