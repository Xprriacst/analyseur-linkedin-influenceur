"""Traitement asynchrone des séries d'analyses (job queue serveur).

Une série (`analysis_jobs`) regroupe plusieurs profils LinkedIn ; chaque profil
est une ligne (`analysis_job_items`). Le traitement se fait dans un thread de
fond qui met à jour le statut de chaque item dans Supabase au fur et à mesure —
l'état vit donc en base, pas en mémoire : le frontend peut rafraîchir, fermer
l'onglet ou se reconnecter, la progression est conservée.

Un verrou global sérialise les analyses (compteurs d'usage globaux + limites de
débit Apify) : les séries s'exécutent l'une après l'autre, profil par profil.
"""
from __future__ import annotations

import threading

from src import db
from src.pipeline import run_analysis

# Sérialise le calcul lui-même (usage global dans src.usage, rate limit Apify).
_compute_lock = threading.Lock()
_threads_lock = threading.Lock()
_threads: dict[str, threading.Thread] = {}


def _counts(items: list[dict]) -> tuple[int, int]:
    done = sum(1 for it in items if it.get("status") == "done")
    failed = sum(1 for it in items if it.get("status") in ("error", "cancelled"))
    return done, failed


def process_job(access_token: str, job_id: str) -> None:
    """Traite séquentiellement les items non terminés d'une série.

    Idempotent : les items déjà `done` sont sautés, ce qui permet de relancer
    (`resume`) une série interrompue sans recalculer ce qui a déjà réussi.
    """
    job = db.get_job(access_token, job_id)
    if not job:
        return

    items = job.get("items", [])
    limit = job.get("limit_posts") or 25
    no_cache = not job.get("use_cache", True)
    with_llm = job.get("run_llm", True)

    done, failed = _counts(items)
    if db.get_job_status(access_token, job_id) != "cancelled":
        db.update_job(access_token, job_id, status="running", completed=done, failed=failed)

    for item in items:
        if item.get("status") in ("done", "cancelled"):
            continue

        # Vérification d'annulation avant chaque profil (ne peut pas interrompre
        # un appel Apify en cours, mais stoppe proprement entre deux profils).
        if db.get_job_status(access_token, job_id) == "cancelled":
            db.update_job_item(access_token, item["id"], status="cancelled")
            item["status"] = "cancelled"
            continue

        db.update_job_item(access_token, item["id"], status="running", error=None)
        try:
            with _compute_lock:
                result = run_analysis(
                    item["url"], limit=limit, no_cache=no_cache, with_llm=with_llm
                )
            if db.get_job_status(access_token, job_id) == "cancelled":
                db.update_job_item(access_token, item["id"], status="cancelled")
                item["status"] = "cancelled"
                continue
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
            if db.get_job_status(access_token, job_id) == "cancelled":
                db.update_job_item(access_token, item["id"], status="cancelled")
                item["status"] = "cancelled"
            else:
                db.update_job_item(
                    access_token, item["id"], status="error", error=str(exc)[:500]
                )
                item["status"] = "error"

        done, failed = _counts(items)
        if db.get_job_status(access_token, job_id) != "cancelled":
            db.update_job(access_token, job_id, status="running", completed=done, failed=failed)

    done, failed = _counts(items)
    current_status = db.get_job_status(access_token, job_id)
    if current_status == "cancelled":
        db.update_job(access_token, job_id, status="cancelled", completed=done, failed=failed)
        return
    final = "error" if failed and not done else "done"
    db.update_job(access_token, job_id, status=final, completed=done, failed=failed)


def is_job_thread_active(job_id: str) -> bool:
    """Return whether this process already owns a live worker for the job."""
    with _threads_lock:
        thread = _threads.get(job_id)
        if not thread:
            return False
        if thread.is_alive():
            return True
        _threads.pop(job_id, None)
        return False


def _run_job_thread(access_token: str, job_id: str) -> None:
    try:
        process_job(access_token, job_id)
    finally:
        with _threads_lock:
            if _threads.get(job_id) is threading.current_thread():
                _threads.pop(job_id, None)


def start_job_thread(access_token: str, job_id: str) -> bool:
    """Lance le traitement d'une série dans un thread de fond (non bloquant)."""
    with _threads_lock:
        existing = _threads.get(job_id)
        if existing and existing.is_alive():
            return False
        if existing:
            _threads.pop(job_id, None)
        thread = threading.Thread(
            target=_run_job_thread, args=(access_token, job_id), daemon=True
        )
        _threads[job_id] = thread
    thread.start()
    return True
