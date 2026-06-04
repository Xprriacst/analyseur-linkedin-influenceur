"""Normalize the various Apify actor schemas into a consistent post shape."""
from __future__ import annotations

from datetime import datetime
from typing import Any


def _get(d: dict, *keys, default=None):
    """Get a key from a dict. Supports dotted paths like 'engagement.likes'."""
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


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _detect_format(post: dict) -> str:
    if _get(post, "video", "videoUrl"):
        return "video"
    images = _get(post, "images", "imageUrls", default=[]) or []
    if isinstance(images, list) and len(images) > 1:
        return "carousel"
    if images:
        return "image"
    if _get(post, "article", "articleUrl"):
        return "article"
    if _get(post, "document", "documentUrl"):
        return "document"
    if _get(post, "isRepost", "reposted", default=False):
        return "repost"
    return "text"


def normalize_posts(raw: list[dict]) -> list[dict]:
    out = []
    for p in raw:
        text = _get(p, "text", "postText", "content", "commentary", default="") or ""
        date = _parse_date(
            _get(p, "postedAt.timestamp", "postedAt", "publishedAt", "date", "time", "postedAtTimestamp", "posted_at.date")
        )
        posted_ago = _get(p, "postedAt.postedAgoText", "postedAgoText", "posted_at.relative", default="") or ""
        likes = int(_get(p, "engagement.likes", "numLikes", "likes", "likeCount", "reactions", "stats.like", "stats.total_reactions", default=0) or 0)
        comments = int(_get(p, "engagement.comments", "numComments", "comments", "commentCount", "stats.comments", default=0) or 0)
        reposts = int(_get(p, "engagement.shares", "numShares", "shares", "reposts", "repostCount", "stats.reposts", default=0) or 0)
        url = _get(p, "url", "postUrl", "link", default="")

        out.append(
            {
                "url": url,
                "text": text.strip(),
                "date": date,
                "posted_ago": posted_ago,
                "format": _detect_format(p),
                "likes": likes,
                "comments": comments,
                "reposts": reposts,
                "engagement": likes + comments + reposts,
                "length_chars": len(text),
                "length_words": len(text.split()),
            }
        )
    out = [p for p in out if p["text"] or p["format"] != "text"]
    return out


def normalize_profile(raw: dict | None) -> dict:
    """Normalize the profile-scraper output."""
    if not raw:
        return {}
    return {
        "name": _get(raw, "fullName", "name", "displayName", default=""),
        "headline": _get(raw, "headline", default=""),
        "summary": _get(raw, "summary", "about", default=""),
        "location": _get(raw, "geoLocationName", "location", "locationName", default=""),
        "follower_count": int(_get(raw, "followerCount", "followers", default=0) or 0),
        "connections_count": int(_get(raw, "connectionsCount", "connections", default=0) or 0),
        "creator_mode": bool(_get(raw, "creator", default=False)),
        "influencer": bool(_get(raw, "influencer", default=False)),
        "profile_url": _get(raw, "url", "profileUrl", "linkedinUrl", default=""),
    }
