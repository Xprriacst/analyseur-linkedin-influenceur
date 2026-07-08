"""Tendances transverses calculées sur l'ensemble des rapports d'un utilisateur.

Agrégation pure (aucun appel LLM) : chaque post est comparé à la médiane
d'engagement de son propre influenceur (lift), ce qui neutralise les écarts de
taille d'audience, puis les lifts sont agrégés en médiane par format, longueur
et jour de publication. Les croisements qui dépendent des classifications LLM
(accroches, funnel, CTA) sont repris des stats déjà stockées dans chaque
rapport (`analyses.stats`) — le mapping classification → post n'est pas
reconstruit ici, seuls les agrégats par rapport font foi.
"""
from __future__ import annotations

import datetime
from statistics import median
from urllib.parse import unquote

from src.report import FORMAT_LABELS, HOOK_LABELS, STAGE_LABELS

# Seuils : en dessous, les « tendances » seraient de l'anecdote.
MIN_REPORTS = 3
MIN_POSTS = 40
_MIN_POSTS_PER_HOOK = 2      # au sein d'un rapport
_MIN_REPORTS_PER_HOOK = 3    # nombre de rapports où le hook apparaît
_MIN_POSTS_PER_FORMAT = 8    # sur tout le corpus
_MIN_POSTS_PER_BUCKET = 10
_MIN_CTA_POSTS = 3           # posts avec CTA dans un rapport pour compter le ratio
_TOP_ACCOUNTS = 6            # comptes retenus pour la part des commentaires
_HIGH_FREQ_POSTS_PER_WEEK = 7

_LENGTH_BUCKETS = [
    (0, 150, "Moins de 150 mots"),
    (150, 250, "150 à 250 mots"),
    (250, 350, "250 à 350 mots"),
    (350, 10**9, "350 mots et plus"),
]
_WEEKDAYS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

_STAGE_PUBLIC_LABELS = {
    "BOFU": "Offre / ressource (conversion)",
    "MOFU": "Éducation / méthode",
    "TOFU": "Visibilité large (attraction)",
}


def _lift_pct(value: float, base: float) -> int:
    return round((value / base - 1) * 100)


def _parse_dt(raw: str | None) -> datetime.datetime | None:
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


def compute_trends(corpus: list[dict], analyses: list[dict]) -> dict:
    """Agrège corpus (posts bruts) + stats des rapports en tendances lisibles.

    `corpus` : sortie de db.get_user_corpus — [{handle, profile, posts}].
    `analyses` : lignes analyses (id, handle, influencer_id, updated_at, stats,
    influencers{name, follower_count}) — une par influenceur.
    """
    posts_by_handle = {inf["handle"]: inf.get("posts") or [] for inf in corpus}
    profile_by_handle = {inf["handle"]: inf.get("profile") or {} for inf in corpus}

    # Médiane d'engagement par influenceur = base de normalisation des lifts.
    base_by_handle: dict[str, float] = {}
    for handle, posts in posts_by_handle.items():
        engs = [int(p.get("engagement") or 0) for p in posts]
        if engs:
            base_by_handle[handle] = float(median(engs))

    post_count = sum(len(p) for p in posts_by_handle.values())
    report_count = len(analyses)
    updated = [d for d in (_parse_dt(a.get("updated_at")) for a in analyses) if d]
    meta = {
        "report_count": report_count,
        "post_count": post_count,
        "updated_at": max(updated).isoformat() if updated else None,
    }

    ranking = _ranking(analyses, base_by_handle, profile_by_handle)
    if report_count < MIN_REPORTS or post_count < MIN_POSTS:
        return {**meta, "insufficient": True, "min_reports": MIN_REPORTS, "ranking": ranking}

    return {
        **meta,
        "insufficient": False,
        "cta": _cta_effect(analyses),
        "comments_share": _comments_share(posts_by_handle, base_by_handle),
        "hooks": _report_level_lifts(analyses, "hook_engagement", "hook_type", HOOK_LABELS),
        "stages": _report_level_lifts(
            analyses, "stage_engagement", "stage", _STAGE_PUBLIC_LABELS, min_reports=2
        ),
        "formats": _format_lifts(posts_by_handle, base_by_handle),
        "length_buckets": _length_lifts(posts_by_handle, base_by_handle),
        "weekdays": _weekday_lifts(posts_by_handle, base_by_handle),
        "benchmark": _benchmark(analyses, profile_by_handle),
        "ranking": ranking,
    }


