"""Surveillance de la fiabilité des acteurs Apify (+ repli automatique).

Item de backlog « Surveiller la fiabilité des acteurs Apify ». Deux incidents
réels ont motivé ce lot — point commun : les pannes d'acteur Apify sont
SILENCIEUSES et se découvrent par hasard, souvent des jours après.

  (1) 2026-06-12 — `harvestapi/linkedin-profile-scraper` s'est mis à exiger une
      approbation de permissions ("full access") côté Apify → chaque
      `fetch_profile` échouait, l'erreur était avalée (`except: return []`
      sans log exploitable) : les abonnés se sont affichés "indisponible"
      pendant des jours avant diagnostic. Le fix de l'époque a ajouté un
      acteur de repli (`apimaestro/linkedin-profile-detail`) directement dans
      `scraper.py::fetch_profile`, mais sans aucune trace de quand/pourquoi le
      repli se déclenche.
  (2) 2026-08-11 (#407) — un import de recherche LinkedIn a tourné sur le
      MAUVAIS acteur Apify (celui des commentaires plutôt que la recherche,
      via un bug de projection SQL). Le run Apify a réussi (200, ~1 s) avec un
      dataset VIDE : "job terminé, 0 profil", strictement aucune erreur
      visible dans l'app. La cause n'a été trouvée qu'en lisant les logs
      Render par hasard, plusieurs jours après.

Ce module ne prévient pas ces pannes (mauvais aiguillage ou acteur tiers
cassé, deux causes que ce module ne peut pas deviner) — il les rend VISIBLES
tout de suite, avec un préfixe grepable dans les logs Render
(`[apify.health]`, même patron que `[apify.linkedin-post-comments]` déjà
utilisé pour diagnostiquer #407) :
  - un échec franc (exception réseau, erreur API) est tracé "ÉCHEC" ;
  - un run qui "réussit" mais renvoie 0 item alors qu'on en attendait est
    tracé "ANOMALIE" — c'est exactement la signature de l'incident #407, un
    succès technique qui cache un problème.

`call_with_fallback` généralise le patron déjà existant pour le profil
(acteur primaire → acteur de repli sur échec/vide) plutôt que d'introduire un
système parallèle : il sert désormais aussi bien au profil qu'à tout futur
acteur qui voudrait un repli.

Best-effort et non bloquant par construction : toute erreur DANS ce module
(bug de formatage, buffer plein, etc.) est avalée — le tracking ne doit
JAMAIS faire échouer un appel Apify qui aurait autrement réussi, et ne débite
ni ne bloque rien lui-même.
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

LOG_PREFIX = "[apify.health]"

# Ring buffer des derniers évènements, en mémoire process uniquement — best
# effort, aucune persistance (le strict minimum utile pour ce lot est le
# logging grepable ci-dessous ; ce buffer est le "plus" qui alimente
# GET /health/apify, pas un remplacement des logs Render). Un redémarrage
# Render le remet à zéro : c'est voulu, il sert à voir "est-ce que ça casse
# EN CE MOMENT", pas à faire un historique.
_MAX_EVENTS = 200
_events: "deque[dict[str, Any]]" = deque(maxlen=_MAX_EVENTS)
_lock = threading.Lock()

T = TypeVar("T")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_call(
    actor: str,
    *,
    ok: bool,
    item_count: int | None = None,
    expected_min_items: int = 0,
    error: str | None = None,
    context: str = "",
) -> None:
    """Trace l'issue d'un appel à un acteur Apify. Best-effort : ne lève JAMAIS.

    `ok=False` : l'appel a levé (réseau, erreur API...) — tracé "ÉCHEC".
    `ok=True` avec `item_count == 0` et `expected_min_items > 0` : anomalie
    silencieuse au sens de l'incident #407 (run réussi, dataset vide alors
    qu'on en attendait) — tracée "ANOMALIE", sans jamais lever ni bloquer.
    Un succès normal ne produit AUCUNE ligne de log (le but est de repérer
    les pannes, pas de noyer les logs Render en régime nominal).
    """
    try:
        actor_name = str(actor or "?")
        ctx = str(context or "").strip()
        anomaly = bool(ok and item_count == 0 and expected_min_items > 0)
        event = {
            "at": _now_iso(),
            "actor": actor_name,
            "context": ctx,
            "ok": bool(ok),
            "item_count": item_count,
            "anomaly": anomaly,
            "error": (str(error) if error is not None else None),
        }
        with _lock:
            _events.append(event)

        if not ok:
            print(
                f"{LOG_PREFIX} ÉCHEC actor={actor_name} context={ctx or '-'} "
                f"erreur={event['error']}",
                flush=True,
            )
        elif anomaly:
            print(
                f"{LOG_PREFIX} ANOMALIE actor={actor_name} context={ctx or '-'} "
                f"0 item ramené alors qu'on en attendait au moins "
                f"{expected_min_items} — vérifier le bon acteur/la bonne "
                f"requête avant de suspecter une vraie absence de résultats "
                f"(cf. incident #407)",
                flush=True,
            )
    except Exception:  # noqa: BLE001 — le tracking ne doit jamais casser l'appelant
        pass


def recent_events(limit: int = 50) -> list[dict[str, Any]]:
    """Derniers évènements tracés (plus récent en dernier). Best-effort."""
    try:
        with _lock:
            items = list(_events)
        n = max(1, int(limit))
        return items[-n:]
    except Exception:  # noqa: BLE001
        return []


def summary() -> dict[str, Any]:
    """Résumé par acteur, calculé sur la fenêtre en mémoire (voir docstring
    module). Sert `GET /health/apify` — pas d'auth requise, aucune donnée
    utilisateur (noms d'acteurs, compteurs, messages d'erreur techniques)."""
    try:
        with _lock:
            events = list(_events)
    except Exception:  # noqa: BLE001
        events = []

    by_actor: dict[str, dict[str, Any]] = {}
    for e in events:
        actor_name = e.get("actor") or "?"
        row = by_actor.setdefault(
            actor_name,
            {
                "calls": 0,
                "failures": 0,
                "anomalies": 0,
                "last_error": None,
                "last_at": None,
            },
        )
        row["calls"] += 1
        if not e.get("ok"):
            row["failures"] += 1
            row["last_error"] = e.get("error")
        if e.get("anomaly"):
            row["anomalies"] += 1
        row["last_at"] = e.get("at")
    return {"actors": by_actor, "window": len(events)}


def _safe_record_call(*args: Any, **kwargs: Any) -> None:
    """Appelle `record_call` en s'en protégeant une seconde fois.

    `record_call` s'avale déjà toutes ses propres erreurs (voir sa docstring),
    mais `call_with_fallback` s'appuie dessus pour ne JAMAIS répercuter un
    souci du module de santé sur l'appel Apify réel — défense en profondeur
    plutôt que de faire confiance à un seul niveau de protection.
    """
    try:
        record_call(*args, **kwargs)
    except Exception:  # noqa: BLE001
        pass


def _try_call(
    call_fn: Callable[[str], list[T]], actor: str
) -> tuple[list[T], str | None]:
    """Appelle `call_fn(actor)` et normalise le résultat en (items, erreur).

    Une exception du côté de l'acteur tiers est capturée ICI (pas avalée plus
    haut) pour que `call_with_fallback` puisse la tracer fidèlement — mais
    elle n'est jamais re-levée : c'est l'appelant de `call_with_fallback` qui
    décide quoi faire d'une liste vide (retomber sur le repli, ou échouer
    proprement plus haut avec un message clair).
    """
    try:
        result = call_fn(actor)
        return (list(result) if result else []), None
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)


def call_with_fallback(
    actor: str,
    call_fn: Callable[[str], list[T]],
    *,
    fallback_actor: str | None = None,
    context: str = "",
    expected_min_items: int = 0,
) -> tuple[list[T], str]:
    """Appelle `call_fn(actor)` ; si ça lève ou renvoie une liste vide, et
    qu'un `fallback_actor` différent est fourni, retente avec ce dernier.

    Généralise le patron déjà en place pour le profil (`scraper.py`,
    harvestapi → apimaestro depuis l'incident du 2026-06-12) — à réutiliser
    pour tout futur acteur qui voudrait un repli, plutôt que de réinventer la
    même bascule ailleurs.

    Chaque tentative est tracée via `record_call`. Retourne
    `(items, acteur_effectivement_utilisé)` — `items` est `[]` si les deux
    tentatives échouent ou sont vides ; l'appelant décide alors de la suite
    (422 explicite au client plutôt qu'un résultat silencieusement vide).
    """
    used_actor = str(actor or "?")
    items, error = _try_call(call_fn, used_actor)
    _safe_record_call(
        used_actor,
        ok=(error is None),
        item_count=len(items),
        expected_min_items=expected_min_items,
        error=error,
        context=context,
    )

    if not items and fallback_actor and fallback_actor != used_actor:
        used_actor = fallback_actor
        items, error = _try_call(call_fn, used_actor)
        _safe_record_call(
            used_actor,
            ok=(error is None),
            item_count=len(items),
            expected_min_items=expected_min_items,
            error=error,
            context=f"{context} (repli)".strip(),
        )

    return items, used_actor
