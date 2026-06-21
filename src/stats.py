"""Deterministic statistics over normalized posts."""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any

import pandas as pd


WEEKDAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

# En dessous, une cadence extrapolée n'a pas de sens (ex. 1 post daté → "7/semaine")
MIN_DATED_POSTS_FOR_CADENCE = 5


def compute_stats(
    posts: list[dict],
    profile: dict | None = None,
    exclude_recent_hours: int = 24,
) -> dict[str, Any]:
    df = pd.DataFrame(posts)
    if df.empty:
        return {"count": 0}

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
    else:
        df["date"] = pd.NaT

    # Posts <24h : métriques pas encore mûres, exclus du corpus d'engagement.
    # Les posts sans date restent inclus : on ne réduit jamais le corpus à cause
    # de dates manquantes (les stats et les patterns doivent porter sur les mêmes posts).
    cutoff = pd.Timestamp(datetime.now(timezone.utc)) - pd.Timedelta(hours=exclude_recent_hours)
    recent_mask = df["date"].notna() & (df["date"] > cutoff)
    excluded = int(recent_mask.sum())
    df_eng = df[~recent_mask] if (~recent_mask).any() else df

    # Corpus temporel : uniquement les posts datés et mûrs
    df_t = df_eng.dropna(subset=["date"]).copy()
    has_dates = not df_t.empty
    if has_dates:
        local = df_t["date"].dt.tz_convert("Europe/Paris")
        df_t["weekday"] = local.dt.weekday.map(lambda i: WEEKDAYS[i])
        df_t["hour"] = local.dt.hour

    span_days = max((df_t["date"].max() - df_t["date"].min()).days, 1) if has_dates else 0
    posts_per_week = (
        round(len(df_t) / (span_days / 7), 2)
        if span_days and len(df_t) >= MIN_DATED_POSTS_FOR_CADENCE
        else None
    )

    weekday_counts = df_t["weekday"].value_counts().to_dict() if has_dates else {}
    hour_counts = df_t["hour"].value_counts().sort_index().to_dict() if has_dates else {}

    format_mix = (df_eng["format"].value_counts(normalize=True) * 100).round(1).to_dict()
    format_counts = df_eng["format"].value_counts().to_dict()

    top_by_engagement = (
        df_eng.sort_values("engagement", ascending=False)
        .head(5)[["url", "text", "format", "likes", "comments", "reposts", "engagement"]]
        .to_dict(orient="records")
    )
    top_by_comments = (
        df_eng.sort_values("comments", ascending=False)
        .head(5)[["url", "text", "format", "likes", "comments", "reposts", "engagement"]]
        .to_dict(orient="records")
    )

    # Engagement "organique" = likes + reposts. Les commentaires sont gonflés
    # par les CTA "commente X pour recevoir" (lead magnets) sur ces profils.
    organic = df_eng["likes"] + df_eng["reposts"]

    follower_count = int((profile or {}).get("follower_count", 0) or 0)
    engagement_rate = None
    comments_rate = None
    organic_rate = None
    if follower_count > 0:
        engagement_rate = round((df_eng["engagement"].median() / follower_count) * 100, 3)
        comments_rate = round((df_eng["comments"].median() / follower_count) * 100, 3)
        organic_rate = round((organic.median() / follower_count) * 100, 3)

    return {
        "count": int(len(df_eng)),
        "dated_count": int(len(df_t)),
        "excluded_recent_count": excluded,
        "span_days": int(span_days),
        "posts_per_week": posts_per_week,
        "weekday_distribution": weekday_counts,
        "hour_distribution": {int(k): int(v) for k, v in hour_counts.items()},
        "format_mix_pct": format_mix,
        "format_counts": format_counts,
        "engagement": {
            "mean_likes": round(df_eng["likes"].mean(), 1),
            "median_likes": int(df_eng["likes"].median()),
            "mean_comments": round(df_eng["comments"].mean(), 1),
            "median_comments": int(df_eng["comments"].median()),
            "mean_reposts": round(df_eng["reposts"].mean(), 1),
            "median_reposts": int(df_eng["reposts"].median()),
            "mean_engagement": round(df_eng["engagement"].mean(), 1),
            "median_engagement": int(df_eng["engagement"].median()),
            "median_organic": int(organic.median()),
            "engagement_rate_pct": engagement_rate,
            "comments_rate_pct": comments_rate,
            "organic_rate_pct": organic_rate,
        },
        "length": {
            "mean_words": round(df_eng["length_words"].mean(), 1),
            "median_words": int(df_eng["length_words"].median()),
            "mean_chars": round(df_eng["length_chars"].mean(), 1),
        },
        "top_posts": top_by_engagement,
        "top_posts_by_comments": top_by_comments,
        "first_post_date": df_t["date"].min().isoformat() if has_dates else "",
        "last_post_date": df_t["date"].max().isoformat() if has_dates else "",
    }


