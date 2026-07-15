from __future__ import annotations

import os
import json
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from src import db, slack as slack_client, zernio, manychat, ig_agent, weekly_posts, influencer_monitor, unipile, stripe_billing
from src import outreach_engine
from src.benchmark import build_benchmark, enrich_influencers
from src.pipeline import run_analysis
from src import jobs as jobs_module
from src.jobs import start_job_thread, start_generation_job_thread, start_image_job_thread
from src.lead_finder import DEFAULT_MAX_ITEMS as LEAD_COMMENTS_DEFAULT, fetch_post_commenters
from src.llm import generate_ideas, generate_one_line_ideas, generate_posts, analyze_dashboard_strategy, draft_editorial_profile, chat_stream, extract_post_template, classify_lead_magnet, score_leads, generate_first_message
from src.llm import ROLE_SPECS, recommend_editorial_role, suggest_angle_from_post, suggest_structures
from src.normalize import normalize_posts, normalize_profile
from src.patterns import analyze_patterns
from src.scraper import fetch_post_detail, fetch_posts, fetch_profile
from src.stats import compute_stats
from src.instagram_hooks import select_hooks
from src.trends import compute_trends
from src.daily_ideas import _render_idea_markdown
from src.listing import ListingError, build_listing_topic, fetch_listing_preview, is_listing_url

load_dotenv()

if slack_client.enabled() and not os.environ.get("SLACK_SIGNING_SECRET"):
    print(
        "⚠️  SLACK_SIGNING_SECRET absent : les webhooks Slack seront refusés (fail-closed). "
        "Ajoutez-le dans les variables d'environnement.",
        file=sys.stderr,
    )

if manychat.enabled() and not os.environ.get("MANYCHAT_WEBHOOK_SECRET"):
    print(
        "⚠️  MANYCHAT_WEBHOOK_SECRET absent : le webhook DM Instagram sera refusé (fail-closed). "
        "Ajoutez-le dans les variables d'environnement.",
        file=sys.stderr,
    )

# État CSRF OAuth Slack : token → {user_id, expires}. TTL 10 min, en mémoire.
_slack_oauth_states: dict[str, dict] = {}

app = FastAPI(title="LinkedIn Strategy Decoder API")


def _cors_origins() -> list[str]:
    default_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
        "https://courageous-strudel-2d8ba3.netlify.app",
        "https://lkd-outreach.netlify.app",
        "https://lkd-outreach-dev.netlify.app",
        "https://analyseur-linkedin-influenceur-api-dev.onrender.com",
    ]
    extra_origins = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    return list(dict.fromkeys(default_origins + extra_origins))


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
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


@app.get("/me/influencer-trends")
def me_influencer_trends(token: str = Depends(require_token)) -> dict[str, Any]:
    """Tendances transverses calculées sur tous les rapports de l'utilisateur.

    Agrégation pure (aucun appel LLM, aucun scraping) : lecture du corpus et
    des stats de rapports, donc gratuit et recalculable à la demande.
    """
    corpus = db.get_user_corpus(token)
    analyses = db.list_analysis_stats(token)
    return compute_trends(corpus, analyses)


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
        "account_name": profile.get("zernio_account_name"),
        "account_type": profile.get("zernio_account_type"),
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
        account = zernio.find_account(profile_id, "linkedin")
    except zernio.ZernioError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    account_id = account.get("_id") if account else None
    account_name = zernio.account_display_name(account)
    account_type = zernio.account_type(account)
    db.set_zernio_account(token, account_id, account_name, account_type)
    return _linkedin_status(token)


@app.delete("/me/linkedin")
def me_linkedin_disconnect(token: str = Depends(require_token)) -> dict[str, Any]:
    """Clear the user's connected LinkedIn account."""
    db.set_zernio_account(token, None)
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

    # Les images sont mises en ligne dès la programmation (URLs publiques) :
    # le message de validation Slack ne peut afficher que des URLs publiques,
    # et on évite de stocker des data-URLs base64 en base. Le cron republie
    # ces items tels quels (prepare_image_media_items est idempotent).
    try:
        media_items = zernio.prepare_image_media_items(_image_payload(payload.images))
    except zernio.ZernioError as exc:
        raise HTTPException(status_code=502, detail=f"Impossible de préparer les images du post : {exc}") from exc

    # ALE-137 — Option A : programmation directe, publiée à l'échéance sans
    # validation Slack (le post naît `validated` pour que le cron le publie).
    if not payload.validate_via_slack:
        row = db.create_scheduled_post(
            token,
            payload.content.strip(),
            payload.scheduled_at,
            media_items=media_items,
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
        media_items=media_items,
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
    # Un lot = 3 idées max : au-delà, la réponse JSON déborde le budget de tokens
    # (réponse tronquée → erreur) et la liste devient inutilisable côté client.
    count: int = Field(default=3, ge=1, le=3)
    web_search: bool = Field(default=False)


class GenerateRequest(BaseModel):
    topic: Optional[str] = Field(default=None)
    editorial_role: Optional[str] = Field(default=None)
    # ALE-216 : template de structure choisi dans la banque (optionnel).
    template_id: Optional[str] = Field(default=None)
    # Deprecated client hint kept for backward compatibility. Post generation now
    # exposes web search as an autonomous server-side tool; the model decides.
    web_search: bool = Field(default=False)
    count: int = Field(default=1, ge=1, le=3)


class GenerateImageRequest(BaseModel):
    post_text: str = Field(..., min_length=10)
    # Prompt validé/édité par l'utilisateur dans la pop-up ; absent = prompt auto.
    prompt: Optional[str] = Field(default=None, max_length=4000)
    # Image de la banque de templates choisie comme référence visuelle (ALE-221).
    reference_template_id: Optional[str] = Field(default=None, max_length=100)
    # Identifiant opaque (fourni par le frontend) du bloc de post auquel l'image
    # doit se rattacher — requis pour /generate-image/jobs (ALE-261), ignoré par
    # /generate-image/prompt.
    target_key: Optional[str] = Field(default=None, max_length=200)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=12000)
    conversation_id: Optional[str] = None


@app.post("/ideas")
def ideas(payload: IdeasRequest, token: Optional[str] = Depends(optional_token)) -> dict[str, Any]:
    """Generate scannable one-liner post ideas anchored in real top posts (ALE-143)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY manquant dans .env")

    influencers = _get_influencers(token)
    if not influencers:
        raise HTTPException(status_code=400, detail="Aucun influenceur analysé. Lance d'abord une analyse.")

    # Débit par lot (pas par idée) — après les préconditions.
    credits: int | None = None
    if token:
        ok, balance = db.debit_credits(token, "generate_ideas", 1)
        if not ok:
            cost = db.CREDIT_COSTS["generate_ideas"]
            raise HTTPException(status_code=402, detail=f"Crédits insuffisants (solde : {balance}). Un lot d'idées = {cost} crédit(s).")
        credits = balance

    # Carburant A : vrais posts performants des influenceurs analysés
    real_posts = db.get_top_real_posts(token) if token else []
    _, benchmark = _build_benchmark(influencers)
    user_context = db.get_user_ai_context(token)

    # Anti-répétition : lignes des idées récentes
    recent_idea_lines: list[str] = []
    if token:
        try:
            recent = db.list_generated_ideas(token, limit=40)
            recent_idea_lines = [r["line"] for r in recent if r.get("line")]
        except Exception:
            pass

    ideas_list = generate_one_line_ideas(
        real_posts=real_posts,
        benchmark=benchmark,
        count=payload.count,
        user_context=user_context,
        web_search=payload.web_search,
        recent_idea_lines=recent_idea_lines or None,
        reference_posts=db.pick_reference_posts(token) or None,
    )
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
        "reference_posts": db.pick_reference_posts(token) or None,
        "template": db.get_post_template(token, payload.template_id) if (token and payload.template_id) else None,
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
        reference_posts=context["reference_posts"],
        template=context["template"],
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
                    reference_posts=context["reference_posts"],
                    template=context["template"],
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


class InspirationPost(BaseModel):
    """Post LinkedIn dont le client a demandé de s'inspirer (parcours guidé, ALE-286)."""
    text: str = Field(..., min_length=20, max_length=6000)
    author: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)


class GenerationJobRequest(GenerateRequest):
    """Requête de la file d'attente. Modèle à part et non un champ de plus sur
    `GenerateRequest` : seul le chemin par jobs sait porter l'inspiration jusqu'au
    modèle. L'ajouter au modèle commun l'aurait fait accepter — puis **ignorer en
    silence** — par `/generate` et `/generate/stream`."""
    inspiration: InspirationPost | None = Field(default=None)


