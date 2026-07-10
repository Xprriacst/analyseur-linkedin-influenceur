"""Traitement asynchrone des séries d'analyses (job queue serveur).

Une série (`analysis_jobs`) regroupe plusieurs profils LinkedIn ; chaque profil
est une ligne (`analysis_job_items`). Le traitement se fait dans un thread de
fond qui met à jour le statut de chaque item dans Supabase au fur et à mesure —
l'état vit donc en base, pas en mémoire : le frontend peut rafraîchir, fermer
l'onglet ou se reconnecter, la progression est conservée.

Un verrou global sérialise les analyses (compteurs d'usage globaux + limites de
débit Apify) : les séries s'exécutent l'une après l'autre, profil par profil.
Pendant l'attente du verrou, la série émet un heartbeat en base — sans lui,
`reconcile_stale_jobs` la solderait en erreur au bout de `JOB_STALE_MINUTES`
alors qu'elle fait simplement la queue.

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
from src.pipeline import run_analysis, run_analysis_instagram

# Sérialise le calcul lui-même (usage global dans src.usage, rate limit Apify).
_compute_lock = threading.Lock()

# Garde-fou : durée max d'analyse d'un profil. Au-delà, on abandonne l'item
# (statut `error`) et on libère le verrou global — sinon un appel Apify figé
# bloquerait toutes les séries de tous les utilisateurs.
ITEM_TIMEOUT_S = 600

# Tranche d'attente du verrou global entre deux heartbeats/vérifs d'annulation.
LOCK_WAIT_SLICE_S = 60


def _acquire_compute_lock(access_token: str, job_id: str, item_id: str) -> bool:
    """Attend le verrou global en gardant la série vivante côté base.

    Retourne False (sans avoir pris le verrou) si la série ou l'item a été
    annulé pendant l'attente.
    """
    while True:
        if _compute_lock.acquire(timeout=LOCK_WAIT_SLICE_S):
            return True
        if db.get_job_status(access_token, job_id) == "cancelled":
            return False
        if db.get_job_item_status(access_token, item_id) == "cancelled":
            return False
        db.update_job(access_token, job_id, status="running")  # heartbeat (updated_at)


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


def _run_analysis_guarded(url, limit, no_cache, with_llm, platform="linkedin"):
    """Exécute `run_analysis` (ou `run_analysis_instagram`) avec un timeout dur.

    On l'isole dans un thread jetable : si Apify se fige, `result(timeout=…)`
    lève `TimeoutError` et on rend la main (le thread fantôme est abandonné sans
    blocage via `shutdown(wait=False)`), ce qui libère le verrou global appelant.
    """
    fn = run_analysis_instagram if platform == "instagram" else run_analysis
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn, url, limit=limit, no_cache=no_cache, with_llm=with_llm)
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
    platform = job.get("platform") or "linkedin"

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
            if not _acquire_compute_lock(access_token, job_id, item["id"]):
                # Annulé pendant l'attente du verrou. Le remboursement est porté
                # par la transition `cancelled` elle-même (cf. db.cancel_job_item).
                db.cancel_job_item(access_token, item["id"])
                item["status"] = "cancelled"
                continue
            try:
                result = _run_analysis_guarded(item["url"], limit, no_cache, with_llm, platform=platform)
            finally:
                _compute_lock.release()
            # L'item a-t-il été annulé pendant le scraping ? Si oui, on respecte
            # l'annulation au lieu d'écrire `done` par-dessus.
            if db.get_job_item_status(access_token, item["id"]) == "cancelled":
                item["status"] = "cancelled"
            else:
                saved = db.save_analysis(access_token, result, posts_limit=limit)
                if not saved or not saved.get("analysis_id"):
                    # Session expirée ou écriture refusée : l'analyse est calculée
                    # mais aucun rapport n'existe → échec explicite (et remboursé),
                    # jamais un `done` silencieux sans rapport.
                    raise RuntimeError("Rapport non sauvegardé (session expirée ?).")
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
            # Transition gardée : rembourse le crédit si c'est bien cet appel qui
            # solde l'item ; sinon (déjà annulé/soldé par ailleurs) on reflète
            # le statut réel sans réécrire.
            if db.fail_job_item(access_token, item["id"], str(exc)[:500]):
                item["status"] = "error"
            else:
                item["status"] = db.get_job_item_status(access_token, item["id"]) or "error"

        # Compteurs : on ne réécrit jamais par-dessus une série annulée ou déjà
        # finalisée par ailleurs (réconciliation).
        if db.get_job_status(access_token, job_id) in ("queued", "running"):
            done, failed = _counts(items)
            db.update_job(access_token, job_id, status="running", completed=done, failed=failed)

    done, failed = _counts(items)
    current = db.get_job_status(access_token, job_id)
    # Une annulation explicite de la série prime sur le statut calculé.
    if current == "cancelled":
        db.update_job(access_token, job_id, completed=done, failed=failed)
        return
    if current not in ("queued", "running"):
        # Série déjà finalisée par ailleurs (réconciliation) — on ne réécrit pas.
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


# ---------------------------------------------------------------------------
# File d'attente de génération de posts (ALE-141)
# ---------------------------------------------------------------------------
# Rend la génération non bloquante : l'utilisateur lance puis quitte la page, le
# résultat (variants) apparaît plus tard. Le débit de crédits et les préconditions
# sont faits en amont (côté API, synchrones) ; ce thread ne fait que le calcul LLM.
#
# Pas de verrou global ici : contrairement aux analyses (rate limit Apify), les
# générations peuvent tourner en parallèle. Un timeout borne quand même la durée
# pour qu'un appel Anthropic figé ne laisse pas un job `running` éternellement.

GENERATION_TIMEOUT_S = 300


def _generate_posts_guarded(topic, top_posts, benchmark, user_context, role, count, reference_posts=None, template=None):
    """Exécute `generate_posts` avec un timeout dur (thread jetable abandonné si figé)."""
    from src.llm import generate_posts
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(
        generate_posts,
        topic,
        top_posts,
        benchmark,
        user_context=user_context,
        editorial_role=role,
        count=count,
        reference_posts=reference_posts,
        template=template,
    )
    try:
        return fut.result(timeout=GENERATION_TIMEOUT_S)
    finally:
        ex.shutdown(wait=False)


def process_generation_job(access_token: str, job_id: str) -> None:
    """Génère les posts d'un job en arrière-plan et persiste le résultat.

    Idempotent quant à l'annulation : si le job a été annulé (statut `cancelled`)
    avant ou pendant le calcul, on n'écrit jamais `done` par-dessus.
    """
    from src.benchmark import build_benchmark, enrich_influencers

    job = db.get_generation_job(access_token, job_id)
    if not job:
        return
    if db.get_generation_job_status(access_token, job_id) == "cancelled":
        return

    db.update_generation_job(access_token, job_id, status="running")
    try:
        influencers = enrich_influencers(db.get_user_corpus(access_token))
        top_posts, benchmark = build_benchmark(influencers)
        user_context = db.get_user_ai_context(access_token)
        role = (job.get("editorial_role") or "").strip() or None
        topic = (job.get("topic") or "").strip()
        count = int(job.get("count") or 1)

        template_id = job.get("template_id")
        variants = _generate_posts_guarded(
            topic, top_posts, benchmark, user_context, role, count,
            reference_posts=db.pick_reference_posts(access_token) or None,
            template=db.get_post_template(access_token, template_id) if template_id else None,
        )

        # Annulé pendant le calcul ? On respecte l'annulation.
        if db.get_generation_job_status(access_token, job_id) == "cancelled":
            return

        save_error: str | None = None
        try:
            variants = db.save_generated_posts(access_token, topic, variants)
        except Exception as exc:  # noqa: BLE001 — la sauvegarde est best-effort
            save_error = str(exc)

        db.update_generation_job(
            access_token, job_id, status="done",
            result={"variants": variants, "save_error": save_error},
        )
    except Exception as exc:  # noqa: BLE001 — on isole l'échec d'un job
        if db.get_generation_job_status(access_token, job_id) == "cancelled":
            return
        db.update_generation_job(
            access_token, job_id, status="error", error=str(exc)[:500]
        )


def start_generation_job_thread(access_token: str, job_id: str) -> None:
    """Lance la génération d'un job dans un thread de fond (non bloquant)."""
    thread = threading.Thread(
        target=process_generation_job, args=(access_token, job_id), daemon=True
    )
    thread.start()


