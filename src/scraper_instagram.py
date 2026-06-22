"""Instagram scraping via Apify actors."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from src.scraper import _client, _default_dataset_id
from src.usage import track_apify


CACHE_DIR = Path("cache")

# Apify actor IDs / names (overridable via env vars)
_DEFAULT_IG_PROFILE_ACTOR = "apify/instagram-profile-scraper"
_DEFAULT_IG_REEL_ACTOR = "apify/instagram-reel-scraper"


def _ig_profile_actor() -> str:
    return os.environ.get("APIFY_IG_PROFILE_ACTOR", _DEFAULT_IG_PROFILE_ACTOR)


def _ig_reel_actor() -> str:
    return os.environ.get("APIFY_IG_REEL_ACTOR", _DEFAULT_IG_REEL_ACTOR)


def _cache_path(handle: str, suffix: str) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / f"{handle}{suffix}.json"


def extract_ig_handle(url_or_handle: str) -> str:
    """Extract a clean Instagram handle (without @) from a URL, @handle, or bare handle.

    Examples:
        "https://www.instagram.com/leaplusbeaudesinsta/"  → "leaplusbeaudesinsta"
        "@leaplusbeaudesinsta"                            → "leaplusbeaudesinsta"
        "leaplusbeaudesinsta"                             → "leaplusbeaudesinsta"
    """
    raw = (url_or_handle or "").strip()
    # Try to extract from instagram.com URL
    m = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", raw, re.IGNORECASE)
    if m:
        handle = m.group(1).rstrip("/")
        return handle
    # Strip @ prefix
    handle = raw.lstrip("@").rstrip("/").split("/")[0].split("?")[0]
    return handle


def fetch_ig_profile(handle: str, use_cache: bool = True) -> dict | None:
    """Scrape an Instagram profile via Apify.

    Returns the raw profile dict from the actor output, or None on failure.
    Cache: cache/{handle}-ig-profile.json
    """
    cache_file = _cache_path(handle, "-ig-profile")
    actor = _ig_profile_actor()

    if use_cache and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text())
            track_apify(actor, 1 if cached else 0, cached=True)
            return cached or None
        except Exception:
            pass

    run_input = {"usernames": [handle]}
    try:
        client = _client()
        run = client.actor(actor).call(run_input=run_input)
        items = list(client.dataset(_default_dataset_id(run)).iterate_items())
    except Exception as exc:
        print(f"[scraper_instagram] fetch_ig_profile({handle}) failed: {exc}")
        items = []

    profile = items[0] if items else {}
    track_apify(actor, 1 if profile else 0, cached=False)
    try:
        cache_file.write_text(json.dumps(profile, ensure_ascii=False, indent=2, default=str))
    except Exception:
        pass
    return profile or None


def fetch_ig_reels(handle: str, limit: int = 30, use_cache: bool = True) -> list[dict]:
    """Scrape Instagram Reels (and posts) for a given handle via Apify.

    Returns a list of raw reel/post dicts from the actor output.
    Cache: cache/{handle}-ig-reels.json
    """
    cache_file = _cache_path(handle, "-ig-reels")
    actor = _ig_reel_actor()

    if use_cache and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text())
            if cached:
                track_apify(actor, len(cached), cached=True)
                return cached
        except Exception:
            pass

    run_input = {
        "username": [handle],
        "resultsLimit": limit,
        "skipPinnedPosts": True,
    }
    try:
        client = _client()
        run = client.actor(actor).call(run_input=run_input)
        items = list(client.dataset(_default_dataset_id(run)).iterate_items())
    except Exception as exc:
        print(f"[scraper_instagram] fetch_ig_reels({handle}) failed: {exc}")
        items = []

    track_apify(actor, len(items), cached=False)
    if items:
        try:
            cache_file.write_text(json.dumps(items, ensure_ascii=False, indent=2, default=str))
        except Exception:
            pass
    return items
