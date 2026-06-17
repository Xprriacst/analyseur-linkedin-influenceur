"""Thin Zernio API client (LinkedIn publishing).

A single server-side API key (ZERNIO_API_KEY) drives one Zernio "profile" per
app user. Each profile connects one LinkedIn account via OAuth (handled by
Zernio). We only need to: create a profile, build the OAuth connect URL, read
back the connected account id, and publish a post.

Uses stdlib urllib to avoid adding an HTTP dependency (matches api.py).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BASE_URL = "https://zernio.com/api/v1"
PLATFORM = "linkedin"


class ZernioError(RuntimeError):
    """Raised when the Zernio API returns an error or is not configured."""


def enabled() -> bool:
    return bool(os.environ.get("ZERNIO_API_KEY"))


def _api_key() -> str:
    key = os.environ.get("ZERNIO_API_KEY")
    if not key:
        raise ZernioError("ZERNIO_API_KEY manquant dans l'environnement serveur.")
    return key


def _request(method: str, path: str, *, params: dict | None = None, body: dict | None = None) -> Any:
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {_api_key()}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(detail)
            detail = parsed.get("error") or parsed.get("message") or detail
        except Exception:
            pass
        raise ZernioError(f"Zernio {method} {path} a échoué ({exc.code}) : {detail}") from exc
    except urllib.error.URLError as exc:
        raise ZernioError(f"Zernio injoignable : {exc.reason}") from exc
    return json.loads(raw) if raw else {}


def create_profile(name: str, description: str | None = None) -> str:
    """Create a Zernio profile and return its id."""
    body: dict[str, Any] = {"name": name[:120] or "Client"}
    if description:
        body["description"] = description[:500]
    data = _request("POST", "/profiles", body=body)
    profile = data.get("profile") or data
    profile_id = profile.get("_id")
    if not profile_id:
        raise ZernioError("Réponse Zernio inattendue : pas d'_id de profile.")
    return profile_id


def get_connect_url(profile_id: str, redirect_url: str | None = None) -> str:
    """Return the LinkedIn OAuth authorization URL for this profile."""
    data = _request(
        "GET",
        f"/connect/{PLATFORM}",
        params={"profileId": profile_id, "redirect_url": redirect_url},
    )
    auth_url = data.get("authUrl")
    if not auth_url:
        raise ZernioError("Réponse Zernio inattendue : pas d'authUrl.")
    return auth_url


def find_linkedin_account_id(profile_id: str) -> str | None:
    """Return the connected LinkedIn account id for this profile, if any."""
    data = _request("GET", "/accounts", params={"profileId": profile_id})
    for account in data.get("accounts", []):
        if account.get("platform") == PLATFORM:
            return account.get("_id")
    return None


def create_post(content: str, account_id: str, *, is_draft: bool = False) -> dict[str, Any]:
    """Create a LinkedIn post, either as a safe draft or published now."""
    body = {
        "content": content,
        "platforms": [{"platform": PLATFORM, "accountId": account_id}],
    }
    if is_draft:
        body["isDraft"] = True
    else:
        body["publishNow"] = True
    return _request("POST", "/posts", body=body)
