"""Chat agent V1 — assistant éditorial LinkedIn.

POST /me/chat → SSE-streamed response from Claude.
History is persisted in Supabase (chat_conversations + chat_messages).
"""

from __future__ import annotations

import json
import os
from typing import Generator, Optional

import anthropic

_SYSTEM = """\
Tu es un assistant éditorial LinkedIn expert. Tu aides l'utilisateur à créer \
du contenu LinkedIn performant et à améliorer sa stratégie de contenu.

Contexte client :
{user_context}

Influenceurs analysés (corpus d'inspiration) :
{corpus_summary}

Missions :
- Proposer des idées de posts LinkedIn originales, adaptées au profil du client
- Analyser un post soumis et suggérer des améliorations concrètes
- Expliquer les patterns de performance des influenceurs du corpus
- Réécrire, raccourcir, allonger ou reformuler un post
- Répondre aux questions sur la stratégie éditoriale LinkedIn

Règles :
- Réponds toujours en français, de manière concise et actionnable
- Appuie tes recommandations sur les données du corpus quand elles existent
- Tu ne peux pas publier directement sur LinkedIn dans cette version\
"""


def _user_context_text(profile: Optional[dict]) -> str:
    if not profile:
        return "Profil non renseigné."
    mapping = [
        ("display_name", "Nom"),
        ("brand_name", "Marque / projet"),
        ("industry", "Secteur"),
        ("target_audience", "Audience cible"),
        ("core_offer", "Offre principale"),
        ("tone", "Ton"),
        ("linkedin_objective", "Objectif LinkedIn"),
        ("topics_to_cover", "Sujets à couvrir"),
        ("language", "Langue"),
        ("extra_context", "Contexte supplémentaire"),
    ]
    parts = []
    for key, label in mapping:
        val = (profile.get(key) or "").strip()
        if val:
            parts.append(f"{label} : {val}")
    return "\n".join(parts) if parts else "Profil non renseigné."


def _corpus_summary_text(corpus: list[dict]) -> str:
    if not corpus:
        return "Aucun influenceur analysé pour l'instant."
    rows = []
    for inf in corpus[:6]:
        profile = inf.get("profile") or {}
        handle = inf.get("handle", "?")
        name = (profile.get("name") or "").strip() or handle
        followers = profile.get("follower_count") or 0
        n_posts = len(inf.get("posts") or [])
        rows.append(f"- {name} (@{handle}) : {followers:,} abonnés, {n_posts} posts analysés")
    return "\n".join(rows)


def stream_chat(
    messages: list[dict],
    user_profile: Optional[dict],
    corpus: list[dict],
) -> Generator[str, None, None]:
    """Yield SSE-formatted text chunks then a [DONE] sentinel."""
    client = anthropic.Anthropic()

    system = _SYSTEM.format(
        user_context=_user_context_text(user_profile),
        corpus_summary=_corpus_summary_text(corpus),
    )

    anthropic_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]

    with client.messages.stream(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        max_tokens=1024,
        system=system,
        messages=anthropic_messages,
    ) as stream:
        for text in stream.text_stream:
            yield f"data: {json.dumps({'text': text})}\n\n"

    yield "data: [DONE]\n\n"
