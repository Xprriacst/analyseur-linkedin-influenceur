"""Thin Stripe client — abonnement 49 €/mois = 1000 crédits (ALE-274).

Une seule clé serveur (STRIPE_SECRET_KEY) : clés de test sur dev, clés réelles en
prod. Le paiement lui-même est hébergé par Stripe (Checkout) et la gestion de la
carte / résiliation par le Customer Portal — l'app ne voit jamais de numéro de
carte et n'a quasiment pas d'UI à construire.

Uses stdlib urllib to avoid adding an HTTP dependency (matches zernio.py / unipile.py).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BASE_URL = "https://api.stripe.com/v1"

# Crédits rechargés à chaque facture payée. Le solde est FIXÉ à cette valeur, pas
# incrémenté : décision produit du 2026-07-10 (pas de report des crédits non
# consommés d'un mois sur l'autre).
DEFAULT_PLAN_CREDITS = 1000

# Fenêtre de tolérance sur l'horodatage de la signature du webhook (rejeu tardif).
WEBHOOK_TOLERANCE_S = 300


class StripeError(RuntimeError):
    """Raised when the Stripe API returns an error or is not configured."""


def enabled() -> bool:
    """Vrai si la facturation est configurée (clé + tarif). Sinon l'UI l'affiche « non configuré »."""
    return bool(os.environ.get("STRIPE_SECRET_KEY") and os.environ.get("STRIPE_PRICE_ID"))


def webhook_enabled() -> bool:
    return bool(os.environ.get("STRIPE_WEBHOOK_SECRET"))


def price_id() -> str:
    value = os.environ.get("STRIPE_PRICE_ID")
    if not value:
        raise StripeError("STRIPE_PRICE_ID non configuré.")
    return value


def plan_credits() -> int:
    """Crédits par période. Surchargeable pour ne pas re-déployer si l'offre bouge."""
    raw = os.environ.get("STRIPE_PLAN_CREDITS")
    try:
        value = int(raw) if raw else DEFAULT_PLAN_CREDITS
    except ValueError:
        return DEFAULT_PLAN_CREDITS
    return value if value > 0 else DEFAULT_PLAN_CREDITS


def _tax_enabled() -> bool:
    """Stripe Tax (TVA) — OFF par défaut.

    Tant que l'adresse du siège n'est pas renseignée dans le dashboard Stripe, le
    compte est en `status: pending` et toute session Checkout avec `automatic_tax`
    est rejetée. On ne l'active donc que sur demande explicite, une fois la config
    faite côté Stripe.
    """
    return os.environ.get("STRIPE_TAX_ENABLED", "").strip().lower() in ("1", "true", "yes")


def _secret_key() -> str:
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        raise StripeError("STRIPE_SECRET_KEY non configuré.")
    return key


