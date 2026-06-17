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

import datetime
import os
import time
import threading
from typing import Any

from src import db
from src.pipeline import run_analysis

# Sérialise le calcul lui-même (usage global dans src.usage, rate limit Apify).
_compute_lock = threading.Lock()

ACTIVE_JOB_STATUSES = {"queued", "running", "retrying"}
ACTIVE_ITEM_STATUSES = {"queued", "running", "retrying", "pending"}
COMPLETED_ITEM_STATUSES = {"completed", "done"}
FAILED_ITEM_STATUSES = {"failed", "error"}
TERMINAL_ITEM_STATUSES = COMPLETED_ITEM_STATUSES | FAILED_ITEM_STATUSES | {"cancelled"}

STALE_AFTER_SECONDS = int(os.environ.get("JOB_STALE_AFTER_SECONDS", "1200"))
MAX_ITEM_ATTEMPTS = int(os.environ.get("JOB_ITEM_MAX_ATTEMPTS", "2"))

STEP_LABELS = {
    "Scraping profile": "Scraping profil",
    "Fetching last": "Scraping posts",
    "Computing stats": "Calcul des statistiques",
    "Detecting patterns": "Détection des patterns",
    "Classifying TOFU/MOFU/BOFU": "Classification LLM",
    "Generating strategic synthesis": "Synthèse LLM",
    "Rendering report": "Génération du rapport",
    "Done": "Analyse terminée",
}


class JobCancelled(RuntimeError):
    """Raised internally when a user cancellation/stale watchdog supersedes work."""


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(ts: datetime.datetime | None = None) -> str:
    return (ts or _now()).isoformat()


def _counts(items: list[dict]) -> tuple[int, int]:
    done = sum(1 for it in items if it.get("status") in COMPLETED_ITEM_STATUSES)
    failed = sum(1 for it in items if it.get("status") in FAILED_ITEM_STATUSES)
    return done, failed


def _cancelled_count(items: list[dict]) -> int:
    return sum(1 for it in items if it.get("status") == "cancelled")


def _active_count(items: list[dict]) -> int:
    return sum(1 for it in items if it.get("status") in ACTIVE_ITEM_STATUSES)


def _step_label(message: str) -> str:
    for prefix, label in STEP_LABELS.items():
        if message.startswith(prefix):
            return label
    return message


def _parse_dt(value: Any) -> datetime.datetime | None:
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value if value.tzinfo else value.replace(tzinfo=datetime.timezone.utc)
    try:
        raw = str(value).replace("Z", "+00:00")
        parsed = datetime.datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None


def _is_stale(value: Any, now: datetime.datetime | None = None) -> bool:
    ts = _parse_dt(value)
    if not ts:
        return False
    return ((now or _now()) - ts).total_seconds() > STALE_AFTER_SECONDS


def _error_code(exc: Exception) -> str:
    msg = str(exc).lower()
    if isinstance(exc, JobCancelled):
        return "user_cancelled"
    if "aucun post exploitable" in msg or "profil privé" in msg:
        return "apify_no_posts"
    if "apify" in msg or "actor" in msg or "linkedin-profile" in msg or "dataset" in msg:
        return "apify_error"
    if "anthropic" in msg or "claude" in msg or "messages" in msg or "model" in msg:
        return "llm_error"
    if "supabase" in msg or "postgrest" in msg or "rls" in msg:
        return "supabase_error"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    return "unknown_error"


def _is_retryable(code: str) -> bool:
    return code not in {"apify_no_posts", "user_cancelled"}


def _find_item(job: dict, item_id: str) -> dict | None:
    return next((it for it in job.get("items", []) if it.get("id") == item_id), None)


def _item_was_superseded(access_token: str, job_id: str, item_id: str) -> bool:
    job = db.get_job(access_token, job_id)
    if not job:
        return True
    if job.get("status") == "cancelled" or job.get("cancel_requested_at"):
        return True
    current = _find_item(job, item_id)
    return not current or current.get("status") not in {"running", "retrying"}


def _progress(access_token: str, job_id: str, item_id: str, message: str) -> None:
    now = _iso()
    step = _step_label(message)
    db.update_job_item(
        access_token,
        item_id,
        current_step=step,
        last_heartbeat_at=now,
    )
    db.update_job(
        access_token,
        job_id,
        status="running",
        current_step=step,
        last_heartbeat_at=now,
    )


