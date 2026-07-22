"""Feature flags — ouvrir une nouveauté à quelques comptes avant tout le monde.

Le besoin : les nouvelles fonctionnalités doivent d'abord être testées en prod par
les comptes de l'agence (Alex, Tom), puis ouvertes aux autres une fois validées.
Avant ça, tout merge sur `main` était visible par tous les utilisateurs d'un coup.

## Où vit le flag, et pourquoi

Dans **`app_metadata`** de l'utilisateur Supabase, jamais dans `user_metadata`.

⚠️ Ce n'est PAS un détail de rangement : `user_metadata` est **modifiable par
l'utilisateur lui-même** depuis son navigateur (`supabase.auth.updateUser`). Un flag
qui y vivrait serait une passoire — n'importe qui s'octroierait les fonctionnalités
en bêta en une ligne de console. `app_metadata` n'est écrivable que par la clé
service-role. C'est le même emplacement que le rôle `ideas_only` déjà en place.

## Les deux sources d'un droit

    features_of(user) = DEFAULT_FEATURES        (sorties de bêta, pour tout le monde)
                      | app_metadata.features   (bêta, compte par compte)

Ouvrir une fonctionnalité à tous = déplacer son nom dans `DEFAULT_FEATURES`, une
ligne. Pas de migration, pas d'écriture sur chaque compte. Ajouter un testeur = une
requête SQL sur son `app_metadata`.

## Le gating front ne suffit jamais

Masquer un bouton ne protège rien : les endpoints restent appelables. Tout ce qui
coûte (crédits, appels Anthropic) ou qui agit au nom du client (envois LinkedIn)
doit être gardé **côté serveur** avec `require_feature`. Le front, lui, ne fait que
ne pas afficher ce qui n'est pas encore ouvert.
"""
from __future__ import annotations

from typing import Any, Iterable

# Catalogue des fonctionnalités qui peuvent être mises en bêta. Sert de garde-fou
# contre les fautes de frappe : un flag inconnu posé sur un compte n'ouvrirait rien
# et personne ne s'en apercevrait avant que le testeur se plaigne de ne rien voir.
KNOWN_FEATURES: frozenset[str] = frozenset({
    "autopilot",  # ALE-284 — autopilote de prospection (invitation + 1er message)
})

# Fonctionnalités SORTIES de bêta : ouvertes à tous les comptes, sans rien poser.
# C'est ici qu'on déplace un nom le jour où la nouveauté est validée — et c'est le
# seul geste nécessaire pour la généraliser.
DEFAULT_FEATURES: frozenset[str] = frozenset()


def _raw_features(user: dict[str, Any] | None) -> Iterable[str]:
    """Flags posés sur CE compte, lus depuis `app_metadata` (jamais `user_metadata`)."""
    meta = (user or {}).get("app_metadata") or {}
    if not isinstance(meta, dict):
        return ()
    raw = meta.get("features")
    if isinstance(raw, str):  # tolère une valeur posée à la main en SQL
        raw = [raw]
    if not isinstance(raw, (list, tuple, set)):
        return ()
    return [str(x).strip().lower() for x in raw if str(x).strip()]


def features_of(user: dict[str, Any] | None) -> set[str]:
    """Fonctionnalités auxquelles ce compte a droit (sorties de bêta + les siennes).

    Les noms inconnus du catalogue sont ignorés : mieux vaut qu'un flag mal orthographié
    n'ouvre rien de façon visible plutôt qu'il ouvre autre chose en silence."""
    granted = {f for f in _raw_features(user) if f in KNOWN_FEATURES}
    return set(DEFAULT_FEATURES) | granted


def has_feature(user: dict[str, Any] | None, name: str) -> bool:
    """Ce compte a-t-il accès à cette fonctionnalité ?

    Fail CLOSED : sans utilisateur (jeton illisible, lecture échouée), la réponse est
    non. Un doute sur l'identité ne doit jamais ouvrir une fonctionnalité en bêta."""
    if not user:
        return False
    return name in features_of(user)
