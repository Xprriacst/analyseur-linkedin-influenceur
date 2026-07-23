"""Supabase data-access layer.

The backend stays usable without Supabase configured (file-based fallback).
When a user JWT is provided, a per-request client is created so that Postgres
Row Level Security applies and data is scoped to that user automatically.
"""
from __future__ import annotations

import datetime
import os
import threading
import time
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


def log_onboarding_preview_event(
    input_kind: str | None,
    linkedin_url: str | None,
    website_url: str | None,
    used_apify: bool,
    preview_ok: bool,
    ip_hash: str | None,
) -> None:
    """Journalise une analyse lancée depuis la landing (parcours anonyme).

    Best-effort : le visiteur n'a pas de session, on écrit donc en service-role
    (table `onboarding_preview_events`, sans RLS policy = inaccessible côté client).
    Un échec de log ne doit JAMAIS bloquer la preview → toute exception est avalée.
    """
    if not supabase_enabled() or not admin_enabled():
        return
    try:
        admin_client().table("onboarding_preview_events").insert({
            "input_kind": input_kind,
            "linkedin_url": linkedin_url or None,
            "website_url": website_url or None,
            "used_apify": bool(used_apify),
            "preview_ok": bool(preview_ok),
            "ip_hash": ip_hash,
        }).execute()
    except Exception:
        pass


# Successful validations are cached in-process: virtually every db helper
# re-validates the same token, and each validation is a network round-trip to
# Supabase Auth. Trade-off: a revoked token stays accepted at most TTL seconds.
_USER_CACHE: dict[str, tuple[float, dict]] = {}
_USER_CACHE_LOCK = threading.Lock()
_USER_CACHE_TTL = 60.0
_USER_CACHE_MAX = 1000


def _copy_user(entry: dict) -> dict:
    """Copie défensive d'une entrée du cache.

    `dict(entry)` ne copierait que le premier niveau : `app_metadata` resterait partagé
    par référence avec le cache, qui est global au process. Un appelant qui le modifierait
    (même par accident) altérerait les droits vus par TOUS les appels suivants sur ce
    jeton — y compris les feature flags."""
    copied = dict(entry)
    meta = copied.get("app_metadata")
    copied["app_metadata"] = dict(meta) if isinstance(meta, dict) else {}
    return copied


def get_user(access_token: str) -> dict | None:
    """Validate a JWT and return the matching user, or None if invalid.

    Inclut `app_metadata` : c'est là que vivent le rôle (`ideas_only`) et les feature
    flags (`src/features.py`). Écrivable uniquement par la clé service-role — un client
    ne peut donc pas s'octroyer un droit en modifiant son propre profil.

    ⚠️ Conséquence du cache ci-dessus : poser ou retirer un flag met jusqu'à
    `_USER_CACHE_TTL` secondes à être pris en compte côté serveur. Acceptable pour un
    déploiement progressif, à connaître si un test « je ne vois toujours rien » suit
    de quelques secondes une modification d'`app_metadata`."""
    if not supabase_enabled():
        return None
    now = time.monotonic()
    with _USER_CACHE_LOCK:
        hit = _USER_CACHE.get(access_token)
        if hit and now - hit[0] < _USER_CACHE_TTL:
            return _copy_user(hit[1])
    try:
        client = create_client(_url(), _anon_key())  # type: ignore[arg-type]
        resp = client.auth.get_user(access_token)
    except Exception:
        return None
    user = getattr(resp, "user", None)
    if not user:
        return None
    raw_meta = getattr(user, "app_metadata", None)
    entry = {
        "id": user.id,
        "email": getattr(user, "email", None),
        "app_metadata": dict(raw_meta) if isinstance(raw_meta, dict) else {},
    }
    with _USER_CACHE_LOCK:
        if len(_USER_CACHE) >= _USER_CACHE_MAX:
            for key in [k for k, (ts, _) in _USER_CACHE.items() if now - ts >= _USER_CACHE_TTL]:
                _USER_CACHE.pop(key, None)
            if len(_USER_CACHE) >= _USER_CACHE_MAX:
                _USER_CACHE.clear()
        _USER_CACHE[access_token] = (now, entry)
    return _copy_user(entry)


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
        media_items = p.get("media_items")
        if media_items:
            row["media_items"] = media_items
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


def list_analysis_stats(access_token: str, platform: str = "linkedin") -> list[dict]:
    """Current analyses with their stats + influencer metadata (no markdown).

    Feeds the cross-report trends computation (src/trends.py).
    """
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("analyses")
        .select("id,handle,influencer_id,updated_at,stats,influencers(name,follower_count,platform)")
        .eq("user_id", user["id"])
        .order("updated_at", desc=True)
        .execute()
    )
    rows = []
    for row in resp.data or []:
        inf = row.get("influencers") or {}
        if isinstance(inf, list):
            inf = inf[0] if inf else {}
        if (inf.get("platform") or "linkedin") != platform:
            continue
        rows.append(row)
    return rows


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