def cta_breakdown(enriched_posts: list[dict]) -> dict[str, Any]:
    """Compare median engagement on posts with vs without CTA."""
    if not enriched_posts:
        return {}
    df = pd.DataFrame(enriched_posts)
    if "has_cta" not in df.columns:
        return {}
    out: dict[str, Any] = {}
    for label, mask in [("with_cta", df["has_cta"] == True), ("without_cta", df["has_cta"] == False)]:
        sub = df[mask]
        out[label] = {
            "count": int(len(sub)),
            "median_likes": int(sub["likes"].median()) if len(sub) else 0,
            "median_comments": int(sub["comments"].median()) if len(sub) else 0,
            "median_reposts": int(sub["reposts"].median()) if len(sub) else 0,
            "median_engagement": int(sub["engagement"].median()) if len(sub) else 0,
        }
    return out


def compute_ig_stats(posts: list[dict], profile: dict | None = None) -> dict[str, Any]:
    """Compute Instagram-specific stats on top of the generic compute_stats.

    Adds:
    - engagement.median_views / mean_views
    - engagement.virality_ratio (median_views / follower_count)
    - engagement.quality_ratio (median_engagement / median_views)
    - top_posts_by_views (top 5 reels by view count)
    - video_duration (median_s, mean_s, distribution by bucket)
    """
    stats = compute_stats(posts, profile=profile)
    if not posts:
        return stats

    df = pd.DataFrame(posts)
    if df.empty:
        return stats

    # Rebuild the same "exclude recent" mask as compute_stats to be consistent
    from datetime import datetime, timezone
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
    else:
        df["date"] = pd.NaT
    cutoff = pd.Timestamp(datetime.now(timezone.utc)) - pd.Timedelta(hours=24)
    recent_mask = df["date"].notna() & (df["date"] > cutoff)
    df_eng = df[~recent_mask] if (~recent_mask).any() else df

    # --- Views metrics ---
    if "views" in df_eng.columns:
        views_series = df_eng["views"].fillna(0).astype(float)
        median_views = int(views_series.median())
        mean_views = float(views_series.mean())
        eng = stats.setdefault("engagement", {})
        eng["median_views"] = median_views
        eng["mean_views"] = round(mean_views, 1)

        follower_count = int((profile or {}).get("follower_count", 0) or 0)
        if follower_count > 0 and median_views > 0:
            eng["virality_ratio"] = round(median_views / follower_count, 4)
        else:
            eng["virality_ratio"] = None

        median_engagement = eng.get("median_engagement", 0)
        if median_views > 0:
            eng["quality_ratio"] = round(median_engagement / median_views, 4)
        else:
            eng["quality_ratio"] = None

    # --- Top 5 by views ---
    if "views" in df_eng.columns:
        top5_cols = [c for c in ["url", "text", "format", "likes", "comments", "views", "engagement"] if c in df_eng.columns]
        top5 = (
            df_eng.sort_values("views", ascending=False)
            .head(5)[top5_cols]
            .to_dict(orient="records")
        )
        stats["top_posts_by_views"] = top5

    # --- Video duration ---
    if "video_duration_s" in df_eng.columns:
        dur = df_eng["video_duration_s"].dropna()
        if not dur.empty:
            def _dur_bucket(s: float) -> str:
                if s < 30:
                    return "<30s"
                if s < 60:
                    return "30–60s"
                if s < 90:
                    return "60–90s"
                return ">90s"
            buckets = dur.map(_dur_bucket)
            bucket_order = ["<30s", "30–60s", "60–90s", ">90s"]
            dist = {b: int((buckets == b).sum()) for b in bucket_order if (buckets == b).any()}
            stats["video_duration"] = {
                "median_s": round(float(dur.median()), 1),
                "mean_s": round(float(dur.mean()), 1),
                "distribution": dist,
            }

    return stats


def engagement_by_classification(
    classifications: list[dict],
    posts: list[dict],
    key: str,
) -> list[dict[str, Any]]:
    """Median engagement grouped by a classification field (stage, hook_type)."""
    groups: dict[str, list[int]] = {}
    for c in classifications:
        i = c.get("index")
        value = c.get(key)
        if i is None or value is None or i >= len(posts):
            continue
        groups.setdefault(str(value), []).append(int(posts[i].get("engagement", 0)))

    rows = [
        {
            key: value,
            "count": len(vals),
            "median_engagement": int(median(vals)),
            "max_engagement": int(max(vals)),
        }
        for value, vals in groups.items()
    ]
    rows.sort(key=lambda r: -r["median_engagement"])
    return rows
