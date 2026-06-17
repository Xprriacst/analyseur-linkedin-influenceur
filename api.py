from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src import db
from src.pipeline import run_analysis
from src.jobs import cancel_item, cancel_job, mark_stale_jobs, resume_job as resume_job_worker, start_job_thread
from src.llm import generate_ideas, generate_posts, analyze_dashboard_strategy
from src.normalize import normalize_posts, normalize_profile
from src.patterns import analyze_patterns
from src.stats import compute_stats

load_dotenv()

app = FastAPI(title="LinkedIn Strategy Decoder API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
        "https://courageous-strudel-2d8ba3.netlify.app",
        "https://lkd-outreach.netlify.app",
        "https://lkd-outreach-dev.netlify.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Extract a bearer token from an Authorization header."""
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def optional_token(authorization: Optional[str] = Header(default=None)) -> Optional[str]:
    """Optional auth: returns a token if present, else None (no error)."""
    return _bearer_token(authorization)


def require_token(authorization: Optional[str] = Header(default=None)) -> str:
    """Required auth: 401 if no valid Supabase session is provided."""
    token = _bearer_token(authorization)
    if not token or not db.get_user(token):
        raise HTTPException(status_code=401, detail="Authentification requise.")
    return token


class AnalyzeRequest(BaseModel):
    profile_url: str = Field(..., min_length=8)
    limit: int = Field(default=25, ge=10, le=50)
    use_cache: bool = True
    run_llm: bool = True


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "apify": bool(os.environ.get("APIFY_TOKEN")),
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "model": os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7"),
        "supabase": db.supabase_enabled(),
    }


@app.get("/me/influencers")
def me_influencers(token: str = Depends(require_token)) -> list[dict[str, Any]]:
    """List the authenticated user's analyzed influencers."""
    return db.list_influencers(token)


@app.get("/me/analyses")
def me_analyses(token: str = Depends(require_token)) -> list[dict[str, Any]]:
    """List the authenticated user's analysis history."""
    return db.list_analyses(token)


