"""Thin Slack API client (workspace integration for idea validation).

Uses stdlib urllib only — no new HTTP dependency.
Relies on a Slack App with:
  - Bot scopes: chat:write, im:write
  - User scopes: identity.basic
  - Interactive Components Request URL: <BACKEND_URL>/slack/webhooks/interactive
  - OAuth Redirect URL: <FRONTEND_URL>?slack_code=<code>

Env vars required:
  SLACK_CLIENT_ID        – from Slack App "Basic Information"
  SLACK_CLIENT_SECRET    – from Slack App "Basic Information"
  SLACK_SIGNING_SECRET   – from Slack App "Basic Information"
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import zoneinfo
from typing import Any

SLACK_API = "https://slack.com/api"
OAUTH_URL = "https://slack.com/oauth/v2/authorize"
BOT_SCOPES = "chat:write,im:write"
USER_SCOPES = "identity.basic"

# A Slack section block text field accepts up to 3000 chars; LinkedIn posts cap
# at 3000 too. Keep a margin for the "> " quote prefixes added per line.
_MAX_QUOTE_LEN = 2900


def _quote_full_text(text: str) -> str:
    """Render a post as a Slack mrkdwn block quote, full text (capped at the
    block-size limit so Slack never rejects the message)."""
    text = text or ""
    truncated = len(text) > _MAX_QUOTE_LEN
    if truncated:
        text = text[:_MAX_QUOTE_LEN].rstrip() + "…"
    # Prefix every line so multi-paragraph posts render as one quote block.
    return "\n".join("> " + line for line in text.split("\n"))


_FR_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_FR_MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
# Slack image blocks require a publicly reachable image_url; cap the count so a
# post with many medias never blows past Slack's block limit.
_MAX_IMAGE_BLOCKS = 5


def _format_scheduled_at(scheduled_at: str) -> str:
    """Render an ISO 8601 datetime as readable French local time (Europe/Paris).

    Ex. `2026-06-22T09:00:00+02:00` → `lundi 22 juin 2026 à 09h00`.
    Falls back to the raw string if it can't be parsed.
    """
    if not scheduled_at:
        return "—"
    raw = scheduled_at.replace("Z", "+00:00") if isinstance(scheduled_at, str) else scheduled_at
    try:
        dt = datetime.datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return str(scheduled_at)
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        dt = dt.astimezone(zoneinfo.ZoneInfo("Europe/Paris"))
    except Exception:
        pass
    return (
        f"{_FR_DAYS[dt.weekday()]} {dt.day} {_FR_MONTHS[dt.month - 1]} "
        f"{dt.year} à {dt.hour:02d}h{dt.minute:02d}"
    )


def _image_blocks(media_items: Any) -> list[dict]:
    """Build Slack `image` blocks from a scheduled post's media_items.

    Only items typed as image with a public http(s) URL are rendered — Slack
    fetches the URL itself, so base64/data URLs and private paths are skipped.
    """
    blocks: list[dict] = []
    for item in (media_items or []):
        if not isinstance(item, dict):
            continue
        url = item.get("url") or ""
        if item.get("type") == "image" and isinstance(url, str) and url.startswith(("http://", "https://")):
            alt = str(item.get("title") or "Image du post")[:150]
            blocks.append({"type": "image", "image_url": url, "alt_text": alt})
            if len(blocks) >= _MAX_IMAGE_BLOCKS:
                break
    return blocks


class SlackError(RuntimeError):
    """Raised when Slack returns an error or is not configured."""


def enabled() -> bool:
    return bool(
        os.environ.get("SLACK_CLIENT_ID")
        and os.environ.get("SLACK_CLIENT_SECRET")
    )


def _client_id() -> str:
    v = os.environ.get("SLACK_CLIENT_ID")
    if not v:
        raise SlackError("SLACK_CLIENT_ID manquant dans l'environnement serveur.")
    return v


def _client_secret() -> str:
    v = os.environ.get("SLACK_CLIENT_SECRET")
    if not v:
        raise SlackError("SLACK_CLIENT_SECRET manquant dans l'environnement serveur.")
    return v


def _signing_secret() -> str:
    return os.environ.get("SLACK_SIGNING_SECRET", "")


def _api_call(method: str, bot_token: str, **kwargs: Any) -> dict:
    """POST to a Slack Web API method."""
    url = f"{SLACK_API}/{method}"
    body = json.dumps(kwargs).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {bot_token}")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data: dict = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SlackError(f"Slack API {method} HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SlackError(f"Slack injoignable : {exc.reason}") from exc
    if not data.get("ok"):
        raise SlackError(f"Slack {method} : {data.get('error', 'erreur inconnue')}")
    return data


def build_oauth_url(redirect_uri: str, state: str = "") -> str:
    """Return the Slack OAuth authorization URL to redirect the user to."""
    params: dict[str, str] = {
        "client_id": _client_id(),
        "scope": BOT_SCOPES,
        "user_scope": USER_SCOPES,
        "redirect_uri": redirect_uri,
    }
    if state:
        params["state"] = state
    return f"{OAUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(code: str, redirect_uri: str) -> dict:
    """Exchange an OAuth code for tokens.

    Returns the full `oauth.v2.access` response dict which includes:
      access_token      – bot token (xoxb-...)
      authed_user.id    – Slack user ID of the installer
      team.id / team.name
    """
    url = f"{SLACK_API}/oauth.v2.access"
    body = urllib.parse.urlencode({
        "client_id": _client_id(),
        "client_secret": _client_secret(),
        "code": code,
        "redirect_uri": redirect_uri,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data: dict = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SlackError(f"Échange de code Slack HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SlackError(f"Slack injoignable : {exc.reason}") from exc
    if not data.get("ok"):
        raise SlackError(f"oauth.v2.access : {data.get('error', 'erreur inconnue')}")
    return data


def open_dm_channel(bot_token: str, slack_user_id: str) -> str:
    """Open (or resume) a DM with the user; return the channel ID (D0...)."""
    data = _api_call("conversations.open", bot_token, users=slack_user_id)
    channel_id: str = data["channel"]["id"]
    return channel_id


def send_idea_for_validation(
    bot_token: str,
    channel_id: str,
    idea: dict,
) -> str:
    """Post an idea as a Slack message with ✅ / ❌ buttons.

    Returns the message timestamp (ts) for future updates.
    """
    idea_id = idea.get("id", "")
    title = idea.get("title") or "Idée sans titre"
    hook = idea.get("hook") or ""
    funnel = idea.get("funnel") or ""
    angle = idea.get("angle") or ""

    text_parts = [f"*{title}*"]
    if hook:
        text_parts.append(f"> {hook}")
    if funnel or angle:
        meta = " · ".join(p for p in [funnel, angle] if p)
        text_parts.append(f"_{meta}_")

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(text_parts)},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "validate_idea",
                    "value": idea_id,
                    "text": {"type": "plain_text", "text": "✅ Retenir", "emoji": True},
                    "style": "primary",
                },
                {
                    "type": "button",
                    "action_id": "decline_idea",
                    "value": idea_id,
                    "text": {"type": "plain_text", "text": "❌ Écarter", "emoji": True},
                    "style": "danger",
                },
            ],
        },
    ]

    data = _api_call(
        "chat.postMessage",
        bot_token,
        channel=channel_id,
        text=title,
        blocks=blocks,
    )
    return data["ts"]


def update_idea_message(
    bot_token: str,
    channel_id: str,
    ts: str,
    idea: dict,
    status: str,
) -> None:
    """Replace the buttons with a status badge after a user validates or declines."""
    title = idea.get("title") or "Idée sans titre"
    hook = idea.get("hook") or ""

    if status == "validated":
        badge = "✅ Retenu"
    elif status == "declined":
        badge = "❌ Écarté"
    else:
        badge = ""

    text_parts = [f"*{title}*"]
    if hook:
        text_parts.append(f"> {hook}")
    if badge:
        text_parts.append(badge)

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(text_parts)},
        }
    ]
    _api_call(
        "chat.update",
        bot_token,
        channel=channel_id,
        ts=ts,
        text=title,
        blocks=blocks,
    )


def send_post_for_validation(
    bot_token: str,
    channel_id: str,
    post: dict,
) -> str:
    """Post a generated post to Slack DM with ✅ / ❌ buttons for validation.

    Returns the message timestamp (ts) for future updates.
    """
    post_id = post.get("id", "")
    text = post.get("post") or ""

    # Titre neutre : on ne montre PAS le sujet/prompt de génération sur Slack —
    # la validation ne porte que sur le texte du post lui-même.
    header = "*📝 Post à valider*"
    blocks: list[dict] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": header},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": _quote_full_text(text)},
        },
        *_image_blocks(post.get("media_items")),
        _post_actions_block(post_id),
    ]

    data = _api_call(
        "chat.postMessage",
        bot_token,
        channel=channel_id,
        text=header,
        blocks=blocks,
    )
    return data["ts"]


def _post_actions_block(post_id: str) -> dict:
    """Validate / edit / reject buttons for a generated-post Slack message."""
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "action_id": "validate_post",
                "value": post_id,
                "text": {"type": "plain_text", "text": "✅ Valider", "emoji": True},
                "style": "primary",
            },
            {
                "type": "button",
                "action_id": "edit_post",
                "value": post_id,
                "text": {"type": "plain_text", "text": "✏️ Modifier", "emoji": True},
            },
            {
                "type": "button",
                "action_id": "reject_post",
                "value": post_id,
                "text": {"type": "plain_text", "text": "❌ Rejeter", "emoji": True},
                "style": "danger",
            },
        ],
    }


_POST_BADGES = {
    "validated": "✅ Validé — prêt à publier",
    "rejected": "❌ Rejeté",
    "edited": "✏️ Modifié — à re-valider",
}


def update_post_message(
    bot_token: str,
    channel_id: str,
    ts: str,
    post: dict,
    status: str,
) -> None:
    """Refresh a generated-post Slack message after a validate/reject/edit action.

    `validated` / `rejected` are terminal → buttons replaced by a status badge.
    `edited` keeps the validate/edit/reject buttons so the user can re-validate
    the new content (symétrie avec les posts programmés)."""
    text = post.get("post") or ""
    header = "*📝 Post à valider*"
    badge = _POST_BADGES.get(status, "")

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": header},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": _quote_full_text(text)},
        },
        *_image_blocks(post.get("media_items")),
    ]
    if badge:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": badge}})
    # Non-terminal states (edited) keep the action buttons for re-validation.
    if status not in ("validated", "rejected"):
        blocks.append(_post_actions_block(post.get("id", "")))

    _api_call(
        "chat.update",
        bot_token,
        channel=channel_id,
        ts=ts,
        text=header,
        blocks=blocks,
    )


def _scheduled_post_actions_block(post_id: str) -> dict:
    """Validate / edit / decline buttons for a scheduled-post Slack message."""
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "action_id": "validate_scheduled_post",
                "value": post_id,
                "text": {"type": "plain_text", "text": "✅ Valider la programmation", "emoji": True},
                "style": "primary",
            },
            {
                "type": "button",
                "action_id": "edit_scheduled_post",
                "value": post_id,
                "text": {"type": "plain_text", "text": "✏️ Modifier", "emoji": True},
            },
            {
                "type": "button",
                "action_id": "decline_scheduled_post",
                "value": post_id,
                "text": {"type": "plain_text", "text": "❌ Refuser", "emoji": True},
                "style": "danger",
            },
        ],
    }


def send_scheduled_post_for_validation(
    bot_token: str,
    channel_id: str,
    scheduled_post: dict,
) -> str:
    """Post a scheduled LinkedIn post to Slack with validation buttons."""
    post_id = scheduled_post.get("id", "")
    text = scheduled_post.get("post_text") or ""
    scheduled_at = _format_scheduled_at(scheduled_post.get("scheduled_at") or "")
    preview = _quote_full_text(text)

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Post LinkedIn programmé*\n"
                    f"*Publication prévue* : {scheduled_at}"
                ),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": preview},
        },
        *_image_blocks(scheduled_post.get("media_items")),
        _scheduled_post_actions_block(post_id),
    ]

    data = _api_call(
        "chat.postMessage",
        bot_token,
        channel=channel_id,
        text="Validation d'un post LinkedIn programmé",
        blocks=blocks,
    )
    return data["ts"]


_SCHEDULED_BADGES = {
    "validated": "✅ Validé — publication maintenue",
    "declined": "❌ Refusé — programmation annulée",
    "edited": "✏️ Modifié — à re-valider",
}


def update_scheduled_post_message(
    bot_token: str,
    channel_id: str,
    ts: str,
    scheduled_post: dict,
    status: str,
) -> None:
    """Refresh a scheduled-post Slack message after a validate/decline/edit action.

    `validated` / `declined` are terminal → buttons are replaced by a status badge.
    `edited` keeps the validate/edit/decline buttons so the user can re-validate the
    new content (ALE-149).
    """
    post_id = scheduled_post.get("id", "")
    text = scheduled_post.get("post_text") or ""
    scheduled_at = _format_scheduled_at(scheduled_post.get("scheduled_at") or "")
    preview = _quote_full_text(text)
    badge = _SCHEDULED_BADGES.get(status, "")

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Post LinkedIn programmé*\n"
                    f"*Publication prévue* : {scheduled_at}"
                ),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": preview},
        },
        *_image_blocks(scheduled_post.get("media_items")),
    ]
    if badge:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": badge}})
    # Non-terminal states (edited) keep the action buttons for re-validation.
    if status not in ("validated", "declined"):
        blocks.append(_scheduled_post_actions_block(post_id))

    _api_call(
        "chat.update",
        bot_token,
        channel=channel_id,
        ts=ts,
        text="Validation d'un post LinkedIn programmé",
        blocks=blocks,
    )


def open_post_edit_modal(
    bot_token: str,
    trigger_id: str,
    scheduled_post: dict,
    channel_id: str,
    message_ts: str,
) -> None:
    """Open a Slack modal to edit a scheduled post's text (ALE-149).

    The modal carries the post id + the originating message coordinates in
    `private_metadata` so the `view_submission` handler can persist the edit and
    refresh the original message. Must be called within ~3 s of the button click
    (the `trigger_id` expires quickly).
    """
    post_id = scheduled_post.get("id", "")
    text = scheduled_post.get("post_text") or ""
    metadata = json.dumps({
        "post_id": post_id,
        "channel_id": channel_id,
        "message_ts": message_ts,
    })
    view = {
        "type": "modal",
        "callback_id": "edit_scheduled_post_modal",
        "private_metadata": metadata,
        "title": {"type": "plain_text", "text": "Modifier le post"},
        "submit": {"type": "plain_text", "text": "Enregistrer"},
        "close": {"type": "plain_text", "text": "Annuler"},
        "blocks": [
            {
                "type": "input",
                "block_id": "post_text_block",
                "label": {"type": "plain_text", "text": "Texte du post LinkedIn"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "post_text_input",
                    "multiline": True,
                    "max_length": 3000,
                    "initial_value": text[:3000],
                },
            },
        ],
    }
    _api_call("views.open", bot_token, trigger_id=trigger_id, view=view)


def open_generated_post_edit_modal(
    bot_token: str,
    trigger_id: str,
    post: dict,
    channel_id: str,
    message_ts: str,
) -> None:
    """Open a Slack modal to edit a generated post's text (envoi direct).

    Symétrie avec `open_post_edit_modal` (posts programmés) : le `view_submission`
    handler (callback_id `edit_post_modal`) persiste le nouveau texte et rafraîchit
    le message d'origine. `trigger_id` expire en ~3 s → appeler dès le clic."""
    post_id = post.get("id", "")
    text = post.get("post") or ""
    metadata = json.dumps({
        "post_id": post_id,
        "channel_id": channel_id,
        "message_ts": message_ts,
    })
    view = {
        "type": "modal",
        "callback_id": "edit_post_modal",
        "private_metadata": metadata,
        "title": {"type": "plain_text", "text": "Modifier le post"},
        "submit": {"type": "plain_text", "text": "Enregistrer"},
        "close": {"type": "plain_text", "text": "Annuler"},
        "blocks": [
            {
                "type": "input",
                "block_id": "post_text_block",
                "label": {"type": "plain_text", "text": "Texte du post LinkedIn"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "post_text_input",
                    "multiline": True,
                    "max_length": 3000,
                    "initial_value": text[:3000],
                },
            },
        ],
    }
    _api_call("views.open", bot_token, trigger_id=trigger_id, view=view)


def verify_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Verify a Slack request signature to prevent webhook spoofing.

    Returns True if the signature is valid, False otherwise.
    """
    secret = _signing_secret()
    if not secret:
        return False  # fail-closed: pas de secret = webhook rejetée

    # Reject requests older than 5 minutes
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except (ValueError, TypeError):
        return False

    base = f"v0:{timestamp}:{body.decode('utf-8', errors='replace')}"
    expected = "v0=" + hmac.new(
        secret.encode("utf-8"),
        base.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")
