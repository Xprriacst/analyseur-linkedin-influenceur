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


def _generate_posts_guarded(topic, top_posts, benchmark, user_context, role, count, reference_posts=None, template=None, recent_posts=None):
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
        recent_posts=recent_posts,
    )
    try:
        return fut.result(timeout=GENERATION_TIMEOUT_S)
    finally:
        ex.shutdown(wait=False)


def _generate_reel_packs_guarded(topic, top_posts, benchmark, user_context, role, trame_id, count, inspiration=None, recent_posts=None, custom_trame=None):
    """Exécute `generate_instagram_reel_packs` avec un timeout dur (ALE-291)."""
    from src.llm import generate_instagram_reel_packs
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(
        generate_instagram_reel_packs,
        topic,
        top_posts,
        benchmark,
        user_context=user_context,
        editorial_role=role,
        trame_id=trame_id,
        count=count,
        inspiration=inspiration,
        recent_posts=recent_posts,
        custom_trame=custom_trame,
    )
    try:
        return fut.result(timeout=GENERATION_TIMEOUT_S)
    finally:
        ex.shutdown(wait=False)


def _resolve_ig_custom_trame(access_token: str, trame_id: str | None) -> dict | None:
    """Résout un id de trame `lib:{template_id}` (ALE-222 parité Instagram) en
    trame personnalisée {label, description}, ou None si l'id vient du
    catalogue statique (ou est introuvable — replie alors sur le catalogue,
    plutôt que de faire échouer la génération sur une entrée supprimée entre
    le choix du client et le lancement du job).
    """
    if not trame_id or not trame_id.startswith("lib:"):
        return None
    tmpl = db.get_post_template(access_token, trame_id[4:])
    if not tmpl:
        return None
    return {
        "label": tmpl.get("structure_label") or "Trame personnalisée",
        "description": (tmpl.get("structure_text") or tmpl.get("post_text") or "").strip(),
    }


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
    platform = job.get("platform") or "linkedin"
    try:
        influencers = enrich_influencers(db.get_user_corpus(access_token, platform=platform))
        top_posts, benchmark = build_benchmark(influencers)
        user_context = db.get_user_ai_context(access_token)
        role = (job.get("editorial_role") or "").strip() or None
        topic = (job.get("topic") or "").strip()
        count = int(job.get("count") or 1)
        # Mémoire des posts déjà créés/publiés sur ce réseau (fail-safe : []).
        recent_posts = db.get_recent_post_memory(access_token, platform=platform) or None

        if platform == "instagram":
            # ALE-291 : pack Reel Instagram (hook + script + caption + hashtags).
            # ALE-222 parité Instagram : la trame peut venir de la bibliothèque du
            # client (id préfixé "lib:", résolu ici) plutôt que du seul catalogue
            # statique — cf. GET /generate/instagram/trames.
            inspiration = None
            inspiration_text = (job.get("inspiration_text") or "").strip()
            if inspiration_text:
                inspiration = {
                    "text": inspiration_text,
                    "author": job.get("inspiration_author"),
                    "url": job.get("inspiration_url"),
                }
            trame_id = job.get("ig_trame_id")
            custom_trame = _resolve_ig_custom_trame(access_token, trame_id)
            variants = _generate_reel_packs_guarded(
                topic, top_posts, benchmark, user_context, role,
                trame_id, count, inspiration=inspiration,
                recent_posts=recent_posts, custom_trame=custom_trame,
            )
        else:
            # ALE-286 : le post d'inspiration passe en TÊTE des références (le
            # formateur de prompt n'en garde que 5) — sinon un tirage aléatoire de la
            # bibliothèque pourrait évincer le seul post que le client a explicitement
            # choisi, et la génération l'ignorerait sans rien signaler.
            reference_posts = db.pick_reference_posts(access_token) or []
            inspiration_text = (job.get("inspiration_text") or "").strip()
            if inspiration_text:
                reference_posts = [{
                    "text": inspiration_text,
                    "author": job.get("inspiration_author"),
                    "url": job.get("inspiration_url"),
                    "note": "post choisi comme inspiration explicite pour CE post — à transposer, jamais à recopier",
                }] + reference_posts

            template_id = job.get("template_id")
            variants = _generate_posts_guarded(
                topic, top_posts, benchmark, user_context, role, count,
                reference_posts=reference_posts or None,
                template=db.get_post_template(access_token, template_id) if template_id else None,
                recent_posts=recent_posts,
            )

        # Annulé pendant le calcul ? On respecte l'annulation.
        if db.get_generation_job_status(access_token, job_id) == "cancelled":
            return

        save_error: str | None = None
        try:
            variants = db.save_generated_posts(access_token, topic, variants, platform=platform)
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


