"""Import d'un lien de recherche LinkedIn comme source de prospection.

Le client colle l'URL d'une recherche LinkedIn (recherche classique, Sales
Navigator, recherche sauvegardée ou liste de leads) et récupère la liste des
profils en leads, dans la même file que les commentateurs d'un post concurrent
(`lead_sources` / `leads`, cf. `src/lead_finder.py`).

Pourquoi Unipile et pas Apify : Unipile accepte l'URL de recherche **telle
quelle** et la parse côté serveur, alors qu'un actor Apify ne prend que des
filtres structurés — or une URL LinkedIn porte des identifiants opaques
(`geoUrn`, facettes Sales Navigator, id de liste) qu'on ne saurait pas
retraduire de façon fiable. S'ajoute que la recherche passe par le compte
LinkedIn déjà connecté du client : pagination réelle et **coût marginal nul**
(le forfait Unipile est par compte connecté, pas à l'usage) — d'où l'absence de
débit de crédits sur ce chemin, contrairement à la collecte de commentateurs.

⚠️ Ce que LinkedIn rend n'est pas ce qu'il affiche : au-delà de 1000 profils par
recherche (2500 en Sales Navigator), il ne renvoie plus rien, quel que soit le
total annoncé. Paginer davantage ne sert à rien — il faut affiner la recherche.
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any

from src import unipile


class LeadSearchError(ValueError):
    """Lien de recherche inexploitable (message destiné au client)."""


# Volumes (curseur côté client) : un import ramène par défaut 100 profils, avec
# 1000 comme plafond dur (celui de LinkedIn lui-même). Unipile recommande de ne
# pas dépasser ~1000 profils récupérés par jour et par compte pour ne pas se
# faire repérer comme automatisation.
DEFAULT_MAX_RESULTS = 100
MIN_MAX_RESULTS = 25
MAX_RESULTS_CAP = unipile.SEARCH_HARD_CAP

# Garde-fou anti-boucle : même si LinkedIn continuait à rendre un curseur, on
# arrête après ce nombre de pages (une page ≈ 10 profils côté classique).
_MAX_PAGES = 120

_PEOPLE_SEARCH_PATHS = (
    "/search/results/people",   # recherche classique, onglet Personnes
    "/sales/search/people",     # Sales Navigator
    "/sales/lists/people",      # liste de leads Sales Navigator
    "/sales/saved-searches",    # recherche sauvegardée Sales Navigator
    "/talent/search",           # Recruiter
    "/talent/hire",             # Recruiter (projet)
)

# Onglets de recherche qui ne rendent PAS des personnes : les refuser avec un
# message clair vaut mieux qu'un import qui revient vide sans explication.
_NON_PEOPLE_PATHS = {
    "/search/results/companies": "entreprises",
    "/search/results/content": "posts",
    "/search/results/groups": "groupes",
    "/search/results/schools": "écoles",
    "/search/results/jobs": "offres d'emploi",
    "/sales/search/company": "entreprises",
}

_PROFILE_SLUG_RE = re.compile(r"/(?:in|pub)/([^/?#]+)", re.IGNORECASE)

# Onglet « Tous » de la recherche LinkedIn. C'est l'URL qu'on obtient en tapant
# dans la barre de recherche sans cliquer sur un onglet — donc le cas le PLUS
# courant. Elle mélange personnes, entreprises et posts : on la bascule
# automatiquement sur l'onglet « Personnes » en gardant les critères, ce que le
# client ferait à la main de toute façon. La refuser serait techniquement
# défendable et pratiquement absurde.
_ALL_TAB_PATH = "/search/results/all"
_PEOPLE_TAB_PATH = "/search/results/people"

# Paramètres de traçage LinkedIn (d'où vient le clic), sans effet sur les
# résultats. On les retire : ils feraient diverger la clé d'unicité
# (user_id, post_url) entre deux copies de la MÊME recherche selon l'endroit
# d'où elle a été copiée — donc deux sources et des leads dupliqués.
_TRACKING_PARAMS = {
    "origin", "position", "sid", "trk", "trackingid", "lipi", "licu",
    "midtoken", "midsig", "refid", "searchid",
}


def _clean_query(query: str) -> str:
    """Retire les paramètres de traçage, garde tous les critères de recherche."""
    kept = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    return urllib.parse.urlencode(kept)


def validate_search_url(raw: str | None) -> str:
    """Valide/nettoie une URL de recherche LinkedIn. Lève `LeadSearchError` sinon.

    On retire le fragment mais on GARDE la query : c'est elle qui porte tous les
    critères de la recherche (`keywords`, `geoUrn`, facettes…). La perdre
    donnerait une recherche vide, sans la moindre erreur visible.
    """
    url = (raw or "").strip()
    if not url:
        raise LeadSearchError("Colle le lien d'une recherche LinkedIn.")
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    host = (parsed.netloc or "").lower().split(":")[0]
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        raise LeadSearchError("Ce lien n'est pas une URL LinkedIn.")
    path = (parsed.path or "").rstrip("/").lower()

    # Onglet « Tous » → onglet « Personnes », critères conservés.
    if path.startswith(_ALL_TAB_PATH):
        path = _PEOPLE_TAB_PATH + path[len(_ALL_TAB_PATH):]
        parsed = parsed._replace(path=path)

    for prefix, label in _NON_PEOPLE_PATHS.items():
        if path.startswith(prefix):
            raise LeadSearchError(
                f"Ce lien pointe vers une recherche de {label}. "
                "Bascule sur l'onglet « Personnes » dans LinkedIn, puis recopie le lien."
            )
    if _PROFILE_SLUG_RE.search(path):
        raise LeadSearchError(
            "Ce lien est un profil, pas une recherche. Ouvre une recherche LinkedIn "
            "(onglet « Personnes ») et copie le lien de la page de résultats."
        )
    if not any(path.startswith(p) for p in _PEOPLE_SEARCH_PATHS):
        raise LeadSearchError(
            "Lien de recherche non reconnu. Lance ta recherche sur LinkedIn, clique "
            "l'onglet « Personnes », puis copie le lien de la page de résultats "
            "(il commence par linkedin.com/search/results/people/). Les recherches "
            "et listes de leads Sales Navigator marchent aussi."
        )
    # Fragment retiré (jamais transmis au serveur, mais il pollue la clé d'unicité
    # (user_id, post_url) : deux fois la même recherche donnerait deux sources).
    return urllib.parse.urlunparse(
        parsed._replace(
            scheme="https",
            netloc=host,
            path=path,
            query=_clean_query(parsed.query or ""),
            fragment="",
        )
    )


def canonical_profile_url(url: str | None) -> str | None:
    """URL de profil canonique `https://www.linkedin.com/in/{slug}`.

    Indispensable à la dédup : un lead peut arriver par deux chemins (commentaire
    d'un post concurrent ET recherche). Les leads sont dédoublonnés par
    `profile_url` en base — deux écritures de la même personne sous deux formes
    d'URL créeraient deux lignes, donc deux invitations à la même personne.
    """
    if not url:
        return None
    parsed = urllib.parse.urlparse(url if "//" in url else "https://" + url)
    match = _PROFILE_SLUG_RE.search(parsed.path or "")
    if not match:
        return None
    slug = urllib.parse.unquote(match.group(1)).strip().strip("/")
    if not slug:
        return None
    # Ré-encode le slug : les profils accentués/emoji existent (cf. changelog du
    # 2026-06-12) et une URL non encodée casserait les appels en aval.
    return "https://www.linkedin.com/in/" + urllib.parse.quote(slug, safe="")


def effective_max_results(requested: int | None) -> int:
    """Volume effectif d'un import, borné au plafond dur de LinkedIn."""
    try:
        n = int(requested or DEFAULT_MAX_RESULTS)
    except (TypeError, ValueError):
        n = DEFAULT_MAX_RESULTS
    return max(MIN_MAX_RESULTS, min(n, MAX_RESULTS_CAP))


def _lead_from_profile(profile: dict[str, Any]) -> dict[str, Any] | None:
    """Prospect normalisé → lead persistable (forme attendue par `db.save_leads`)."""
    url = canonical_profile_url(profile.get("profile_url"))
    if not url:
        return None
    return {
        "name": profile.get("name"),
        "headline": profile.get("headline"),
        "profile_url": url,
        "provider_id": profile.get("provider_id"),
        # Un lead issu d'une recherche n'a pas commenté : ces champs restent
        # vides plutôt que d'inventer un signal qui n'existe pas.
        "comment_text": None,
        "commented_at": None,
        "reaction_count": 0,
    }


def collect_search_profiles(
    account_id: str, search_url: str, max_results: int
) -> tuple[list[dict[str, Any]], int | None]:
    """Parcourt la recherche page par page jusqu'à `max_results` profils.

    Retourne (leads dédoublonnés, total annoncé par LinkedIn). S'arrête dès que
    LinkedIn ne rend plus de curseur, plus d'items, ou **plus rien de nouveau** —
    ce dernier cas couvre un curseur qui tournerait en rond (déjà vu sur les
    listes Sales Navigator) : sans lui, on bouclerait jusqu'au plafond de pages
    en rappelant LinkedIn pour rien, ce qui est exactement le comportement qui
    fait flaguer un compte.
    """
    limit = effective_max_results(max_results)
    leads: list[dict[str, Any]] = []
    seen: set[str] = set()
    cursor: str | None = None
    total: int | None = None

    for _page in range(_MAX_PAGES):
        page = unipile.search_page(account_id, url=search_url, cursor=cursor)
        if total is None:
            total = unipile.search_total_count(page)
        items = page.get("items") if isinstance(page, dict) else None
        if not isinstance(items, list) or not items:
            break

        fresh = 0
        for item in items:
            profile = unipile.normalize_search_profile(item)
            if not profile:
                continue
            lead = _lead_from_profile(profile)
            if not lead or lead["profile_url"] in seen:
                continue
            seen.add(lead["profile_url"])
            leads.append(lead)
            fresh += 1
            if len(leads) >= limit:
                return leads, total

        cursor = page.get("cursor") if isinstance(page, dict) else None
        if not cursor or fresh == 0:
            break

    return leads, total


def collect_and_persist_search(
    access_token: str, source: dict, max_results: int
) -> dict[str, Any]:
    """Récupère les profils d'une recherche, les persiste en leads et les note.

    Aucun débit de crédits : la recherche passe par le compte LinkedIn du client
    (forfait Unipile fixe), elle ne nous coûte rien à l'appel. Lève sur échec
    Unipile / compte non connecté.
    """
    from datetime import datetime, timezone

    from src import db
    from src.lead_finder import _score_leads_for_source

    account = db.get_linkedin_outreach_account(access_token) or {}
    account_id = account.get("unipile_account_id")
    if not account_id:
        raise RuntimeError(
            "Aucun compte LinkedIn connecté : connecte-le dans Mon profil pour importer une recherche."
        )

    profiles, total = collect_search_profiles(account_id, source["post_url"], max_results)
    counts = db.save_leads(access_token, source, profiles)
    _score_leads_for_source(access_token, source, counts)
    fields: dict[str, Any] = {
        "comments_count": len(profiles),
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
    if total is not None:
        fields["search_total"] = total
    db.update_lead_source(access_token, source["id"], fields)
    print(
        f"[leads] recherche {source['id']} ({source['post_url']}): "
        f"{len(profiles)} profil(s) récupéré(s) sur {total if total is not None else '?'} annoncé(s), "
        f"leads {counts}",
        flush=True,
    )
    public_counts = {k: v for k, v in (counts or {}).items() if k != "ids_by_url"}
    return {
        "comments_count": len(profiles),
        "profiles_count": len(profiles),
        "search_total": total,
        "leads": public_counts,
        "credits": None,
    }
