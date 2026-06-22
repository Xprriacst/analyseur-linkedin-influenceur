"""Normalize Apify Instagram actor output into a consistent internal shape."""
from __future__ import annotations

import re
from typing import Any

from src.normalize import _parse_date


def _get(d: dict, *keys, default=None):
    """Get first matching key from a dict (supports dotted paths)."""
    for k in keys:
        if "." in k:
            cur: Any = d
            ok = True
            for part in k.split("."):
                if isinstance(cur, dict) and part in cur and cur[part] is not None:
                    cur = cur[part]
                else:
                    ok = False
                    break
            if ok:
                return cur
        elif k in d and d[k] is not None:
            return d[k]
    return default


def _extract_hashtags_from_text(text: str) -> list[str]:
    """Extract hashtags from caption text."""
    return re.findall(r"#(\w+)", text or "")


def _detect_ig_format(raw: dict) -> str:
    """Detect format (reel, carousel, image) from the Apify reel output."""
    product_type = (raw.get("productType") or "").lower()
    media_type = (raw.get("type") or "").lower()

    if product_type in ("clips", "reels") or media_type == "video":
        return "reel"

    # Multiple sidecar images = carousel
    images = raw.get("images") or raw.get("sidecarImages") or []
    if isinstance(images, list) and len(images) > 1:
        return "carousel"

    if images or media_type == "image":
        return "image"

    # Default: if it has a video duration, it's a reel
    if raw.get("videoDuration") or raw.get("videoViewCount") or raw.get("videoPlayCount"):
        return "reel"

    return "image"


def normalize_ig_reels(raw: list[dict]) -> list[dict]:
    """Map Apify Instagram reel/post output to the internal post model.

    Returns a list of dicts with consistent keys matching what stats.py expects.
    """
    out = []
    for r in raw:
        text = (r.get("caption") or "").strip()
        transcript = ""
        try:
            transcript = (r.get("transcript") or "").strip()
        except Exception:
            pass

        date = _parse_date(_get(r, "timestamp", "takenAt", "postedAt"))

        fmt = _detect_ig_format(r)

        likes = int(_get(r, "likesCount", "likeCount", "likes", default=0) or 0)
        comments = int(_get(r, "commentsCount", "commentCount", "comments", default=0) or 0)
        views = int(_get(r, "videoViewCount", "videoPlayCount", "viewCount", default=0) or 0)
        video_duration_s = None
        try:
            vd = r.get("videoDuration")
            if vd is not None:
                video_duration_s = float(vd)
        except (TypeError, ValueError):
            pass

        # Hashtags: from field or extracted from caption
        raw_hashtags = r.get("hashtags")
        if isinstance(raw_hashtags, list) and raw_hashtags:
            hashtags = [str(h).lstrip("#") for h in raw_hashtags if h]
        else:
            hashtags = _extract_hashtags_from_text(text)

        # Music info
        music = r.get("musicInfo") or r.get("music") or None

        url = _get(r, "url", "postUrl", "shortcode", default="")
        if url and not url.startswith("http") and url:
            url = f"https://www.instagram.com/reel/{url}/"

        engagement = likes + comments

        out.append({
            "url": url,
            "text": text,
            "transcript": transcript,
            "date": date,
            "format": fmt,
            "likes": likes,
            "comments": comments,
            "views": views,
            "video_duration_s": video_duration_s,
            "hashtags": hashtags,
            "music": music,
            "engagement": engagement,
            "length_chars": len(text),
            "length_words": len(text.split()) if text else 0,
            # Instagram posts don't have "reposts" in the LinkedIn sense
            "reposts": 0,
        })

    # Filter out completely empty posts (no text and no views)
    out = [p for p in out if p["text"] or p["views"] > 0]
    return out


def normalize_ig_profile(raw: dict | None) -> dict:
    """Map Instagram profile scraper output to the internal profile model."""
    if not raw:
        return {}
    username = _get(raw, "username", "userName", default="")
    name = _get(raw, "fullName", "full_name", "name", default="") or username
    return {
        "name": name,
        "headline": _get(raw, "businessCategoryName", "category", default=""),
        "summary": _get(raw, "biography", "bio", default=""),
        "location": "",
        "follower_count": int(_get(raw, "followersCount", "followerCount", "followers", default=0) or 0),
        "connections_count": int(_get(raw, "followingCount", "followsCount", "following", default=0) or 0),
        "creator_mode": bool(_get(raw, "isCreator", default=False)),
        "influencer": bool(_get(raw, "isVerified", "verified", default=False)),
        "profile_url": f"https://www.instagram.com/{username}/" if username else "",
        # Instagram-specific extras (stored in profile for report rendering)
        "posts_count": int(_get(raw, "postsCount", "mediaCount", default=0) or 0),
        "is_business": bool(_get(raw, "isBusinessAccount", default=False)),
        "business_category": _get(raw, "businessCategoryName", default=""),
    }
