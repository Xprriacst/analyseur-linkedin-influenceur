"""Vivier partagé de prospects — Mode Pilote, 1 profil réel par jour.

Décision produit (Alex, 2026-09-02, corrigée le soir même) : l'app propose
**un** prospect réel au compte Pilote, tant que LinkedIn n'est pas encore
connecté. Le stock `prospect_cache` (migration 0073) est alimenté par **tous
les prospects de tous les comptes** — cartes publiques seulement (nom, titre,
URL LinkedIn). L'import admin (CSV / xlsx / URLs) reste un appoint.

Jamais de commentaire, d'invitation ou de message : ces champs n'existent
pas sur la table, et la copie depuis `leads` ne les projette pas.

Même garantie que les suggestions « à suivre » (`src/follow_suggestions.py`) :

1. **Rien plutôt que n'importe quoi.** Sans mot-clé de niche (profil encore
   vide), on ne propose RIEN et on ne lit même pas le vivier.
2. **Matching textuel, zéro modèle, zéro Apify, zéro crédit.** Les mots-clés
   viennent du profil éditorial + du ciblage ICP ; on les cherche dans
   nom + headline. Correspondance par **début de mot** (`\\b`) : « vente »
   ne matche pas « inventaire », « coach » matche « coaching ».
3. **Copie dans `leads` du receveur.** L'outreach reste par compte : deux
   clients pharmacie peuvent voir la même personne, chacun invite depuis
   SON LinkedIn. Jamais de commentaire, d'invitation ou de message d'un
   autre compte — ces champs n'existent pas sur `prospect_cache`.
4. **1 par jour calendaire (UTC).** Une attribution déjà faite aujourd'hui
   n'en crée pas une deuxième, même si on rouvre l'écran vingt fois.
5. **Fail-safe.** Vivier vide, service-role absent, Supabase en panne ⇒
   liste vide, jamais une exception sur le plan du jour. Et **plus aucun
   nom inventé** (Camille Martin / Thomas Leroy / Sarah Benali) : le
   théâtre simulé ne se mélange pas à de vrais profils.

Le module est testable sans fastapi. L'orchestration (`maybe_assign_one`,
`ingest_rows`) appelle `db.admin_*` avec un `user_id` explicite.
"""
from __future__ import annotations

import datetime
import re
from typing import Any, Iterable

from src import db
from src.follow_suggestions import extract_niche_keywords
from src.lead_search import canonical_profile_url

# Score posé à la copie : vert (≥ 70), donc `pick_contacts` l'accepte.
# Sans ça le profil serait en base et invisible dans le Mode Pilote —
# panne silencieuse, exactement le piège du scoring ICP manquant.
POOL_ASSIGN_SCORE = 75

SIGNAL_ORIGIN = "prospect_pool"

# Combien de fiches du vivier on inspecte. Filtrage en mémoire ensuite.
# Doit couvrir le stock organique (prod ~1 300 URLs distinctes au 2026-09-02)
# sinon le matching ne verrait que les 500 plus récentes — souvent une seule
# niche — et un compte d'une autre niche resterait à « en recherche ».
_CANDIDATE_POOL = 2500

# Un harvest (copie des leads existants) par process Render : idempotent, et
# `save_leads` alimente ensuite le vivier à chaque nouvel import.
_harvest_attempted = False


def canonical_url(url: str | None) -> str | None:
    """URL de profil canonique — la même dédup que `save_leads`."""
    return canonical_profile_url(url)


def keyword_hits(haystack: str, keywords: Iterable[str]) -> list[str]:
    """Mots-clés présents dans le texte, ancrés en début de mot.

    « vente » ne matche pas « inventaire » ; « coach » matche « coaching ».
    L'ordre de `keywords` est conservé (c'est celui du profil du client).
    """
    text = (haystack or "").lower()
    hits: list[str] = []
    seen: set[str] = set()
    for raw in keywords:
        token = str(raw or "").strip().lower()
        if len(token) < 4 or token in seen:
            continue
        variants = [token]
        # « Coachs & consultants » extrait `coachs` / `consultants` — sans
        # ça `\bcoachs` rate « Coach en … » (le cas normal sur LinkedIn).
        if token.endswith("s") and len(token) >= 5:
            stem = token[:-1]
            if len(stem) >= 4:
                variants.append(stem)
        if any(re.search(r"\b" + re.escape(variant), text) for variant in variants):
            seen.add(token)
            hits.append(token)
    return hits