def set_zernio_account(
    access_token: str,
    account_id: str | None,
    account_name: str | None = None,
    account_type: str | None = None,
) -> dict | None:
    """Persist (or clear) the connected LinkedIn account (id + nom + type) for this user."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    row = {
        "user_id": user["id"],
        "zernio_account_id": account_id,
        "zernio_account_name": account_name if account_id else None,
        "zernio_account_type": account_type if account_id else None,
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


def set_zernio_reddit_account(access_token: str, account_id: str | None) -> dict | None:
    """Persist (or clear) the connected Reddit account id for this user (ALE-59)."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    row = {
        "user_id": user["id"],
        "zernio_reddit_account_id": account_id,
        "zernio_reddit_connected_at": now if account_id else None,
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
    access_token: str,
    limit: int = 100,
    saved_only: bool = False,
    pending_validation: bool = False,
) -> list[dict]:
    """List the user's generated posts, newest first.

    With ``saved_only=True``, only posts explicitly marked ``saved`` are returned
    (ALE-135 : « Mes contenus » n'affiche que les posts sauvegardés).
    With ``pending_validation=True``, only posts awaiting client validation
    (``slack_status='pending'``, not yet published on LinkedIn).
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
    if pending_validation:
        query = query.eq("slack_status", "pending").is_("zernio_post_id", "null")
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
# défaut de colonne et l'auto-création dans debit_credits() (migration 0047).
WELCOME_CREDITS = 150

CREDIT_COSTS: dict[str, int] = {
    "generate_post": 5,    # par variant
    "generate_ideas": 3,   # par lot (ALE-143)
    "analyze_job": 20,     # par influenceur
    "chat": 2,             # par message
    "generate_image": 5,
    "collect_leads": 1,    # par crédit ; le nb débité = nb de commentateurs / N (ALE-239)
    "adapt_x": 2,          # adaptation IA d'un post pour X (ALE-59)
    "adapt_reddit": 3,     # adaptation IA d'un post pour Reddit + suggestion subreddits (ALE-59)
}


def get_user_credits(access_token: str) -> dict:
    """Retourne le solde de crédits de l'utilisateur (crée l'offre de bienvenue au 1er appel)."""
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
    # Première visite : initialiser via service-role (offre de bienvenue = WELCOME_CREDITS).
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


def refund_credits_admin(
    user_id: str | None, action: str, count: int = 1, description: str | None = None
) -> None:
    """Recrédite un utilisateur (remboursement d'une action non livrée).

    Passe par la même fonction Postgres que le débit, avec un montant négatif :
    le mouvement est journalisé dans credit_ledger avec un delta positif.
    Best-effort — un remboursement raté ne doit jamais casser le flux appelant.
    """
    if not user_id or not supabase_enabled() or not admin_enabled():
        return
    cost = CREDIT_COSTS.get(action, 5) * max(1, count)
    try:
        admin_client().rpc("debit_credits", {
            "p_user_id": user_id,
            "p_amount": -cost,
            "p_action": f"refund_{action}",
            "p_description": description or f"remboursement {action} x{count}",
        }).execute()
    except Exception:
        pass


# ── Abonnement Stripe (ALE-274) ── #
#
# Toutes les écritures passent par le service-role : l'état d'abonnement est
# dicté par Stripe (via le webhook), jamais par le client. Côté utilisateur, la
# table est en lecture seule (RLS, migration 0046).

_SUBSCRIPTION_COLS = (
    "user_id, stripe_customer_id, stripe_subscription_id, status, price_id, "
    "cancel_at_period_end, current_period_end, updated_at"
)


def get_subscription(access_token: str) -> dict | None:
    """Abonnement de l'utilisateur courant (RLS), ou None s'il n'en a jamais eu."""
    if not supabase_enabled():
        return None
    user = get_user(access_token)
    if not user:
        return None
    try:
        resp = (
            client_for_token(access_token)
            .table("user_subscriptions")
            .select(_SUBSCRIPTION_COLS)
            .eq("user_id", user["id"])
            .limit(1)
            .execute()
        )
        rows = resp.data if resp and getattr(resp, "data", None) else []
    except Exception:
        return None
    return rows[0] if rows else None


def get_subscription_by_user_admin(user_id: str) -> dict | None:
    if not admin_enabled() or not user_id:
        return None
    try:
        resp = (
            admin_client()
            .table("user_subscriptions")
            .select(_SUBSCRIPTION_COLS)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = resp.data if resp and getattr(resp, "data", None) else []
    except Exception:
        return None
    return rows[0] if rows else None


def get_subscription_by_customer_admin(customer_id: str) -> dict | None:
    """Retrouve le compte app depuis l'identifiant client Stripe.

    C'est le chemin de rattachement du webhook : une facture ne porte que le
    client et l'abonnement Stripe, jamais notre user_id.
    """
    if not admin_enabled() or not customer_id:
        return None
    try:
        resp = (
            admin_client()
            .table("user_subscriptions")
            .select(_SUBSCRIPTION_COLS)
            .eq("stripe_customer_id", customer_id)
            .limit(1)
            .execute()
        )
        rows = resp.data if resp and getattr(resp, "data", None) else []
    except Exception:
        return None
    return rows[0] if rows else None


def upsert_subscription_admin(user_id: str, **fields: Any) -> dict | None:
    """Crée/met à jour l'état d'abonnement (service-role). Les champs absents sont laissés tels quels."""
    if not admin_enabled() or not user_id:
        return None
    payload = {k: v for k, v in fields.items() if v is not None}
    payload["user_id"] = user_id
    payload["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        resp = (
            admin_client()
            .table("user_subscriptions")
            .upsert(payload, on_conflict="user_id")
            .execute()
        )
        return resp.data[0] if resp and getattr(resp, "data", None) else None
    except Exception:
        return None


def set_credits_admin(
    user_id: str, amount: int, action: str = "subscription_renewal", description: str | None = None
) -> int | None:
    """FIXE le solde à `amount` (pas d'incrément) — renouvellement d'abonnement.

    Décision produit : les crédits non consommés ne sont pas reportés d'un mois
    sur l'autre. Retourne le nouveau solde, ou None si l'écriture a échoué (le
    webhook renvoie alors une erreur → Stripe rejoue l'événement).
    """
    if not admin_enabled() or not user_id:
        return None
    try:
        resp = admin_client().rpc("set_credits", {
            "p_user_id": user_id,
            "p_amount": int(amount),
            "p_action": action,
            "p_description": description or f"abonnement : solde remis à {amount}",
        }).execute()
        return resp.data if isinstance(resp.data, int) else int(amount)
    except Exception:
        return None


def billing_event_already_processed(event_id: str, event_type: str, user_id: str | None) -> bool:
    """Marque un événement Stripe comme traité. True s'il l'était déjà (rejeu).

    Stripe rejoue un événement tant qu'il n'a pas reçu de 2xx : sans ce garde-fou,
    un rejeu de `invoice.paid` re-fixerait le solde à 1000 (et effacerait la
    consommation du mois en cours). L'insertion sur clé primaire = verrou atomique.
    """
    if not admin_enabled() or not event_id:
        return False
    try:
        admin_client().table("billing_events").insert(
            {"id": event_id, "type": event_type, "user_id": user_id}
        ).execute()
        return False
    except Exception as exc:
        # 23505 = violation de clé primaire → l'événement a déjà été traité.
        if "23505" in str(exc) or "duplicate key" in str(exc).lower():
            return True
        raise


def delete_billing_event_admin(event_id: str) -> None:
    """Retire un événement du journal d'idempotence.

    Appelé quand le traitement a échoué APRÈS l'avoir marqué traité (ex. le crédit
    n'a pas pu s'appliquer) : sans ça, le rejeu de Stripe serait vu comme un
    doublon et l'utilisateur ne serait jamais crédité.
    """
    if not admin_enabled() or not event_id:
        return
    try:
        admin_client().table("billing_events").delete().eq("id", event_id).execute()
    except Exception:
        pass


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
    (`done`/`error`) et qu'une seule transition a lieu même en cas d'appels
    concurrents — c'est cette transition qui déclenche le remboursement du
    crédit de l'analyse non livrée. RLS scope l'update au propriétaire via le JWT.
    """
    db = client_for_token(access_token)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    resp = (
        db.table("analysis_job_items")
        .update({"status": "cancelled", "updated_at": now})
        .eq("id", item_id)
        .in_("status", ["pending", "running"])
        .execute()
    )
    for row in resp.data or []:
        refund_credits_admin(
            row.get("user_id"), "analyze_job", description="remboursement analyse annulée"
        )
    return get_job_item_status(access_token, item_id)


def cancel_pending_items(access_token: str, job_id: str) -> None:
    """Annule tous les items encore en attente/en cours d'une série (cancel global).

    Chaque item réellement transitionné est remboursé (analyse non livrée).
    """
    db = client_for_token(access_token)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    resp = (
        db.table("analysis_job_items")
        .update({"status": "cancelled", "updated_at": now})
        .eq("job_id", job_id)
        .in_("status", ["pending", "running"])
        .execute()
    )
    rows = resp.data or []
    if rows:
        refund_credits_admin(
            rows[0].get("user_id"), "analyze_job", count=len(rows),
            description=f"remboursement série annulée ({len(rows)} profil(s))",
        )


def fail_job_item(access_token: str, item_id: str, error: str) -> bool:
    """Passe un item en `error` s'il est encore actif, et rembourse son crédit.

    Transition gardée (`in_` sur les statuts actifs) : un item déjà finalisé
    (`done`/`cancelled`/`error`) n'est jamais réécrit, et deux appels
    concurrents (thread + réconciliation, deux onglets qui pollent) ne
    remboursent qu'une seule fois. Retourne True si la transition a eu lieu.
    """
    db = client_for_token(access_token)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    resp = (
        db.table("analysis_job_items")
        .update({"status": "error", "error": error, "updated_at": now})
        .eq("id", item_id)
        .in_("status", ["pending", "running"])
        .execute()
    )
    rows = resp.data or []
    for row in rows:
        refund_credits_admin(
            row.get("user_id"), "analyze_job", description="remboursement analyse échouée"
        )
    return bool(rows)


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
                if fail_job_item(access_token, it["id"], "Analyse interrompue (délai dépassé)."):
                    it["status"] = "error"
            elif it.get("status") == "pending":
                if fail_job_item(access_token, it["id"], "Non démarrée — série interrompue."):
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

# Toute colonne absente de cette projection est lue `None` par le thread de
# génération, SANS erreur : c'est ainsi que `template_id` a été ignoré pendant
# toute la vie d'ALE-216 (le template choisi n'atteignait jamais le modèle).
# Ajouter une colonne au job ⇒ l'ajouter ici.
_GENERATION_JOB_COLS = (
    "id,status,topic,editorial_role,web_search,count,template_id,"
    "inspiration_text,inspiration_author,inspiration_url,"
    "result,error,created_at,updated_at"
)


def create_generation_job(
    access_token: str,
    topic: str | None,
    editorial_role: str | None,
    web_search: bool,
    count: int,
    template_id: str | None = None,
    inspiration: dict | None = None,
) -> dict | None:
    """Crée un job de génération `queued`. Retourne la ligne créée."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    row: dict[str, Any] = {
        "user_id": user["id"],
        "status": "queued",
        "topic": topic or None,
        "editorial_role": editorial_role or None,
        "web_search": bool(web_search),
        "count": count,
    }
    if template_id:
        row["template_id"] = template_id
    if inspiration and (inspiration.get("text") or "").strip():
        row["inspiration_text"] = inspiration["text"].strip()[:6000]
        row["inspiration_author"] = (inspiration.get("author") or "").strip()[:200] or None
        row["inspiration_url"] = (inspiration.get("url") or "").strip()[:2000] or None
    resp = (
        db.table("generation_jobs")
        .insert(row)
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


# ---------------------------------------------------------------------------
# File d'attente de génération d'image IA (ALE-261)
# ---------------------------------------------------------------------------
# Même patron que generation_jobs : une ligne = une génération d'image. Le
# `target_key` (opaque, fourni par le frontend) identifie le bloc de post
# auquel l'image doit se rattacher, pour qu'elle rejoigne le bon post même
# après fermeture de la pop-up. Crédits débités à la complétion réussie
# uniquement (jamais au lancement) — un échec ne coûte donc jamais de crédit,
# pas de remboursement à gérer (contrairement aux séries d'analyse).

_IMAGE_JOB_COLS = (
    "id,status,post_text,prompt,reference_template_id,reference_self_photo_ids,"
    "target_key,result,error,created_at,updated_at"
)

# Photos de soi (0054) : plafond par compte + max transmis à GPT Image 2 par génération.
SELF_PHOTOS_CAP = 5
SELF_PHOTOS_PER_GEN = 3


def create_image_job(
    access_token: str,
    post_text: str,
    prompt: str | None,
    reference_template_id: str | None,
    target_key: str,
    reference_self_photo_ids: list[str] | None = None,
) -> dict | None:
    """Crée un job de génération d'image `queued`. Retourne la ligne créée."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    row: dict[str, Any] = {
        "user_id": user["id"],
        "status": "queued",
        "post_text": post_text,
        "prompt": prompt or None,
        "target_key": target_key,
        "reference_self_photo_ids": list(reference_self_photo_ids or [])[:SELF_PHOTOS_PER_GEN],
    }
    if reference_template_id:
        row["reference_template_id"] = reference_template_id
    resp = db.table("image_generation_jobs").insert(row).execute()
    return resp.data[0] if resp.data else None


def get_image_job(access_token: str, job_id: str) -> dict | None:
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    r = (
        db.table("image_generation_jobs")
        .select(_IMAGE_JOB_COLS)
        .eq("id", job_id)
        .eq("user_id", user["id"])
        .limit(1)
        .execute()
    )
    return r.data[0] if r.data else None


def list_image_jobs(access_token: str, limit: int = 30) -> list[dict]:
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    r = (
        db.table("image_generation_jobs")
        .select(_IMAGE_JOB_COLS)
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return reconcile_stale_image_jobs(access_token, r.data or [])


def get_image_job_status(access_token: str, job_id: str) -> str | None:
    """Statut seul (lecture légère, pour la vérif d'annulation du thread)."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    r = (
        db.table("image_generation_jobs")
        .select("status")
        .eq("id", job_id)
        .eq("user_id", user["id"])
        .limit(1)
        .execute()
    )
    return r.data[0]["status"] if r.data else None


def update_image_job(access_token: str, job_id: str, **fields: Any) -> None:
    db = client_for_token(access_token)
    fields["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    db.table("image_generation_jobs").update(fields).eq("id", job_id).execute()


def cancel_image_job(access_token: str, job_id: str) -> dict | None:
    """Annule un job d'image s'il est encore `queued`/`running`.

    Jamais de remboursement ici : le débit n'intervient qu'à la complétion
    réussie (cf. `src.jobs.process_image_job`), donc un job annulé n'a jamais
    été débité.
    """
    db = client_for_token(access_token)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (
        db.table("image_generation_jobs")
        .update({"status": "cancelled", "updated_at": now})
        .eq("id", job_id)
        .in_("status", ["queued", "running"])
        .execute()
    )
    return get_image_job(access_token, job_id)


def reconcile_stale_image_jobs(access_token: str, jobs: list[dict]) -> list[dict]:
    """Solde les jobs d'image orphelins (thread mort/figé) — appelé au listing.

    Même logique que `reconcile_stale_generation_jobs`. Idempotent.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(minutes=JOB_STALE_MINUTES)
    for job in jobs:
        if job.get("status") not in ("queued", "running"):
            continue
        job_ts = _parse_ts(job.get("updated_at"))
        if job_ts is None or job_ts > cutoff:
            continue
        update_image_job(
            access_token, job["id"], status="error",
            error="Génération d'image interrompue (délai dépassé).",
        )
        job["status"] = "error"
        job["error"] = "Génération d'image interrompue (délai dépassé)."
    return jobs


# ── Photos de soi (génération d'image à identité) ─────────────────────────── #

def list_self_photos(access_token: str, limit: int = 20) -> list[dict]:
    """Liste les photos de soi de l'utilisateur (plus récentes d'abord)."""
    if not supabase_enabled():
        return []
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("user_self_photos")
        .select("id,image_url,filename,created_at")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def get_self_photos_by_ids(access_token: str, photo_ids: list[str]) -> list[dict]:
    """Récupère des photos de soi appartenant à l'utilisateur (ordre = ids demandés)."""
    if not supabase_enabled() or not photo_ids:
        return []
    user = get_user(access_token)
    if not user:
        return []
    # Dédoublonne en conservant l'ordre, plafonne au max transmis à l'API image.
    seen: set[str] = set()
    ordered: list[str] = []
    for pid in photo_ids:
        pid = str(pid or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        ordered.append(pid)
        if len(ordered) >= SELF_PHOTOS_PER_GEN:
            break
    if not ordered:
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("user_self_photos")
        .select("id,image_url,filename,created_at")
        .eq("user_id", user["id"])
        .in_("id", ordered)
        .execute()
    )
    by_id = {row["id"]: row for row in (resp.data or [])}
    return [by_id[pid] for pid in ordered if pid in by_id]


def create_self_photo(
    access_token: str,
    image_url: str,
    filename: str | None = None,
) -> dict | None:
    """Ajoute une photo de soi (après upload Zernio). Respecte SELF_PHOTOS_CAP."""
    if not supabase_enabled():
        return None
    user = get_user(access_token)
    if not user:
        return None
    url = (image_url or "").strip()
    if not url:
        return None
    existing = list_self_photos(access_token, limit=SELF_PHOTOS_CAP + 1)
    if len(existing) >= SELF_PHOTOS_CAP:
        raise ValueError(f"Limite atteinte : {SELF_PHOTOS_CAP} photos maximum.")
    db = client_for_token(access_token)
    row: dict[str, Any] = {
        "user_id": user["id"],
        "image_url": url[:2000],
    }
    if filename:
        row["filename"] = str(filename)[:200]
    resp = db.table("user_self_photos").insert(row).execute()
    return resp.data[0] if resp.data else None


def delete_self_photo(access_token: str, photo_id: str) -> bool:
    """Supprime une photo de soi appartenant à l'utilisateur."""
    if not supabase_enabled() or not photo_id:
        return False
    user = get_user(access_token)
    if not user:
        return False
    db = client_for_token(access_token)
    resp = (
        db.table("user_self_photos")
        .delete()
        .eq("id", photo_id)
        .eq("user_id", user["id"])
        .execute()
    )
    return bool(resp.data)


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


def _as_reference_post(row: dict) -> dict:
    """Projette une entrée de bibliothèque au format « post de référence » legacy.

    Le mapping vit ici pour que llm._format_reference_posts (clés text/author/
    url/note) et le front legacy restent inchangés.
    """
    return {
        "id": row.get("id"),
        "text": row.get("post_text") or "",
        "url": row.get("source_post_url"),
        "author": row.get("source_author"),
        "note": row.get("note"),
        "created_at": row.get("created_at"),
    }


def list_reference_posts(access_token: str, limit: int = 200) -> list[dict]:
    """Entrées de la bibliothèque ayant un texte de post, au format legacy.

    Depuis ALE-222 tout vit dans post_templates (user_reference_posts est
    gelée) ; ce shim ne sert plus qu'aux endpoints /me/reference-posts
    conservés une release pour les onglets ouverts sur un vieux bundle.
    """
    if not supabase_enabled():
        return []
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("post_templates")
        .select("*")
        .eq("user_id", user["id"])
        .not_.is_("post_text", "null")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [_as_reference_post(row) for row in (resp.data or [])]


def add_reference_post(
    access_token: str,
    text: str,
    url: str | None = None,
    author: str | None = None,
    note: str | None = None,
) -> dict | None:
    """Shim legacy : ajoute une entrée texte-seul dans la bibliothèque unifiée."""
    row = add_post_template(
        access_token,
        post_text=text,
        note=note,
        source_author=author,
        source_post_url=url,
    )
    return _as_reference_post(row) if row else None


def pick_reference_posts(access_token: str | None, count: int = 3) -> list[dict]:
    """Échantillon de la bibliothèque (entrées avec texte) pour une génération.

    Aléatoire quand la bibliothèque dépasse `count`, pour varier l'inspiration
    d'un appel à l'autre. Best-effort : ne bloque jamais la génération.
    """
    if not access_token:
        return []
    try:
        refs = list_reference_posts(access_token, limit=50)
    except Exception:
        return []
    refs = [r for r in refs if (r.get("text") or "").strip()]
    if len(refs) <= count:
        return refs
    import random

    return random.sample(refs, count)


def delete_reference_post(access_token: str, ref_id: str) -> bool:
    """Shim legacy : supprime une entrée de la bibliothèque unifiée."""
    return delete_post_template(access_token, ref_id)


# ── Banque de templates de posts (ALE-216) ────────────────────────────────── #

def list_post_templates(access_token: str, limit: int = 200) -> list[dict]:
    """List the user's post templates, newest first."""
    if not supabase_enabled():
        return []
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("post_templates")
        .select("*")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def get_post_template(access_token: str, template_id: str) -> dict | None:
    """Fetch one of the user's templates (RLS scope)."""
    if not supabase_enabled() or not template_id:
        return None
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("post_templates")
        .select("*")
        .eq("id", template_id)
        .eq("user_id", user["id"])
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def add_post_template(
    access_token: str,
    structure_label: str | None = None,
    structure_text: str | None = None,
    format: str | None = None,
    image_url: str | None = None,
    image_note: str | None = None,
    source: str = "user",
    source_author: str | None = None,
    source_post_url: str | None = None,
    post_text: str | None = None,
    note: str | None = None,
) -> dict | None:
    """Ajoute une entrée à la bibliothèque (texte de post et/ou structure)."""
    if not supabase_enabled():
        return None
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    row: dict[str, Any] = {
        "user_id": user["id"],
        "source": source,
    }
    for key, value in (
        ("structure_label", structure_label),
        ("structure_text", structure_text),
        ("format", format),
        ("image_url", image_url),
        ("image_note", image_note),
        ("source_author", source_author),
        ("source_post_url", source_post_url),
        ("post_text", post_text),
        ("note", note),
    ):
        if value:
            row[key] = value
    resp = db.table("post_templates").insert(row).execute()
    return resp.data[0] if resp.data else None


def update_post_template(access_token: str, template_id: str, fields: dict) -> dict | None:
    """Met à jour une entrée de la bibliothèque (RLS scope)."""
    if not supabase_enabled() or not template_id or not fields:
        return None
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("post_templates")
        .update(fields)
        .eq("id", template_id)
        .eq("user_id", user["id"])
        .execute()
    )
    return resp.data[0] if resp.data else None


def delete_post_template(access_token: str, template_id: str) -> bool:
    """Delete one of the user's templates. RLS guarantees ownership."""
    if not supabase_enabled():
        return False
    user = get_user(access_token)
    if not user:
        return False
    db = client_for_token(access_token)
    (
        db.table("post_templates")
        .delete()
        .eq("id", template_id)
        .eq("user_id", user["id"])
        .execute()
    )
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
    cross_posts: dict[str, Any] | None = None,
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
            "cross_posts": cross_posts or {},
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
        .select("id, post_text, scheduled_at, status, slack_status, slack_message_ts, zernio_post_id, error_message, media_items, cross_posts, created_at")
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
    media_items: list[dict] | None = None,
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
    if media_items is not None:
        payload["media_items"] = media_items
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
        payload["error_message"] = "Publication annulée après refus."
    resp = (
        admin_client()
        .table("scheduled_posts")
        .update(payload)
        .eq("id", post_id)
        .eq("user_id", user_id)
        .execute()
    )
    return bool(resp.data)


def validate_scheduled_post_user(access_token: str, post_id: str) -> dict | None:
    """Mark a pending scheduled post as validated (in-app validation, JWT)."""
    if not supabase_enabled():
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("scheduled_posts")
        .update({"slack_status": "validated", "updated_at": "now()"})
        .eq("id", post_id)
        .eq("status", "pending")
        .eq("slack_status", "pending")
        .execute()
    )
    return resp.data[0] if resp.data else None


