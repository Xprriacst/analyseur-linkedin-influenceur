"""Supabase data-access layer.

The backend stays usable without Supabase configured (file-based fallback).
When a user JWT is provided, a per-request client is created so that Postgres
Row Level Security applies and data is scoped to that user automatically.
"""
from __future__ import annotations

import datetime
import os
from typing import Any
from urllib.parse import unquote

try:
    from supabase import Client, create_client
except Exception:  # supabase not installed yet / import error
    Client = Any  # type: ignore
    create_client = None  # type: ignore


def _json_safe(obj: Any) -> Any:
    """Recursively convert non-JSON-serializable types to safe equivalents.

    Supabase-py serialises JSONB columns with the standard json module, which
    rejects datetime/date objects.  pandas Timestamps inherit from datetime so
    they are caught by the same branch.
    """
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


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


def _service_key() -> str | None:
    return os.environ.get("SUPABASE_SERVICE_ROLE_KEY")


def admin_enabled() -> bool:
    """True when a service-role key is configured (cron context only)."""
    return bool(create_client and _url() and _service_key())


def admin_client() -> "Client":
    """Service-role client that BYPASSES RLS.

    Reserved for server-side jobs without a user session (e.g. the daily-idea
    cron). Endpoints use `client_for_token` by default so RLS scopes the data.
    The only HTTP exception is a write to a client-read-only table that only the
    service-role may write (e.g. `daily_ideas`, cf. `replace_daily_idea`) : it is
    safe *only* because the row is strictly scoped to the verified token's
    `user_id`. Never use it to read/return data without such scoping.
    """
    return create_client(_url(), _service_key())  # type: ignore[arg-type]


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


def _influencer_row(user_id: str, result: dict, platform: str = "linkedin") -> dict:
    profile = result.get("profile", {}) or {}
    return {
        "user_id": user_id,
        "handle": result["handle"],
        "platform": platform,
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


def _post_rows(influencer_id: str, posts: list[dict], platform: str = "linkedin") -> list[dict]:
    rows = []
    for p in posts:
        date = p.get("date")
        row: dict = {
            "influencer_id": influencer_id,
            "platform": platform,
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
        }
        # Instagram-specific columns (ignored for LinkedIn rows by Postgres if columns absent)
        if platform == "instagram":
            views = p.get("views")
            if views is not None:
                row["views"] = int(views)
            video_dur = p.get("video_duration_s")
            if video_dur is not None:
                row["video_duration_s"] = float(video_dur)
            transcript = p.get("transcript")
            if transcript:
                row["transcript"] = transcript
            hashtags = p.get("hashtags")
            if hashtags is not None:
                row["hashtags"] = hashtags
            music = p.get("music")
            if music is not None:
                row["music"] = music
        rows.append(row)
    return rows


def save_analysis(access_token: str, result: dict, posts_limit: int | None = None) -> dict | None:
    """Persist an analysis run for the authenticated user.

    Upserts the influencer (and its posts), then replaces the current analysis
    report for that user/influencer pair.
    Returns {"influencer_id", "analysis_id"} or None on failure.
    """
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    user_id = user["id"]

    platform = result.get("platform") or "linkedin"

    # upsert influencer — try new constraint (user_id, handle, platform) first,
    # fall back to old (user_id, handle) for legacy DB without migration 0015.
    inf_row = _influencer_row(user_id, result, platform=platform)
    try:
        inf_resp = (
            db.table("influencers")
            .upsert(inf_row, on_conflict="user_id,handle,platform")
            .execute()
        )
    except Exception:
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
    rows = _post_rows(influencer_id, posts, platform=platform)
    if rows:
        db.table("posts").insert(rows).execute()

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # replace current analysis (unique on user_id + influencer_id)
    analysis_row = {
        "user_id": user_id,
        "influencer_id": influencer_id,
        "handle": result["handle"],
        "report_markdown": result.get("markdown"),
        "stats": _json_safe(result.get("stats")),
        "patterns": _json_safe(result.get("patterns")),
        "classifications": _json_safe(result.get("classifications")),
        "synthesis": _json_safe(result.get("synthesis")),
        "cta_stats": _json_safe(result.get("cta_stats")),
        "usage": _json_safe(result.get("usage")),
        "posts_limit": posts_limit,
        "updated_at": now,
    }
    an_resp = (
        db.table("analyses")
        .upsert(analysis_row, on_conflict="user_id,influencer_id")
        .select("id")
        .execute()
    )
    analysis_id = an_resp.data[0]["id"] if an_resp.data else None
    return {"influencer_id": influencer_id, "analysis_id": analysis_id}


def get_user_corpus(access_token: str, platform: str = "linkedin") -> list[dict]:
    """Load the user's corpus (influencers + posts) from Supabase for one platform.

    Returns a list of {"handle", "profile", "posts"} dicts shaped like the
    normalized pipeline output, so stats/patterns can be recomputed on top.
    """
    user = get_user(access_token)
    if not user:
        return []
    return _corpus_from_client(client_for_token(access_token), user["id"], platform=platform)


def _corpus_from_client(db: "Client", user_id: str, platform: str = "linkedin") -> list[dict]:
    """Shared corpus loader, usable with a user JWT client or the admin client."""
    # Filtre user_id explicite en plus de RLS (défense en profondeur).
    inf_resp = (
        db.table("influencers")
        .select("*")
        .eq("user_id", user_id)
        .eq("platform", platform)
        .order("updated_at", desc=True)
        .execute()
    )
    influencers = inf_resp.data or []
    if not influencers:
        return []

    ids = [inf["id"] for inf in influencers]
    posts_resp = (
        db.table("posts")
        .select("*")
        .in_("influencer_id", ids)
        .eq("platform", platform)
        .order("posted_at", desc=True)
        .execute()
    )
    posts_by_inf: dict[str, list[dict]] = {}
    for row in posts_resp.data or []:
        posts_by_inf.setdefault(row["influencer_id"], []).append({
            "url": row.get("url"),
            "text": row.get("text") or "",
            "date": row.get("posted_at"),
            "posted_ago": row.get("posted_ago"),
            "format": row.get("format"),
            "likes": row.get("likes", 0) or 0,
            "comments": row.get("comments", 0) or 0,
            "reposts": row.get("reposts", 0) or 0,
            "engagement": row.get("engagement", 0) or 0,
            "length_chars": row.get("length_chars", 0) or 0,
            "length_words": row.get("length_words", 0) or 0,
        })

    corpus = []
    for inf in influencers:
        posts = posts_by_inf.get(inf["id"], [])
        if not posts:
            continue
        profile = inf.get("raw_profile") or {
            "name": inf.get("name"),
            "headline": inf.get("headline"),
            "follower_count": inf.get("follower_count", 0),
        }
        corpus.append({"handle": inf["handle"], "profile": profile, "posts": posts})
    return corpus


def list_influencers(access_token: str) -> list[dict]:
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("influencers")
        .select("*")
        .eq("user_id", user["id"])
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
        .select("id,handle,created_at,updated_at,posts_limit")
        .eq("user_id", user["id"])
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def list_influencer_library(access_token: str) -> list[dict]:
    """One row per analyzed influencer — current analysis metadata only (no markdown)."""
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("influencers")
        .select("id,handle,name,headline,follower_count,profile_url,updated_at,analyses(id,updated_at,created_at)")
        .eq("user_id", user["id"])
        .order("updated_at", desc=True)
        .execute()
    )
    rows: list[dict] = []
    for inf in resp.data or []:
        analyses = inf.get("analyses") or []
        if isinstance(analyses, dict):
            analyses = [analyses]
        if not analyses:
            continue
        analysis = max(
            analyses,
            key=lambda a: (a.get("updated_at") or a.get("created_at") or ""),
        )
        analyzed_at = analysis.get("updated_at") or analysis.get("created_at") or ""
        try:
            ts = datetime.datetime.fromisoformat(analyzed_at.replace("Z", "+00:00")).timestamp()
        except Exception:
            ts = 0
        handle = unquote(inf["handle"])
        name = (inf.get("name") or "").strip() or handle
        profile_url = inf.get("profile_url") or f"https://www.linkedin.com/in/{inf['handle']}/"
        rows.append({
            "influencer_id": inf["id"],
            "analysis_id": analysis["id"],
            "handle": handle,
            "name": name,
            "headline": (inf.get("headline") or "").strip(),
            "follower_count": int(inf.get("follower_count") or 0),
            "profile_url": profile_url,
            "analyzed_at": ts,
        })
    rows.sort(key=lambda r: r.get("analyzed_at") or 0, reverse=True)
    return rows


def list_reports(access_token: str, limit: int = 3) -> list[dict]:
    """User's recent analysis reports, shaped like the disk-based /reports payload."""
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("analyses")
        .select("id,handle,created_at,updated_at,report_markdown,influencers(name)")
        .eq("user_id", user["id"])
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    reports = []
    for row in resp.data or []:
        updated = row.get("updated_at") or row.get("created_at") or ""
        try:
            from datetime import datetime
            ts = datetime.fromisoformat(updated.replace("Z", "+00:00")).timestamp()
        except Exception:
            ts = 0
        # Nom lisible : prénom + nom de l'influenceur, fallback handle décodé
        influencer = row.get("influencers") or {}
        name = (influencer.get("name") or "").strip() or unquote(row["handle"])
        reports.append({
            "name": name,
            "path": row["id"],
            "updated_at": ts,
            "content": row.get("report_markdown") or "",
        })
    return reports


_EDITORIAL_PROFILE_FIELDS = (
    "display_name",
    "brand_name",
    "industry",
    "business_description",
    "location",
    "target_audience",
    "core_offer",
    "tone",
    "linkedin_objective",
    "topics_to_cover",
    "topics_to_avoid",
    "constraints",
    "website_url",
    "linkedin_url",
    "language",
    "market",
    "extra_context",
)