def _refresh_job_counts(access_token: str, job_id: str) -> dict | None:
    job = db.get_job(access_token, job_id)
    if not job:
        return None
    items = job.get("items", [])
    done, failed = _counts(items)
    active = _active_count(items)
    cancelled = _cancelled_count(items)
    if active:
        status = "running"
    elif done == (job.get("total") or len(items)):
        status = "completed"
    elif failed:
        status = "failed"
    elif cancelled:
        status = "cancelled"
    else:
        status = "completed"
    fields: dict[str, Any] = {"status": status, "completed": done, "failed": failed}
    if status == "completed":
        fields.update(current_step="Série terminée", error_code=None, error_message=None)
    elif status == "failed":
        fields.update(
            current_step="Série interrompue",
            error_code=job.get("error_code") or "item_failed",
            error_message=job.get("error_message") or "Un ou plusieurs profils ont échoué. Clique sur Reprendre pour relancer les profils non terminés.",
        )
    elif status == "cancelled":
        fields.update(current_step="Série annulée")
    db.update_job(access_token, job_id, **fields)
    return db.get_job(access_token, job_id)


def mark_stale_jobs(access_token: str) -> None:
    """Marque les jobs/items sans heartbeat récent comme échoués.

    Appelé au polling : cela évite qu'un redémarrage Render ou un appel externe
    bloqué laisse l'UI sur "en cours" indéfiniment.
    """
    now = _now()
    for job in db.list_jobs(access_token, limit=50):
        if job.get("status") not in ACTIVE_JOB_STATUSES:
            continue
        items = job.get("items", [])
        changed = False
        for item in items:
            if item.get("status") not in {"running", "retrying"}:
                continue
            heartbeat = item.get("last_heartbeat_at") or item.get("updated_at")
            if not _is_stale(heartbeat, now):
                continue
            msg = (
                f"Aucune activité depuis plus de {STALE_AFTER_SECONDS // 60} min "
                "sur cette étape. Cause probable : Apify, Claude ou Render a bloqué. "
                "Clique sur Relancer pour réessayer ce profil."
            )
            db.update_job_item(
                access_token,
                item["id"],
                status="failed",
                error=msg,
                error_code="timeout_stale",
                error_message=msg,
                current_step=item.get("current_step") or "Étape inconnue",
                last_heartbeat_at=_iso(now),
            )
            item["status"] = "failed"
            changed = True

        active_items = [it for it in items if it.get("status") in ACTIVE_ITEM_STATUSES]
        has_running_item = any(it.get("status") in {"running", "retrying"} for it in items)
        job_heartbeat = job.get("last_heartbeat_at") or job.get("updated_at")
        if active_items and not has_running_item and _is_stale(job_heartbeat, now):
            msg = (
                f"La série n'a pas démarré ou repris depuis plus de {STALE_AFTER_SECONDS // 60} min. "
                "Clique sur Reprendre pour relancer les profils non terminés."
            )
            for item in active_items:
                db.update_job_item(
                    access_token,
                    item["id"],
                    status="failed",
                    error=msg,
                    error_code="job_stalled",
                    error_message=msg,
                    current_step=item.get("current_step") or "En attente",
                    last_heartbeat_at=_iso(now),
                )
            changed = True
        if changed:
            _refresh_job_counts(access_token, job["id"])


def cancel_job(access_token: str, job_id: str) -> dict | None:
    job = db.get_job(access_token, job_id)
    if not job:
        return None
    now = _iso()
    msg = "Annulé par l'utilisateur. Clique sur Reprendre si tu veux relancer les profils non terminés."
    for item in job.get("items", []):
        if item.get("status") in TERMINAL_ITEM_STATUSES:
            continue
        db.update_job_item(
            access_token,
            item["id"],
            status="cancelled",
            error=msg,
            error_code="user_cancelled",
            error_message=msg,
            current_step="Annulé",
            cancel_requested_at=now,
            cancelled_at=now,
            last_heartbeat_at=now,
        )
    db.update_job(
        access_token,
        job_id,
        status="cancelled",
        current_step="Série annulée",
        error_code="user_cancelled",
        error_message=msg,
        cancel_requested_at=now,
        cancelled_at=now,
        last_heartbeat_at=now,
    )
    return _refresh_job_counts(access_token, job_id)


def cancel_item(access_token: str, job_id: str, item_id: str) -> dict | None:
    job = db.get_job(access_token, job_id)
    if not job or not _find_item(job, item_id):
        return None
    item = _find_item(job, item_id)
    if item and item.get("status") not in TERMINAL_ITEM_STATUSES:
        now = _iso()
        msg = "Annulé par l'utilisateur. Clique sur Relancer pour réessayer ce profil."
        db.update_job_item(
            access_token,
            item_id,
            status="cancelled",
            error=msg,
            error_code="user_cancelled",
            error_message=msg,
            current_step="Annulé",
            cancel_requested_at=now,
            cancelled_at=now,
            last_heartbeat_at=now,
        )
    return _refresh_job_counts(access_token, job_id)