def reject_scheduled_post_user(access_token: str, post_id: str) -> dict | None:
    """Decline a pending scheduled post (in-app validation, JWT)."""
    if not supabase_enabled():
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("scheduled_posts")
        .update({
            "slack_status": "declined",
            "status": "cancelled",
            "error_message": "Publication annulée après refus.",
            "updated_at": "now()",
        })
        .eq("id", post_id)
        .eq("status", "pending")
        .execute()
    )
    return resp.data[0] if resp.data else None


def submit_generated_post_for_validation(access_token: str, post_id: str) -> dict | None:
    """Queue a generated post for in-app validation (replaces Slack send)."""
    if not supabase_enabled():
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("generated_posts")
        .update({"slack_status": "pending"})
        .eq("id", post_id)
        .is_("zernio_post_id", "null")
        .execute()
    )
    return resp.data[0] if resp.data else None


def validate_generated_post_user(access_token: str, post_id: str) -> dict | None:
    """Mark a generated post validated (publication handled by the API layer)."""
    if not supabase_enabled():
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("generated_posts")
        .update({"slack_status": "validated"})
        .eq("id", post_id)
        .eq("slack_status", "pending")
        .is_("zernio_post_id", "null")
        .execute()
    )
    return resp.data[0] if resp.data else None


def reject_generated_post_user(access_token: str, post_id: str) -> dict | None:
    """Decline a generated post awaiting validation."""
    if not supabase_enabled():
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("generated_posts")
        .update({"slack_status": "declined"})
        .eq("id", post_id)
        .eq("slack_status", "pending")
        .execute()
    )
    return resp.data[0] if resp.data else None


def mark_generated_post_published_user(
    access_token: str, post_id: str, zernio_post_id: str | None
) -> dict | None:
    """Record LinkedIn publication of a validated generated post (JWT)."""
    if not supabase_enabled():
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("generated_posts")
        .update({"slack_status": "published", "zernio_post_id": zernio_post_id})
        .eq("id", post_id)
        .execute()
    )
    return resp.data[0] if resp.data else None


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
        .select("id, user_id, post_text, media_items, cross_posts")
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
        .select("user_id, zernio_account_id, zernio_x_account_id, zernio_reddit_account_id")
        .in_("user_id", user_ids)
        .execute()
    )
    accounts_by_user = {r["user_id"]: r for r in (prof.data or [])}
    return [
        {
            "id": p["id"],
            "user_id": p["user_id"],
            "post_text": p["post_text"],
            "media_items": p.get("media_items") or [],
            "cross_posts": p.get("cross_posts") or {},
            "zernio_account_id": (accounts_by_user.get(p["user_id"]) or {}).get("zernio_account_id"),
            "zernio_x_account_id": (accounts_by_user.get(p["user_id"]) or {}).get("zernio_x_account_id"),
            "zernio_reddit_account_id": (accounts_by_user.get(p["user_id"]) or {}).get("zernio_reddit_account_id"),
        }
        for p in posts
    ]


def update_scheduled_post_status(
    post_id: str,
    status: str,
    *,
    zernio_post_id: str | None = None,
    error: str | None = None,
    cross_posts: dict[str, Any] | None = None,
) -> None:
    """Update publication status for a scheduled post (service-role, for cron).

    `cross_posts` (ALE-59) : versions X/Reddit enrichies du résultat de leur
    publication (status/erreur par réseau), réécrites en bloc."""
    if not admin_enabled():
        return
    admin = admin_client()
    payload: dict[str, Any] = {"status": status, "updated_at": "now()"}
    if zernio_post_id is not None:
        payload["zernio_post_id"] = zernio_post_id
    if error is not None:
        payload["error_message"] = error[:500]
    if cross_posts is not None:
        payload["cross_posts"] = cross_posts
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


def upsert_cached_posts(
    cache_id: str,
    posts_with_classifs: list[dict],
    detected_by_monitor: bool = False,
) -> None:
    """Insère les nouveaux posts dans le cache global (les existants sont préservés).

    `posts_with_classifs` : liste de {"post": post_dict, "classification": classif | None}.
    Les métriques (likes/comments/reposts) des posts déjà présents en cache ne sont
    PAS mises à jour — conformément à la décision ALE-109 ("métriques figées").
    Exception ALE-214 : le cron de monitoring re-relève l'engagement des posts
    récents via `refresh_cached_post_metrics` (engagement non stabilisé).
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
            media_items = post.get("media_items")
            if media_items:
                row["media_items"] = _json_safe(media_items)
            if detected_by_monitor:
                row["detected_by_monitor"] = True
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


# ── Monitoring influenceurs (ALE-214) ─────────────────────────────────────── #

def list_followed_influencers(access_token: str) -> list[dict]:
    """Influenceurs suivis par l'utilisateur (RLS)."""
    if not supabase_enabled():
        return []
    user = get_user(access_token)
    if not user:
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("followed_influencers")
        .select("*")
        .eq("user_id", user["id"])
        .order("created_at", desc=False)
        .execute()
    )
    return resp.data or []


def follow_influencer(access_token: str, handle: str, platform: str = "linkedin") -> dict | None:
    """Suit un influenceur (idempotent : renvoie la ligne existante si déjà suivi)."""
    if not supabase_enabled():
        return None
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("followed_influencers")
        .upsert(
            {"user_id": user["id"], "handle": handle, "platform": platform},
            on_conflict="user_id,handle,platform",
        )
        .execute()
    )
    return resp.data[0] if resp.data else None


def unfollow_influencer(access_token: str, follow_id: str) -> bool:
    """Ne plus suivre un influenceur. RLS garantit la propriété."""
    if not supabase_enabled():
        return False
    user = get_user(access_token)
    if not user:
        return False
    db = client_for_token(access_token)
    (
        db.table("followed_influencers")
        .delete()
        .eq("id", follow_id)
        .eq("user_id", user["id"])
        .execute()
    )
    return True


def list_all_followed_handles(platform: str = "linkedin") -> list[str]:
    """[cron] Handles suivis, dédupliqués tous utilisateurs confondus.

    Le cache est partagé : un influenceur suivi par 3 clients = un seul scrape.
    """
    if not admin_enabled():
        return []
    resp = (
        admin_client()
        .table("followed_influencers")
        .select("handle")
        .eq("platform", platform)
        .execute()
    )
    return sorted({r["handle"] for r in (resp.data or []) if r.get("handle")})


def list_followed_handles_for_user(user_id: str, platform: str = "linkedin") -> list[str]:
    """[cron/run-now] Handles suivis par un utilisateur donné (service-role)."""
    if not admin_enabled():
        return []
    resp = (
        admin_client()
        .table("followed_influencers")
        .select("handle")
        .eq("user_id", user_id)
        .eq("platform", platform)
        .execute()
    )
    return sorted({r["handle"] for r in (resp.data or []) if r.get("handle")})


def get_monitoring_feed_for_user(user_id: str, days: int = 30, limit: int = 60) -> list[dict]:
    """[veille ALE-215] Posts récents des influenceurs suivis par l'utilisateur.

    Lit le cache partagé via le service-role (ses tables ont une RLS sans policy,
    donc inaccessibles au front), mais ne renvoie que les posts des influenceurs
    que CET utilisateur suit. Fenêtre : posts publiés OU découverts < `days` jours.
    """
    if not admin_enabled():
        return []
    handles = list_followed_handles_for_user(user_id)
    if not handles:
        return []
    admin = admin_client()
    caches = (
        admin.table("influencer_cache")
        .select("id,handle,name")
        .in_("handle", handles)
        .eq("platform", "linkedin")
        .execute()
    ).data or []
    if not caches:
        return []
    by_id = {c["id"]: c for c in caches}
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    ).isoformat()
    posts = (
        admin.table("cached_posts")
        .select(
            "id,influencer_cache_id,url,text,posted_at,format,likes,comments,"
            "reposts,engagement,media_items,detected_by_monitor,first_seen_at"
        )
        .in_("influencer_cache_id", list(by_id.keys()))
        .or_(f"posted_at.gte.{cutoff},first_seen_at.gte.{cutoff}")
        .order("posted_at", desc=True, nullsfirst=False)
        .limit(limit)
        .execute()
    ).data or []
    for p in posts:
        cache = by_id.get(p.get("influencer_cache_id")) or {}
        p["influencer_name"] = cache.get("name") or cache.get("handle")
        p["influencer_handle"] = cache.get("handle")
    return posts


