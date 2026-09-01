"""Suggestions de profils LinkedIn à suivre — matching niche/ICP.

Ticket Notion « Onboarding — propositions automatiques de profils LinkedIn à
suivre ». Le problème résolu : l'écran Veille → Mes influenceurs est
**entièrement vide** pour un compte qui vient de s'inscrire (il ne liste que
les profils que le client a déjà fait analyser, ce qui coûte des crédits).
On propose donc des influenceurs **déjà analysés par d'autres comptes**
(cache mutualisé `influencer_cache`) dont la fiche publique correspond à la
niche du client.

Trois propriétés à conserver si ce fichier est retouché :

1. **Zéro appel IA, zéro Apify, zéro crédit.** Le matching est purement
   textuel : des mots-clés tirés du profil éditorial et du ciblage de
   prospection, cherchés dans le titre/nom des fiches déjà en base. Un
   scrape déclenché ici transformerait une aide à la découverte en coût.
2. **Best-effort assumé.** Ça ne sert qu'à *filtrer et classer une liste
   d'affichage* — jamais à ouvrir un droit, jamais à facturer. Un mot-clé
   raté dégrade la pertinence, jamais la correction.
3. **Rien plutôt que n'importe quoi.** Sans mot-clé de niche (profil encore
   vide juste après l'inscription), on ne suggère RIEN : la section
   disparaît. Proposer des profils au hasard à quelqu'un dont on ignore le
   métier abîme la confiance dans toutes les autres recommandations.

Le module ne fait que *proposer* : le suivi lui-même passe par le mécanisme
existant (`POST /me/followed-influencers`, plafond `FOLLOWED_INFLUENCERS_CAP`,
qui borne le coût Apify du cron de veille). Aucun second mécanisme de suivi
n'est introduit ici.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

from src import db

# Ce que l'écran affiche au maximum. Volontairement court : une liste longue
# de profils « peut-être » pertinents se parcourt moins qu'une poignée.
FOLLOW_SUGGESTIONS_LIMIT = 6

# Combien de fiches du cache mutualisé on inspecte (les plus récemment
# analysées). Le filtrage est en mémoire : inutile de ramener toute la table.
_CANDIDATE_POOL = 300

# Mots trop courants pour discriminer une niche. Best-effort : un mot manquant
# ici ne fait qu'ajouter du bruit dans le classement, il ne casse rien.
# (Les mots de moins de 4 lettres sont de toute façon écartés en amont.)
_NICHE_STOPWORDS = frozenset({
    "afin", "ainsi", "alors", "aussi", "autre", "autres", "avec", "avez",
    "avoir", "avons", "beaucoup", "bien", "ceci", "cela", "cette", "chez",
    "comme", "dans", "donc", "dont", "elle", "elles", "encore", "entre",
    "être", "faire", "leur", "leurs", "mais", "même", "nous", "notre", "nos",
    "peut", "peuvent", "plus", "pour", "quoi", "sans", "sera", "seront",
    "sont", "sous", "tout", "tous", "toute", "toutes", "très", "vers",
    "votre", "vous",
    # anglais courant (les fiches LinkedIn mélangent les deux langues)
    "about", "with", "your", "yours", "that", "this", "from", "have", "help",
    "helping", "here", "make", "more", "than", "them", "they", "will",
})

# Le texte est mis en minuscules avant extraction : pas besoin de A-Z.
_NICHE_WORD_RE = re.compile(r"[a-z0-9àâäçéèêëîïôöùûüÿñœæ]+")

# Champs qui décrivent la niche. Volontairement restreint : `tone`,
# `constraints` ou `topics_to_avoid` parlent de forme, pas de secteur — les
# inclure ferait matcher des profils sur « bienveillant » ou « jargon ».
_PROFILE_FIELDS = (
    "industry",
    "business_description",
    "target_audience",
    "core_offer",
    "topics_to_cover",
)
_TARGETING_FIELDS = ("ideal_client", "offer")


def handle_from_profile_url(url: str | None) -> str:
    """Handle LinkedIn décodé depuis une URL de profil, sans passer par Apify.

    Sert à ne pas se proposer soi-même : le client peut très bien avoir été
    analysé par quelqu'un d'autre et figurer dans le cache mutualisé.
    """
    if not url:
        return ""
    raw = url.strip().rstrip("/")
    raw = raw.split("/in/")[-1].split("/")[0].split("?")[0].split("#")[0]
    return unquote(raw).strip().lower()


def extract_niche_keywords(
    profile: dict[str, Any] | None,
    targeting: dict[str, Any] | None,
    max_keywords: int = 25,
) -> list[str]:
    """Mots-clés de niche tirés du profil éditorial + du ciblage prospection.

    Renvoie une liste vide dès que rien d'exploitable n'est renseigné — c'est
    ce cas qui fait disparaître la section côté écran, par construction.
    """
    texts: list[str] = []
    if isinstance(profile, dict):
        for key in _PROFILE_FIELDS:
            value = profile.get(key)
            if isinstance(value, str) and value.strip():
                texts.append(value)
    if isinstance(targeting, dict):
        for key in _TARGETING_FIELDS:
            value = targeting.get(key)
            if isinstance(value, str) and value.strip():
                texts.append(value)
        raw_keywords = targeting.get("interest_keywords")
        if isinstance(raw_keywords, list):
            texts.extend(str(k) for k in raw_keywords if str(k or "").strip())
        elif isinstance(raw_keywords, str) and raw_keywords.strip():
            texts.append(raw_keywords)

    words: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for token in _NICHE_WORD_RE.findall(text.lower()):
            if len(token) < 4 or token in _NICHE_STOPWORDS or token in seen:
                continue
            seen.add(token)
            words.append(token)
            if len(words) >= max_keywords:
                return words
    return words


def _keyword_patterns(keywords: list[str]) -> list[tuple[str, re.Pattern[str]]]:
    """Un motif par mot-clé, ancré sur un DÉBUT de mot.

    ⚠️ Pas une simple recherche de sous-chaîne : « vente » ne doit pas matcher
    « inventaire », sinon des profils hors sujet remontent avec un score élevé
    et la liste perd toute crédibilité. L'ancrage n'est mis qu'au début, pas à
    la fin : « consultant » doit continuer de matcher « consultants » et
    « coach » « coaching » — le pluriel et les dérivés sont le cas NORMAL sur
    une fiche LinkedIn.
    """
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for kw in keywords:
        if not kw:
            continue
        try:
            patterns.append((kw, re.compile(r"\b" + re.escape(kw))))
        except re.error:  # pragma: no cover - re.escape rend ce cas improbable
            continue
    return patterns


def _matched_keywords(
    candidate: dict[str, Any],
    patterns: list[tuple[str, re.Pattern[str]]],
) -> list[str]:
    haystack = " ".join(
        str(candidate.get(field) or "") for field in ("headline", "name")
    ).lower()
    if not haystack.strip():
        return []
    return [kw for kw, pattern in patterns if pattern.search(haystack)]


def _profile_url(row: dict[str, Any], raw_handle: str) -> str:
    url = (row.get("profile_url") or "").strip()
    if url:
        return url
    return f"https://www.linkedin.com/in/{raw_handle}/"


def rank_suggestions(
    candidates: list[dict[str, Any]],
    keywords: list[str],
    excluded_handles: set[str],
    limit: int = FOLLOW_SUGGESTIONS_LIMIT,
) -> list[dict[str, Any]]:
    """Classe les fiches du cache mutualisé par correspondance avec la niche.

    Tri : nombre de mots-clés distincts touchés (décroissant), puis nombre
    d'abonnés (décroissant) pour départager. ⚠️ Les abonnés ne départagent
    QUE des scores égaux : un gros compte hors sujet ne doit jamais passer
    devant un petit compte de la niche, sinon on suggère les mêmes
    célébrités LinkedIn à tout le monde.
    """
    if limit <= 0 or not keywords:
        return []
    patterns = _keyword_patterns(keywords)
    if not patterns:
        return []
    # Normalisé ici plutôt que de faire confiance à l'appelant : une exclusion
    # ratée sur une différence de casse proposerait de suivre quelqu'un qu'on
    # suit déjà — visible pour le client, muet côté serveur.
    excluded = {h.strip().lower() for h in excluded_handles if h}

    scored: list[tuple[int, int, str, dict[str, Any]]] = []
    seen: set[str] = set()
    for row in candidates:
        raw_handle = (row.get("handle") or "").strip()
        handle = unquote(raw_handle).strip()
        if not handle or handle.lower() in excluded or handle.lower() in seen:
            continue
        matched = _matched_keywords(row, patterns)
        if not matched:
            continue
        seen.add(handle.lower())
        followers = row.get("follower_count")
        try:
            followers = int(followers or 0)
        except (TypeError, ValueError):
            followers = 0
        scored.append((
            len(matched),
            followers,
            handle,
            {
                "handle": handle,
                "name": (row.get("name") or "").strip() or handle,
                "headline": (row.get("headline") or "").strip(),
                "profile_url": _profile_url(row, raw_handle),
                "follower_count": followers,
                # Les 3 premiers suffisent : l'écran affiche « correspond à
                # ta niche : x · y · z », pas la liste complète.
                "matched_keywords": matched[:3],
            },
        ))

    # `handle` en 3e clé : à score ET abonnés égaux, l'ordre reste stable d'un
    # appel à l'autre (une liste qui se réordonne toute seule à chaque
    # rafraîchissement donne l'impression d'un bug).
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [row for _score, _followers, _handle, row in scored[:limit]]


def excluded_handles(
    library: list[dict[str, Any]],
    followed_handles: set[str],
    own_handle: str = "",
) -> set[str]:
    """Profils qu'il ne sert à rien de suggérer, en minuscules.

    - ceux que le client suit déjà (le bouton n'aurait rien à faire) ;
    - ceux qu'il a déjà fait analyser (ils sont déjà listés juste en dessous,
      avec leur propre bouton « Suivre ») ;
    - lui-même.
    """
    excluded = {h.strip().lower() for h in followed_handles if h and h.strip()}
    for row in library or []:
        handle = unquote((row.get("handle") or "").strip()).strip().lower()
        if handle:
            excluded.add(handle)
    if own_handle:
        excluded.add(own_handle.strip().lower())
    return excluded


def build_follow_suggestions(access_token: str) -> dict[str, Any]:
    """Suggestions pour l'utilisateur authentifié (lecture seule, fail-safe).

    Fail-safe volontaire, comme `pilot_plan.build_pilot_today` : une aide à la
    découverte ne doit jamais faire tomber l'écran qui la porte. En cas de
    pépin, la section se comporte exactement comme pour un profil vide — elle
    n'apparaît pas.
    """
    try:
        profile = db.get_editorial_profile(access_token)
        targeting = db.get_lead_targeting(access_token)
        keywords = extract_niche_keywords(profile, targeting)
        followed = db.list_followed_influencers(access_token)
        followed_handles = {
            unquote((f.get("handle") or "").strip())
            for f in followed
            if f.get("handle")
        }
        if not keywords:
            # Aucun mot-clé ⇒ `rank_suggestions` ne renverrait rien de toute
            # façon : on évite la requête service-role plutôt que de la payer
            # pour jeter le résultat.
            return {"suggestions": [], "followed_count": len(followed_handles)}

        library = db.list_influencer_library(access_token)
        own_handle = handle_from_profile_url((profile or {}).get("linkedin_url"))
        candidates = db.list_influencer_cache_candidates(limit=_CANDIDATE_POOL)
        suggestions = rank_suggestions(
            candidates,
            keywords,
            excluded_handles(library, followed_handles, own_handle),
        )
        return {"suggestions": suggestions, "followed_count": len(followed_handles)}
    except Exception as exc:  # noqa: BLE001
        print(f"[follow-suggestions] échec : {exc}", flush=True)
        return {"suggestions": [], "followed_count": 0}
