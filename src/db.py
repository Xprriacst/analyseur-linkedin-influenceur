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

    Upserts the influencer (and its posts), then replaces the current analysis
    report for that user/influencer pair.
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
        .select("id,handle,created_at,updated_at,posts_limit")
        .eq("user_id", user["id"])
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


def list_reports(access_token: str, limit: int = 10) -> list[dict]:
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


def _optional_user_rows(
    db: "Client",
    user_id: str,
    table: str,
    columns: str,
    limit: int = 1000,
) -> dict[str, Any]:
    """Read an optional per-user table without making progress depend on it.

    Some roadmap bricks (library, publication, credits) may not be migrated yet
    in every environment. Missing tables should appear as unavailable sections,
    not as a failing global dashboard.
    """
    try:
        resp = (
            db.table(table)
            .select(columns)
            .eq("user_id", user_id)
            .limit(limit)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 - optional table / column drift
        return {"available": False, "rows": [], "error": str(exc)[:240]}
    return {"available": True, "rows": resp.data or [], "error": None}


def _usage_totals(analyses: list[dict]) -> dict[str, Any]:
    totals = {
        "estimated_cost_usd": 0.0,
        "apify_items": 0,
        "apify_runs": 0,
        "anthropic_calls": 0,
        "anthropic_tokens": 0,
    }
    for row in analyses:
        usage = row.get("usage") or {}
        apify = usage.get("apify") or {}
        anthropic = usage.get("anthropic") or {}
        totals["estimated_cost_usd"] += float(apify.get("estimated_cost_usd", 0) or 0)
        totals["estimated_cost_usd"] += float(anthropic.get("estimated_cost_usd", 0) or 0)
        totals["apify_items"] += int(apify.get("items", 0) or 0)
        totals["apify_runs"] += int(apify.get("runs", 0) or 0)
        totals["anthropic_calls"] += int(anthropic.get("calls", 0) or 0)
        totals["anthropic_tokens"] += int(anthropic.get("input_tokens", 0) or 0)
        totals["anthropic_tokens"] += int(anthropic.get("output_tokens", 0) or 0)
    totals["estimated_cost_usd"] = round(totals["estimated_cost_usd"], 4)
    return totals


def _count_by_status(rows: list[dict], fallback: str = "saved") -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = (
            row.get("status")
            or row.get("state")
            or row.get("publication_status")
            or ("archived" if row.get("archived") else fallback)
        )
        counts[str(status)] = counts.get(str(status), 0) + 1
    return counts


def _progress_status(
    *,
    available: bool = True,
    blocked: bool = False,
    active: bool = False,
    complete: bool = False,
) -> str:
    if not available:
        return "unavailable"
    if blocked:
        return "blocked"
    if active:
        return "in_progress"
    if complete:
        return "ready"
    return "todo"


def _next_action(
    *,
    influencers_count: int,
    active_jobs: int,
    failed_job_items: int,
    ideas_available: bool,
    ideas_count: int,
    posts_available: bool,
    posts_count: int,
) -> dict[str, Any]:
    if active_jobs:
        return {
            "key": "follow_running_job",
            "label": "Suivre la série d'analyses en cours",
            "description": "Un backlog tourne côté serveur : surveille les profils terminés puis ouvre les rapports prêts.",
            "view": "analyze",
        }
    if failed_job_items:
        return {
            "key": "review_failed_jobs",
            "label": "Traiter les profils en échec",
            "description": "Corrige les URLs ou relance la série pour compléter ton corpus.",
            "view": "analyze",
        }
    if influencers_count == 0:
        return {
            "key": "start_corpus",
            "label": "Analyser un premier profil LinkedIn",
            "description": "Ajoute 1 à 3 influenceurs pour créer la base de génération.",
            "view": "analyze",
        }
    if ideas_available and ideas_count == 0:
        return {
            "key": "generate_ideas",
            "label": "Générer tes premières idées",
            "description": "Transforme le corpus analysé en angles de posts réutilisables.",
            "view": "generator",
        }
    if posts_available and ideas_count > 0 and posts_count == 0:
        return {
            "key": "generate_posts",
            "label": "Transformer une idée en post",
            "description": "Génère des variantes à partir d'une idée ou d'un sujet prioritaire.",
            "view": "generator",
        }
    return {
        "key": "keep_building",
        "label": "Continuer à enrichir ton système",
        "description": "Ajoute des profils, génère de nouvelles idées ou prépare le prochain post.",
        "view": "analyze" if influencers_count < 3 else "generator",
    }


def get_dashboard_progress(access_token: str) -> dict | None:
    """Aggregate the authenticated user's product progress across modules."""
    user = get_user(access_token)
    if not user:
        return None
    db = client_for_token(access_token)
    user_id = user["id"]

    inf_resp = (
        db.table("influencers")
        .select("id,handle,name,updated_at")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .execute()
    )
    influencers = inf_resp.data or []

    an_resp = (
        db.table("analyses")
        .select("id,handle,updated_at,usage,influencers(name)")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .limit(50)
        .execute()
    )
    analyses = an_resp.data or []

    try:
        jobs = list_jobs(access_token)
    except Exception:  # noqa: BLE001 - migration can be absent in older envs
        jobs = []

    ideas = _optional_user_rows(
        db,
        user_id,
        "generated_ideas",
        "*",
    )
    drafts = _optional_user_rows(
        db,
        user_id,
        "user_draft_ideas",
        "*",
    )
    posts = _optional_user_rows(
        db,
        user_id,
        "generated_posts",
        "*",
    )
    publications = _optional_user_rows(
        db,
        user_id,
        "linkedin_connections",
        "*",
        limit=10,
    )
    credits = _optional_user_rows(
        db,
        user_id,
        "user_credits",
        "*",
        limit=10,
    )

    active_jobs = [
        job for job in jobs
        if job.get("status") in {"queued", "running"}
    ]
    job_items = [
        item
        for job in jobs
        for item in job.get("items", [])
    ]
    failed_job_items = sum(1 for item in job_items if item.get("status") == "error")
    completed_job_items = sum(1 for item in job_items if item.get("status") == "done")

    idea_rows = ideas["rows"]
    draft_rows = drafts["rows"]
    post_rows = posts["rows"]
    publication_rows = publications["rows"]
    connected_publications = [
        row for row in publication_rows
        if str(row.get("status", "")).lower() in {"connected", "active", "ok"}
    ]
    credit_rows = credits["rows"]
    credit_balance = None
    if credit_rows:
        first_credit = credit_rows[0]
        credit_balance = (
            first_credit.get("balance")
            if first_credit.get("balance") is not None
            else first_credit.get("total")
        )

    ideas_available = bool(ideas["available"])
    posts_available = bool(posts["available"])
    usage_totals = _usage_totals(analyses)
    progress_sections = [
        {
            "key": "corpus",
            "title": "Corpus",
            "status": _progress_status(
                active=bool(active_jobs),
                complete=bool(influencers),
            ),
            "summary": (
                f"{len(influencers)} influenceur(s), {len(analyses)} analyse(s)"
                if influencers
                else "Aucun influenceur analysé"
            ),
            "metrics": {
                "influencers": len(influencers),
                "analyses": len(analyses),
                "jobs_total": len(jobs),
                "jobs_active": len(active_jobs),
                "job_items_done": completed_job_items,
                "job_items_failed": failed_job_items,
            },
            "recent": [
                {
                    "id": row.get("id"),
                    "handle": row.get("handle"),
                    "name": ((row.get("influencers") or {}).get("name") or row.get("handle")),
                    "updated_at": row.get("updated_at"),
                }
                for row in analyses[:3]
            ],
        },
        {
            "key": "ideas",
            "title": "Idées",
            "status": _progress_status(
                available=ideas_available,
                blocked=not influencers,
                complete=bool(idea_rows or draft_rows),
            ),
            "summary": (
                "Bibliothèque d'idées non disponible"
                if not ideas_available
                else f"{len(idea_rows)} idée(s) générée(s), {len(draft_rows)} brouillon(s)"
            ),
            "metrics": {
                "generated": len(idea_rows),
                "drafts": len(draft_rows),
                "drafts_available": drafts["available"],
                "by_status": _count_by_status(idea_rows),
            },
        },
        {
            "key": "posts",
            "title": "Posts",
            "status": _progress_status(
                available=posts_available,
                blocked=ideas_available and not idea_rows and not draft_rows,
                complete=bool(post_rows),
            ),
            "summary": (
                "Bibliothèque de posts non disponible"
                if not posts_available
                else f"{len(post_rows)} post(s) généré(s)"
            ),
            "metrics": {
                "generated": len(post_rows),
                "by_status": _count_by_status(post_rows, fallback="generated"),
            },
        },
        {
            "key": "publication",
            "title": "Publication",
            "status": _progress_status(
                available=publications["available"],
                complete=bool(connected_publications),
            ),
            "summary": (
                "Connexion LinkedIn / Unipile non disponible"
                if not publications["available"]
                else (
                    "Compte LinkedIn connecté"
                    if connected_publications
                    else "Aucun compte LinkedIn connecté"
                )
            ),
            "metrics": {
                "connections": len(publication_rows),
                "connected": len(connected_publications),
            },
        },
        {
            "key": "credits",
            "title": "Crédits / usage",
            "status": _progress_status(
                available=True,
                complete=bool(analyses),
            ),
            "summary": (
                f"Coût estimé historique : ${usage_totals['estimated_cost_usd']}"
                if analyses
                else "Aucun usage enregistré"
            ),
            "metrics": {
                **usage_totals,
                "credits_available": credits["available"],
                "credit_balance": credit_balance,
            },
        },
    ]

    ready = sum(1 for section in progress_sections if section["status"] == "ready")
    in_progress = sum(1 for section in progress_sections if section["status"] == "in_progress")
    actionable = [s for s in progress_sections if s["status"] != "unavailable"]
    completion_pct = round((ready / max(1, len(actionable))) * 100)

    return {
        "summary": {
            "completion_pct": completion_pct,
            "ready_sections": ready,
            "active_sections": in_progress,
            "available_sections": len(actionable),
            "total_sections": len(progress_sections),
        },
        "next_action": _next_action(
            influencers_count=len(influencers),
            active_jobs=len(active_jobs),
            failed_job_items=failed_job_items,
            ideas_available=ideas_available,
            ideas_count=len(idea_rows) + len(draft_rows),
            posts_available=posts_available,
            posts_count=len(post_rows),
        ),
        "sections": progress_sections,
    }


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