def refresh_cached_post_metrics(cache_id: str, post: dict) -> None:
    """[cron monitoring] Re-relève l'engagement d'un post déjà en cache.

    Exception assumée à la règle « métriques figées » d'ALE-109 : l'engagement
    d'un post frais n'est pas stabilisé, le cron le re-mesure à chaque passage
    tant que le post est récent (fenêtre gérée par l'appelant).
    """
    if not admin_enabled():
        return
    url = post.get("url")
    if not url:
        return
    try:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        updates: dict[str, Any] = {
            "likes": int(post.get("likes", 0) or 0),
            "comments": int(post.get("comments", 0) or 0),
            "reposts": int(post.get("reposts", 0) or 0),
            "engagement": int(post.get("engagement", 0) or 0),
            "engagement_checked_at": now,
        }
        media_items = post.get("media_items")
        if media_items:
            updates["media_items"] = _json_safe(media_items)
        (
            admin_client()
            .table("cached_posts")
            .update(updates)
            .eq("influencer_cache_id", cache_id)
            .eq("url", url)
            .execute()
        )
    except Exception:
        pass  # best-effort : ne bloque jamais le cron


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
    slack_status: str = "pending",
) -> dict | None:
    """Insert a scheduled post with service-role (no user JWT). Used by crons.

    `slack_status` defaults to "pending" (awaiting Slack validation). Pass
    "validated" for users without Slack connected: the publish scheduler only
    picks up validated posts, and the Slack webhook is the only other path to
    "validated" — a pending post without Slack would be stuck forever (ALE-272).
    """
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
            "slack_status": slack_status,
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


def update_ig_message_text_admin(message_id: str, text: str) -> dict | None:
    """Mettre à jour le texte d'un message IG (service-role) — note vocale transcrite.

    Un vocal entrant est d'abord persisté avec un texte d'attente (« transcription
    en cours ») pour être **immédiatement visible** dans l'inbox, puis ce texte est
    remplacé par la transcription (ou un message d'échec) quand Whisper a fini.
    """
    if not admin_enabled():
        return None
    resp = (
        admin_client()
        .table("ig_messages")
        .update({"text": text or ""})
        .eq("id", message_id)
        .execute()
    )
    return resp.data[0] if resp.data else None


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


# --- Garde-fou + autopilot (ALE-205) ---------------------------------------

def get_ig_conversation_admin(user_id: str, conversation_id: str) -> dict | None:
    """Lire une conversation (service-role, scellé user_id) — pour le routage agent."""
    if not admin_enabled():
        return None
    resp = (
        admin_client()
        .table("ig_conversations")
        .select("*")
        .eq("user_id", user_id)
        .eq("id", conversation_id)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_ig_kill_switch_admin(user_id: str) -> bool:
    """Kill-switch global de l'utilisateur (service-role). Défaut True (fail-safe)
    si le profil est introuvable : on préfère NE PAS auto-envoyer par défaut."""
    if not admin_enabled():
        return True
    resp = (
        admin_client()
        .table("user_editorial_profiles")
        .select("ig_autopilot_kill_switch")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not resp.data:
        return True
    return bool(resp.data[0].get("ig_autopilot_kill_switch", False))


def get_ig_kill_switch(access_token: str) -> bool:
    """Kill-switch global de l'utilisateur (RLS) — pour l'UI."""
    if not supabase_enabled():
        return True
    db = client_for_token(access_token)
    resp = (
        db.table("user_editorial_profiles")
        .select("ig_autopilot_kill_switch")
        .limit(1)
        .execute()
    )
    if not resp.data:
        return False
    return bool(resp.data[0].get("ig_autopilot_kill_switch", False))


def set_ig_kill_switch(access_token: str, active: bool) -> bool:
    """Basculer le kill-switch global (RLS)."""
    user = get_user(access_token)
    if not user or not supabase_enabled():
        return False
    db = client_for_token(access_token)
    resp = (
        db.table("user_editorial_profiles")
        .update({"ig_autopilot_kill_switch": bool(active), "updated_at": "now()"})
        .eq("user_id", user["id"])
        .execute()
    )
    return bool(resp.data)


def update_ig_draft_status_admin(draft_id: str, status: str, reply: str | None = None) -> dict | None:
    """Mettre à jour le statut d'un draft (service-role) — pour l'envoi autopilot."""
    if not admin_enabled():
        return None
    payload: dict[str, Any] = {"status": status, "updated_at": "now()"}
    if reply is not None:
        payload["reply"] = reply
    resp = admin_client().table("ig_drafts").update(payload).eq("id", draft_id).execute()
    return resp.data[0] if resp.data else None


def log_ig_decision_admin(
    user_id: str,
    conversation_id: str,
    message_id: str | None,
    draft_id: str | None,
    *,
    decision: str,
    confidence,
    needs_human,
    reason,
) -> None:
    """Journaliser une décision du garde-fou (service-role) pour tuner le seuil (ALE-205)."""
    if not admin_enabled():
        return
    admin_client().table("ig_decisions").insert({
        "user_id": user_id,
        "conversation_id": conversation_id,
        "message_id": message_id,
        "draft_id": draft_id,
        "decision": decision,
        "confidence": confidence,
        "needs_human": needs_human,
        "reason": reason,
    }).execute()


def get_ig_faq(access_token: str) -> dict | None:
    """FAQ + objectif de l'utilisateur (RLS) — pour l'éditeur in-app.

    Fail-safe si la table n'existe pas encore (migration 0034 non appliquée).
    """
    if not supabase_enabled():
        return None
    db = client_for_token(access_token)
    try:
        resp = db.table("ig_faqs").select("*").limit(1).execute()
    except Exception:
        return None
    return resp.data[0] if resp.data else None


def set_ig_faq(access_token: str, content: str) -> dict | None:
    """Créer/mettre à jour la FAQ de l'utilisateur (RLS, une ligne par user)."""
    user = get_user(access_token)
    if not user or not supabase_enabled():
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("ig_faqs")
        .upsert(
            {"user_id": user["id"], "content": content or "", "updated_at": "now()"},
            on_conflict="user_id",
        )
        .execute()
    )
    return resp.data[0] if resp.data else None


# ---------------------------------------------------------------------------
# Apprentissage des réponses IA — suggestion vs texte envoyé + règles apprises
# par canal (Instagram, LinkedIn), distillées par cron (ALE-253).
# ---------------------------------------------------------------------------


def log_ai_reply_feedback(
    access_token: str,
    *,
    channel: str,
    conversation_ref: str | None,
    suggested_text: str,
    sent_text: str,
    learn_opt_out: bool = False,
) -> None:
    """Enregistrer une suggestion IA vs le texte réellement envoyé (RLS).

    Best-effort : ne doit jamais faire échouer l'envoi du message lui-même si
    la table est absente (migration pas encore appliquée) ou l'insert échoue.
    """
    if not supabase_enabled():
        return
    user = get_user(access_token)
    if not user:
        return
    suggested = (suggested_text or "").strip()
    sent = (sent_text or "").strip()
    if not suggested or not sent:
        return
    try:
        client_for_token(access_token).table("ai_reply_feedback").insert({
            "user_id": user["id"],
            "channel": channel,
            "conversation_ref": conversation_ref,
            "suggested_text": suggested,
            "sent_text": sent,
            "edited": suggested != sent,
            "learn_opt_out": bool(learn_opt_out),
        }).execute()
    except Exception:
        pass


def get_ai_learned_rules(access_token: str, channel: str) -> dict | None:
    """Règles apprises de l'utilisateur pour un canal (RLS) — pour l'éditeur in-app."""
    if not supabase_enabled():
        return None
    db = client_for_token(access_token)
    try:
        resp = (
            db.table("ai_learned_rules")
            .select("*")
            .eq("channel", channel)
            .limit(1)
            .execute()
        )
    except Exception:
        return None
    return resp.data[0] if resp.data else None


def set_ai_learned_rules(access_token: str, channel: str, content: str) -> dict | None:
    """Créer/éditer à la main les règles apprises d'un canal (RLS, une ligne par user+canal)."""
    user = get_user(access_token)
    if not user or not supabase_enabled():
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("ai_learned_rules")
        .upsert(
            {"user_id": user["id"], "channel": channel, "content": content or "", "updated_at": "now()"},
            on_conflict="user_id,channel",
        )
        .execute()
    )
    return resp.data[0] if resp.data else None


def admin_list_users_with_pending_feedback(channel: str) -> list[str]:
    """User ids ayant au moins une édition non apprise sur ce canal (service-role, pour le cron)."""
    if not admin_enabled():
        return []
    try:
        resp = (
            admin_client()
            .table("ai_reply_feedback")
            .select("user_id")
            .eq("channel", channel)
            .eq("learn_opt_out", False)
            .eq("edited", True)
            .is_("learned_at", "null")
            .execute()
        )
    except Exception:
        return []
    return sorted({r["user_id"] for r in (resp.data or []) if r.get("user_id")})


def admin_list_pending_feedback(user_id: str, channel: str, limit: int = 200) -> list[dict]:
    """Éditions non apprises d'un utilisateur pour un canal (service-role, pour le cron)."""
    if not admin_enabled():
        return []
    resp = (
        admin_client()
        .table("ai_reply_feedback")
        .select("id,suggested_text,sent_text,created_at")
        .eq("user_id", user_id)
        .eq("channel", channel)
        .eq("learn_opt_out", False)
        .eq("edited", True)
        .is_("learned_at", "null")
        .order("created_at")
        .limit(max(1, min(limit, 500)))
        .execute()
    )
    return resp.data or []


def admin_mark_feedback_learned(ids: list[str]) -> None:
    """Marquer des lignes de feedback comme apprises (service-role, idempotent)."""
    if not admin_enabled() or not ids:
        return
    admin_client().table("ai_reply_feedback").update({"learned_at": "now()"}).in_("id", ids).execute()


def admin_get_learned_rules(user_id: str, channel: str) -> str:
    """Contenu des règles apprises d'un utilisateur pour un canal (service-role) — pour le cerveau agent."""
    if not admin_enabled():
        return ""
    try:
        resp = (
            admin_client()
            .table("ai_learned_rules")
            .select("content")
            .eq("user_id", user_id)
            .eq("channel", channel)
            .limit(1)
            .execute()
        )
    except Exception:
        return ""
    if not resp.data:
        return ""
    return (resp.data[0].get("content") or "").strip()


def admin_set_learned_rules(user_id: str, channel: str, content: str) -> None:
    """Écrire les règles apprises distillées par le cron (service-role, upsert user+canal)."""
    if not admin_enabled():
        return
    admin_client().table("ai_learned_rules").upsert(
        {"user_id": user_id, "channel": channel, "content": content or "", "updated_at": "now()", "last_distilled_at": "now()"},
        on_conflict="user_id,channel",
    ).execute()


