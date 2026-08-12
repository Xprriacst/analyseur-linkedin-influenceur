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
    """Retire les paramètres de traçage, garde tous les critères de recherche.

    ⚠️ Encodage en `%20` (`quote_via=quote`), pas en `+` : c'est Unipile qui
    parse cette URL, et on lui rend la forme que LinkedIn produit lui-même
    plutôt qu'une variante équivalente en théorie. Moins on s'éloigne de l'URL
    copiée par le client, moins on dépend du parseur d'en face.
    """
    kept = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    return urllib.parse.urlencode(kept, quote_via=urllib.parse.quote)


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

    # `raw_path` garde la forme exacte de LinkedIn (slash final compris) — c'est
    # elle qu'on renverra à Unipile ; `path` n'en est que la version normalisée
    # pour les comparaisons.
    raw_path = parsed.path or ""
    path = raw_path.rstrip("/").lower()

    # Onglet « Tous » → onglet « Personnes », critères conservés.
    if path.startswith(_ALL_TAB_PATH):
        raw_path = _PEOPLE_TAB_PATH + raw_path[len(_ALL_TAB_PATH):]
        path = _PEOPLE_TAB_PATH + path[len(_ALL_TAB_PATH):]

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
            path=raw_path,
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


# --------------------------------------------------------------------------- #
# Traduction d'une URL de recherche en requête Unipile
# --------------------------------------------------------------------------- #
#
# ⚠️ `api` est OBLIGATOIRE côté Unipile, et le passage d'URL brute n'est
# documenté qu'avec des exemples Sales Navigator. Une URL de recherche CLASSIQUE
# envoyée seule dans `{"url": …}` ne lève aucune erreur : Unipile répond 200 en
# ~1 s avec `items: []` et `total_count: 0` — un import « terminé, 0 profil »
# indiscernable d'une recherche réellement vide. D'où la traduction explicite
# ci-dessous pour les recherches classiques.

_CLASSIC_NETWORK = {"F": 1, "S": 2, "O": 3}   # 1er / 2e / 3e+ niveau

# Facettes de la recherche classique qu'on sait transmettre à Unipile.
_MAPPED_CLASSIC_PARAMS = {"keywords", "geourn", "network"}

# Facettes connues qu'on ne sait PAS transmettre. On ne les ignore pas en
# silence : le client doit savoir que son filtre « France » n'est pas parti,
# sinon il reçoit des prospects du monde entier en croyant l'avoir restreint.
_CLASSIC_FILTER_LABELS = {
    "currentcompany": "entreprise actuelle",
    "pastcompany": "entreprise passée",
    "industry": "secteur",
    "industrycompanyvertical": "secteur",
    "titlefreetext": "intitulé de poste",
    "schoolfilter": "école",
    "schoolfreetext": "école",
    "servicecategory": "services proposés",
    "connectionof": "relations d'une personne",
    "followerof": "abonnés d'une page",
    "profilelanguage": "langue du profil",
    "firstname": "prénom",
    "lastname": "nom",
}


def _sales_or_recruiter_api(path: str) -> str | None:
    """`api` Unipile pour les chemins Sales Navigator / Recruiter, sinon None."""
    if path.startswith("/sales"):
        return "sales_navigator"
    if path.startswith("/talent"):
        return "recruiter"
    return None


