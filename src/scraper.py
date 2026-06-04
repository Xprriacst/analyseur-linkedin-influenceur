"""LinkedIn post scraping via Apify."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from apify_client import ApifyClient

from src.usage import track_apify


CACHE_DIR = Path("cache")


def _cache_path(handle: str, suffix: str = "") -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    name = f"{handle}{suffix}.json"
    return CACHE_DIR / name


def extract_handle(profile_url: str) -> str:
    url = profile_url.rstrip("/")
    return url.split("/in/")[-1].split("/")[0].split("?")[0]


def normalize_url(profile_url: str) -> str:
    """Ensure trailing slash. Keep encoding intact (emojis %F0%9F...)."""
    url = profile_url.strip()
    if "?" in url:
        url = url.split("?")[0]
    if not url.endswith("/"):
        url += "/"
    return url


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
    track_apify(actor, len(items), cached=False)

    cache_file.write_text(json.dumps(items, ensure_ascii=False, indent=2, default=str))
    return items


def fetch_profile(profile_url: str, use_cache: bool = True) -> dict[str, Any] | None:
    """Fetch profile metadata (followers, headline, creator badge, etc.)."""
    handle = extract_handle(profile_url)
    cache_file = _cache_path(handle, "-profile")

    if use_cache and cache_file.exists():
        cached = json.loads(cache_file.read_text())
        actor = os.environ.get("APIFY_PROFILE_ACTOR", "harvestapi/linkedin-profile-scraper")
        track_apify(actor, 1 if cached else 0, cached=True)
        return cached or None

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
    except Exception:
        items = []

    profile = items[0] if items else {}
    track_apify(actor, 1 if profile else 0, cached=False)
    cache_file.write_text(json.dumps(profile, ensure_ascii=False, indent=2, default=str))
    return profile or None