def _report_base(analysis: dict) -> float:
    stats = analysis.get("stats") or {}
    return float((stats.get("engagement") or {}).get("median_engagement") or 0)


def _report_level_lifts(
    analyses: list[dict],
    stats_key: str,
    entry_key: str,
    labels: dict[str, str],
    min_reports: int = _MIN_REPORTS_PER_HOOK,
) -> list[dict]:
    """Lifts par hook/stage à partir des croisements stockés dans chaque rapport."""
    lifts: dict[str, list[float]] = {}
    posts: dict[str, int] = {}
    wins: dict[str, int] = {}
    for analysis in analyses:
        base = _report_base(analysis)
        if base <= 0:
            continue
        for entry in (analysis.get("stats") or {}).get(stats_key) or []:
            key = entry.get(entry_key)
            count = int(entry.get("count") or 0)
            med = entry.get("median_engagement")
            if not key or count < _MIN_POSTS_PER_HOOK or med is None:
                continue
            lift = float(med) / base
            lifts.setdefault(key, []).append(lift)
            posts[key] = posts.get(key, 0) + count
            wins[key] = wins.get(key, 0) + (1 if lift >= 1 else 0)
    rows = [
        {
            "key": key,
            "label": labels.get(key, key),
            "lift_pct": _lift_pct(median(values), 1.0),
            "reports": len(values),
            "wins": wins.get(key, 0),
            "posts": posts.get(key, 0),
        }
        for key, values in lifts.items()
        if len(values) >= min_reports
    ]
    rows.sort(key=lambda r: r["lift_pct"], reverse=True)
    return rows


def _normalized_posts(posts_by_handle: dict, base_by_handle: dict):
    for handle, posts in posts_by_handle.items():
        base = base_by_handle.get(handle) or 0
        if base <= 0:
            continue
        for post in posts:
            yield post, int(post.get("engagement") or 0) / base


def _format_lifts(posts_by_handle: dict, base_by_handle: dict) -> list[dict]:
    groups: dict[str, list[float]] = {}
    for post, norm in _normalized_posts(posts_by_handle, base_by_handle):
        fmt = post.get("format") or "text"
        groups.setdefault(fmt, []).append(norm)
    rows = [
        {
            "key": fmt,
            "label": FORMAT_LABELS.get(fmt, fmt),
            "lift_pct": _lift_pct(median(values), 1.0),
            "posts": len(values),
        }
        for fmt, values in groups.items()
        if len(values) >= _MIN_POSTS_PER_FORMAT
    ]
    rows.sort(key=lambda r: r["lift_pct"], reverse=True)
    return rows


def _length_lifts(posts_by_handle: dict, base_by_handle: dict) -> list[dict]:
    groups: dict[str, list[float]] = {label: [] for _, _, label in _LENGTH_BUCKETS}
    for post, norm in _normalized_posts(posts_by_handle, base_by_handle):
        if (post.get("format") or "") == "repost":
            continue  # la longueur d'un repost est celle de l'auteur d'origine
        words = int(post.get("length_words") or 0)
        for lo, hi, label in _LENGTH_BUCKETS:
            if lo <= words < hi:
                groups[label].append(norm)
                break
    return [
        {"label": label, "lift_pct": _lift_pct(median(values), 1.0), "posts": len(values)}
        for label, values in groups.items()
        if len(values) >= _MIN_POSTS_PER_BUCKET
    ]


def _weekday_lifts(posts_by_handle: dict, base_by_handle: dict) -> list[dict]:
    groups: dict[int, list[float]] = {}
    for post, norm in _normalized_posts(posts_by_handle, base_by_handle):
        dt = _parse_dt(post.get("date"))
        if not dt:
            continue
        groups.setdefault(dt.weekday(), []).append(norm)
    return [
        {
            "label": _WEEKDAYS_FR[day],
            "lift_pct": _lift_pct(median(values), 1.0),
            "posts": len(values),
        }
        for day, values in sorted(groups.items())
        if len(values) >= _MIN_POSTS_PER_BUCKET
    ]


