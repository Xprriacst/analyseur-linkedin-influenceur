"""Supabase data-access layer.

The backend stays usable without Supabase configured (file-based fallback).
When a user JWT is provided, a per-request client is created so that Postgres
Row Level Security applies and data is scoped to that user automatically.
"""
from __future__ import annotations

import os
from typing import Any

try:
    from supabase import Client, create_client
except Exception:  # supabase not installed yet / import error
    Client = Any  # type: ignore
    create_client = None  # type: ignore


def _url() -> str | None:
    return os.environ.get("SUPABASE_URL")


def _anon_key() -> str | None:
    return os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_KEY")


def supabase_enabled() -> bool:
    return bool(create_client and _url() and _anon_key())


def client_for_token(access_token: str) -> "Client":
    """Return a Supabase client acting as the user identified by `access_token`.

    PostgREST requests carry the user JWT so RLS policies (user_id = auth.uid())
    are enforced server-side.
    """
    client = create_client(_url(), _anon_key())  # type: ignore[arg-type]
    client.postgrest.auth(access_token)
    return client


def get_user(access_token: str) -> dict | None:
    """Validate a JWT and return the matching user, or None if invalid."""
    if not supabase_enabled():
        return None
    try:
        client = create_client(_url(), _anon_key())  # type: ignore[arg-type]
        resp = client.auth.get_user(access_token)
    except Exception:
        return None
    user = getattr(resp, "user", None)
    if not user:
        return None
    return {"id": user.id, "email": getattr(user, "email", None)}


def _influencer_row(user_id: str, result: dict) -> dict:
    profile = result.get("profile", {}) or {}
    return {
        "user_id": user_id,
        "handle": result["handle"],
        "name": profile.get("name"),
        "headline": profile.get("headline"),
        "summary": profile.get("summary"),
        "location": profile.get("location"),
        "follower_count": int(profile.get("follower_count", 0) or 0),
        "connections_count": int(profile.get("connections_count", 0) or 0),
        "creator_mode": bool(profile.get("creator_mode", False)),
        "is_influencer": bool(profile.get("influencer", False)),
        "profile_url": profile.get("profile_url"),
        "raw_profile": profile,
    }


def _post_rows(influencer_id: str, posts: list[dict]) -> list[dict]:
    rows = []
    for p in posts:
        date = p.get("date")
        rows.append({
            "influencer_id": influencer_id,
            "url": p.get("url"),
            "text": p.get("text"),
            "posted_at": date.isoformat() if hasattr(date, "isoformat") else date,
            "posted_ago": p.get("posted_ago"),
            "format": p.get("format"),
            "likes": int(p.get("likes", 0) or 0),
            "comments": int(p.get("comments", 0) or 0),
            "reposts": int(p.get("reposts", 0) or 0),
            "engagement": int(p.get("engagement", 0) or 0),
            "length_chars": int(p.get("length_chars", 0) or 0),
            "length_words": int(p.get("length_words", 0) or 0),
        })
    return rows


def save_analysis(access_token: str, result: dict, posts_limit: int | None = None) -> dict | None:
    """Persist an analysis run for the authenticated user.

    Upserts the influencer (and its posts), then inserts the analysis report.
    Returns {"influencer_id", "analysis_id"} or None on failure.
    """
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    user_id = user["id"]

    # upsert influencer (unique on user_id + handle)
    inf_row = _influencer_row(user_id, result)
    inf_resp = (
        db.table("influencers")
        .upsert(inf_row, on_conflict="user_id,handle")
        .execute()
    )
    if not inf_resp.data:
        return None
    influencer_id = inf_resp.data[0]["id"]

    # replace posts
    posts = result.get("posts", []) or []
    db.table("posts").delete().eq("influencer_id", influencer_id).execute()
    rows = _post_rows(influencer_id, posts)
    if rows:
        db.table("posts").insert(rows).execute()

    # insert analysis
    analysis_row = {
        "user_id": user_id,
        "influencer_id": influencer_id,
        "handle": result["handle"],
        "report_markdown": result.get("markdown"),
        "stats": result.get("stats"),
        "patterns": result.get("patterns"),
        "classifications": result.get("classifications"),
        "synthesis": result.get("synthesis"),
        "cta_stats": result.get("cta_stats"),
        "usage": result.get("usage"),
        "posts_limit": posts_limit,
    }
    an_resp = db.table("analyses").insert(analysis_row).execute()
    analysis_id = an_resp.data[0]["id"] if an_resp.data else None
    return {"influencer_id": influencer_id, "analysis_id": analysis_id}


def list_influencers(access_token: str) -> list[dict]:
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("influencers")
        .select("*")
        .order("updated_at", desc=True)
        .execute()
    )
    return resp.data or []


def list_analyses(access_token: str, limit: int = 20) -> list[dict]:
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("analyses")
        .select("id,handle,created_at,posts_limit")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def get_analysis(access_token: str, analysis_id: str) -> dict | None:
    if not get_user(access_token):
        return None
    db = client_for_token(access_token)
    resp = db.table("analyses").select("*").eq("id", analysis_id).limit(1).execute()
    return resp.data[0] if resp.data else None
