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


# LinkedIn/Unipile renvoie parfois le gabarit non substitué comme titre de chat
# (`{{full_name}}`, `{{first_name}}`…). Ce n'est PAS un nom affichable : le garder
# bloquerait le rattrapage par `attendee_name` / nom du lead.
_PLACEHOLDER_NAME_RE = re.compile(r"\{\{\s*[^{}]+\s*\}\}")


def usable_display_name(value: Any) -> str | None:
    """Nom affichable, ou None si vide / placeholder type `{{full_name}}`."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if _PLACEHOLDER_NAME_RE.search(text):
        return None
    return text


def _pick_display_name(obj: dict | None, *keys: str) -> str | None:
    """Comme `_pick`, mais ignore les placeholders Unipile/LinkedIn."""
    if not isinstance(obj, dict):
        return None
    for key in keys:
        name = usable_display_name(obj.get(key))
        if name:
            return name
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
# Posts du compte connecté (mémoire du post du jour)
# --------------------------------------------------------------------------- #


def list_own_posts(account_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Posts LinkedIn du compte connecté (`GET /users/me/posts`).

    `me` = le propriétaire du `account_id`. Pagination non suivie : le cron
    n'a besoin que des ~10 plus récents. Lève `UnipileError` ; l'appelant
    rattrape — un hoquet Unipile ne doit jamais casser la génération du jour.
    """
    if not account_id:
        raise UnipileError("account_id requis pour lister tes posts.")
    data = _request(
        "GET",
        "/users/me/posts",
        params={"account_id": account_id, "limit": max(1, min(int(limit), 20))},
    )
    items = data.get("items") if isinstance(data, dict) else None
    if items is None and isinstance(data, list):
        items = data
    return [row for row in (items or []) if isinstance(row, dict)]


def normalize_own_post(item: dict[str, Any] | None, text_cap: int = 400) -> dict[str, Any] | None:
    """Transforme un item Unipile en entrée de mémoire. Pure, schéma tolérant.

    `text` est une chaîne dans le schéma documenté ; certains wraps le rangent
    encore en `{text: …}`. Sans texte → None (un post image-only n'aide pas
    l'anti-répétition).
    """
    if not isinstance(item, dict):
        return None
    raw_text = _pick(item, "text", "content", "commentary", "message")
    if isinstance(raw_text, dict):
        raw_text = _pick(raw_text, "text", "body")
    text = str(raw_text or "").strip()
    if not text:
        return None
    date_raw = _pick(item, "parsed_datetime", "date", "created_at", "posted_at")
    date = str(date_raw)[:10] if date_raw else None
    if date and not date[:4].isdigit():
        date = None
    return {
        "text": text[: max(1, int(text_cap))],
        "status": "publié sur LinkedIn",
        "date": date,
        "card": None,
    }


def own_posts_to_memory(items: list[dict[str, Any]] | None, text_cap: int = 400) -> list[dict[str, Any]]:
    """Liste d'entrées mémoire depuis la réponse Unipile. Ignore les items vides."""
    out: list[dict[str, Any]] = []
    for item in items or []:
        entry = normalize_own_post(item, text_cap=text_cap)
        if entry:
            out.append(entry)
    return out


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