def _flatten(data: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """Aplatit un dict imbriqué au format attendu par Stripe (`a[b][c]=v`)."""
    pairs: list[tuple[str, str]] = []
    for key, value in data.items():
        field = f"{prefix}[{key}]" if prefix else str(key)
        if value is None:
            continue
        if isinstance(value, dict):
            pairs.extend(_flatten(value, field))
        elif isinstance(value, (list, tuple)):
            for idx, item in enumerate(value):
                if isinstance(item, dict):
                    pairs.extend(_flatten(item, f"{field}[{idx}]"))
                else:
                    pairs.append((f"{field}[{idx}]", str(item)))
        elif isinstance(value, bool):
            pairs.append((field, "true" if value else "false"))
        else:
            pairs.append((field, str(value)))
    return pairs


def _request(method: str, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{BASE_URL}{path}"
    body = urllib.parse.urlencode(_flatten(data or {})).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {_secret_key()}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        try:
            message = (json.loads(detail).get("error") or {}).get("message") or detail
        except Exception:
            message = detail
        raise StripeError(f"Stripe {exc.code} : {message}") from exc
    except urllib.error.URLError as exc:
        raise StripeError(f"Stripe injoignable : {exc.reason}") from exc


# ── Clients & abonnements ── #

def create_customer(user_id: str, email: str | None) -> dict[str, Any]:
    """Crée le client Stripe du compte app. `metadata.user_id` = notre clé de rattachement."""
    payload: dict[str, Any] = {"metadata": {"user_id": user_id}}
    if email:
        payload["email"] = email
    return _request("POST", "/customers", payload)


def create_checkout_session(
    customer_id: str, user_id: str, success_url: str, cancel_url: str
) -> dict[str, Any]:
    """Session Checkout en mode abonnement (page de paiement hébergée par Stripe)."""
    payload: dict[str, Any] = {
        "mode": "subscription",
        "customer": customer_id,
        "line_items": [{"price": price_id(), "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        # Deux chemins de rattachement à notre compte app : sur la session (retour
        # immédiat) et sur l'abonnement (factures suivantes, où seul l'abonnement
        # et le client Stripe voyagent).
        "client_reference_id": user_id,
        "metadata": {"user_id": user_id},
        "subscription_data": {"metadata": {"user_id": user_id}},
        "allow_promotion_codes": True,  # comptes internes/démo : code promo 100 %
    }
    if _tax_enabled():
        payload["automatic_tax"] = {"enabled": True}
        payload["customer_update"] = {"address": "auto"}
    return _request("POST", "/checkout/sessions", payload)


def create_portal_session(customer_id: str, return_url: str) -> dict[str, Any]:
    """Customer Portal : changement de carte, factures, résiliation — hébergé par Stripe."""
    return _request(
        "POST", "/billing_portal/sessions", {"customer": customer_id, "return_url": return_url}
    )


def get_subscription(subscription_id: str) -> dict[str, Any]:
    return _request("GET", f"/subscriptions/{urllib.parse.quote(subscription_id)}")


_PRICE_CACHE: dict[str, dict[str, Any]] = {}


def plan_summary() -> dict[str, Any]:
    """Montant/devise/période du tarif configuré, lus depuis Stripe (source de vérité).

    Évite de coder « 49 € » en dur dans l'UI : si le tarif change côté Stripe,
    l'app suit. Mis en cache en mémoire (le tarif ne bouge pas en cours de vie du
    process) ; sur échec réseau on renvoie ce qu'on sait, sans casser l'écran.
    """
    pid = price_id()
    cached = _PRICE_CACHE.get(pid)
    if cached:
        return cached
    summary: dict[str, Any] = {"credits": plan_credits(), "amount": None, "currency": None, "interval": None}
    try:
        price = _request("GET", f"/prices/{urllib.parse.quote(pid)}")
    except StripeError:
        return summary
    unit_amount = price.get("unit_amount")
    summary["amount"] = unit_amount / 100 if isinstance(unit_amount, int) else None
    summary["currency"] = price.get("currency")
    summary["interval"] = (price.get("recurring") or {}).get("interval")
    _PRICE_CACHE[pid] = summary
    return summary


def list_customer_subscriptions(customer_id: str, limit: int = 3) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"customer": customer_id, "status": "all", "limit": limit})
    resp = _request("GET", f"/subscriptions?{query}")
    data = resp.get("data")
    return data if isinstance(data, list) else []


# ── Normalisation ── #

# Statuts pour lesquels l'abonnement donne droit au service. `past_due` reste
# actif : Stripe retente le paiement plusieurs jours, on ne coupe pas au 1er échec.
ACTIVE_STATUSES = {"active", "trialing", "past_due"}


def is_active(status: str | None) -> bool:
    return (status or "") in ACTIVE_STATUSES


def normalize_subscription(sub: dict[str, Any]) -> dict[str, Any]:
    """Extrait ce qu'on stocke d'un objet subscription Stripe (schéma tolérant).

    `current_period_end` est au premier niveau sur les anciennes versions d'API et
    porté par l'item d'abonnement sur les récentes → on lit les deux.
    """
    items = ((sub.get("items") or {}).get("data") or [])
    first_item = items[0] if items and isinstance(items[0], dict) else {}
    period_end = sub.get("current_period_end") or first_item.get("current_period_end")
    price = (first_item.get("price") or {}).get("id") or (first_item.get("plan") or {}).get("id")
    return {
        "stripe_subscription_id": sub.get("id"),
        "status": sub.get("status"),
        "price_id": price,
        "cancel_at_period_end": bool(sub.get("cancel_at_period_end")),
        "current_period_end": _iso(period_end),
    }


def invoice_subscription_id(invoice: dict[str, Any]) -> str | None:
    """Identifiant d'abonnement porté par une facture (schéma tolérant).

    ⚠️ Piège vérifié en test : sur les versions récentes de l'API, `invoice.subscription`
    **n'existe plus** — l'identifiant a migré dans `parent.subscription_details`. Sans
    ce repli, une facture de renouvellement ne permet plus de retrouver l'abonnement
    (donc ni la date de prochaine échéance, ni le tarif).
    """
    direct = invoice.get("subscription")
    if isinstance(direct, str) and direct:
        return direct
    parent = invoice.get("parent") or {}
    nested = (parent.get("subscription_details") or {}).get("subscription")
    if isinstance(nested, str) and nested:
        return nested
    lines = ((invoice.get("lines") or {}).get("data") or [])
    for line in lines:
        details = ((line or {}).get("parent") or {}).get("subscription_item_details") or {}
        sub_id = details.get("subscription")
        if isinstance(sub_id, str) and sub_id:
            return sub_id
    return None


def invoice_user_id(invoice: dict[str, Any]) -> str | None:
    """Notre `user_id` tel que porté par une facture (métadonnées de l'abonnement)."""
    parent = invoice.get("parent") or {}
    metadata = (parent.get("subscription_details") or {}).get("metadata") or {}
    user_id = metadata.get("user_id")
    return user_id if isinstance(user_id, str) and user_id else None


def _iso(epoch: Any) -> str | None:
    try:
        return (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(epoch))) if epoch else None
        )
    except (TypeError, ValueError):
        return None


# ── Webhook ── #

def verify_webhook(payload: bytes, signature_header: str) -> dict[str, Any]:
    """Vérifie la signature Stripe et retourne l'événement.

    Fail-closed : sans STRIPE_WEBHOOK_SECRET, on refuse (comme Slack/ManyChat) —
    un webhook non signé accepté laisserait n'importe qui créditer 1000 crédits.
    """
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise StripeError("STRIPE_WEBHOOK_SECRET non configuré.")

    timestamp = ""
    signatures: list[str] = []
    for part in (signature_header or "").split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if not timestamp or not signatures:
        raise StripeError("Signature Stripe absente ou malformée.")

    try:
        age = time.time() - int(timestamp)
    except ValueError:
        raise StripeError("Horodatage de signature Stripe invalide.")
    if abs(age) > WEBHOOK_TOLERANCE_S:
        raise StripeError("Signature Stripe expirée.")

    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in signatures):
        raise StripeError("Signature Stripe invalide.")

    try:
        event = json.loads(payload.decode())
    except Exception as exc:
        raise StripeError("Corps de webhook Stripe illisible.") from exc
    if not isinstance(event, dict):
        raise StripeError("Événement Stripe invalide.")
    return event
