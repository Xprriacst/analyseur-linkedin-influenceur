"""Création de pages Notion pour les audits du tunnel /start.

Patron identique à `mailer.py` : urllib stdlib, optionnel — sans
`NOTION_TOKEN` / `NOTION_AUDITS_PARENT_PAGE_ID`, `enabled()` est faux et
**rien ne casse** (l'audit reste stocké en base + page publique site).

⚠️ L'API Notion ne permet PAS de basculer « Share to web ». Pour que les
sous-pages soient lisibles sans compte, publier **une fois** la page parente
(`NOTION_AUDITS_PARENT_PAGE_ID`) via Share → Publish to web.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TIMEOUT_S = 30


class NotionError(RuntimeError):
    """Notion a répondu une erreur, ou la configuration est absente."""


def enabled() -> bool:
    return bool(os.environ.get("NOTION_TOKEN")) and bool(
        os.environ.get("NOTION_AUDITS_PARENT_PAGE_ID")
    )


def _token() -> str:
    key = os.environ.get("NOTION_TOKEN")
    if not key:
        raise NotionError("NOTION_TOKEN manquant.")
    return key


def _parent_id() -> str:
    parent = (os.environ.get("NOTION_AUDITS_PARENT_PAGE_ID") or "").strip()
    if not parent:
        raise NotionError("NOTION_AUDITS_PARENT_PAGE_ID manquant.")
    return parent.replace("-", "")


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
            body = response.read().decode("utf-8") or "{}"
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise NotionError(f"Notion {exc.code} : {detail}") from exc
    except Exception as exc:
        raise NotionError(f"Appel Notion impossible : {exc}") from exc


def _rich(text: str) -> list[dict[str, Any]]:
    """Découpe un long texte en chunks Notion (limite 2000 car. par rich_text)."""
    clean = (text or "").strip()
    if not clean:
        return [{"type": "text", "text": {"content": ""}}]
    chunks: list[dict[str, Any]] = []
    for i in range(0, len(clean), 1900):
        chunks.append({"type": "text", "text": {"content": clean[i : i + 1900]}})
    return chunks


def _heading(text: str, level: int = 2) -> dict[str, Any]:
    key = {1: "heading_1", 2: "heading_2", 3: "heading_3"}.get(level, "heading_2")
    return {
        "object": "block",
        "type": key,
        key: {"rich_text": _rich(text)},
    }


def _paragraph(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _rich(text)},
    }


def _bulleted(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich(text)},
    }


def _quote(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "quote",
        "quote": {"rich_text": _rich(text)},
    }


def _divider() -> dict[str, Any]:
    return {"object": "block", "type": "divider", "divider": {}}


def audit_to_blocks(
    full_name: str,
    audit: dict[str, Any],
    *,
    email: str = "",
    phone: str = "",
    linkedin_url: str = "",
    calendly_url: str = "",
) -> list[dict[str, Any]]:
    """Traduit l'audit JSON en blocs Notion (max ~100 blocs / requête create)."""
    blocks: list[dict[str, Any]] = []
    first = (full_name or "").strip().split(" ")[0] or "toi"

    meta_bits = [b for b in [email, phone, linkedin_url] if b]
    if meta_bits:
        blocks.append(_paragraph(" · ".join(meta_bits)))
        blocks.append(_divider())

    blocks.append(_paragraph(
        f"Salut {first}, voici ton audit LinkedIn complet — positionnement, "
        "profil réécrit, bannières, comptes à suivre, angles de posts et plan 90 jours."
    ))

    if audit.get("positioning"):
        blocks.append(_heading("Ton positionnement"))
        blocks.append(_paragraph(audit["positioning"]))

    if audit.get("headline"):
        blocks.append(_heading("Ton titre LinkedIn, réécrit"))
        blocks.append(_paragraph("À copier-coller directement dans ton profil :"))
        blocks.append(_quote(audit["headline"]))

    if audit.get("about"):
        blocks.append(_heading("Ta section « Infos », réécrite"))
        blocks.append(_quote(audit["about"]))

    if audit.get("banners"):
        blocks.append(_heading("3 concepts de bannière"))
        for b in audit["banners"]:
            title = b.get("title") or ""
            line = title
            if b.get("subtitle"):
                line += f" — {b['subtitle']}"
            blocks.append(_bulleted(line))
            if b.get("direction"):
                blocks.append(_paragraph(f"Direction visuelle : {b['direction']}"))

    if audit.get("influencers"):
        blocks.append(_heading("Les comptes à suivre dans ta niche"))
        blocks.append(_paragraph(
            "Chaque nom ouvre une recherche LinkedIn — on préfère un lien qui marche "
            "à une URL de profil devinée."
        ))
        for i in audit["influencers"]:
            name = i.get("name") or ""
            reason = i.get("reason") or ""
            url = i.get("search_url") or ""
            label = f"{name}" + (f" — {reason}" if reason else "")
            if url:
                # Lien dans le rich_text
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{
                            "type": "text",
                            "text": {"content": label[:1900], "link": {"url": url}},
                        }],
                    },
                })
            else:
                blocks.append(_bulleted(label))

    if audit.get("post_angles"):
        blocks.append(_heading("5 angles de posts pour démarrer"))
        for a in audit["post_angles"]:
            blocks.append(_bulleted(a))

    if audit.get("prospecting"):
        blocks.append(_heading("Qui cibler, et comment l'aborder"))
        blocks.append(_paragraph(audit["prospecting"]))

    if audit.get("plan"):
        blocks.append(_heading("Ton plan sur 90 jours"))
        for step in audit["plan"]:
            blocks.append(_heading(str(step.get("horizon") or ""), level=3))
            for action in step.get("actions") or []:
                blocks.append(_bulleted(action))

    if audit.get("services"):
        blocks.append(_heading("Ce qu'on peut faire ensemble"))
        for s in audit["services"]:
            name = s.get("name") or ""
            pitch = s.get("pitch") or ""
            reason = s.get("reason") or ""
            blocks.append(_bulleted(name))
            if pitch:
                blocks.append(_paragraph(pitch))
            if reason:
                blocks.append(_paragraph(f"Pour toi : {reason}"))

    if calendly_url:
        blocks.append(_divider())
        blocks.append(_heading("Suite"))
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {
                        "content": "Réserver 15 minutes avec Tom",
                        "link": {"url": calendly_url},
                    },
                }],
            },
        })

    # Notion limite à 100 enfants à la création.
    return blocks[:100]