@app.post("/generate/jobs")
def create_generation_job(payload: GenerationJobRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Lance une génération de posts en arrière-plan (file d'attente — ALE-141).

    Non bloquant : on débite les crédits, on crée le job et on lance le thread,
    puis on rend la main immédiatement. Le frontend récupère le résultat via
    GET /generate/jobs/{id}. L'utilisateur peut quitter la page entre-temps.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY manquant dans .env")

    influencers = _get_influencers(token)
    if not influencers:
        raise HTTPException(status_code=400, detail="Aucun influenceur analysé. Lance d'abord une analyse.")

    # Débit après les préconditions : un user sans influenceur ne perd pas de crédits.
    ok, balance = db.debit_credits(token, "generate_post", payload.count)
    if not ok:
        cost = db.CREDIT_COSTS["generate_post"] * payload.count
        raise HTTPException(status_code=402, detail=f"Crédits insuffisants (solde : {balance}). Génération de {payload.count} post(s) = {cost} crédit(s).")

    role = (payload.editorial_role or "").strip() or None
    topic = (payload.topic or "").strip() or None
    job = db.create_generation_job(
        token, topic, role, payload.web_search, payload.count,
        template_id=payload.template_id,
        inspiration=payload.inspiration.model_dump() if payload.inspiration else None,
    )
    if not job:
        raise HTTPException(status_code=500, detail="Création du job de génération impossible.")
    start_generation_job_thread(token, job["id"])
    job["credits"] = balance
    return job


@app.get("/generate/jobs")
def list_generation_jobs(token: str = Depends(require_token)) -> list[dict[str, Any]]:
    """Liste les jobs de génération de l'utilisateur (plus récents d'abord)."""
    return db.list_generation_jobs(token)


@app.get("/generate/jobs/{job_id}")
def get_generation_job(job_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Récupère un job de génération (pour le polling du frontend)."""
    job = db.get_generation_job(token, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job de génération introuvable.")
    return job


@app.post("/generate/jobs/{job_id}/cancel")
def cancel_generation_job(job_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Annule un job de génération encore en attente/en cours."""
    job = db.cancel_generation_job(token, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job de génération introuvable.")
    return job


# --------------------------------------------------------------------------- #
# Parcours guidé de génération (ALE-286)
# --------------------------------------------------------------------------- #
# Le client part d'un des trois points d'entrée (une idée à lui, aucune idée, un
# post qui l'a inspiré), converge sur un rôle éditorial, puis sur une structure
# de sa bibliothèque, et obtient UN post. Trois endpoints d'aide à la décision —
# lire l'inspiration, recommander le rôle, proposer les structures — tous gratuits
# et sans effet de bord : le post, lui, part par la file d'attente existante
# (`POST /generate/jobs`), qui sait déjà débiter, créer le job et le suivre.


class InspirationRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2000)


@app.post("/generate/inspiration")
def read_inspiration_post(payload: InspirationRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Lit le post LinkedIn dont le client veut s'inspirer et en déduit un angle.

    Gratuit (aucun crédit) : c'est une aide à la décision, pas une génération —
    le client peut se tromper de lien sans que ça lui coûte quoi que ce soit.
    """
    url = payload.url.strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Colle un lien de post LinkedIn (https://…).")

    detail = fetch_post_detail(url)
    if not detail or not (detail.get("text") or "").strip():
        raise HTTPException(
            status_code=422,
            detail="Impossible de lire le post depuis ce lien — colle son texte directement.",
        )

    # L'angle est un confort : s'il échoue, le client écrit le sien à la main
    # plutôt que de voir le parcours s'arrêter sur un post pourtant bien lu.
    angle = ""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            angle = suggest_angle_from_post(detail["text"], db.get_user_ai_context(token))
        except Exception as exc:  # noqa: BLE001
            print(f"[wizard] angle non déduit pour {url}: {exc}", flush=True)

    return {
        "text": detail["text"],
        "author": detail.get("author"),
        "url": detail.get("url") or url,
        "image_url": detail.get("image_url"),
        "angle": angle,
    }


class EditorialRoleRequest(BaseModel):
    idea: str = Field(..., min_length=3, max_length=2000)


@app.post("/generate/editorial-role")
def recommend_role(payload: EditorialRoleRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Recommande un rôle éditorial pour l'idée retenue (gratuit, non contraignant)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY manquant côté serveur.")
    reco = recommend_editorial_role(payload.idea.strip(), db.get_user_ai_context(token))
    return {
        "editorial_role": reco["editorial_role"],
        "reason": reco["reason"],
        "roles": [{"value": key, "label": spec["label"]} for key, spec in ROLE_SPECS.items()],
    }


class StructuresRequest(BaseModel):
    idea: str = Field(..., min_length=3, max_length=2000)
    editorial_role: str = Field(..., max_length=50)


@app.post("/generate/structures")
def suggest_post_structures(payload: StructuresRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Propose les structures de la bibliothèque les plus adaptées à l'idée retenue.

    Gratuit (aucun crédit) : c'est une aide au choix, pas une génération. Le
    client voit ce qu'il choisit — on rend donc le nom et un extrait de chaque
    structure, pas des identifiants nus.

    Liste vide = bibliothèque vide ou sans contenu exploitable. Le parcours
    enchaîne alors en structure libre : un compte neuf n'est jamais bloqué sur une
    étape sans option.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY manquant côté serveur.")
    role = payload.editorial_role.strip()
    if role not in ROLE_SPECS:
        raise HTTPException(status_code=422, detail="Rôle éditorial inconnu.")

    try:
        library = db.list_post_templates(token)
    except Exception:  # noqa: BLE001 — la bibliothèque est un plus, pas un prérequis
        library = []
    suggested = suggest_structures(payload.idea.strip(), role, library)

    return {
        "structures": [
            {
                "id": t["id"],
                "label": (t.get("structure_label") or "").strip() or None,
                "structure_text": (t.get("structure_text") or "").strip() or None,
                "post_text": (t.get("post_text") or "").strip()[:400] or None,
            }
            for t in suggested
        ],
        # La plus adaptée d'abord : c'est celle que le parcours pré-coche.
        "recommended_id": suggested[0]["id"] if suggested else None,
    }


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


class CreatePostRequest(BaseModel):
    post: str = Field(..., min_length=1, max_length=50000)
    topic: str | None = None
    editorial_role: str | None = None
    hook_type: str | None = None
    strategy: str | None = None
    predicted_lift: str | None = None
    images: list[LinkedInImageRequest] = Field(default_factory=list, max_length=zernio.MAX_LINKEDIN_IMAGES)


def _saved_post_media_items(images: list[LinkedInImageRequest]) -> tuple[list[dict[str, Any]], bool]:
    """Convert attached images to public-URL media_items (ALE-179).

    Les data URLs sont hébergées sur Zernio (URL publique), les URLs déjà
    publiques passent telles quelles. Non bloquant : un échec d'upload ne doit
    pas empêcher la sauvegarde du texte — retourne (items, erreur)."""
    if not images:
        return [], False
    try:
        return zernio.prepare_image_media_items(_image_payload(images)), False
    except zernio.ZernioError:
        return [], True


@app.post("/me/generated-posts")
def create_me_generated_post(
    payload: CreatePostRequest, token: str = Depends(require_token)
) -> dict[str, Any]:
    """Create an explicitly-saved post (ALE-136 : sauvegarder le post du jour)."""
    media_items, media_error = _saved_post_media_items(payload.images)
    row = db.create_saved_post(
        token,
        payload.post,
        topic=payload.topic,
        editorial_role=payload.editorial_role,
        hook_type=payload.hook_type,
        strategy=payload.strategy,
        predicted_lift=payload.predicted_lift,
        media_items=media_items or None,
    )
    if not row:
        raise HTTPException(status_code=500, detail="Sauvegarde impossible.")
    if media_error:
        row["media_error"] = True
    return row


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
    # None = ne pas toucher aux images ; [] = tout retirer (ALE-179).
    images: list[LinkedInImageRequest] | None = Field(default=None, max_length=zernio.MAX_LINKEDIN_IMAGES)


@app.put("/me/generated-posts/{post_id}")
def update_me_generated_post(post_id: str, payload: UpdatePostRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Update a saved post's text, its `saved` flag and/or its images (ALE-134/179)."""
    if payload.post is None and payload.saved is None and payload.images is None:
        raise HTTPException(status_code=400, detail="Rien à mettre à jour (post, saved ou images requis).")
    media_items: list[dict[str, Any]] | None = None
    media_error = False
    if payload.images is not None:
        media_items, media_error = _saved_post_media_items(payload.images)
        if media_error and not media_items and payload.post is None and payload.saved is None:
            raise HTTPException(status_code=502, detail="Hébergement des images impossible, réessaie.")
        if media_error:
            media_items = None  # échec upload : ne pas écraser les images existantes
    updated = db.update_generated_post(token, post_id, payload.post, payload.saved, media_items=media_items)
    if not updated:
        raise HTTPException(status_code=404, detail="Post introuvable ou non autorisé.")
    if media_error:
        updated["media_error"] = True
    return updated


# --------------------------------------------------------------------------- #
# Crédits utilisateur (ALE-41)
# --------------------------------------------------------------------------- #

@app.get("/me/credits")
def me_credits(token: str = Depends(require_token)) -> dict[str, Any]:
    """Retourne le solde de crédits de l'utilisateur authentifié."""
    return db.get_user_credits(token)


# --------------------------------------------------------------------------- #
# Abonnement Stripe (ALE-274) — 49 €/mois = 1000 crédits
#
# Le paiement et la gestion de la carte/résiliation sont hébergés par Stripe
# (Checkout + Customer Portal). L'app ne fait que : ouvrir la page de paiement,
# écouter le webhook, et refléter l'état d'abonnement.
#
# Règle de confiance : SEUL le webhook (signé par Stripe) crédite et fait foi sur
# l'état d'abonnement. Aucun endpoint porteur d'un JWT utilisateur ne crédite —
# sinon un client pourrait s'auto-recharger en rejouant l'appel de retour.
# --------------------------------------------------------------------------- #

class BillingCheckoutRequest(BaseModel):
    success_url: str = Field(..., max_length=2000)
    cancel_url: str = Field(..., max_length=2000)


class BillingPortalRequest(BaseModel):
    return_url: str = Field(..., max_length=2000)


def _billing_state(subscription: dict | None) -> dict[str, Any]:
    """Vue publique de l'abonnement (jamais d'identifiants Stripe côté client)."""
    status = (subscription or {}).get("status")
    return {
        "enabled": stripe_billing.enabled(),
        "subscribed": stripe_billing.is_active(status),
        "status": status,
        "cancel_at_period_end": bool((subscription or {}).get("cancel_at_period_end")),
        "current_period_end": (subscription or {}).get("current_period_end"),
        "has_customer": bool((subscription or {}).get("stripe_customer_id")),
        "plan": stripe_billing.plan_summary() if stripe_billing.enabled() else None,
    }


def _require_billing() -> None:
    if not stripe_billing.enabled():
        raise HTTPException(
            status_code=503,
            detail="Facturation non configurée (STRIPE_SECRET_KEY / STRIPE_PRICE_ID).",
        )


def _ensure_stripe_customer(token: str) -> tuple[str, str]:
    """Retourne (user_id, stripe_customer_id), en créant le client Stripe au besoin.

    Écriture service-role strictement scopée au user_id du token vérifié (même
    exception documentée que `replace_daily_idea`) : la table est en lecture seule
    côté client, donc l'app ne peut pas s'écrire un abonnement.
    """
    user = db.get_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur inconnu.")
    if not db.admin_enabled():
        raise HTTPException(status_code=503, detail="Service-role Supabase indisponible.")

    existing = db.get_subscription_by_user_admin(user["id"])
    customer_id = (existing or {}).get("stripe_customer_id")
    if customer_id:
        return user["id"], customer_id

    try:
        customer = stripe_billing.create_customer(user["id"], user.get("email"))
    except stripe_billing.StripeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    customer_id = customer.get("id")
    if not customer_id:
        raise HTTPException(status_code=502, detail="Stripe n'a pas renvoyé de client.")
    db.upsert_subscription_admin(user["id"], stripe_customer_id=customer_id)
    return user["id"], customer_id


@app.get("/billing/plan")
def billing_plan() -> dict[str, Any]:
    """Offre publique (page de vente) — prix et crédits lus depuis Stripe.

    Sans authentification : ne renvoie que ce qui est déjà public (le montant
    affiché sur la page de paiement). Évite de figer « 49 € » en dur dans la page
    de vente et de se retrouver avec un prix qui ment si le tarif change.
    """
    if not stripe_billing.enabled():
        return {"enabled": False, "plan": None}
    return {"enabled": True, "plan": stripe_billing.plan_summary()}


@app.get("/me/billing")
def me_billing(token: str = Depends(require_token)) -> dict[str, Any]:
    """État d'abonnement de l'utilisateur (pour la carte « Abonnement » du profil)."""
    return _billing_state(db.get_subscription(token))


@app.post("/me/billing/checkout")
def me_billing_checkout(
    payload: BillingCheckoutRequest, token: str = Depends(require_token)
) -> dict[str, Any]:
    """Ouvre une session Checkout Stripe (page de paiement hébergée) → URL de redirection."""
    _require_billing()
    user_id, customer_id = _ensure_stripe_customer(token)
    try:
        session = stripe_billing.create_checkout_session(
            customer_id, user_id, payload.success_url, payload.cancel_url
        )
    except stripe_billing.StripeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    url = session.get("url")
    if not url:
        raise HTTPException(status_code=502, detail="Stripe n'a pas renvoyé d'URL de paiement.")
    return {"url": url}


@app.post("/me/billing/portal")
def me_billing_portal(
    payload: BillingPortalRequest, token: str = Depends(require_token)
) -> dict[str, Any]:
    """Ouvre le Customer Portal Stripe (carte, factures, résiliation)."""
    _require_billing()
    subscription = db.get_subscription(token)
    customer_id = (subscription or {}).get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(status_code=404, detail="Aucun abonnement à gérer.")
    try:
        session = stripe_billing.create_portal_session(customer_id, payload.return_url)
    except stripe_billing.StripeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    url = session.get("url")
    if not url:
        raise HTTPException(status_code=502, detail="Stripe n'a pas renvoyé d'URL de portail.")
    return {"url": url}


@app.post("/me/billing/refresh")
def me_billing_refresh(token: str = Depends(require_token)) -> dict[str, Any]:
    """Resynchronise l'état d'abonnement depuis Stripe (filet si un webhook s'est perdu).

    Ne crédite RIEN : seul le webhook signé le fait. Ici on ne relit que le statut,
    la période et la résiliation programmée.
    """
    _require_billing()
    user = db.get_user(token)
    if not user or not db.admin_enabled():
        raise HTTPException(status_code=503, detail="Service-role Supabase indisponible.")
    existing = db.get_subscription_by_user_admin(user["id"])
    customer_id = (existing or {}).get("stripe_customer_id")
    if not customer_id:
        return _billing_state(existing)
    try:
        subs = stripe_billing.list_customer_subscriptions(customer_id)
    except stripe_billing.StripeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if not subs:
        return _billing_state(existing)
    # Le plus pertinent = un abonnement actif s'il y en a un, sinon le plus récent.
    active = next((s for s in subs if stripe_billing.is_active(s.get("status"))), subs[0])
    fields = stripe_billing.normalize_subscription(active)
    db.upsert_subscription_admin(
        user["id"],
        stripe_subscription_id=fields["stripe_subscription_id"],
        status=fields["status"],
        price_id=fields["price_id"],
        current_period_end=fields["current_period_end"],
        cancel_at_period_end=fields["cancel_at_period_end"],
    )
    return _billing_state(db.get_subscription_by_user_admin(user["id"]))


def _webhook_user_id(obj: dict[str, Any], customer_id: str | None) -> str | None:
    """Retrouve le compte app visé par un événement Stripe.

    Trois chemins, du plus direct au plus tolérant : la métadonnée `user_id` (posée
    sur la session et l'abonnement), celle relayée par la facture (rangée dans
    `parent.subscription_details` sur les versions récentes de l'API), sinon le
    client Stripe → notre table.
    """
    meta_user = (obj.get("metadata") or {}).get("user_id")
    if meta_user:
        return meta_user
    invoice_user = stripe_billing.invoice_user_id(obj)
    if invoice_user:
        return invoice_user
    row = db.get_subscription_by_customer_admin(customer_id) if customer_id else None
    return (row or {}).get("user_id")


@app.post("/stripe/webhooks")
async def stripe_webhook(request: Request) -> dict[str, Any]:
    """Webhook Stripe : source de vérité de l'abonnement et des crédits.

    Fail-closed sur la signature (comme Slack/ManyChat). Idempotent : Stripe rejoue
    un événement tant qu'il n'a pas eu de 2xx — sans dédoublonnage, un rejeu de
    `invoice.paid` remettrait le solde à 1000 et effacerait la consommation du mois.
    """
    body = await request.body()
    try:
        event = stripe_billing.verify_webhook(body, request.headers.get("Stripe-Signature", ""))
    except stripe_billing.StripeError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    if not db.admin_enabled():
        # 503 → Stripe rejouera l'événement plus tard (rien n'est perdu).
        raise HTTPException(status_code=503, detail="Service-role Supabase indisponible.")

    event_type = event.get("type") or ""
    obj = ((event.get("data") or {}).get("object") or {})
    if event_type not in (
        "checkout.session.completed",
        "invoice.paid",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        return {"ignored": event_type}

    customer_id = obj.get("customer") if isinstance(obj.get("customer"), str) else None
    user_id = _webhook_user_id(obj, customer_id)
    if not user_id:
        # Client Stripe inconnu de l'app (ex. abonnement créé à la main dans le
        # dashboard) : on accuse réception pour ne pas faire boucler Stripe.
        return {"ignored": event_type, "reason": "compte inconnu"}

    if db.billing_event_already_processed(event.get("id") or "", event_type, user_id):
        return {"duplicate": True}

    if event_type == "checkout.session.completed":
        # Rattache le client + l'abonnement au compte. Le crédit, lui, arrive avec
        # `invoice.paid` (émis dans la foulée) → un seul endroit qui crédite.
        subscription_id = obj.get("subscription") if isinstance(obj.get("subscription"), str) else None
        db.upsert_subscription_admin(
            user_id, stripe_customer_id=customer_id, stripe_subscription_id=subscription_id
        )
        return {"ok": True}

    if event_type == "invoice.paid":
        subscription_id = stripe_billing.invoice_subscription_id(obj)
        credits = stripe_billing.plan_credits()
        # Solde FIXÉ (pas incrémenté) : pas de report des crédits non consommés.
        new_balance = db.set_credits_admin(
            user_id, credits, action="subscription_renewal",
            description=f"abonnement payé — solde remis à {credits}",
        )
        if new_balance is None:
            # L'écriture a échoué : on renvoie une erreur pour que Stripe rejoue
            # (l'événement n'a pas été marqué traité… si, il l'a été → on le purge).
            db.delete_billing_event_admin(event.get("id") or "")
            raise HTTPException(status_code=500, detail="Crédits non appliqués — rejouer.")
        fields: dict[str, Any] = {"stripe_customer_id": customer_id, "status": "active"}
        if subscription_id:
            fields["stripe_subscription_id"] = subscription_id
            try:
                fields.update({
                    k: v for k, v in
                    stripe_billing.normalize_subscription(
                        stripe_billing.get_subscription(subscription_id)
                    ).items()
                    if k in ("status", "price_id", "current_period_end")
                })
            except stripe_billing.StripeError:
                pass  # le statut/période se resynchroniseront au prochain événement
        db.upsert_subscription_admin(user_id, **fields)
        return {"ok": True, "credits": new_balance}

    # customer.subscription.updated / .deleted → l'objet EST l'abonnement.
    fields = stripe_billing.normalize_subscription(obj)
    status = "canceled" if event_type == "customer.subscription.deleted" else fields["status"]
    db.upsert_subscription_admin(
        user_id,
        stripe_customer_id=customer_id,
        stripe_subscription_id=fields["stripe_subscription_id"],
        status=status,
        price_id=fields["price_id"],
        current_period_end=fields["current_period_end"],
        cancel_at_period_end=fields["cancel_at_period_end"],
    )
    return {"ok": True, "status": status}


# --------------------------------------------------------------------------- #
# Idée du jour — réservoir de seeds + idées générées + opt-in
# --------------------------------------------------------------------------- #

class IdeaSeedRequest(BaseModel):
    text: str = Field(..., min_length=3, max_length=2000)
    comment: str | None = Field(default=None, max_length=500)


class IdeaSeedReorderRequest(BaseModel):
    ordered_ids: list[str] = Field(..., max_length=500)


class DailyIdeasEnabledRequest(BaseModel):
    enabled: bool


class ListingPreviewRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2000)


@app.post("/listing/preview")
def listing_preview(payload: ListingPreviewRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """ALE-156 : lit une annonce immobilière (image + infos) depuis son URL.

    Sert d'aperçu avant d'enregistrer le lien dans le réservoir : la cliente voit
    la photo + les infos qu'on a su extraire, et sait si le site est lisible.
    """
    try:
        return fetch_listing_preview(payload.url.strip())
    except ListingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/me/idea-seeds")
def me_idea_seeds(token: str = Depends(require_token)) -> list[dict[str, Any]]:
    """List the user's idea reservoir."""
    return db.list_idea_seeds(token)


@app.post("/me/idea-seeds")
def add_me_idea_seed(payload: IdeaSeedRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Add an idea to the user's reservoir."""
    comment = (payload.comment or "").strip() or None
    seed = db.add_idea_seed(token, payload.text.strip(), comment=comment)
    if not seed:
        raise HTTPException(status_code=400, detail="Impossible d'enregistrer l'idée.")
    return seed


@app.post("/me/idea-seeds/reorder")
def reorder_me_idea_seeds(payload: IdeaSeedReorderRequest, token: str = Depends(require_token)) -> dict[str, bool]:
    """Persist a new manual order for the user's reservoir (drag & drop)."""
    return {"ok": db.reorder_idea_seeds(token, payload.ordered_ids)}


class IdeaSeedUpdateRequest(BaseModel):
    text: str | None = Field(default=None, min_length=3, max_length=2000)
    # None = inchangé ; "" = effacer le commentaire d'orientation.
    comment: str | None = Field(default=None, max_length=500)


@app.put("/me/idea-seeds/{seed_id}")
def update_me_idea_seed(seed_id: str, payload: IdeaSeedUpdateRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Edit an idea's text and/or orientation comment in the reservoir."""
    if payload.text is None and payload.comment is None:
        raise HTTPException(status_code=400, detail="Rien à mettre à jour (text ou comment requis).")
    text = payload.text.strip() if payload.text is not None else None
    if text is not None and len(text) < 3:
        raise HTTPException(status_code=422, detail="L'idée doit faire au moins 3 caractères.")
    comment = payload.comment.strip() if payload.comment is not None else None
    seed = db.update_idea_seed(token, seed_id, text=text, comment=comment)
    if not seed:
        raise HTTPException(status_code=404, detail="Idée introuvable ou non autorisée.")
    return seed


@app.delete("/me/idea-seeds/{seed_id}")
def delete_me_idea_seed(seed_id: str, token: str = Depends(require_token)) -> dict[str, bool]:
    """Delete one of the user's seeds."""
    return {"deleted": db.delete_idea_seed(token, seed_id)}


# --------------------------------------------------------------------------- #
# Boîte à idées — posts de référence (ALE-67)
# --------------------------------------------------------------------------- #

class ReferencePostRequest(BaseModel):
    # Texte optionnel : un lien LinkedIn seul suffit, le post est importé (scrape).
    text: str | None = Field(default=None, max_length=6000)
    url: str | None = Field(default=None, max_length=2000)
    author: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)


@app.get("/me/reference-posts")
def me_reference_posts(token: str = Depends(require_token)) -> list[dict[str, Any]]:
    """Déprécié (ALE-222) : lit la bibliothèque unifiée au format legacy.

    Conservé une release pour les onglets ouverts sur un vieux bundle SPA.
    """
    return db.list_reference_posts(token)


@app.post("/me/reference-posts")
def add_me_reference_post(payload: ReferencePostRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Déprécié (ALE-222) : écrit dans la bibliothèque unifiée (sans extraction IA).

    Conservé une release pour les onglets ouverts sur un vieux bundle SPA.
    Deux modes : texte collé directement, ou lien LinkedIn seul → le texte et
    l'auteur sont importés automatiquement (scrape Apify, ~0,005 $).
    """
    text = (payload.text or "").strip()
    url = (payload.url or "").strip() or None
    author = (payload.author or "").strip() or None

    if not text:
        if not url or not url.lower().startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="Colle le lien du post ou son texte.")
        detail = fetch_post_detail(url)
        if not detail:
            raise HTTPException(
                status_code=422,
                detail="Impossible de lire le post depuis ce lien — colle son texte directement.",
            )
        text = detail["text"]
        author = author or detail.get("author")
        url = detail.get("url") or url

    if len(text) < 10:
        raise HTTPException(status_code=422, detail="Le texte du post est trop court (10 caractères minimum).")

    ref = db.add_reference_post(
        token,
        text[:6000],
        url=url,
        author=author,
        note=(payload.note or "").strip() or None,
    )
    if not ref:
        raise HTTPException(status_code=400, detail="Impossible d'enregistrer le post de référence.")
    return ref


@app.delete("/me/reference-posts/{ref_id}")
def delete_me_reference_post(ref_id: str, token: str = Depends(require_token)) -> dict[str, bool]:
    """Déprécié (ALE-222) : supprime dans la bibliothèque unifiée."""
    return {"deleted": db.delete_reference_post(token, ref_id)}


# --------------------------------------------------------------------------- #
# Ma bibliothèque (ALE-222 — fusion posts de référence ALE-67 + templates ALE-216)
# --------------------------------------------------------------------------- #

class PostTemplateRequest(BaseModel):
    # Tous optionnels — il faut au moins un lien de post, un texte ou une structure.
    url: str | None = Field(default=None, max_length=2000)
    text: str | None = Field(default=None, max_length=6000)
    note: str | None = Field(default=None, max_length=500)
    author: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=30)
    structure_label: str | None = Field(default=None, max_length=200)
    structure_text: str | None = Field(default=None, max_length=4000)
    format: str | None = Field(default=None, max_length=30)
    image_url: str | None = Field(default=None, max_length=2000)
    image_note: str | None = Field(default=None, max_length=500)


def _add_library_entry(
    token: str,
    *,
    url: str | None,
    text: str | None,
    note: str | None,
    author: str | None,
    structure_label: str | None,
    structure_text: str | None,
    fmt: str | None,
    image_url: str | None,
    image_note: str | None,
    source: str,
) -> dict[str, Any]:
    """Ajout unifié à « Ma bibliothèque » (ALE-222).

    (1) Pas de texte ni de structure + lien valide → import du post (texte,
    auteur, image) ; (2) texte sans structure manuelle → extraction IA du
    squelette, best-effort : un échec ne fait jamais perdre la sauvegarde
    (l'entrée reste utilisable comme inspiration) ; (3) insert.
    """
    text = (text or "").strip()
    url = (url or "").strip() or None
    author = (author or "").strip() or None
    structure_label = (structure_label or "").strip() or None
    structure_text = (structure_text or "").strip() or None
    fmt = (fmt or "").strip() or None
    image_url = (image_url or "").strip() or None

    has_valid_url = bool(url and url.lower().startswith(("http://", "https://")))
    if not text and not structure_text:
        if not has_valid_url:
            raise HTTPException(
                status_code=422,
                detail="Colle le lien du post, son texte, ou une structure.",
            )
        detail = fetch_post_detail(url)
        if not detail:
            raise HTTPException(
                status_code=422,
                detail="Impossible de lire le post depuis ce lien — colle son texte directement.",
            )
        text = detail["text"]
        author = author or detail.get("author")
        url = detail.get("url") or url
        image_url = image_url or detail.get("image_url")
        imported_from_link = True
    else:
        imported_from_link = False

    if text and len(text) < 10:
        raise HTTPException(status_code=422, detail="Le texte du post est trop court (10 caractères minimum).")
    if not text and structure_text and len(structure_text) < 10:
        raise HTTPException(status_code=422, detail="La structure est trop courte (10 caractères minimum).")

    # ALE-233 : le post complet EST le template. Plus d'extraction IA de squelette
    # à l'import (fini la friction/latence/coût) — le texte entier sert directement
    # de référence à la génération (cf. _format_template). On dérive juste un titre
    # court pour l'affichage, découplé du texte de génération (nommage = ALE-232).
    if not structure_label:
        basis = (structure_text or text or "").strip()
        if basis:
            structure_label = basis.splitlines()[0][:60] or None

    entry = db.add_post_template(
        token,
        structure_label=structure_label,
        structure_text=structure_text,
        format=fmt,
        image_url=image_url,
        image_note=(image_note or "").strip() or None,
        source=source,
        source_author=author,
        source_post_url=url,
        post_text=text[:6000] or None,
        note=(note or "").strip() or None,
    )
    if not entry:
        raise HTTPException(status_code=400, detail="Impossible d'enregistrer dans la bibliothèque.")
    # ALE-234 : un post importé par lien peut être un lead magnet — on le détecte
    # et on crée la source de prospection (sans collecte payante). La clé
    # `lead_magnet` n'est pas persistée sur l'entrée : le front la lit dans la
    # réponse, puis recroise bibliothèque × sources via l'URL du post.
    if imported_from_link and text:
        lead_magnet = _detect_library_lead_magnet(token, url=url, text=text, author=author)
        if lead_magnet:
            entry["lead_magnet"] = lead_magnet
    return entry


def _detect_library_lead_magnet(token: str, *, url: str, text: str, author: str | None) -> dict[str, Any] | None:
    """Verdict lead-magnet à l'import bibliothèque (ALE-234), best-effort.

    Ne bloque jamais la sauvegarde de l'entrée. Réutilise la source existante
    si le post est déjà connu de la prospection (import direct ou veille).
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        source = db.get_lead_source_by_url(token, url)
        if source is None:
            verdict = classify_lead_magnet(text)
            if not verdict["is_lead_magnet"]:
                return None
            source = db.add_lead_source(
                token,
                url,
                author=author,
                post_text=text,
                is_lead_magnet=True,
                trigger_keyword=verdict["trigger_keyword"],
                origin="library",
            )
        if not source or not source.get("is_lead_magnet"):
            return None
        return {
            "source_id": source["id"],
            "trigger_keyword": source.get("trigger_keyword"),
            "collected_at": source.get("collected_at"),
            "comments_count": source.get("comments_count"),
        }
    except Exception as exc:  # noqa: BLE001 — détection bonus, jamais bloquante
        print(f"[library] détection lead-magnet échouée (entrée sauvée quand même) : {exc}", flush=True)
        return None


@app.get("/me/post-templates")
def me_post_templates(token: str = Depends(require_token)) -> list[dict[str, Any]]:
    """List the user's library entries (posts de référence + templates unifiés)."""
    return db.list_post_templates(token)


@app.post("/me/post-templates")
def add_me_post_template(payload: PostTemplateRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Ajout unifié à « Ma bibliothèque » — lien de post, texte collé et/ou structure."""
    # `source` coercé serveur : jamais de valeur libre venue du client.
    source = "influencer" if (payload.source or "").strip() == "influencer" else "user"
    return _add_library_entry(
        token,
        url=payload.url,
        text=payload.text,
        note=payload.note,
        author=payload.author,
        structure_label=payload.structure_label,
        structure_text=payload.structure_text,
        fmt=payload.format,
        image_url=payload.image_url,
        image_note=payload.image_note,
        source=source,
    )


@app.delete("/me/post-templates/{template_id}")
def delete_me_post_template(template_id: str, token: str = Depends(require_token)) -> dict[str, bool]:
    """Delete one of the user's library entries."""
    return {"deleted": db.delete_post_template(token, template_id)}


@app.post("/me/post-templates/{template_id}/extract-structure")
def extract_me_post_template_structure(template_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Extrait (IA) la structure d'une entrée de bibliothèque qui n'en a pas.

    Remède pour les entrées migrées d'ALE-67 ou collées sans structure :
    elles deviennent sélectionnables comme template dans le Générateur.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY manquant côté serveur.")
    entry = db.get_post_template(token, template_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entrée introuvable.")
    text = (entry.get("post_text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="Cette entrée n'a pas de texte de post à analyser.")
    extracted = extract_post_template(text)
    if len(extracted.get("structure_text") or "") < 10:
        raise HTTPException(status_code=502, detail="L'extraction de la structure a échoué — réessaie.")
    fields: dict[str, Any] = {"structure_text": extracted["structure_text"][:4000]}
    if not entry.get("structure_label") and extracted.get("structure_label"):
        fields["structure_label"] = extracted["structure_label"][:200]
    if not entry.get("format") and extracted.get("format"):
        fields["format"] = extracted["format"]
    updated = db.update_post_template(token, template_id, fields)
    if not updated:
        raise HTTPException(status_code=400, detail="Impossible de mettre à jour l'entrée.")
    return updated


class TemplateFromPostRequest(BaseModel):
    text: str = Field(..., min_length=20, max_length=6000)
    image_url: str | None = Field(default=None, max_length=2000)
    author: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)


@app.post("/me/post-templates/from-post")
def add_me_post_template_from_post(payload: TemplateFromPostRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Déprécié (ALE-222) : alias de POST /me/post-templates pour la veille (ALE-217).

    Conservé une release pour les onglets ouverts sur un vieux bundle SPA.
    Stocke désormais aussi le texte du post ; un échec d'extraction de la
    structure ne bloque plus la sauvegarde (plus de 502).
    """
    return _add_library_entry(
        token,
        url=payload.url,
        text=payload.text,
        note=None,
        author=payload.author,
        structure_label=None,
        structure_text=None,
        fmt=None,
        image_url=payload.image_url,
        image_note=None,
        source="influencer",
    )


# --------------------------------------------------------------------------- #
# Prospection LinkedIn (ALE-227) — sources lead-magnet + leads commentateurs
# --------------------------------------------------------------------------- #

class LeadSourceRequest(BaseModel):
    url: str = Field(..., max_length=2000)
    max_comments: int | None = Field(default=None, ge=1, le=500)


class LeadCollectRequest(BaseModel):
    max_comments: int | None = Field(default=None, ge=1, le=500)


class LeadTargetingRequest(BaseModel):
    ideal_client: str | None = Field(default=None, max_length=4000)
    offer: str | None = Field(default=None, max_length=4000)
    interest_keywords: list[str] | None = Field(default=None)
    score_threshold: int | None = Field(default=None, ge=0, le=100)
    first_message_instructions: str | None = Field(default=None, max_length=4000)


def _score_leads_for_source(token: str, source: dict, counts: dict) -> None:
    """Note (ICP) les leads fraîchement touchés par une collecte, si un ciblage
    est configuré. Best-effort : un échec de scoring ne casse pas la collecte."""
    ids_by_url = (counts or {}).get("ids_by_url") or {}
    if not ids_by_url:
        return
    targeting = db.get_lead_targeting(token)
    if not targeting:
        return  # pas de ciblage → on n'invente pas de score (tous les leads restent visibles)
    try:
        leads = db.list_leads_for_scoring(token)
        by_id = {l["id"]: l for l in leads}
        to_score = [by_id[lid] for lid in ids_by_url.values() if lid in by_id]
        lead_inputs = [
            {
                "headline": l.get("headline"),
                "comment_text": l.get("comment_text"),
                "trigger_keyword": (source or {}).get("trigger_keyword"),
                "author": (source or {}).get("author"),
            }
            for l in to_score
        ]
        scores = score_leads(targeting, lead_inputs, source_post_text=(source or {}).get("post_text"))
        scored = [
            {"id": l["id"], "score": s.get("score"), "reason": s.get("reason")}
            for l, s in zip(to_score, scores)
        ]
        db.update_lead_scores(token, scored)
    except Exception as exc:  # noqa: BLE001
        print(f"[leads] scoring à l'ingestion échoué : {exc}", flush=True)


# Facturation de la collecte de commentateurs (ALE-239). L'appel Apify est
# payant (~0,002 $/commentaire) mais n'était débité d'aucun crédit → fuite de
# coût. On débite proportionnellement au volume RÉELLEMENT récupéré. Constante
# ajustable : au calibrage actuel (~0,006 $/crédit) 3 commentateurs ≈ 1 crédit
# couvre à peu près le coût Apify. La monter réduit la marge, la baisser la creuse.
LEAD_COMMENTERS_PER_CREDIT = 3


def _lead_collect_credit_cost(n_commenters: int) -> int:
    """Crédits à débiter pour une collecte, proportionnels au volume (min 1)."""
    n = max(0, int(n_commenters))
    if n == 0:
        return 0
    return max(1, (n + LEAD_COMMENTERS_PER_CREDIT - 1) // LEAD_COMMENTERS_PER_CREDIT)


def _collect_lead_source(token: str, source: dict, max_comments: int | None) -> dict[str, Any]:
    """Scrape les commentateurs d'une source et les persiste en leads dédupliqués.

    Facturation (ALE-239) : pré-check fail-closed du solde AVANT l'appel Apify
    payant (on ne scrape pas si le solde ne couvre pas le pire cas = le volume
    demandé), puis débit proportionnel au volume RÉELLEMENT récupéré (toujours
    <= demandé, donc le débit ne peut pas échouer après avoir payé le scrape).
    Zéro commentateur récupéré = zéro débit.
    """
    if not os.environ.get("APIFY_TOKEN"):
        raise HTTPException(status_code=503, detail="Scraping non configuré (APIFY_TOKEN manquant).")
    requested = max_comments or LEAD_COMMENTS_DEFAULT
    if token:
        worst_case = _lead_collect_credit_cost(requested)
        info = db.get_user_credits(token)
        if info.get("enabled") and info.get("balance", 0) < worst_case:
            raise HTTPException(
                status_code=402,
                detail=(
                    f"Crédits insuffisants (solde : {info.get('balance', 0)}). "
                    f"Cette collecte peut coûter jusqu'à {worst_case} crédit(s)."
                ),
            )
    try:
        commenters = fetch_post_commenters(source["post_url"], max_items=requested)
    except Exception as exc:  # noqa: BLE001 — erreur actor/réseau remontée telle quelle
        raise HTTPException(status_code=502, detail=f"Collecte des commentaires échouée : {exc}")
    credits_balance: int | None = None
    if token and commenters:
        # ok toujours True ici : le pré-check garantit solde >= coût du pire cas >= coût réel.
        _ok, credits_balance = db.debit_credits(
            token, "collect_leads", _lead_collect_credit_cost(len(commenters))
        )
    counts = db.save_leads(token, source, commenters)
    # Scoring ICP (ALE-228) : note les leads fraîchement touchés contre le ciblage.
    _score_leads_for_source(token, source, counts)
    updated = db.update_lead_source(
        token,
        source["id"],
        {
            "comments_count": len(commenters),
            "collected_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    # Journalisation coût (garde-fou ALE-227) : volume récupéré à chaque collecte.
    print(
        f"[leads] source {source['id']} ({source['post_url']}): "
        f"{len(commenters)} commentaire(s) récupéré(s), leads {counts}",
        flush=True,
    )
    return {
        "source": updated or source,
        "comments_count": len(commenters),
        "leads": counts,
        "credits": credits_balance,
    }


@app.get("/me/lead-sources")
def me_lead_sources(token: str = Depends(require_token)) -> dict[str, Any]:
    """Posts sources de prospection de l'utilisateur."""
    return {"sources": db.list_lead_sources(token)}


@app.post("/me/lead-sources")
def add_me_lead_source(payload: LeadSourceRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Importe un post concurrent par lien : verdict lead-magnet + mot-clé, puis
    collecte des commentateurs si lead magnet (leads dédupliqués).

    Garde-fou coût : si une source existe déjà pour ce post, on la renvoie sans
    re-scraper — la recollecte passe par POST /me/lead-sources/{id}/collect.
    """
    url = (payload.url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Colle le lien du post LinkedIn à analyser.")

    existing = db.get_lead_source_by_url(token, url)
    if existing:
        return {"source": existing, "existing": True}

    detail = fetch_post_detail(url)
    if not detail:
        raise HTTPException(
            status_code=422,
            detail="Impossible de lire le post depuis ce lien — vérifie qu'il est public.",
        )
    # L'actor peut renvoyer une URL canonique différente du lien collé : on
    # re-vérifie dessus, sinon un second import violerait l'unicité user+post.
    canonical = detail.get("url") or url
    if canonical != url:
        existing = db.get_lead_source_by_url(token, canonical)
        if existing:
            return {"source": existing, "existing": True}
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503, detail="Classification IA non configurée.")
    try:
        verdict = classify_lead_magnet(detail["text"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Classification lead-magnet échouée : {exc}")

    source = db.add_lead_source(
        token,
        canonical,
        author=detail.get("author"),
        post_text=detail["text"],
        is_lead_magnet=verdict["is_lead_magnet"],
        trigger_keyword=verdict["trigger_keyword"],
    )
    if not source:
        raise HTTPException(status_code=400, detail="Impossible d'enregistrer la source.")

    if not verdict["is_lead_magnet"]:
        return {"source": source, "leads": {"inserted": 0, "updated": 0, "skipped": 0}}
    return _collect_lead_source(token, source, payload.max_comments)


@app.post("/me/lead-sources/{source_id}/collect")
def collect_me_lead_source(
    source_id: str,
    payload: LeadCollectRequest | None = None,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """(Re)collecte explicite des commentateurs d'une source (seul chemin de relance)."""
    source = db.get_lead_source(token, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source introuvable.")
    return _collect_lead_source(token, source, payload.max_comments if payload else None)


@app.delete("/me/lead-sources/{source_id}")
def delete_me_lead_source(source_id: str, token: str = Depends(require_token)) -> dict[str, bool]:
    """Supprime une source (les leads déjà collectés restent)."""
    return {"deleted": db.delete_lead_source(token, source_id)}


@app.get("/me/leads")
def me_leads(token: str = Depends(require_token)) -> dict[str, Any]:
    """Leads de prospection de l'utilisateur — mieux notés d'abord, jamais masqués
    (les écartés « ne pas contacter » restent en bas de liste, cf. ALE-243)."""
    return {"leads": db.list_leads(token)}


class LeadContactStatusRequest(BaseModel):
    contact_status: str
    skip_reason: str | None = Field(default=None, max_length=280)


@app.patch("/me/leads/{lead_id}")
def patch_me_lead(
    lead_id: str, payload: LeadContactStatusRequest, token: str = Depends(require_token)
) -> dict[str, Any]:
    """Curation manuelle d'un lead (ALE-243) : « ne pas contacter » (+ raison courte)
    ou remise dans la liste. Le lead n'est JAMAIS supprimé — il reste visible,
    relégué en bas de la liste (cf. db.list_leads)."""
    if payload.contact_status not in ("to_contact", "skip"):
        raise HTTPException(status_code=422, detail="Statut invalide (to_contact | skip).")
    if not db.get_lead(token, lead_id):
        raise HTTPException(status_code=404, detail="Lead introuvable.")
    updated = db.set_lead_contact_status(token, lead_id, payload.contact_status, payload.skip_reason)
    if not updated:
        raise HTTPException(status_code=400, detail="Mise à jour impossible.")
    return {"lead": updated}


@app.get("/me/lead-targeting")
def me_lead_targeting(token: str = Depends(require_token)) -> dict[str, Any]:
    """Config de ciblage ICP. Si jamais enregistrée, on renvoie un brouillon
    pré-rempli depuis le profil éditorial (client idéal ← audience cible, offre ←
    offre principale) — éditable puis à enregistrer via PUT. On ne réécrit jamais
    dans le profil éditorial (ALE-228)."""
    targeting = db.get_lead_targeting(token)
    if targeting:
        return {"targeting": targeting, "exists": True}
    profile = db.get_editorial_profile(token) or {}
    draft = {
        "ideal_client": profile.get("target_audience") or "",
        "offer": profile.get("core_offer") or "",
        "interest_keywords": [],
        "score_threshold": 60,
        "first_message_instructions": "",
    }
    return {"targeting": draft, "exists": False}


@app.put("/me/lead-targeting")
def update_me_lead_targeting(
    payload: LeadTargetingRequest, token: str = Depends(require_token)
) -> dict[str, Any]:
    """Enregistre la config de ciblage ICP."""
    saved = db.upsert_lead_targeting(token, payload.model_dump(exclude_unset=True))
    if not saved:
        raise HTTPException(status_code=400, detail="Impossible d'enregistrer le ciblage.")
    return {"targeting": saved, "exists": True}


@app.post("/me/leads/rescore")
def rescore_me_leads(token: str = Depends(require_token)) -> dict[str, Any]:
    """Recalcule le score ICP de tous les leads avec le ciblage courant (ALE-228).

    À appeler après une modification du ciblage : change le classement et le
    filtrage par seuil. Sans ciblage enregistré → 400."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503, detail="Scoring IA non configuré.")
    targeting = db.get_lead_targeting(token)
    if not targeting:
        raise HTTPException(status_code=400, detail="Configure d'abord ton ciblage.")
    leads = db.list_leads_for_scoring(token)
    if not leads:
        return {"rescored": 0}

    def _last_signal(lead: dict) -> dict:
        signals = lead.get("signals") or []
        return signals[-1] if signals else {}

    lead_inputs = [
        {
            "headline": l.get("headline"),
            "comment_text": l.get("comment_text"),
            "trigger_keyword": _last_signal(l).get("trigger_keyword"),
            "author": _last_signal(l).get("author"),
        }
        for l in leads
    ]
    scores = score_leads(targeting, lead_inputs)
    scored = [
        {"id": l["id"], "score": s.get("score"), "reason": s.get("reason")}
        for l, s in zip(leads, scores)
    ]
    n = db.update_lead_scores(token, scored)
    return {"rescored": n}


# ── ALE-230 : envoi via Unipile + garde-fous quota ────────────────────────────
# Chaque client connecte SON compte LinkedIn via Unipile (modèle multi-client).
# Deux compteurs séparés (invitations / messages) sont calculés depuis le journal
# `linkedin_outreach_actions` sur des fenêtres glissantes, et bornés par un plafond
# quotidien configurable (défaut 25) + une sécurité hebdo glissante (~100 invit./sem).

UNIPILE_DAILY_CAP_DEFAULT = 25
UNIPILE_WEEKLY_INVITE_CAP_DEFAULT = 100


class UnipileConnectRequest(BaseModel):
    redirect_url: Optional[str] = Field(default=None, max_length=1000)


class UnipileSettingsRequest(BaseModel):
    daily_cap: int | None = Field(default=None, ge=1, le=100)
    weekly_invite_cap: int | None = Field(default=None, ge=1, le=500)
    # ALE-174 — fenêtre d'envoi du moteur cadencé (heures de bureau du client).
    timezone: str | None = Field(default=None, max_length=64)
    send_hour_start: int | None = Field(default=None, ge=0, le=23)
    send_hour_end: int | None = Field(default=None, ge=1, le=24)
    send_days: list[int] | None = Field(default=None)  # ISO : 1 = lundi … 7 = dimanche


class OutreachInviteRequest(BaseModel):
    # ALE-174 — par défaut l'invitation part EN FILE (le moteur choisit le créneau).
    # `immediate` = la soupape « envoyer maintenant », plafonnée par jour.
    immediate: bool = False


class OutreachMessageRequest(BaseModel):
    # Texte final (édité par l'utilisateur). Vide → généré par l'IA côté serveur.
    text: str | None = Field(default=None, max_length=1500)
    immediate: bool = False


class OutreachChatSendRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1500)


def _outreach_quota(account: dict[str, Any], counts: dict[str, int], counts_ok: bool = True) -> dict[str, Any]:
    """État de quota lisible par l'UI : compteurs, plafonds, autorisations + raisons.

    `counts_ok=False` (lecture des compteurs échouée) → fail CLOSED : tout est
    bloqué avec un message clair, jamais autorisé sans compteur fiable (protège
    le compte LinkedIn d'une restriction)."""
    daily_cap = int((account or {}).get("daily_cap") or UNIPILE_DAILY_CAP_DEFAULT)
    weekly_cap = int((account or {}).get("weekly_invite_cap") or UNIPILE_WEEKLY_INVITE_CAP_DEFAULT)
    invites_today = int(counts.get("invites_today", 0))
    messages_today = int(counts.get("messages_today", 0))
    invites_week = int(counts.get("invites_week", 0))

    if not counts_ok:
        unavailable = "Vérification du quota temporairement indisponible — réessaie dans un instant."
        return {
            "daily_cap": daily_cap,
            "weekly_invite_cap": weekly_cap,
            "invites_today": invites_today,
            "messages_today": messages_today,
            "invites_week": invites_week,
            "can_invite": False,
            "can_message": False,
            "invite_blocked_reason": unavailable,
            "message_blocked_reason": unavailable,
            "counts_available": False,
        }

    if invites_week >= weekly_cap:
        invite_reason = (
            f"Sécurité hebdomadaire atteinte ({invites_week}/{weekly_cap} invitations sur 7 jours "
            "glissants). En pause pour protéger le compte — réessaie plus tard."
        )
    elif invites_today >= daily_cap:
        invite_reason = f"Plafond du jour atteint ({invites_today}/{daily_cap} invitations). Réessaie dans 24 h."
    else:
        invite_reason = None

    message_reason = (
        f"Plafond du jour atteint ({messages_today}/{daily_cap} messages). Réessaie dans 24 h."
        if messages_today >= daily_cap
        else None
    )
    return {
        "daily_cap": daily_cap,
        "weekly_invite_cap": weekly_cap,
        "invites_today": invites_today,
        "messages_today": messages_today,
        "invites_week": invites_week,
        "can_invite": invite_reason is None,
        "can_message": message_reason is None,
        "invite_blocked_reason": invite_reason,
        "message_blocked_reason": message_reason,
        "counts_available": True,
    }


def _safe_counts(token: str) -> tuple[dict[str, int], bool]:
    """Compteurs de quota + drapeau de fiabilité. Sur échec de lecture on renvoie
    (zéros, False) : les zéros ne sont JAMAIS utilisés pour autoriser (fail closed
    via `counts_ok=False`), seulement pour l'affichage."""
    try:
        return db.outreach_counts(token), True
    except Exception as exc:  # noqa: BLE001
        print(f"[outreach] lecture des compteurs de quota échouée : {exc}", flush=True)
        return {"invites_today": 0, "messages_today": 0, "invites_week": 0}, False


def _engine_state(token: str, account: dict[str, Any]) -> dict[str, Any]:
    """ALE-174 — état du moteur d'envoi, tel que l'app doit le montrer.

    Contient de quoi répondre à trois questions que l'utilisateur se pose : quand
    partira ma prochaine action, pourquoi elle ne part pas encore, et — le plus
    important — est-ce que le moteur tourne encore. Un cron mort ne peut pas alerter
    sur sa propre mort : c'est ici, côté app, qu'on le détecte (`stalled`)."""
    now = datetime.now(timezone.utc)
    try:
        pending = len(db.list_outreach_queue(token))
    except Exception:  # noqa: BLE001 — l'affichage ne doit pas casser sur une lecture
        pending = 0
    try:
        immediate_used = db.count_immediate_outreach_sends(token)
    except Exception:  # noqa: BLE001
        immediate_used = outreach_engine.IMMEDIATE_DAILY_CAP  # fail closed : soupape fermée
    start, end = outreach_engine.send_hours(account)
    frozen_until = outreach_engine.freeze_until(account)
    return {
        "pending": pending,
        "last_run_at": account.get("last_run_at"),
        "last_run_error": account.get("last_run_error"),
        "stalled": outreach_engine.is_stalled(now, account.get("last_run_at"), pending),
        "frozen": outreach_engine.freeze_active(now, account),
        "freeze_reason": account.get("freeze_reason"),
        "frozen_until": frozen_until.isoformat() if frozen_until else None,
        "warmup_week": outreach_engine.warmup_week(now, account),
        "warmup_cap": outreach_engine.warmup_cap(now, account),
        "warmup_weeks_total": len(outreach_engine.WARMUP_STEPS),
        "next_send_estimate": outreach_engine.estimate_send_at(now, account).isoformat(),
        "immediate_left": max(0, outreach_engine.IMMEDIATE_DAILY_CAP - immediate_used),
        "immediate_cap": outreach_engine.IMMEDIATE_DAILY_CAP,
        "window": {
            "timezone": account.get("timezone") or outreach_engine.DEFAULT_TIMEZONE,
            "hour_start": start,
            "hour_end": end,
            "days": list(outreach_engine.send_days(account)),
        },
    }


def _unipile_outreach_status(token: str) -> dict[str, Any]:
    account = db.get_linkedin_outreach_account(token)
    connected = bool(account and account.get("unipile_account_id"))
    if connected:
        counts, ok = _safe_counts(token)
    else:
        counts, ok = {"invites_today": 0, "messages_today": 0, "invites_week": 0}, True
    return {
        "configured": unipile.enabled(),
        "connected": connected,
        "account_name": (account or {}).get("account_name"),
        "connected_at": (account or {}).get("connected_at"),
        "quota": _outreach_quota(account or {}, counts, ok),
        "engine": _engine_state(token, account or {}) if connected else None,
    }


def _require_outreach_account(token: str) -> dict[str, Any]:
    """Compte Unipile connecté de l'utilisateur, ou 400 explicite."""
    if not unipile.enabled():
        raise HTTPException(status_code=400, detail="Messagerie LinkedIn non configurée côté serveur (Unipile).")
    account = db.get_linkedin_outreach_account(token)
    if not account or not account.get("unipile_account_id"):
        raise HTTPException(status_code=400, detail="Connecte d'abord ton compte LinkedIn de prospection (Mon profil).")
    return account


def _require_owned_chat(account: dict[str, Any], chat_id: str) -> None:
    """Vérifie que la conversation appartient bien au compte Unipile du caller.

    Garde-fou IDOR/multi-tenant : la clé API Unipile est partagée entre tous les
    clients, donc un `chat_id` arbitraire pourrait viser la conversation d'un
    autre utilisateur. On refuse (404) toute conversation dont l'`account_id`
    propriétaire ne correspond pas à celui de l'utilisateur courant."""
    try:
        chat = unipile.get_chat(chat_id)
    except unipile.UnipileError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    owner = unipile.chat_account_id_of(chat)
    if not chat or not owner or owner != account.get("unipile_account_id"):
        raise HTTPException(status_code=404, detail="Conversation introuvable.")


def _lead_message_context(lead: dict[str, Any]) -> dict[str, Any]:
    signals = lead.get("signals") or []
    last = signals[-1] if signals else {}
    return {
        "name": lead.get("name"),
        "headline": lead.get("headline"),
        "comment_text": lead.get("comment_text"),
        "trigger_keyword": last.get("trigger_keyword"),
        "author": last.get("author"),
    }


@app.get("/me/linkedin/outreach/status")
def me_linkedin_outreach_status(token: str = Depends(require_token)) -> dict[str, Any]:
    """Connexion Unipile + état des quotas (compteurs invitations/messages)."""
    return _unipile_outreach_status(token)


@app.post("/me/linkedin/outreach/connect")
def me_linkedin_outreach_connect(
    payload: UnipileConnectRequest, token: str = Depends(require_token)
) -> dict[str, Any]:
    """Lien d'auth hébergée Unipile : le client s'y connecte à son LinkedIn."""
    if not unipile.enabled():
        raise HTTPException(status_code=400, detail="UNIPILE_DSN / UNIPILE_API_KEY manquants côté serveur.")
    user = db.get_user(token) or {}
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Utilisateur inconnu.")
    # Unipile exige `expiresOn` en ISO 8601 UTC MILLIsecondes + suffixe `Z`
    # (pattern `...\.\d{3}Z$`) — pas de microsecondes ni d'offset `+00:00`, sinon
    # 400 « Expected union value ». Lien court-vécu (1 h).
    expires_on = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    try:
        url = unipile.create_hosted_auth_link(
            name=str(user_id),
            success_redirect_url=payload.redirect_url,
            failure_redirect_url=payload.redirect_url,
            expires_on=expires_on,
        )
    except unipile.UnipileError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"auth_url": url}


def _resolve_unipile_account(token: str, user_id: str) -> dict[str, Any] | None:
    """Retrouve le compte Unipile fraîchement connecté par cet utilisateur.

    ⚠️ Piège Unipile : `GET /accounts` renvoie le NOM LinkedIn du compte, pas le
    `name` (=user_id) qu'on a passé à la connexion (celui-ci n'arrive que via le
    webhook notify_url). On tente donc : (1) correspondance exacte par `name` (si
    Unipile l'expose un jour), sinon (2) fallback robuste pour les connexions
    séquentielles/supervisées — le compte le plus récent NON déjà rattaché à un
    autre utilisateur (en gardant le nôtre en cas de reconnexion). Limite assumée :
    2 connexions simultanées pourraient se croiser → durcissement via notify_url."""
    accounts = unipile.list_accounts()
    if not accounts:
        return None

    def _most_recent(items: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not items:
            return None
        return sorted(items, key=lambda a: str(a.get("created_at") or ""), reverse=True)[0]

    exact = [a for a in accounts if a.get("name") == user_id]
    if exact:
        return _most_recent(exact)

    current = db.get_linkedin_outreach_account(token) or {}
    my_id = current.get("unipile_account_id")
    claimed = db.list_claimed_unipile_account_ids()
    candidates = [
        a for a in accounts
        if unipile.account_id_of(a) == my_id or unipile.account_id_of(a) not in claimed
    ]
    return _most_recent(candidates)


@app.post("/me/linkedin/outreach/refresh")
def me_linkedin_outreach_refresh(token: str = Depends(require_token)) -> dict[str, Any]:
    """Retrouve le compte fraîchement connecté et le rattache à l'utilisateur.
    À appeler au retour de la page d'auth Unipile."""
    if not unipile.enabled():
        raise HTTPException(status_code=400, detail="UNIPILE_DSN / UNIPILE_API_KEY manquants côté serveur.")
    user = db.get_user(token) or {}
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Utilisateur inconnu.")
    try:
        account = _resolve_unipile_account(token, str(user_id))
    except unipile.UnipileError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if account:
        db.upsert_linkedin_outreach_account(
            token,
            unipile_account_id=unipile.account_id_of(account),
            account_name=unipile.account_display_name(account),
            status="connected",
        )
    return _unipile_outreach_status(token)


@app.put("/me/linkedin/outreach/settings")
def me_linkedin_outreach_settings(
    payload: UnipileSettingsRequest, token: str = Depends(require_token)
) -> dict[str, Any]:
    """Plafonds de quota + fenêtre d'envoi du moteur (fuseau, heures, jours).

    Ne permet PAS de lever un gel ni de raccourcir le warm-up : ces colonnes ne sont
    pas écrivables par le client (droits de colonne, migration 0048)."""
    _require_outreach_account(token)
    if payload.send_days is not None and not [d for d in payload.send_days if 1 <= d <= 7]:
        raise HTTPException(status_code=422, detail="Choisis au moins un jour d'envoi.")
    db.upsert_linkedin_outreach_account(
        token,
        daily_cap=payload.daily_cap,
        weekly_invite_cap=payload.weekly_invite_cap,
        timezone_name=payload.timezone,
        send_hour_start=payload.send_hour_start,
        send_hour_end=payload.send_hour_end,
        send_days=payload.send_days,
    )
    return _unipile_outreach_status(token)


@app.delete("/me/linkedin/outreach")
def me_linkedin_outreach_disconnect(token: str = Depends(require_token)) -> dict[str, Any]:
    """Délie le compte Unipile de l'utilisateur."""
    db.disconnect_linkedin_outreach(token)
    return _unipile_outreach_status(token)


def _freeze_on_restriction(token: str, message: str) -> None:
    """LinkedIn a signalé une limite/restriction sur un envoi immédiat → on gèle.

    Même réflexe que le moteur : on arrête de taper. Le gel s'écrit en service-role
    (le client n'a pas le droit d'écrire cette colonne — voir migration 0048) et se
    lève tout seul après la période de refroidissement."""
    if not outreach_engine.is_restriction_error(message):
        return
    user = db.get_user(token) or {}
    if user.get("id"):
        db.admin_freeze_outreach_account(str(user["id"]), f"LinkedIn a signalé une limite : {message}")


def _queue_outreach(token: str, lead: dict[str, Any], action_type: str, body: str | None = None) -> dict[str, Any]:
    """ALE-174 — voie NORMALE : l'action entre en file, le moteur choisit son créneau.

    Le client garde la main sur *qui* il contacte ; on ne lui retire que le *moment*.
    C'est ce qui empêche 25 invitations de partir en deux minutes à 3 h du matin."""
    item = db.enqueue_outreach_action(token, lead_id=lead["id"], action_type=action_type, body=body)
    if not item:
        raise HTTPException(status_code=502, detail="Mise en file impossible — réessaie dans un instant.")
    status = _unipile_outreach_status(token)
    return {
        "lead": lead,
        "queued": item,
        "scheduled_for": (status.get("engine") or {}).get("next_send_estimate"),
        "quota": status["quota"],
        "engine": status.get("engine"),
    }


def _require_immediate_slot(token: str, account: dict[str, Any], action_type: str) -> None:
    """Soupape « envoyer maintenant » : autorisée quelques fois par jour seulement.

    Elle saute la plage horaire et le délai entre deux actions — mais JAMAIS le gel,
    les plafonds ni le warm-up : c'est `outreach_engine.decide` qui tranche, la même
    fonction que le moteur. Une soupape qui contourne les garde-fous serait un trou."""
    try:
        used = db.count_immediate_outreach_sends(token)
    except Exception as exc:  # noqa: BLE001 — fail closed : on ferme la soupape
        print(f"[outreach] lecture des envois immédiats échouée : {exc}", flush=True)
        raise HTTPException(status_code=503, detail="Vérification de la soupape indisponible — réessaie dans un instant.") from exc
    if used >= outreach_engine.IMMEDIATE_DAILY_CAP:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Soupape épuisée ({used}/{outreach_engine.IMMEDIATE_DAILY_CAP} envois immédiats sur 24 h). "
                "Mets cette action en file : elle partira au prochain créneau."
            ),
        )
    counts, ok = _safe_counts(token)
    decision = outreach_engine.decide(
        datetime.now(timezone.utc), account, counts,
        action_type=action_type, counts_ok=ok, ignore_pacing=True,
    )
    if not decision.can_send:
        raise HTTPException(status_code=(429 if ok else 503), detail=decision.reason or "Envoi immédiat impossible.")


@app.post("/me/leads/{lead_id}/invite")
def me_lead_invite(
    lead_id: str,
    payload: OutreachInviteRequest | None = None,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Demande de connexion SANS note. Par défaut : MISE EN FILE (ALE-174) — le
    moteur l'enverra dans la plage horaire du client, après un délai aléatoire, en
    respectant le palier de warm-up. `immediate: true` = soupape (plafonnée)."""
    account = _require_outreach_account(token)
    account_id = account["unipile_account_id"]
    lead = db.get_lead(token, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead introuvable.")

    if not (payload and payload.immediate):
        return _queue_outreach(token, lead, "invite")

    _require_immediate_slot(token, account, "invite")

    identifier = unipile.profile_identifier(lead.get("profile_url"))
    if not identifier:
        raise HTTPException(status_code=422, detail="Impossible de lire l'identifiant LinkedIn de ce profil.")
    try:
        profile = unipile.get_user_profile(account_id, identifier)
    except unipile.UnipileError as exc:
        raise HTTPException(status_code=502, detail=f"Profil LinkedIn illisible via Unipile : {exc}") from exc
    provider_id = unipile.provider_id_of(profile)
    if not provider_id:
        raise HTTPException(status_code=502, detail="Unipile n'a pas renvoyé d'identifiant pour ce profil.")

    # Déjà relié (1er niveau) : inutile d'inviter, on passe direct en « connecté ».
    if unipile.is_first_degree(profile):
        updated = db.update_lead_outreach(
            token, lead_id, {"outreach_status": "connected", "provider_id": provider_id}
        )
        return {"lead": updated or lead, "already_connected": True,
                "quota": _outreach_quota(account, *_safe_counts(token))}

    try:
        unipile.send_invitation(account_id, provider_id)
    except unipile.UnipileError as exc:
        db.log_outreach_action(token, action_type="invite", status="failed",
                               lead_id=lead_id, provider_id=provider_id, error=str(exc))
        _freeze_on_restriction(token, str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    db.log_outreach_action(token, action_type="invite", status="sent", lead_id=lead_id, provider_id=provider_id)
    updated = db.update_lead_outreach(
        token, lead_id, {"outreach_status": "invite_sent", "provider_id": provider_id}
    )
    status = _unipile_outreach_status(token)
    return {"lead": updated or lead, "immediate": True, "quota": status["quota"], "engine": status.get("engine")}


@app.post("/me/leads/{lead_id}/check-connection")
def me_lead_check_connection(lead_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Vérifie si l'invitation a été acceptée (network_distance == 1er niveau)."""
    account = _require_outreach_account(token)
    account_id = account["unipile_account_id"]
    lead = db.get_lead(token, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead introuvable.")
    identifier = lead.get("provider_id") or unipile.profile_identifier(lead.get("profile_url"))
    if not identifier:
        raise HTTPException(status_code=422, detail="Identifiant LinkedIn indisponible.")
    try:
        profile = unipile.get_user_profile(account_id, identifier)
    except unipile.UnipileError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    connected = unipile.is_first_degree(profile)
    if connected and lead.get("outreach_status") not in ("connected", "messaged"):
        provider_id = unipile.provider_id_of(profile) or lead.get("provider_id")
        lead = db.update_lead_outreach(
            token, lead_id, {"outreach_status": "connected", "provider_id": provider_id}
        ) or lead
    return {"lead": lead, "connected": connected}


@app.post("/me/leads/{lead_id}/message/preview")
def me_lead_message_preview(lead_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Génère (sans envoyer, sans consommer de quota) le premier message IA à relire."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503, detail="Génération IA non configurée.")
    lead = db.get_lead(token, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead introuvable.")
    targeting = db.get_lead_targeting(token) or {}
    try:
        text = generate_first_message(targeting, _lead_message_context(lead))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Génération du message échouée : {exc}") from exc
    return {"message": text}


@app.post("/me/leads/{lead_id}/message")
def me_lead_message(
    lead_id: str,
    payload: OutreachMessageRequest | None = None,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Premier message au lead (texte édité, ou généré par l'IA). Par défaut : MISE
    EN FILE (ALE-174) — le moteur l'enverra à son créneau. `immediate: true` = soupape.
    L'envoi crée une conversation visible dans l'Inbox LinkedIn."""
    account = _require_outreach_account(token)
    account_id = account["unipile_account_id"]
    lead = db.get_lead(token, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead introuvable.")
    provider_id = lead.get("provider_id")
    if not provider_id:
        raise HTTPException(status_code=400, detail="Envoie d'abord une demande de connexion à ce lead.")

    text = ((payload.text if payload else None) or "").strip()
    if not text:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise HTTPException(status_code=503, detail="Génération IA non configurée.")
        targeting = db.get_lead_targeting(token) or {}
        try:
            text = generate_first_message(targeting, _lead_message_context(lead))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Génération du message échouée : {exc}") from exc

    # Voie normale : le message attend son créneau. Le texte part en file avec lui —
    # il est donc relu et validé par l'utilisateur AVANT d'entrer dans la file, jamais
    # généré à la volée au moment de l'envoi.
    if not (payload and payload.immediate):
        result = _queue_outreach(token, lead, "message", body=text)
        result["message"] = text
        return result

    _require_immediate_slot(token, account, "message")

    try:
        result = unipile.start_new_chat(account_id, provider_id, text)
    except unipile.UnipileError as exc:
        db.log_outreach_action(token, action_type="message", status="failed",
                               lead_id=lead_id, provider_id=provider_id, error=str(exc))
        _freeze_on_restriction(token, str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    chat_id = unipile.chat_id_of(result)
    db.log_outreach_action(token, action_type="message", status="sent",
                           lead_id=lead_id, provider_id=provider_id, chat_id=chat_id)
    updated = db.update_lead_outreach(
        token, lead_id, {"outreach_status": "messaged", "outreach_chat_id": chat_id}
    )
    status = _unipile_outreach_status(token)
    return {"lead": updated or lead, "message": text, "chat_id": chat_id, "immediate": True,
            "quota": status["quota"], "engine": status.get("engine")}


@app.get("/me/linkedin/outreach/queue")
def me_outreach_queue(token: str = Depends(require_token)) -> dict[str, Any]:
    """Actions en attente d'envoi (ALE-174) — ce que le moteur va sortir, et quand."""
    return {"items": db.list_outreach_queue(token)}


@app.delete("/me/linkedin/outreach/queue/{item_id}")
def me_outreach_queue_cancel(item_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Retire une action de la file, tant qu'elle n'est pas partie."""
    item = db.cancel_outreach_queue_item(token, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Action introuvable ou déjà envoyée.")
    return {"item": item, "items": db.list_outreach_queue(token)}


@app.get("/me/linkedin/outreach/chats")
def me_linkedin_outreach_chats(token: str = Depends(require_token)) -> dict[str, Any]:
    """Conversations LinkedIn du compte connecté (onglet LinkedIn de l'Inbox)."""
    account = _require_outreach_account(token)
    try:
        chats = unipile.list_chats(account["unipile_account_id"])
    except unipile.UnipileError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    normalized = [unipile.normalize_chat(c) for c in chats]
    # Nommer les conversations avec le nom du lead : Unipile ne renvoie pas
    # toujours le participant dans la liste des chats (→ fallback « Conversation
    # LinkedIn »). `outreach_chat_id` relie la conversation à son lead scrapé, qui
    # a un vrai nom. On préfère ce nom quand il existe.
    lead_names = db.get_outreach_chat_lead_names(token)
    for chat in normalized:
        lead_name = lead_names.get(chat.get("id"))
        if lead_name:
            chat["name"] = lead_name
    return {"chats": normalized}


@app.get("/me/linkedin/outreach/chats/{chat_id}/messages")
def me_linkedin_outreach_chat_messages(
    chat_id: str, token: str = Depends(require_token)
) -> dict[str, Any]:
    """Messages d'une conversation LinkedIn."""
    account = _require_outreach_account(token)
    _require_owned_chat(account, chat_id)
    try:
        msgs = unipile.list_chat_messages(chat_id)
    except unipile.UnipileError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    normalized = [unipile.normalize_message(m) for m in msgs]
    # Unipile renvoie les messages les plus récents d'abord ; l'Inbox les affiche
    # de haut en bas (auto-scroll vers le bas) → tri chronologique ascendant.
    normalized.sort(key=lambda m: str(m.get("created_at") or ""))
    return {"messages": normalized}


@app.post("/me/linkedin/outreach/chats/{chat_id}/messages")
def me_linkedin_outreach_chat_send(
    chat_id: str, payload: OutreachChatSendRequest, token: str = Depends(require_token)
) -> dict[str, Any]:
    """Répond dans une conversation LinkedIn (compté dans le quota messages)."""
    account = _require_outreach_account(token)
    _require_owned_chat(account, chat_id)
    counts, ok = _safe_counts(token)
    quota = _outreach_quota(account, counts, ok)
    if not quota["can_message"]:
        raise HTTPException(status_code=(429 if ok else 503), detail=quota["message_blocked_reason"] or "Plafond de messages atteint.")
    try:
        unipile.send_message(chat_id, payload.text.strip())
    except unipile.UnipileError as exc:
        db.log_outreach_action(token, action_type="message", status="failed", chat_id=chat_id, error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    db.log_outreach_action(token, action_type="message", status="sent", chat_id=chat_id)
    return {"ok": True, "quota": _outreach_quota(account, *_safe_counts(token))}


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


# ── ALE-157 : Weekly posts (UI opt-in + schedule) ────────────────────────────

class WeeklyPostsEnabledRequest(BaseModel):
    enabled: bool


class WeeklyScheduleSlot(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6)
    hour: int = Field(9, ge=0, le=23)
    timezone: str = "Europe/Paris"


class WeeklyScheduleRequest(BaseModel):
    schedule: list[WeeklyScheduleSlot] = []


@app.get("/me/weekly-posts")
def get_me_weekly_posts(token: str = Depends(require_token)) -> dict[str, Any]:
    """Return the user's weekly-posts opt-in state and schedule."""
    return {
        "enabled": db.get_weekly_posts_enabled(token),
        "schedule": db.get_weekly_schedule(token),
    }


@app.post("/me/weekly-posts/enabled")
def set_me_weekly_posts_enabled(
    payload: WeeklyPostsEnabledRequest,
    token: str = Depends(require_token),
) -> dict[str, bool]:
    """Toggle the weekly-posts opt-in for the authenticated user."""
    db.set_weekly_posts_enabled(token, payload.enabled)
    return {"enabled": payload.enabled}


@app.put("/me/weekly-posts/schedule")
def put_me_weekly_posts_schedule(
    payload: WeeklyScheduleRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Replace the user's weekly-posts schedule."""
    slots = [s.model_dump() for s in payload.schedule]
    saved = db.set_weekly_schedule(token, slots)
    return {"schedule": saved}


def _weekly_run_bg(user_id: str) -> None:
    """Génère les posts hebdo d'un utilisateur en tâche de fond (déclenchement manuel)."""
    try:
        created = weekly_posts.run_for_user(user_id)
        print(f"[weekly manual] {user_id}: {created} post(s) créé(s)")
    except Exception as exc:  # noqa: BLE001
        print(f"[weekly manual] {user_id}: échec {exc}", file=sys.stderr)


@app.post("/me/weekly-posts/run")
def run_me_weekly_posts_now(token: str = Depends(require_token)) -> dict[str, Any]:
    """Déclenche manuellement la génération des posts de la semaine (comme le cron du vendredi).

    Génère les posts de la semaine suivante pour l'utilisateur courant et les envoie
    sur Slack à valider. Lancé en tâche de fond (peut prendre ~1 min) ; idempotent :
    ne recrée pas un post déjà planifié pour une date.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY manquant côté serveur.")
    if not db.admin_enabled():
        raise HTTPException(status_code=400, detail="Génération manuelle indisponible (service-role serveur manquant).")
    user = db.get_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session invalide.")
    user_id = user["id"]
    if not db.get_weekly_schedule_for_user(user_id):
        raise HTTPException(status_code=400, detail="Choisis au moins un jour de publication avant de générer.")
    if not db.get_corpus_for_user(user_id):
        raise HTTPException(status_code=400, detail="Aucun influenceur analysé : lance d'abord une analyse pour nourrir la génération.")
    threading.Thread(target=_weekly_run_bg, args=(user_id,), daemon=True).start()
    return {"started": True}


# --------------------------------------------------------------------------- #
# Monitoring influenceurs (ALE-214) — suivi + détection à la demande
# --------------------------------------------------------------------------- #

FOLLOWED_INFLUENCERS_CAP = int(os.environ.get("FOLLOWED_INFLUENCERS_CAP", "5"))


class FollowInfluencerRequest(BaseModel):
    handle: str = Field(..., min_length=2, max_length=200)
    platform: str = Field(default="linkedin", max_length=30)


@app.get("/me/followed-influencers")
def me_followed_influencers(token: str = Depends(require_token)) -> dict[str, Any]:
    """Influenceurs suivis par l'utilisateur + plafond."""
    return {"followed": db.list_followed_influencers(token), "cap": FOLLOWED_INFLUENCERS_CAP}


@app.post("/me/followed-influencers")
def follow_me_influencer(payload: FollowInfluencerRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Suit un influenceur (cap FOLLOWED_INFLUENCERS_CAP — garde-fou coûts Apify)."""
    handle = payload.handle.strip()
    current = db.list_followed_influencers(token)
    existing = next(
        (f for f in current if f.get("handle") == handle and f.get("platform") == payload.platform),
        None,
    )
    if existing:
        return existing
    if len(current) >= FOLLOWED_INFLUENCERS_CAP:
        raise HTTPException(
            status_code=422,
            detail=f"Tu suis déjà {FOLLOWED_INFLUENCERS_CAP} influenceurs (maximum). Retire-en un avant d'en ajouter.",
        )
    row = db.follow_influencer(token, handle, payload.platform)
    if not row:
        raise HTTPException(status_code=400, detail="Impossible de suivre cet influenceur.")
    return row


@app.delete("/me/followed-influencers/{follow_id}")
def unfollow_me_influencer(follow_id: str, token: str = Depends(require_token)) -> dict[str, bool]:
    """Ne plus suivre un influenceur."""
    return {"deleted": db.unfollow_influencer(token, follow_id)}


def _monitor_run_bg(user_id: str) -> None:
    """Détection des nouveaux posts en tâche de fond (bouton « Vérifier maintenant »)."""
    try:
        totals = influencer_monitor.run_for_user(user_id)
        print(f"[monitor manual] {user_id}: {totals}")
    except Exception as exc:  # noqa: BLE001
        print(f"[monitor manual] {user_id}: échec {exc}", file=sys.stderr)


@app.post("/me/influencer-monitor/run")
def run_me_influencer_monitor(token: str = Depends(require_token)) -> dict[str, Any]:
    """Déclenche manuellement la détection des nouveaux posts (comme le cron).

    Tâche de fond (quelques dizaines de secondes par influenceur suivi).
    Idempotent : les posts déjà connus ne sont pas dupliqués (dédup URL).
    """
    if not db.admin_enabled():
        raise HTTPException(status_code=400, detail="Détection indisponible (service-role serveur manquant).")
    if not os.environ.get("APIFY_TOKEN"):
        raise HTTPException(status_code=400, detail="APIFY_TOKEN manquant côté serveur.")
    user = db.get_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session invalide.")
    if not db.list_followed_handles_for_user(user["id"]):
        raise HTTPException(status_code=400, detail="Suis d'abord au moins un influenceur (onglet Veille › Mes influenceurs).")
    threading.Thread(target=_monitor_run_bg, args=(user["id"],), daemon=True).start()
    return {"started": True}


@app.get("/me/monitoring/feed")
def me_monitoring_feed(token: str = Depends(require_token)) -> dict[str, Any]:
    """Fil de veille (ALE-215) : posts récents des influenceurs suivis.

    Lecture seule en base (aucun scrape, aucun LLM) — la détection est faite
    par le cron ou le bouton « Vérifier les nouveaux posts ».
    """
    if not db.admin_enabled():
        raise HTTPException(status_code=400, detail="Veille indisponible (service-role serveur manquant).")
    user = db.get_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session invalide.")
    followed = db.list_followed_handles_for_user(user["id"])
    return {
        "posts": db.get_monitoring_feed_for_user(user["id"]),
        "followed_count": len(followed),
    }


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

    # ALE-156 : seed = lien d'annonce → on ancre le post sur le bien + sa photo.
    image_url = source_url = None
    if seed_text and is_listing_url(seed_text):
        try:
            preview = fetch_listing_preview(seed_text, download_image=False)
            seed_text = build_listing_topic(preview)
            image_url = preview.get("image_url")
            source_url = preview.get("source_url")
        except ListingError:
            seed_text = None  # échec propre : post benchmark sans image

    # ALE-136 : régénérer produit un VRAI post (postable), comme le cron.
    posts = generate_posts(
        seed_text, top_posts, benchmark, user_context=user_context, count=1,
        reference_posts=db.pick_reference_posts(token) or None,
    )
    if not posts:
        raise HTTPException(status_code=500, detail="La génération n'a produit aucun post.")

    post = posts[0]
    markdown = post.get("post") or ""
    idea_row = db.replace_daily_idea(
        token, markdown, today, post=post, image_url=image_url, source_url=source_url
    )

    if seed:
        db.mark_seed_used_by_token(token, seed["id"])

    return {
        "idea": idea_row or {"idea_markdown": markdown, "idea_date": today, "post_text": markdown},
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
    state: str = ""  # CSRF token généré par /connect ; vide = flux sans state (rétro-compat dev)


class SlackSendIdeasRequest(BaseModel):
    idea_ids: list[str] = Field(..., min_length=1, max_length=10)


class SlackSendPostsRequest(BaseModel):
    post_id: str = Field(..., min_length=1)
    content: Optional[str] = None
    images: list[LinkedInImageRequest] = Field(default_factory=list, max_length=zernio.MAX_LINKEDIN_IMAGES)


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
    user = db.get_user(token) or {}
    user_id = user.get("id", "")
    state_token = secrets.token_urlsafe(32)
    _slack_oauth_states[state_token] = {"user_id": user_id, "expires": time.time() + 600}
    try:
        auth_url = slack_client.build_oauth_url(payload.redirect_uri, state=state_token)
    except slack_client.SlackError as exc:
        _slack_oauth_states.pop(state_token, None)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"auth_url": auth_url, "state": state_token}


@app.post("/me/integrations/slack/callback")
def slack_callback(
    payload: SlackCallbackRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Exchange an OAuth code for tokens and persist the Slack integration."""
    if not slack_client.enabled():
        raise HTTPException(status_code=400, detail="SLACK_CLIENT_ID / SLACK_CLIENT_SECRET manquants sur le serveur.")
    if payload.state:
        stored = _slack_oauth_states.pop(payload.state, None)
        if not stored or time.time() > stored["expires"]:
            raise HTTPException(status_code=400, detail="État OAuth invalide ou expiré.")
        current_user = db.get_user(token) or {}
        if stored["user_id"] and stored["user_id"] != current_user.get("id"):
            raise HTTPException(status_code=400, detail="État OAuth ne correspond pas à l'utilisateur authentifié.")
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

    # Si l'utilisateur a édité le post dans l'app sans cliquer « Sauvegarder »,
    # le front envoie le texte courant : on le persiste avant l'envoi pour que
    # Slack (et la publication validée derrière) utilisent bien le texte affiché.
    content = (payload.content or "").strip()
    if content and content != (post.get("post") or ""):
        updated = db.update_generated_post(token, payload.post_id, new_post=content)
        post = updated or {**post, "post": content}

    # Images jointes (annonce / upload) → URLs publiques Zernio, affichées sur
    # Slack. Persistées sur le post pour survivre aux clics Valider/Modifier (qui
    # rechargent le post depuis la base). Non bloquant : un échec d'upload média
    # n'empêche pas l'envoi du texte.
    if payload.images:
        try:
            media_items = zernio.prepare_image_media_items(_image_payload(payload.images))
        except zernio.ZernioError:
            media_items = []
        if media_items:
            db.update_generated_post_media(token, payload.post_id, media_items)
            post = {**post, "media_items": media_items}

    try:
        slack_client.send_post_for_validation(bot_token, channel_id, post)
    except slack_client.SlackError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    db.set_post_slack_pending(token, [payload.post_id])
    return {"sent": True}


def _find_slack_owner(slack_user_id: str, fetch) -> tuple[dict | None, dict | None]:
    """Resolve which linked app account owns the item targeted by a Slack action.

    `user_integrations` n'est pas unique par utilisateur Slack : un même compte
    Slack peut être relié à plusieurs comptes app (plusieurs emails). On teste
    chaque compte relié et on retourne (intégration, item) du propriétaire —
    sinon la pop-up d'édition s'ouvre vide et les validations tombent dans le vide.
    """
    for integration in db.get_users_by_slack_id(slack_user_id):
        item = fetch(integration["user_id"])
        if item:
            return integration, item
    return None, None


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

    # Modal submission: the user edited a post's text from Slack.
    # Deux flux symétriques : posts programmés (ALE-149) et posts envoyés directement.
    if data.get("type") == "view_submission":
        view = data.get("view") or {}
        callback_id = view.get("callback_id")
        if callback_id not in ("edit_scheduled_post_modal", "edit_post_modal"):
            return {"response_action": "clear"}
        slack_user_id = (data.get("user") or {}).get("id", "")
        try:
            meta = json.loads(view.get("private_metadata") or "{}")
        except Exception:
            meta = {}
        post_id = meta.get("post_id", "")
        channel_id_w = meta.get("channel_id", "")
        ts_w = meta.get("message_ts", "")
        values = (view.get("state") or {}).get("values") or {}
        new_text = (
            ((values.get("post_text_block") or {}).get("post_text_input") or {}).get("value") or ""
        ).strip()
        if not (post_id and new_text):
            return {"response_action": "clear"}
        if callback_id == "edit_scheduled_post_modal":
            integration, _item = _find_slack_owner(
                slack_user_id, lambda uid: db.get_scheduled_post_for_user(post_id, uid)
            )
        else:
            integration, _item = _find_slack_owner(
                slack_user_id, lambda uid: db.get_generated_post_for_user(post_id, uid)
            )
        if not integration:
            return {"response_action": "clear"}
        bot_token_w = integration.get("access_token", "")
        if callback_id == "edit_scheduled_post_modal":
            updated = db.update_scheduled_post_text_admin(post_id, integration["user_id"], new_text)
            if not updated:
                return {
                    "response_action": "errors",
                    "errors": {"post_text_block": "Ce post n'est plus modifiable (déjà publié ou annulé)."},
                }
            if bot_token_w and channel_id_w and ts_w:
                try:
                    slack_client.update_scheduled_post_message(bot_token_w, channel_id_w, ts_w, updated, "edited")
                except slack_client.SlackError:
                    pass
        else:  # edit_post_modal (post envoyé directement)
            updated = db.update_generated_post_text_admin(post_id, integration["user_id"], new_text)
            if not updated:
                return {
                    "response_action": "errors",
                    "errors": {"post_text_block": "Ce post n'est plus modifiable."},
                }
            if bot_token_w and channel_id_w and ts_w:
                try:
                    slack_client.update_post_message(bot_token_w, channel_id_w, ts_w, updated, "edited")
                except slack_client.SlackError:
                    pass
        return {"response_action": "clear"}

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

    # Un utilisateur Slack peut être relié à plusieurs comptes app : chaque
    # branche résout le compte propriétaire de l'item via _find_slack_owner.
    if action_id in ("validate_idea", "decline_idea"):
        status = "validated" if action_id == "validate_idea" else "declined"
        integration = None
        for candidate in db.get_users_by_slack_id(slack_user_id):
            if db.update_idea_slack_status(item_id, candidate["user_id"], status):
                integration = candidate
                break
        if integration:
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
        integration, post = _find_slack_owner(
            slack_user_id, lambda uid: db.get_generated_post_for_user(item_id, uid)
        )
        if integration and post:
            user_id_w = integration["user_id"]
            bot_token_w = integration.get("access_token", "")
            channel_id_w = (data.get("channel") or {}).get("id", "")
            ts_w = (data.get("message") or {}).get("ts", "")

            if action_id == "reject_post":
                db.update_post_slack_status(item_id, user_id_w, "rejected")
                if bot_token_w and channel_id_w and ts_w:
                    try:
                        slack_client.update_post_message(bot_token_w, channel_id_w, ts_w, post, "rejected")
                    except slack_client.SlackError:
                        pass
            else:
                # Valider un post « envoi direct » = le publier immédiatement sur
                # LinkedIn (via Zernio), comme le cron le fait pour les posts
                # programmés. Sans ce câblage, la validation ne faisait que poser
                # un badge et le post ne partait jamais.
                db.update_post_slack_status(item_id, user_id_w, "validated")
                display_status = "published"
                error_detail = ""
                if post.get("zernio_post_id"):
                    # Déjà publié (webhook rejouée par Slack) → ne pas republier.
                    pass
                elif not zernio.enabled():
                    display_status = "publish_error"
                    error_detail = "Publication LinkedIn indisponible côté serveur."
                else:
                    account_id = db.get_zernio_account_for_user(user_id_w)
                    if not account_id:
                        display_status = "publish_error"
                        error_detail = "Aucun compte LinkedIn connecté."
                    else:
                        try:
                            media_items = zernio.prepare_image_media_items(post.get("media_items") or [])
                            result = zernio.create_post(
                                post.get("post") or "",
                                account_id,
                                publish_now=True,
                                media_items=media_items,
                            )
                            z_post = result.get("post") or result
                            db.mark_generated_post_published(item_id, user_id_w, (z_post or {}).get("_id"))
                        except Exception as exc:
                            display_status = "publish_error"
                            error_detail = str(exc)
                if bot_token_w and channel_id_w and ts_w:
                    try:
                        slack_client.update_post_message(
                            bot_token_w, channel_id_w, ts_w, post, display_status, error=error_detail
                        )
                    except slack_client.SlackError:
                        pass

    elif action_id == "edit_post":
        # Ouvre la modal d'édition immédiatement — le trigger_id expire en ~3 s.
        integration, post = _find_slack_owner(
            slack_user_id, lambda uid: db.get_generated_post_for_user(item_id, uid)
        )
        if integration and post:
            bot_token_w = integration.get("access_token", "")
            trigger_id = data.get("trigger_id", "")
            channel_id_w = (data.get("channel") or {}).get("id", "")
            ts_w = (data.get("message") or {}).get("ts", "")
            if bot_token_w and trigger_id:
                try:
                    slack_client.open_generated_post_edit_modal(bot_token_w, trigger_id, post, channel_id_w, ts_w)
                except slack_client.SlackError:
                    pass

    elif action_id == "edit_scheduled_post":
        # Open the edit modal immediately — the trigger_id expires in ~3 s (ALE-149).
        integration, scheduled = _find_slack_owner(
            slack_user_id, lambda uid: db.get_scheduled_post_for_user(item_id, uid)
        )
        if integration and scheduled:
            bot_token_w = integration.get("access_token", "")
            trigger_id: str = data.get("trigger_id", "")
            channel_id_w = (data.get("channel") or {}).get("id", "")
            ts_w = (data.get("message") or {}).get("ts", "")
            if bot_token_w and trigger_id:
                try:
                    slack_client.open_post_edit_modal(bot_token_w, trigger_id, scheduled, channel_id_w, ts_w)
                except slack_client.SlackError:
                    pass

    elif action_id in ("validate_scheduled_post", "decline_scheduled_post"):
        status = "validated" if action_id == "validate_scheduled_post" else "declined"
        integration, scheduled = _find_slack_owner(
            slack_user_id, lambda uid: db.get_scheduled_post_for_user(item_id, uid)
        )
        if integration and scheduled:
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


@app.post("/generate-image/prompt")
def generate_image_prompt(payload: GenerateImageRequest, token: Optional[str] = Depends(optional_token)) -> dict[str, Any]:
    """Prépare le prompt d'illustration proposé à l'utilisateur avant génération.

    Étape 1 du flux : le prompt est affiché dans une pop-up, l'utilisateur peut
    l'ajuster puis valider (l'image n'est générée — et débitée — qu'à l'étape 2).
    """
    try:
        from src.image_gen import build_image_prompt
        return {"prompt": build_image_prompt(payload.post_text)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/generate-image/jobs")
def create_image_job(payload: GenerateImageRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Lance une génération d'image IA en arrière-plan (file d'attente — ALE-261).

    Non bloquant : on vérifie les préconditions (clé OpenAI, solde, référence),
    on crée le job et on lance le thread, puis on rend la main immédiatement.
    Le frontend récupère le résultat via GET /generate-image/jobs — l'image
    rejoint le bloc de post identifié par `target_key` même si la pop-up a été
    fermée entre-temps (fermer la page ne perd plus rien, ALE-261). Les crédits
    ne sont débités qu'à la complétion réussie (cf. `src.jobs.process_image_job`).
    """
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY manquant dans .env")
    if not payload.target_key:
        raise HTTPException(status_code=400, detail="target_key manquant.")

    # Pré-check fail-closed du solde (ALE-270) : un solde illisible ou
    # insuffisant ne doit pas lancer un job qu'on ne saurait pas facturer.
    cost = db.CREDIT_COSTS["generate_image"]
    try:
        info = db.get_user_credits(token)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Vérification du solde impossible, réessaie dans un instant ({exc}).")
    if info.get("enabled") and info.get("balance", 0) < cost:
        raise HTTPException(status_code=402, detail=f"Crédits insuffisants (solde : {info.get('balance', 0)}). Génération d'image = {cost} crédit(s).")

    # Vérif immédiate (feedback rapide) ; le thread revérifie avant de
    # télécharger l'image (course possible entre la création et le traitement).
    if payload.reference_template_id:
        template = db.get_post_template(token, payload.reference_template_id)
        if not template or not template.get("image_url"):
            raise HTTPException(status_code=404, detail="Template introuvable ou sans image de référence.")

    job = db.create_image_job(token, payload.post_text, payload.prompt, payload.reference_template_id, payload.target_key)
    if not job:
        raise HTTPException(status_code=500, detail="Création du job d'image impossible.")
    start_image_job_thread(token, job["id"])
    return job


@app.get("/generate-image/jobs")
def list_image_jobs(token: str = Depends(require_token)) -> list[dict[str, Any]]:
    """Liste les jobs de génération d'image de l'utilisateur (plus récents d'abord)."""
    return db.list_image_jobs(token)


@app.get("/generate-image/jobs/{job_id}")
def get_image_job(job_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Récupère un job de génération d'image (pour le polling du frontend)."""
    job = db.get_image_job(token, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job de génération d'image introuvable.")
    return job


@app.post("/generate-image/jobs/{job_id}/cancel")
def cancel_image_job(job_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Annule un job de génération d'image encore en attente/en cours."""
    job = db.cancel_image_job(token, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job de génération d'image introuvable.")
    return job


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

    # Débit des crédits à l'avance : 20 crédits par influenceur de la série.
    # Atomique (fonction Postgres debit_credits). Si le solde est insuffisant,
    # la série n'est pas créée. Pas de remboursement auto si un profil échoue.
    ok, balance = db.debit_credits(token, "analyze_job", len(urls))
    if not ok:
        cost = db.CREDIT_COSTS["analyze_job"] * len(urls)
        raise HTTPException(
            status_code=402,
            detail=(
                f"Crédits insuffisants (solde : {balance}). "
                f"Analyse de {len(urls)} profil(s) = {cost} crédit(s)."
            ),
        )

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
    job["credits"] = balance
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
    """Relance le traitement des profils non terminés (après un redémarrage serveur).

    Les profils en échec ont été remboursés au moment de l'échec : les retenter
    est re-débité ici. Les profils jamais soldés (pending/running, donc jamais
    remboursés) se relancent sans nouveau débit.
    """
    job = db.get_job(token, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Série introuvable.")
    items = job.get("items", [])
    retry_errors = [it for it in items if it.get("status") == "error"]
    if retry_errors:
        ok, balance = db.debit_credits(token, "analyze_job", len(retry_errors))
        if not ok:
            cost = db.CREDIT_COSTS["analyze_job"] * len(retry_errors)
            raise HTTPException(
                status_code=402,
                detail=(
                    f"Crédits insuffisants pour relancer {len(retry_errors)} profil(s) "
                    f"en échec ({cost} crédit(s), solde : {balance})."
                ),
            )
        # Repasse les items re-débités en `pending` : s'ils échouent à nouveau
        # (ou que la série meurt), la transition d'échec les remboursera.
        for it in retry_errors:
            db.update_job_item(token, it["id"], status="pending", error=None)
            it["status"] = "pending"
    pending = [it for it in items if it.get("status") not in ("done", "cancelled")]
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


# ---------------------------------------------------------------------------
# Agent de qualification Instagram — transport ManyChat (ALE-195 / 201)
# ---------------------------------------------------------------------------

def _verify_manychat_secret(request: Request, expected: str | None = None) -> None:
    """Fail-closed : le webhook n'accepte que les appels portant le bon secret.

    Le secret est passé en en-tête `X-ManyChat-Secret` (l'action « External
    Request » ManyChat permet les en-têtes custom). On évite volontairement le
    query-string : il finirait en clair dans les access logs. `expected` = secret
    de l'utilisateur (multi-client) ; sinon le secret global (webhook legacy). Si
    aucun secret n'est configuré, on refuse tout (pas de webhook ouvert par défaut).
    """
    expected = expected or os.environ.get("MANYCHAT_WEBHOOK_SECRET")
    if not expected:
        raise HTTPException(status_code=503, detail="Webhook ManyChat non configuré.")
    provided = request.headers.get("X-ManyChat-Secret") or ""
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Secret ManyChat invalide.")


def _public_base_url(request: Request) -> str:
    """URL publique du backend pour construire l'URL de webhook montrée au client.

    Render expose `RENDER_EXTERNAL_URL` ; sinon on dérive de la requête (en
    forçant https, le backend étant servi derrière un proxy TLS).
    """
    base = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("PUBLIC_BACKEND_URL")
    if base:
        return base.rstrip("/")
    url = str(request.base_url).rstrip("/")
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    return url


async def _process_manychat_inbound(request: Request, owner: str) -> dict[str, Any]:
    """Traiter un DM entrant ManyChat pour le compte `owner` (routage résolu en amont).

    Partagé par le webhook legacy (mono-compte via IG_OWNER_USER_ID) et le webhook
    personnel par utilisateur (multi-client). Persiste le message via service-role
    scellé sur `owner`, déclenche la génération de réponse en tâche de fond.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Corps JSON invalide.")

    parsed = manychat.parse_inbound(payload if isinstance(payload, dict) else {})
    if not parsed["prospect_id"]:
        raise HTTPException(status_code=400, detail="prospect_id (subscriber_id) manquant.")

    if not db.admin_enabled():
        raise HTTPException(status_code=503, detail="Service-role Supabase indisponible.")

    conv = db.get_or_create_ig_conversation_admin(
        owner, parsed["prospect_id"], parsed["prospect_name"] or None
    )
    if not conv:
        raise HTTPException(status_code=500, detail="Impossible de créer la conversation.")

    if parsed["text"]:
        msg = db.add_ig_message_admin(
            owner, conv["id"], role="in", source="prospect", text=parsed["text"], kind="text"
        )
        # Génère la réponse suggérée en tâche de fond (ALE-202) — ne bloque pas
        # l'accusé de réception à ManyChat. L'envoi reste manuel (supervisé, 204).
        if msg:
            ig_agent.generate_draft_async(owner, conv["id"], msg["id"], parsed["text"])
        return {"ok": True, "conversation_id": conv["id"]}

    if parsed["audio_url"]:
        # Note vocale : transcription Whisper en tâche de fond → persiste comme
        # message texte → génère le draft (ALE-203). Ne bloque pas l'accusé ManyChat.
        ig_agent.handle_inbound_voice_async(owner, conv["id"], parsed["audio_url"])
        return {"ok": True, "conversation_id": conv["id"], "pending_audio": True}

    raise HTTPException(status_code=400, detail="Message vide (ni texte ni audio).")


@app.post("/manychat/webhooks/inbound")
async def manychat_inbound_webhook(request: Request) -> dict[str, Any]:
    """Webhook ManyChat legacy — compte propriétaire unique (IG_OWNER_USER_ID).

    Conservé pour le compte mono-compte historique (secret + owner via env). Les
    clients multi-comptes utilisent leur URL personnelle `…/inbound/{token}`.
    """
    _verify_manychat_secret(request)
    owner = db.ig_owner_user_id()
    if not owner:
        raise HTTPException(status_code=503, detail="IG_OWNER_USER_ID non configuré.")
    return await _process_manychat_inbound(request, owner)


@app.post("/manychat/webhooks/inbound/{webhook_token}")
async def manychat_inbound_webhook_personal(webhook_token: str, request: Request) -> dict[str, Any]:
    """Webhook ManyChat par utilisateur (multi-client).

    Le slug d'URL identifie le compte app du client ; on vérifie ensuite le
    secret propre à ce client dans `X-ManyChat-Secret`, puis on route le DM vers
    SON inbox. Aucune configuration serveur par client : tout est en base.
    """
    integ = db.get_ig_manychat_by_webhook_token_admin(webhook_token)
    if not integ:
        raise HTTPException(status_code=404, detail="Webhook ManyChat inconnu.")
    _verify_manychat_secret(request, expected=integ.get("webhook_secret"))
    return await _process_manychat_inbound(request, integ["user_id"])


class IgSendRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


@app.get("/me/ig/conversations")
def me_ig_conversations(token: str = Depends(require_token)) -> list[dict[str, Any]]:
    """Lister les conversations IG de l'utilisateur (RLS)."""
    return db.list_ig_conversations(token)


@app.get("/me/ig/conversations/{conversation_id}/messages")
def me_ig_messages(
    conversation_id: str, token: str = Depends(require_token)
) -> list[dict[str, Any]]:
    """Lister les messages d'une conversation IG de l'utilisateur (RLS)."""
    if not db.get_ig_conversation(token, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation introuvable.")
    return db.list_ig_messages(token, conversation_id)


@app.post("/me/ig/conversations/{conversation_id}/send")
def me_ig_send(
    conversation_id: str,
    payload: IgSendRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Envoyer un message texte au prospect (envoi supervisé) + le persister.

    Vérifie la propriété (RLS) et la fenêtre de réponse 24 h avant d'appeler
    ManyChat. Point d'entrée réutilisé par l'inbox in-app (ALE-204).
    """
    conv = db.get_ig_conversation(token, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation introuvable.")
    return {"ok": True, "message": _ig_send_to_conversation(token, conv, payload.text)}


def _ig_send_to_conversation(token: str, conv: dict, text: str) -> dict | None:
    """Envoyer un texte au prospect + persister le message sortant (envoi supervisé).

    Vérifie la fenêtre 24 h, appelle ManyChat, persiste le message `out`.
    Levée d'HTTPException en cas de fenêtre expirée / ManyChat KO / non configuré.
    """
    expires = conv.get("window_expires_at")
    if expires:
        try:
            exp_dt = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
            if exp_dt < datetime.now(timezone.utc):
                raise HTTPException(
                    status_code=409,
                    detail="Fenêtre de réponse 24 h expirée : envoi non conforme.",
                )
        except (ValueError, TypeError):
            pass
    # Conversation de simulation (page de test ManyChat) : on persiste sans
    # appeler l'API ManyChat — le prospect n'existe pas côté middleware.
    if not ig_agent.is_test_prospect(conv.get("prospect_id")):
        # Multi-client : on envoie avec la clé du compte ManyChat de l'utilisateur ;
        # repli sur la clé globale (compte propriétaire legacy) si pas de connexion.
        integ = db.get_ig_manychat(token)
        api_token = (integ or {}).get("access_token")
        if not api_token and not manychat.enabled():
            raise HTTPException(
                status_code=503,
                detail="Aucun compte ManyChat relié : connecte ta clé API ManyChat.",
            )
        try:
            manychat.send_text(conv["prospect_id"], text, api_token=api_token)
        except manychat.ManyChatError as exc:
            raise HTTPException(status_code=502, detail=f"Envoi ManyChat échoué : {exc}")
    return db.add_ig_message(
        token, conv["id"], role="out", source="human", text=text, kind="text"
    )


@app.get("/me/ig/conversations/{conversation_id}/drafts")
def me_ig_drafts(
    conversation_id: str, token: str = Depends(require_token)
) -> list[dict[str, Any]]:
    """Lister les réponses suggérées d'une conversation (RLS)."""
    if not db.get_ig_conversation(token, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation introuvable.")
    return db.list_ig_drafts(token, conversation_id)


class IgDraftSendRequest(BaseModel):
    text: str | None = Field(default=None, max_length=4000)


@app.post("/me/ig/drafts/{draft_id}/send")
def me_ig_draft_send(
    draft_id: str,
    payload: IgDraftSendRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Valider/éditer puis envoyer une réponse suggérée (envoi supervisé, ALE-204).

    `text` fourni = version éditée par Alex (statut `edited`) ; sinon la
    suggestion telle quelle (statut `approved`). Envoie via ManyChat + persiste
    le message sortant, puis marque le draft `sent`.
    """
    draft = db.get_ig_draft(token, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Réponse suggérée introuvable.")
    if draft.get("status") == "sent":
        raise HTTPException(status_code=409, detail="Réponse déjà envoyée.")
    conv = db.get_ig_conversation(token, draft["conversation_id"])
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation introuvable.")
    edited = payload.text is not None and payload.text.strip() != (draft.get("reply") or "").strip()
    text = (payload.text if payload.text is not None else draft.get("reply") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Réponse vide.")
    msg = _ig_send_to_conversation(token, conv, text)
    db.update_ig_draft(token, draft_id, status="sent", reply=text if edited else None)
    return {"ok": True, "message": msg, "edited": edited}


@app.post("/me/ig/drafts/{draft_id}/reject")
def me_ig_draft_reject(draft_id: str, token: str = Depends(require_token)) -> dict[str, Any]:
    """Refuser une réponse suggérée (ne l'envoie pas) — RLS."""
    updated = db.update_ig_draft(token, draft_id, status="rejected")
    if not updated:
        raise HTTPException(status_code=404, detail="Réponse suggérée introuvable.")
    return {"ok": True, "draft": updated}


@app.post("/me/ig/conversations/{conversation_id}/generate-draft")
def me_ig_generate_draft(
    conversation_id: str, token: str = Depends(require_token)
) -> dict[str, Any]:
    """Générer à la demande une réponse IA pour le dernier message du prospect.

    Réutilise le même cerveau (`ig_agent.generate_draft`) que la génération
    automatique sur DM entrant, mais déclenché uniquement par un clic — utile
    pour obtenir une suggestion sans attendre un nouveau message, ou pour en
    régénérer une. N'envoie rien : le draft créé reste `pending`, à valider/
    éditer via `/me/ig/drafts/{id}/send` comme toute autre suggestion.
    """
    conv = db.get_ig_conversation(token, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation introuvable.")
    user = db.get_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable.")
    if not db.admin_enabled():
        raise HTTPException(status_code=503, detail="Service-role Supabase indisponible.")
    inbound = [m for m in db.list_ig_messages(token, conversation_id) if m.get("role") == "in"]
    if not inbound:
        raise HTTPException(status_code=400, detail="Aucun message du prospect à qui répondre.")
    last = inbound[-1]
    draft = ig_agent.generate_draft(user["id"], conversation_id, last["id"], last.get("text") or "")
    if not draft:
        raise HTTPException(status_code=500, detail="Génération de la réponse impossible.")
    return {"ok": True, "draft": draft}


class IgModeRequest(BaseModel):
    mode: str = Field(..., pattern="^(supervised|autopilot)$")


@app.post("/me/ig/conversations/{conversation_id}/mode")
def me_ig_conversation_mode(
    conversation_id: str,
    payload: IgModeRequest,
    token: str = Depends(require_token),
) -> dict[str, Any]:
    """Basculer une conversation supervisé ↔ autopilot (le comportement autopilot = ALE-205)."""
    updated = db.set_ig_conversation_mode(token, conversation_id, payload.mode)
    if not updated:
        raise HTTPException(status_code=404, detail="Conversation introuvable.")
    return {"ok": True, "conversation": updated}


@app.get("/me/ig/autopilot/kill-switch")
def me_ig_kill_switch_get(token: str = Depends(require_token)) -> dict[str, Any]:
    """État du kill-switch global (true = tout en supervisé, aucun envoi auto)."""
    return {"active": db.get_ig_kill_switch(token)}


class IgKillSwitchRequest(BaseModel):
    active: bool


@app.post("/me/ig/autopilot/kill-switch")
def me_ig_kill_switch_set(
    payload: IgKillSwitchRequest, token: str = Depends(require_token)
) -> dict[str, Any]:
    """Basculer le kill-switch global — « tout repasser en supervisé » (ALE-205)."""
    ok = db.set_ig_kill_switch(token, payload.active)
    if not ok:
        raise HTTPException(status_code=400, detail="Profil éditorial requis pour le kill-switch.")
    return {"ok": True, "active": payload.active}


@app.get("/me/ig/faq")
def me_ig_faq_get(token: str = Depends(require_token)) -> dict[str, Any]:
    """FAQ + objectif de l'agent IG, remplis par l'utilisateur (RLS).

    `source` indique d'où viendrait le texte utilisé par le cerveau : `user`
    (base) ou `file` (repli fichier serveur si la FAQ user est vide).
    """
    row = db.get_ig_faq(token)
    content = (row or {}).get("content") or ""
    return {
        "content": content,
        "updated_at": (row or {}).get("updated_at"),
        "source": "user" if content.strip() else "file",
    }


class IgFaqRequest(BaseModel):
    content: str = Field(default="", max_length=40000)


@app.put("/me/ig/faq")
def me_ig_faq_set(payload: IgFaqRequest, token: str = Depends(require_token)) -> dict[str, Any]:
    """Enregistrer la FAQ + objectif de l'agent IG (RLS, une ligne par utilisateur)."""
    row = db.set_ig_faq(token, payload.content)
    if row is None:
        raise HTTPException(status_code=500, detail="Enregistrement de la FAQ impossible.")
    return {"ok": True, "content": row.get("content", ""), "updated_at": row.get("updated_at")}


class IgTestInboundRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    prospect_name: str = Field(default="Prospect Test", max_length=120)


@app.post("/me/ig/test/inbound")
def me_ig_test_inbound(
    payload: IgTestInboundRequest, token: str = Depends(require_token)
) -> dict[str, Any]:
    """Simuler un DM Instagram entrant (page de test ManyChat).

    Rejoue exactement le pipeline du webhook `/manychat/webhooks/inbound`, mais
    sur le compte de l'utilisateur authentifié et avec un prospect fictif
    (`prospect_id` préfixé `test:`) : message persisté, réponse suggérée générée
    en tâche de fond, garde-fou/autopilot appliqués. Aucun appel ManyChat ne
    part jamais pour ces conversations.
    """
    user = db.get_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable.")
    if not db.admin_enabled():
        raise HTTPException(status_code=503, detail="Service-role Supabase indisponible.")

    slug = "".join(
        ch for ch in payload.prospect_name.lower().replace(" ", "-") if ch.isalnum() or ch == "-"
    ) or "demo"
    prospect_id = f"{ig_agent.TEST_PROSPECT_PREFIX}{slug}"
    conv = db.get_or_create_ig_conversation_admin(user["id"], prospect_id, payload.prospect_name)
    if not conv:
        raise HTTPException(status_code=500, detail="Impossible de créer la conversation de test.")
    msg = db.add_ig_message_admin(
        user["id"], conv["id"], role="in", source="prospect", text=payload.text, kind="text"
    )
    if msg:
        ig_agent.generate_draft_async(user["id"], conv["id"], msg["id"], payload.text)
    return {"ok": True, "conversation_id": conv["id"], "message": msg}


# ---------------------------------------------------------------------------
# Connexion ManyChat par utilisateur (multi-client) — chaque client relie SON
# compte ManyChat (clé API) et reçoit SON URL de webhook + secret à coller dans
# une action « External Request » de son flow ManyChat.
# ---------------------------------------------------------------------------

def _mask_token(token: str | None) -> str | None:
    """Ne jamais renvoyer la clé en clair : uniquement les 4 derniers caractères."""
    if not token:
        return None
    tail = token[-4:]
    return f"…{tail}"


def _manychat_status_payload(request: Request, integ: dict | None) -> dict[str, Any]:
    """Construire l'état de connexion ManyChat renvoyé au front (jamais la clé en clair)."""
    if not integ or not integ.get("webhook_token"):
        return {"connected": False}
    base = _public_base_url(request)
    return {
        "connected": True,
        "api_token_masked": _mask_token(integ.get("access_token")),
        "webhook_url": f"{base}/manychat/webhooks/inbound/{integ['webhook_token']}",
        "webhook_secret": integ.get("webhook_secret"),
        "connected_at": integ.get("connected_at"),
    }


@app.get("/me/ig/manychat")
def me_ig_manychat_status(request: Request, token: str = Depends(require_token)) -> dict[str, Any]:
    """État de la connexion ManyChat de l'utilisateur (URL de webhook + secret à copier)."""
    return _manychat_status_payload(request, db.get_ig_manychat(token))


class IgManychatConnectRequest(BaseModel):
    api_token: str = Field(..., min_length=8, max_length=400)


@app.post("/me/ig/manychat")
def me_ig_manychat_connect(
    payload: IgManychatConnectRequest, request: Request, token: str = Depends(require_token)
) -> dict[str, Any]:
    """Relier le compte ManyChat de l'utilisateur : valide la clé, génère l'URL + secret.

    On vérifie la clé auprès de ManyChat (attrape une faute de frappe), puis on
    persiste. L'URL de webhook et le secret sont réutilisés s'ils existent déjà
    (reconnexion = nouvelle clé sans changer l'URL à recoller dans ManyChat).
    """
    api_token = payload.api_token.strip()
    try:
        manychat.validate_token(api_token)
    except manychat.ManyChatError as exc:
        raise HTTPException(status_code=400, detail=f"Clé API ManyChat refusée : {exc}")

    existing = db.get_ig_manychat(token)
    webhook_token = (existing or {}).get("webhook_token") or secrets.token_urlsafe(24)
    webhook_secret = (existing or {}).get("webhook_secret") or secrets.token_urlsafe(24)
    row = db.save_ig_manychat(
        token, api_token=api_token, webhook_token=webhook_token, webhook_secret=webhook_secret
    )
    if row is None:
        raise HTTPException(status_code=500, detail="Enregistrement de la connexion impossible.")
    return {"ok": True, **_manychat_status_payload(request, row)}


@app.delete("/me/ig/manychat")
def me_ig_manychat_disconnect(token: str = Depends(require_token)) -> dict[str, Any]:
    """Délier le compte ManyChat de l'utilisateur (l'URL de webhook cesse de router)."""
    db.delete_ig_manychat(token)
    return {"ok": True, "connected": False}
