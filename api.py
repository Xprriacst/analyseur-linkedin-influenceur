from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from src import db, slack as slack_client, zernio
from src.benchmark import build_benchmark, enrich_influencers
from src.pipeline import run_analysis
from src import jobs as jobs_module
from src.jobs import start_job_thread
from src.llm import generate_ideas, generate_posts, analyze_dashboard_strategy, draft_editorial_profile, chat_stream
from src.normalize import normalize_posts, normalize_profile
from src.patterns import analyze_patterns
from src.scraper import fetch_posts, fetch_profile
from src.stats import compute_stats
from src.instagram_hooks import select_hooks
from src.daily_ideas import _render_idea_markdown

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


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Renvoyer une réponse JSON 500 *qui repasse par le CORSMiddleware*.

    Sans ça, une exception non gérée est interceptée par le ServerErrorMiddleware
    de Starlette (en dehors du CORSMiddleware) : la 500 sort sans en-tête CORS, et
    le navigateur affiche « Failed to fetch » au lieu du vrai message. Les
    `HTTPException` gardent leur handler dédié (non concernées ici).
    """
    import logging
    import traceback

    logging.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc)
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": "Erreur interne du serveur."})


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


class EditorialProfileRequest(BaseModel):
    display_name: str | None = None
    brand_name: str | None = None
    industry: str | None = None
    business_description: str | None = None
    location: str | None = None
    target_audience: str | None = None
    core_offer: str | None = None
    tone: str | None = None
    linkedin_objective: str | None = None
    topics_to_cover: str | None = None
    topics_to_avoid: str | None = None
    constraints: str | None = None
    website_url: str | None = None
    linkedin_url: str | None = None
    language: str | None = "francais"
    market: str | None = None
    extra_context: str | None = None


class EditorialProfileDraftRequest(BaseModel):
    activity_description: str | None = Field(default=None, max_length=5000)
    linkedin_url: str | None = Field(default=None, max_length=500)
    website_url: str | None = Field(default=None, max_length=500)
    use_apify_linkedin: bool = False


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "apify": bool(os.environ.get("APIFY_TOKEN")),
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "model": os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7"),
        "supabase": db.supabase_enabled(),
        "service_role": db.admin_enabled(),
    }


@app.get("/me/influencers")
def me_influencers(token: str = Depends(require_token)) -> list[dict[str, Any]]:
    """List the authenticated user's analyzed influencers."""
    return db.list_influencers(token)


@app.get("/me/influencers/library")
def me_influencer_library(token: str = Depends(require_token)) -> list[dict[str, Any]]:
    """All analyzed influencers with current analysis metadata (no markdown)."""
    return db.list_influencer_library(token)


@app.get("/me/analyses")
def me_analyses(
    limit: int = 100,
    token: str = Depends(require_token),
) -> list[dict[str, Any]]:
    """List the authenticated user's current analyses (one per influencer)."""
    return db.list_analyses(token, limit=max(1, min(limit, 500)))


@app.get("/me/profile")
def me_profile(token: str = Depends(require_token)) -> dict[str, Any]:
    """Editorial/business profile used as AI context for generation."""
    return db.get_editorial_profile(token) or {}


