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
    db.update_job(access_token, job_id, status="running", completed=done, failed=failed)

    for item in items:
        if item.get("status") == "done":
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
            db.update_job_item(
                access_token, item["id"], status="error", error=str(exc)[:500]
            )
            item["status"] = "error"

        done, failed = _counts(items)
        db.update_job(access_token, job_id, status="running", completed=done, failed=failed)

    done, failed = _counts(items)
    final = "error" if failed and not done else "done"
    db.update_job(access_token, job_id, status=final, completed=done, failed=failed)


def start_job_thread(access_token: str, job_id: str) -> None:
    """Lance le traitement d'une série dans un thread de fond (non bloquant)."""
    thread = threading.Thread(
        target=process_job, args=(access_token, job_id), daemon=True
    )
    thread.start()
