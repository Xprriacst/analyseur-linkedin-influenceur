"""ALE-59 — Publication multi-réseaux (X + Reddit) : logique pure.

Découpage décide/exécute : ce module porte la bibliothèque de subreddits, la
normalisation des sorties du modèle et le découpage en thread — vérifiables
sans réseau ni base. Les appels LLM vivent dans src/llm.py, les appels Zernio
dans src/zernio.py, l'orchestration dans api.py / src/scheduler.py.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

# Limites réseau (X gratuit = 280 caractères par tweet ; titre Reddit = 300,
# définitif après publication — doc Zernio).
X_TWEET_MAX = 280
X_THREAD_MAX_ITEMS = 10
REDDIT_TITLE_MAX = 300
MAX_SUBREDDIT_SUGGESTIONS = 4

_LIBRARY_PATH = Path(__file__).resolve().parent.parent / "data" / "subreddits_b2b.json"

_SUBREDDIT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_]{1,20}$")


@lru_cache(maxsize=1)
def load_subreddit_library() -> tuple[dict[str, Any], ...]:
    """Bibliothèque curatée du dépôt (socle de « l'IA propose, Reddit confirme »).

    Fichier absent ou illisible → tuple vide : la suggestion continue sans socle
    (le modèle propose selon le métier, la vérification Zernio confirme).
    """
    try:
        raw = json.loads(_LIBRARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return ()
    subs = raw.get("subreddits") if isinstance(raw, dict) else None
    if not isinstance(subs, list):
        return ()
    return tuple(s for s in subs if isinstance(s, dict) and s.get("name"))


def normalize_subreddit_name(name: Any) -> str:
    """« r/Marketing », « /r/marketing/ », « marketing » → « Marketing » (sans préfixe).

    Renvoie "" si le nom n'a pas la forme d'un subreddit (l'appelant écarte)."""
    if not isinstance(name, str):
        return ""
    cleaned = name.strip().strip("/")
    cleaned = re.sub(r"^r/", "", cleaned, flags=re.IGNORECASE).strip("/").strip()
    return cleaned if _SUBREDDIT_NAME_RE.match(cleaned) else ""


def library_entry(name: str) -> dict[str, Any] | None:
    wanted = normalize_subreddit_name(name).lower()
    if not wanted:
        return None
    for entry in load_subreddit_library():
        if normalize_subreddit_name(entry.get("name")).lower() == wanted:
            return entry
    return None


def _split_long_chunk(chunk: str, limit: int) -> list[str]:
    """Découpe un paragraphe trop long en phrases, puis en mots en dernier recours."""
    sentences = re.split(r"(?<=[.!?…])\s+", chunk)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        if len(sentence) <= limit:
            current = sentence
            continue
        # Phrase elle-même trop longue : coupe au dernier espace avant la limite.
        remaining = sentence
        while len(remaining) > limit:
            cut = remaining.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            parts.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        current = remaining
    if current:
        parts.append(current)
    return [p for p in (part.strip() for part in parts) if p]


def split_into_tweets(text: str, limit: int = X_TWEET_MAX) -> list[str]:
    """Découpe un texte en tweets ≤ `limit`, en respectant les paragraphes.

    C'est le repli quand le texte (édité par le client) dépasse 280 caractères :
    la bascule en thread annoncée dans la pop-up. Les paragraphes sont regroupés
    tant qu'ils tiennent, jamais coupés en plein mot sauf mot > limite."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= limit:
        return [cleaned]
    tweets: list[str] = []
    current = ""
    for paragraph in (p.strip() for p in cleaned.split("\n\n")):
        if not paragraph:
            continue
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            tweets.append(current)
            current = ""
        if len(paragraph) <= limit:
            current = paragraph
        else:
            chunks = _split_long_chunk(paragraph, limit)
            tweets.extend(chunks[:-1])
            current = chunks[-1] if chunks else ""
    if current:
        tweets.append(current)
    return tweets[:X_THREAD_MAX_ITEMS]


def normalize_x_adaptation(data: Any) -> list[str]:
    """Sortie modèle → liste de tweets propre (1 tweet = post simple, sinon thread).

    Défensif : le modèle peut renvoyer un champ manquant, des tweets vides ou
    trop longs — un tweet > 280 est re-découpé plutôt que d'échouer à l'envoi."""
    tweets_raw = data.get("tweets") if isinstance(data, dict) else None
    if not isinstance(tweets_raw, list):
        single = data.get("content") if isinstance(data, dict) else None
        tweets_raw = [single] if isinstance(single, str) else []
    tweets: list[str] = []
    for item in tweets_raw:
        text = (item or "").strip() if isinstance(item, str) else ""
        if not text:
            continue
        tweets.extend(split_into_tweets(text) if len(text) > X_TWEET_MAX else [text])
    return tweets[:X_THREAD_MAX_ITEMS]


def normalize_reddit_adaptation(data: Any) -> dict[str, Any]:
    """Sortie modèle → {title, body, subreddits:[{name, reason}]} propre.

    Titre manquant → première ligne du corps (même défaut que Zernio) ; noms de
    subreddits normalisés (sans r/), dédoublonnés, plafonnés."""
    data = data if isinstance(data, dict) else {}
    body = (data.get("body") or "").strip() if isinstance(data.get("body"), str) else ""
    title = (data.get("title") or "").strip() if isinstance(data.get("title"), str) else ""
    if not title and body:
        title = body.splitlines()[0].strip()
    title = title[:REDDIT_TITLE_MAX]

    suggestions: list[dict[str, str]] = []
    seen: set[str] = set()
    raw_subs = data.get("subreddits")
    for item in raw_subs if isinstance(raw_subs, list) else []:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        name = normalize_subreddit_name(item.get("name"))
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        reason = (item.get("reason") or "").strip() if isinstance(item.get("reason"), str) else ""
        suggestions.append({"name": name, "reason": reason})
        if len(suggestions) >= MAX_SUBREDDIT_SUGGESTIONS:
            break

    return {"title": title, "body": body, "subreddits": suggestions}


def suggestion_metadata(name: str) -> dict[str, Any]:
    """Métadonnées d'affichage d'un subreddit (badges de la pop-up).

    Fusionne l'entrée bibliothèque si présente ; les champs absents restent None
    (le front n'affiche alors pas le badge)."""
    entry = library_entry(name) or {}
    return {
        "in_library": bool(entry),
        "selfpromo_tolerance": entry.get("selfpromo_tolerance"),
        "min_karma_advised": entry.get("min_karma_advised"),
        "geo_score": entry.get("geo_score"),
        "notes": entry.get("notes"),
        "language": entry.get("language"),
    }