def _generate_post_image_guarded(post_text, prompt, reference_image=None, reference_images=None, identity=False):
    """Exécute `generate_post_image` avec un timeout dur (thread jetable abandonné si figé)."""
    from src.image_gen import generate_post_image
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(
        generate_post_image,
        post_text,
        prompt=prompt,
        reference_image=reference_image,
        reference_images=reference_images,
        identity=identity,
    )
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
        reference_images = None
        identity = False

        # Photos de soi (identité) prioritaires sur la référence style bibliothèque :
        # les deux modes ne se combinent pas — mélanger style + visage brouille le modèle.
        raw_ids = job.get("reference_self_photo_ids") or []
        if isinstance(raw_ids, str):
            # Défensif : PostgREST peut parfois renvoyer du JSON stringifié.
            try:
                import json as _json
                raw_ids = _json.loads(raw_ids)
            except Exception:
                raw_ids = []
        photo_ids = [str(x) for x in raw_ids if x] if isinstance(raw_ids, list) else []
        if photo_ids:
            photos = db.get_self_photos_by_ids(access_token, photo_ids)
            if not photos:
                raise ImageGenError("Photos de référence introuvables.")
            reference_images = []
            for i, photo in enumerate(photos):
                url = (photo or {}).get("image_url")
                if not url:
                    continue
                reference_images.append(
                    fetch_reference_image(url, filename_stem=f"self-{i + 1}")
                )
            if not reference_images:
                raise ImageGenError("Photos de référence introuvables.")
            identity = True
        else:
            template_id = job.get("reference_template_id")
            if template_id:
                template = db.get_post_template(access_token, template_id)
                image_url = (template or {}).get("image_url")
                if not image_url:
                    raise ImageGenError("Image de référence introuvable.")
                reference_image = fetch_reference_image(image_url)

        result = _generate_post_image_guarded(
            job.get("post_text") or "",
            job.get("prompt"),
            reference_image=reference_image,
            reference_images=reference_images,
            identity=identity,
        )

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


# ── Vidéos avatar IA (HeyGen) en tâche de fond (0065) ─────────────────────── #

# Même patron que les images, avec deux différences structurelles :
# (1) le rendu se fait CHEZ HeyGen (asynchrone de leur côté aussi) — le thread
#     ne calcule rien, il lance le rendu puis POLL leur API en poussant un
#     heartbeat en base à chaque passage (sans lui, la réconciliation solderait
#     « orphelin » un rendu légitime de 10 min) ;
# (2) l'URL renvoyée par HeyGen est PRÉ-SIGNÉE et expire — la vidéo est
#     téléchargée immédiatement et re-hébergée sur Zernio, et c'est cette URL
#     pérenne qui part dans `result`. Publier plus tard ne tombe jamais sur un
#     lien mort. Jamais d'octets en base (leçon OOM du 2026-07-27).
# Un rendu prend ~5-10 min par minute de vidéo : le timeout doit rester très
# au-dessus du pire cas d'un reel de 90 s.

AVATAR_VIDEO_TIMEOUT_S = 1500  # 25 min
AVATAR_VIDEO_POLL_INTERVAL_S = 12