def attendee_names(
    account_id: str,
    wanted: set[str] | None = None,
    *,
    limit: int = 250,
    max_pages: int = 4,
) -> dict[str, str]:
    """{provider_id: nom LinkedIn} des participants des conversations du compte.

    ⚠️ Pourquoi cet appel existe : `GET /chats` ne renvoie, pour une conversation
    1-to-1, que l'`attendee_provider_id` — **jamais le nom** (`name` est null, il n'est
    rempli que pour un groupe ou un objet d'InMail). Sans ce complément, toute
    conversation avec quelqu'un qui n'est pas un lead de notre base s'affiche
    « Conversation LinkedIn » : c'est le cas de la majorité de l'Inbox (messages
    entrants, recruteurs, relations existantes), qui n'est jamais passée par la
    prospection.

    `wanted` = identifiants qu'on cherche : dès qu'ils sont tous trouvés on arrête de
    paginer (en pratique une seule page). Sans lui, on ramène `max_pages` pages au plus
    — un compte ancien peut avoir des milliers de participants, on ne va pas au bout.
    """
    if not account_id:
        return {}
    todo = {str(p) for p in (wanted or set()) if p}
    out: dict[str, str] = {}
    cursor: str | None = None
    for _ in range(max(1, max_pages)):
        params: dict[str, Any] = {"account_id": account_id, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        data = _request("GET", "/chat_attendees", params=params)
        items = data.get("items") if isinstance(data, dict) else None
        if items is None and isinstance(data, list):
            items = data
        for att in items or []:
            if not isinstance(att, dict):
                continue
            # `is_self` = nous-même dans la conversation : jamais un nom d'interlocuteur.
            if str(att.get("is_self")) in ("1", "True", "true"):
                continue
            pid = _pick(att, "provider_id", "attendee_provider_id")
            name = _pick_display_name(att, "name", "attendee_name", "display_name")
            if pid and name and str(pid) not in out:
                out[str(pid)] = name
                todo.discard(str(pid))
        cursor = data.get("cursor") if isinstance(data, dict) else None
        if not cursor or not items or (wanted is not None and not todo):
            break
    return out


def chat_attendee_names(chat_id: str) -> dict[str, str]:
    """{provider_id: nom} des participants d'UNE conversation.

    Complément ciblé de `attendee_names` : le listing par compte ramène les
    participants de TOUTES les conversations, sans ordre garanti — sur un compte à gros
    historique, ceux des conversations affichées peuvent se trouver hors des premières
    pages. On va alors les chercher conversation par conversation, pour celles-là
    seulement.
    """
    if not chat_id:
        return {}
    data = _request("GET", f"/chats/{urllib.parse.quote(chat_id)}/attendees")
    items = data.get("items") if isinstance(data, dict) else None
    if items is None and isinstance(data, list):
        items = data
    out: dict[str, str] = {}
    for att in items or []:
        if not isinstance(att, dict):
            continue
        if str(att.get("is_self")) in ("1", "True", "true"):
            continue
        pid = _pick(att, "provider_id", "attendee_provider_id")
        name = _pick_display_name(att, "name", "attendee_name", "display_name")
        if pid and name:
            out[str(pid)] = name
    return out


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

    ⚠️ Unipile pose parfois le gabarit littéral `{{full_name}}` dans `name`/`subject`
    (titre LinkedIn non substitué). Ce n'est pas un nom : on l'ignore pour laisser
    `attendee_name` ou le rattrapage par lead prendre le relais.
    """
    attendee = None
    attendees = chat.get("attendees")
    if isinstance(attendees, list) and attendees:
        attendee = attendees[0] if isinstance(attendees[0], dict) else None
    # Identifiant LinkedIn du participant (format `ACoAA…`), même clé que `leads.provider_id`.
    attendee_provider_id = _pick(chat, "attendee_provider_id") or (
        _pick(attendee, "attendee_provider_id", "provider_id") if attendee else None
    )
    # Titre donné par Unipile : rempli pour un GROUPE, et pour un InMail c'est son objet
    # (« Astek s'intéresse à votre profil ») — pas le nom d'une personne. D'où la
    # distinction avec `attendee_name` : c'est `apply_chat_names` qui tranche lequel
    # affiche, selon `is_group`.
    title = _pick_display_name(chat, "name", "subject")
    attendee_name = (
        _pick_display_name(attendee, "attendee_name", "name", "display_name") if attendee else None
    )
    # `type` Unipile : 0 = conversation à deux, 1/2 = groupe. Absent ⇒ traité comme un
    # 1-to-1 (le repli sur le titre reste en bout de chaîne, rien ne se perd).
    is_group = str(_pick(chat, "type")) in ("1", "2")
    return {
        "id": _pick(chat, "id", "chat_id"),
        "name": title or attendee_name,
        "attendee_name": attendee_name,
        "is_group": is_group,
        "attendee_provider_id": attendee_provider_id,
        "last_message_at": _pick(chat, "timestamp", "last_message_at", "updated_at"),
        "provider_url": _pick(attendee, "attendee_profile_url", "profile_url") if attendee else None,
    }


def apply_chat_names(
    chats: list[dict[str, Any]],
    *,
    by_attendee: dict[str, str],
    by_lead_provider: dict[str, str],
    by_lead_chat: dict[str, str],
) -> list[dict[str, Any]]:
    """Nomme chaque conversation (mutation en place).

    Une Inbox liste des personnes : pour une conversation à deux on affiche donc le nom
    de l'interlocuteur, et le titre Unipile ne sert que de repli — c'est souvent l'objet
    d'un InMail, voire le libellé de dossier « Other », pas un nom. Un GROUPE, lui,
    garde son titre : c'est son seul nom.

    Priorité (1-to-1) : participant embarqué dans le chat > `attendee_names` du compte
    (le seul chemin qui nomme quelqu'un qui n'est PAS un lead de la base) > nom du lead
    par `attendee_provider_id` > nom du lead par `outreach_chat_id` (rétro-compat) >
    titre Unipile > fallback générique.

    Un placeholder (`{{full_name}}`) compte partout comme « pas de nom » — sans ça, il
    bloquerait toute la chaîne et s'afficherait tel quel.
    """
    for chat in chats:
        pid = chat.get("attendee_provider_id")
        person = (
            usable_display_name(chat.get("attendee_name"))
            or usable_display_name(by_attendee.get(pid))
            or usable_display_name(by_lead_provider.get(pid))
            or usable_display_name(by_lead_chat.get(chat.get("id")))
        )
        title = usable_display_name(chat.get("name"))
        if chat.get("is_group"):
            chat["name"] = title or person or "Conversation LinkedIn"
        else:
            chat["name"] = person or title or "Conversation LinkedIn"
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


# --------------------------------------------------------------------------- #
# Recherche de profils (import d'un lien de recherche LinkedIn)
# --------------------------------------------------------------------------- #

# Unipile ne restitue pas plus que ce que LinkedIn accepte de rendre : 1000
# profils par requête de recherche classique, 2500 en Sales Navigator — même
# quand l'UI annonce davantage de résultats. Au-delà, il faut affiner la
# recherche, pas paginer plus loin.
SEARCH_HARD_CAP = 1000
SEARCH_SALES_NAVIGATOR_CAP = 2500


def search_page(
    account_id: str,
    *,
    url: str | None = None,
    body: dict | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Une page de résultats de recherche LinkedIn.

    ⚠️ `api` est OBLIGATOIRE dans le corps ; le passage d'une URL brute n'est
    documenté qu'avec des exemples Sales Navigator. Une URL de recherche
    CLASSIQUE envoyée seule ne lève pas d'erreur : Unipile répond 200 avec zéro
    résultat. La construction du corps vit dans `lead_search.build_search_request`.

    Retourne la réponse brute {items, paging, cursor}.
    """
    if not account_id:
        raise UnipileError("account_id requis pour lancer une recherche.")
    payload: dict[str, Any] = dict(body or {})
    if url:
        payload["url"] = url
    if not payload:
        raise UnipileError("Recherche vide : fournis une URL ou des paramètres.")
    params: dict[str, Any] = {"account_id": account_id}
    if cursor:
        params["cursor"] = cursor
    if limit:
        params["limit"] = int(limit)
    # Une page de recherche peut être lente côté LinkedIn : on laisse plus de
    # marge que le défaut (30 s) sans pour autant bloquer indéfiniment.
    return _request("POST", "/linkedin/search", params=params, body=payload, timeout=90)


def normalize_search_profile(item: dict[str, Any]) -> dict[str, Any] | None:
    """Réduit un résultat de recherche à un prospect exploitable, ou None.

    Schéma tolérant (cf. entête du module) : selon l'API (classic / sales
    navigator / recruiter) le nom arrive entier (`name`) ou en deux morceaux, et
    l'URL publique sous plusieurs clés. On exige une URL de profil OU un
    identifiant public — sans l'un des deux, le prospect n'est ni dédoublonnable
    ni contactable, donc inutilisable.
    """
    if not isinstance(item, dict):
        return None
    identifier = _pick(item, "public_identifier", "public_id", "username")
    profile_url = _pick(item, "public_profile_url", "profile_url", "linkedin_url", "url")
    if not profile_url and identifier:
        profile_url = f"https://www.linkedin.com/in/{identifier}"
    if not profile_url:
        return None

    name = _pick_display_name(item, "name", "full_name", "display_name")
    if not name:
        first = _pick(item, "first_name", "firstName") or ""
        last = _pick(item, "last_name", "lastName") or ""
        name = f"{first} {last}".strip() or None

    location = _pick(item, "location", "geo_region", "region")
    if isinstance(location, dict):
        location = _pick(location, "name", "label", "text")

    return {
        "name": name,
        "headline": (_pick(item, "headline", "title", "subtitle") or None),
        "profile_url": str(profile_url),
        "provider_id": _pick(item, "provider_id", "member_id", "id"),
        "location": str(location) if isinstance(location, str) and location.strip() else None,
    }


def search_total_count(page: dict[str, Any] | None) -> int | None:
    """Total annoncé par LinkedIn pour cette recherche (None si absent)."""
    paging = (page or {}).get("paging") if isinstance(page, dict) else None
    total = _pick(paging, "total_count", "total") if isinstance(paging, dict) else None
    try:
        return int(total) if total is not None else None
    except (TypeError, ValueError):
        return None
