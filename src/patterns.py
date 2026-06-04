"""Deterministic pattern detection on post content."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any


CTA_PATTERNS = [
    re.compile(r"\bcomment(?:e|ez|er)\b[^\n]{0,40}?[\"'«]([A-Z0-9ÉÈÊÀÂÎÏÔÛÇ\-]{2,30})[\"'»]", re.IGNORECASE),
    re.compile(r"\bcomment(?:e|ez)\b[^\n]{0,30}?\b([A-ZÉÈÊÀÂÎÏÔÛÇ]{3,30})\b"),
    re.compile(r"\bDM\b[^\n]{0,30}?[\"'«]([A-Z0-9\-]{2,30})[\"'»]"),
    re.compile(r"\b(?:tape|tapez|écris|écrivez)\b[^\n]{0,30}?[\"'«]([A-Z0-9\-]{2,30})[\"'»]", re.IGNORECASE),
]

VISUAL_SIGNATURES = ["↳", "→", "➜", "➡", "▸", "▶", "►", "•", "·", "✓", "✅", "❌", "✕", "⚡", "🔥", "💡", "👉"]


def detect_cta(text: str) -> str | None:
    """Return the CTA keyword if a comment-bait pattern is present."""
    if not text:
        return None
    for pattern in CTA_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1).strip().upper()
    if re.search(r"\bcomment(?:e|ez)\b.{0,40}\bpour\b.{0,40}\b(recevoir|obtenir|avoir)\b", text, re.IGNORECASE):
        return "GENERIC_CTA"
    return None


def detect_hook_type(text: str) -> str:
    """Classify the first 1-2 lines into a hook archetype."""
    if not text.strip():
        return "other"
    first_block = text.strip().split("\n\n")[0]
    first = first_block.split("\n")[0].strip()
    fl = first.lower()

    if re.search(r"\b\d{1,3}\s?%", first) or re.search(r"\b\d+\s*(x|fois)\b", fl):
        return "stat"
    if re.match(r"^\s*\d+\s+(façons|raisons|étapes|erreurs|conseils|astuces|leçons)\b", fl):
        return "list"
    if first.endswith("?"):
        return "question"
    contrarian_markers = ["c'est faux", "tout le monde se trompe", "personne ne", "arrête de", "stop ", "oublie", "le mythe"]
    if any(m in fl for m in contrarian_markers):
        return "contrarian"
    result_markers = ["j'ai fait", "j'ai généré", "j'ai gagné", "en ", "résultat", "+", "passé de", "atteint"]
    if any(m in fl for m in result_markers) and re.search(r"\d", first):
        return "result"
    bold_markers = ["jamais", "toujours", "personne", "tout le monde", "le secret", "la vérité"]
    if any(m in fl for m in bold_markers):
        return "bold_claim"
    if len(first) < 60 and not first.endswith("?"):
        return "story"
    return "other"


def detect_visual_signature(posts: list[dict]) -> list[tuple[str, int]]:
    """Identify recurring visual symbols across posts."""
    counter: Counter[str] = Counter()
    for p in posts:
        text = p.get("text", "")
        seen_in_post: set[str] = set()
        for sym in VISUAL_SIGNATURES:
            if sym in text and sym not in seen_in_post:
                counter[sym] += 1
                seen_in_post.add(sym)
    threshold = max(2, len(posts) // 5)
    return [(s, n) for s, n in counter.most_common() if n >= threshold]


def detect_recurring_sections(posts: list[dict]) -> list[tuple[str, int]]:
    """Find short recurring section headers (e.g. 'Le piège', 'Pro tip')."""
    candidates: Counter[str] = Counter()
    line_re = re.compile(r"^\s*([A-Za-zÀ-ÿ][\wÀ-ÿ' \-]{2,30})\s*:\s*$")
    bold_re = re.compile(r"\*\*([^*]{2,30})\*\*")

    for p in posts:
        text = p.get("text", "")
        for line in text.splitlines():
            m = line_re.match(line)
            if m:
                candidates[m.group(1).strip().lower()] += 1
            for bm in bold_re.findall(line):
                if 3 <= len(bm) <= 30:
                    candidates[bm.strip().lower()] += 1

    threshold = max(3, len(posts) // 6)
    return [(s, n) for s, n in candidates.most_common(15) if n >= threshold]


def length_bucket(words: int) -> str:
    if words < 80:
        return "court"
    if words < 250:
        return "moyen"
    return "long"


def analyze_patterns(posts: list[dict]) -> dict[str, Any]:
    """Run all deterministic pattern detectors."""
    enriched = []
    for p in posts:
        text = p.get("text", "") or ""
        cta = detect_cta(text)
        enriched.append(
            {
                **p,
                "cta_keyword": cta,
                "has_cta": cta is not None,
                "hook_type": detect_hook_type(text),
                "length_bucket": length_bucket(p.get("length_words", 0)),
            }
        )

    hook_counts = Counter(p["hook_type"] for p in enriched)
    length_counts = Counter(p["length_bucket"] for p in enriched)
    cta_count = sum(1 for p in enriched if p["has_cta"])

    return {
        "posts_enriched": enriched,
        "hook_distribution": dict(hook_counts),
        "length_distribution": dict(length_counts),
        "cta_count": cta_count,
        "cta_share_pct": round((cta_count / len(enriched)) * 100, 1) if enriched else 0,
        "cta_keywords": Counter(
            p["cta_keyword"] for p in enriched if p["cta_keyword"] and p["cta_keyword"] != "GENERIC_CTA"
        ).most_common(10),
        "visual_signatures": detect_visual_signature(enriched),
        "recurring_sections": detect_recurring_sections(enriched),
    }
