"""Cron de surveillance des acteurs Apify LinkedIn.

Usage (cron Render) :
  python -m src.actor_health          # vérification statique uniquement (sans scrape)
  python -m src.actor_health --live   # + scrape minimal d'un profil de test (~$0.004)

Variables d'environnement :
  APIFY_TOKEN              — requis
  APIFY_ACTOR              — actor posts (défaut : harvestapi/linkedin-profile-posts)
  APIFY_PROFILE_ACTOR      — actor profil (défaut : apimaestro/linkedin-profile-detail)
  SLACK_ALERT_WEBHOOK_URL  — Incoming Webhook Slack pour les alertes (optionnel)
  HEALTH_TEST_PROFILE      — profil LinkedIn de test pour le --live check
                             (défaut : https://www.linkedin.com/in/williamhgates/)

Cycle recommandé sur Render :
  - Vérification statique quotidienne (0 6 * * *) — zéro coût Apify
  - Vérification live hebdomadaire (0 6 * * 1) — ~$0.004 max
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from apify_client import ApifyClient


def _client() -> ApifyClient:
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        raise RuntimeError("APIFY_TOKEN manquant dans l'environnement.")
    return ApifyClient(token)


def _actor_info(actor_id: str) -> dict[str, Any] | None:
    """Return Apify store metadata for *actor_id*, or None if not found."""
    try:
        return _client().actor(actor_id).get()
    except Exception as exc:
        print(f"[actor_health] Erreur lecture Apify pour {actor_id!r}: {exc}", flush=True)
        return None


def _send_slack_alert(message: str) -> None:
    """POST *message* to SLACK_ALERT_WEBHOOK_URL (Incoming Webhook).

    Falls back to a log line if the env var is not set.
    """
    webhook_url = os.environ.get("SLACK_ALERT_WEBHOOK_URL")
    if not webhook_url:
        print(f"[actor_health] ALERTE (Slack non configuré) : {message}", flush=True)
        return
    body = json.dumps({"text": message}).encode("utf-8")
    req = urllib.request.Request(webhook_url, data=body, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        print(f"[actor_health] Alerte Slack envoyée.", flush=True)
    except Exception as exc:
        print(f"[actor_health] Échec envoi Slack : {exc} — message : {message}", flush=True)


def check_actor_exists(actor_id: str) -> tuple[bool, str]:
    """Verify that *actor_id* exists in the Apify store and is not deprecated.

    Returns (ok, human-readable reason).
    No Apify compute cost — uses the metadata API only.
    """
    info = _actor_info(actor_id)
    if info is None:
        return False, f"Acteur {actor_id!r} introuvable sur Apify (supprimé ou privé)."
    if info.get("isDeprecated"):
        return False, f"Acteur {actor_id!r} marqué comme déprécié."
    version = info.get("defaultRunOptions", {}).get("build", "") or ""
    return True, f"Acteur {actor_id!r} disponible{' (build: ' + version + ')' if version else ''}."


def live_check_posts(actor_id: str, profile_url: str) -> tuple[bool, str]:
    """Run a minimal posts scrape (1 post) to confirm the actor returns valid data.

    This makes a real Apify run — cost ~$0.002. Only called when --live is passed.
    """
    from src.scraper import _call_actor, _default_dataset_id, normalize_url, extract_handle

    handle = extract_handle(profile_url)
    url = normalize_url(profile_url)

    if "harvestapi" in actor_id:
        run_input: dict[str, Any] = {
            "targetUrls": [url],
            "maxPosts": 1,
            "postedLimit": "any",
            "scrapeComments": False,
            "scrapeReactions": False,
            "includeReposts": False,
        }
    else:
        run_input = {"username": handle, "limit": 1}

    try:
        run = _call_actor(actor_id, run_input, timeout_secs=120)
        items = list(_client().dataset(_default_dataset_id(run)).iterate_items())
        items = [
            i for i in items
            if isinstance(i, dict) and (i.get("text") or i.get("content") or i.get("id"))
        ]
        if not items:
            return False, f"Acteur {actor_id!r} a renvoyé 0 post pour {handle!r}."
        return True, f"Acteur {actor_id!r} OK — {len(items)} post(s) pour {handle!r}."
    except Exception as exc:
        return False, f"Acteur {actor_id!r} a levé une exception pour {handle!r} : {exc}"


def live_check_profile(actor_id: str, profile_url: str) -> tuple[bool, str]:
    """Run a minimal profile scrape to confirm the actor returns valid data.

    Cost ~$0.005. Only called when --live is passed.
    """
    from src.scraper import _run_profile_actor, extract_handle

    handle = extract_handle(profile_url)
    try:
        items = _run_profile_actor(actor_id, profile_url)
        if not items:
            return False, f"Acteur {actor_id!r} a renvoyé 0 résultat pour {handle!r}."
        return True, f"Acteur {actor_id!r} OK — profil récupéré pour {handle!r}."
    except Exception as exc:
        return False, f"Acteur {actor_id!r} a levé une exception pour {handle!r} : {exc}"


def run_checks(live: bool = False) -> int:
    """Run all health checks and alert on Slack if any fail.

    Returns 0 (all OK) or 1 (at least one failure).
    """
    from src.scraper import PROFILE_FALLBACK_ACTOR, POSTS_FALLBACK_ACTOR

    posts_actor = os.environ.get("APIFY_ACTOR", "harvestapi/linkedin-profile-posts")
    profile_actor = os.environ.get("APIFY_PROFILE_ACTOR", PROFILE_FALLBACK_ACTOR)
    test_profile = os.environ.get(
        "HEALTH_TEST_PROFILE", "https://www.linkedin.com/in/williamhgates/"
    )

    checks: list[tuple[str, tuple[bool, str]]] = []

    # Static checks (zero Apify cost)
    checks.append(("posts_actor", check_actor_exists(posts_actor)))
    checks.append(("profile_actor", check_actor_exists(profile_actor)))
    if posts_actor != POSTS_FALLBACK_ACTOR:
        checks.append(("posts_fallback", check_actor_exists(POSTS_FALLBACK_ACTOR)))
    if profile_actor != PROFILE_FALLBACK_ACTOR:
        checks.append(("profile_fallback", check_actor_exists(PROFILE_FALLBACK_ACTOR)))

    # Live checks (actual Apify runs — only when requested)
    if live:
        checks.append(("posts_live", live_check_posts(posts_actor, test_profile)))
        checks.append(("profile_live", live_check_profile(profile_actor, test_profile)))

    failures: list[str] = []
    for name, (ok, msg) in checks:
        label = "✅ OK" if ok else "❌ ECHEC"
        print(f"[actor_health] {name}: {label} — {msg}", flush=True)
        if not ok:
            failures.append(f"• [{name}] {msg}")

    if failures:
        failure_text = "\n".join(failures)
        alert = (
            ":warning: *Alerte Apify — acteurs LinkedIn défaillants*\n"
            f"{failure_text}\n\n"
            f"Posts principal : `{posts_actor}` → fallback : `{POSTS_FALLBACK_ACTOR}`\n"
            f"Profil principal : `{profile_actor}` → fallback : `{PROFILE_FALLBACK_ACTOR}`"
        )
        _send_slack_alert(alert)
        return 1

    print("[actor_health] Tous les acteurs sont opérationnels.", flush=True)
    return 0


if __name__ == "__main__":
    live_mode = "--live" in sys.argv
    sys.exit(run_checks(live=live_mode))
