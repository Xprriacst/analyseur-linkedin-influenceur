"""ALE-96 — Cron : publier les posts LinkedIn planifiés arrivés à échéance.

Entrypoint : python -m src.scheduler
Schedule conseillé sur Render : */5 * * * * (toutes les 5 minutes)

Dépendances :
- SUPABASE_SERVICE_ROLE_KEY (admin client — bypass RLS)
- ZERNIO_API_KEY
"""
from __future__ import annotations

import logging

from src import crosspost, db, features, zernio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _user_features(user_id: str) -> set[str] | None:
    """Droits du compte, lus en service-role (le cron n'a pas de jeton).

    None = droits illisibles → l'appelant ferme (fail closed, même règle que le
    planificateur de l'autopilote) : on ne publie pas au nom d'un compte dont on
    ignore les droits."""
    meta = db.admin_user_app_metadata(user_id)
    if meta is None:
        return None
    return features.features_of({"app_metadata": meta})


def publish_cross_posts(post: dict) -> dict:
    """Publie les versions X/Reddit stockées avec un post programmé (ALE-59).

    Appelé APRÈS le succès de la publication LinkedIn (si LinkedIn échoue, le
    post reste `failed` et rien d'autre ne part : un retry ne risque pas de
    dupliquer les versions annexes). Best-effort réseau par réseau : le résultat
    (status / erreur / id Zernio) est consigné DANS `cross_posts` — un échec X
    n'empêche ni Reddit ni le statut `published` du post LinkedIn.
    """
    cross = dict(post.get("cross_posts") or {})

    # Déploiement progressif (fail closed) : sans ce contrôle, retirer le flag à
    # un compte ne couperait pas les versions X/Reddit qu'il a déjà programmées —
    # le flag ne serait qu'un masque d'affichage. Droits illisibles ⇒ on ne
    # publie pas non plus (consigné, pas silencieux).
    feats = _user_features(post.get("user_id") or "")

    x_version = cross.get("x") if isinstance(cross.get("x"), dict) else None
    if x_version:
        entry = dict(x_version)
        tweets = [t for t in (entry.get("tweets") or []) if isinstance(t, str) and t.strip()]
        account_id = post.get("zernio_x_account_id")
        if feats is None or "x" not in feats:
            entry.update({"status": "failed", "error": "Fonctionnalité non activée sur ce compte (ou droits illisibles)."})
        elif not account_id:
            entry.update({"status": "failed", "error": "Compte X non connecté."})
        elif not tweets:
            entry.update({"status": "failed", "error": "Version X vide."})
        else:
            psd = {"threadItems": [{"content": t} for t in tweets]} if len(tweets) > 1 else None
            try:
                result = zernio.create_post(
                    tweets[0] if len(tweets) == 1 else "\n\n".join(tweets),
                    account_id,
                    publish_now=True,
                    platform=zernio.PLATFORM_X,
                    platform_specific_data=psd,
                )
                z_post = result.get("post") or result
                entry.update({"status": "published", "zernio_post_id": z_post.get("_id")})
            except Exception as exc:
                logger.error(f"Post {post['id']} : publication X échouée : {exc}")
                entry.update({"status": "failed", "error": str(exc)[:500]})
        cross["x"] = entry

    reddit_version = cross.get("reddit") if isinstance(cross.get("reddit"), dict) else None
    if reddit_version:
        entry = dict(reddit_version)
        account_id = post.get("zernio_reddit_account_id")
        subreddit = crosspost.normalize_subreddit_name(entry.get("subreddit"))
        if feats is None or "reddit" not in feats:
            entry.update({"status": "failed", "error": "Fonctionnalité non activée sur ce compte (ou droits illisibles)."})
        elif not account_id:
            entry.update({"status": "failed", "error": "Compte Reddit non connecté."})
        elif not subreddit or not (entry.get("body") or "").strip() or not (entry.get("title") or "").strip():
            entry.update({"status": "failed", "error": "Version Reddit incomplète."})
        else:
            psd = {"subreddit": subreddit, "title": str(entry["title"]).strip()[:crosspost.REDDIT_TITLE_MAX]}
            if entry.get("flair_id"):
                psd["flairId"] = entry["flair_id"]
            elif entry.get("flair_text"):
                psd["flairText"] = entry["flair_text"]
            try:
                result = zernio.create_post(
                    str(entry["body"]).strip(),
                    account_id,
                    publish_now=True,
                    platform="reddit",
                    platform_specific_data=psd,
                )
                z_post = result.get("post") or result
                entry.update({"status": "published", "zernio_post_id": z_post.get("_id")})
            except Exception as exc:
                logger.error(f"Post {post['id']} : publication Reddit échouée : {exc}")
                entry.update({"status": "failed", "error": str(exc)[:500]})
        cross["reddit"] = entry

    return cross


def run() -> None:
    if not db.admin_enabled():
        logger.warning("SUPABASE_SERVICE_ROLE_KEY absent — scheduler ignoré.")
        return
    if not zernio.enabled():
        logger.warning("ZERNIO_API_KEY absent — scheduler ignoré.")
        return

    due = db.get_due_scheduled_posts()
    logger.info(f"Scheduler : {len(due)} post(s) validé(s) sur Slack à publier.")

    for post in due:
        post_id = post["id"]
        user_id = post["user_id"]
        account_id = post.get("zernio_account_id")

        if not account_id:
            logger.warning(f"Post {post_id} (user {user_id}) : compte LinkedIn non connecté.")
            db.update_scheduled_post_status(
                post_id, "failed", error="Compte LinkedIn non connecté (zernio_account_id manquant)."
            )
            continue

        try:
            media_items = zernio.prepare_image_media_items(post.get("media_items") or [])
            result = zernio.create_post(
                post["post_text"],
                account_id,
                publish_now=True,
                media_items=media_items,
            )
            z_post = result.get("post") or result
            # ALE-59 : versions X/Reddit publiées ensemble, après le succès
            # LinkedIn (résultats par réseau consignés dans cross_posts). Un
            # imprévu ici ne doit jamais faire passer en `failed` un post déjà
            # publié sur LinkedIn (aucun retry ne doit pouvoir le dupliquer).
            cross_results = None
            if post.get("cross_posts"):
                try:
                    cross_results = publish_cross_posts(post)
                except Exception as cross_exc:
                    logger.error(f"Post {post_id} : publication multi-réseaux échouée : {cross_exc}")
            db.update_scheduled_post_status(
                post_id, "published", zernio_post_id=z_post.get("_id"), cross_posts=cross_results
            )
            logger.info(f"Post {post_id} publié (user {user_id}, zernio_id={z_post.get('_id')}).")
        except Exception as exc:
            logger.error(f"Erreur publication post {post_id} : {exc}")
            db.update_scheduled_post_status(post_id, "failed", error=str(exc))


if __name__ == "__main__":
    run()