def process_avatar_video_job(access_token: str, job_id: str) -> None:
    """Rend la vidéo avatar d'un job en arrière-plan, re-héberge, débite au succès.

    Idempotent quant à l'annulation : jamais de `done` par-dessus un `cancelled`,
    et jamais de débit sur un job annulé (le rendu HeyGen déjà lancé continue et
    sera facturé par HeyGen, mais aucun crédit Cibl n'est pris).
    """
    import time

    from src import heygen, zernio

    job = db.get_avatar_video_job(access_token, job_id)
    if not job:
        return
    if db.get_avatar_video_job_status(access_token, job_id) == "cancelled":
        return

    db.update_avatar_video_job(access_token, job_id, status="running")
    try:
        video_id = job.get("heygen_video_id")
        if not video_id:
            video_id = heygen.create_avatar_video(
                job.get("avatar_look_id") or "",
                job.get("script") or "",
                job.get("voice_id") or "",
                title=f"Cibl reel {job_id[:8]}",
            )
            # Persisté tout de suite : si le thread meurt pendant le polling, le
            # rendu HeyGen reste retrouvable (diagnostic) au lieu d'être perdu.
            db.update_avatar_video_job(access_token, job_id, heygen_video_id=video_id)

        deadline = time.monotonic() + AVATAR_VIDEO_TIMEOUT_S
        video: dict | None = None
        while True:
            if db.get_avatar_video_job_status(access_token, job_id) == "cancelled":
                return
            video = heygen.get_video(video_id)
            if video["status"] == "completed":
                break
            if video["status"] == "failed":
                raise heygen.HeygenError(video.get("error") or "Rendu HeyGen en échec.")
            if time.monotonic() > deadline:
                raise heygen.HeygenError(
                    "Rendu HeyGen trop long (délai dépassé) — réessaie dans un moment."
                )
            db.touch_avatar_video_job(access_token, job_id)  # heartbeat anti-réconciliation
            time.sleep(AVATAR_VIDEO_POLL_INTERVAL_S)

        source_url = video.get("video_url")
        if not source_url:
            raise heygen.HeygenError("Rendu HeyGen terminé mais sans URL de vidéo.")
        data = heygen.download_video(source_url)
        hosted_url = zernio.upload_reel_video(
            f"avatar-reel-{job_id}.mp4", "video/mp4", data
        )
        del data  # gros buffer : le lâcher avant les écritures qui suivent

        # Annulé pendant le rendu/re-hébergement ? On respecte l'annulation.
        if db.get_avatar_video_job_status(access_token, job_id) == "cancelled":
            return

        ok, balance = db.debit_credits(access_token, "avatar_video")
        if not ok:
            print(
                f"[avatar-job] débit impossible après un rendu réussi (solde {balance}) — vidéo livrée sans débit.",
                flush=True,
            )
        result = {
            "video_url": hosted_url,
            "thumbnail_url": video.get("thumbnail_url"),
            "duration": video.get("duration"),
            "credits": balance if ok else None,
        }
        db.update_avatar_video_job(access_token, job_id, status="done", result=result)
    except Exception as exc:  # noqa: BLE001 — on isole l'échec d'un job
        if db.get_avatar_video_job_status(access_token, job_id) == "cancelled":
            return
        db.update_avatar_video_job(
            access_token, job_id, status="error", error=str(exc)[:500]
        )


def start_avatar_video_job_thread(access_token: str, job_id: str) -> None:
    """Lance le rendu vidéo avatar d'un job dans un thread de fond (non bloquant)."""
    thread = threading.Thread(
        target=process_avatar_video_job, args=(access_token, job_id), daemon=True
    )
    thread.start()


# Garde-fou : durée max d'une collecte. Aligné sur le timeout de l'actor Apify
# (`lead_finder`, 1500 s) et < LEAD_JOB_STALE_MINUTES pour qu'un run figé libère
# le thread avant d'être soldé « orphelin ».
LEAD_COLLECT_TIMEOUT_S = 1500


def _collect_and_persist_guarded(access_token: str, source: dict, max_comments: int):
    """Exécute la collecte avec un timeout dur (thread jetable abandonné si figé)."""
    from src.lead_finder import collect_and_persist

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(collect_and_persist, access_token, source, max_comments)
    try:
        return fut.result(timeout=LEAD_COLLECT_TIMEOUT_S)
    finally:
        ex.shutdown(wait=False)


