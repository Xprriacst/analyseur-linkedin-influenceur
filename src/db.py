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
    cron). Must never be reachable from an HTTP endpoint — it would expose every
    user's data. Endpoints keep using `client_for_token`.
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


def get_user_corpus(access_token: str) -> list[dict]:
    """Load the user's full corpus (influencers + their posts) from Supabase.

    Returns a list of {"handle", "profile", "posts"} dicts shaped like the
    normalized pipeline output, so stats/patterns can be recomputed on top.
    """
    user = get_user(access_token)
    if not user:
        return []
    return _corpus_from_client(client_for_token(access_token), user["id"])


def _corpus_from_client(db: "Client", user_id: str) -> list[dict]:
    """Shared corpus loader, usable with a user JWT client or the admin client."""
    # Filtre user_id explicite en plus de RLS (défense en profondeur).
    inf_resp = (
        db.table("influencers")
        .select("*")
        .eq("user_id", user_id)
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
        }
        for variant in variants
        if variant.get("post")
    ]
    if not rows:
        return variants
    resp = db.table("generated_posts").insert(rows).execute()
    return resp.data if resp.data else variants


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


def list_generated_posts(access_token: str, limit: int = 100) -> list[dict]:
    """List the user's saved generated posts, newest first."""
    if not supabase_enabled():
        return []
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("generated_posts")
        .select("*")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
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


def update_generated_post(access_token: str, post_id: str, new_post: str) -> dict | None:
    """Update the text of a saved post. Returns the updated row or None."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("generated_posts")
        .update({"post": new_post})
        .eq("user_id", user["id"])
        .eq("id", post_id)
        .execute()
    )
    return resp.data[0] if resp.data else None


# ── Crédits utilisateur (ALE-41) ── #

CREDIT_COSTS: dict[str, int] = {
    "generate_post": 5,    # par variant
    "generate_ideas": 3,   # par idée
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
    # Première visite : initialiser via service-role
    if admin_enabled():
        try:
            admin_client().table("user_credits").insert({"user_id": user["id"], "balance": 20}).execute()
        except Exception:
            pass
    return {"balance": 20, "enabled": True}


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
    """List the user's idea seeds, oldest first (FIFO consumption order)."""
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
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def add_idea_seed(access_token: str, text: str) -> dict | None:
    """Add a seed idea to the user's reservoir."""
    if not supabase_enabled():
        return None
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("idea_seeds")
        .insert({"user_id": user["id"], "text": text})
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


def get_corpus_for_user(user_id: str) -> list[dict]:
    """Admin-side corpus loader for the cron (no user JWT available)."""
    if not admin_enabled():
        return []
    return _corpus_from_client(admin_client(), user_id)


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
    """Return the oldest unused seed for a user (service-role). Does not mark it."""
    if not admin_enabled():
        return None
    db = admin_client()
    resp = (
        db.table("idea_seeds")
        .select("*")
        .eq("user_id", user_id)
        .is_("used_at", "null")
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
    user_id: str, idea_markdown: str, idea_date: str, seed_id: str | None = None
) -> dict | None:
    """Persist a generated daily idea (service-role). Ignores conflicts on (user, date)."""
    if not admin_enabled():
        return None
    db = admin_client()
    row = {
        "user_id": user_id,
        "idea_markdown": idea_markdown,
        "idea_date": idea_date,
        "seed_id": seed_id,
    }
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


def get_user_by_slack_id(slack_user_id: str) -> dict | None:
    """Find user_id + bot token by Slack user ID (service-role, for webhook)."""
    if not admin_enabled():
        return None
    resp = (
        admin_client()
        .table("user_integrations")
        .select("user_id, access_token, channel_id")
        .eq("service", "slack")
        .eq("service_user_id", slack_user_id)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


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


# ── Monitoring influenceurs (ALE-32) ── #

def get_monitoring_for_user(access_token: str) -> list[dict]:
    """Liste les entrées de monitoring actives de l'utilisateur (avec infos influenceur)."""
    if not supabase_enabled():
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("influencer_monitoring")
        .select("*, influencers(handle, name, follower_count, profile_url)")
        .eq("is_active", True)
        .order("created_at", desc=False)
        .execute()
    )
    rows = resp.data or []
    result = []
    for row in rows:
        inf = row.pop("influencers", {}) or {}
        row["handle"] = inf.get("handle", "")
        row["name"] = inf.get("name", "")
        row["follower_count"] = inf.get("follower_count")
        row["profile_url"] = inf.get("profile_url", "")
        result.append(row)
    return result