def _clean_editorial_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep only known profile fields and normalize empty strings to null."""
    cleaned: dict[str, Any] = {}
    for key in _EDITORIAL_PROFILE_FIELDS:
        value = payload.get(key)
        if isinstance(value, str):
            value = value.strip()
            cleaned[key] = value or None
        elif value is not None:
            cleaned[key] = value
    return cleaned


def get_editorial_profile(access_token: str) -> dict | None:
    """Return the authenticated user's editorial profile, if it exists."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("user_editorial_profiles")
        .select("*")
        .eq("user_id", user["id"])
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def upsert_editorial_profile(access_token: str, payload: dict[str, Any]) -> dict | None:
    """Create or update the user's editorial profile."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    row = {
        "user_id": user["id"],
        **_clean_editorial_profile(payload),
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    resp = (
        db.table("user_editorial_profiles")
        .upsert(row, on_conflict="user_id")
        .execute()
    )
    return resp.data[0] if resp.data else None


def set_zernio_profile_id(access_token: str, profile_id: str) -> dict | None:
    """Persist the Zernio profile id for this user (creating the row if needed)."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    row = {
        "user_id": user["id"],
        "zernio_profile_id": profile_id,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    resp = (
        db.table("user_editorial_profiles")
        .upsert(row, on_conflict="user_id")
        .execute()
    )
    return resp.data[0] if resp.data else None


def set_zernio_account(access_token: str, account_id: str | None) -> dict | None:
    """Persist (or clear) the connected LinkedIn account id for this user."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    row = {
        "user_id": user["id"],
        "zernio_account_id": account_id,
        "zernio_connected_at": now if account_id else None,
        "updated_at": now,
    }
    resp = (
        db.table("user_editorial_profiles")
        .upsert(row, on_conflict="user_id")
        .execute()
    )
    return resp.data[0] if resp.data else None


def set_zernio_x_account(access_token: str, account_id: str | None) -> dict | None:
    """Persist (or clear) the connected X (Twitter) account id for this user."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    row = {
        "user_id": user["id"],
        "zernio_x_account_id": account_id,
        "zernio_x_connected_at": now if account_id else None,
        "updated_at": now,
    }
    resp = (
        db.table("user_editorial_profiles")
        .upsert(row, on_conflict="user_id")
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_user_ai_context(access_token: str | None) -> dict[str, Any] | None:
    """Compact profile context consumed by LLM prompts.

    Returns None when Supabase is disabled, the session is missing/invalid, or no
    profile has been filled yet. This keeps generation usable with benchmark data.
    """
    if not access_token or not supabase_enabled():
        return None
    profile = get_editorial_profile(access_token)
    if not profile:
        return None
    context = {
        key: profile.get(key)
        for key in _EDITORIAL_PROFILE_FIELDS
        if profile.get(key) not in (None, "")
    }
    if not context:
        return None
    return context


def get_top_real_posts(access_token: str, limit: int = 40) -> list[dict]:
    """Return the user's top-performing real posts (from analysed influencers).

    Used to ground idea generation in actual content that worked.
    """
    if not supabase_enabled() or not access_token:
        return []
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    try:
        inf_resp = (
            db.table("influencers")
            .select("id, name")
            .eq("user_id", user["id"])
            .eq("platform", "linkedin")
            .execute()
        )
        influencer_ids = [r["id"] for r in (inf_resp.data or [])]
        influencer_names: dict[str, str] = {r["id"]: r.get("name") or r["id"] for r in (inf_resp.data or [])}
        if not influencer_ids:
            return []
        posts_resp = (
            db.table("posts")
            .select("text, likes, comments, url, influencer_id")
            .in_("influencer_id", influencer_ids)
            .order("likes", desc=True)
            .limit(limit)
            .execute()
        )
        result = []
        for row in posts_resp.data or []:
            if not row.get("text"):
                continue
            engagement = (row.get("likes") or 0) + (row.get("comments") or 0)
            result.append({
                "name": influencer_names.get(row["influencer_id"], "?"),
                "text": row["text"],
                "url": row.get("url") or "",
                "engagement": engagement,
            })
        return result
    except Exception:
        return []


def save_ideas(access_token: str, ideas: list[dict]) -> list[dict]:
    """Persist generated ideas for the authenticated user. Returns saved rows (with ids)."""
    if not ideas or not supabase_enabled():
        return ideas
    user = get_user(access_token)
    if not user:
        return ideas
    db = client_for_token(access_token)
    rows = [
        {
            "user_id": user["id"],
            "title": idea.get("title"),
            "hook": idea.get("hook"),
            "hook_type": idea.get("hook_type"),
            "funnel": idea.get("funnel"),
            "angle": idea.get("angle"),
            "why_it_works": idea.get("why_it_works"),
            "difficulty": idea.get("difficulty"),
            "estimated_lift": idea.get("estimated_lift"),
            # ALE-143 : nouvelles colonnes one-liner (nullable — rétro-compatible)
            "line": idea.get("line"),
            "source_type": idea.get("source_type"),
            "source_ref": idea.get("source_ref"),
            "source_url": idea.get("source_url"),
        }
        for idea in ideas
    ]
    resp = db.table("generated_ideas").insert(rows).execute()
    return resp.data if resp.data else ideas


def save_generated_posts(
    access_token: str, topic: str, variants: list[dict]
) -> list[dict]:
    """Persist generated post variants for the authenticated user. Returns saved rows (with ids)."""
    if not variants or not supabase_enabled():
        return variants
    user = get_user(access_token)
    if not user:
        return variants
    db = client_for_token(access_token)
    rows = [
        {
            "user_id": user["id"],
            "topic": topic or None,
            "editorial_role": variant.get("editorial_role"),
            "hook_type": variant.get("hook_type"),
            "strategy": variant.get("strategy"),
            "predicted_lift": variant.get("predicted_lift"),
            "post": variant.get("post") or "",
            # ALE-134 : auto-sauvegarde = brouillon non « sauvegardé ». L'id reste
            # dispo (Slack/X), mais le post n'apparaît dans « Mes contenus » qu'après
            # un clic explicite sur « Sauvegarder » (passe saved → true).
            "saved": False,
        }
        for variant in variants
        if variant.get("post")
    ]
    if not rows:
        return variants
    resp = db.table("generated_posts").insert(rows).execute()
    return resp.data if resp.data else variants


def create_saved_post(
    access_token: str,
    post_text: str,
    topic: str | None = None,
    editorial_role: str | None = None,
    hook_type: str | None = None,
    strategy: str | None = None,
    predicted_lift: str | None = None,
    media_items: list[dict] | None = None,
) -> dict | None:
    """Create a single explicitly-saved generated post (ALE-136 : sauvegarder le post du jour)."""
    if not supabase_enabled():
        return None
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    row: dict = {
        "user_id": user["id"],
        "topic": topic or None,
        "editorial_role": editorial_role,
        "hook_type": hook_type,
        "strategy": strategy,
        "predicted_lift": predicted_lift,
        "post": post_text,
        "saved": True,
    }
    if media_items:
        row["media_items"] = media_items
    resp = (
        db.table("generated_posts")
        .insert(row)
        .execute()
    )
    return resp.data[0] if resp.data else None


def list_generated_ideas(access_token: str, limit: int = 100) -> list[dict]:
    """List the user's saved post ideas, newest first."""
    if not supabase_enabled():
        return []
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("generated_ideas")
        .select("*")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def list_generated_posts(
    access_token: str, limit: int = 100, saved_only: bool = False
) -> list[dict]:
    """List the user's generated posts, newest first.

    With ``saved_only=True``, only posts explicitly marked ``saved`` are returned
    (ALE-135 : « Mes contenus » n'affiche que les posts sauvegardés).
    """
    if not supabase_enabled():
        return []
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    query = (
        db.table("generated_posts")
        .select("*")
        .eq("user_id", user["id"])
    )
    if saved_only:
        query = query.eq("saved", True)
    resp = query.order("created_at", desc=True).limit(limit).execute()
    return resp.data or []


def delete_generated_idea(access_token: str, idea_id: str) -> bool:
    """Delete one of the user's saved ideas. Returns True if a row was removed."""
    user = get_user(access_token)
    if not user:
        return False
    db = client_for_token(access_token)
    resp = (
        db.table("generated_ideas")
        .delete()
        .eq("user_id", user["id"])
        .eq("id", idea_id)
        .execute()
    )
    return bool(resp.data)


def delete_generated_post(access_token: str, post_id: str) -> bool:
    """Delete one of the user's saved posts. Returns True if a row was removed."""
    user = get_user(access_token)
    if not user:
        return False
    db = client_for_token(access_token)
    resp = (
        db.table("generated_posts")
        .delete()
        .eq("user_id", user["id"])
        .eq("id", post_id)
        .execute()
    )
    return bool(resp.data)


def update_generated_post(
    access_token: str,
    post_id: str,
    new_post: str | None = None,
    saved: bool | None = None,
    media_items: list[dict] | None = None,
) -> dict | None:
    """Update a saved post's text, `saved` flag and/or images (ALE-134/179).

    All fields are optional; only the provided ones are written. `media_items`
    remplace la liste d'images ([] = tout retirer). Returns the updated row or None.
    """
    user = get_user(access_token)
    if not user:
        return None
    updates: dict = {}
    if new_post is not None:
        updates["post"] = new_post
    if saved is not None:
        updates["saved"] = saved
    if media_items is not None:
        updates["media_items"] = media_items
    if not updates:
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("generated_posts")
        .update(updates)
        .eq("user_id", user["id"])
        .eq("id", post_id)
        .execute()
    )
    return resp.data[0] if resp.data else None


# ── Crédits utilisateur (ALE-41) ── #

# Offre de bienvenue à l'inscription (1re visite). Doit rester alignée avec le
# défaut de colonne et l'auto-création dans debit_credits() (migration 0028).
WELCOME_CREDITS = 60

CREDIT_COSTS: dict[str, int] = {
    "generate_post": 5,    # par variant
    "generate_ideas": 3,   # par lot (ALE-143)
    "analyze_job": 20,     # par influenceur
    "chat": 2,             # par message
    "generate_image": 5,
}