def create_audit_page(
    full_name: str,
    audit: dict[str, Any],
    *,
    email: str = "",
    phone: str = "",
    linkedin_url: str = "",
    calendly_url: str = "",
) -> dict[str, str]:
    """Crée la page Notion. Renvoie {page_id, url, public_url?}."""
    if not enabled():
        raise NotionError("Notion non configuré (NOTION_TOKEN / parent).")

    title = f"Audit LinkedIn — {(full_name or '').strip() or 'Prospect'}"
    children = audit_to_blocks(
        full_name,
        audit,
        email=email,
        phone=phone,
        linkedin_url=linkedin_url,
        calendly_url=calendly_url,
    )
    payload: dict[str, Any] = {
        "parent": {"page_id": _parent_id()},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title[:2000]}}],
            }
        },
        "children": children,
    }
    page = _request("POST", "/pages", payload)
    page_id = str(page.get("id") or "")
    url = str(page.get("url") or "")
    public_url = page.get("public_url")
    # Relire pour récupérer public_url si le parent est déjà publié.
    if page_id and not public_url:
        try:
            refreshed = _request("GET", f"/pages/{page_id.replace('-', '')}")
            public_url = refreshed.get("public_url")
            url = str(refreshed.get("url") or url)
        except NotionError:
            pass
    return {
        "page_id": page_id,
        "url": url,
        "public_url": str(public_url) if public_url else "",
    }


def create_audit_page_safe(*args: Any, **kwargs: Any) -> dict[str, str] | None:
    """Best-effort : None si Notion est absent ou en erreur."""
    if not enabled():
        return None
    try:
        return create_audit_page(*args, **kwargs)
    except Exception as exc:
        print(f"[notion] création page audit impossible : {exc}")
        return None
