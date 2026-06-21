"""Traitement asynchrone des séries d'analyses (job queue serveur).

Une série (`analysis_jobs`) regroupe plusieurs profils LinkedIn ; chaque profil
est une ligne (`analysis_job_items`). Le traitement se fait dans un thread de
fond qui met à jour le statut de chaque item dans Supabase au fur et à mesure —
l'état vit donc en base, pas en mémoire : le frontend peut rafraîchir, fermer
l'onglet ou se reconnecter, la progression est conservée.

Un verrou global sérialise les analyses (compteurs d'usage globaux + limites de
débit Apify) : les séries s'exécutent l'une après l'autre, profil par profil.

Annulation : elle se fait en base (statut `cancelled` posé par l'API, sur la
série entière ou un item précis). Le thread la respecte — il ne réécrit jamais
par-dessus un `cancelled`. Un appel Apify déjà lancé ne peut pas être interrompu,
mais un garde-fou (`ITEM_TIMEOUT_S`) borne sa durée pour qu'un profil figé ne
bloque pas le verrou global indéfiniment.
"""
from __future__ import annotations

import concurrent.futures
import threading

from src import db
from src.pipeline import run_analysis

# Sérialise le calcul lui-même (usage global dans src.usage, rate limit Apify).
_compute_lock = threading.Lock()

# Garde-fou : durée max d'analyse d'un profil. Au-delà, on abandonne l'item
# (statut `error`) et on libère le verrou global — sinon un appel Apify figé
# bloquerait toutes les séries de tous les utilisateurs.
ITEM_TIMEOUT_S = 600


def final_counts(items: list[dict]) -> tuple[int, int]:
    """(`done`, `failed`) d'une série — `failed` ne compte que les vrais échecs."""
    done = sum(1 for it in items if it.get("status") == "done")
    failed = sum(1 for it in items if it.get("status") == "error")
    return done, failed


# Alias interne historique.
_counts = final_counts


def final_status(items: list[dict]) -> str | None:
    """Statut final d'une série une fois tous ses items terminés (None sinon).

    Partiellement réussie (au moins un `done`) → `done`. Que des échecs → `error`.
    Que des annulations → `cancelled`.
    """
    if any(it.get("status") in ("pending", "running") for it in items):
        return None
    done, failed = _counts(items)
    if failed and not done:
        return "error"
    if done:
        return "done"
    return "cancelled"


def _run_analysis_guarded(url, limit, no_cache, with_llm):
    """Exécute `run_analysis` avec un timeout dur.

    On l'isole dans un thread jetable : si Apify se fige, `result(timeout=…)`
    lève `TimeoutError` et on rend la main (le thread fantôme est abandonné sans
    blocage via `shutdown(wait=False)`), ce qui libère le verrou global appelant.
    """
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(run_analysis, url, limit=limit, no_cache=no_cache, with_llm=with_llm)
    try:
        return fut.result(timeout=ITEM_TIMEOUT_S)
    finally:
        ex.shutdown(wait=False)


def process_job(access_token: str, job_id: str) -> None:
    """Traite séquentiellement les items non terminés d'une série.

    Idempotent : les items déjà `done` (ou `cancelled`) sont sautés, ce qui
    permet de relancer (`resume`) une série interrompue sans recalculer ce qui a
    déjà abouti.
    """
    job = db.get_job(access_token, job_id)
    if not job:
        return

    items = job.get("items", [])
    limit = job.get("limit_posts") or 25
    no_cache = not job.get("use_cache", True)
    with_llm = job.get("run_llm", True)

    # Série déjà annulée avant même le démarrage du thread → rien à faire.
    if db.get_job_status(access_token, job_id) == "cancelled":
        return

    done, failed = _counts(items)
    db.update_job(access_token, job_id, status="running", completed=done, failed=failed)

    for item in items:
        if item.get("status") in ("done", "cancelled"):
            continue

        # Annulation de la série entière (posée par l'API) → on stoppe proprement.
        if db.get_job_status(access_token, job_id) == "cancelled":
            db.cancel_job_item(access_token, item["id"])
            item["status"] = "cancelled"
            continue

        # Annulation de cet item précis pendant qu'il était en attente.
        if db.get_job_item_status(access_token, item["id"]) == "cancelled":
            item["status"] = "cancelled"
            continue

        db.update_job_item(access_token, item["id"], status="running", error=None)
        try:
            with _compute_lock:
                result = _run_analysis_guarded(item["url"], limit, no_cache, with_llm)
            # L'item a-t-il été annulé pendant le scraping ? Si oui, on respecte
            # l'annulation au lieu d'écrire `done` par-dessus.
            if db.get_job_item_status(access_token, item["id"]) == "cancelled":
                item["status"] = "cancelled"
            else:
                saved = db.save_analysis(access_token, result, posts_limit=limit) or {}
                profile = result.get("profile", {}) or {}
                db.update_job_item(
                    access_token,
                    item["id"],
                    status="done",
                    handle=result.get("handle"),
                    name=profile.get("name"),
                    follower_count=int(profile.get("follower_count", 0) or 0),
                    posts_count=(result.get("stats") or {}).get("count"),
                    analysis_id=saved.get("analysis_id"),
                    influencer_id=saved.get("influencer_id"),
                )
                item["status"] = "done"
        except Exception as exc:  # noqa: BLE001 — on isole l'échec d'un profil
            if db.get_job_item_status(access_token, item["id"]) == "cancelled":
                item["status"] = "cancelled"
            else:
                db.update_job_item(
                    access_token, item["id"], status="error", error=str(exc)[:500]
                )
                item["status"] = "error"

        # Compteurs : on ne réécrit jamais par-dessus un `cancelled` global.
        if db.get_job_status(access_token, job_id) != "cancelled":
            done, failed = _counts(items)
            db.update_job(access_token, job_id, status="running", completed=done, failed=failed)

    done, failed = _counts(items)
    # Une annulation explicite de la série prime sur le statut calculé.
    if db.get_job_status(access_token, job_id) == "cancelled":
        db.update_job(access_token, job_id, completed=done, failed=failed)
        return
    db.update_job(
        access_token, job_id, status=final_status(items) or "done",
        completed=done, failed=failed,
    )


def start_job_thread(access_token: str, job_id: str) -> None:
    """Lance le traitement d'une série dans un thread de fond (non bloquant)."""
    thread = threading.Thread(
        target=process_job, args=(access_token, job_id), daemon=True
    )
    thread.start()