def process_lead_collection_job(access_token: str, job_id: str) -> None:
    """Collecte les leads d'une source en arrière-plan (ALE-240).

    Deux natures de source, aiguillées par `job["kind"]` : les commentateurs d'un
    post concurrent ('comments', Apify, facturé au volume) et les profils d'un
    lien de recherche LinkedIn ('search', Unipile, gratuit).

    Idempotent quant à l'annulation : si le job a été annulé avant/pendant le
    scrape, on n'écrit jamais `done` par-dessus. Le débit n'a lieu qu'à la
    complétion réussie (dans `collect_and_persist`) — un job annulé/en échec
    n'est jamais débité.
    """
    job = db.get_lead_collection_job(access_token, job_id)
    if not job:
        return
    if db.get_lead_collection_job_status(access_token, job_id) == "cancelled":
        return

    db.update_lead_collection_job(access_token, job_id, status="running")
    try:
        source = db.get_lead_source(access_token, job["source_id"])
        if not source:
            raise RuntimeError("Source de prospection introuvable.")

        # Une source `import` (fichier CSV/Excel, 0070) ne se « recollecte » pas :
        # le fichier n'existe plus côté serveur. Son traitement passe par
        # `process_lead_import_job` (qui reçoit les profils parsés en mémoire) —
        # si un job d'import atterrit malgré tout ici (mauvais aiguillage, rejeu),
        # on refuse net plutôt que de scraper les « commentaires » d'une URL
        # `import://…` via Apify (la panne silencieuse de #407, en pire).
        if job.get("kind") == "import" or source.get("kind") == "import":
            raise RuntimeError(
                "Cette source vient d'un fichier importé — re-téléverse le fichier "
                "pour ajouter de nouveaux prospects."
            )

        # Aiguillage en ceinture ET bretelles : le `kind` du job, mais AUSSI celui
        # de la source. Une source de recherche ne peut jamais être collectée par
        # l'actor de commentaires — se fier au seul job rendait la routine otage
        # d'une projection SQL (cf. `_LEAD_JOB_COLS`), et l'erreur était muette.
        if job.get("kind") == "search" or source.get("kind") == "search":
            # Import d'un lien de recherche LinkedIn (0062) : profils lus via le
            # compte connecté du client (Unipile), sans débit de crédits.
            from src.lead_search import collect_and_persist_search

            result = collect_and_persist_search(
                access_token, source, int(job.get("max_comments") or 0)
            )
        else:
            result = _collect_and_persist_guarded(
                access_token, source, int(job.get("max_comments") or 0)
            )

        # Annulé pendant le scrape ? On respecte l'annulation (jamais de `done`).
        if db.get_lead_collection_job_status(access_token, job_id) == "cancelled":
            return
        db.update_lead_collection_job(access_token, job_id, status="done", result=result)
    except Exception as exc:  # noqa: BLE001 — on isole l'échec d'un job
        if db.get_lead_collection_job_status(access_token, job_id) == "cancelled":
            return
        db.update_lead_collection_job(
            access_token, job_id, status="error", error=str(exc)[:500]
        )


def start_lead_collection_job_thread(access_token: str, job_id: str) -> None:
    """Lance une collecte de commentateurs dans un thread de fond (non bloquant)."""
    thread = threading.Thread(
        target=process_lead_collection_job, args=(access_token, job_id), daemon=True
    )
    thread.start()


def process_lead_import_job(
    access_token: str,
    job_id: str,
    source: dict,
    leads: list[dict],
    ignored: int,
    rows: int,
    truncated: bool = False,
) -> None:
    """Persiste un import de fichier de leads en arrière-plan (source 0070).

    Contrairement aux deux autres natures de job, les données arrivent EN
    MÉMOIRE (le fichier a été parsé dans la requête d'upload) : le job n'existe
    que pour donner au frontend le même suivi par polling que la recherche —
    et parce que le scoring ICP (appel IA par lots) peut prendre plus longtemps
    que le budget d'une requête HTTP sur un gros fichier. Revers assumé : un
    redémarrage du process en plein import perd les profils pas encore écrits ;
    le job est alors soldé « délai dépassé » par la réconciliation et le client
    re-téléverse son fichier (la dédup de `save_leads` rend le rejeu sans danger).

    Aucun débit de crédits, comme la recherche : lire un fichier ne coûte rien.
    """
    from src.lead_import import persist_import

    if db.get_lead_collection_job_status(access_token, job_id) == "cancelled":
        return
    db.update_lead_collection_job(access_token, job_id, status="running")
    try:
        result = persist_import(access_token, source, leads, ignored, rows, truncated)
        if db.get_lead_collection_job_status(access_token, job_id) == "cancelled":
            return
        db.update_lead_collection_job(access_token, job_id, status="done", result=result)
    except Exception as exc:  # noqa: BLE001 — on isole l'échec d'un job
        if db.get_lead_collection_job_status(access_token, job_id) == "cancelled":
            return
        db.update_lead_collection_job(
            access_token, job_id, status="error", error=str(exc)[:500]
        )


def start_lead_import_job_thread(
    access_token: str,
    job_id: str,
    source: dict,
    leads: list[dict],
    ignored: int,
    rows: int,
    truncated: bool = False,
) -> None:
    """Lance la persistance d'un import de fichier dans un thread de fond."""
    thread = threading.Thread(
        target=process_lead_import_job,
        args=(access_token, job_id, source, leads, ignored, rows, truncated),
        daemon=True,
    )
    thread.start()
