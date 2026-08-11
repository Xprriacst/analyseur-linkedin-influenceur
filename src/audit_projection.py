"""Projection des gains montrés après l'audit léger de la landing.

Ce module ne fait AUCUN appel réseau et ne dépend de rien : c'est de l'arithmétique
pure, testable sans base ni serveur. C'est volontaire — les chiffres affichés ici
sont une promesse commerciale montrée à un prospect, ils doivent être vérifiables
ligne à ligne plutôt que sortis d'un modèle.

Deux règles qui expliquent toute la forme du code :

1. **Aucun chiffre inventé, que des fourchettes.** L'audit léger interdit déjà au
   modèle d'inventer des vues ou des taux ; l'écran « ce que tu peux gagner » ne
   doit pas faire par le calcul ce qu'on interdit au modèle de faire en prose. On
   ne sort donc jamais une valeur unique, toujours un bas et un haut, et les
   hypothèses sont rendues avec (`assumptions`) pour être affichées au visiteur.

2. **Les volumes de prospection ne sont pas devinés** : ils viennent des plafonds
   réels du moteur d'envoi (`src/outreach_engine.py` — warm-up 8 → 15 → 20 actions
   par jour ouvré, sécurité hebdomadaire ~100 invitations). Annoncer un volume que
   l'app s'interdit d'atteindre serait se contredire soi-même dès le premier mois.

Le calcul vit côté serveur pour une raison précise : l'écran laisse le visiteur
choisir son panier moyen et voit les montants bouger. Refaire la formule en
TypeScript pour cet affichage la ferait diverger de celle utilisée pour l'e-mail
d'audit. Le serveur renvoie donc les projections de TOUS les paliers en une fois,
et le front se contente de basculer d'un palier à l'autre.
"""

from __future__ import annotations

from typing import Any

# --- Hypothèses de prospection -----------------------------------------------
# Bornes mensuelles d'invitations réellement atteignables par le moteur d'envoi :
# ~10/jour ouvré en régime prudent, ~20/jour une fois le warm-up terminé.
INVITES_PER_MONTH_LOW = 220
INVITES_PER_MONTH_HIGH = 400

# Taux d'acceptation d'une invitation sans note vers une cible qualifiée.
ACCEPT_RATE_LOW = 0.18
ACCEPT_RATE_HIGH = 0.28

# Part des relations acceptées qui répondent au premier message.
REPLY_RATE_LOW = 0.12
REPLY_RATE_HIGH = 0.18

# Part des conversations engagées qui deviennent un client.
CLOSING_RATE_LOW = 0.08
CLOSING_RATE_HIGH = 0.20

# --- Hypothèses de contenu ----------------------------------------------------
# Croissance d'abonnés sur 90 jours à raison de ~3 publications par semaine.
# Le plancher absolu existe parce qu'un pourcentage sur un compte de 80 abonnés ne
# veut rien dire : un petit compte gagne des abonnés par la portée des posts, pas
# proportionnellement à une base qu'il n'a pas encore.
FOLLOWER_GROWTH_LOW = 0.18
FOLLOWER_GROWTH_HIGH = 0.55
FOLLOWER_FLOOR_LOW = 120
FOLLOWER_FLOOR_HIGH = 450

# --- Paliers de panier moyen --------------------------------------------------
# `value` = milieu de fourchette utilisé pour le calcul ; le libellé affiche la
# fourchette réelle pour que le visiteur voie l'hypothèse, pas juste le résultat.
DEAL_BANDS: list[dict[str, Any]] = [
    {"key": "small", "label": "Moins de 1 000 €", "value": 600},
    {"key": "mid", "label": "1 000 à 5 000 €", "value": 3000},
    {"key": "high", "label": "5 000 à 20 000 €", "value": 12000},
    {"key": "enterprise", "label": "Plus de 20 000 €", "value": 30000},
]
DEFAULT_DEAL_BAND = "mid"

