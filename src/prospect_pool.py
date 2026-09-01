"""Pool partagé de prospects — Mode Pilote : jusqu'à 3 propositions par jour.

Décision produit (Alex, 2026-09-01, ticket Notion « Agent prospects ») : chaque
jour, l'app propose ≤3 prospects au compte. Deux sources, selon l'état du compte :

- **SANS compte LinkedIn connecté (Unipile)** → pool PARTAGÉ : des prospects déjà
  identifiés par les AUTRES comptes (table `leads`), réduits à leurs seules
  données PUBLIQUES de profil. Le partage cross-comptes est explicite et voulu.
- **AVEC compte LinkedIn connecté** → recherches propres : la sélection reste
  celle des leads du compte (import de recherche `src/lead_search.py`,
  commentateurs), déjà notée par le scoring ICP. L'aiguillage vit dans
  `pilot_plan.build_pilot_today` — un compte connecté ne touche JAMAIS au pool
  (aucune réservation gaspillée).

⚠️ GARDE-FOU NON NÉGOCIABLE — frontière d'anonymisation : seules les données
publiques du profil transitent d'un compte à l'autre (nom, headline, URL
LinkedIn). JAMAIS le contexte privé du compte source : commentaire capté, score
ICP et sa justification, signaux, curation « ne pas contacter », conversations.
Deux remparts indépendants : la projection SQL explicite
(`db._POOL_PUBLIC_LEAD_COLS`) ne SELECT que ces colonnes, et `public_prospect()`
re-filtre par whitelist même si la projection régressait un jour. Un test
verrouille chacun des deux (`tests/test_prospect_pool.py`).

Proposition ≠ envoi : rien ne part d'ici. L'envoi reste le circuit existant
(file cadencée ALE-174), qui exige de toute façon un compte LinkedIn connecté —
et l'UI désactive « Inviter » sur un prospect du pool.

Même découpage décide/exécute que `outreach_autopilot` : tout ce qui choisit QUI
proposer est pur (testable sans base ni réseau) ; `ensure_daily_assignments`
n'orchestre que des appels `db.admin_*` (service-role, `user_id` explicite — la
table des attributions est cross-user par nature) et reste fail-safe : pool vide
ou erreur ⇒ liste vide, jamais une exception qui casse le plan du jour.
"""
from __future__ import annotations

import datetime
from typing import Any, Iterable

from src import db, lead_search

# Plafond quotidien de propositions (la promesse du Mode Pilote : « jusqu'à
# 3 contacts / jour »). Même valeur que `pilot_plan.PILOT_CONTACT_LIMIT` — les
# deux chemins de l'aiguillage doivent proposer le même volume.
POOL_DAILY_LIMIT = 3

# La whitelist. Tout champ absent d'ici n'existe pas pour le compte receveur.
PUBLIC_PROSPECT_FIELDS = ("profile_url", "name", "headline")

# Mots trop génériques pour porter un signal de ciblage (l'heuristique est
# gratuite et volontairement fruste : elle ordonne, elle ne note pas).
_STOPWORDS = frozenset({
    "les", "des", "une", "aux", "pour", "avec", "dans", "qui", "que", "quoi",
    "ton", "tes", "ses", "leur", "leurs", "chez", "sur", "par", "the", "and",
    "est", "sont", "plus", "tout", "tous", "toutes",
})


def canonical_url(url: str | None) -> str | None:
    """URL de profil canonique pour toute comparaison de personnes.

    Délègue à `lead_search.canonical_profile_url` (la même canonicalisation que
    la dédup des leads) : sans elle, `fr.linkedin.com/in/x?trk=…` et
    `www.linkedin.com/in/x/` passeraient pour deux personnes — et un prospect
    déjà en leads chez le receveur lui serait re-proposé.
    """
    canon = lead_search.canonical_profile_url(url)
    if canon:
        return canon
    return (url or "").strip() or None


def public_prospect(lead: dict[str, Any] | None) -> dict[str, Any] | None:
    """Réduit un lead à ses seules données publiques de profil — ou None.

    C'est le second rempart de la frontière d'anonymisation (le premier est la
    projection SQL) : même si un jour la lecture ramenait des colonnes privées,
    rien d'autre que la whitelist ne sort d'ici. None si l'essentiel manque
    (pas d'URL canonique ou pas de nom : un prospect anonyme n'aide personne).
    """
    if not isinstance(lead, dict):
        return None
    url = canonical_url(lead.get("profile_url"))
    name = str(lead.get("name") or "").strip()
    if not url or not name:
        return None
    return {
        "profile_url": url,
        "name": name,
        "headline": str(lead.get("headline") or "").strip(),
    }


def _tokens(text: Any) -> set[str]:
    words = str(text or "").lower().replace("/", " ").replace(",", " ").split()
    return {w.strip(".:;()'\"«»") for w in words if len(w.strip(".:;()'\"«»")) >= 3} - _STOPWORDS


def targeting_tokens(targeting: dict[str, Any] | None) -> set[str]:
    """Vocabulaire du ciblage ICP du compte RECEVEUR (jamais du compte source)."""
    if not targeting:
        return set()
    tokens: set[str] = set()
    tokens |= _tokens(targeting.get("ideal_client"))
    tokens |= _tokens(targeting.get("offer"))
    keywords = targeting.get("interest_keywords") or []
    if isinstance(keywords, str):
        keywords = keywords.split(",")
    for kw in keywords:
        tokens |= _tokens(kw)
    return tokens