@app.get("/me/analyses/{analysis_id}")
def me_analysis(analysis_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Fetch a single stored analysis (report + computed data)."""
    analysis = db.get_analysis(token, analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analyse introuvable.")
    return analysis


@app.get("/reports")
def reports(token: Optional[str] = Depends(optional_token)) -> list[dict[str, Any]]:
    """Recent analysis reports, scoped to the authenticated user.

    Supabase-backed in production; falls back to the local reports/ folder
    only when Supabase is not configured (single-user dev mode).
    """
    if db.supabase_enabled():
        if not token or not db.get_user(token):
            raise HTTPException(status_code=401, detail="Authentification requise.")
        return db.list_reports(token)

    reports_dir = Path("reports")
    if not reports_dir.exists():
        return []
    files = sorted(reports_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "name": path.name,
            "path": str(path),
            "updated_at": path.stat().st_mtime,
            "content": path.read_text(encoding="utf-8"),
        }
        for path in files[:10]
    ]


def _load_cached_influencers() -> list[dict]:
    """Load all influencer profiles + posts from local cache."""
    import json
    cache_dir = Path("cache")
    if not cache_dir.exists():
        return []
    result = []
    for profile_file in sorted(cache_dir.glob("*-profile.json")):
        handle = profile_file.stem.replace("-profile", "")
        posts_file = cache_dir / f"{handle}-posts.json"
        if not posts_file.exists():
            continue
        try:
            profile_raw = json.loads(profile_file.read_text())
            posts_raw = json.loads(posts_file.read_text())
        except Exception:
            continue
        profile = normalize_profile(profile_raw)
        posts = normalize_posts(posts_raw)
        if not posts:
            continue
        patterns = analyze_patterns(posts)
        stats = compute_stats(posts, profile=profile)
        result.append({
            "handle": handle,
            "profile": profile,
            "posts": posts,
            "stats": stats,
            "patterns": patterns,
        })
    return result


def _enrich_influencers(corpus: list[dict]) -> list[dict]:
    """Compute stats + patterns on a raw corpus of {handle, profile, posts}."""
    result = []
    for inf in corpus:
        posts = inf["posts"]
        if not posts:
            continue
        result.append({
            "handle": inf["handle"],
            "profile": inf["profile"],
            "posts": posts,
            "stats": compute_stats(posts, profile=inf["profile"]),
            "patterns": analyze_patterns(posts),
        })
    return result


def _get_influencers(token: Optional[str]) -> list[dict]:
    """Per-user data source: Supabase when configured, disk cache otherwise.

    When Supabase is enabled the endpoints become multi-user: a valid session
    is required and only the caller's data is returned (RLS-scoped).
    """
    if db.supabase_enabled():
        if not token or not db.get_user(token):
            raise HTTPException(status_code=401, detail="Authentification requise.")
        return _enrich_influencers(db.get_user_corpus(token))
    return _load_cached_influencers()


def _build_benchmark(influencers: list[dict]) -> tuple[list[dict], dict]:
    """Build top posts list and benchmark summary."""
    from collections import Counter
    all_posts: list[dict] = []
    hook_totals: Counter = Counter()
    for inf in influencers:
        name = inf["profile"].get("name", inf["handle"])
        enriched = inf["patterns"].get("posts_enriched", inf["posts"])
        for p in enriched:
            all_posts.append({**p, "influencer": name})
        for hook, count in inf["patterns"].get("hook_distribution", {}).items():
            hook_totals[hook] += count

    top_posts = sorted(all_posts, key=lambda x: x.get("engagement", 0), reverse=True)[:6]
    benchmarks = []
    for inf in influencers:
        s = inf["stats"].get("engagement", {})
        benchmarks.append({
            "influencer": inf["profile"].get("name", inf["handle"]),
            "followers": inf["profile"].get("follower_count", 0),
            "avg_engagement": round(s.get("mean_engagement", 0), 1),
            "avg_comments": round(s.get("mean_comments", 0), 1),
        })
    benchmark = {
        "benchmarks": benchmarks,
        "top_hook_types": dict(hook_totals.most_common(6)),
        "proven_insights": [
            "Hook stat+contrarian : combo sous-exploité, +40-80% vs post standard",
            "Triple CTA (comment+repost+save) : multiplicateur x2-3 prouvé sur le corpus",
            "Format image/carousel : 2x plus d'engagement que texte seul",
            "Longueur optimale : 1 400-1 800 caractères",
            "Hook question : quasi absent du corpus = alpha, +150% engagement potentiel",
        ],
    }
    return top_posts, benchmark


@app.get("/dashboard")
def dashboard(token: Optional[str] = Depends(optional_token)) -> dict[str, Any]:
    """Aggregated stats across the user's analyzed influencers."""
    influencers = _get_influencers(token)
    if not influencers:
        return {"influencer_count": 0, "influencers": [], "aggregated": {}}

    total_posts = 0
    total_followers = 0
    all_likes = []
    all_comments = []
    all_reposts = []
    all_engagement = []
    format_counts: dict[str, int] = {}
    hook_counts: dict[str, int] = {}
    weekday_counts: dict[str, int] = {}
    influencer_summaries = []

    for inf in influencers:
        stats = inf["stats"]
        profile = inf["profile"]
        patterns = inf["patterns"]
        posts = inf["posts"]
        eng = stats.get("engagement", {})

        total_posts += stats.get("count", 0)
        total_followers += profile.get("follower_count", 0) or 0

        for p in posts:
            all_likes.append(p.get("likes", 0))
            all_comments.append(p.get("comments", 0))
            all_reposts.append(p.get("reposts", 0))
            all_engagement.append(p.get("engagement", 0))

        for fmt_name, count in stats.get("format_counts", {}).items():
            format_counts[fmt_name] = format_counts.get(fmt_name, 0) + count

        for hook, count in patterns.get("hook_distribution", {}).items():
            hook_counts[hook] = hook_counts.get(hook, 0) + count

        for day, count in stats.get("weekday_distribution", {}).items():
            weekday_counts[day] = weekday_counts.get(day, 0) + count

        influencer_summaries.append({
            "handle": inf["handle"],
            "name": profile.get("name", inf["handle"]),
            "headline": profile.get("headline", ""),
            "followers": profile.get("follower_count", 0) or 0,
            "posts_analyzed": stats.get("count", 0),
            "posts_per_week": stats.get("posts_per_week"),
            "avg_engagement": round(eng.get("mean_engagement", 0), 1),
            "median_comments": eng.get("median_comments", 0),
            "engagement_rate_pct": eng.get("engagement_rate_pct"),
            "top_format": max(stats.get("format_counts", {"?": 0}), key=lambda k: stats["format_counts"][k]) if stats.get("format_counts") else "—",
        })

    import statistics
    aggregated = {
        "total_posts": total_posts,
        "total_followers": total_followers,
        "avg_likes": round(statistics.mean(all_likes), 1) if all_likes else 0,
        "median_likes": round(statistics.median(all_likes)) if all_likes else 0,
        "avg_comments": round(statistics.mean(all_comments), 1) if all_comments else 0,
        "median_comments": round(statistics.median(all_comments)) if all_comments else 0,
        "avg_reposts": round(statistics.mean(all_reposts), 1) if all_reposts else 0,
        "avg_engagement": round(statistics.mean(all_engagement), 1) if all_engagement else 0,
        "median_engagement": round(statistics.median(all_engagement)) if all_engagement else 0,
        "format_distribution": format_counts,
        "hook_distribution": dict(sorted(hook_counts.items(), key=lambda x: x[1], reverse=True)),
        "weekday_distribution": weekday_counts,
    }

    return {
        "influencer_count": len(influencers),
        "influencers": influencer_summaries,
        "aggregated": aggregated,
    }


def _compute_growth(influencers: list[dict]) -> list[dict[str, Any]]:
    """Growth comparison: engagement before vs after the 25th post for each influencer."""
    result = []
    for inf in influencers:
        name = inf["profile"].get("name", inf["handle"]) or inf["handle"]
        posts_sorted = sorted(
            [p for p in inf["posts"] if p.get("date")],
            key=lambda x: x["date"],
        )
        total = len(posts_sorted)
        if total < 5:
            continue

        split_idx = min(25, total)
        first_batch = posts_sorted[:split_idx]
        later_batch = posts_sorted[split_idx:]

        import statistics as _stats
        first_eng = [p.get("engagement", 0) for p in first_batch]
        first_avg = round(_stats.mean(first_eng), 1) if first_eng else 0

        later_avg: float | None = None
        growth_pct: float | None = None
        if later_batch:
            later_eng = [p.get("engagement", 0) for p in later_batch]
            later_avg = round(_stats.mean(later_eng), 1)
            growth_pct = round(((later_avg / max(first_avg, 1)) - 1) * 100, 1)

        post_25_date = first_batch[-1]["date"]
        date_str = post_25_date.strftime("%Y-%m-%d") if hasattr(post_25_date, "strftime") else str(post_25_date)[:10]

        result.append({
            "handle": inf["handle"],
            "name": name,
            "total_posts": total,
            "split_at": split_idx,
            "date_post_split": date_str,
            "avg_eng_before": first_avg,
            "avg_eng_after": later_avg,
            "growth_pct": growth_pct,
        })

    result.sort(key=lambda x: x["growth_pct"] if x["growth_pct"] is not None else -999, reverse=True)
    return result


@app.get("/dashboard/growth")
def dashboard_growth(token: Optional[str] = Depends(optional_token)) -> list[dict[str, Any]]:
    """Growth comparison endpoint, scoped to the authenticated user."""
    return _compute_growth(_get_influencers(token))


@app.post("/dashboard/ai-analysis")
def dashboard_ai_analysis(token: Optional[str] = Depends(optional_token)) -> dict[str, Any]:
    """AI strategic analysis of the user's influencer data."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY manquant dans .env")

    influencers = _get_influencers(token)
    if not influencers:
        raise HTTPException(status_code=400, detail="Aucun influenceur analysé.")

    inf_summaries = []
    for inf in influencers:
        s = inf["stats"].get("engagement", {})
        p = inf["profile"]
        pats = inf["patterns"]
        inf_summaries.append({
            "name": p.get("name", inf["handle"]) or inf["handle"],
            "handle": inf["handle"],
            "followers": p.get("follower_count", 0) or 0,
            "posts_count": inf["stats"].get("count", 0),
            "posts_per_week": inf["stats"].get("posts_per_week"),
            "mean_engagement": round(s.get("mean_engagement", 0), 1),
            "median_engagement": s.get("median_engagement", 0),
            "mean_likes": round(s.get("mean_likes", 0), 1),
            "mean_comments": round(s.get("mean_comments", 0), 1),
            "median_comments": s.get("median_comments", 0),
            "engagement_rate_pct": s.get("engagement_rate_pct", 0),
            "format_mix": inf["stats"].get("format_mix_pct", {}),
            "hook_distribution": pats.get("hook_distribution", {}),
            "cta_share_pct": pats.get("cta_share_pct", 0),
            "length_distribution": pats.get("length_distribution", {}),
            "weekday_distribution": inf["stats"].get("weekday_distribution", {}),
        })

    # Also include growth data
    growth_data = None
    try:
        growth_data = _compute_growth(influencers)
    except Exception:
        pass

    try:
        analysis_md = analyze_dashboard_strategy(inf_summaries, growth_data)
        return {"markdown": analysis_md}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class IdeasRequest(BaseModel):
    count: int = Field(default=5, ge=1, le=10)


class GenerateRequest(BaseModel):
    topic: str = Field(..., min_length=3)


@app.post("/ideas")
def ideas(payload: IdeasRequest, token: Optional[str] = Depends(optional_token)) -> dict[str, Any]:
    """Generate post ideas from the user's influencer insights."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY manquant dans .env")

    influencers = _get_influencers(token)
    if not influencers:
        raise HTTPException(status_code=400, detail="Aucun influenceur analysé. Lance d'abord une analyse.")

    top_posts, benchmark = _build_benchmark(influencers)
    ideas_list = generate_ideas(top_posts, benchmark, count=payload.count)
    save_error: str | None = None
    if token:
        try:
            ideas_list = db.save_ideas(token, ideas_list)
        except Exception as exc:
            save_error = str(exc)
    return {"ideas": ideas_list, "influencer_count": len(influencers), "save_error": save_error}


@app.post("/generate")
def generate(payload: GenerateRequest, token: Optional[str] = Depends(optional_token)) -> dict[str, Any]:
    """Generate optimized post variants for a given topic."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY manquant dans .env")

    influencers = _get_influencers(token)
    if not influencers:
        raise HTTPException(status_code=400, detail="Aucun influenceur analysé. Lance d'abord une analyse.")

    top_posts, benchmark = _build_benchmark(influencers)
    variants = generate_posts(payload.topic.strip(), top_posts, benchmark)
    return {"variants": variants}


@app.post("/analyze")
def analyze(
    payload: AnalyzeRequest,
    token: Optional[str] = Depends(optional_token),
) -> dict[str, Any]:
    if not os.environ.get("APIFY_TOKEN"):
        raise HTTPException(status_code=400, detail="APIFY_TOKEN manquant dans .env")
    if payload.run_llm and not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY manquant dans .env")

    try:
        result = run_analysis(
            payload.profile_url.strip(),
            limit=payload.limit,
            no_cache=not payload.use_cache,
            with_llm=payload.run_llm,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Persist to the database when an authenticated user is making the request.
    if token and db.supabase_enabled():
        try:
            saved = db.save_analysis(token, result, posts_limit=payload.limit)
            if saved:
                result["saved"] = saved
            else:
                result["save_error"] = "Sauvegarde Supabase échouée (session invalide ou RLS)."
        except Exception as exc:
            # Persistence is best-effort: never fail the analysis on a DB error,
            # but surface the reason so the client can warn the user.
            result["save_error"] = f"Sauvegarde Supabase échouée : {exc}"
    elif not db.supabase_enabled():
        result["save_error"] = "Supabase non configuré sur le serveur (SUPABASE_URL / SUPABASE_ANON_KEY)."
    else:
        result["save_error"] = "Aucune session utilisateur : analyse non sauvegardée."

    return result


class JobRequest(BaseModel):
    profile_urls: list[str] = Field(..., min_length=1, max_length=25)
    limit: int = Field(default=25, ge=10, le=50)
    use_cache: bool = True
    run_llm: bool = True


def _clean_urls(raw: list[str]) -> list[str]:
    """Filtre les URLs LinkedIn valides et déduplique (insensible à la casse/slash)."""
    import re
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        url = (item or "").strip()
        if not url or not re.search(r"linkedin\.com/in/", url, re.IGNORECASE):
            continue
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(url)
    return out


@app.post("/jobs")
def create_job(payload: JobRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Crée une série d'analyses (backlog) traitée en fond, profil par profil."""
    if not os.environ.get("APIFY_TOKEN"):
        raise HTTPException(status_code=400, detail="APIFY_TOKEN manquant dans .env")
    if payload.run_llm and not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY manquant dans .env")

    urls = _clean_urls(payload.profile_urls)
    if not urls:
        raise HTTPException(status_code=400, detail="Aucune URL de profil LinkedIn valide.")

    try:
        job = db.create_job(token, urls, payload.limit, payload.run_llm, payload.use_cache)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Création de la série échouée (table analysis_jobs en place ?) : {exc}",
        ) from exc
    if not job:
        raise HTTPException(status_code=500, detail="Création de la série échouée.")

    start_job_thread(token, job["id"])
    return job


