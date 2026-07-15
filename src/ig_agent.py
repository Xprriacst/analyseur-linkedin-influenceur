"""Orchestration de l'agent de qualification Instagram (ALE-195 / 202).

Fait le lien entre un message prospect persisté (ALE-201) et le cerveau Claude
(`llm.qualify_prospect`) : charge la FAQ, reconstruit l'historique, génère la
réponse suggérée structurée, et persiste un `ig_drafts` (statut pending)
rattaché au message. N'ENVOIE rien (envoi = 204/205).

La FAQ est remplie par l'utilisateur dans l'app (table `ig_faqs`, RLS). Repli
si vide : fichier de config serveur via l'env `IG_FAQ_PATH`, sinon le gabarit
versionné `docs/faq-qualification-instagram.template.md`.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from src import db, manychat, transcription
from src.llm import qualify_prospect

_DEFAULT_FAQ_PATH = "docs/faq-qualification-instagram.template.md"

# Les conversations de simulation (page de test ManyChat) ont un prospect_id
# préfixé "test:" : tout le pipeline tourne normalement mais rien ne part vers
# l'API ManyChat — le message sortant est seulement persisté.
TEST_PROSPECT_PREFIX = "test:"


def is_test_prospect(prospect_id) -> bool:
    return str(prospect_id or "").startswith(TEST_PROSPECT_PREFIX)

# Seuil de confiance conservateur pour l'autopilot (surchargeable).
_AUTOPILOT_THRESHOLD = float(os.environ.get("IG_AUTOPILOT_CONFIDENCE_THRESHOLD", "0.85"))

# Cache mémoire du fichier FAQ (clé = chemin), invalidé si le mtime change.
_faq_cache: dict[str, tuple[float, str]] = {}


def faq_path() -> str:
    return os.environ.get("IG_FAQ_PATH") or _DEFAULT_FAQ_PATH


def load_faq(user_id: str | None = None) -> str:
    """Charger le texte FAQ+objectif : d'abord celui de l'utilisateur (base), sinon fichier.

    Renvoie une chaîne vide si rien n'est configuré (l'appelant décide : sans
    FAQ, le cerveau escalade tout → `besoin_humain=true`, ce qui est le bon
    comportement fail-safe). Cache fichier invalidé au changement de mtime.
    """
    if user_id:
        user_faq = db.get_ig_faq_admin(user_id)
        if user_faq:
            return user_faq
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
    faq = load_faq(user_id)
    learned_rules = db.admin_get_learned_rules(user_id, "instagram")
    history = db.list_ig_messages_admin(user_id, conversation_id)
    result = qualify_prospect(faq, history, latest_message, learned_rules)
    draft = db.create_ig_draft_admin(
        user_id,
        conversation_id,
        message_id,
        reply=result.get("reponse", ""),
        confidence=result.get("confiance"),
        needs_human=bool(result.get("besoin_humain", True)),
        reason=result.get("raison"),
    )
    # Garde-fou + autopilot conditionnel (ALE-205) : décide envoi auto vs escalade.
    _route_draft(user_id, conversation_id, message_id, draft, result)
    return draft


def _route_draft(
    user_id: str,
    conversation_id: str,
    message_id: str,
    draft: dict | None,
    result: dict,
) -> None:
    """Router la réponse suggérée : envoi automatique (autopilot vert) ou escalade.

    « Vert » = couvert par la FAQ (`besoin_humain=false`) ET `confiance >= seuil`.
    Autopilot n'envoie QUE sur le vert, conversation en mode autopilot, kill-switch
    global OFF, et fenêtre 24 h ouverte. Sinon → reste `pending` = escalade in-app
    (badge dans l'inbox, ALE-204). Toute décision est journalisée pour tuner le seuil.
    """
    import logging

    confidence = result.get("confiance")
    needs_human = bool(result.get("besoin_humain", True))
    reason = result.get("raison")
    draft_id = draft.get("id") if draft else None

    green = (not needs_human) and isinstance(confidence, (int, float)) and confidence >= _AUTOPILOT_THRESHOLD

    conv = db.get_ig_conversation_admin(user_id, conversation_id)
    mode = (conv or {}).get("mode", "supervised")
    kill = db.get_ig_kill_switch_admin(user_id)
    window_open = _window_open((conv or {}).get("window_expires_at"))

    if mode == "autopilot" and green and not kill and window_open and draft:
        try:
            if not is_test_prospect(conv.get("prospect_id")):
                # Multi-client : envoi avec la clé ManyChat de l'utilisateur (repli global).
                api_token = db.get_ig_manychat_token_admin(user_id)
                manychat.send_text(conv["prospect_id"], draft.get("reply", ""), api_token=api_token)
            db.add_ig_message_admin(
                user_id, conversation_id, role="out", source="agent",
                text=draft.get("reply", ""), kind="text",
            )
            db.update_ig_draft_status_admin(draft_id, "sent")
            db.log_ig_decision_admin(
                user_id, conversation_id, message_id, draft_id,
                decision="auto_sent", confidence=confidence, needs_human=needs_human, reason=reason,
            )
            return
        except Exception as exc:  # noqa: BLE001 — échec envoi auto → on retombe en supervisé
            logging.error("Envoi autopilot IG échoué (conv=%s): %s", conversation_id, exc)
            db.log_ig_decision_admin(
                user_id, conversation_id, message_id, draft_id,
                decision="escalated", confidence=confidence, needs_human=needs_human,
                reason=f"échec envoi auto: {exc}",
            )
            return

    # Sinon : le draft reste pending → escalade in-app (badge inbox). On journalise
    # « escalated » quand l'agent ne sait pas / rouge, « supervised » sinon.
    decision = "escalated" if (needs_human or not green) else "supervised"
    db.log_ig_decision_admin(
        user_id, conversation_id, message_id, draft_id,
        decision=decision, confidence=confidence, needs_human=needs_human, reason=reason,
    )


def _window_open(window_expires_at) -> bool:
    """True si la fenêtre de réponse 24 h est encore ouverte (ou inconnue)."""
    if not window_expires_at:
        return True
    import datetime

    try:
        exp = datetime.datetime.fromisoformat(str(window_expires_at).replace("Z", "+00:00"))
        return exp >= datetime.datetime.now(datetime.timezone.utc)
    except (ValueError, TypeError):
        return True


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
    webhook ManyChat). Le message vocal est **d'abord persisté avec un texte
    d'attente** pour être immédiatement visible dans l'inbox (kind=voice), puis
    Whisper remplace ce texte par la transcription → génère le draft. Si la
    transcription échoue/est vide, le message reste visible avec une mention
    d'échec (l'humain sait qu'un vocal est arrivé et peut répondre à la main).
    Best-effort : tout échec est loggé.
    """
    def _run() -> None:
        import logging

        # 1. Rendre le vocal visible tout de suite — ne jamais laisser un message
        #    entrant invisible parce que la transcription a raté (cf. inbox vide).
        msg = db.add_ig_message_admin(
            user_id, conversation_id, role="in", source="prospect",
            text="Note vocale reçue — transcription en cours…", kind="voice",
        )

        # 2. Transcrire, puis remplacer le texte d'attente.
        try:
            text = transcription.transcribe_audio_url(audio_url)
        except Exception as exc:  # noqa: BLE001
            logging.error("Transcription vocale IG échouée (conv=%s): %s", conversation_id, exc)
            if msg:
                db.update_ig_message_text_admin(
                    msg["id"], "Pièce jointe reçue — à consulter directement sur Instagram."
                )
            return
        if not text:
            logging.warning("Transcription vocale IG vide (conv=%s)", conversation_id)
            if msg:
                db.update_ig_message_text_admin(
                    msg["id"], "Note vocale reçue — inaudible ou vide (à écouter sur Instagram)."
                )
            return
        if not msg:
            return
        db.update_ig_message_text_admin(msg["id"], text)

        # 3. Même pipeline qu'un DM texte : génère la réponse suggérée.
        try:
            generate_draft(user_id, conversation_id, msg["id"], text)
        except Exception as exc:  # noqa: BLE001
            logging.error("Génération draft (vocal) IG échouée (conv=%s): %s", conversation_id, exc)

    threading.Thread(target=_run, daemon=True).start()