def _cta_effect(analyses: list[dict]) -> dict | None:
    """Effet des appels à commenter, agrégé sur les rapports qui en contiennent."""
    ratios: list[float] = []
    posts_with = posts_without = winning = 0
    for analysis in analyses:
        cta = (analysis.get("stats") or {}).get("cta_effect") or {}
        with_cta = cta.get("with_cta") or {}
        without = cta.get("without_cta") or {}
        n_with = int(with_cta.get("count") or 0)
        base = float(without.get("median_engagement") or 0)
        if n_with < _MIN_CTA_POSTS or base <= 0:
            continue
        ratio = float(with_cta.get("median_engagement") or 0) / base
        ratios.append(ratio)
        posts_with += n_with
        posts_without += int(without.get("count") or 0)
        winning += 1 if ratio > 1 else 0
    if not ratios:
        return None
    return {
        "accounts": len(ratios),
        "winning": winning,
        "ratio_median": round(median(ratios), 1),
        "ratio_min": round(min(ratios), 1),
        "ratio_max": round(max(ratios), 1),
        "posts_with": posts_with,
        "posts_without": posts_without,
    }


def _comments_share(posts_by_handle: dict, base_by_handle: dict) -> dict | None:
    """Part des commentaires dans l'engagement des comptes les plus performants."""
    tops = sorted(
        (h for h, b in base_by_handle.items() if b > 0 and len(posts_by_handle.get(h) or []) >= 5),
        key=lambda h: base_by_handle[h],
        reverse=True,
    )[:_TOP_ACCOUNTS]
    shares = []
    for handle in tops:
        posts = posts_by_handle[handle]
        total_eng = sum(int(p.get("engagement") or 0) for p in posts)
        total_comments = sum(int(p.get("comments") or 0) for p in posts)
        if total_eng > 0:
            shares.append(100 * total_comments / total_eng)
    if len(shares) < 3:
        return None
    return {
        "top_accounts": len(shares),
        "share_median_pct": round(median(shares)),
        "share_max_pct": round(max(shares)),
    }


def _benchmark(analyses: list[dict], profile_by_handle: dict) -> dict | None:
    accounts = []
    for analysis in analyses:
        stats = analysis.get("stats") or {}
        eng = stats.get("engagement") or {}
        rate = eng.get("engagement_rate_pct")
        followers = _followers(analysis, profile_by_handle)
        if rate is None or not followers:
            continue
        accounts.append({
            "name": _display_name(analysis),
            "followers": followers,
            "rate_pct": float(rate),
            "posts_per_week": float(stats.get("posts_per_week") or 0),
        })
    if len(accounts) < 3:
        return None
    best = max(accounts, key=lambda a: a["rate_pct"])
    biggest = max(accounts, key=lambda a: a["followers"])
    high_freq = [a for a in accounts if a["posts_per_week"] >= _HIGH_FREQ_POSTS_PER_WEEK]
    result = {
        "best": {k: best[k] for k in ("name", "followers", "rate_pct")},
        "biggest": {k: biggest[k] for k in ("name", "followers", "rate_pct")},
    }
    if high_freq:
        result["high_freq"] = {
            "threshold": _HIGH_FREQ_POSTS_PER_WEEK,
            "accounts": len(high_freq),
            "max_rate_pct": max(a["rate_pct"] for a in high_freq),
        }
    return result


def _followers(analysis: dict, profile_by_handle: dict) -> int:
    inf = analysis.get("influencers") or {}
    if isinstance(inf, list):
        inf = inf[0] if inf else {}
    followers = inf.get("follower_count") or 0
    if not followers:
        profile = profile_by_handle.get(analysis.get("handle")) or {}
        followers = profile.get("follower_count") or 0
    try:
        return int(followers)
    except Exception:
        return 0


def _display_name(analysis: dict) -> str:
    inf = analysis.get("influencers") or {}
    if isinstance(inf, list):
        inf = inf[0] if inf else {}
    name = (inf.get("name") or "").strip()
    return name or unquote(analysis.get("handle") or "")


def _ranking(analyses: list[dict], base_by_handle: dict, profile_by_handle: dict) -> list[dict]:
    rows = []
    for analysis in analyses:
        stats = analysis.get("stats") or {}
        eng = stats.get("engagement") or {}
        handle = analysis.get("handle") or ""
        median_eng = eng.get("median_engagement")
        if median_eng is None:
            median_eng = base_by_handle.get(handle) or 0
        rows.append({
            "influencer_id": analysis.get("influencer_id"),
            "analysis_id": analysis.get("id"),
            "handle": unquote(handle),
            "name": _display_name(analysis),
            "followers": _followers(analysis, profile_by_handle),
            "median_engagement": round(float(median_eng)),
            "engagement_rate_pct": eng.get("engagement_rate_pct"),
            "posts": int(stats.get("count") or 0),
        })
    rows.sort(key=lambda r: r["median_engagement"], reverse=True)
    return rows
