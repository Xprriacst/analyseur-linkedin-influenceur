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

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
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
    topic = post.get("topic") or ""

    preview = text[:300] + ("…" if len(text) > 300 else "")

    header = f"*{topic}*" if topic else "*Post généré*"
    blocks: list[dict] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{header}\n> {preview}"},
        },
        {
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
                    "action_id": "reject_post",
                    "value": post_id,
                    "text": {"type": "plain_text", "text": "❌ Rejeter", "emoji": True},
                    "style": "danger",
                },
            ],
        },
    ]

    data = _api_call(
        "chat.postMessage",
        bot_token,
        channel=channel_id,
        text=header,
        blocks=blocks,
    )
    return data["ts"]


def update_post_message(
    bot_token: str,
    channel_id: str,
    ts: str,
    post: dict,
    status: str,
) -> None:
    """Replace the buttons with a status badge after a user validates or rejects a post."""
    topic = post.get("topic") or ""
    text = post.get("post") or ""
    preview = text[:300] + ("…" if len(text) > 300 else "")

    badge = "✅ Validé — prêt à publier" if status == "validated" else "❌ Rejeté"
    header = f"*{topic}*" if topic else "*Post généré*"

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{header}\n> {preview}\n{badge}"},
        }
    ]
    _api_call(
        "chat.update",
        bot_token,
        channel=channel_id,
        ts=ts,
        text=header,
        blocks=blocks,
    )


def send_scheduled_post_for_validation(
    bot_token: str,
    channel_id: str,
    scheduled_post: dict,
) -> str:
    """Post a scheduled LinkedIn post to Slack with validation buttons."""
    post_id = scheduled_post.get("id", "")
    text = scheduled_post.get("post_text") or ""
    scheduled_at = scheduled_post.get("scheduled_at") or ""
    preview = _quote_full_text(text)

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Post LinkedIn programmé*\n"
                    f"*Publication prévue* : `{scheduled_at}`"
                ),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": preview},
        },
        {
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
                    "action_id": "decline_scheduled_post",
                    "value": post_id,
                    "text": {"type": "plain_text", "text": "❌ Refuser", "emoji": True},
                    "style": "danger",
                },
            ],
        },
    ]

    data = _api_call(
        "chat.postMessage",
        bot_token,
        channel=channel_id,
        text="Validation d'un post LinkedIn programmé",
        blocks=blocks,
    )
    return data["ts"]


def update_scheduled_post_message(
    bot_token: str,
    channel_id: str,
    ts: str,
    scheduled_post: dict,
    status: str,
) -> None:
    """Replace scheduled-post validation buttons with the final Slack status."""
    text = scheduled_post.get("post_text") or ""
    scheduled_at = scheduled_post.get("scheduled_at") or ""
    preview = _quote_full_text(text)
    badge = (
        "✅ Validé — publication maintenue"
        if status == "validated"
        else "❌ Refusé — programmation annulée"
    )

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Post LinkedIn programmé*\n"
                    f"*Publication prévue* : `{scheduled_at}`"
                ),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": preview},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": badge},
        },
    ]
    _api_call(
        "chat.update",
        bot_token,
        channel=channel_id,
        ts=ts,
        text="Validation d'un post LinkedIn programmé",
        blocks=blocks,
    )


def verify_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Verify a Slack request signature to prevent webhook spoofing.

    Returns True if the signature is valid, False otherwise.
    """
    secret = _signing_secret()
    if not secret:
        return True  # not configured → skip verification in dev

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
