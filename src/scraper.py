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


def _default_dataset_id(run: Any) -> str:
    if isinstance(run, dict):
        return run["defaultDatasetId"]
    return run.default_dataset_id


def fetch_posts(profile_url: str, limit: int = 30, use_cache: bool = True) -> list[dict[str, Any]]:
    """Fetch the last `limit` posts of a LinkedIn profile via Apify."""
    handle = extract_handle(profile_url)
    cache_file = _cache_path(handle, "-posts")

    if use_cache and cache_file.exists():
        cached = json.loads(cache_file.read_text())
        actor = os.environ.get("APIFY_ACTOR", "harvestapi/linkedin-profile-posts")
        track_apify(actor, len(cached), cached=True)
        return cached

    actor = os.environ.get("APIFY_ACTOR", "harvestapi/linkedin-profile-posts")
    url = normalize_url(profile_url)

    if "harvestapi" in actor:
        run_input = {
            "targetUrls": [url],
            "maxPosts": limit,
            "postedLimit": "any",
            "scrapeComments": False,
            "scrapeReactions": False,
            "includeReposts": False,
        }
    else:
        run_input = {
            "username": handle,
            "page_number": 1,
            "limit": limit,
        }

    run = _client().actor(actor).call(run_input=run_input)
    items = list(_client().dataset(_default_dataset_id(run)).iterate_items())
    # Certains actors renvoient un item d'erreur ({"message": ..., "profile_input": ...})
    # au lieu d'un dataset vide : on ne garde que les vrais posts.
    items = [
        i for i in items
        if isinstance(i, dict) and (i.get("text") or i.get("content") or i.get("full_urn") or i.get("id"))
    ]
    track_apify(actor, len(items), cached=False)

    if items:  # ne jamais mettre en cache un échec
        cache_file.write_text(json.dumps(items, ensure_ascii=False, indent=2, default=str))
    return items


def fetch_profile(profile_url: str, use_cache: bool = True) -> dict[str, Any] | None:
    """Fetch profile metadata (followers, headline, creator badge, etc.)."""
    handle = extract_handle(profile_url)
    cache_file = _cache_path(handle, "-profile")

    if use_cache and cache_file.exists():
        cached = json.loads(cache_file.read_text())
        if cached:  # un cache vide = échec passé, on retente le scrape
            actor = os.environ.get("APIFY_PROFILE_ACTOR", "harvestapi/linkedin-profile-scraper")
            track_apify(actor, 1, cached=True)
            return cached

    actor = os.environ.get("APIFY_PROFILE_ACTOR", "harvestapi/linkedin-profile-scraper")
    url = normalize_url(profile_url)

    if "harvestapi" in actor:
        run_input = {
            "queries": [url],
        }
    else:
        run_input = {
            "urls": [{"url": url}],
            "scrapeCompany": False,
            "findContacts": False,
        }

    try:
        run = _client().actor(actor).call(run_input=run_input)
        items = list(_client().dataset(_default_dataset_id(run)).iterate_items())
    except Exception as exc:
        # Visible dans les logs Render — ex. actor qui exige une approbation de
        # permissions Apify ("This Actor requires full access to your account").
        print(f"[scraper] échec scrape profil {url} via {actor}: {exc}", flush=True)
        items = []

    profile = items[0] if items else {}
    track_apify(actor, 1 if profile else 0, cached=False)
    if profile:  # ne jamais mettre en cache un échec
        cache_file.write_text(json.dumps(profile, ensure_ascii=False, indent=2, default=str))
    return profile or None