def niche_reason(matched: list[str]) -> str:
    shown = " · ".join(matched[:3])
    if not shown:
        return "correspond à ta niche"
    return f"correspond à ta niche : {shown}"


def pick_best(
    candidates: Iterable[dict[str, Any]],
    keywords: list[str],
    excluded_urls: set[str],
) -> dict[str, Any] | None:
    """Le meilleur match du vivier, ou None.

    Tri : nombre de mots-clés (décroissant), puis URL pour un ordre stable.
    Un profil sans aucun hit n'est jamais proposé — on ne comble pas avec
    un inconnu « pour remplir la case ».
    """
    if not keywords:
        return None
    excluded = {canonical_url(u) or u for u in excluded_urls if u}
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for row in candidates or []:
        if not isinstance(row, dict):
            continue
        url = canonical_url(row.get("profile_url"))
        if not url or url in excluded:
            continue
        haystack = " ".join(
            str(row.get(field) or "") for field in ("name", "headline")
        )
        hits = keyword_hits(haystack, keywords)
        if not hits:
            continue
        ranked.append((-len(hits), url, {
            "profile_url": url,
            "name": (row.get("name") or "").strip() or None,
            "headline": (row.get("headline") or "").strip() or None,
            "matched_keywords": hits,
        }))
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][2]


def is_pool_lead(lead: dict[str, Any] | None) -> bool:
    if not isinstance(lead, dict):
        return False
    for signal in lead.get("signals") or []:
        if isinstance(signal, dict) and signal.get("origin") == SIGNAL_ORIGIN:
            return True
    return False


def _created_date(lead: dict[str, Any]) -> datetime.date | None:
    raw = lead.get("created_at")
    if not raw:
        return None
    try:
        ts = datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=datetime.timezone.utc)
    return ts.astimezone(datetime.timezone.utc).date()