def get_user_credits(access_token: str) -> dict:
    """Retourne le solde de crédits de l'utilisateur (crée 20 crédits au 1er appel)."""
    if not supabase_enabled():
        return {"balance": 999, "enabled": False}
    user = get_user(access_token)
    if not user:
        return {"balance": 0, "enabled": True}
    db_client = client_for_token(access_token)
    # maybe_single() peut renvoyer None (0 ligne) ou lever selon la version de
    # supabase-py → on lit la liste brute et on reste défensif.
    try:
        resp = (
            db_client.table("user_credits")
            .select("balance, updated_at")
            .eq("user_id", user["id"])
            .limit(1)
            .execute()
        )
        rows = resp.data if resp and getattr(resp, "data", None) else []
    except Exception:
        rows = []
    if rows:
        return {"balance": rows[0]["balance"], "enabled": True}
    # Première visite : initialiser via service-role (offre de bienvenue = 60).
    if admin_enabled():
        try:
            admin_client().table("user_credits").insert({"user_id": user["id"], "balance": WELCOME_CREDITS}).execute()
        except Exception:
            pass
    return {"balance": WELCOME_CREDITS, "enabled": True}


def debit_credits(access_token: str, action: str, count: int = 1) -> tuple[bool, int]:
    """Débite les crédits pour une action. Retourne (succès, nouveau_solde).

    Utilise la fonction Postgres debit_credits() pour l'atomicité.
    Si Supabase ou la service-role key ne sont pas configurés, retourne toujours True.
    """
    if not supabase_enabled() or not admin_enabled():
        return (True, 999)
    user = get_user(access_token)
    if not user:
        return (False, 0)
    cost = CREDIT_COSTS.get(action, 5) * max(1, count)
    try:
        resp = admin_client().rpc("debit_credits", {
            "p_user_id": user["id"],
            "p_amount": cost,
            "p_action": action,
            "p_description": f"{action} x{count}",
        }).execute()
        new_balance = resp.data if isinstance(resp.data, int) else 0
        return (True, new_balance)
    except Exception as exc:
        if "INSUFFICIENT_CREDITS" in str(exc):
            # Récupère le solde actuel pour le message d'erreur
            try:
                info = get_user_credits(access_token)
                return (False, info.get("balance", 0))
            except Exception:
                return (False, 0)
        raise


import re as _re


def _handle_from_url(url: str) -> str | None:
    """Handle lisible extrait d'une URL LinkedIn (sans importer le scraper)."""
    m = _re.search(r"/in/([^/?#]+)", url or "")
    if not m:
        return None
    try:
        return unquote(m.group(1))
    except Exception:
        return m.group(1)


def get_linkedin_profile_seed(access_token: str, linkedin_url: str | None) -> dict[str, Any] | None:
    """Return analyzed LinkedIn context for a URL if it exists in the user's corpus."""
    handle = _handle_from_url(linkedin_url or "")
    if not handle:
        return None
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    inf_resp = (
        db.table("influencers")
        .select("id,handle,name,headline,summary,location,follower_count,profile_url,raw_profile")
        .eq("user_id", user["id"])
        .eq("handle", handle)
        .limit(1)
        .execute()
    )
    if not inf_resp.data:
        return None
    influencer = inf_resp.data[0]
    posts_resp = (
        db.table("posts")
        .select("text,format,likes,comments,reposts,engagement")
        .eq("influencer_id", influencer["id"])
        .order("engagement", desc=True)
        .limit(6)
        .execute()
    )
    posts = [
        {
            "text": (row.get("text") or "")[:900],
            "format": row.get("format"),
            "engagement": row.get("engagement", 0),
            "likes": row.get("likes", 0),
            "comments": row.get("comments", 0),
            "reposts": row.get("reposts", 0),
        }
        for row in posts_resp.data or []
        if row.get("text")
    ]
    return {
        "handle": influencer.get("handle"),
        "profile": {
            "name": influencer.get("name"),
            "headline": influencer.get("headline"),
            "summary": influencer.get("summary"),
            "location": influencer.get("location"),
            "follower_count": influencer.get("follower_count"),
            "profile_url": influencer.get("profile_url"),
            "raw_profile": influencer.get("raw_profile"),
        },
        "top_posts": posts,
    }


_JOB_ITEM_COLS = (
    "id,position,url,handle,name,status,error,analysis_id,"
    "influencer_id,follower_count,posts_count,updated_at"
)


def create_job(
    access_token: str,
    urls: list[str],
    limit_posts: int,
    run_llm: bool,
    use_cache: bool,
    platform: str = "linkedin",
) -> dict | None:
    """Crée une série (job) + ses items (un par URL). Retourne le job complet."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    job_row: dict = {
        "user_id": user["id"],
        "status": "queued",
        "total": len(urls),
        "limit_posts": limit_posts,
        "run_llm": run_llm,
        "use_cache": use_cache,
    }
    # Store platform if the column exists (migration 0015); ignored otherwise.
    if platform != "linkedin":
        job_row["platform"] = platform
    job_resp = (
        db.table("analysis_jobs")
        .insert(job_row)
        .execute()
    )
    if not job_resp.data:
        return None
    job = job_resp.data[0]

    def _handle_from_raw(url: str) -> str | None:
        """Extract handle from either LinkedIn or Instagram URL."""
        if platform == "instagram":
            try:
                from src.scraper_instagram import extract_ig_handle
                return extract_ig_handle(url)
            except Exception:
                pass
        return _handle_from_url(url)

    items = [
        {
            "job_id": job["id"],
            "user_id": user["id"],
            "position": i,
            "url": url,
            "handle": _handle_from_raw(url),
            "status": "pending",
        }
        for i, url in enumerate(urls)
    ]
    db.table("analysis_job_items").insert(items).execute()
    return get_job(access_token, job["id"])


def get_job(access_token: str, job_id: str) -> dict | None:
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    jr = (
        db.table("analysis_jobs")
        .select("*")
        .eq("id", job_id)
        .eq("user_id", user["id"])
        .limit(1)
        .execute()
    )
    if not jr.data:
        return None
    job = jr.data[0]
    ir = (
        db.table("analysis_job_items")
        .select(_JOB_ITEM_COLS)
        .eq("job_id", job_id)
        .order("position")
        .execute()
    )
    job["items"] = ir.data or []
    return job


def list_jobs(access_token: str, limit: int = 20) -> list[dict]:
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    jr = (
        db.table("analysis_jobs")
        .select("*")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    jobs = jr.data or []
    if not jobs:
        return []
    ids = [j["id"] for j in jobs]
    ir = (
        db.table("analysis_job_items")
        .select(_JOB_ITEM_COLS + ",job_id")
        .in_("job_id", ids)
        .order("position")
        .execute()
    )
    by_job: dict[str, list[dict]] = {}
    for it in ir.data or []:
        by_job.setdefault(it["job_id"], []).append(it)
    for j in jobs:
        j["items"] = by_job.get(j["id"], [])
    return reconcile_stale_jobs(access_token, jobs)


def get_job_status(access_token: str, job_id: str) -> str | None:
    """Retourne uniquement le statut du job (lecture légère, sans items)."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    r = (
        db.table("analysis_jobs")
        .select("status")
        .eq("id", job_id)
        .eq("user_id", user["id"])
        .limit(1)
        .execute()
    )
    return r.data[0]["status"] if r.data else None