def heuristic_score(prospect: dict[str, Any], targeting_vocab: set[str]) -> int:
    """Recouvrement de vocabulaire ciblage ↔ (nom + headline). Gratuit, fruste.

    Volontairement PAS le scoring ICP (`llm.score_leads`) : lui coûte un appel
    modèle par lot et note des leads que le client possède. Ici on ORDONNE des
    candidats d'un pool — un tri approximatif gratuit suffit, et un pool vide de
    signal (0 partout) garde simplement l'ordre d'arrivée (tri stable).
    """
    if not targeting_vocab:
        return 0
    return len(_tokens(prospect.get("headline")) & targeting_vocab) + len(
        _tokens(prospect.get("name")) & targeting_vocab
    )


def select_daily(
    candidates: Iterable[dict[str, Any]],
    *,
    receiver_id: str,
    targeting: dict[str, Any] | None = None,
    own_urls: set[str] | None = None,
    reserved_urls: set[str] | None = None,
    history_urls: set[str] | None = None,
    limit: int | None = POOL_DAILY_LIMIT,
) -> list[dict[str, Any]]:
    """Choisit les prospects proposables aujourd'hui, ordonnés par affinité ICP.

    Règles (toutes testées) :
    - données publiques uniquement (`public_prospect`) ;
    - jamais un lead du compte receveur lui-même (ceinture en plus du filtre SQL) ;
    - jamais un prospect déjà dans les leads du receveur (`own_urls`) ;
    - jamais un prospect déjà réservé par un AUTRE compte aujourd'hui
      (`reserved_urls`) ni déjà proposé au receveur un jour précédent
      (`history_urls`) ;
    - une même personne vue par deux comptes source = UN candidat ;
    - `limit=None` renvoie toute la liste ordonnée (l'orchestrateur sur-provisionne
      pour survivre aux courses de réservation), sinon coupe à `limit`.
    """
    own = {u for u in (own_urls or set()) if u}
    own = {canonical_url(u) or u for u in own}
    reserved = reserved_urls or set()
    history = history_urls or set()
    vocab = targeting_tokens(targeting)

    seen: set[str] = set()
    eligible: list[dict[str, Any]] = []
    for lead in candidates or []:
        if not isinstance(lead, dict):
            continue
        if lead.get("user_id") and str(lead.get("user_id")) == str(receiver_id):
            continue  # ceinture : un lead du receveur n'est pas « un autre compte »
        prospect = public_prospect(lead)
        if prospect is None:
            continue
        url = prospect["profile_url"]
        if url in seen or url in own or url in reserved or url in history:
            continue
        seen.add(url)
        eligible.append(prospect)

    # Tri stable : à score égal, l'ordre d'arrivée (les plus récents d'abord,
    # tel que servi par la lecture) est conservé.
    eligible.sort(key=lambda p: -heuristic_score(p, vocab))
    if limit is None:
        return eligible
    return eligible[: max(0, int(limit))]


def assignment_row(
    user_id: str, day: str, position: int, prospect: dict[str, Any]
) -> dict[str, Any]:
    """Ligne d'attribution à insérer — ne porte QUE des champs publics.

    Fonction pure et testée : c'est elle qui garantit qu'aucune donnée privée du
    compte source n'atterrit dans la table des attributions (snapshot du jour).
    """
    return {
        "user_id": user_id,
        "day": day,
        "position": int(position),
        "profile_url": str(prospect.get("profile_url") or ""),
        "name": str(prospect.get("name") or "") or None,
        "headline": str(prospect.get("headline") or "") or None,
    }


def today_key(now: datetime.datetime | None = None) -> str:
    """Jour d'attribution, en UTC — le même pour toutes les instances du backend."""
    moment = now or datetime.datetime.now(datetime.timezone.utc)
    return moment.date().isoformat()


def ensure_daily_assignments(
    user_id: str | None,
    targeting: dict[str, Any] | None,
    own_lead_urls: Iterable[str] | None,
    *,
    day: str | None = None,
    limit: int = POOL_DAILY_LIMIT,
) -> list[dict[str, Any]]:
    """Les prospects du jour du compte : relus s'ils existent, sinon attribués.

    Sélection à la demande (à l'ouverture du Mode Pilote), mémorisée pour la
    journée par la table `pilot_pool_assignments` — pas de cron. La réservation
    « un prospect ne va qu'à UN compte par jour » est portée par l'index unique
    `(day, profile_url)` en base, pas par un select préalable : deux comptes qui
    ouvrent l'app au même instant ne peuvent pas se voir attribuer la même
    personne — l'insert du second échoue et on passe au candidat suivant.

    Fail-safe : service-role absent, pool vide ou n'importe quelle erreur ⇒ [].
    """
    if not user_id or not db.admin_enabled():
        return []
    day_key = day or today_key()
    try:
        existing = db.admin_pool_assignments_for_day(user_id, day_key)
        if existing:
            return existing
        candidates = db.admin_pool_candidate_leads(exclude_user_id=user_id)
        if not candidates:
            return []
        ranked = select_daily(
            candidates,
            receiver_id=user_id,
            targeting=targeting,
            own_urls={u for u in (own_lead_urls or []) if u},
            reserved_urls=db.admin_pool_reserved_urls(day_key),
            history_urls=db.admin_pool_user_history_urls(user_id),
            limit=None,  # sur-provision : les courses de réservation consomment des candidats
        )
        assigned: list[dict[str, Any]] = []
        for prospect in ranked:
            if len(assigned) >= max(0, int(limit)):
                break
            row = db.admin_create_pool_assignment(
                assignment_row(user_id, day_key, len(assigned), prospect)
            )
            if row is None:
                # Réservé par un autre compte entre la lecture et l'insert (ou
                # panne d'écriture) : on passe au suivant, jamais d'exception.
                continue
            assigned.append(row)
        return assigned
    except Exception as exc:  # noqa: BLE001 — le plan du jour ne casse jamais sur le pool
        print(f"[pilot.pool] sélection du jour échouée pour {user_id} : {exc}", flush=True)
        return []
