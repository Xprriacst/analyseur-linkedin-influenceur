"""Envoi d'e-mails transactionnels via Resend.

Client minimal en urllib stdlib, comme `zernio.py` / `unipile.py` / `stripe_billing.py`
— aucune dépendance HTTP ajoutée au projet.

⚠️ Posture identique à celle des autres intégrations optionnelles : sans
`RESEND_API_KEY`, `enabled()` est faux et **rien ne casse**. C'est la propriété
importante ici : le tunnel d'audit doit enregistrer le lead et emmener le visiteur
sur Calendly même si l'e-mail ne part pas. Perdre un e-mail est ennuyeux ; perdre
le prospect parce que l'appel SMTP a hoqueté serait absurde.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

BASE_URL = "https://api.resend.com"
TIMEOUT_S = 15

# ⚠️ NON COSMÉTIQUE — sans lui, AUCUN e-mail ne part.
# `api.resend.com` est derrière Cloudflare, dont la protection anti-bot refuse
# le User-Agent par défaut d'urllib (`Python-urllib/3.x`) : la réponse est un
# **403 Cloudflare « error code: 1010 »**, pas une erreur de l'API Resend — donc
# ni « clé invalide » ni « domaine non vérifié » dans le message, rien qui mette
# sur la piste. Vérifié en direct le 2026-08-19 : requête identique, UA urllib
# → 403, UA applicatif → 200.
# Les autres clients urllib du projet (zernio, unipile, stripe_billing) ne sont
# pas concernés aujourd'hui — leurs API n'appliquent pas cette règle. Si l'un
# d'eux se met à répondre 403 sans explication, penser d'abord à ceci.
USER_AGENT = "Cibl/1.0 (+https://cibl.clareo-solutions.fr)"


class MailError(RuntimeError):
    """Resend a répondu une erreur, ou la configuration est absente."""


def enabled() -> bool:
    return bool(os.environ.get("RESEND_API_KEY"))


def default_sender() -> str:
    """Expéditeur par défaut — doit appartenir à un domaine vérifié chez Resend."""
    return os.environ.get("RESEND_FROM", "Cible <contact@clareo-solutions.fr>")


def internal_recipients() -> list[str]:
    """Qui, chez nous, est prévenu d'un nouveau lead (liste séparée par des virgules)."""
    raw = os.environ.get("AUDIT_LEAD_NOTIFY_TO", "")
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


def _api_key() -> str:
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        raise MailError("RESEND_API_KEY manquant dans l'environnement serveur.")
    return key


def send_email(
    to: list[str] | str,
    subject: str,
    html: str,
    *,
    text: str | None = None,
    sender: str | None = None,
    reply_to: str | None = None,
) -> dict[str, Any]:
    """Envoie un e-mail. Lève `MailError` en cas d'échec — l'appelant décide."""
    recipients = [to] if isinstance(to, str) else [addr for addr in to if addr]
    if not recipients:
        raise MailError("Aucun destinataire.")

    payload: dict[str, Any] = {
        "from": sender or default_sender(),
        "to": recipients,
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text
    if reply_to:
        payload["reply_to"] = reply_to

    request = urllib.request.Request(
        f"{BASE_URL}/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            body = response.read().decode("utf-8") or "{}"
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise MailError(f"Resend {exc.code} : {detail}") from exc
    except Exception as exc:  # réseau, DNS, timeout
        raise MailError(f"Envoi e-mail impossible : {exc}") from exc


def send_email_safe(*args: Any, **kwargs: Any) -> bool:
    """Variante best-effort : renvoie False au lieu de lever.

    Utilisée sur les chemins où l'e-mail est un à-côté (notification interne d'un
    nouveau lead) et ne doit jamais faire échouer la requête du visiteur.
    """
    if not enabled():
        return False
    try:
        send_email(*args, **kwargs)
        return True
    except Exception:
        return False