def update_job(access_token: str, job_id: str, **fields: Any) -> None:
    db = client_for_token(access_token)
    fields["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    db.table("analysis_jobs").update(fields).eq("id", job_id).execute()


def update_job_item(access_token: str, item_id: str, **fields: Any) -> None:
    db = client_for_token(access_token)
    fields["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    db.table("analysis_job_items").update(fields).eq("id", item_id).execute()


def get_job_item_status(access_token: str, item_id: str) -> str | None:
    """Statut d'un item précis (lecture légère, pour la vérif d'annulation du thread)."""
    db = client_for_token(access_token)
    r = (
        db.table("analysis_job_items")
        .select("status")
        .eq("id", item_id)
        .limit(1)
        .execute()
    )
    return r.data[0]["status"] if r.data else None


def cancel_job_item(access_token: str, item_id: str) -> str | None:
    """Annule un item s'il est encore `pending`/`running`. Retourne le statut résultant.

    L'`in_("status", …)` garantit qu'on n'écrase jamais un item déjà terminé
    (`done`/`error`). RLS scope l'update au propriétaire via le JWT.
    """
    db = client_for_token(access_token)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (
        db.table("analysis_job_items")
        .update({"status": "cancelled", "updated_at": now})
        .eq("id", item_id)
        .in_("status", ["pending", "running"])
        .execute()
    )
    return get_job_item_status(access_token, item_id)


def cancel_pending_items(access_token: str, job_id: str) -> None:
    """Annule tous les items encore en attente/en cours d'une série (cancel global)."""
    db = client_for_token(access_token)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (
        db.table("analysis_job_items")
        .update({"status": "cancelled", "updated_at": now})
        .eq("job_id", job_id)
        .in_("status", ["pending", "running"])
        .execute()
    )


def delete_job_item(access_token: str, item_id: str) -> bool:
    """Supprime une analyse depuis la liste des séries (ALE-131).

    Retire la ligne (`analysis_job_items`) ET le rapport d'analyse lié
    (`analyses`) s'il existe, scoppé à l'utilisateur (RLS). Retourne True si la
    ligne a été supprimée.
    """
    user = get_user(access_token)
    if not user:
        return False
    db = client_for_token(access_token)
    row = (
        db.table("analysis_job_items")
        .select("analysis_id")
        .eq("user_id", user["id"])
        .eq("id", item_id)
        .limit(1)
        .execute()
    )
    if not row.data:
        return False
    analysis_id = row.data[0].get("analysis_id")
    if analysis_id:
        (
            db.table("analyses")
            .delete()
            .eq("user_id", user["id"])
            .eq("id", analysis_id)
            .execute()
        )
    resp = (
        db.table("analysis_job_items")
        .delete()
        .eq("user_id", user["id"])
        .eq("id", item_id)
        .execute()
    )
    return bool(resp.data)


# Une série dont rien n'a bougé depuis ce délai est considérée morte (thread tué
# par un redémarrage Render, ou figé) → ses items non terminés sont soldés.
JOB_STALE_MINUTES = 15


def _parse_ts(value: str | None) -> "datetime.datetime | None":
    if not value:
        return None
    try:
        text = value.replace(" ", "T")
        if text.endswith("+00"):  # Postgres renvoie parfois "+00" (non ISO strict)
            text = text[:-3] + "+00:00"
        return datetime.datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def reconcile_stale_jobs(access_token: str, jobs: list[dict]) -> list[dict]:
    """Solde les séries actives orphelines (thread mort/figé) — appelé au listing.

    Si une série `queued`/`running` n'a pas été touchée depuis `JOB_STALE_MINUTES`,
    on en déduit que son thread de traitement n'existe plus : les items `running`
    et `pending` sont passés en `error`, et la série est finalisée. Idempotent :
    une fois finalisée la série n'est plus active, donc plus jamais reconsidérée.
    Mute les dicts en place pour que la réponse reflète la réconciliation.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(minutes=JOB_STALE_MINUTES)
    for job in jobs:
        if job.get("status") not in ("queued", "running"):
            continue
        job_ts = _parse_ts(job.get("updated_at"))
        if job_ts is None or job_ts > cutoff:
            continue  # récemment actif (ou date illisible) → on laisse tourner
        for it in job.get("items", []):
            if it.get("status") == "running":
                update_job_item(
                    access_token, it["id"], status="error",
                    error="Analyse interrompue (délai dépassé).",
                )
                it["status"] = "error"
            elif it.get("status") == "pending":
                update_job_item(
                    access_token, it["id"], status="error",
                    error="Non démarrée — série interrompue.",
                )
                it["status"] = "error"
        done = sum(1 for it in job.get("items", []) if it.get("status") == "done")
        failed = sum(1 for it in job.get("items", []) if it.get("status") == "error")
        final = "error" if failed and not done else "done"
        update_job(access_token, job["id"], status=final, completed=done, failed=failed)
        job["status"], job["completed"], job["failed"] = final, done, failed
    return jobs


# ---------------------------------------------------------------------------
# File d'attente de génération de posts (ALE-141)
# ---------------------------------------------------------------------------
# Une génération = une requête unique (un sujet → N variants), stockée dans une
# seule table `generation_jobs`. Le résultat (variants) est écrit en jsonb une
# fois terminé. L'état vit en base : l'utilisateur peut quitter la page et
# revenir, le résultat est conservé.

_GENERATION_JOB_COLS = (
    "id,status,topic,editorial_role,web_search,count,result,error,created_at,updated_at"
)


def create_generation_job(
    access_token: str,
    topic: str | None,
    editorial_role: str | None,
    web_search: bool,
    count: int,
) -> dict | None:
    """Crée un job de génération `queued`. Retourne la ligne créée."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("generation_jobs")
        .insert({
            "user_id": user["id"],
            "status": "queued",
            "topic": topic or None,
            "editorial_role": editorial_role or None,
            "web_search": bool(web_search),
            "count": count,
        })
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_generation_job(access_token: str, job_id: str) -> dict | None:
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    r = (
        db.table("generation_jobs")
        .select(_GENERATION_JOB_COLS)
        .eq("id", job_id)
        .eq("user_id", user["id"])
        .limit(1)
        .execute()
    )
    return r.data[0] if r.data else None


def list_generation_jobs(access_token: str, limit: int = 20) -> list[dict]:
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    r = (
        db.table("generation_jobs")
        .select(_GENERATION_JOB_COLS)
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return reconcile_stale_generation_jobs(access_token, r.data or [])


def get_generation_job_status(access_token: str, job_id: str) -> str | None:
    """Statut seul (lecture légère, pour la vérif d'annulation du thread)."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    r = (
        db.table("generation_jobs")
        .select("status")
        .eq("id", job_id)
        .eq("user_id", user["id"])
        .limit(1)
        .execute()
    )
    return r.data[0]["status"] if r.data else None


def update_generation_job(access_token: str, job_id: str, **fields: Any) -> None:
    db = client_for_token(access_token)
    fields["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    db.table("generation_jobs").update(fields).eq("id", job_id).execute()


def cancel_generation_job(access_token: str, job_id: str) -> dict | None:
    """Annule un job de génération s'il est encore `queued`/`running`.

    L'`in_("status", …)` garantit qu'on n'écrase jamais un job déjà terminé.
    """
    db = client_for_token(access_token)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (
        db.table("generation_jobs")
        .update({"status": "cancelled", "updated_at": now})
        .eq("id", job_id)
        .in_("status", ["queued", "running"])
        .execute()
    )
    return get_generation_job(access_token, job_id)


def reconcile_stale_generation_jobs(access_token: str, jobs: list[dict]) -> list[dict]:
    """Solde les jobs de génération orphelins (thread mort/figé) — appelé au listing.

    Même logique que `reconcile_stale_jobs` : un job `queued`/`running` sans update
    depuis `JOB_STALE_MINUTES` est passé en `error`. Idempotent. Mute en place.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(minutes=JOB_STALE_MINUTES)
    for job in jobs:
        if job.get("status") not in ("queued", "running"):
            continue
        job_ts = _parse_ts(job.get("updated_at"))
        if job_ts is None or job_ts > cutoff:
            continue
        update_generation_job(
            access_token, job["id"], status="error",
            error="Génération interrompue (délai dépassé).",
        )
        job["status"] = "error"
        job["error"] = "Génération interrompue (délai dépassé)."
    return jobs


def get_analysis(access_token: str, analysis_id: str) -> dict | None:
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("analyses")
        .select("*")
        .eq("id", analysis_id)
        .eq("user_id", user["id"])
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


# ── Assistant conversationnel (ALE-79) ──

def _chat_title_from_message(message: str) -> str:
    title = " ".join((message or "").strip().split())
    if not title:
        return "Nouvelle conversation"
    return title[:80]


def create_chat_conversation(access_token: str, first_message: str | None = None) -> dict | None:
    """Create a chat conversation owned by the authenticated user."""
    user = get_user(access_token)
    if not user:
        return None
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    db = client_for_token(access_token)
    resp = (
        db.table("chat_conversations")
        .insert({
            "user_id": user["id"],
            "title": _chat_title_from_message(first_message or ""),
            "updated_at": now,
        })
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_chat_conversation(access_token: str, conversation_id: str) -> dict | None:
    """Return a conversation only if it belongs to the authenticated user."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("chat_conversations")
        .select("*")
        .eq("id", conversation_id)
        .eq("user_id", user["id"])
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def list_chat_conversations(access_token: str, limit: int = 20) -> list[dict]:
    """List the user's recent chat conversations."""
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("chat_conversations")
        .select("id,title,created_at,updated_at")
        .eq("user_id", user["id"])
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def get_chat_messages(access_token: str, conversation_id: str, limit: int = 50) -> list[dict]:
    """Return messages for a user-owned conversation in chronological order."""
    if not get_chat_conversation(access_token, conversation_id):
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("chat_messages")
        .select("id,role,content,created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .limit(limit)
        .execute()
    )
    return resp.data or []


def append_chat_message(access_token: str, conversation_id: str, role: str, content: str) -> dict | None:
    """Append a user/assistant message and bump conversation freshness."""
    user = get_user(access_token)
    if not user:
        return None
    if role not in {"user", "assistant"}:
        raise ValueError("role must be user or assistant")
    if not get_chat_conversation(access_token, conversation_id):
        return None
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    db = client_for_token(access_token)
    resp = (
        db.table("chat_messages")
        .insert({
            "conversation_id": conversation_id,
            "user_id": user["id"],
            "role": role,
            "content": content,
            "created_at": now,
        })
        .execute()
    )
    db.table("chat_conversations").update({"updated_at": now}).eq("id", conversation_id).execute()
    return resp.data[0] if resp.data else None


# --------------------------------------------------------------------------- #
# Idée du jour — réservoir (idea_seeds) + idées générées (daily_ideas)
# --------------------------------------------------------------------------- #

def list_idea_seeds(access_token: str, limit: int = 200) -> list[dict]:
    """List the user's idea seeds in manual order (position), oldest first as fallback."""
    if not supabase_enabled():
        return []
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("idea_seeds")
        .select("*")
        .eq("user_id", user["id"])
        .order("position", desc=False)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def add_idea_seed(access_token: str, text: str, comment: str | None = None) -> dict | None:
    """Add a seed idea to the user's reservoir.

    `comment` is an optional orientation note (used for listing-URL seeds) that is
    injected into the prompt at generation time.
    """
    if not supabase_enabled():
        return None
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    row: dict[str, Any] = {"user_id": user["id"], "text": text}
    if comment:
        row["comment"] = comment
    # Nouvelle idée = ajoutée en fin de réservoir (position max + 1).
    last = (
        db.table("idea_seeds")
        .select("position")
        .eq("user_id", user["id"])
        .order("position", desc=True)
        .limit(1)
        .execute()
    )
    max_pos = (last.data[0].get("position") if last.data else None)
    row["position"] = (max_pos + 1) if isinstance(max_pos, int) else 0
    resp = (
        db.table("idea_seeds")
        .insert(row)
        .execute()
    )
    return resp.data[0] if resp.data else None


def reorder_idea_seeds(access_token: str, ordered_ids: list[str]) -> bool:
    """Persist a new manual order for the user's seeds.

    `ordered_ids` is the full list of the user's seed ids in the desired order.
    RLS scopes every update to the caller; unknown ids simply match no row.
    """
    if not supabase_enabled():
        return False
    user = get_user(access_token)
    if not user:
        return False
    db = client_for_token(access_token)
    for index, seed_id in enumerate(ordered_ids):
        (
            db.table("idea_seeds")
            .update({"position": index})
            .eq("id", seed_id)
            .eq("user_id", user["id"])
            .execute()
        )
    return True


def update_idea_seed(
    access_token: str,
    seed_id: str,
    text: str | None = None,
    comment: str | None = None,
) -> dict | None:
    """Edit a seed's text and/or orientation comment (RLS scope user).

    `text=None` → inchangé ; `comment=None` → inchangé, `comment=""` → effacé.
    Returns the updated row or None.
    """
    if not supabase_enabled():
        return None
    user = get_user(access_token)
    if not user:
        return None
    updates: dict[str, Any] = {}
    if text is not None:
        updates["text"] = text
    if comment is not None:
        updates["comment"] = comment or None
    if not updates:
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("idea_seeds")
        .update(updates)
        .eq("id", seed_id)
        .eq("user_id", user["id"])
        .execute()
    )
    return resp.data[0] if resp.data else None


def delete_idea_seed(access_token: str, seed_id: str) -> bool:
    """Delete one of the user's seeds. RLS guarantees ownership."""
    if not supabase_enabled():
        return False
    user = get_user(access_token)
    if not user:
        return False
    db = client_for_token(access_token)
    db.table("idea_seeds").delete().eq("id", seed_id).eq("user_id", user["id"]).execute()
    return True


def list_daily_ideas(access_token: str, limit: int = 30) -> list[dict]:
    """List the user's generated daily ideas, newest first."""
    if not supabase_enabled():
        return []
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("daily_ideas")
        .select("*")
        .eq("user_id", user["id"])
        .order("idea_date", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def get_daily_ideas_enabled(access_token: str) -> bool:
    """Whether the user opted in to the daily idea cron."""
    profile = get_editorial_profile(access_token)
    return bool(profile and profile.get("daily_ideas_enabled"))


def set_daily_ideas_enabled(access_token: str, enabled: bool) -> dict | None:
    """Toggle the user's daily-idea opt-in (creating the profile row if needed)."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    row = {
        "user_id": user["id"],
        "daily_ideas_enabled": bool(enabled),
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    resp = (
        db.table("user_editorial_profiles")
        .upsert(row, on_conflict="user_id")
        .execute()
    )
    return resp.data[0] if resp.data else None


# --- Cron helpers (service-role, bypass RLS) — jamais exposés via HTTP -------- #

def list_daily_idea_users() -> list[str]:
    """User ids that opted in to the daily idea cron (service-role)."""
    if not admin_enabled():
        return []
    db = admin_client()
    resp = (
        db.table("user_editorial_profiles")
        .select("user_id")
        .eq("daily_ideas_enabled", True)
        .execute()
    )
    return [r["user_id"] for r in (resp.data or []) if r.get("user_id")]


def get_corpus_for_user(user_id: str, platform: str = "linkedin") -> list[dict]:
    """Admin-side corpus loader for the cron (no user JWT available)."""
    if not admin_enabled():
        return []
    return _corpus_from_client(admin_client(), user_id, platform=platform)


def get_ai_context_for_user(user_id: str) -> dict[str, Any] | None:
    """Compact editorial context for a user, loaded with the service-role client."""
    if not admin_enabled():
        return None
    db = admin_client()
    resp = (
        db.table("user_editorial_profiles")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    profile = resp.data[0] if resp.data else None
    if not profile:
        return None
    context = {
        key: profile.get(key)
        for key in _EDITORIAL_PROFILE_FIELDS
        if profile.get(key) not in (None, "")
    }
    return context or None


def pop_unused_seed(user_id: str) -> dict | None:
    """Return the next unused seed for a user in manual order (service-role).

    Honours the user's manual ordering (position); falls back to created_at for
    rows without a position. Does not mark the seed as used.
    """
    if not admin_enabled():
        return None
    db = admin_client()
    resp = (
        db.table("idea_seeds")
        .select("*")
        .eq("user_id", user_id)
        .is_("used_at", "null")
        .order("position", desc=False)
        .order("created_at", desc=False)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def mark_seed_used(seed_id: str) -> None:
    """Mark a seed as consumed (service-role)."""
    if not admin_enabled():
        return
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    admin_client().table("idea_seeds").update({"used_at": now}).eq("id", seed_id).execute()


def replace_daily_idea(
    access_token: str,
    idea_markdown: str,
    idea_date: str,
    post: dict | None = None,
    image_url: str | None = None,
    source_url: str | None = None,
) -> dict | None:
    """Upsert the daily idea for today — replaces an existing one (on-demand regen).

    `daily_ideas` is client read-only (migration 0007 : seul le service-role
    écrit, la RLS `authenticated` n'autorise que le SELECT). Un upsert via le
    token user déclenche une RLS violation 42501 → 500. On écrit donc avec le
    client service-role, mais strictement scoppé à la ligne de l'utilisateur
    authentifié (`user_id` issu du token vérifié).

    ALE-136 : `post` (variant `generate_posts`) rend l'idée du jour postable.
    """
    user = get_user(access_token)
    if not user or not supabase_enabled() or not admin_enabled():
        return None
    db = admin_client()
    row = {
        "user_id": user["id"],
        "idea_markdown": idea_markdown,
        "idea_date": idea_date,
        # remis à NULL si la régénération ne vient pas d'une annonce (évite de
        # garder l'image d'un précédent post du jour basé sur un lien).
        "image_url": image_url,
        "source_url": source_url,
    }
    if post:
        row.update({
            "post_text": post.get("post"),
            "editorial_role": post.get("editorial_role"),
            "hook_type": post.get("hook_type"),
            "strategy": post.get("strategy"),
            "predicted_lift": post.get("predicted_lift"),
        })
    resp = (
        db.table("daily_ideas")
        .upsert(row, on_conflict="user_id,idea_date")
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_unused_seed_by_token(access_token: str) -> dict | None:
    """Return the next unused idea seed for the authenticated user (manual order)."""
    user = get_user(access_token)
    if not user or not supabase_enabled():
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("idea_seeds")
        .select("*")
        .eq("user_id", user["id"])
        .is_("used_at", "null")
        .order("position", desc=False)
        .order("created_at", desc=False)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def mark_seed_used_by_token(access_token: str, seed_id: str) -> None:
    """Mark a seed as consumed for the authenticated user."""
    user = get_user(access_token)
    if not user or not supabase_enabled():
        return
    db = client_for_token(access_token)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    db.table("idea_seeds").update({"used_at": now}).eq("id", seed_id).eq("user_id", user["id"]).execute()


def daily_idea_exists(user_id: str, idea_date: str) -> bool:
    """Whether a daily idea already exists for this user/date (idempotent cron)."""
    if not admin_enabled():
        return False
    db = admin_client()
    resp = (
        db.table("daily_ideas")
        .select("id")
        .eq("user_id", user_id)
        .eq("idea_date", idea_date)
        .limit(1)
        .execute()
    )
    return bool(resp.data)


def insert_daily_idea(
    user_id: str,
    idea_markdown: str,
    idea_date: str,
    seed_id: str | None = None,
    post: dict | None = None,
    image_url: str | None = None,
    source_url: str | None = None,
) -> dict | None:
    """Persist a generated daily idea (service-role). Ignores conflicts on (user, date).

    ALE-136 : `post` (dict d'un variant `generate_posts`) rend l'idée du jour
    postable — on stocke son texte + métadonnées en plus du markdown.
    ALE-156 : `image_url`/`source_url` quand le post vient d'un lien d'annonce
    immobilière (photo du bien rattachée à la publication).
    """
    if not admin_enabled():
        return None
    db = admin_client()
    row = {
        "user_id": user_id,
        "idea_markdown": idea_markdown,
        "idea_date": idea_date,
        "seed_id": seed_id,
    }
    if image_url:
        row["image_url"] = image_url
    if source_url:
        row["source_url"] = source_url
    if post:
        row.update({
            "post_text": post.get("post"),
            "editorial_role": post.get("editorial_role"),
            "hook_type": post.get("hook_type"),
            "strategy": post.get("strategy"),
            "predicted_lift": post.get("predicted_lift"),
        })
    resp = (
        db.table("daily_ideas")
        .upsert(row, on_conflict="user_id,idea_date", ignore_duplicates=True)
        .execute()
    )
    return resp.data[0] if resp.data else None


# ── Slack integration (ALE-63) ── #

def get_slack_integration(access_token: str) -> dict | None:
    """Return the user's Slack integration row, or None if not connected."""
    user = get_user(access_token)
    if not user or not supabase_enabled():
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("user_integrations")
        .select("*")
        .eq("user_id", user["id"])
        .eq("service", "slack")
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def save_slack_integration(access_token: str, data: dict) -> dict | None:
    """Upsert Slack integration for the authenticated user."""
    user = get_user(access_token)
    if not user or not supabase_enabled():
        return None
    db = client_for_token(access_token)
    row = {
        "user_id": user["id"],
        "service": "slack",
        "access_token": data["access_token"],
        "service_user_id": data.get("service_user_id"),
        "channel_id": data.get("channel_id"),
        "team_id": data.get("team_id"),
        "team_name": data.get("team_name"),
        "metadata": data.get("metadata"),
        "connected_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    resp = (
        db.table("user_integrations")
        .upsert(row, on_conflict="user_id,service")
        .select("*")
        .execute()
    )
    return resp.data[0] if resp.data else None


def delete_slack_integration(access_token: str) -> bool:
    """Remove the user's Slack integration. Returns True if a row was deleted."""
    user = get_user(access_token)
    if not user or not supabase_enabled():
        return False
    db = client_for_token(access_token)
    resp = (
        db.table("user_integrations")
        .delete()
        .eq("user_id", user["id"])
        .eq("service", "slack")
        .execute()
    )
    return bool(resp.data)


def get_users_by_slack_id(slack_user_id: str) -> list[dict]:
    """List every app account linked to a Slack user ID (service-role, for webhook).

    Un même utilisateur Slack peut avoir connecté Slack depuis plusieurs comptes
    app (plusieurs emails) — le webhook doit tester chaque compte pour trouver
    le propriétaire de l'item ciblé, pas en prendre un au hasard.
    """
    if not admin_enabled():
        return []
    resp = (
        admin_client()
        .table("user_integrations")
        .select("user_id, access_token, channel_id")
        .eq("service", "slack")
        .eq("service_user_id", slack_user_id)
        .execute()
    )
    return resp.data or []


def get_generated_idea(access_token: str, idea_id: str) -> dict | None:
    """Fetch a single generated idea for the authenticated user."""
    user = get_user(access_token)
    if not user or not supabase_enabled():
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("generated_ideas")
        .select("*")
        .eq("user_id", user["id"])
        .eq("id", idea_id)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def update_idea_slack_status(idea_id: str, user_id: str, status: str) -> bool:
    """Update slack_status on a generated_idea (service-role, called from webhook)."""
    if not admin_enabled():
        return False
    resp = (
        admin_client()
        .table("generated_ideas")
        .update({"slack_status": status})
        .eq("id", idea_id)
        .eq("user_id", user_id)
        .execute()
    )
    return bool(resp.data)


def set_idea_slack_pending(access_token: str, idea_ids: list[str]) -> int:
    """Mark a batch of ideas as 'pending' Slack validation. Returns count updated."""
    user = get_user(access_token)
    if not user or not supabase_enabled():
        return 0
    db = client_for_token(access_token)
    resp = (
        db.table("generated_ideas")
        .update({"slack_status": "pending"})
        .in_("id", idea_ids)
        .eq("user_id", user["id"])
        .execute()
    )
    return len(resp.data) if resp.data else 0


# ── ALE-96 : Posts LinkedIn planifiés ─────────────────────────────────────────

def create_scheduled_post(
    access_token: str,
    post_text: str,
    scheduled_at_iso: str,
    media_items: list[dict[str, Any]] | None = None,
    require_slack: bool = True,
) -> dict | None:
    """Store a scheduled LinkedIn post (with optional images).

    `require_slack=True` (défaut) → `slack_status='pending'` : le post attend une
    validation Slack avant que le cron ne le publie (ALE-120).
    `require_slack=False` → `slack_status='validated'` : programmation directe,
    publiée à l'échéance sans validation (ALE-137, option A).
    """
    if not supabase_enabled():
        return None
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("scheduled_posts")
        .insert({
            "user_id": user["id"],
            "post_text": post_text,
            "scheduled_at": scheduled_at_iso,
            "media_items": media_items or [],
            "slack_status": "pending" if require_slack else "validated",
        })
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_generated_post(access_token: str, post_id: str) -> dict | None:
    """Fetch a single generated post for the authenticated user."""
    user = get_user(access_token)
    if not user or not supabase_enabled():
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("generated_posts")
        .select("*")
        .eq("user_id", user["id"])
        .eq("id", post_id)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def list_scheduled_posts(access_token: str, limit: int = 50) -> list[dict]:
    """List all scheduled posts for the authenticated user, newest first."""
    if not supabase_enabled():
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("scheduled_posts")
        .select("id, post_text, scheduled_at, status, slack_status, slack_message_ts, zernio_post_id, error_message, media_items, created_at")
        .order("scheduled_at", desc=False)
        .limit(max(1, min(limit, 200)))
        .execute()
    )
    return resp.data or []


def cancel_scheduled_post(access_token: str, post_id: str) -> bool:
    """Cancel a pending scheduled post (RLS ensures ownership)."""
    if not supabase_enabled():
        return False
    db = client_for_token(access_token)
    resp = (
        db.table("scheduled_posts")
        .update({"status": "cancelled", "updated_at": "now()"})
        .eq("id", post_id)
        .eq("status", "pending")
        .execute()
    )
    return bool(resp.data)


def update_scheduled_post(
    access_token: str,
    post_id: str,
    *,
    post_text: str | None = None,
    scheduled_at_iso: str | None = None,
) -> dict | None:
    """Update a pending scheduled post owned by the authenticated user."""
    if not supabase_enabled():
        return None
    user = get_user(access_token)
    if not user:
        return None
    payload: dict[str, Any] = {"updated_at": "now()"}
    if post_text is not None:
        payload["post_text"] = post_text
    if scheduled_at_iso is not None:
        payload["scheduled_at"] = scheduled_at_iso
    if len(payload) == 1:
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("scheduled_posts")
        .update(payload)
        .eq("id", post_id)
        .eq("user_id", user["id"])
        .eq("status", "pending")
        .execute()
    )
    return resp.data[0] if resp.data else None


def mark_scheduled_post_slack_error(access_token: str, post_id: str, error: str) -> bool:
    """Mark the caller's scheduled post as failed when Slack validation cannot be sent."""
    if not supabase_enabled():
        return False
    db = client_for_token(access_token)
    resp = (
        db.table("scheduled_posts")
        .update({
            "status": "failed",
            "error_message": error[:500],
            "updated_at": "now()",
        })
        .eq("id", post_id)
        .eq("status", "pending")
        .execute()
    )
    return bool(resp.data)


def set_scheduled_post_slack_message(access_token: str, post_id: str, message_ts: str) -> dict | None:
    """Persist the Slack message timestamp for a scheduled post."""
    if not supabase_enabled():
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("scheduled_posts")
        .update({
            "slack_status": "pending",
            "slack_message_ts": message_ts,
            "updated_at": "now()",
        })
        .eq("id", post_id)
        .eq("status", "pending")
        .execute()
    )
    return resp.data[0] if resp.data else None


def set_post_slack_pending(access_token: str, post_ids: list[str]) -> int:
    """Mark a batch of generated posts as 'pending' Slack validation. Returns count updated."""
    user = get_user(access_token)
    if not user or not supabase_enabled():
        return 0
    db = client_for_token(access_token)
    resp = (
        db.table("generated_posts")
        .update({"slack_status": "pending"})
        .in_("id", post_ids)
        .eq("user_id", user["id"])
        .execute()
    )
    return len(resp.data) if resp.data else 0


def update_post_slack_status(post_id: str, user_id: str, status: str) -> bool:
    """Update slack_status on a generated_post (service-role, called from webhook)."""
    if not admin_enabled():
        return False
    resp = (
        admin_client()
        .table("generated_posts")
        .update({"slack_status": status})
        .eq("id", post_id)
        .eq("user_id", user_id)
        .execute()
    )
    return bool(resp.data)


def get_generated_post_for_user(post_id: str, user_id: str) -> dict | None:
    """Fetch a generated post by id/user with service-role access (webhook, no JWT)."""
    if not admin_enabled():
        return None
    resp = (
        admin_client()
        .table("generated_posts")
        .select("id, user_id, post, topic, slack_status, media_items, zernio_post_id")
        .eq("id", post_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_zernio_account_for_user(user_id: str) -> str | None:
    """Return a user's connected LinkedIn account id (service-role, for the webhook).

    Used to publish a directly-sent post on Slack validation, without a JWT.
    """
    if not admin_enabled():
        return None
    resp = (
        admin_client()
        .table("user_editorial_profiles")
        .select("zernio_account_id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not resp.data:
        return None
    return resp.data[0].get("zernio_account_id")


def mark_generated_post_published(post_id: str, user_id: str, zernio_post_id: str | None) -> bool:
    """Record a successful LinkedIn publication of a directly-sent post.

    Sets slack_status='published' and stores the Zernio post id so a replayed
    Slack webhook never republishes the same post (idempotence).
    """
    if not admin_enabled():
        return False
    resp = (
        admin_client()
        .table("generated_posts")
        .update({"slack_status": "published", "zernio_post_id": zernio_post_id})
        .eq("id", post_id)
        .eq("user_id", user_id)
        .execute()
    )
    return bool(resp.data)


def update_generated_post_media(access_token: str, post_id: str, media_items: list[dict]) -> bool:
    """Persist the Slack media_items (public image URLs) on a generated post.

    JWT-scoped (appelé depuis /send-posts). Permet aux images jointes de survivre
    aux clics Valider/Modifier sur Slack (qui rechargent le post depuis la base)."""
    user = get_user(access_token)
    if not user:
        return False
    db = client_for_token(access_token)
    resp = (
        db.table("generated_posts")
        .update({"media_items": media_items or []})
        .eq("user_id", user["id"])
        .eq("id", post_id)
        .execute()
    )
    return bool(resp.data)


def update_generated_post_text_admin(post_id: str, user_id: str, text: str) -> dict | None:
    """Edit a generated post's text from Slack (service-role, no JWT in webhook).

    Resets `slack_status` to 'pending' so an edited post must be re-validated
    before it counts as approved (symétrie avec les posts programmés, ALE-149).
    Returns the updated row, or None if the post no longer exists for this user.
    """
    if not admin_enabled():
        return None
    resp = (
        admin_client()
        .table("generated_posts")
        .update({"post": text, "slack_status": "pending"})
        .eq("id", post_id)
        .eq("user_id", user_id)
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_scheduled_post_for_user(post_id: str, user_id: str) -> dict | None:
    """Fetch a scheduled post by id/user with service-role access."""
    if not admin_enabled():
        return None
    resp = (
        admin_client()
        .table("scheduled_posts")
        .select("id, user_id, post_text, scheduled_at, status, slack_status, media_items")
        .eq("id", post_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def update_scheduled_post_slack_status(post_id: str, user_id: str, status: str) -> bool:
    """Apply Slack validation result to a scheduled post.

    Validation keeps the schedule pending for the cron. Decline cancels the
    schedule immediately so a due cron run can never publish it.
    """
    if not admin_enabled():
        return False
    payload: dict[str, Any] = {"slack_status": status, "updated_at": "now()"}
    if status == "declined":
        payload["status"] = "cancelled"
        payload["error_message"] = "Publication annulée après refus Slack."
    resp = (
        admin_client()
        .table("scheduled_posts")
        .update(payload)
        .eq("id", post_id)
        .eq("user_id", user_id)
        .execute()
    )
    return bool(resp.data)


def update_scheduled_post_text_admin(post_id: str, user_id: str, text: str) -> dict | None:
    """Edit a scheduled post's text from Slack (service-role, no JWT in webhook).

    Resets `slack_status` to 'pending' so an edited post must be re-validated
    before the cron publishes it (ALE-149/ALE-130). Only touches posts still
    pending publication; returns the updated row, or None if not editable.
    """
    if not admin_enabled():
        return None
    resp = (
        admin_client()
        .table("scheduled_posts")
        .update({
            "post_text": text,
            "slack_status": "pending",
            "updated_at": "now()",
        })
        .eq("id", post_id)
        .eq("user_id", user_id)
        .eq("status", "pending")
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_due_scheduled_posts() -> list[dict]:
    """Return pending posts whose scheduled_at <= now() (service-role, for cron).

    Two-step query: PostgREST ne peut pas embarquer `user_editorial_profiles`
    directement (pas de FK entre `scheduled_posts` et `user_editorial_profiles`,
    les deux ne se rejoignent que par `auth.users`). On récupère donc les posts
    dus, puis les `zernio_account_id` par `user_id` en une requête groupée.
    """
    if not admin_enabled():
        return []
    admin = admin_client()
    resp = (
        admin.table("scheduled_posts")
        .select("id, user_id, post_text, media_items")
        .eq("status", "pending")
        .eq("slack_status", "validated")
        .lte("scheduled_at", "now()")
        .limit(100)
        .execute()
    )
    posts = resp.data or []
    if not posts:
        return []
    user_ids = list({p["user_id"] for p in posts})
    prof = (
        admin.table("user_editorial_profiles")
        .select("user_id, zernio_account_id")
        .in_("user_id", user_ids)
        .execute()
    )
    account_by_user = {r["user_id"]: r.get("zernio_account_id") for r in (prof.data or [])}
    return [
        {
            "id": p["id"],
            "user_id": p["user_id"],
            "post_text": p["post_text"],
            "media_items": p.get("media_items") or [],
            "zernio_account_id": account_by_user.get(p["user_id"]),
        }
        for p in posts
    ]


def update_scheduled_post_status(
    post_id: str,
    status: str,
    *,
    zernio_post_id: str | None = None,
    error: str | None = None,
) -> None:
    """Update publication status for a scheduled post (service-role, for cron)."""
    if not admin_enabled():
        return
    admin = admin_client()
    payload: dict[str, Any] = {"status": status, "updated_at": "now()"}
    if zernio_post_id is not None:
        payload["zernio_post_id"] = zernio_post_id
    if error is not None:
        payload["error_message"] = error[:500]
    admin.table("scheduled_posts").update(payload).eq("id", post_id).execute()


# ── ALE-109 : Analyse incrémentale — cache global cross-user ─────────────── #

def get_influencer_from_cache(handle: str, platform: str = "linkedin") -> dict | None:
    """Retourne l'entrée de cache globale pour un influenceur (service-role).

    Utilisé par le pipeline pour détecter les posts déjà classifiés et éviter
    de rappeler le LLM. Retourne None si Supabase ou la service-role key ne sont
    pas configurés, ou si l'influenceur n'a jamais été analysé.
    """
    if not admin_enabled():
        return None
    try:
        resp = (
            admin_client()
            .table("influencer_cache")
            .select("*")
            .eq("handle", handle)
            .eq("platform", platform)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None
    except Exception:
        return None


def get_cached_posts_for_influencer(cache_id: str) -> list[dict]:
    """Charge tous les posts (avec classifications LLM) depuis le cache global."""
    if not admin_enabled():
        return []
    try:
        resp = (
            admin_client()
            .table("cached_posts")
            .select("*")
            .eq("influencer_cache_id", cache_id)
            .order("posted_at", desc=True)
            .execute()
        )
        return resp.data or []
    except Exception:
        return []


def upsert_influencer_cache(
    handle: str,
    platform: str,
    profile: dict,
    synthesis: dict | None = None,
) -> str | None:
    """Crée ou met à jour le cache global d'un influenceur. Retourne le cache id.

    La synthesis est stockée pour être réutilisée si le delta de nouveaux posts
    est insuffisant pour justifier une re-synthèse (ALE-109).
    """
    if not admin_enabled():
        return None
    try:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        row: dict[str, Any] = {
            "handle": handle,
            "platform": platform,
            "name": profile.get("name"),
            "headline": profile.get("headline"),
            "follower_count": int(profile.get("follower_count", 0) or 0),
            "profile_url": profile.get("profile_url"),
            "raw_profile": _json_safe(profile),
            "last_analyzed_at": now,
        }
        if synthesis is not None:
            row["synthesis"] = _json_safe(synthesis)
        resp = (
            admin_client()
            .table("influencer_cache")
            .upsert(row, on_conflict="handle,platform")
            .select("id")
            .execute()
        )
        return resp.data[0]["id"] if resp.data else None
    except Exception:
        return None


def upsert_cached_posts(cache_id: str, posts_with_classifs: list[dict]) -> None:
    """Insère les nouveaux posts dans le cache global (les existants sont préservés).

    `posts_with_classifs` : liste de {"post": post_dict, "classification": classif | None}.
    Les métriques (likes/comments/reposts) des posts déjà présents en cache ne sont
    PAS mises à jour — conformément à la décision ALE-109 ("métriques figées").
    La clé de déduplication est (influencer_cache_id, url).
    """
    if not admin_enabled() or not posts_with_classifs:
        return
    try:
        admin = admin_client()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        existing_resp = (
            admin.table("cached_posts")
            .select("url")
            .eq("influencer_cache_id", cache_id)
            .execute()
        )
        existing_urls = {r["url"] for r in (existing_resp.data or []) if r.get("url")}

        new_rows = []
        for item in posts_with_classifs:
            post = item.get("post", {})
            url = post.get("url")
            if not url or url in existing_urls:
                continue
            classif = item.get("classification")
            date = post.get("date")
            row: dict[str, Any] = {
                "influencer_cache_id": cache_id,
                "url": url,
                "text": post.get("text"),
                "posted_at": date.isoformat() if hasattr(date, "isoformat") else date,
                "format": post.get("format"),
                "likes": int(post.get("likes", 0) or 0),
                "comments": int(post.get("comments", 0) or 0),
                "reposts": int(post.get("reposts", 0) or 0),
                "engagement": int(post.get("engagement", 0) or 0),
                "length_chars": int(post.get("length_chars", 0) or 0),
                "length_words": int(post.get("length_words", 0) or 0),
            }
            if classif:
                row.update({
                    "stage": classif.get("stage"),
                    "hook_type": classif.get("hook_type"),
                    "topic": classif.get("topic"),
                    "angle": classif.get("angle"),
                    "classified_at": now,
                })
            new_rows.append(row)

        if new_rows:
            admin.table("cached_posts").insert(new_rows).execute()
    except Exception:
        pass  # La persistance du cache ne doit jamais bloquer l'analyse


# ── Posts hebdo (ALE-159) ─────────────────────────────────────────────────── #

# Jours par défaut : lundi (0), mercredi (2), vendredi (4) à 9h Europe/Paris.
_WEEKLY_DEFAULTS: list[dict[str, Any]] = [
    {"day_of_week": 0, "hour": 9, "timezone": "Europe/Paris"},
    {"day_of_week": 2, "hour": 9, "timezone": "Europe/Paris"},
    {"day_of_week": 4, "hour": 9, "timezone": "Europe/Paris"},
]


def get_weekly_posts_enabled(access_token: str) -> bool:
    """Whether the user opted in to the weekly posts cron."""
    profile = get_editorial_profile(access_token)
    return bool(profile and profile.get("weekly_posts_enabled"))


def set_weekly_posts_enabled(access_token: str, enabled: bool) -> dict | None:
    """Toggle the user's weekly-posts opt-in (creating the profile row if needed)."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    row = {
        "user_id": user["id"],
        "weekly_posts_enabled": bool(enabled),
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    resp = (
        db.table("user_editorial_profiles")
        .upsert(row, on_conflict="user_id")
        .execute()
    )
    # À la première activation, pré-remplir le planning avec les jours par
    # défaut (Lun/Mer/Ven 9h) pour que la grille ne soit pas vide. On ne touche
    # pas à un planning déjà configuré, et on ne sème rien à la désactivation.
    if enabled:
        existing = (
            db.table("weekly_post_schedule")
            .select("id")
            .eq("user_id", user["id"])
            .limit(1)
            .execute()
        )
        if not (existing.data or []):
            set_weekly_schedule(access_token, _WEEKLY_DEFAULTS)
    return resp.data[0] if resp.data else None


def get_weekly_schedule(access_token: str) -> list[dict]:
    """Return the user's weekly schedule slots exactly as stored.

    An empty list means the user has no day configured (and thus wants no
    posts). Defaults are only seeded at opt-in time (``set_weekly_posts_enabled``),
    never silently substituted here — otherwise unchecking every day would
    resurrect the Mon/Wed/Fri defaults.
    """
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("weekly_post_schedule")
        .select("day_of_week, hour, timezone")
        .eq("user_id", user["id"])
        .order("day_of_week")
        .execute()
    )
    return resp.data or []


def set_weekly_schedule(access_token: str, slots: list[dict]) -> list[dict]:
    """Replace the user's weekly schedule with the provided slots.

    Each slot must have ``day_of_week`` (0-6), ``hour`` (0-23), and optionally
    ``timezone`` (defaults to 'Europe/Paris'). Existing rows are deleted first
    (replace semantics).
    """
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    user_id = user["id"]
    db.table("weekly_post_schedule").delete().eq("user_id", user_id).execute()
    if not slots:
        return []
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rows = [
        {
            "user_id": user_id,
            "day_of_week": int(s["day_of_week"]),
            "hour": int(s.get("hour", 9)),
            "timezone": str(s.get("timezone", "Europe/Paris")),
            "created_at": now,
            "updated_at": now,
        }
        for s in slots
        if 0 <= int(s.get("day_of_week", -1)) <= 6
    ]
    if not rows:
        return []
    resp = db.table("weekly_post_schedule").insert(rows).execute()
    return resp.data or []


# --- Cron helpers (service-role, bypass RLS) -------------------------------- #

def list_weekly_posts_users() -> list[str]:
    """User ids that opted in to the weekly posts cron (service-role)."""
    if not admin_enabled():
        return []
    db = admin_client()
    resp = (
        db.table("user_editorial_profiles")
        .select("user_id")
        .eq("weekly_posts_enabled", True)
        .execute()
    )
    return [r["user_id"] for r in (resp.data or []) if r.get("user_id")]


def get_weekly_schedule_for_user(user_id: str) -> list[dict]:
    """Return the weekly schedule slots for a given user (service-role).

    Returns exactly what is stored: an empty list means the user configured no
    day, so the cron must generate nothing. No defaults fallback here — the
    opt-in switch is the master control and defaults are only seeded at opt-in.
    """
    if not admin_enabled():
        return []
    db = admin_client()
    resp = (
        db.table("weekly_post_schedule")
        .select("day_of_week, hour, timezone")
        .eq("user_id", user_id)
        .order("day_of_week")
        .execute()
    )
    return resp.data or []


def get_slack_config_for_user(user_id: str) -> dict | None:
    """Fetch Slack bot_token + channel_id for a user (service-role, for crons)."""
    if not admin_enabled():
        return None
    resp = (
        admin_client()
        .table("user_integrations")
        .select("access_token, channel_id")
        .eq("user_id", user_id)
        .eq("service", "slack")
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def create_scheduled_post_admin(
    user_id: str,
    post_text: str,
    scheduled_at_iso: str,
) -> dict | None:
    """Insert a scheduled post with service-role (no user JWT). Used by crons."""
    if not admin_enabled():
        return None
    resp = (
        admin_client()
        .table("scheduled_posts")
        .insert({
            "user_id": user_id,
            "post_text": post_text,
            "scheduled_at": scheduled_at_iso,
            "media_items": [],
            "slack_status": "pending",
        })
        .execute()
    )
    return resp.data[0] if resp.data else None


def set_scheduled_post_slack_ts_admin(post_id: str, message_ts: str) -> None:
    """Persist the Slack message timestamp for a scheduled post (service-role)."""
    if not admin_enabled():
        return
    admin_client().table("scheduled_posts").update({
        "slack_message_ts": message_ts,
        "updated_at": "now()",
    }).eq("id", post_id).execute()


def weekly_post_exists(user_id: str, utc_date: str) -> bool:
    """True if a non-cancelled scheduled post already exists for this user on utc_date.

    `utc_date` is YYYY-MM-DD. Used by the weekly cron for idempotency.
    """
    if not admin_enabled():
        return False
    resp = (
        admin_client()
        .table("scheduled_posts")
        .select("id")
        .eq("user_id", user_id)
        .gte("scheduled_at", f"{utc_date}T00:00:00+00:00")
        .lte("scheduled_at", f"{utc_date}T23:59:59+00:00")
        .neq("status", "cancelled")
        .limit(1)
        .execute()
    )
    return bool(resp.data)


# ---------------------------------------------------------------------------
# Agent de qualification Instagram (ALE-195 / 201)
#
# Le webhook ManyChat entrant n'a pas de session utilisateur → écritures
# service-role STRICTEMENT scellées sur le user_id propriétaire du compte IG
# (patron du cron daily_ideas). En v1 mono-compte, ce propriétaire est résolu
# via l'env IG_OWNER_USER_ID. Les lectures UI (204) passent par le JWT (RLS).
# ---------------------------------------------------------------------------

def ig_owner_user_id() -> str | None:
    """App user_id propriétaire du compte Instagram (v1 mono-compte)."""
    return os.environ.get("IG_OWNER_USER_ID") or None


def get_or_create_ig_conversation_admin(
    user_id: str, prospect_id: str, prospect_name: str | None = None
) -> dict | None:
    """Retrouver ou créer la conversation d'un prospect (service-role, scellé user_id)."""
    if not admin_enabled():
        return None
    db = admin_client()
    existing = (
        db.table("ig_conversations")
        .select("*")
        .eq("user_id", user_id)
        .eq("prospect_id", prospect_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        row = existing.data[0]
        if prospect_name and not row.get("prospect_name"):
            upd = (
                db.table("ig_conversations")
                .update({"prospect_name": prospect_name, "updated_at": "now()"})
                .eq("id", row["id"])
                .execute()
            )
            return upd.data[0] if upd.data else row
        return row
    resp = (
        db.table("ig_conversations")
        .insert({
            "user_id": user_id,
            "prospect_id": prospect_id,
            "prospect_name": prospect_name,
        })
        .execute()
    )
    return resp.data[0] if resp.data else None


def add_ig_message_admin(
    user_id: str,
    conversation_id: str,
    *,
    role: str,
    source: str,
    text: str,
    kind: str = "text",
) -> dict | None:
    """Persister un message IG + rafraîchir les horodatages/fenêtre 24 h de la conversation.

    `role` in|out, `source` prospect|agent|human. Un message entrant (in) remet à
    zéro la fenêtre de réponse conforme (24 h après le dernier message du prospect).
    """
    if not admin_enabled():
        return None
    db = admin_client()
    msg = (
        db.table("ig_messages")
        .insert({
            "user_id": user_id,
            "conversation_id": conversation_id,
            "role": role,
            "source": source,
            "text": text or "",
            "kind": kind,
        })
        .execute()
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    conv_update: dict[str, Any] = {
        "last_message_at": now.isoformat(),
        "updated_at": "now()",
    }
    if role == "in":
        expires = now + datetime.timedelta(hours=24)
        conv_update["last_inbound_at"] = now.isoformat()
        conv_update["window_expires_at"] = expires.isoformat()
    db.table("ig_conversations").update(conv_update).eq("id", conversation_id).execute()
    return msg.data[0] if msg.data else None


def list_ig_conversations(access_token: str, limit: int = 100) -> list[dict]:
    """Lister les conversations IG de l'utilisateur (RLS), plus récentes d'abord."""
    if not supabase_enabled():
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("ig_conversations")
        .select("*")
        .order("last_message_at", desc=True)
        .limit(max(1, min(limit, 200)))
        .execute()
    )
    return resp.data or []


def list_ig_messages(access_token: str, conversation_id: str, limit: int = 200) -> list[dict]:
    """Lister les messages d'une conversation IG de l'utilisateur (RLS), chronologique."""
    if not supabase_enabled():
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("ig_messages")
        .select("*")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=False)
        .limit(max(1, min(limit, 500)))
        .execute()
    )
    return resp.data or []


def get_ig_conversation(access_token: str, conversation_id: str) -> dict | None:
    """Récupérer une conversation IG de l'utilisateur (RLS garantit la propriété)."""
    if not supabase_enabled():
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("ig_conversations")
        .select("*")
        .eq("id", conversation_id)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def add_ig_message(
    access_token: str,
    conversation_id: str,
    *,
    role: str,
    source: str,
    text: str,
    kind: str = "text",
) -> dict | None:
    """Insérer un message IG + rafraîchir la conversation, côté utilisateur (RLS).

    Variante token-scoped d'`add_ig_message_admin`, utilisée par les actions UI
    (envoi supervisé). RLS empêche l'écriture sur la conversation d'un autre user.
    """
    user = get_user(access_token)
    if not user or not supabase_enabled():
        return None
    db = client_for_token(access_token)
    msg = (
        db.table("ig_messages")
        .insert({
            "user_id": user["id"],
            "conversation_id": conversation_id,
            "role": role,
            "source": source,
            "text": text or "",
            "kind": kind,
        })
        .execute()
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    conv_update: dict[str, Any] = {
        "last_message_at": now.isoformat(),
        "updated_at": "now()",
    }
    if role == "in":
        expires = now + datetime.timedelta(hours=24)
        conv_update["last_inbound_at"] = now.isoformat()
        conv_update["window_expires_at"] = expires.isoformat()
    db.table("ig_conversations").update(conv_update).eq("id", conversation_id).execute()
    return msg.data[0] if msg.data else None


def list_ig_messages_admin(user_id: str, conversation_id: str, limit: int = 40) -> list[dict]:
    """Historique d'une conversation (service-role, scellé user_id) — pour le cerveau agent."""
    if not admin_enabled():
        return []
    resp = (
        admin_client()
        .table("ig_messages")
        .select("role, source, text, kind, created_at")
        .eq("user_id", user_id)
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=False)
        .limit(max(1, min(limit, 200)))
        .execute()
    )
    return resp.data or []


def create_ig_draft_admin(
    user_id: str,
    conversation_id: str,
    message_id: str,
    *,
    reply: str,
    confidence,
    needs_human: bool,
    reason,
) -> dict | None:
    """Persister une réponse suggérée (statut pending), service-role scellé user_id (ALE-202)."""
    if not admin_enabled():
        return None
    resp = (
        admin_client()
        .table("ig_drafts")
        .insert({
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "reply": reply or "",
            "confidence": confidence,
            "needs_human": bool(needs_human),
            "reason": reason,
            "status": "pending",
        })
        .execute()
    )
    return resp.data[0] if resp.data else None


def list_ig_drafts(access_token: str, conversation_id: str, limit: int = 50) -> list[dict]:
    """Lister les réponses suggérées d'une conversation (RLS), plus récentes d'abord."""
    if not supabase_enabled():
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("ig_drafts")
        .select("*")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)
        .limit(max(1, min(limit, 200)))
        .execute()
    )
    return resp.data or []


def get_ig_draft(access_token: str, draft_id: str) -> dict | None:
    """Récupérer une réponse suggérée de l'utilisateur (RLS garantit la propriété)."""
    if not supabase_enabled():
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("ig_drafts").select("*").eq("id", draft_id).limit(1).execute()
    )
    return resp.data[0] if resp.data else None


def update_ig_draft(
    access_token: str, draft_id: str, *, status: str, reply: str | None = None
) -> dict | None:
    """Mettre à jour le statut (et éventuellement le texte) d'un draft (RLS)."""
    if not supabase_enabled():
        return None
    payload: dict[str, Any] = {"status": status, "updated_at": "now()"}
    if reply is not None:
        payload["reply"] = reply
    db = client_for_token(access_token)
    resp = db.table("ig_drafts").update(payload).eq("id", draft_id).execute()
    return resp.data[0] if resp.data else None


def set_ig_conversation_mode(access_token: str, conversation_id: str, mode: str) -> dict | None:
    """Basculer une conversation entre supervisé et autopilot (RLS)."""
    if mode not in ("supervised", "autopilot") or not supabase_enabled():
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("ig_conversations")
        .update({"mode": mode, "updated_at": "now()"})
        .eq("id", conversation_id)
        .execute()
    )
    return resp.data[0] if resp.data else None