@app.get("/jobs")
def list_jobs(token: str = Depends(require_token)) -> list[dict[str, Any]]:
    """Liste les séries de l'utilisateur (la plus récente en premier), avec items."""
    mark_stale_jobs(token)
    return db.list_jobs(token)


@app.get("/jobs/{job_id}")
def get_job(job_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """État d'une série + statut de chaque profil (pour le polling frontend)."""
    mark_stale_jobs(token)
    job = db.get_job(token, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Série introuvable.")
    return job


@app.post("/jobs/{job_id}/resume")
def resume_job(job_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Relance le traitement des profils non terminés (après un redémarrage serveur)."""
    job = resume_job_worker(token, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Série introuvable.")
    return job


@app.post("/jobs/{job_id}/cancel")
def cancel_job_endpoint(job_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Annule une série. L'appel externe déjà en vol ne peut pas toujours être interrompu."""
    job = cancel_job(token, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Série introuvable.")
    return job


@app.post("/jobs/{job_id}/items/{item_id}/cancel")
def cancel_job_item_endpoint(job_id: str, item_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Annule un item de série si son traitement n'est pas déjà terminé."""
    job = cancel_item(token, job_id, item_id)
    if not job:
        raise HTTPException(status_code=404, detail="Profil introuvable dans cette série.")
    return job


@app.post("/jobs/{job_id}/items/{item_id}/resume")
def resume_job_item_endpoint(job_id: str, item_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Relance un profil échoué/annulé."""
    job = resume_job_worker(token, job_id, item_id=item_id)
    if not job:
        raise HTTPException(status_code=404, detail="Profil introuvable dans cette série.")
    return job


@app.post("/analyses/persist")
def persist_analysis(
    result: dict[str, Any],
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Persist an already-computed analysis result for the authenticated user.

    Used by the freemium flow: a visitor runs an anonymous analysis (full result
    returned but not saved), then signs up. The client replays the in-memory
    result here so it lands in the new account's history — no recompute, no cost.
    """
    if not result.get("handle"):
        raise HTTPException(status_code=400, detail="Résultat d'analyse invalide (handle manquant).")

    posts_limit = (result.get("stats") or {}).get("count")
    try:
        saved = db.save_analysis(token, result, posts_limit=posts_limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Sauvegarde échouée : {exc}") from exc
    if not saved:
        raise HTTPException(status_code=500, detail="Sauvegarde échouée (session invalide ou RLS).")
    return {"saved": saved}
