"""Thin Unipile API client — messagerie LinkedIn pour la prospection (ALE-230).

Unipile pilote LinkedIn via son API non officielle : chaque client connecte SON
compte LinkedIn (modèle multi-client, comme la connexion ManyChat côté Instagram).
On utilise une seule clé API serveur (UNIPILE_API_KEY) + un DSN (UNIPILE_DSN, ex.
`api8.unipile.com:13443`). Le compte de chaque client est identifié par son
`account_id` Unipile, stocké par utilisateur.

Ce module ne fait QUE parler à Unipile ; les garde-fous quota et la persistance
vivent dans `db.py` / `api.py`. Comme `zernio.py`, on s'appuie sur `urllib` stdlib
pour ne pas ajouter de dépendance HTTP.

⚠️ Le schéma exact des réponses Unipile n'est pas garanti stable : les
normaliseurs (`_pick`, `normalize_chat`, `normalize_message`) testent plusieurs
clés usuelles et restent tolérants plutôt que de présumer une forme précise.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# LinkedIn est le seul provider utilisé ici (l'app est centrée LinkedIn).
PROVIDER = "LINKEDIN"


class UnipileError(RuntimeError):
    """Levée quand l'API Unipile renvoie une erreur ou n'est pas configurée."""


def enabled() -> bool:
    """Vrai si Unipile est configuré côté serveur (DSN + clé API)."""
    return bool(os.environ.get("UNIPILE_DSN") and os.environ.get("UNIPILE_API_KEY"))


def _api_key() -> str:
    key = os.environ.get("UNIPILE_API_KEY")
    if not key:
        raise UnipileError("UNIPILE_API_KEY manquant dans l'environnement serveur.")
    return key


def _base_origin() -> str:
    """Origine du DSN Unipile (`https://api8.unipile.com:13443`), sans /api/v1."""
    dsn = (os.environ.get("UNIPILE_DSN") or "").strip().rstrip("/")
    if not dsn:
        raise UnipileError("UNIPILE_DSN manquant dans l'environnement serveur.")
    if not dsn.startswith(("http://", "https://")):
        dsn = "https://" + dsn
    return dsn


def _base_url() -> str:
    return _base_origin() + "/api/v1"


def _request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    body: dict | None = None,
    timeout: int = 30,
) -> Any:
    url = f"{_base_url()}{path}"
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-API-KEY", _api_key())
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(detail)
            # Unipile renvoie souvent {type, title, detail} ou {message}.
            detail = parsed.get("detail") or parsed.get("message") or parsed.get("title") or detail
        except Exception:
            pass
        raise UnipileError(f"Unipile {method} {path} a échoué ({exc.code}) : {detail}") from exc
    except urllib.error.URLError as exc:
        raise UnipileError(f"Unipile injoignable : {exc.reason}") from exc
    return json.loads(raw) if raw else {}


def _pick(obj: dict | None, *keys: str) -> Any:
    """Première valeur non vide parmi `keys` d'un dict (tolérance de schéma)."""
    if not isinstance(obj, dict):
        return None
    for key in keys:
        val = obj.get(key)
        if val not in (None, "", [], {}):
            return val
    return None


# --------------------------------------------------------------------------- #
# Connexion d'un compte (Hosted Auth Wizard)
# --------------------------------------------------------------------------- #


def create_hosted_auth_link(
    *,
    name: str,
    success_redirect_url: str | None = None,
    failure_redirect_url: str | None = None,
    notify_url: str | None = None,
    expires_on: str | None = None,
) -> str:
    """URL d'auth hébergée Unipile : le client s'y connecte à LinkedIn.

    `name` = notre identifiant interne (user_id) — il voyage avec le compte
    connecté, ce qui nous permet de le retrouver ensuite via `find_account_by_name`.
    Retourne l'URL à ouvrir dans le navigateur.
    """
    body: dict[str, Any] = {
        "type": "create",
        "providers": [PROVIDER],
        "api_url": _base_origin(),
        "name": name,
    }
    if expires_on:
        body["expiresOn"] = expires_on
    if success_redirect_url:
        body["success_redirect_url"] = success_redirect_url
    if failure_redirect_url:
        body["failure_redirect_url"] = failure_redirect_url
    if notify_url:
        body["notify_url"] = notify_url
    data = _request("POST", "/hosted/accounts/link", body=body)
    url = _pick(data, "url")
    if not url:
        raise UnipileError("Réponse Unipile inattendue : pas d'URL d'auth hébergée.")
    return url


def list_accounts() -> list[dict[str, Any]]:
    """Comptes connectés sur ce workspace Unipile."""
    data = _request("GET", "/accounts")
    items = data.get("items") if isinstance(data, dict) else None
    if items is None and isinstance(data, list):
        items = data
    return [a for a in (items or []) if isinstance(a, dict)]