# ---------------------------------------------------------------------------
# File d'attente de génération d'image IA (ALE-261)
# ---------------------------------------------------------------------------
# Même principe que la file de génération de posts : l'utilisateur ferme la
# pop-up ou change d'onglet, la génération continue en fond et le résultat
# rejoint le bon bloc de post (identifié par `target_key`) via le polling
# frontend. Pas de verrou global (les générations d'image peuvent tourner en
# parallèle) ; un timeout borne la durée pour qu'un appel OpenAI figé ne
# laisse pas un job `running` éternellement.

IMAGE_JOB_TIMEOUT_S = 300


def _generate_post_image_guarded(post_text, prompt, reference_image):
    """Exécute `generate_post_image` avec un timeout dur (thread jetable abandonné si figé)."""
    from src.image_gen import generate_post_image
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(generate_post_image, post_text, prompt=prompt, reference_image=reference_image)
    try:
        return fut.result(timeout=IMAGE_JOB_TIMEOUT_S)
    finally:
        ex.shutdown(wait=False)


def process_image_job(access_token: str, job_id: str) -> None:
    """Génère l'image d'un job en arrière-plan et débite les crédits au succès.

    Idempotent quant à l'annulation : si le job a été annulé (statut `cancelled`)
    avant ou pendant le calcul, on n'écrit jamais `done` par-dessus. Aucun
    remboursement à gérer : le débit n'a lieu qu'après une image réussie.
    """
    from src.image_gen import ImageGenError, fetch_reference_image

    job = db.get_image_job(access_token, job_id)
    if not job:
        return
    if db.get_image_job_status(access_token, job_id) == "cancelled":
        return

    db.update_image_job(access_token, job_id, status="running")
    try:
        reference_image = None
        template_id = job.get("reference_template_id")
        if template_id:
            template = db.get_post_template(access_token, template_id)
            image_url = (template or {}).get("image_url")
            if not image_url:
                raise ImageGenError("Image de référence introuvable.")
            reference_image = fetch_reference_image(image_url)

        result = _generate_post_image_guarded(job.get("post_text") or "", job.get("prompt"), reference_image)

        # Annulé pendant le calcul ? On respecte l'annulation (jamais de débit).
        if db.get_image_job_status(access_token, job_id) == "cancelled":
            return

        ok, balance = db.debit_credits(access_token, "generate_image")
        if not ok:
            print(f"[image-job] débit impossible après une génération réussie (solde {balance}) — image livrée sans débit.", flush=True)
        if isinstance(result, dict):
            result["credits"] = balance if ok else None

        db.update_image_job(access_token, job_id, status="done", result=result)
    except Exception as exc:  # noqa: BLE001 — on isole l'échec d'un job
        if db.get_image_job_status(access_token, job_id) == "cancelled":
            return
        db.update_image_job(
            access_token, job_id, status="error", error=str(exc)[:500]
        )


def start_image_job_thread(access_token: str, job_id: str) -> None:
    """Lance la génération d'image d'un job dans un thread de fond (non bloquant)."""
    thread = threading.Thread(
        target=process_image_job, args=(access_token, job_id), daemon=True
    )
    thread.start()
