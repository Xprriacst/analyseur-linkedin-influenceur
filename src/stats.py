"""Deterministic statistics over normalized posts."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd


WEEKDAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def compute_stats(
    posts: list[dict],
    profile: dict | None = None,
    exclude_recent_hours: int = 24,
) -> dict[str, Any]:
    df = pd.DataFrame(posts)
    if df.empty:
        return {"count": 0}

    df_all = df.copy()
    df_dates = df.dropna(subset=["date"]).copy()
    df_dates["date"] = pd.to_datetime(df_dates["date"], utc=True, errors="coerce")
    df_dates = df_dates.dropna(subset=["date"])

    excluded = 0
    if not df_dates.empty:
        cutoff = pd.Timestamp(datetime.now(timezone.utc) - timedelta(hours=exclude_recent_hours))
        df_mature = df_dates[df_dates["date"] <= cutoff].copy()
        excluded = len(df_dates) - len(df_mature)
        if not df_mature.empty:
            df = df_mature
        else:
            df = df_dates
    else:
        df = df_all

    has_dates = "date" in df.columns and not df["date"].isna().all()
    if has_dates:
        df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
        df = df.dropna(subset=["date"])
        df["weekday"] = df["date"].dt.weekday.map(lambda i: WEEKDAYS[i])
        df["hour"] = df["date"].dt.hour

    span_days = max((df["date"].max() - df["date"].min()).days, 1) if has_dates and not df.empty else 0
    posts_per_week = round(len(df) / (span_days / 7), 2) if span_days else None

    weekday_counts = df["weekday"].value_counts().to_dict() if has_dates and not df.empty else {}
    hour_counts = df["hour"].value_counts().sort_index().to_dict() if has_dates and not df.empty else {}

    format_mix = (df["format"].value_counts(normalize=True) * 100).round(1).to_dict()
    format_counts = df["format"].value_counts().to_dict()

    top_by_engagement = (
        df.sort_values("engagement", ascending=False)
        .head(3)[["url", "text", "format", "likes", "comments", "reposts", "engagement"]]
        .to_dict(orient="records")
    )
    top_by_comments = (
        df.sort_values("comments", ascending=False)
        .head(5)[["url", "text", "format", "likes", "comments", "reposts", "engagement"]]
        .to_dict(orient="records")
    )

    follower_count = int((profile or {}).get("follower_count", 0) or 0)
    engagement_rate = None
    comments_rate = None
    if follower_count > 0:
        engagement_rate = round(
            (df["engagement"].median() / follower_count) * 100, 3
        )
        comments_rate = round((df["comments"].median() / follower_count) * 100, 3)

    return {
        "count": int(len(df)),
        "excluded_recent_count": excluded,
        "span_days": int(span_days),
        "posts_per_week": posts_per_week,
        "weekday_distribution": weekday_counts,
        "hour_distribution": {int(k): int(v) for k, v in hour_counts.items()},
        "format_mix_pct": format_mix,
        "format_counts": format_counts,
        "engagement": {
            "mean_likes": round(df["likes"].mean(), 1),
            "median_likes": int(df["likes"].median()),
            "mean_comments": round(df["comments"].mean(), 1),
            "median_comments": int(df["comments"].median()),
            "mean_reposts": round(df["reposts"].mean(), 1),
            "median_reposts": int(df["reposts"].median()),
            "mean_engagement": round(df["engagement"].mean(), 1),
            "median_engagement": int(df["engagement"].median()),
            "engagement_rate_pct": engagement_rate,
            "comments_rate_pct": comments_rate,
        },
        "length": {
            "mean_words": round(df["length_words"].mean(), 1),
            "median_words": int(df["length_words"].median()),
            "mean_chars": round(df["length_chars"].mean(), 1),
        },
        "top_posts": top_by_engagement,
        "top_posts_by_comments": top_by_comments,
        "first_post_date": df["date"].min().isoformat() if has_dates and not df.empty else "",
        "last_post_date": df["date"].max().isoformat() if has_dates and not df.empty else "",
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