def find_account_by_name(name: str) -> dict[str, Any] | None:
    """Compte connecté dont le `name` (notre user_id) correspond — le plus récent.

    Plusieurs clients partagent la même clé API Unipile : on isole le compte du
    bon utilisateur par le `name` passé à la connexion.
    """
    if not name:
        return None
    matches = [a for a in list_accounts() if _pick(a, "name") == name]
    # Un même utilisateur peut avoir reconnecté : on garde le compte le plus récent.
    matches.sort(key=lambda a: str(_pick(a, "created_at", "connected_at") or ""), reverse=True)
    return matches[0] if matches else None


def account_id_of(account: dict[str, Any] | None) -> str | None:
    """Id Unipile d'un compte connecté (schéma tolérant)."""
    return _pick(account, "id", "account_id") if account else None


def chat_id_of(chat: dict[str, Any] | None) -> str | None:
    """Id d'un chat renvoyé par Unipile (start_new_chat / send)."""
    return _pick(chat, "chat_id", "id") if chat else None


def get_account(account_id: str) -> dict[str, Any] | None:
    """Statut d'un compte connecté (None si absent/supprimé)."""
    if not account_id:
        return None
    try:
        return _request("GET", f"/accounts/{urllib.parse.quote(account_id)}")
    except UnipileError:
        return None


def account_display_name(account: dict[str, Any] | None) -> str | None:
    """Nom affichable d'un compte connecté (best-effort, schéma non garanti)."""
    if not isinstance(account, dict):
        return None
    val = _pick(account, "name", "display_name", "username")
    # `name` peut être notre user_id (passé à la connexion) : on préfère le nom réel.
    connection = account.get("connection_params") or {}
    im = connection.get("im") if isinstance(connection, dict) else None
    real = _pick(im, "username", "display_name") if isinstance(im, dict) else None
    name = real or val
    return str(name).strip() if isinstance(name, str) and name.strip() else None


# --------------------------------------------------------------------------- #
# Résolution d'un profil → provider_id + distance réseau
# --------------------------------------------------------------------------- #

_SLUG_RE = re.compile(r"linkedin\.com/(?:in|pub)/([^/?#]+)", re.IGNORECASE)


def profile_identifier(profile_url: str | None) -> str | None:
    """Slug public LinkedIn extrait d'une URL de profil (`.../in/satyanadella/`)."""
    if not profile_url:
        return None
    match = _SLUG_RE.search(profile_url)
    if not match:
        return None
    slug = urllib.parse.unquote(match.group(1)).strip()
    return slug or None


def get_user_profile(account_id: str, identifier: str) -> dict[str, Any]:
    """Profil LinkedIn d'une personne (par slug public OU provider_id).

    Sert à récupérer le `provider_id` (nécessaire pour inviter/écrire) et la
    `network_distance` (DISTANCE_1 = déjà connecté).
    """
    if not account_id or not identifier:
        raise UnipileError("account_id et identifiant requis pour lire un profil.")
    return _request(
        "GET",
        f"/users/{urllib.parse.quote(str(identifier))}",
        params={"account_id": account_id},
    )


def provider_id_of(profile: dict[str, Any] | None) -> str | None:
    return _pick(profile, "provider_id", "member_id", "id") if profile else None


def is_first_degree(profile: dict[str, Any] | None) -> bool:
    """Vrai si la personne est une relation de 1er niveau (invitation acceptée)."""
    distance = _pick(profile, "network_distance", "distance")
    return str(distance or "").upper() in ("DISTANCE_1", "FIRST_DEGREE", "1")


# --------------------------------------------------------------------------- #
# Invitations
# --------------------------------------------------------------------------- #


def send_invitation(account_id: str, provider_id: str, message: str | None = None) -> dict[str, Any]:
    """Envoie une demande de connexion. Sans `message` = invitation SANS note
    (quotas LinkedIn bien plus permissifs — c'est le parcours par défaut d'ALE-230).
    """
    if not account_id or not provider_id:
        raise UnipileError("account_id et provider_id requis pour inviter.")
    body: dict[str, Any] = {"account_id": account_id, "provider_id": provider_id}
    if message:
        body["message"] = message[:300]
    return _request("POST", "/users/invite", body=body)


# --------------------------------------------------------------------------- #
# Messagerie (chats)
# --------------------------------------------------------------------------- #


def start_new_chat(account_id: str, provider_id: str, text: str) -> dict[str, Any]:
    """Démarre une conversation et envoie le premier message. Retourne le chat créé."""
    if not account_id or not provider_id:
        raise UnipileError("account_id et provider_id requis pour écrire.")
    if not (text or "").strip():
        raise UnipileError("Message vide.")
    return _request(
        "POST",
        "/chats",
        body={"account_id": account_id, "attendees_ids": [provider_id], "text": text},
    )