@app.put("/me/profile")
def update_me_profile(
    payload: EditorialProfileRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Create or update the user's editorial/business profile."""
    profile = db.upsert_editorial_profile(token, payload.model_dump())
    if not profile:
        raise HTTPException(status_code=500, detail="Sauvegarde du profil impossible.")
    return profile


def _clean_html_text(html: str) -> str:
    """Extract a compact text summary from public HTML without adding dependencies."""
    import html as html_lib
    import re

    text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
    title = ""
    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", text)
    if title_match:
        title = html_lib.unescape(re.sub(r"\s+", " ", title_match.group(1))).strip()

    meta = ""
    meta_match = re.search(
        r'(?is)<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\']([^"\']+)["\']',
        text,
    )
    if meta_match:
        meta = html_lib.unescape(meta_match.group(1)).strip()

    headings = [
        html_lib.unescape(re.sub(r"<[^>]+>", " ", m)).strip()
        for m in re.findall(r"(?is)<h[1-3][^>]*>(.*?)</h[1-3]>", text)[:8]
    ]
    body = html_lib.unescape(re.sub(r"<[^>]+>", " ", text))
    body = re.sub(r"\s+", " ", body).strip()
    parts = [p for p in [title, meta, " | ".join(h for h in headings if h), body[:2500]] if p]
    return "\n".join(parts)[:3500]


def _fetch_website_summary(url: str | None) -> dict[str, Any] | None:
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    try:
        import ipaddress
        import socket
        from urllib.parse import urlparse
        from urllib.request import Request, urlopen

        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return {"url": url, "error": "URL invalide"}
        if hostname in {"localhost"} or hostname.endswith(".local"):
            return {"url": url, "error": "Hôte local refusé"}
        for addr in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(addr[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return {"url": url, "error": "Adresse privée refusée"}

        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=8) as resp:
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type:
                return {"url": url, "error": f"Contenu non HTML ({content_type})"}
            raw = resp.read(250_000)
        html = raw.decode("utf-8", errors="ignore")
        summary = _clean_html_text(html)
        return {"url": url, "summary": summary} if summary else {"url": url, "error": "Aucun contenu texte lisible"}
    except Exception as exc:
        return {"url": url, "error": str(exc)}


def _fetch_linkedin_apify_seed(linkedin_url: str, limit: int = 10) -> dict[str, Any] | None:
    """Fetch LinkedIn profile + recent posts with Apify for profile drafting only."""
    raw_profile = fetch_profile(linkedin_url, use_cache=True)
    raw_posts = fetch_posts(linkedin_url, limit=limit, use_cache=True)
    profile = normalize_profile(raw_profile)
    posts = normalize_posts(raw_posts)
    return {
        "profile": profile,
        "top_posts": [
            {
                "text": (post.get("text") or "")[:900],
                "format": post.get("format"),
                "engagement": post.get("engagement", 0),
                "likes": post.get("likes", 0),
                "comments": post.get("comments", 0),
                "reposts": post.get("reposts", 0),
            }
            for post in sorted(posts, key=lambda p: p.get("engagement", 0), reverse=True)[:6]
            if post.get("text")
        ],
    } if profile or posts else None


@app.post("/me/profile/draft")
def draft_me_profile(
    payload: EditorialProfileDraftRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Draft an editorial profile from a description, analyzed LinkedIn profile, or website."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY manquant dans .env")

    activity = (payload.activity_description or "").strip()
    linkedin_url = (payload.linkedin_url or "").strip()
    website_url = (payload.website_url or "").strip()
    if not activity and not linkedin_url and not website_url:
        raise HTTPException(status_code=400, detail="Ajoute une description, une URL LinkedIn ou un site web.")
    if payload.use_apify_linkedin and not linkedin_url:
        raise HTTPException(status_code=400, detail="Ajoute une URL LinkedIn pour utiliser Apify.")
    if payload.use_apify_linkedin and not os.environ.get("APIFY_TOKEN"):
        raise HTTPException(status_code=400, detail="APIFY_TOKEN manquant dans .env")

    linkedin_seed = db.get_linkedin_profile_seed(token, linkedin_url) if linkedin_url else None
    linkedin_apify_seed = None
    if payload.use_apify_linkedin and linkedin_url:
        try:
            linkedin_apify_seed = _fetch_linkedin_apify_seed(linkedin_url)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Lecture LinkedIn via Apify impossible : {exc}") from exc
    website_seed = _fetch_website_summary(website_url) if website_url else None
    existing_profile = db.get_editorial_profile(token) or {}
    seed = {
        "activity_description": activity,
        "linkedin_url": linkedin_url,
        "website_url": website_url,
        "linkedin_analyzed_profile": linkedin_seed,
        "linkedin_apify_profile": linkedin_apify_seed,
        "website_public_summary": website_seed,
    }
    try:
        profile = draft_editorial_profile(seed, existing_profile=existing_profile)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pré-remplissage IA impossible : {exc}") from exc

    if linkedin_url and not profile.get("linkedin_url"):
        profile["linkedin_url"] = linkedin_url
    if website_url and not profile.get("website_url"):
        profile["website_url"] = website_url
    return {
        "profile": profile,
        "sources": {
            "description": bool(activity),
            "linkedin_analyzed": bool(linkedin_seed),
            "linkedin_apify": bool(linkedin_apify_seed),
            "website_summary": bool(website_seed and website_seed.get("summary")),
        },
    }


@app.get("/me/analyses/{analysis_id}")
def me_analysis(analysis_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Fetch a single stored analysis (report + computed data)."""
    analysis = db.get_analysis(token, analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analyse introuvable.")
    return analysis


# --- LinkedIn publishing via Zernio -----------------------------------------

class LinkedInConnectRequest(BaseModel):
    redirect_url: Optional[str] = Field(default=None, max_length=1000)


class LinkedInImageRequest(BaseModel):
    url: Optional[str] = Field(default=None, description="Public image URL or data:image/... base64 URL.")
    data_url: Optional[str] = Field(default=None, description="Uploaded/generated image as a data:image/... base64 URL.")
    filename: Optional[str] = Field(default=None, max_length=200)
    title: Optional[str] = Field(default=None, max_length=200)


class LinkedInPublishRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=8000)
    draft: bool = False
    images: list[LinkedInImageRequest] = Field(default_factory=list, max_length=zernio.MAX_LINKEDIN_IMAGES)


def _image_payload(images: list[LinkedInImageRequest]) -> list[dict[str, Any]]:
    return [image.model_dump(exclude_none=True) for image in images]


def _linkedin_status(token: str) -> dict[str, Any]:
    profile = db.get_editorial_profile(token) or {}
    return {
        "configured": zernio.enabled(),
        "connected": bool(profile.get("zernio_account_id")),
        "account_id": profile.get("zernio_account_id"),
        "profile_id": profile.get("zernio_profile_id"),
        "connected_at": profile.get("zernio_connected_at"),
    }


def _ensure_zernio_profile(token: str) -> str:
    """Return this user's Zernio profile id, creating it on first use."""
    profile = db.get_editorial_profile(token) or {}
    profile_id = profile.get("zernio_profile_id")
    if profile_id:
        return profile_id
    user = db.get_user(token) or {}
    name = profile.get("display_name") or profile.get("brand_name") or user.get("email") or "Client"
    profile_id = zernio.create_profile(name, profile.get("business_description"))
    db.set_zernio_profile_id(token, profile_id)
    return profile_id


@app.get("/me/linkedin/status")
def me_linkedin_status(token: str = Depends(require_token)) -> dict[str, Any]:
    """Whether the user has a LinkedIn account connected through Zernio."""
    return _linkedin_status(token)


@app.post("/me/linkedin/connect")
def me_linkedin_connect(
    payload: LinkedInConnectRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Return a LinkedIn OAuth URL the user opens to authorize publishing."""
    if not zernio.enabled():
        raise HTTPException(status_code=400, detail="ZERNIO_API_KEY manquant côté serveur.")
    try:
        profile_id = _ensure_zernio_profile(token)
        auth_url = zernio.get_connect_url(profile_id, redirect_url=payload.redirect_url)
    except zernio.ZernioError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"auth_url": auth_url}


@app.post("/me/linkedin/refresh")
def me_linkedin_refresh(token: str = Depends(require_token)) -> dict[str, Any]:
    """Re-read the connected account from Zernio (call after OAuth return)."""
    if not zernio.enabled():
        raise HTTPException(status_code=400, detail="ZERNIO_API_KEY manquant côté serveur.")
    profile = db.get_editorial_profile(token) or {}
    profile_id = profile.get("zernio_profile_id")
    if not profile_id:
        return _linkedin_status(token)
    try:
        account_id = zernio.find_linkedin_account_id(profile_id)
    except zernio.ZernioError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    db.set_zernio_account(token, account_id)
    return _linkedin_status(token)


@app.post("/me/linkedin/publish")
def me_linkedin_publish(
    payload: LinkedInPublishRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Publish or save a post draft on the user's connected LinkedIn account."""
    if not zernio.enabled():
        raise HTTPException(status_code=400, detail="ZERNIO_API_KEY manquant côté serveur.")
    profile = db.get_editorial_profile(token) or {}
    account_id = profile.get("zernio_account_id")
    if not account_id:
        raise HTTPException(status_code=400, detail="Aucun compte LinkedIn connecté. Connecte-le d'abord.")
    try:
        media_items = zernio.prepare_image_media_items(_image_payload(payload.images))
        result = zernio.create_post(
            payload.content.strip(),
            account_id,
            publish_now=True,
            is_draft=payload.draft,
            media_items=media_items,
        )
    except zernio.ZernioError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    post = result.get("post") or result
    return {"ok": True, "post_id": post.get("_id"), "post": post, "draft": payload.draft, "media_count": len(payload.images)}


# ── ALE-96 : Planification LinkedIn ──────────────────────────────────────────

class LinkedInScheduleRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=8000)
    scheduled_at: str = Field(..., description="ISO 8601 datetime (ex. 2026-06-22T09:00:00+02:00)")
    images: list[LinkedInImageRequest] = Field(default_factory=list, max_length=zernio.MAX_LINKEDIN_IMAGES)
    # ALE-137 : True = passer par une validation Slack avant publication ;
    # False = programmation directe (publiée à l'échéance sans validation).
    validate_via_slack: bool = True


class LinkedInScheduledPostUpdateRequest(BaseModel):
    post_text: str | None = Field(None, min_length=1, max_length=8000)
    scheduled_at: str | None = Field(None, description="ISO 8601 datetime (ex. 2026-06-22T09:00:00+02:00)")


def _validate_future_scheduled_at(scheduled_at: str) -> None:
    try:
        parsed = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Format de date invalide. Utilise ISO 8601 (ex. 2026-06-22T09:00:00+02:00).")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="La date de programmation doit être dans le futur.")


@app.post("/me/linkedin/schedule")
def me_linkedin_schedule(
    payload: LinkedInScheduleRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Store a LinkedIn post and request Slack validation before future publication."""
    if not zernio.enabled():
        raise HTTPException(status_code=400, detail="ZERNIO_API_KEY manquant côté serveur.")
    profile = db.get_editorial_profile(token) or {}
    if not profile.get("zernio_account_id"):
        raise HTTPException(status_code=400, detail="Aucun compte LinkedIn connecté. Connecte-le d'abord.")
    _validate_future_scheduled_at(payload.scheduled_at)

    # ALE-137 — Option A : programmation directe, publiée à l'échéance sans
    # validation Slack (le post naît `validated` pour que le cron le publie).
    if not payload.validate_via_slack:
        row = db.create_scheduled_post(
            token,
            payload.content.strip(),
            payload.scheduled_at,
            media_items=_image_payload(payload.images),
            require_slack=False,
        )
        if row is None:
            raise HTTPException(status_code=500, detail="Impossible d'enregistrer le post planifié.")
        return {"ok": True, "scheduled_post": row}

    # Option B : validation Slack avant publication (comportement existant).
    slack_row = db.get_slack_integration(token)
    if not slack_row:
        raise HTTPException(status_code=400, detail="Connecte Slack dans ton profil pour valider les posts programmés.")
    channel_id: str = slack_row.get("channel_id") or ""
    bot_token: str = slack_row.get("access_token") or ""
    if not channel_id or not bot_token:
        raise HTTPException(status_code=400, detail="Intégration Slack incomplète (channel ou token manquant).")

    row = db.create_scheduled_post(
        token,
        payload.content.strip(),
        payload.scheduled_at,
        media_items=_image_payload(payload.images),
    )
    if row is None:
        raise HTTPException(status_code=500, detail="Impossible d'enregistrer le post planifié.")
    try:
        message_ts = slack_client.send_scheduled_post_for_validation(bot_token, channel_id, row)
    except slack_client.SlackError as exc:
        db.mark_scheduled_post_slack_error(token, row["id"], str(exc))
        raise HTTPException(status_code=502, detail=f"Programmation enregistrée, mais demande Slack impossible : {exc}") from exc
    row = db.set_scheduled_post_slack_message(token, row["id"], message_ts) or {
        **row,
        "slack_message_ts": message_ts,
    }
    return {"ok": True, "scheduled_post": row}


@app.get("/me/linkedin/scheduled")
def me_linkedin_scheduled_list(
    limit: int = 50,
    token: str = Depends(require_token),
) -> list[dict[str, Any]]:
    """List the authenticated user's scheduled LinkedIn posts."""
    return db.list_scheduled_posts(token, limit=limit)


@app.delete("/me/linkedin/scheduled/{post_id}")
def me_linkedin_scheduled_cancel(
    post_id: str,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Cancel a pending scheduled post."""
    ok = db.cancel_scheduled_post(token, post_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Post planifié introuvable ou déjà publié.")
    return {"ok": True}


# ── ALE-108 : Publication X (Twitter) via Zernio ──────────────────────────────

class XConnectRequest(BaseModel):
    redirect_url: str | None = None


class XPublishRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=8000)
    draft: bool = False


def _x_status(token: str) -> dict[str, Any]:
    profile = db.get_editorial_profile(token) or {}
    return {
        "configured": zernio.enabled(),
        "connected": bool(profile.get("zernio_x_account_id")),
        "account_id": profile.get("zernio_x_account_id"),
        "profile_id": profile.get("zernio_profile_id"),
        "connected_at": profile.get("zernio_x_connected_at"),
    }


@app.get("/me/x/status")
def me_x_status(token: str = Depends(require_token)) -> dict[str, Any]:
    """Whether the user has an X (Twitter) account connected through Zernio."""
    return _x_status(token)


@app.post("/me/x/connect")
def me_x_connect(
    payload: XConnectRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Return an X OAuth URL the user opens to authorize publishing."""
    if not zernio.enabled():
        raise HTTPException(status_code=400, detail="ZERNIO_API_KEY manquant côté serveur.")
    try:
        profile_id = _ensure_zernio_profile(token)
        auth_url = zernio.get_connect_url(profile_id, redirect_url=payload.redirect_url, platform="x")
    except zernio.ZernioError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"auth_url": auth_url}


@app.post("/me/x/refresh")
def me_x_refresh(token: str = Depends(require_token)) -> dict[str, Any]:
    """Re-read the connected X account from Zernio (call after OAuth return)."""
    if not zernio.enabled():
        raise HTTPException(status_code=400, detail="ZERNIO_API_KEY manquant côté serveur.")
    profile = db.get_editorial_profile(token) or {}
    profile_id = profile.get("zernio_profile_id")
    if not profile_id:
        return _x_status(token)
    try:
        account_id = zernio.find_account_id(profile_id, platform="x")
    except zernio.ZernioError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    db.set_zernio_x_account(token, account_id)
    return _x_status(token)


@app.post("/me/x/publish")
def me_x_publish(
    payload: XPublishRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Publish a post immediately on the user's connected X (Twitter) account."""
    if not zernio.enabled():
        raise HTTPException(status_code=400, detail="ZERNIO_API_KEY manquant côté serveur.")
    profile = db.get_editorial_profile(token) or {}
    account_id = profile.get("zernio_x_account_id")
    if not account_id:
        raise HTTPException(status_code=400, detail="Aucun compte X connecté. Connecte-le d'abord dans l'onglet Profil.")
    try:
        result = zernio.create_post(
            payload.content.strip(), account_id, publish_now=True, is_draft=payload.draft, platform="x"
        )
    except zernio.ZernioError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    post = result.get("post") or result
    return {"ok": True, "post_id": post.get("_id"), "post": post, "draft": payload.draft}


@app.patch("/me/linkedin/scheduled/{post_id}")
def me_linkedin_scheduled_update(
    post_id: str,
    payload: LinkedInScheduledPostUpdateRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Edit a pending scheduled LinkedIn post."""
    if payload.post_text is None and payload.scheduled_at is None:
        raise HTTPException(status_code=400, detail="Indique au moins un champ à modifier.")

    post_text: str | None = None
    if payload.post_text is not None:
        post_text = payload.post_text.strip()
        if not post_text:
            raise HTTPException(status_code=400, detail="Le texte du post ne peut pas être vide.")

    if payload.scheduled_at is not None:
        _validate_future_scheduled_at(payload.scheduled_at)

    row = db.update_scheduled_post(
        token,
        post_id,
        post_text=post_text,
        scheduled_at_iso=payload.scheduled_at,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Post planifié introuvable ou non éditable.")
    return {"ok": True, "scheduled_post": row}


@app.get("/reports")
def reports(
    limit: int = 3,
    token: Optional[str] = Depends(optional_token),
) -> list[dict[str, Any]]:
    """Recent analysis reports, scoped to the authenticated user.

    Supabase-backed in production; falls back to the local reports/ folder
    only when Supabase is not configured (single-user dev mode).
    """
    safe_limit = max(1, min(limit, 100))
    if db.supabase_enabled():
        if not token or not db.get_user(token):
            raise HTTPException(status_code=401, detail="Authentification requise.")
        return db.list_reports(token, limit=safe_limit)

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
        for path in files[:safe_limit]
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
    return enrich_influencers(corpus)


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
    return build_benchmark(influencers)


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


@app.get("/dashboard/progress")
def dashboard_progress(token: str = Depends(require_token)) -> dict[str, Any]:
    """Aggregated progression dashboard for the authenticated user."""
    profile = db.get_editorial_profile(token) or {}
    credits_info = db.get_user_credits(token)
    influencers = db.list_influencers(token) or []
    analyses = db.list_analyses(token, limit=100) or []
    generated_posts = db.list_generated_posts(token, limit=500) or []
    generated_ideas = db.list_generated_ideas(token, limit=500) or []
    jobs = db.list_jobs(token, limit=100) or []

    last_analysis_at = None
    if analyses:
        ts = analyses[0].get("created_at") or analyses[0].get("updated_at")
        last_analysis_at = ts

    active_jobs = [j for j in jobs if j.get("status") in ("pending", "running")]
    done_jobs = [j for j in jobs if j.get("status") == "done"]

    return {
        "corpus": {
            "influencer_count": len(influencers),
            "analysis_count": len(analyses),
            "last_analysis_at": last_analysis_at,
            "active_jobs": len(active_jobs),
            "done_jobs": len(done_jobs),
        },
        "content": {
            "ideas_count": len(generated_ideas),
            "posts_count": len(generated_posts),
        },
        "publishing": {
            "linkedin_connected": bool(profile.get("zernio_account_id")),
            "slack_connected": bool(profile.get("slack_bot_token") or profile.get("slack_channel_id")),
        },
        "profile": {
            "filled": bool(
                profile.get("display_name") or profile.get("brand_name") or profile.get("business_description")
            ),
            "has_linkedin_url": bool(profile.get("linkedin_url")),
        },
        "credits": {
            "balance": credits_info.get("balance", 0),
        },
        "next_action": _suggest_next_action(profile, influencers, generated_posts, generated_ideas),
    }


def _suggest_next_action(
    profile: dict,
    influencers: list,
    posts: list,
    ideas: list,
) -> str:
    if not profile.get("display_name") and not profile.get("business_description"):
        return "Remplis ton profil éditorial pour personnaliser les générations."
    if not influencers:
        return "Analyse un premier influenceur LinkedIn pour construire ton benchmark."
    if not ideas and not posts:
        return "Génère tes premières idées de posts à partir de ton benchmark."
    if posts and not profile.get("zernio_account_id"):
        return "Connecte ton compte LinkedIn pour publier tes posts générés en un clic."
    if ideas and not posts:
        return "Transforme une idée en post complet via le Générateur."
    return "Tout est en place — génère et publie !"


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
    web_search: bool = Field(default=False)


class GenerateRequest(BaseModel):
    topic: Optional[str] = Field(default=None)
    editorial_role: Optional[str] = Field(default=None)
    # Deprecated client hint kept for backward compatibility. Post generation now
    # exposes web search as an autonomous server-side tool; the model decides.
    web_search: bool = Field(default=False)
    count: int = Field(default=1, ge=1, le=3)


class GenerateImageRequest(BaseModel):
    post_text: str = Field(..., min_length=10)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=12000)
    conversation_id: Optional[str] = None


@app.post("/ideas")
def ideas(payload: IdeasRequest, token: Optional[str] = Depends(optional_token)) -> dict[str, Any]:
    """Generate post ideas from the user's influencer insights."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY manquant dans .env")

    influencers = _get_influencers(token)
    if not influencers:
        raise HTTPException(status_code=400, detail="Aucun influenceur analysé. Lance d'abord une analyse.")

    # Débit après toutes les préconditions : un user sans influenceur ne perd pas de crédits.
    credits: int | None = None
    if token:
        ok, balance = db.debit_credits(token, "generate_ideas", payload.count)
        if not ok:
            cost = db.CREDIT_COSTS["generate_ideas"] * payload.count
            raise HTTPException(status_code=402, detail=f"Crédits insuffisants (solde : {balance}). Génération de {payload.count} idée(s) = {cost} crédit(s).")
        credits = balance

    top_posts, benchmark = _build_benchmark(influencers)
    user_context = db.get_user_ai_context(token)
    ideas_list = generate_ideas(top_posts, benchmark, count=payload.count, user_context=user_context, web_search=payload.web_search)
    save_error: str | None = None
    if token:
        try:
            ideas_list = db.save_ideas(token, ideas_list)
        except Exception as exc:
            save_error = str(exc)
    return {"ideas": ideas_list, "influencer_count": len(influencers), "save_error": save_error, "credits": credits}


@app.post("/generate")
def generate(payload: GenerateRequest, token: Optional[str] = Depends(optional_token)) -> dict[str, Any]:
    """Generate optimized post variants for a given topic."""
    web_searches: list[dict[str, Any]] = []
    response = _generate_posts_response(payload, token, on_web_search=web_searches.append)
    response["web_search"] = {
        "used": bool(web_searches),
        "queries": web_searches,
    }
    return response


def _prepare_generate_context(payload: GenerateRequest, token: Optional[str]) -> dict[str, Any]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY manquant dans .env")

    influencers = _get_influencers(token)
    if not influencers:
        raise HTTPException(status_code=400, detail="Aucun influenceur analysé. Lance d'abord une analyse.")

    # Débit après toutes les préconditions : un user sans influenceur ne perd pas de crédits.
    credits: int | None = None
    if token:
        ok, balance = db.debit_credits(token, "generate_post", payload.count)
        if not ok:
            cost = db.CREDIT_COSTS["generate_post"] * payload.count
            raise HTTPException(status_code=402, detail=f"Crédits insuffisants (solde : {balance}). Génération de {payload.count} post(s) = {cost} crédit(s).")
        credits = balance

    top_posts, benchmark = _build_benchmark(influencers)
    user_context = db.get_user_ai_context(token)
    role = (payload.editorial_role or "").strip() or None
    topic = (payload.topic or "").strip()
    return {
        "top_posts": top_posts,
        "benchmark": benchmark,
        "user_context": user_context,
        "role": role,
        "topic": topic,
        "credits": credits,
    }


def _save_generated_variants(token: Optional[str], topic: str, variants: list[dict]) -> tuple[list[dict], str | None]:
    save_error: str | None = None
    if token:
        try:
            variants = db.save_generated_posts(token, topic, variants)
        except Exception as exc:
            save_error = str(exc)
    return variants, save_error


def _generate_posts_response(
    payload: GenerateRequest,
    token: Optional[str],
    on_web_search=None,
) -> dict[str, Any]:
    context = _prepare_generate_context(payload, token)
    variants = generate_posts(
        context["topic"],
        context["top_posts"],
        context["benchmark"],
        user_context=context["user_context"],
        editorial_role=context["role"],
        count=payload.count,
        on_web_search=on_web_search,
    )
    variants, save_error = _save_generated_variants(token, context["topic"], variants)
    return {"variants": variants, "save_error": save_error, "credits": context["credits"]}


@app.post("/generate/stream")
def generate_stream(payload: GenerateRequest, token: Optional[str] = Depends(optional_token)) -> StreamingResponse:
    """Generate posts as SSE and report autonomous web-search starts live."""
    context = _prepare_generate_context(payload, token)

    def stream_response():
        import queue
        import threading

        events: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()
        web_searches: list[dict[str, Any]] = []

        def on_web_search(event: dict[str, Any]) -> None:
            web_searches.append(event)
            events.put(("search", event))

        def worker() -> None:
            try:
                variants = generate_posts(
                    context["topic"],
                    context["top_posts"],
                    context["benchmark"],
                    user_context=context["user_context"],
                    editorial_role=context["role"],
                    count=payload.count,
                    on_web_search=on_web_search,
                )
                variants, save_error = _save_generated_variants(token, context["topic"], variants)
                events.put(("done", {
                    "variants": variants,
                    "save_error": save_error,
                    "credits": context["credits"],
                    "web_search": {
                        "used": bool(web_searches),
                        "queries": web_searches,
                    },
                }))
            except Exception as exc:
                events.put(("error", {"detail": str(exc)}))
            finally:
                events.put(None)

        yield _sse("meta", {"credits": context["credits"]})
        threading.Thread(target=worker, daemon=True).start()

        while True:
            item = events.get()
            if item is None:
                break
            event, data = item
            yield _sse(event, data)

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/me/generated-ideas")
def me_generated_ideas(
    limit: int = 100,
    token: str = Depends(require_token),
) -> list[dict[str, Any]]:
    """List the authenticated user's saved post ideas."""
    return db.list_generated_ideas(token, limit=max(1, min(limit, 500)))


@app.get("/me/generated-posts")
def me_generated_posts(
    limit: int = 100,
    token: str = Depends(require_token),
) -> list[dict[str, Any]]:
    """List the authenticated user's saved generated posts (ALE-135 : seulement les `saved`)."""
    return db.list_generated_posts(token, limit=max(1, min(limit, 500)), saved_only=True)


@app.delete("/me/generated-ideas/{idea_id}")
def delete_me_generated_idea(idea_id: str, token: str = Depends(require_token)) -> dict[str, bool]:
    """Delete one of the authenticated user's saved ideas."""
    return {"deleted": db.delete_generated_idea(token, idea_id)}


@app.delete("/me/generated-posts/{post_id}")
def delete_me_generated_post(post_id: str, token: str = Depends(require_token)) -> dict[str, bool]:
    """Delete one of the authenticated user's saved posts."""
    return {"deleted": db.delete_generated_post(token, post_id)}


class UpdatePostRequest(BaseModel):
    post: str | None = Field(default=None, min_length=1, max_length=50000)
    saved: bool | None = None


@app.put("/me/generated-posts/{post_id}")
def update_me_generated_post(post_id: str, payload: UpdatePostRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Update a saved post's text and/or its `saved` flag (ALE-134)."""
    if payload.post is None and payload.saved is None:
        raise HTTPException(status_code=400, detail="Rien à mettre à jour (post ou saved requis).")
    updated = db.update_generated_post(token, post_id, payload.post, payload.saved)
    if not updated:
        raise HTTPException(status_code=404, detail="Post introuvable ou non autorisé.")
    return updated


# --------------------------------------------------------------------------- #
# Crédits utilisateur (ALE-41)
# --------------------------------------------------------------------------- #

@app.get("/me/credits")
def me_credits(token: str = Depends(require_token)) -> dict[str, Any]:
    """Retourne le solde de crédits de l'utilisateur authentifié."""
    return db.get_user_credits(token)


# --------------------------------------------------------------------------- #
# Idée du jour — réservoir de seeds + idées générées + opt-in
# --------------------------------------------------------------------------- #

class IdeaSeedRequest(BaseModel):
    text: str = Field(..., min_length=3, max_length=2000)


class DailyIdeasEnabledRequest(BaseModel):
    enabled: bool


@app.get("/me/idea-seeds")
def me_idea_seeds(token: str = Depends(require_token)) -> list[dict[str, Any]]:
    """List the user's idea reservoir."""
    return db.list_idea_seeds(token)


@app.post("/me/idea-seeds")
def add_me_idea_seed(payload: IdeaSeedRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Add an idea to the user's reservoir."""
    seed = db.add_idea_seed(token, payload.text.strip())
    if not seed:
        raise HTTPException(status_code=400, detail="Impossible d'enregistrer l'idée.")
    return seed


@app.delete("/me/idea-seeds/{seed_id}")
def delete_me_idea_seed(seed_id: str, token: str = Depends(require_token)) -> dict[str, bool]:
    """Delete one of the user's seeds."""
    return {"deleted": db.delete_idea_seed(token, seed_id)}


@app.get("/me/daily-ideas")
def me_daily_ideas(
    limit: int = 30,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """List the user's generated daily ideas + opt-in state."""
    return {
        "ideas": db.list_daily_ideas(token, limit=max(1, min(limit, 90))),
        "enabled": db.get_daily_ideas_enabled(token),
    }


@app.post("/me/daily-ideas/enabled")
def set_me_daily_ideas_enabled(
    payload: DailyIdeasEnabledRequest,
    token: str = Depends(require_token),
) -> dict[str, bool]:
    """Toggle the daily-idea opt-in for the authenticated user."""
    db.set_daily_ideas_enabled(token, payload.enabled)
    return {"enabled": payload.enabled}


@app.post("/me/daily-ideas/regenerate")
def regenerate_daily_idea(token: str = Depends(require_token)) -> dict[str, Any]:
    """Regenerate today's daily idea on demand (costs 1 credit)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY manquant dans .env")

    influencers = _get_influencers(token)
    if not influencers:
        raise HTTPException(status_code=400, detail="Aucun influenceur analysé. Lance d'abord une analyse.")

    ok, balance = db.debit_credits(token, "generate_ideas", 1)
    if not ok:
        cost = db.CREDIT_COSTS["generate_ideas"]
        raise HTTPException(status_code=402, detail=f"Crédits insuffisants (solde : {balance}). Régénération = {cost} crédit(s).")

    top_posts, benchmark = _build_benchmark(influencers)
    user_context = db.get_user_ai_context(token)

    seed = db.get_unused_seed_by_token(token)
    seed_text = seed["text"] if seed else None

    import datetime as _dt
    today = _dt.date.today().isoformat()

    ideas = generate_ideas(top_posts, benchmark, count=1, user_context=user_context, seed_topic=seed_text)
    if not ideas:
        raise HTTPException(status_code=500, detail="La génération n'a produit aucune idée.")

    markdown = _render_idea_markdown(ideas[0], seed_text)
    idea_row = db.replace_daily_idea(token, markdown, today)

    if seed:
        db.mark_seed_used_by_token(token, seed["id"])

    return {
        "idea": idea_row or {"idea_markdown": markdown, "idea_date": today},
        "credits": balance,
    }


# --------------------------------------------------------------------------- #
# Slack integration (ALE-63) — validation d'idées par boutons Slack
# --------------------------------------------------------------------------- #

class SlackConnectRequest(BaseModel):
    redirect_uri: str = Field(..., min_length=10)


class SlackCallbackRequest(BaseModel):
    code: str = Field(..., min_length=4)
    redirect_uri: str = Field(..., min_length=10)


class SlackSendIdeasRequest(BaseModel):
    idea_ids: list[str] = Field(..., min_length=1, max_length=10)


class SlackSendPostsRequest(BaseModel):
    post_id: str = Field(..., min_length=1)


@app.get("/me/integrations/slack/status")
def slack_status(token: str = Depends(require_token)) -> dict[str, Any]:
    """Check whether the authenticated user has connected their Slack workspace."""
    row = db.get_slack_integration(token)
    if not row:
        return {"connected": False, "configured": slack_client.enabled()}
    return {
        "connected": True,
        "configured": slack_client.enabled(),
        "team_name": row.get("team_name"),
        "team_id": row.get("team_id"),
        "channel_id": row.get("channel_id"),
        "connected_at": row.get("connected_at"),
    }


@app.post("/me/integrations/slack/connect")
def slack_connect(
    payload: SlackConnectRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Return the Slack OAuth authorization URL to redirect the user to."""
    if not slack_client.enabled():
        raise HTTPException(status_code=400, detail="SLACK_CLIENT_ID / SLACK_CLIENT_SECRET manquants sur le serveur.")
    try:
        auth_url = slack_client.build_oauth_url(payload.redirect_uri)
    except slack_client.SlackError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"auth_url": auth_url}


@app.post("/me/integrations/slack/callback")
def slack_callback(
    payload: SlackCallbackRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Exchange an OAuth code for tokens and persist the Slack integration."""
    if not slack_client.enabled():
        raise HTTPException(status_code=400, detail="SLACK_CLIENT_ID / SLACK_CLIENT_SECRET manquants sur le serveur.")
    try:
        oauth = slack_client.exchange_code(payload.code, payload.redirect_uri)
    except slack_client.SlackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    bot_token: str = oauth.get("access_token", "")
    authed_user: dict = oauth.get("authed_user") or {}
    team: dict = oauth.get("team") or {}
    slack_user_id: str = authed_user.get("id", "")

    # Open a DM channel so we know where to post ideas
    channel_id: str | None = None
    if bot_token and slack_user_id:
        try:
            channel_id = slack_client.open_dm_channel(bot_token, slack_user_id)
        except slack_client.SlackError:
            pass  # non-blocking; the user can still connect

    row = db.save_slack_integration(token, {
        "access_token": bot_token,
        "service_user_id": slack_user_id,
        "channel_id": channel_id,
        "team_id": team.get("id"),
        "team_name": team.get("name"),
        "metadata": {"bot_user_id": oauth.get("bot_user_id")},
    })
    if not row:
        raise HTTPException(status_code=500, detail="Impossible de sauvegarder l'intégration Slack.")
    return {
        "ok": True,
        "team_name": team.get("name"),
        "channel_id": channel_id,
    }


@app.delete("/me/integrations/slack")
def slack_disconnect(token: str = Depends(require_token)) -> dict[str, bool]:
    """Remove the Slack integration for the authenticated user."""
    return {"deleted": db.delete_slack_integration(token)}


@app.post("/me/integrations/slack/send-ideas")
def slack_send_ideas(
    payload: SlackSendIdeasRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Send a batch of generated ideas to the user's Slack DM for validation."""
    row = db.get_slack_integration(token)
    if not row:
        raise HTTPException(status_code=400, detail="Compte Slack non connecté. Connecte Slack dans ton profil.")
    channel_id: str = row.get("channel_id") or ""
    bot_token: str = row.get("access_token") or ""
    if not channel_id or not bot_token:
        raise HTTPException(status_code=400, detail="Intégration Slack incomplète (channel ou token manquant).")

    sent = 0
    errors: list[str] = []
    for idea_id in payload.idea_ids:
        idea = db.get_generated_idea(token, idea_id)
        if not idea:
            errors.append(f"Idée {idea_id} introuvable.")
            continue
        try:
            slack_client.send_idea_for_validation(bot_token, channel_id, idea)
            sent += 1
        except slack_client.SlackError as exc:
            errors.append(str(exc))

    if sent:
        db.set_idea_slack_pending(token, payload.idea_ids)

    return {"sent": sent, "errors": errors}


@app.post("/me/integrations/slack/send-posts")
def slack_send_post(
    payload: SlackSendPostsRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Send a generated post to the user's Slack DM for validation (Option B)."""
    row = db.get_slack_integration(token)
    if not row:
        raise HTTPException(status_code=400, detail="Compte Slack non connecté. Connecte Slack dans ton profil.")
    channel_id: str = row.get("channel_id") or ""
    bot_token: str = row.get("access_token") or ""
    if not channel_id or not bot_token:
        raise HTTPException(status_code=400, detail="Intégration Slack incomplète (channel ou token manquant).")

    post = db.get_generated_post(token, payload.post_id)
    if not post:
        raise HTTPException(status_code=404, detail=f"Post {payload.post_id} introuvable.")

    try:
        slack_client.send_post_for_validation(bot_token, channel_id, post)
    except slack_client.SlackError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    db.set_post_slack_pending(token, [payload.post_id])
    return {"sent": True}


@app.post("/slack/webhooks/interactive")
async def slack_interactive_webhook(request: Request) -> dict[str, Any]:
    """Receive Slack interactive component payloads (button clicks).

    Verifies the Slack signing secret, then updates the idea status in DB.
    This endpoint has no user auth — it's called directly by Slack.
    """
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not slack_client.verify_signature(body, timestamp, signature):
        raise HTTPException(status_code=403, detail="Signature Slack invalide.")

    # Slack sends payload as URL-encoded form: payload=<JSON>
    import urllib.parse
    form = urllib.parse.parse_qs(body.decode("utf-8", errors="replace"))
    raw = form.get("payload", [""])[0]
    if not raw:
        raise HTTPException(status_code=400, detail="Payload Slack manquant.")
    try:
        data = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Payload Slack invalide (JSON).")

    if data.get("type") != "block_actions":
        return {"ok": True}

    actions: list[dict] = data.get("actions") or []
    slack_user_id: str = (data.get("user") or {}).get("id", "")

    if not actions or not slack_user_id:
        return {"ok": True}

    action = actions[0]
    action_id: str = action.get("action_id", "")
    item_id: str = action.get("value", "")

    if not item_id:
        return {"ok": True}

    # Lookup user by Slack user ID (service-role, no JWT available here)
    integration = db.get_user_by_slack_id(slack_user_id)

    if action_id in ("validate_idea", "decline_idea"):
        status = "validated" if action_id == "validate_idea" else "declined"
        if integration:
            db.update_idea_slack_status(item_id, integration["user_id"], status)
            bot_token_w: str = integration.get("access_token", "")
            channel_id_w: str = (data.get("channel") or {}).get("id", "")
            ts_w: str = (data.get("message") or {}).get("ts", "")
            if bot_token_w and channel_id_w and ts_w:
                try:
                    idea_blocks = (data.get("message") or {}).get("blocks") or []
                    title = ""
                    if idea_blocks and idea_blocks[0].get("text"):
                        title = idea_blocks[0]["text"].get("text", "").split("\n")[0].strip("*")
                    slack_client.update_idea_message(bot_token_w, channel_id_w, ts_w, {"id": item_id, "title": title}, status)
                except slack_client.SlackError:
                    pass

    elif action_id in ("validate_post", "reject_post"):
        status = "validated" if action_id == "validate_post" else "rejected"
        if integration:
            db.update_post_slack_status(item_id, integration["user_id"], status)
            bot_token_w = integration.get("access_token", "")
            channel_id_w = (data.get("channel") or {}).get("id", "")
            ts_w = (data.get("message") or {}).get("ts", "")
            if bot_token_w and channel_id_w and ts_w:
                try:
                    slack_client.update_post_message(bot_token_w, channel_id_w, ts_w, {"id": item_id}, status)
                except slack_client.SlackError:
                    pass

    elif action_id in ("validate_scheduled_post", "decline_scheduled_post"):
        status = "validated" if action_id == "validate_scheduled_post" else "declined"
        if integration:
            scheduled = db.get_scheduled_post_for_user(item_id, integration["user_id"]) or {"id": item_id}
            db.update_scheduled_post_slack_status(item_id, integration["user_id"], status)
            bot_token_w = integration.get("access_token", "")
            channel_id_w = (data.get("channel") or {}).get("id", "")
            ts_w = (data.get("message") or {}).get("ts", "")
            if bot_token_w and channel_id_w and ts_w:
                try:
                    slack_client.update_scheduled_post_message(bot_token_w, channel_id_w, ts_w, scheduled, status)
                except slack_client.SlackError:
                    pass

    return {"ok": True}


@app.post("/generate-image")
def generate_image(payload: GenerateImageRequest, token: Optional[str] = Depends(optional_token)) -> dict[str, Any]:
    """Generate an image to accompany a LinkedIn post (GPT Image 2)."""
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY manquant dans .env")
    credits: int | None = None
    if token:
        ok, balance = db.debit_credits(token, "generate_image")
        if not ok:
            raise HTTPException(status_code=402, detail=f"Crédits insuffisants (solde : {balance}). Génération d'image = {db.CREDIT_COSTS['generate_image']} crédit(s).")
        credits = balance
    try:
        # Import paresseux : la génération d'image dépend d'`openai`. Un import
        # au niveau module ferait planter tout le démarrage de l'API si la
        # dépendance (ou le module) manque — on l'isole donc à cet endpoint.
        from src.image_gen import generate_post_image
        result = generate_post_image(payload.post_text)
        if isinstance(result, dict):
            result["credits"] = credits
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def _sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@app.get("/chat/conversations")
def chat_conversations(token: str = Depends(require_token)) -> list[dict[str, Any]]:
    """List recent chat conversations for the authenticated user."""
    return db.list_chat_conversations(token)


@app.get("/chat/conversations/{conversation_id}/messages")
def chat_messages(conversation_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Return a persisted chat history."""
    conversation = db.get_chat_conversation(token, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation introuvable.")
    return {
        "conversation": conversation,
        "messages": db.get_chat_messages(token, conversation_id, limit=80),
    }


@app.post("/chat")
def chat(payload: ChatRequest, token: str = Depends(require_token)) -> StreamingResponse:
    """Conversationnel V1: contexte client + benchmark + historique, streamé en SSE."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY manquant dans .env")

    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message vide.")

    ok, balance = db.debit_credits(token, "chat")
    if not ok:
        raise HTTPException(status_code=402, detail=f"Crédits insuffisants (solde : {balance}). Message = {db.CREDIT_COSTS['chat']} crédit(s).")
    credits_balance = balance

    influencers = _get_influencers(token)
    if not influencers:
        raise HTTPException(status_code=400, detail="Aucun influenceur analysé. Lance d'abord une analyse.")

    conversation = None
    if payload.conversation_id:
        conversation = db.get_chat_conversation(token, payload.conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation introuvable.")
    else:
        conversation = db.create_chat_conversation(token, first_message=message)
        if not conversation:
            raise HTTPException(status_code=500, detail="Création de la conversation impossible.")

    conversation_id = conversation["id"]
    user_message = db.append_chat_message(token, conversation_id, "user", message)
    if not user_message:
        raise HTTPException(status_code=500, detail="Sauvegarde du message impossible.")

    history = db.get_chat_messages(token, conversation_id, limit=80)
    top_posts, benchmark = _build_benchmark(influencers)
    user_context = db.get_user_ai_context(token)

    def stream_response():
        assistant_text = ""
        yield _sse("meta", {"conversation_id": conversation_id, "credits": credits_balance})
        try:
            for delta in chat_stream(history, top_posts, benchmark, user_context=user_context):
                assistant_text += delta
                yield _sse("delta", {"text": delta})
            if assistant_text.strip():
                db.append_chat_message(token, conversation_id, "assistant", assistant_text)
            yield _sse("done", {"ok": True})
        except Exception as exc:
            yield _sse("error", {"detail": str(exc)})

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
    platform: str = "linkedin"


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


def _clean_ig_urls(raw: list[str]) -> list[str]:
    """Normalise les handles/URLs Instagram en URLs canoniques, déduplique."""
    from src.scraper_instagram import extract_ig_handle
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        raw_item = (item or "").strip()
        if not raw_item:
            continue
        handle = extract_ig_handle(raw_item)
        if not handle:
            continue
        key = handle.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(f"https://www.instagram.com/{handle}/")
    return out


@app.post("/jobs")
def create_job(payload: JobRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Crée une série d'analyses (backlog) traitée en fond, profil par profil."""
    if not os.environ.get("APIFY_TOKEN"):
        raise HTTPException(status_code=400, detail="APIFY_TOKEN manquant dans .env")
    if payload.run_llm and not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY manquant dans .env")

    platform = payload.platform or "linkedin"

    if platform == "instagram":
        urls = _clean_ig_urls(payload.profile_urls)
        if not urls:
            raise HTTPException(status_code=400, detail="Aucun handle Instagram valide.")
    else:
        urls = _clean_urls(payload.profile_urls)
        if not urls:
            raise HTTPException(status_code=400, detail="Aucune URL de profil LinkedIn valide.")

    try:
        job = db.create_job(token, urls, payload.limit, payload.run_llm, payload.use_cache, platform=platform)
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
    return db.list_jobs(token)


@app.get("/jobs/{job_id}")
def get_job(job_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """État d'une série + statut de chaque profil (pour le polling frontend)."""
    job = db.get_job(token, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Série introuvable.")
    return job


@app.post("/jobs/{job_id}/resume")
def resume_job(job_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Relance le traitement des profils non terminés (après un redémarrage serveur)."""
    job = db.get_job(token, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Série introuvable.")
    pending = [it for it in job.get("items", []) if it.get("status") != "done"]
    if pending:
        start_job_thread(token, job_id)
    return job


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Annule une série en cours.

    Pose le statut `cancelled` en base — le thread de traitement s'en aperçoit
    avant chaque nouveau profil et stoppe proprement. Le profil en cours de
    scraping (appel Apify bloquant) se terminera néanmoins avant l'arrêt.
    """
    job = db.get_job(token, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Série introuvable.")
    if job.get("status") not in ("queued", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"La série est déjà terminée (statut : {job.get('status')}).",
        )
    db.update_job(token, job_id, status="cancelled")
    db.cancel_pending_items(token, job_id)  # solde aussi les items en cours/attente
    return db.get_job(token, job_id)


@app.post("/jobs/{job_id}/items/{item_id}/cancel")
def cancel_job_item(
    job_id: str, item_id: str, token: str = Depends(require_token)
) -> dict[str, Any]:
    """Annule un profil précis d'une série (sans toucher aux autres).

    L'item passe en `cancelled` (si encore `pending`/`running`). Si plus aucun
    profil n'est actif, la série est finalisée immédiatement — utile quand le
    thread de traitement est figé/mort et ne le ferait pas de lui-même.
    """
    job = db.get_job(token, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Série introuvable.")
    item = next((it for it in job.get("items", []) if it["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Profil introuvable dans la série.")
    if item["status"] not in ("pending", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Ce profil est déjà terminé (statut : {item['status']}).",
        )

    db.cancel_job_item(token, item_id)
    item["status"] = "cancelled"

    # Finalise la série si plus rien n'est actif (cas thread figé/mort).
    final = jobs_module.final_status(job.get("items", []))
    if final and job.get("status") in ("queued", "running"):
        done, failed = jobs_module.final_counts(job.get("items", []))
        db.update_job(token, job_id, status=final, completed=done, failed=failed)
    return db.get_job(token, job_id)


@app.delete("/jobs/{job_id}/items/{item_id}")
def delete_job_item(
    job_id: str, item_id: str, token: str = Depends(require_token)
) -> dict[str, bool]:
    """Supprime une analyse d'une série : la ligne + son rapport lié (ALE-131)."""
    return {"deleted": db.delete_job_item(token, item_id)}


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


# ── ALE-103 : Instagram hooks ─────────────────────────────────────────────────

class InstagramHooksRequest(BaseModel):
    count: int = 8
    topic: str | None = None


@app.post("/instagram/hooks")
def instagram_hooks(
    payload: InstagramHooksRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Génère des hooks Instagram personnalisés depuis la base de hooks."""
    user_context: dict[str, Any] = {}
    try:
        profile = db.get_editorial_profile(token) or {}
        user_context = {k: v for k, v in profile.items() if v not in (None, "")}
    except Exception:
        pass
    hooks = select_hooks(user_context, count=max(1, min(payload.count, 20)), topic=payload.topic)
    return {"hooks": hooks}