def build_search_request(search_url: str) -> tuple[dict[str, Any], list[str]]:
    """Corps de requête Unipile pour une URL de recherche, + filtres non transmis.

    - Sales Navigator / Recruiter : on passe l'URL telle quelle (forme documentée),
      avec son `api`.
    - Recherche classique : on traduit l'URL en paramètres (`api`/`category`/
      `keywords`…), parce que l'URL brute y est ignorée sans erreur.
    """
    parsed = urllib.parse.urlparse(search_url)
    path = (parsed.path or "").rstrip("/").lower()

    api = _sales_or_recruiter_api(path)
    if api:
        return {"api": api, "url": search_url}, []

    params = urllib.parse.parse_qs(parsed.query or "")
    lowered = {k.lower(): v for k, v in params.items()}

    body: dict[str, Any] = {"api": "classic", "category": "people"}
    keywords = " ".join(v.strip() for v in lowered.get("keywords", []) if v.strip())
    if keywords:
        body["keywords"] = keywords

    # `geoUrn=["105015875"]` → identifiants de localisation LinkedIn.
    locations = _ids_from_urn_param(lowered.get("geourn"))
    if locations:
        body["location"] = locations

    # `network=["F","S"]` → distances réseau.
    distances = sorted(
        {
            _CLASSIC_NETWORK[code]
            for raw in lowered.get("network", [])
            for code in _split_bracketed(raw)
            if code in _CLASSIC_NETWORK
        }
    )
    if distances:
        body["network_distance"] = distances

    dropped = sorted(
        {
            label
            for key, label in _CLASSIC_FILTER_LABELS.items()
            if key in lowered and key not in _MAPPED_CLASSIC_PARAMS
        }
    )
    return body, dropped


def _split_bracketed(raw: str) -> list[str]:
    """Découpe une valeur LinkedIn du type `["F","S"]` (ou `F`) en éléments."""
    return [part.strip().strip('"').strip("'") for part in raw.strip("[]").split(",") if part.strip()]


def _ids_from_urn_param(values: list[str] | None) -> list[str]:
    """Identifiants numériques d'un paramètre `geoUrn`/`industry` LinkedIn."""
    out: list[str] = []
    for raw in values or []:
        for part in _split_bracketed(raw):
            cleaned = part.rsplit(":", 1)[-1]
            if cleaned.isdigit():
                out.append(cleaned)
    return out


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
) -> tuple[list[dict[str, Any]], int | None, list[str]]:
    """Parcourt la recherche page par page jusqu'à `max_results` profils.

    Retourne (leads dédoublonnés, total annoncé par LinkedIn). S'arrête dès que
    LinkedIn ne rend plus de curseur, plus d'items, ou **plus rien de nouveau** —
    ce dernier cas couvre un curseur qui tournerait en rond (déjà vu sur les
    listes Sales Navigator) : sans lui, on bouclerait jusqu'au plafond de pages
    en rappelant LinkedIn pour rien, ce qui est exactement le comportement qui
    fait flaguer un compte.
    """
    limit = effective_max_results(max_results)
    body, dropped = build_search_request(search_url)
    leads: list[dict[str, Any]] = []
    seen: set[str] = set()
    cursor: str | None = None
    total: int | None = None

    for page_index in range(_MAX_PAGES):
        page = unipile.search_page(account_id, body=body, cursor=cursor)
        if total is None:
            total = unipile.search_total_count(page)
        items = page.get("items") if isinstance(page, dict) else None
        if not isinstance(items, list) or not items:
            if page_index == 0:
                # Une recherche qui revient vide est indiscernable d'une requête
                # mal formée : on trace la FORME de la réponse (jamais son
                # contenu) pour pouvoir trancher sans redéployer.
                print(
                    f"[leads] recherche vide — requête {sorted(body)} → "
                    f"clés réponse {sorted(page) if isinstance(page, dict) else type(page).__name__}, "
                    f"paging {page.get('paging') if isinstance(page, dict) else None}",
                    flush=True,
                )
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
                return leads, total, dropped

        cursor = page.get("cursor") if isinstance(page, dict) else None
        if not cursor or fresh == 0:
            break

    return leads, total, dropped


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

    profiles, total, dropped = collect_search_profiles(account_id, source["post_url"], max_results)
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
        # Filtres de la recherche qu'on n'a pas su transmettre : le client doit
        # le savoir, sinon il croit avoir restreint sa liste alors qu'elle est
        # plus large que ce qu'il a paramétré sur LinkedIn.
        "dropped_filters": dropped,
        "leads": public_counts,
        "credits": None,
    }