def resume_job(access_token: str, job_id: str, item_id: str | None = None) -> dict | None:
    job = db.get_job(access_token, job_id)
    if not job:
        return None
    was_active = job.get("status") in ACTIVE_JOB_STATUSES
    if was_active and not item_id:
        return job
    now = _iso()
    reset_ids = [
        item["id"]
        for item in job.get("items", [])
        if (not item_id or item.get("id") == item_id)
        and item.get("status") not in COMPLETED_ITEM_STATUSES
    ]
    for reset_id in reset_ids:
        db.update_job_item(
            access_token,
            reset_id,
            status="queued",
            error=None,
            error_code=None,
            error_message=None,
            current_step="En attente de relance",
            cancel_requested_at=None,
            cancelled_at=None,
            last_heartbeat_at=now,
        )
    if reset_ids:
        db.update_job(
            access_token,
            job_id,
            status="running" if was_active else "queued",
            current_step="Relance demandée",
            error_code=None,
            error_message=None,
            cancel_requested_at=None,
            cancelled_at=None,
            last_heartbeat_at=now,
        )
        if not was_active:
            start_job_thread(access_token, job_id)
    return db.get_job(access_token, job_id)


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
    db.update_job(
        access_token,
        job_id,
        status="running",
        completed=done,
        failed=failed,
        current_step="Démarrage de la série",
        last_heartbeat_at=_iso(),
        error_code=None,
        error_message=None,
    )

    for item in items:
        job = db.get_job(access_token, job_id)
        if not job or job.get("cancel_requested_at") or job.get("status") == "cancelled":
            break
        current_item = _find_item(job, item["id"]) or item
        if current_item.get("status") in TERMINAL_ITEM_STATUSES:
            continue

        attempt = 1
        while attempt <= MAX_ITEM_ATTEMPTS:
            status = "running" if attempt == 1 else "retrying"
            current_step = "Démarrage de l'analyse" if attempt == 1 else f"Nouvelle tentative ({attempt}/{MAX_ITEM_ATTEMPTS})"
            db.update_job_item(
                access_token,
                item["id"],
                status=status,
                error=None,
                error_code=None,
                error_message=None,
                current_step=current_step,
                last_heartbeat_at=_iso(),
            )
            try:
                with _compute_lock:
                    result = run_analysis(
                        item["url"],
                        limit=limit,
                        no_cache=no_cache,
                        with_llm=with_llm,
                        progress=lambda _value, message: _progress(access_token, job_id, item["id"], message),
                    )
                if _item_was_superseded(access_token, job_id, item["id"]):
                    raise JobCancelled("Annulation ou watchdog détecté avant sauvegarde.")
                _progress(access_token, job_id, item["id"], "Sauvegarde Supabase")
                try:
                    saved = db.save_analysis(access_token, result, posts_limit=limit) or {}
                except Exception as exc:
                    raise RuntimeError(f"Sauvegarde Supabase échouée : {exc}") from exc
                if _item_was_superseded(access_token, job_id, item["id"]):
                    raise JobCancelled("Annulation détectée après sauvegarde.")
                profile = result.get("profile", {}) or {}
                db.update_job_item(
                    access_token,
                    item["id"],
                    status="completed",
                    handle=result.get("handle"),
                    name=profile.get("name"),
                    follower_count=int(profile.get("follower_count", 0) or 0),
                    posts_count=(result.get("stats") or {}).get("count"),
                    analysis_id=saved.get("analysis_id"),
                    influencer_id=saved.get("influencer_id"),
                    current_step="Analyse terminée",
                    last_heartbeat_at=_iso(),
                    error=None,
                    error_code=None,
                    error_message=None,
                )
                item["status"] = "completed"
                break
            except JobCancelled:
                item["status"] = "cancelled"
                break
            except Exception as exc:  # noqa: BLE001 — on isole l'échec d'un profil
                code = _error_code(exc)
                message = str(exc)[:500]
                if attempt < MAX_ITEM_ATTEMPTS and _is_retryable(code):
                    db.update_job_item(
                        access_token,
                        item["id"],
                        status="retrying",
                        error=message,
                        error_code=code,
                        error_message=message,
                        current_step=f"Erreur {code}, nouvelle tentative à venir",
                        last_heartbeat_at=_iso(),
                    )
                    time.sleep(3)
                    attempt += 1
                    continue
                db.update_job_item(
                    access_token,
                    item["id"],
                    status="failed",
                    error=message,
                    error_code=code,
                    error_message=message,
                    current_step="Analyse échouée",
                    last_heartbeat_at=_iso(),
                )
                item["status"] = "failed"
                break

        fresh = _refresh_job_counts(access_token, job_id)
        if fresh and (fresh.get("cancel_requested_at") or fresh.get("status") == "cancelled"):
            break

    _refresh_job_counts(access_token, job_id)


def start_job_thread(access_token: str, job_id: str) -> None:
    """Lance le traitement d'une série dans un thread de fond (non bloquant)."""
    thread = threading.Thread(
        target=process_job, args=(access_token, job_id), daemon=True
    )
    thread.start()