def get_ig_faq_admin(user_id: str) -> str:
    """Contenu FAQ de l'utilisateur (service-role) — pour le cerveau agent.

    Chaîne vide si absent : l'appelant retombe sur le fichier de config serveur.
    """
    if not admin_enabled():
        return ""
    try:
        resp = (
            admin_client()
            .table("ig_faqs")
            .select("content")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    except Exception:
        # Table absente (migration 0034 non appliquée) → repli fichier.
        return ""
    if not resp.data:
        return ""
    return (resp.data[0].get("content") or "").strip()


# ---------------------------------------------------------------------------
# Connexion ManyChat par utilisateur (multi-client) — table `user_integrations`
# service='manychat'. access_token = clé API du client ; webhook_token = slug
# public de routage ; webhook_secret = en-tête d'authentification.
# ---------------------------------------------------------------------------


def get_ig_manychat(access_token: str) -> dict | None:
    """Intégration ManyChat de l'utilisateur (RLS) — pour l'écran de connexion."""
    user = get_user(access_token)
    if not user or not supabase_enabled():
        return None
    db = client_for_token(access_token)
    try:
        resp = (
            db.table("user_integrations")
            .select("*")
            .eq("user_id", user["id"])
            .eq("service", "manychat")
            .limit(1)
            .execute()
        )
    except Exception:
        return None
    return resp.data[0] if resp.data else None


def save_ig_manychat(
    access_token: str,
    *,
    api_token: str,
    webhook_token: str,
    webhook_secret: str,
) -> dict | None:
    """Relier/mettre à jour le compte ManyChat de l'utilisateur (RLS, upsert)."""
    user = get_user(access_token)
    if not user or not supabase_enabled():
        return None
    db = client_for_token(access_token)
    row = {
        "user_id": user["id"],
        "service": "manychat",
        "access_token": api_token,
        "webhook_token": webhook_token,
        "webhook_secret": webhook_secret,
        "connected_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    resp = (
        db.table("user_integrations")
        .upsert(row, on_conflict="user_id,service")
        .execute()
    )
    return resp.data[0] if resp.data else None


def delete_ig_manychat(access_token: str) -> bool:
    """Délier le compte ManyChat de l'utilisateur (RLS)."""
    user = get_user(access_token)
    if not user or not supabase_enabled():
        return False
    db = client_for_token(access_token)
    resp = (
        db.table("user_integrations")
        .delete()
        .eq("user_id", user["id"])
        .eq("service", "manychat")
        .execute()
    )
    return bool(resp.data)


def get_ig_manychat_by_webhook_token_admin(webhook_token: str) -> dict | None:
    """Résoudre l'utilisateur propriétaire d'un webhook ManyChat (service-role).

    Sert au routage du DM entrant : le slug de l'URL identifie le compte, on
    renvoie user_id + secret (à vérifier) + clé API. Aucune session utilisateur
    sur le webhook → service-role obligatoire.
    """
    if not admin_enabled() or not webhook_token:
        return None
    try:
        resp = (
            admin_client()
            .table("user_integrations")
            .select("user_id, access_token, webhook_secret")
            .eq("service", "manychat")
            .eq("webhook_token", webhook_token)
            .limit(1)
            .execute()
        )
    except Exception:
        return None
    return resp.data[0] if resp.data else None


def get_ig_manychat_token_admin(user_id: str) -> str | None:
    """Clé API ManyChat d'un utilisateur (service-role) — pour l'envoi autopilot."""
    if not admin_enabled():
        return None
    try:
        resp = (
            admin_client()
            .table("user_integrations")
            .select("access_token")
            .eq("service", "manychat")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    except Exception:
        return None
    if not resp.data:
        return None
    return resp.data[0].get("access_token") or None


# --------------------------------------------------------------------------- #
# Prospection LinkedIn (ALE-227) — sources lead-magnet + leads commentateurs
# --------------------------------------------------------------------------- #

def list_lead_sources(access_token: str) -> list[dict]:
    """Posts sources de prospection de l'utilisateur (RLS scope)."""
    if not supabase_enabled():
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("lead_sources")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data or []


def get_lead_source(access_token: str, source_id: str) -> dict | None:
    if not supabase_enabled() or not source_id:
        return None
    db = client_for_token(access_token)
    resp = db.table("lead_sources").select("*").eq("id", source_id).limit(1).execute()
    return resp.data[0] if resp.data else None


def get_lead_source_by_url(access_token: str, post_url: str) -> dict | None:
    if not supabase_enabled() or not post_url:
        return None
    db = client_for_token(access_token)
    resp = db.table("lead_sources").select("*").eq("post_url", post_url).limit(1).execute()
    return resp.data[0] if resp.data else None


def add_lead_source(
    access_token: str,
    post_url: str,
    *,
    author: str | None = None,
    post_text: str | None = None,
    is_lead_magnet: bool = False,
    trigger_keyword: str | None = None,
    origin: str = "manual",
) -> dict | None:
    """Crée une source de prospection (RLS scope)."""
    if not supabase_enabled():
        return None
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    row: dict[str, Any] = {
        "user_id": user["id"],
        "post_url": post_url,
        "is_lead_magnet": is_lead_magnet,
        "origin": origin,
    }
    if author:
        row["author"] = author
    if post_text:
        row["post_text"] = post_text[:6000]
    if trigger_keyword:
        row["trigger_keyword"] = trigger_keyword
    resp = db.table("lead_sources").insert(row).execute()
    return resp.data[0] if resp.data else None


def update_lead_source(access_token: str, source_id: str, fields: dict) -> dict | None:
    """Met à jour une source (collecte : collected_at + comments_count)."""
    if not supabase_enabled() or not source_id or not fields:
        return None
    db = client_for_token(access_token)
    resp = db.table("lead_sources").update(fields).eq("id", source_id).execute()
    return resp.data[0] if resp.data else None


def delete_lead_source(access_token: str, source_id: str) -> bool:
    if not supabase_enabled() or not source_id:
        return False
    db = client_for_token(access_token)
    db.table("lead_sources").delete().eq("id", source_id).execute()
    return True


def add_lead_source_admin(
    user_id: str,
    post_url: str,
    *,
    author: str | None = None,
    post_text: str | None = None,
    trigger_keyword: str | None = None,
) -> dict | None:
    """[veille] Source détectée automatiquement pour un utilisateur (service-role).

    Idempotent : si l'utilisateur a déjà une source sur ce post (manuelle ou
    monitoring), on ne crée rien — la collecte reste à sa main. Scope strict :
    la ligne écrite appartient au user_id passé (suiveur vérifié en amont).
    """
    if not admin_enabled() or not user_id or not post_url:
        return None
    db = admin_client()
    existing = (
        db.table("lead_sources")
        .select("id")
        .eq("user_id", user_id)
        .eq("post_url", post_url)
        .limit(1)
        .execute()
    )
    if existing.data:
        return None
    row: dict[str, Any] = {
        "user_id": user_id,
        "post_url": post_url,
        "is_lead_magnet": True,
        "origin": "monitoring",
    }
    if author:
        row["author"] = author
    if post_text:
        row["post_text"] = post_text[:6000]
    if trigger_keyword:
        row["trigger_keyword"] = trigger_keyword
    resp = db.table("lead_sources").insert(row).execute()
    return resp.data[0] if resp.data else None


def list_user_ids_following_handle(handle: str, platform: str = "linkedin") -> list[str]:
    """[veille] Utilisateurs qui suivent un handle donné (service-role)."""
    if not admin_enabled() or not handle:
        return []
    resp = (
        admin_client()
        .table("followed_influencers")
        .select("user_id")
        .eq("handle", handle)
        .eq("platform", platform)
        .execute()
    )
    return sorted({r["user_id"] for r in (resp.data or []) if r.get("user_id")})


def save_leads(access_token: str, source: dict, commenters: list[dict]) -> dict:
    """Persiste les commentateurs d'une source en leads dédupliqués (RLS scope).

    Dédup par (personne, source) : une personne = UNE ligne par utilisateur
    (unique user_id + profile_url) ; commenter chez plusieurs concurrents
    ajoute un signal (`signals`) au lieu de dupliquer — `signal_count` > 1
    = « multi-signaux ». Recollecter la même source ne recrée rien.
    """
    if not supabase_enabled():
        return {"inserted": 0, "updated": 0, "skipped": 0}
    user = get_user(access_token)
    if not user:
        return {"inserted": 0, "updated": 0, "skipped": 0}
    db = client_for_token(access_token)

    def _iso_or_none(value: Any) -> str | None:
        # La colonne `commented_at` est un timestamptz : on ne passe que des
        # dates ISO valides (l'actor peut renvoyer un format inattendu).
        if not value:
            return None
        try:
            datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return str(value)

    valid = [c for c in commenters if c.get("profile_url")]
    for c in valid:
        c["commented_at"] = _iso_or_none(c.get("commented_at"))
    urls = [c["profile_url"] for c in valid]
    existing_by_url: dict[str, dict] = {}
    for i in range(0, len(urls), 100):  # borne la taille de la clause in()
        resp = (
            db.table("leads")
            .select("id, profile_url, signals, signal_count, status")
            .in_("profile_url", urls[i : i + 100])
            .execute()
        )
        for row in resp.data or []:
            existing_by_url[row["profile_url"]] = row

    def _signal(c: dict) -> dict:
        return {
            "source_id": source.get("id"),
            "post_url": source.get("post_url"),
            "author": source.get("author"),
            "trigger_keyword": source.get("trigger_keyword"),
            "comment_text": c.get("comment_text"),
            "commented_at": c.get("commented_at"),
        }

    inserted, updated, skipped = 0, 0, 0
    to_insert: list[dict] = []
    # profile_url → lead id des leads touchés (insérés ou mis à jour) : sert au
    # scoring ICP à l'ingestion (ALE-228). Les « skipped » (déjà vus sur cette
    # source, inchangés) n'ont pas besoin d'être re-notés.
    ids_by_url: dict[str, str] = {}
    for c in valid:
        row = existing_by_url.get(c["profile_url"])
        if row is None:
            to_insert.append(
                {
                    "user_id": user["id"],
                    "profile_url": c["profile_url"],
                    "name": c.get("name"),
                    "headline": c.get("headline"),
                    "source_id": source.get("id"),
                    "comment_text": c.get("comment_text"),
                    "commented_at": c.get("commented_at"),
                    "reaction_count": int(c.get("reaction_count") or 0),
                    "signals": [_signal(c)],
                    "signal_count": 1,
                }
            )
            continue
        signals = list(row.get("signals") or [])
        if any(s.get("source_id") == source.get("id") for s in signals):
            skipped += 1  # déjà vu sur cette source (dédup personne + source)
            continue
        signals.append(_signal(c))
        db.table("leads").update(
            {
                "signals": signals,
                "signal_count": len(signals),
                "source_id": source.get("id"),
                "comment_text": c.get("comment_text"),
                "commented_at": c.get("commented_at"),
                "reaction_count": int(c.get("reaction_count") or 0),
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        ).eq("id", row["id"]).execute()
        ids_by_url[c["profile_url"]] = row["id"]
        updated += 1

    for i in range(0, len(to_insert), 100):
        resp = db.table("leads").insert(to_insert[i : i + 100]).execute()
        for r in resp.data or []:
            if r.get("profile_url") and r.get("id"):
                ids_by_url[r["profile_url"]] = r["id"]
        inserted += len(resp.data or [])

    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "ids_by_url": ids_by_url,
    }


def list_leads(access_token: str, limit: int = 500) -> list[dict]:
    """Leads de l'utilisateur pour la liste Prospection (RLS scope).

    On garde TOUTE la liste (aucun masquage) : les leads sont classés par score
    ICP décroissant — les moins pertinents descendent mais restent visibles ; les
    non-notés (score null) passent après. À l'intérieur d'un même groupe :
    multi-signaux puis plus récents (ordre du fetch, tri stable). La curation
    manuelle « ne pas contacter » est un sujet à part (ALE-243).
    """
    if not supabase_enabled():
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("leads")
        .select("*")
        .order("signal_count", desc=True)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = resp.data or []
    # Tri stable : les écartés « ne pas contacter » (ALE-243) en tout dernier
    # (jamais masqués), puis scorés (par score décroissant) avant non-scorés.
    rows.sort(key=lambda r: (
        1 if r.get("contact_status") == "skip" else 0,
        0 if r.get("score") is not None else 1,
        -(int(r.get("score") or 0)),
    ))
    return rows


def list_leads_for_scoring(access_token: str, limit: int = 1000) -> list[dict]:
    """Tous les leads du user (non filtrés par seuil) pour un recalcul de score."""
    if not supabase_enabled():
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("leads")
        .select("id, name, headline, comment_text, signals")
        .limit(limit)
        .execute()
    )
    return resp.data or []


def update_lead_scores(access_token: str, scored: list[dict]) -> int:
    """Écrit score + justification sur des leads (RLS scope). `scored` = liste de
    {id, score, reason}. Retourne le nombre de leads mis à jour."""
    if not supabase_enabled() or not scored:
        return 0
    db = client_for_token(access_token)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    n = 0
    for item in scored:
        lead_id = item.get("id")
        if not lead_id:
            continue
        db.table("leads").update(
            {
                "score": int(item.get("score") or 0),
                "score_reason": (item.get("reason") or None),
                "scored_at": now,
            }
        ).eq("id", lead_id).execute()
        n += 1
    return n


# ── Ciblage ICP (ALE-228) : config de prospection par utilisateur ──────────────
_LEAD_TARGETING_FIELDS = (
    "ideal_client",
    "offer",
    "interest_keywords",
    "score_threshold",
    "first_message_instructions",
)


def get_lead_targeting(access_token: str) -> dict | None:
    """Config de ciblage de l'utilisateur, ou None si jamais enregistrée."""
    if not supabase_enabled():
        return None
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("lead_targeting")
        .select("*")
        .eq("user_id", user["id"])
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def upsert_lead_targeting(access_token: str, payload: dict[str, Any]) -> dict | None:
    """Crée ou met à jour la config de ciblage (RLS scope)."""
    if not supabase_enabled():
        return None
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    row: dict[str, Any] = {
        "user_id": user["id"],
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    for key in _LEAD_TARGETING_FIELDS:
        if key not in payload:
            continue
        value = payload[key]
        if key == "score_threshold":
            try:
                row[key] = max(0, min(100, int(value)))
            except (TypeError, ValueError):
                row[key] = 60
        elif key == "interest_keywords":
            if isinstance(value, str):
                value = [v.strip() for v in value.split(",")]
            row[key] = [str(v).strip() for v in (value or []) if str(v).strip()]
        elif isinstance(value, str):
            row[key] = value.strip() or None
        else:
            row[key] = value
    resp = (
        db.table("lead_targeting")
        .upsert(row, on_conflict="user_id")
        .execute()
    )
    return resp.data[0] if resp.data else None


# --------------------------------------------------------------------------- #
# Prospection LinkedIn (ALE-230) — envoi via Unipile + quotas
# `linkedin_outreach_accounts` : compte Unipile connecté + config quota (1/user).
# `linkedin_outreach_actions`  : journal des envois → base des compteurs de quota
#                                (calculés sur fenêtres glissantes, sans reset cron).
# --------------------------------------------------------------------------- #


def get_linkedin_outreach_account(access_token: str) -> dict | None:
    """Compte Unipile connecté de l'utilisateur (config quota incluse), ou None."""
    if not supabase_enabled():
        return None
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("linkedin_outreach_accounts")
        .select("*")
        .eq("user_id", user["id"])
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def upsert_linkedin_outreach_account(
    access_token: str,
    *,
    unipile_account_id: str | None = None,
    account_name: str | None = None,
    daily_cap: int | None = None,
    weekly_invite_cap: int | None = None,
    status: str | None = None,
    timezone_name: str | None = None,
    send_hour_start: int | None = None,
    send_hour_end: int | None = None,
    send_days: list[int] | None = None,
    auto_prospection_enabled: bool | None = None,
    auto_invite_min_score: int | None = None,
    auto_invite_daily_cap: int | None = None,
    auto_message_mode: str | None = None,
    auto_message_template: str | None = None,
    auto_message_requires_validation: bool | None = None,
) -> dict | None:
    """Crée/met à jour le compte Unipile + la config de cadençage (RLS scope, upsert).

    Seules les colonnes fournies sont écrites : maj partielle sûre (changer le
    plafond ne réinitialise pas l'account_id, et inversement).

    ⚠️ Aucun paramètre ne permet de lever le gel (`frozen`) : c'est un garde-fou
    anti-restriction, il n'est pas contournable depuis l'interface. Il se lève seul
    (voir `outreach_engine.freeze_active`)."""
    if not supabase_enabled():
        return None
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    row: dict[str, Any] = {
        "user_id": user["id"],
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if unipile_account_id is not None:
        row["unipile_account_id"] = unipile_account_id
    if account_name is not None:
        row["account_name"] = account_name
    if status is not None:
        row["status"] = status
    if daily_cap is not None:
        row["daily_cap"] = max(1, min(100, int(daily_cap)))
    if weekly_invite_cap is not None:
        row["weekly_invite_cap"] = max(1, min(500, int(weekly_invite_cap)))
    if timezone_name is not None:
        row["timezone"] = timezone_name
    if send_hour_start is not None:
        row["send_hour_start"] = max(0, min(23, int(send_hour_start)))
    if send_hour_end is not None:
        row["send_hour_end"] = max(1, min(24, int(send_hour_end)))
    if send_days is not None:
        days = sorted({int(d) for d in send_days if 1 <= int(d) <= 7})
        row["send_days"] = days or [1, 2, 3, 4, 5]
    # ALE-284 — réglages de l'autopilote (opt-in, palier de score, message, relecture).
    # ⚠️ Chacune de ces colonnes doit figurer dans le `grant update (…)` de la migration
    # 0052 : la 0048 a révoqué l'UPDATE global, et une colonne oubliée fait échouer tout
    # l'upsert — pas seulement son écriture (Postgres exige UPDATE sur CHAQUE colonne
    # du payload).
    if auto_prospection_enabled is not None:
        row["auto_prospection_enabled"] = bool(auto_prospection_enabled)
    if auto_invite_min_score is not None:
        row["auto_invite_min_score"] = max(0, min(100, int(auto_invite_min_score)))
    if auto_invite_daily_cap is not None:
        row["auto_invite_daily_cap"] = max(1, min(50, int(auto_invite_daily_cap)))
    if auto_message_mode is not None:
        # La base a un CHECK sur ces trois valeurs : on ne lui envoie jamais autre chose,
        # sinon c'est tout l'upsert (donc le réglage entier) qui partirait en erreur.
        mode = str(auto_message_mode).strip().lower()
        row["auto_message_mode"] = mode if mode in ("none", "ai", "template") else "none"
    if auto_message_template is not None:
        row["auto_message_template"] = str(auto_message_template).strip()[:2000] or None
    if auto_message_requires_validation is not None:
        row["auto_message_requires_validation"] = bool(auto_message_requires_validation)
    resp = (
        db.table("linkedin_outreach_accounts")
        .upsert(row, on_conflict="user_id")
        .execute()
    )
    return resp.data[0] if resp.data else None


def disconnect_linkedin_outreach(access_token: str) -> bool:
    """Délie le compte Unipile de l'utilisateur (le journal d'actions reste)."""
    if not supabase_enabled():
        return False
    user = get_user(access_token)
    if not user:
        return False
    db = client_for_token(access_token)
    resp = (
        db.table("linkedin_outreach_accounts")
        .delete()
        .eq("user_id", user["id"])
        .execute()
    )
    return bool(resp.data)


def list_claimed_unipile_account_ids() -> set[str]:
    """Tous les `unipile_account_id` déjà rattachés à un utilisateur (service-role).

    Sert au rattachement du compte fraîchement connecté : /accounts d'Unipile ne
    renvoie pas notre `name` (=user_id) mais le nom LinkedIn du compte, donc on
    réclame un compte NON déjà pris — d'où ce set des comptes déjà attribués.
    Service-role car il faut voir les lignes de TOUS les utilisateurs (RLS bypass)."""
    if not admin_enabled():
        return set()
    try:
        resp = (
            admin_client()
            .table("linkedin_outreach_accounts")
            .select("unipile_account_id")
            .execute()
        )
    except Exception:
        return set()
    return {r["unipile_account_id"] for r in (resp.data or []) if r.get("unipile_account_id")}


def log_outreach_action(
    access_token: str,
    *,
    action_type: str,
    status: str = "sent",
    origin: str = "immediate",
    lead_id: str | None = None,
    provider_id: str | None = None,
    chat_id: str | None = None,
    error: str | None = None,
) -> None:
    """Journalise une action d'envoi (invitation/message). Best-effort.

    `origin` : depuis ALE-174, tout envoi passant par l'API est un envoi *immédiat*
    (la soupape) — la voie normale passe par la file et est journalisée par le moteur
    avec `origin='queue'`. C'est ce champ qui plafonne la soupape à quelques envois
    par jour."""
    if not supabase_enabled():
        return
    user = get_user(access_token)
    if not user:
        return
    db = client_for_token(access_token)
    row: dict[str, Any] = {
        "user_id": user["id"],
        "action_type": action_type,
        "status": status,
        "origin": origin,
    }
    if lead_id:
        row["lead_id"] = lead_id
    if provider_id:
        row["provider_id"] = provider_id
    if chat_id:
        row["chat_id"] = chat_id
    if error:
        row["error"] = error[:2000]
    try:
        db.table("linkedin_outreach_actions").insert(row).execute()
    except Exception as exc:  # noqa: BLE001 — la journalisation ne doit rien casser
        print(f"[outreach] log action échoué : {exc}", flush=True)


def outreach_counts(access_token: str) -> dict[str, int]:
    """Compteurs de quota sur fenêtres glissantes : invitations & messages sur
    24 h, invitations sur 7 j. Seules les actions RÉUSSIES (status='sent') comptent.
    Calcul depuis le journal → auto-correctif, aucun compteur à réinitialiser.

    ⚠️ Lève en cas d'échec de lecture (Supabase indisponible…) : le quota est un
    garde-fou anti-restriction, il doit échouer FERMÉ. L'appelant traite l'erreur
    en bloquant l'envoi, jamais en le laissant passer. `supabase_enabled()` False
    ou pas d'utilisateur → 0 (feature simplement inactive, pas un échec de lecture)."""
    zero = {"invites_today": 0, "messages_today": 0, "invites_week": 0}
    if not supabase_enabled():
        return zero
    user = get_user(access_token)
    if not user:
        return zero
    now = datetime.datetime.now(datetime.timezone.utc)
    day_ago = (now - datetime.timedelta(hours=24)).isoformat()
    week_ago = (now - datetime.timedelta(days=7)).isoformat()
    db = client_for_token(access_token)

    def _count(action_type: str, since: str) -> int:
        # Pas de try/except ici : une erreur de lecture doit remonter (fail closed).
        resp = (
            db.table("linkedin_outreach_actions")
            .select("id")
            .eq("action_type", action_type)
            .eq("status", "sent")
            .gte("created_at", since)
            .execute()
        )
        return len(resp.data or [])

    return {
        "invites_today": _count("invite", day_ago),
        "messages_today": _count("message", day_ago),
        "invites_week": _count("invite", week_ago),
    }


def get_outreach_chat_lead_names(access_token: str) -> dict[str, str]:
    """Map `outreach_chat_id` -> nom du lead, pour nommer les conversations
    LinkedIn de l'Inbox : Unipile ne renvoie pas toujours le nom du participant
    dans la liste des chats, alors que le lead scrapé, lui, a un nom."""
    if not supabase_enabled():
        return {}
    db = client_for_token(access_token)
    resp = db.table("leads").select("name, outreach_chat_id").execute()
    out: dict[str, str] = {}
    for row in resp.data or []:
        cid = row.get("outreach_chat_id")
        name = (row.get("name") or "").strip()
        if cid and name:
            out[cid] = name
    return out


def get_lead(access_token: str, lead_id: str) -> dict | None:
    """Un lead par id (RLS scope)."""
    if not supabase_enabled() or not lead_id:
        return None
    db = client_for_token(access_token)
    resp = db.table("leads").select("*").eq("id", lead_id).limit(1).execute()
    return resp.data[0] if resp.data else None


def get_lead_by_chat_id(access_token: str, chat_id: str) -> dict | None:
    """Le lead scrapé rattaché à une conversation LinkedIn (RLS scope), si connu.

    Une conversation LinkedIn ouverte depuis l'Inbox ne provient pas toujours
    d'un lead qu'on a scrapé (l'utilisateur peut avoir déjà des messages sur
    son compte) — `None` dans ce cas, à l'appelant de dégrader proprement.
    """
    if not supabase_enabled() or not chat_id:
        return None
    db = client_for_token(access_token)
    resp = db.table("leads").select("*").eq("outreach_chat_id", chat_id).limit(1).execute()
    return resp.data[0] if resp.data else None


def set_lead_contact_status(
    access_token: str, lead_id: str, contact_status: str, skip_reason: str | None
) -> dict | None:
    """Curation manuelle (ALE-243) : marque un lead 'to_contact' ou 'skip' (+ raison
    courte). Ne supprime JAMAIS le lead — il reste dans la liste, relégué en bas.
    La raison n'est conservée que pour 'skip' (nettoyée si on le remet en liste)."""
    if not supabase_enabled() or not lead_id:
        return None
    db = client_for_token(access_token)
    payload = {
        "contact_status": contact_status,
        "skip_reason": (skip_reason or None) if contact_status == "skip" else None,
    }
    resp = db.table("leads").update(payload).eq("id", lead_id).execute()
    return resp.data[0] if resp.data else None


def update_lead_outreach(access_token: str, lead_id: str, fields: dict[str, Any]) -> dict | None:
    """Met à jour l'état d'outreach d'un lead (status, provider_id, chat_id…)."""
    if not supabase_enabled() or not lead_id or not fields:
        return None
    db = client_for_token(access_token)
    payload = dict(fields)
    payload["outreach_updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    resp = db.table("leads").update(payload).eq("id", lead_id).execute()
    return resp.data[0] if resp.data else None


# --------------------------------------------------------------------------- #
# ALE-174 — Moteur d'envoi cadencé : la file d'envoi + les accès du cron.
#
# DEUX FAMILLES DE FONCTIONS, à ne surtout pas mélanger :
#
#  1. Celles qui prennent un `access_token` (appels depuis l'API, pour le compte
#     d'un utilisateur connecté) : la base cloisonne SEULE via la RLS. C'est le
#     modèle de tout le code de prospection existant.
#
#  2. Celles préfixées `admin_` (appels depuis le cron, qui n'a aucun jeton) :
#     elles passent par la clé service-role, qui **contourne la RLS**. Elles
#     exigent donc TOUTES un `user_id` explicite et filtrent dessus à la main.
#     Aucune ne doit être appelée depuis un endpoint HTTP.
#
#  ⚠️ Le danger de la famille 2 : sans le `.eq("user_id", …)`, on lit/écrit les
#  lignes de TOUS les clients — donc on peut envoyer le message du client A depuis
#  le compte LinkedIn du client B. D'où le `user_id` en premier paramètre
#  obligatoire (jamais de défaut) et le garde-fou `outreach_engine.assert_same_owner`
#  juste avant l'appel réseau, côté cron.
# --------------------------------------------------------------------------- #


# ⚠️ Toute colonne absente de cette projection est lue `None` par le moteur et par
# l'app, SANS la moindre erreur — c'est exactement ainsi que `template_id` a été ignoré
# pendant toute la vie d'ALE-216. Ajouter une colonne à la file ⇒ l'ajouter ici.
_QUEUE_COLS = "id, user_id, lead_id, action_type, body, status, origin, not_before, sent_at, error, created_at"


def enqueue_outreach_action(
    access_token: str,
    *,
    lead_id: str,
    action_type: str,
    body: str | None = None,
    not_before: str | None = None,
) -> dict | None:
    """Met une action de prospection en file (RLS scope).

    L'index unique partiel `(lead_id, action_type) where status = 'pending'` interdit
    d'empiler deux fois la même action sur un lead : un double-clic ne crée pas deux
    invitations. On renvoie alors l'action déjà en file plutôt qu'une erreur."""
    if not supabase_enabled() or not lead_id:
        return None
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    row: dict[str, Any] = {
        "user_id": user["id"],
        "lead_id": lead_id,
        "action_type": action_type,
        "status": "pending",
    }
    if body:
        row["body"] = body
    if not_before:
        row["not_before"] = not_before
    try:
        resp = db.table("linkedin_outreach_queue").insert(row).execute()
        return resp.data[0] if resp.data else None
    except Exception:  # noqa: BLE001 — collision d'unicité = action déjà en file
        existing = (
            db.table("linkedin_outreach_queue")
            .select(_QUEUE_COLS)
            .eq("lead_id", lead_id)
            .eq("action_type", action_type)
            .eq("status", "pending")
            .limit(1)
            .execute()
        )
        return existing.data[0] if existing.data else None


def list_outreach_queue(access_token: str, *, status: str = "pending") -> list[dict]:
    """Actions en file de l'utilisateur (RLS scope), les plus anciennes d'abord."""
    if not supabase_enabled():
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("linkedin_outreach_queue")
        .select(_QUEUE_COLS)
        .eq("status", status)
        .order("not_before")
        .limit(200)
        .execute()
    )
    return resp.data or []


def list_outreach_drafts(access_token: str) -> list[dict]:
    """Brouillons de l'autopilote en attente de relecture (RLS scope), avec leur lead.

    Le lead est joint ici plutôt que relu un par un côté API : la liste s'affiche en
    une requête, et surtout on ne peut pas afficher un brouillon sans savoir à qui il
    est destiné — ce serait demander au client de valider un message à l'aveugle."""
    if not supabase_enabled():
        return []
    db = client_for_token(access_token)
    resp = (
        db.table("linkedin_outreach_queue")
        .select(f"{_QUEUE_COLS}, leads(id, name, headline, profile_url, score, score_reason)")
        .eq("status", "draft")
        .order("created_at")
        .limit(100)
        .execute()
    )
    return resp.data or []


def count_leads_by_tier(access_token: str) -> dict[str, int]:
    """Répartition des leads du client par palier de score (RLS scope).

    Sert à la pop-up d'autopilote : « vert seulement » doit annoncer combien de
    personnes cela représente vraiment. Un choix de ciblage fait à l'aveugle, sur un
    stock inconnu, n'est pas un choix éclairé.

    Les leads écartés à la main (`skip`) sont exclus du décompte : l'autopilote ne les
    contactera jamais, les compter gonflerait le chiffre annoncé au client."""
    from src import outreach_autopilot as autopilot  # import local : évite un cycle db ↔ autopilot

    counts = {"green": 0, "orange": 0, "red": 0, "unscored": 0}
    if not supabase_enabled():
        return counts
    db = client_for_token(access_token)
    resp = (
        db.table("leads")
        .select("score, contact_status, outreach_status")
        .neq("contact_status", "skip")
        .eq("outreach_status", "none")
        .limit(5000)
        .execute()
    )
    for row in resp.data or []:
        tier = autopilot.tier_of(row.get("score"))
        counts["unscored" if tier is None else tier] += 1
    return counts


def cancel_outreach_queue_item(access_token: str, item_id: str) -> dict | None:
    """Retire une action de la file tant qu'elle n'est pas partie (RLS scope).

    Le filtre sur le statut évite d'« annuler » une action déjà envoyée. `draft` est
    inclus (ALE-284) : refuser un brouillon proposé par l'autopilote, c'est la même
    opération qu'annuler une action en file — et un brouillon refusé ne doit pas
    revenir (le planificateur ne repropose jamais un lead déjà passé par la file)."""
    if not supabase_enabled() or not item_id:
        return None
    db = client_for_token(access_token)
    resp = (
        db.table("linkedin_outreach_queue")
        .update({"status": "canceled", "updated_at": "now()"})
        .eq("id", item_id)
        .in_("status", ["pending", "draft"])
        .execute()
    )
    return resp.data[0] if resp.data else None


def approve_outreach_draft(access_token: str, item_id: str, *, body: str | None = None) -> dict | None:
    """Valide un brouillon de l'autopilote : il passe de `draft` à `pending` (RLS scope).

    C'est le SEUL chemin par lequel un message relu entre dans la file d'envoi. Le
    filtre `status = 'draft'` est le garde-fou : il rend l'opération inopérante sur une
    action déjà envoyée, déjà en file ou annulée — un rejeu de la requête (double-clic,
    onglet resté ouvert) ne peut donc pas ressusciter un message refusé.

    `body` permet au client d'envoyer le texte qu'il a corrigé à l'écran. On garde la
    règle d'architecture d'ALE-174 : le texte définitif entre dans la file AVEC
    l'action, il n'est jamais (re)généré au moment de l'envoi."""
    if not supabase_enabled() or not item_id:
        return None
    db = client_for_token(access_token)
    patch: dict[str, Any] = {"status": "pending", "updated_at": "now()"}
    text = (body or "").strip()
    if text:
        patch["body"] = text[:1500]
    resp = (
        db.table("linkedin_outreach_queue")
        .update(patch)
        .eq("id", item_id)
        .eq("status", "draft")
        .execute()
    )
    return resp.data[0] if resp.data else None


def count_immediate_outreach_sends(access_token: str) -> int:
    """Envois immédiats (soupape « envoyer maintenant ») sur 24 h glissantes.

    Lève en cas d'échec de lecture, comme `outreach_counts` : la soupape est un
    garde-fou, elle doit échouer FERMÉE."""
    if not supabase_enabled():
        return 0
    user = get_user(access_token)
    if not user:
        return 0
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)).isoformat()
    db = client_for_token(access_token)
    resp = (
        db.table("linkedin_outreach_actions")
        .select("id")
        .eq("origin", "immediate")
        .eq("status", "sent")
        .gte("created_at", since)
        .execute()
    )
    return len(resp.data or [])


# ── Famille service-role (cron) : `user_id` obligatoire partout ───────────────


def admin_list_outreach_accounts() -> list[dict]:
    """Tous les comptes de prospection connectés (service-role, pour le cron).

    Chaque ligne porte son `user_id` : c'est LUI qui sert de clé de cloisonnement
    dans toute la suite du traitement, jamais un contexte ambiant."""
    if not admin_enabled():
        return []
    resp = (
        admin_client()
        .table("linkedin_outreach_accounts")
        .select("*")
        .not_.is_("unipile_account_id", "null")
        .limit(500)
        .execute()
    )
    return resp.data or []


def admin_pending_queue_count(user_id: str) -> int:
    """Nombre d'actions en attente pour CE client (service-role)."""
    if not admin_enabled() or not user_id:
        return 0
    resp = (
        admin_client()
        .table("linkedin_outreach_queue")
        .select("id")
        .eq("user_id", user_id)
        .eq("status", "pending")
        .execute()
    )
    return len(resp.data or [])


def admin_due_queue_items(user_id: str, *, limit: int = 10) -> list[dict]:
    """Actions dues de CE client (service-role), les plus anciennes d'abord.

    `user_id` filtre explicitement : la clé service-role contourne la RLS, donc
    l'absence de ce filtre ferait remonter les actions de tous les clients."""
    if not admin_enabled() or not user_id:
        return []
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    resp = (
        admin_client()
        .table("linkedin_outreach_queue")
        .select(_QUEUE_COLS)
        .eq("user_id", user_id)
        .eq("status", "pending")
        .lte("not_before", now)
        .order("not_before")
        .limit(limit)
        .execute()
    )
    return resp.data or []


def admin_outreach_counts(user_id: str) -> dict[str, int]:
    """Compteurs de quota de CE client (service-role), fenêtres glissantes.

    Même contrat que `outreach_counts` : LÈVE en cas d'échec de lecture (fail closed,
    l'appelant bloque l'envoi). Filtre `user_id` obligatoire."""
    if not admin_enabled() or not user_id:
        return {"invites_today": 0, "messages_today": 0, "invites_week": 0}
    now = datetime.datetime.now(datetime.timezone.utc)
    day_ago = (now - datetime.timedelta(hours=24)).isoformat()
    week_ago = (now - datetime.timedelta(days=7)).isoformat()
    admin = admin_client()

    def _count(action_type: str, since: str) -> int:
        resp = (
            admin.table("linkedin_outreach_actions")
            .select("id")
            .eq("user_id", user_id)
            .eq("action_type", action_type)
            .eq("status", "sent")
            .gte("created_at", since)
            .execute()
        )
        return len(resp.data or [])

    return {
        "invites_today": _count("invite", day_ago),
        "messages_today": _count("message", day_ago),
        "invites_week": _count("invite", week_ago),
    }


def admin_get_lead(user_id: str, lead_id: str) -> dict | None:
    """Un lead de CE client (service-role). Le filtre `user_id` est la sécurité :
    un lead_id venu de la file ne peut pas pointer sur le lead d'un autre client."""
    if not admin_enabled() or not user_id or not lead_id:
        return None
    resp = (
        admin_client()
        .table("leads")
        .select("*")
        .eq("id", lead_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def admin_update_lead_outreach(user_id: str, lead_id: str, fields: dict[str, Any]) -> dict | None:
    """Met à jour l'état d'outreach d'un lead de CE client (service-role)."""
    if not admin_enabled() or not user_id or not lead_id or not fields:
        return None
    payload = dict(fields)
    payload["outreach_updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    resp = (
        admin_client()
        .table("leads")
        .update(payload)
        .eq("id", lead_id)
        .eq("user_id", user_id)
        .execute()
    )
    return resp.data[0] if resp.data else None


def admin_list_leads_awaiting_acceptance(user_id: str, *, limit: int = 100) -> list[dict]:
    """Leads de CE client dont l'invitation est partie mais pas encore acceptée
    (service-role, pour la détection automatique d'acceptation).

    Le filtre `user_id` est la sécurité : la clé service-role contourne la RLS, donc
    sans lui on remonterait les leads de tous les clients."""
    if not admin_enabled() or not user_id:
        return []
    resp = (
        admin_client()
        .table("leads")
        .select("id, user_id, provider_id, profile_url, outreach_status, outreach_updated_at, outreach_last_checked_at")
        .eq("user_id", user_id)
        .eq("outreach_status", "invite_sent")
        .limit(limit)
        .execute()
    )
    return resp.data or []


# --------------------------------------------------------------------------- #
# ALE-284 — Autopilote : les accès du planificateur (service-role).
#
# Même règle que toute la famille `admin_` : `user_id` en premier paramètre, jamais
# de défaut, et filtré explicitement sur CHAQUE requête. Ici l'enjeu est direct — un
# filtre manquant ferait inviter les leads du client A depuis le compte LinkedIn du
# client B, sans la moindre erreur visible.
# --------------------------------------------------------------------------- #


def admin_user_app_metadata(user_id: str) -> dict | None:
    """`app_metadata` de CE compte, lu en service-role (rôle + feature flags).

    Le cron n'a aucun jeton : il ne peut pas passer par `get_user(token)`. Sert au
    planificateur de l'autopilote à vérifier que le compte a toujours la fonctionnalité
    — sans ça, retirer le flag à quelqu'un ne couperait pas son autopilote déjà armé.

    Retourne **None** (et pas `{}`) si la lecture échoue : l'appelant doit pouvoir
    distinguer « ce compte n'a aucun flag » de « je n'ai pas réussi à savoir », et
    fermer dans le second cas."""
    if not admin_enabled() or not user_id:
        return None
    try:
        resp = admin_client().auth.admin.get_user_by_id(user_id)
    except Exception as exc:  # noqa: BLE001
        print(f"[features] lecture d'app_metadata échouée ({user_id}) : {exc}", flush=True)
        return None
    user = getattr(resp, "user", None)
    if not user:
        return None
    meta = getattr(user, "app_metadata", None)
    return dict(meta) if isinstance(meta, dict) else {}


def admin_get_lead_targeting(user_id: str) -> dict | None:
    """Ciblage ICP de CE client (service-role).

    Le cron n'a aucun jeton : il ne peut pas passer par `get_lead_targeting(token)`,
    qui s'appuie sur la RLS. Sans ce ciblage, l'IA écrirait un message hors sujet —
    le planificateur préfère alors ne rien proposer du tout."""
    if not admin_enabled() or not user_id:
        return None
    resp = (
        admin_client()
        .table("lead_targeting")
        .select("user_id, ideal_client, offer, interest_keywords, score_threshold, first_message_instructions")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def admin_list_leads_for_autopilot(user_id: str, *, limit: int = 400) -> list[dict]:
    """Leads de CE client que l'autopilote peut avoir à traiter (service-role).

    On ne remonte que les états utiles au planificateur : `none` (candidat à une
    invitation) et `connected` (candidat à un premier message). Les leads déjà invités
    ou déjà contactés ne le concernent pas — les premiers sont entre les mains de la
    détection d'acceptation, les seconds sont terminés."""
    if not admin_enabled() or not user_id:
        return []
    resp = (
        admin_client()
        .table("leads")
        .select(
            "id, user_id, name, headline, profile_url, comment_text, signals, "
            "score, score_reason, outreach_status, contact_status, provider_id, "
            "created_at, outreach_updated_at"
        )
        .eq("user_id", user_id)
        .in_("outreach_status", ["none", "connected"])
        .neq("contact_status", "skip")
        .order("score", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def admin_queue_lead_ids(user_id: str, action_type: str) -> set[str]:
    """Leads de CE client ayant DÉJÀ une action de ce type en file (service-role).

    Tous statuts confondus, volontairement — y compris `canceled` et `failed`. C'est
    ce qui garantit que l'autopilote ne propose qu'UNE fois : sans ça, un brouillon
    refusé ou une invitation annulée par le client reviendrait au passage suivant, en
    boucle, et le « non » du client ne vaudrait rien."""
    if not admin_enabled() or not user_id:
        return set()
    resp = (
        admin_client()
        .table("linkedin_outreach_queue")
        .select("lead_id")
        .eq("user_id", user_id)
        .eq("action_type", action_type)
        .limit(5000)
        .execute()
    )
    return {str(r["lead_id"]) for r in (resp.data or []) if r.get("lead_id")}


def admin_count_auto_invites_today(user_id: str) -> int:
    """Invitations déposées par l'autopilote pour CE client sur 24 h glissantes.

    Compte les DÉPÔTS en file, pas les envois : c'est le robinet qu'on veut borner.
    Les envois, eux, sont déjà bornés par le warm-up et les plafonds durs d'ALE-174 —
    les deux limites se cumulent, elles ne se remplacent pas."""
    if not admin_enabled() or not user_id:
        return 0
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)).isoformat()
    resp = (
        admin_client()
        .table("linkedin_outreach_queue")
        .select("id")
        .eq("user_id", user_id)
        .eq("action_type", "invite")
        .eq("origin", "autopilot")
        .gte("created_at", since)
        .execute()
    )
    return len(resp.data or [])


def admin_enqueue_outreach_action(
    user_id: str,
    *,
    lead_id: str,
    action_type: str,
    body: str | None = None,
    status: str = "pending",
    not_before: str | None = None,
) -> dict | None:
    """Dépose une action de l'autopilote dans la file (service-role).

    `status` vaut `pending` (part au prochain créneau du moteur) ou `draft` (attend la
    relecture du client — le moteur ne lit pas ce statut, l'action est donc
    structurellement inenvoyable tant qu'elle n'est pas approuvée).

    Les index uniques partiels sur (lead_id, action_type) — un pour `pending`, un pour
    `draft` — interdisent d'empiler deux fois la même action : deux passages du cron
    qui se chevaucheraient ne peuvent pas créer de doublon. Une collision n'est donc
    pas une erreur, c'est le résultat attendu, et on renvoie None sans crier."""
    if not admin_enabled() or not user_id or not lead_id:
        return None
    row: dict[str, Any] = {
        "user_id": user_id,
        "lead_id": lead_id,
        "action_type": action_type,
        "status": status,
        "origin": "autopilot",
    }
    if body:
        row["body"] = body
    if not_before:
        row["not_before"] = not_before
    try:
        resp = admin_client().table("linkedin_outreach_queue").insert(row).execute()
        return resp.data[0] if resp.data else None
    except Exception:  # noqa: BLE001 — collision d'unicité = action déjà en file
        return None


def admin_mark_lead_checked(user_id: str, lead_id: str) -> None:
    """Note qu'un lead vient d'être re-vérifié sans changement d'état (service-role).

    Sert de cadence : on repousse ainsi le prochain re-check de ce lead. Distinct de
    `outreach_updated_at` (qui, lui, ne bouge que quand l'ÉTAT change) pour ne pas
    faire croire à un changement de statut à chaque lecture."""
    if not admin_enabled() or not user_id or not lead_id:
        return
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (
        admin_client()
        .table("leads")
        .update({"outreach_last_checked_at": now})
        .eq("id", lead_id)
        .eq("user_id", user_id)
        .execute()
    )


def admin_log_outreach_action(
    user_id: str,
    *,
    action_type: str,
    status: str = "sent",
    origin: str = "queue",
    lead_id: str | None = None,
    provider_id: str | None = None,
    chat_id: str | None = None,
    error: str | None = None,
) -> None:
    """Journalise une action envoyée par le moteur (service-role).

    Ce journal EST la source des compteurs de quota : ne jamais l'oublier après un
    envoi réussi, sinon le plafond du jour ne voit pas l'action passer."""
    if not admin_enabled() or not user_id:
        return
    row: dict[str, Any] = {
        "user_id": user_id,
        "action_type": action_type,
        "status": status,
        "origin": origin,
    }
    if lead_id:
        row["lead_id"] = lead_id
    if provider_id:
        row["provider_id"] = provider_id
    if chat_id:
        row["chat_id"] = chat_id
    if error:
        row["error"] = error[:2000]
    try:
        admin_client().table("linkedin_outreach_actions").insert(row).execute()
    except Exception as exc:  # noqa: BLE001 — la journalisation ne doit rien casser
        print(f"[outreach-sender] log action échoué : {exc}", flush=True)


def admin_update_queue_item(
    user_id: str,
    item_id: str,
    *,
    status: str,
    error: str | None = None,
) -> None:
    """Solde une action de la file de CE client (service-role)."""
    if not admin_enabled() or not user_id or not item_id:
        return
    payload: dict[str, Any] = {"status": status, "updated_at": "now()"}
    if status == "sent":
        payload["sent_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if error is not None:
        payload["error"] = error[:2000]
    admin_client().table("linkedin_outreach_queue").update(payload).eq("id", item_id).eq(
        "user_id", user_id
    ).execute()


def admin_mark_outreach_sent(user_id: str, *, next_action_at: str) -> None:
    """Pose l'horodatage de la dernière action + le délai aléatoire avant la
    prochaine (service-role). C'est ce `next_action_at` qui espace les envois."""
    if not admin_enabled() or not user_id:
        return
    admin_client().table("linkedin_outreach_accounts").update(
        {
            "last_action_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "next_action_at": next_action_at,
            "updated_at": "now()",
        }
    ).eq("user_id", user_id).execute()


def admin_freeze_outreach_account(user_id: str, reason: str) -> None:
    """Gèle le compte de CE client (service-role) : LinkedIn a signalé une limite ou
    une restriction. Non contournable depuis l'interface — c'est le dernier rempart."""
    if not admin_enabled() or not user_id:
        return
    admin_client().table("linkedin_outreach_accounts").update(
        {
            "frozen": True,
            "freeze_reason": (reason or "Limite LinkedIn atteinte.")[:500],
            "frozen_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "updated_at": "now()",
        }
    ).eq("user_id", user_id).execute()


def admin_record_engine_run(user_id: str, *, sent: int = 0, error: str | None = None) -> None:
    """Trace le passage du moteur sur ce compte (service-role).

    Écrit à CHAQUE passage, même quand rien n'est envoyé : c'est cette date qui
    permet à l'app de dire « dernier passage il y a 8 min » et de lever le bandeau
    « prospection à l'arrêt » quand le cron est mort. Un cron mort ne peut pas
    alerter sur sa propre mort — seule la fraîcheur de cette date le trahit."""
    if not admin_enabled() or not user_id:
        return
    try:
        admin_client().table("linkedin_outreach_accounts").update(
            {
                "last_run_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "last_run_sent": max(0, int(sent)),
                "last_run_error": (error or None) and str(error)[:500],
                "updated_at": "now()",
            }
        ).eq("user_id", user_id).execute()
    except Exception as exc:  # noqa: BLE001 — la trace ne doit jamais casser le run
        print(f"[outreach-sender] trace de passage échouée ({user_id}) : {exc}", flush=True)


def admin_unfreeze_outreach_account(user_id: str) -> None:
    """Lève un gel EXPIRÉ (service-role, appelé par le moteur uniquement).

    Le client n'a aucun moyen de lever un gel lui-même : ce serait son premier
    réflexe, au pire moment. Seul le moteur le fait, et seulement une fois la période
    de refroidissement écoulée (`outreach_engine.freeze_active`)."""
    if not admin_enabled() or not user_id:
        return
    admin_client().table("linkedin_outreach_accounts").update(
        {"frozen": False, "freeze_reason": None, "frozen_at": None, "updated_at": "now()"}
    ).eq("user_id", user_id).execute()