# Paliers du tunnel fondateurs SaaS (/founders). Ce ne sont PAS les mêmes paliers
# habillés autrement : un éditeur SaaS ne raisonne pas en prix de prestation mais
# en **ACV** — ce que rapporte un client sur douze mois. Un plan à 99 €/mois vaut
# donc ~1 200 € ici, là où la grille générique le rangerait dans « moins de
# 1 000 € » et sous-estimerait le compte d'un facteur 2.
#
# ⚠️ Le montant projeté avec ces paliers est donc de l'**ARR signé**, pas du
# chiffre encaissé le mois même. C'est écrit dans les hypothèses ET dans le
# libellé affiché — sans quoi l'écran promettrait douze fois trop.
SAAS_DEAL_BANDS: list[dict[str, Any]] = [
    {"key": "self_serve", "label": "Moins de 1 200 € / an", "value": 700},
    {"key": "smb", "label": "1 200 à 6 000 € / an", "value": 3600},
    {"key": "midmarket", "label": "6 000 à 25 000 € / an", "value": 15000},
    {"key": "enterprise", "label": "Plus de 25 000 € / an", "value": 40000},
]
DEFAULT_SAAS_DEAL_BAND = "smb"

# Un jeu de paliers par audience de tunnel. `default` = /start (prestataires,
# coachs, agences), `saas` = /founders.
AUDIENCES: dict[str, dict[str, Any]] = {
    "default": {
        "bands": DEAL_BANDS,
        "default_band": DEFAULT_DEAL_BAND,
        "deal_label": "Ton panier moyen",
        "revenue_label": "Chiffre d'affaires mensuel supplémentaire",
        "extra_assumption": None,
    },
    "saas": {
        "bands": SAAS_DEAL_BANDS,
        "default_band": DEFAULT_SAAS_DEAL_BAND,
        "deal_label": "Ton ACV moyen (ce que rapporte un client sur 12 mois)",
        "revenue_label": "Nouvel ARR signé par mois",
        "extra_assumption": (
            "Montants exprimés en ARR signé (valeur annuelle des contrats fermés "
            "dans le mois), pas en encaissement du mois."
        ),
    },
}


def audience_config(audience: str | None = None) -> dict[str, Any]:
    """Configuration de paliers d'une audience — repli silencieux sur `default`.

    Repli plutôt que 400 : une audience inconnue (faute de frappe dans une URL de
    campagne, vieille page en cache) doit dégrader vers l'écran générique, pas
    faire disparaître les chiffres du tunnel.
    """
    return AUDIENCES.get((audience or "").strip().lower() or "default", AUDIENCES["default"])


def _round_nice(value: float) -> int:
    """Arrondit à un palier lisible — un « 1 247 € » sonne faux sur une projection.

    Une projection est une estimation : l'afficher à l'euro près lui donnerait une
    précision qu'elle n'a pas, et c'est précisément ce qui fait perdre confiance.
    """
    if value <= 0:
        return 0
    if value < 10:
        return int(round(value))
    if value < 100:
        return int(round(value / 5) * 5)
    if value < 1000:
        return int(round(value / 10) * 10)
    if value < 10000:
        return int(round(value / 100) * 100)
    if value < 100000:
        return int(round(value / 500) * 500)
    return int(round(value / 1000) * 1000)


def _range(low: float, high: float, minimum: int = 0) -> dict[str, int]:
    """Fourchette normalisée : bas ≤ haut, arrondie, jamais sous `minimum`.

    Le garde-fou `minimum` sert aux petits volumes : une borne basse qui tombe à 0
    après arrondi (« 0 à 4 nouveaux clients ») annule tout l'écran alors que le
    calcul, lui, dit bien qu'il se passe quelque chose.
    """
    lo = max(_round_nice(low), minimum)
    hi = max(_round_nice(high), lo)
    return {"low": lo, "high": hi}


