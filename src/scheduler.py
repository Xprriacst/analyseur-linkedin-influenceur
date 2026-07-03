"""ALE-96 — Cron : publier les posts LinkedIn planifiés arrivés à échéance.

Entrypoint : python -m src.scheduler
Schedule conseillé sur Render : */5 * * * * (toutes les 5 minutes)

Dépendances :
- SUPABASE_SERVICE_ROLE_KEY (admin client — bypass RLS)
- ZERNIO_API_KEY
"""
from __future__ import annotations

import logging

from src import db, zernio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


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
            media_items = zernio.prepare_media_items(post.get("media_items") or [])
            result = zernio.create_post(
                post["post_text"],
                account_id,
                publish_now=True,
                media_items=media_items,
            )
            z_post = result.get("post") or result
            db.update_scheduled_post_status(
                post_id, "published", zernio_post_id=z_post.get("_id")
            )
            logger.info(f"Post {post_id} publié (user {user_id}, zernio_id={z_post.get('_id')}).")
        except Exception as exc:
            logger.error(f"Erreur publication post {post_id} : {exc}")
            db.update_scheduled_post_status(post_id, "failed", error=str(exc))


if __name__ == "__main__":
    run()
