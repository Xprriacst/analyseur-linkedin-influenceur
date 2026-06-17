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
        "stats": _json_safe(result.get("stats")),
        "patterns": _json_safe(result.get("patterns")),
        "classifications": _json_safe(result.get("classifications")),
        "synthesis": _json_safe(result.get("synthesis")),
        "cta_stats": _json_safe(result.get("cta_stats")),
        "usage": _json_safe(result.get("usage")),
        "posts_limit": posts_limit,
    }
    an_resp = db.table("analyses").insert(analysis_row).execute()
    analysis_id = an_resp.data[0]["id"] if an_resp.data else None
    return {"influencer_id": influencer_id, "analysis_id": analysis_id}


def get_user_corpus(access_token: str) -> list[dict]:
    """Load the user's full corpus (influencers + their posts) from Supabase.

    Returns a list of {"handle", "profile", "posts"} dicts shaped like the
    normalized pipeline output, so stats/patterns can be recomputed on top.
    """
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)

    # Filtre user_id explicite en plus de RLS (défense en profondeur).
    inf_resp = (
        db.table("influencers")
        .select("*")
        .eq("user_id", user["id"])
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
        .select("id,handle,created_at,posts_limit")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
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
        .select("id,handle,created_at,report_markdown,influencers(name)")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    reports = []
    for row in resp.data or []:
        created = row.get("created_at") or ""
        try:
            from datetime import datetime
            ts = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
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
        }
        for idea in ideas
    ]
    resp = db.table("generated_ideas").insert(rows).execute()
    return resp.data if resp.data else ideas


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
) -> dict | None:
    """Crée une série (job) + ses items (un par URL). Retourne le job complet."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    job_resp = (
        db.table("analysis_jobs")
        .insert({
            "user_id": user["id"],
            "status": "queued",
            "total": len(urls),
            "limit_posts": limit_posts,
            "run_llm": run_llm,
            "use_cache": use_cache,
        })
        .execute()
    )
    if not job_resp.data:
        return None
    job = job_resp.data[0]
    items = [
        {
            "job_id": job["id"],
            "user_id": user["id"],
            "position": i,
            "url": url,
            "handle": _handle_from_url(url),
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
    return jobs


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