def project_gains(
    followers: int = 0,
    connections: int = 0,
    posts_count: int = 0,
    deal_value: float = 0,
) -> dict[str, Any]:
    """Projette les gains d'un compte pour UN panier moyen donné.

    `followers` / `connections` / `posts_count` viennent du scrape (jamais du
    modèle). Un compte inconnu (0 partout) reste projetable : les volumes de
    prospection ne dépendent pas de la taille de l'audience, seule la croissance
    d'abonnés en dépend.
    """
    followers = max(0, int(followers or 0))
    connections = max(0, int(connections or 0))
    posts_count = max(0, int(posts_count or 0))
    deal_value = max(0.0, float(deal_value or 0))

    # Prospection : invitations → relations acceptées → conversations → clients.
    relations = _range(
        INVITES_PER_MONTH_LOW * ACCEPT_RATE_LOW,
        INVITES_PER_MONTH_HIGH * ACCEPT_RATE_HIGH,
        minimum=1,
    )
    conversations = _range(
        INVITES_PER_MONTH_LOW * ACCEPT_RATE_LOW * REPLY_RATE_LOW,
        INVITES_PER_MONTH_HIGH * ACCEPT_RATE_HIGH * REPLY_RATE_HIGH,
        minimum=1,
    )
    clients = _range(
        INVITES_PER_MONTH_LOW * ACCEPT_RATE_LOW * REPLY_RATE_LOW * CLOSING_RATE_LOW,
        INVITES_PER_MONTH_HIGH * ACCEPT_RATE_HIGH * REPLY_RATE_HIGH * CLOSING_RATE_HIGH,
        minimum=1,
    )
    revenue = _range(clients["low"] * deal_value, clients["high"] * deal_value)

    # Contenu : abonnés projetés à 90 jours.
    gain_low = max(FOLLOWER_FLOOR_LOW, followers * FOLLOWER_GROWTH_LOW)
    gain_high = max(FOLLOWER_FLOOR_HIGH, followers * FOLLOWER_GROWTH_HIGH)
    followers_gain = _range(gain_low, gain_high, minimum=1)
    followers_after = {
        "low": followers + followers_gain["low"],
        "high": followers + followers_gain["high"],
    }

    return {
        "followers_now": followers,
        "connections_now": connections,
        "posts_count": posts_count,
        "followers_gain": followers_gain,
        "followers_after": followers_after,
        "relations_per_month": relations,
        "conversations_per_month": conversations,
        "clients_per_month": clients,
        "revenue_per_month": revenue,
        "deal_value": int(deal_value),
    }


def assumptions(deal_label: str | None = None, audience: str | None = None) -> list[str]:
    """Les hypothèses, telles qu'elles doivent être affichées sous les chiffres.

    Elles ne sont pas décoratives : sans elles, la projection devient une promesse
    chiffrée invérifiable. Elles sont rendues dans l'encart d'avertissement de
    l'écran, au même titre que le « pas assez de données » de l'audit léger.
    """
    lines = [
        "Publication régulière (~3 posts par semaine) et prospection active depuis l'app.",
        f"{INVITES_PER_MONTH_LOW} à {INVITES_PER_MONTH_HIGH} invitations par mois, "
        f"dans les plafonds de sécurité LinkedIn appliqués par l'app.",
        f"{int(ACCEPT_RATE_LOW * 100)} à {int(ACCEPT_RATE_HIGH * 100)} % d'acceptation, "
        f"{int(REPLY_RATE_LOW * 100)} à {int(REPLY_RATE_HIGH * 100)} % de réponses, "
        f"{int(CLOSING_RATE_LOW * 100)} à {int(CLOSING_RATE_HIGH * 100)} % de signatures.",
    ]
    extra = audience_config(audience).get("extra_assumption")
    if extra:
        lines.append(extra)
    if deal_label:
        lines.append(f"Panier moyen retenu : {deal_label}.")
    lines.append("Fourchettes indicatives observées sur des profils comparables — pas une garantie de résultat.")
    return lines


def project_all_bands(
    followers: int = 0,
    connections: int = 0,
    posts_count: int = 0,
    audience: str | None = None,
) -> dict[str, Any]:
    """Projections pour TOUS les paliers de panier, en un seul aller-retour.

    L'écran laisse le visiteur changer de palier et voir les montants bouger : tout
    précalculer évite à la fois un appel réseau par clic et une seconde
    implémentation de la formule côté navigateur (qui divergerait de celle utilisée
    pour l'e-mail d'audit à la première retouche).

    `audience` choisit la grille de paliers (`default` = prestation, `saas` = ACV).
    Les libellés partent avec la réponse pour la même raison que le calcul : un
    front qui écrirait « chiffre d'affaires » au-dessus de montants calculés en ARR
    mentirait sans qu'aucun test serveur ne s'en aperçoive.
    """
    config = audience_config(audience)
    bands = []
    for band in config["bands"]:
        bands.append({
            "key": band["key"],
            "label": band["label"],
            "deal_value": band["value"],
            "projection": project_gains(
                followers=followers,
                connections=connections,
                posts_count=posts_count,
                deal_value=band["value"],
            ),
            "assumptions": assumptions(band["label"], audience=audience),
        })
    return {
        "default_band": config["default_band"],
        "deal_label": config["deal_label"],
        "revenue_label": config["revenue_label"],
        "bands": bands,
    }