def list_chats(account_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Conversations du compte connecté (les plus récentes d'abord côté Unipile)."""
    if not account_id:
        return []
    data = _request("GET", "/chats", params={"account_id": account_id, "limit": limit})
    items = data.get("items") if isinstance(data, dict) else None
    if items is None and isinstance(data, list):
        items = data
    return [c for c in (items or []) if isinstance(c, dict)]


def get_chat(chat_id: str) -> dict[str, Any] | None:
    """Métadonnées d'une conversation (dont l'`account_id` propriétaire), ou None."""
    if not chat_id:
        return None
    try:
        return _request("GET", f"/chats/{urllib.parse.quote(chat_id)}")
    except UnipileError:
        return None


def chat_account_id_of(chat: dict[str, Any] | None) -> str | None:
    """`account_id` Unipile propriétaire d'une conversation (contrôle d'accès)."""
    return _pick(chat, "account_id", "account") if chat else None


def list_chat_messages(chat_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Messages d'une conversation."""
    if not chat_id:
        return []
    data = _request(
        "GET",
        f"/chats/{urllib.parse.quote(chat_id)}/messages",
        params={"limit": limit},
    )
    items = data.get("items") if isinstance(data, dict) else None
    if items is None and isinstance(data, list):
        items = data
    return [m for m in (items or []) if isinstance(m, dict)]


def send_message(chat_id: str, text: str) -> dict[str, Any]:
    """Envoie un message dans une conversation existante."""
    if not chat_id:
        raise UnipileError("chat_id requis.")
    if not (text or "").strip():
        raise UnipileError("Message vide.")
    return _request("POST", f"/chats/{urllib.parse.quote(chat_id)}/messages", body={"text": text})


# --------------------------------------------------------------------------- #
# Normaliseurs d'affichage (schéma Unipile tolérant)
# --------------------------------------------------------------------------- #


def normalize_chat(chat: dict[str, Any]) -> dict[str, Any]:
    """Réduit un chat Unipile à ce dont l'Inbox a besoin.

    ⚠️ Le nom du participant vit dans `attendee_name` (schéma Unipile), PAS `name` —
    lire `name`/`display_name` (l'ancienne version) ratait le participant même quand
    Unipile l'embarquait. `attendee_provider_id` sert à nommer la conversation avec le
    nom du lead correspondant côté endpoint (Unipile n'embarque pas toujours l'attendee
    dans la liste des chats). Ici, `name` peut rester None : la résolution finale (nom
    du lead, sinon fallback générique) est faite par l'endpoint qui a accès à la base.
    """
    attendee = None
    attendees = chat.get("attendees")
    if isinstance(attendees, list) and attendees:
        attendee = attendees[0] if isinstance(attendees[0], dict) else None
    # Identifiant LinkedIn du participant (format `ACoAA…`), même clé que `leads.provider_id`.
    attendee_provider_id = _pick(chat, "attendee_provider_id") or (
        _pick(attendee, "attendee_provider_id", "provider_id") if attendee else None
    )
    # Nom réel quand Unipile l'a fourni (chat de groupe → `name`/`subject` ; 1-to-1 →
    # `attendee_name`). Sinon None → l'endpoint nommera par le lead.
    name = (
        _pick(chat, "name", "subject")
        or (_pick(attendee, "attendee_name", "name", "display_name") if attendee else None)
        or None
    )
    return {
        "id": _pick(chat, "id", "chat_id"),
        "name": name,
        "attendee_provider_id": attendee_provider_id,
        "last_message_at": _pick(chat, "timestamp", "last_message_at", "updated_at"),
        "provider_url": _pick(attendee, "attendee_profile_url", "profile_url") if attendee else None,
    }


def apply_lead_names(
    chats: list[dict[str, Any]],
    by_provider: dict[str, str],
    by_chat: dict[str, str],
) -> list[dict[str, Any]]:
    """Nomme chaque conversation (mutation en place) quand Unipile n'a pas fourni de
    nom réel. Priorité : nom Unipile existant > nom du lead par `attendee_provider_id`
    (fiable) > nom du lead par `outreach_chat_id` (rétro-compat) > fallback générique.
    """
    for chat in chats:
        if not chat.get("name"):
            chat["name"] = (
                by_provider.get(chat.get("attendee_provider_id"))
                or by_chat.get(chat.get("id"))
                or "Conversation LinkedIn"
            )
    return chats


def normalize_message(message: dict[str, Any]) -> dict[str, Any]:
    """Réduit un message Unipile à {id, text, from_me, created_at}."""
    is_sender = _pick(message, "is_sender", "is_self", "from_me")
    from_me = str(is_sender) in ("1", "True", "true") if is_sender is not None else False
    return {
        "id": _pick(message, "id", "message_id"),
        "text": _pick(message, "text", "body") or "",
        "from_me": from_me,
        "created_at": _pick(message, "timestamp", "created_at", "date"),
    }