def upsert_influencer_monitoring(
    access_token: str,
    influencer_id: str,
    is_active: bool = True,
    frequency: str = "daily",
) -> dict | None:
    """Active ou met à jour le monitoring d'un influenceur pour l'utilisateur."""
    if not supabase_enabled():
        return None
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    row = {
        "user_id": user["id"],
        "influencer_id": influencer_id,
        "is_active": is_active,
        "frequency": frequency,
    }
    resp = (
        db.table("influencer_monitoring")
        .upsert(row, on_conflict="user_id,influencer_id")
        .execute()
    )
    return resp.data[0] if resp.data else None


def delete_influencer_monitoring(access_token: str, influencer_id: str) -> None:
    """Supprime le monitoring d'un influenceur pour l'utilisateur."""
    if not supabase_enabled():
        return
    db = client_for_token(access_token)
    db.table("influencer_monitoring").delete().eq("influencer_id", influencer_id).execute()


# ── Helpers cron monitoring (admin seulement — jamais exposés via HTTP) ── #

def list_active_monitoring_entries() -> list[dict]:
    """Retourne toutes les entrées de monitoring actives (admin, pour le cron)."""
    if not admin_enabled():
        return []
    resp = (
        admin_client()
        .table("influencer_monitoring")
        .select("*, influencers(handle, profile_url)")
        .eq("is_active", True)
        .execute()
    )
    rows = resp.data or []
    result = []
    for row in rows:
        inf = row.pop("influencers", {}) or {}
        row["handle"] = inf.get("handle", "")
        row["profile_url"] = inf.get("profile_url", "")
        result.append(row)
    return result


def get_post_urls_for_influencer(influencer_id: str) -> set:
    """Retourne les URLs de posts existants pour cet influenceur (admin)."""
    resp = (
        admin_client()
        .table("posts")
        .select("url")
        .eq("influencer_id", influencer_id)
        .execute()
    )
    return {row["url"] for row in (resp.data or []) if row.get("url")}


def save_new_posts_for_influencer(influencer_id: str, posts: list[dict]) -> int:
    """Insère les nouveaux posts sans supprimer les existants. Retourne le nombre inséré."""
    if not posts:
        return 0
    rows = _post_rows(influencer_id, posts)
    if not rows:
        return 0
    resp = admin_client().table("posts").insert(rows).execute()
    return len(resp.data or [])


def update_monitoring_last_checked(monitor_id: str, new_posts_count: int = 0) -> None:
    """Met à jour last_monitored_at et le compteur de nouveaux posts (admin)."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    admin_client().table("influencer_monitoring").update({
        "last_monitored_at": now,
        "new_posts_since_last": new_posts_count,
    }).eq("id", monitor_id).execute()


def get_user_credits_admin(user_id: str) -> int:
    """Retourne le solde de crédits d'un user sans JWT (admin, pour le cron)."""
    if not admin_enabled():
        return 999
    resp = (
        admin_client()
        .table("user_credits")
        .select("balance")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    return resp.data["balance"] if resp.data else 0


def debit_credits_admin(user_id: str, amount: int, action: str) -> bool:
    """Débite des crédits via le service-role (pour le cron, sans JWT user)."""
    if not admin_enabled():
        return True
    try:
        admin_client().rpc("debit_credits", {
            "p_user_id": user_id,
            "p_amount": amount,
            "p_action": action,
            "p_description": f"[cron] {action}",
        }).execute()
        return True
    except Exception:
        return False
