"""Thin Resend API client (transactional email).

Single server-side API key (RESEND_API_KEY). Used to send the free full audit
to landing leads, plus an internal notification per new lead.

⚠️ Resend refuse d'envoyer depuis un domaine non vérifié : le domaine de
l'expéditeur (clareo-solutions.fr) doit être vérifié dans le dashboard Resend
AVANT que le moindre mail parte. Sans clé (ou domaine non vérifié), l'app reste
fonctionnelle : le lead est capturé en base, seul l'envoi est sauté/échoue.

Uses stdlib urllib to avoid adding an HTTP dependency (matches zernio.py).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

BASE_URL = "https://api.resend.com"
# Expéditeur par défaut, surchargeable sans redéploiement.
DEFAULT_FROM = "Tom de Clareo Solutions <tom@clareo-solutions.fr>"


class EmailError(RuntimeError):
    """Raised when the Resend API returns an error or is not configured."""


def enabled() -> bool:
    return bool(os.environ.get("RESEND_API_KEY"))


def _api_key() -> str:
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        raise EmailError("RESEND_API_KEY manquant dans l'environnement serveur.")
    return key


def sender() -> str:
    return os.environ.get("AUDIT_EMAIL_FROM", "").strip() or DEFAULT_FROM


def notify_recipients() -> list[str]:
    """Adresses internes prévenues à chaque nouveau lead (AUDIT_NOTIFY_EMAILS, CSV)."""
    raw = os.environ.get("AUDIT_NOTIFY_EMAILS", "")
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


def send_email(
    to: str | list[str],
    subject: str,
    html: str,
    *,
    reply_to: str | None = None,
) -> dict[str, Any]:
    """Envoie un email via Resend. Lève EmailError en cas d'échec (jamais avalé ici :
    l'appelant décide si l'échec est bloquant — pour l'audit il est consigné en base)."""
    body: dict[str, Any] = {
        "from": sender(),
        "to": [to] if isinstance(to, str) else list(to),
        "subject": subject,
        "html": html,
    }
    if reply_to:
        body["reply_to"] = reply_to
    req = urllib.request.Request(
        f"{BASE_URL}/emails",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="ignore")[:500]
        except Exception:
            pass
        raise EmailError(f"Resend HTTP {exc.code} : {detail or exc.reason}") from exc
    except Exception as exc:
        raise EmailError(f"Envoi Resend impossible : {exc}") from exc