def assigned_from_pool_today(
    leads: Iterable[dict[str, Any]],
    now: datetime.datetime | None = None,
) -> bool:
    """True si un lead du vivier a déjà été copié aujourd'hui (UTC)."""
    moment = now or datetime.datetime.now(datetime.timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    today = moment.astimezone(datetime.timezone.utc).date()
    for lead in leads or []:
        if not is_pool_lead(lead):
            continue
        if _created_date(lead) == today:
            return True
    return False


def existing_profile_urls(leads: Iterable[dict[str, Any]]) -> set[str]:
    urls: set[str] = set()
    for lead in leads or []:
        if not isinstance(lead, dict):
            continue
        url = canonical_url(lead.get("profile_url"))
        if url:
            urls.add(url)
    return urls


def parse_profile_urls(text: str) -> dict[str, Any]:
    """URLs collées (une par ligne) → même forme que `parse_leads_file`.

    Les lignes sans URL de profil LinkedIn sont COMPTÉES (`ignored`), jamais
    avalées : coller 20 lignes et n'en importer que 3 sans le dire ferait
    croire que le vivier est rempli.
    """
    leads: list[dict[str, Any]] = []
    ignored = 0
    seen: set[str] = set()
    rows = 0
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        rows += 1
        url = canonical_url(line)
        if not url:
            ignored += 1
            continue
        if url in seen:
            continue
        seen.add(url)
        leads.append({"profile_url": url, "name": None, "headline": None})
    return {"leads": leads, "ignored": ignored, "rows": rows, "truncated": False}


def public_card(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """URL / nom / titre. Jamais un commentaire, un signal, un user_id."""
    if not isinstance(row, dict):
        return None
    url = canonical_url(row.get("profile_url"))
    if not url:
        return None
    name = str(row.get("name") or "").strip() or None
    headline = str(row.get("headline") or "").strip() or None
    return {
        "profile_url": url,
        "name": name[:300] if name else None,
        "headline": headline[:500] if headline else None,
    }


def ingest_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Écrit les cartes publiques dans `prospect_cache`. Dédup par URL.

    Deux lignes de la même personne (deux comptes) : on garde le nom/titre
    déjà remplis, on complète les blancs. On n'écrase pas une fiche nommée
    par une URL seule.
    """
    by_url: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        card = public_card(row)
        if not card:
            continue
        url = card["profile_url"]
        current = by_url.get(url)
        if current is None:
            by_url[url] = card
            continue
        if card["name"] and not current["name"]:
            current["name"] = card["name"]
        if card["headline"] and not current["headline"]:
            current["headline"] = card["headline"]
    payload = list(by_url.values())
    if not payload:
        return {"inserted": 0, "updated": 0, "skipped": 0}
    return db.upsert_prospect_cache(payload)


def contribute_from_leads(rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Copie les cartes publiques d'un lot de leads dans le vivier.

    Best-effort : un échec ici ne doit jamais faire échouer `save_leads`.
    """
    try:
        return ingest_rows(list(rows or []))
    except Exception as exc:  # noqa: BLE001
        print(f"[prospect_pool] contribution sautée : {exc}", flush=True)
        return {"inserted": 0, "updated": 0, "skipped": 0}


def harvest_existing_leads(
    *,
    force: bool = False,
    list_leads=None,
) -> dict[str, Any]:
    """Rattrapage : tous les leads déjà en base → vivier, une fois par process.

    Les imports *futurs* passent par `contribute_from_leads` depuis
    `save_leads`. Celui-ci ne sert qu'à ne pas attendre le prochain import
    pour remplir un vivier encore vide.
    """
    global _harvest_attempted
    if _harvest_attempted and not force:
        return {"inserted": 0, "updated": 0, "skipped": 0, "read": 0}
    _harvest_attempted = True
    try:
        reader = list_leads or db.list_all_lead_public_cards
        rows = reader()
        counts = ingest_rows(list(rows or []))
        counts["read"] = len(rows or [])
        return counts
    except Exception as exc:  # noqa: BLE001
        print(f"[prospect_pool] harvest sauté : {exc}", flush=True)
        return {"inserted": 0, "updated": 0, "skipped": 0, "read": 0}


def maybe_assign_one(
    user_id: str | None,
    profile: dict[str, Any] | None,
    targeting: dict[str, Any] | None,
    existing_leads: list[dict[str, Any]] | None,
    *,
    now: datetime.datetime | None = None,
    list_candidates=None,
    insert_lead=None,
) -> dict[str, Any] | None:
    """Copie AU PLUS un prospect du vivier dans les leads du compte.

    Retourne la ligne insérée, ou None. Ne lève jamais : un vivier en panne
    ne doit pas emporter le plan du jour.

    `list_candidates` / `insert_lead` sont injectables pour les tests ; en
    prod ce sont les fonctions `db.*`.
    """
    if not user_id:
        return None
    try:
        keywords = extract_niche_keywords(profile, targeting)
        if not keywords:
            # Rien plutôt que n'importe quoi : on ne lit même pas le vivier.
            return None
        leads = list(existing_leads or [])
        if assigned_from_pool_today(leads, now):
            return None
        excluded = existing_profile_urls(leads)
        reader = list_candidates or db.list_prospect_cache_candidates
        candidates = reader(limit=_CANDIDATE_POOL)
        # Vivier encore vide (aucun import depuis le dernier deploy) : on
        # rattrape les leads déjà en base, puis on relit. Injecter
        # `list_candidates` (tests) saute ce chemin — on ne touche pas à la DB.
        if list_candidates is None and not candidates:
            harvest_existing_leads()
            candidates = reader(limit=_CANDIDATE_POOL)
        picked = pick_best(candidates, keywords, excluded)
        if not picked:
            return None
        writer = insert_lead or db.admin_insert_pool_lead
        return writer(
            user_id,
            profile_url=picked["profile_url"],
            name=picked.get("name"),
            headline=picked.get("headline"),
            score=POOL_ASSIGN_SCORE,
            score_reason=niche_reason(picked.get("matched_keywords") or []),
            matched_keywords=list(picked.get("matched_keywords") or []),
        )
    except Exception as exc:  # noqa: BLE001 — le plan du jour ne casse jamais ici
        print(f"[prospect_pool] attribution sautée pour {user_id} : {exc}", flush=True)
        return None
