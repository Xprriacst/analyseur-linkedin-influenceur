"""Deterministic Instagram pattern detection."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any


# Instagram CTA types
_LIEN_BIO = re.compile(r"\b(lien en bio|link in bio|lien dans la bio|link in my bio)\b", re.IGNORECASE)
_DM = re.compile(r"\b(dm|dm[- ]me|écris[- ]moi|message[- ]moi|envoie[- ]moi|message me|send me a dm)\b", re.IGNORECASE)
_TAG = re.compile(r"\b(tag|tague|tagge|tag a friend|taguez)\b", re.IGNORECASE)
_SAVE = re.compile(r"\b(sauvegarde|save|enregistre|bookmark)\b", re.IGNORECASE)
_FOLLOW = re.compile(r"\b(abonne[- ]toi|follow|suivez|suis[- ]moi|follow me|rejoins)\b", re.IGNORECASE)


def detect_ig_cta(text: str, transcript: str = "") -> str | None:
    """Detect Instagram CTA type from caption text and optional transcript.

    Returns one of: "LIEN_BIO", "DM", "TAG", "SAVE", "FOLLOW", or None.
    Searches both text (caption) and transcript.
    """
    combined = f"{text}\n{transcript}"
    if _LIEN_BIO.search(combined):
        return "LIEN_BIO"
    if _DM.search(combined):
        return "DM"
    if _TAG.search(combined):
        return "TAG"
    if _SAVE.search(combined):
        return "SAVE"
    if _FOLLOW.search(combined):
        return "FOLLOW"
    return None


def detect_ig_hook_type(text: str, transcript: str = "") -> str:
    """Classify the hook archetype from caption first line and transcript opening.

    Returns: question | story | stat | bold_claim | list | contrarian | other
    """
    if not text.strip() and not transcript.strip():
        return "other"

    # Use first line of caption + first ~200 chars of transcript as hook context
    first_line = ""
    if text.strip():
        first_line = text.strip().split("\n")[0].strip()

    transcript_hook = ""
    if transcript.strip():
        words = transcript.strip().split()
        transcript_hook = " ".join(words[:20])

    fl = first_line.lower()
    tl = transcript_hook.lower()
    combined = f"{fl} {tl}"

    # Stat: number + percentage or multiplier
    if re.search(r"\b\d{1,3}\s?%", first_line) or re.search(r"\b\d+\s*(x|fois)\b", fl):
        return "stat"
    if re.search(r"\b\d{1,3}\s?%", transcript_hook) or re.search(r"\b\d+\s*(x|fois)\b", tl):
        return "stat"

    # List: numbered items
    if re.match(r"^\s*\d+\s+(façons|raisons|étapes|erreurs|conseils|astuces|leçons|tips)\b", fl):
        return "list"
    if re.match(r"^\s*\d+\s+(façons|raisons|étapes|erreurs|conseils|astuces|leçons|tips)\b", tl):
        return "list"

    # Question
    if first_line.endswith("?") or transcript_hook.endswith("?"):
        return "question"
    if re.search(r"\b(comment|pourquoi|est-ce que|qu'est-ce|qui est|how to|what if)\b", fl):
        return "question"

    # Contrarian
    contrarian = ["c'est faux", "tout le monde se trompe", "personne ne", "arrête de",
                  "stop ", "oublie", "le mythe", "on vous ment", "la vérité que"]
    if any(m in combined for m in contrarian):
        return "contrarian"

    # Bold claim
    bold = ["jamais", "toujours", "personne", "tout le monde", "le secret", "la vérité",
            "the truth", "nobody tells you", "ce que personne"]
    if any(m in combined for m in bold):
        return "bold_claim"

    # Story: short opening line without question mark (narrative/micro-story)
    if len(first_line) < 80 and not first_line.endswith("?"):
        return "story"

    return "other"


def detect_ig_hashtag_strategy(posts: list[dict]) -> dict[str, Any]:
    """Analyze hashtag usage across posts.

    Returns: {count_median, top_hashtags, uses_hashtags_pct}
    """
    if not posts:
        return {"count_median": 0, "top_hashtags": [], "uses_hashtags_pct": 0}

    all_hashtags: list[str] = []
    hashtag_counts: list[int] = []
    posts_with_hashtags = 0

    for p in posts:
        tags = p.get("hashtags") or []
        if isinstance(tags, list):
            count = len(tags)
            all_hashtags.extend(tags)
        else:
            count = 0
        hashtag_counts.append(count)
        if count > 0:
            posts_with_hashtags += 1

    if hashtag_counts:
        sorted_counts = sorted(hashtag_counts)
        mid = len(sorted_counts) // 2
        count_median = sorted_counts[mid]
    else:
        count_median = 0

    tag_counter = Counter(all_hashtags)
    top_hashtags = [(tag, n) for tag, n in tag_counter.most_common(10)]
    uses_hashtags_pct = round((posts_with_hashtags / len(posts)) * 100, 1) if posts else 0

    return {
        "count_median": count_median,
        "top_hashtags": top_hashtags,
        "uses_hashtags_pct": uses_hashtags_pct,
    }


def _length_bucket(words: int) -> str:
    if words < 30:
        return "court"
    if words < 100:
        return "moyen"
    return "long"


def analyze_ig_patterns(posts: list[dict]) -> dict[str, Any]:
    """Run all deterministic pattern detectors on Instagram posts/reels.

    Returns same shape as analyze_patterns (LinkedIn) for compatibility.
    """
    enriched = []
    for p in posts:
        text = p.get("text", "") or ""
        transcript = p.get("transcript", "") or ""
        cta = detect_ig_cta(text, transcript)
        enriched.append({
            **p,
            "cta_keyword": cta,
            "has_cta": cta is not None,
            "hook_type": detect_ig_hook_type(text, transcript),
            "length_bucket": _length_bucket(p.get("length_words", 0)),
        })

    hook_counts = Counter(p["hook_type"] for p in enriched)
    length_counts = Counter(p["length_bucket"] for p in enriched)
    cta_count = sum(1 for p in enriched if p["has_cta"])
    hashtag_strategy = detect_ig_hashtag_strategy(posts)

    return {
        "posts_enriched": enriched,
        "hook_distribution": dict(hook_counts),
        "length_distribution": dict(length_counts),
        "cta_count": cta_count,
        "cta_share_pct": round((cta_count / len(enriched)) * 100, 1) if enriched else 0,
        "cta_keywords": Counter(
            p["cta_keyword"] for p in enriched if p["cta_keyword"]
        ).most_common(10),
        "hashtag_strategy": hashtag_strategy,
    }
