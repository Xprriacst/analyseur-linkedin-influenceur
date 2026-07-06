"""Orchestration de l'agent de qualification Instagram (ALE-195 / 202).

Fait le lien entre un message prospect persisté (ALE-201) et le cerveau Claude
(`llm.qualify_prospect`) : charge la FAQ depuis un fichier de config externe,
reconstruit l'historique, génère la réponse suggérée structurée, et persiste un
`ig_drafts` (statut pending) rattaché au message. N'ENVOIE rien (envoi = 204/205).

La FAQ vit dans un fichier externe (pas de table en v1) : chemin via l'env
`IG_FAQ_PATH`, sinon le gabarit versionné `docs/faq-qualification-instagram.template.md`.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from src import db, transcription
from src.llm import qualify_prospect

_DEFAULT_FAQ_PATH = "docs/faq-qualification-instagram.template.md"

# Cache mémoire du fichier FAQ (clé = chemin), invalidé si le mtime change.
_faq_cache: dict[str, tuple[float, str]] = {}


def faq_path() -> str:
    return os.environ.get("IG_FAQ_PATH") or _DEFAULT_FAQ_PATH


def load_faq() -> str:
    """Charger le texte FAQ+objectif depuis le fichier de config externe.

    Renvoie une chaîne vide si le fichier est absent (l'appelant décide : sans
    FAQ, le cerveau escalade tout → `besoin_humain=true`, ce qui est le bon
    comportement fail-safe). Cache invalidé au changement de mtime.
    """
    path = faq_path()
    try:
        p = Path(path)
        mtime = p.stat().st_mtime
        cached = _faq_cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        text = p.read_text(encoding="utf-8")
        _faq_cache[path] = (mtime, text)
        return text
    except (FileNotFoundError, OSError):
        return ""


def generate_draft(
    user_id: str,
    conversation_id: str,
    message_id: str,
    latest_message: str,
) -> dict | None:
    """Générer + persister la réponse suggérée pour un message prospect.

    Charge la FAQ, reconstruit l'historique de la conversation, appelle le
    cerveau Claude, écrit un `ig_drafts` pending. Best-effort : toute erreur est
    remontée à l'appelant (qui l'avale en tâche de fond). Renvoie le draft créé.
    """
    faq = load_faq()
    history = db.list_ig_messages_admin(user_id, conversation_id)
    result = qualify_prospect(faq, history, latest_message)
    return db.create_ig_draft_admin(
        user_id,
        conversation_id,
        message_id,
        reply=result.get("reponse", ""),
        confidence=result.get("confiance"),
        needs_human=bool(result.get("besoin_humain", True)),
        reason=result.get("raison"),
    )


def generate_draft_async(
    user_id: str,
    conversation_id: str,
    message_id: str,
    latest_message: str,
) -> None:
    """Lancer `generate_draft` en tâche de fond (ne bloque pas le webhook ManyChat).

    Un échec (LLM, réseau, DB) est loggé sans casser l'accusé de réception au
    middleware. Le message reste persisté ; une regénération manuelle reste
    possible côté inbox (ALE-204).
    """
    def _run() -> None:
        try:
            generate_draft(user_id, conversation_id, message_id, latest_message)
        except Exception as exc:  # noqa: BLE001 — best-effort, on ne casse pas le webhook
            import logging

            logging.error("Génération draft IG échouée (conv=%s): %s", conversation_id, exc)

    threading.Thread(target=_run, daemon=True).start()


def handle_inbound_voice_async(
    user_id: str,
    conversation_id: str,
    audio_url: str,
) -> None:
    """Transcrire une note vocale entrante puis alimenter le même pipeline (ALE-203).

    En tâche de fond (transcription + LLM peuvent être longs → ne bloque pas le
    webhook ManyChat) : Whisper → persiste le texte comme un `ig_messages` normal
    (source=prospect, kind=voice) → génère le draft. Indistinguable d'un DM texte
    pour la suite du pipeline. Best-effort : tout échec est loggé.
    """
    def _run() -> None:
        import logging

        try:
            text = transcription.transcribe_audio_url(audio_url)
        except Exception as exc:  # noqa: BLE001
            logging.error("Transcription vocale IG échouée (conv=%s): %s", conversation_id, exc)
            return
        if not text:
            logging.warning("Transcription vocale IG vide (conv=%s)", conversation_id)
            return
        msg = db.add_ig_message_admin(
            user_id, conversation_id, role="in", source="prospect", text=text, kind="voice"
        )
        if not msg:
            return
        try:
            generate_draft(user_id, conversation_id, msg["id"], text)
        except Exception as exc:  # noqa: BLE001
            logging.error("Génération draft (vocal) IG échouée (conv=%s): %s", conversation_id, exc)

    threading.Thread(target=_run, daemon=True).start()
