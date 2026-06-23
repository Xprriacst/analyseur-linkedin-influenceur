"""LinkedIn post scraping via Apify."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from apify_client import ApifyClient

from src.usage import track_apify


CACHE_DIR = Path("cache")


def _cache_path(handle: str, suffix: str = "") -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    name = f"{handle}{suffix}.json"
    return CACHE_DIR / name


def extract_handle(profile_url: str) -> str:
    """Handle décodé (clément-geynet-☀️-…), forme canonique pour cache/db/affichage."""
    url = profile_url.strip().rstrip("/")
    raw = url.split("/in/")[-1].split("/")[0].split("?")[0].split("#")[0]
    return unquote(raw)


def normalize_url(profile_url: str) -> str:
    """URL canonique pour les actors Apify : handle percent-encodé, sans query params.

    Gère les handles avec accents/emojis, qu'ils arrivent bruts (☀️) ou déjà
    encodés (%F0%9F...) — unquote puis quote évite le double encodage.
    """
    handle = extract_handle(profile_url)
    return f"https://www.linkedin.com/in/{quote(handle, safe='-._~')}/"


def _client() -> ApifyClient:
    return ApifyClient(os.environ["APIFY_TOKEN"])


def _call_actor(actor: str, run_input: dict[str, Any], timeout_secs: int) -> Any:
    """Lance un actor en attendant la fin du run.

    `timeout_secs` n'est pas accepté par toutes les versions d'apify-client
    déployées (un environnement Render avec un client mis en cache plus ancien
    le refuse → "ActorClient.call() got an unexpected keyword argument
    'timeout_secs'"). On retombe alors sur un appel sans le paramètre plutôt
    que de faire planter toute l'analyse.
    """
    client = _client().actor(actor)
    try:
        return client.call(run_input=run_input, timeout_secs=timeout_secs)
    except TypeError as exc:
        if "timeout_secs" not in str(exc):
            raise
        return client.call(run_input=run_input)


def _default_dataset_id(run: Any) -> str:
    if isinstance(run, dict):
        return run["defaultDatasetId"]
    return run.default_dataset_id


def _posts_run_input(actor: str, handle: str, url: str, limit: int) -> dict[str, Any]:
    if "harvestapi" in actor:
        return {
            "targetUrls": [url],
            "maxPosts": limit,
            "postedLimit": "any",
            "scrapeComments": False,
            "scrapeReactions": False,
            "includeReposts": False,
        }
    if "datadoping" in actor:
        return {"username": handle, "resultsLimit": limit}
    return {"username": handle, "limit": limit}


def _run_posts_actor(actor: str, handle: str, url: str, limit: int) -> list[dict]:
    try:
        run = _call_actor(actor, _posts_run_input(actor, handle, url, limit), timeout_secs=300)
        items = list(_client().dataset(_default_dataset_id(run)).iterate_items())
    except Exception as exc:
        print(f"[scraper] échec scrape posts {handle!r} via {actor}: {exc}", flush=True)
        return []
    # Certains actors renvoient un item d'erreur au lieu d'un dataset vide.
    return [
        i for i in items
        if isinstance(i, dict) and (i.get("text") or i.get("content") or i.get("full_urn") or i.get("id"))
    ]


def fetch_posts(profile_url: str, limit: int = 30, use_cache: bool = True) -> list[dict[str, Any]]:
    """Fetch the last `limit` posts of a LinkedIn profile via Apify.

    Tries APIFY_ACTOR first (default: harvestapi/linkedin-profile-posts).
    Falls back to POSTS_FALLBACK_ACTOR if the primary returns no results.
    """
    handle = extract_handle(profile_url)
    cache_file = _cache_path(handle, "-posts")

    if use_cache and cache_file.exists():
        cached = json.loads(cache_file.read_text())
        actor = os.environ.get("APIFY_ACTOR", "harvestapi/linkedin-profile-posts")
        track_apify(actor, len(cached), cached=True)
        return cached

    actor = os.environ.get("APIFY_ACTOR", "harvestapi/linkedin-profile-posts")
    url = normalize_url(profile_url)

    items = _run_posts_actor(actor, handle, url, limit)

    if not items and actor != POSTS_FALLBACK_ACTOR:
        print(f"[scraper] 0 post via {actor!r} pour {handle!r} — tentative fallback {POSTS_FALLBACK_ACTOR!r}", flush=True)
        items = _run_posts_actor(POSTS_FALLBACK_ACTOR, handle, url, limit)
        if items:
            actor = POSTS_FALLBACK_ACTOR

    track_apify(actor, len(items), cached=False)
    if items:  # ne jamais mettre en cache un échec
        cache_file.write_text(json.dumps(items, ensure_ascii=False, indent=2, default=str))
    return items


# Fallback profil : fonctionne sans approbation de permissions Apify
# (harvestapi/linkedin-profile-scraper exige depuis ~06/2026 un "full access"
# à approuver manuellement dans la console — sinon chaque scrape échoue).
PROFILE_FALLBACK_ACTOR = "apimaestro/linkedin-profile-detail"

# Fallback posts : utilisé automatiquement si l'actor principal renvoie 0 résultat.
# ~$0.0014/post, 100% succès déclaré (vs harvestapi à $0.002/post).
# Env var APIFY_ACTOR surcharge l'actor principal ; le fallback reste fixe.
POSTS_FALLBACK_ACTOR = "datadoping/linkedin-profile-posts-scraper"


def _profile_run_input(actor: str, url: str) -> dict[str, Any]:
    if "harvestapi" in actor:
        return {"queries": [url]}
    if "apimaestro" in actor:
        return {"username": url}  # accepte handle, URL ou URN
    return {"urls": [{"url": url}], "scrapeCompany": False, "findContacts": False}


def _run_profile_actor(actor: str, url: str) -> list[dict]:
    try:
        run = _call_actor(actor, _profile_run_input(actor, url), timeout_secs=120)
        items = list(_client().dataset(_default_dataset_id(run)).iterate_items())
    except Exception as exc:
        # Visible dans les logs Render — ex. actor qui exige une approbation de
        # permissions Apify ("This Actor requires full access to your account").
        print(f"[scraper] échec scrape profil {url} via {actor}: {exc}", flush=True)
        return []
    # Écarte les payloads d'erreur ({"message": ...}) renvoyés en guise d'item
    return [
        i for i in items
        if isinstance(i, dict) and (i.get("basic_info") or i.get("firstName") or i.get("fullName") or i.get("name"))
    ]


def fetch_profile(profile_url: str, use_cache: bool = True) -> dict[str, Any] | None:
    """Fetch profile metadata (followers, headline, creator badge, etc.)."""
    handle = extract_handle(profile_url)
    cache_file = _cache_path(handle, "-profile")

    if use_cache and cache_file.exists():
        cached = json.loads(cache_file.read_text())
        if cached:  # un cache vide = échec passé, on retente le scrape
            actor = os.environ.get("APIFY_PROFILE_ACTOR", PROFILE_FALLBACK_ACTOR)
            track_apify(actor, 1, cached=True)
            return cached

    actor = os.environ.get("APIFY_PROFILE_ACTOR", PROFILE_FALLBACK_ACTOR)
    url = normalize_url(profile_url)

    items = _run_profile_actor(actor, url)
    if not items and actor != PROFILE_FALLBACK_ACTOR:
        items = _run_profile_actor(PROFILE_FALLBACK_ACTOR, url)
        actor = PROFILE_FALLBACK_ACTOR

    profile = items[0] if items else {}
    track_apify(actor, 1 if profile else 0, cached=False)
    if profile:  # ne jamais mettre en cache un échec
        cache_file.write_text(json.dumps(profile, ensure_ascii=False, indent=2, default=str))
    return profile or None
