"""ALE-174 — Cron : sort les actions de prospection de la file, au bon moment.

Entrypoint : python -m src.outreach_sender
Schedule Render conseillé : */10 * * * * (toutes les 10 minutes)

Dépendances :
- SUPABASE_SERVICE_ROLE_KEY (client admin — contourne la RLS)
- UNIPILE_DSN + UNIPILE_API_KEY

Ce module ne DÉCIDE rien : toute la logique (plage horaire, warm-up, plafonds,
délai aléatoire, détection de restriction) vit dans `src/outreach_engine.py`, en
fonctions pures testées sans réseau. Ici, on ne fait que de l'orchestration et des
appels — c'est volontaire : la partie qui protège le compte du client doit être
lisible et testable d'un bloc.

⚠️ Cloisonnement : ce cron tourne en service-role, donc SANS le cloisonnement
automatique de la base. Chaque accès passe par une fonction `db.admin_*` qui exige
un `user_id`, et `assert_same_owner` revérifie compte/action/lead juste avant
l'appel réseau. Sans ça, on pourrait envoyer le message du client A depuis le
compte LinkedIn du client B — sans la moindre erreur côté Unipile.
"""
from __future__ import annotations

import datetime
import logging
from typing import Any

from src import db, features, llm, outreach_autopilot as autopilot, outreach_engine as engine, unipile

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Une seule action par passage et par compte : avec un cron toutes les 10 min et un
# délai aléatoire de 11 à 37 min, le rythme reste celui d'un humain qui prospecte.
SEND_PER_TICK = 1


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _resolve_provider_id(account_id: str, lead: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """`provider_id` Unipile du lead (déjà connu, sinon résolu depuis l'URL du profil)."""
    known = lead.get("provider_id")
    identifier = known or unipile.profile_identifier(lead.get("profile_url"))
    if not identifier:
        return None, None
    profile = unipile.get_user_profile(account_id, identifier)
    return unipile.provider_id_of(profile) or known, profile


def _send_invite(account: dict[str, Any], item: dict[str, Any], lead: dict[str, Any]) -> bool:
    """Envoie une demande de connexion SANS note. True si le quota a été consommé."""
    user_id = account["user_id"]
    account_id = account["unipile_account_id"]
    provider_id, profile = _resolve_provider_id(account_id, lead)
    if not provider_id:
        db.admin_update_queue_item(user_id, item["id"], status="failed", error="Identifiant LinkedIn illisible pour ce profil.")
        return False

    # Déjà en relation : rien à envoyer, et surtout aucun quota à consommer.
    if profile is not None and unipile.is_first_degree(profile):
        db.admin_update_lead_outreach(user_id, lead["id"], {"outreach_status": "connected", "provider_id": provider_id})
        db.admin_update_queue_item(user_id, item["id"], status="skipped", error="Déjà en relation — invitation inutile.")
        logger.info(f"[{user_id}] lead {lead['id']} déjà en relation, invitation annulée.")
        return False

    unipile.send_invitation(account_id, provider_id)
    db.admin_log_outreach_action(
        user_id, action_type="invite", status="sent", origin="queue",
        lead_id=lead["id"], provider_id=provider_id,
    )
    db.admin_update_lead_outreach(user_id, lead["id"], {"outreach_status": "invite_sent", "provider_id": provider_id})
    db.admin_update_queue_item(user_id, item["id"], status="sent")
    logger.info(f"[{user_id}] invitation envoyée au lead {lead['id']}.")
    return True


def _send_message(account: dict[str, Any], item: dict[str, Any], lead: dict[str, Any]) -> bool:
    """Envoie le message mis en file. True si le quota a été consommé."""
    user_id = account["user_id"]
    account_id = account["unipile_account_id"]
    text = (item.get("body") or "").strip()
    if not text:
        db.admin_update_queue_item(user_id, item["id"], status="failed", error="Message vide.")
        return False
    provider_id = lead.get("provider_id")
    if not provider_id:
        db.admin_update_queue_item(user_id, item["id"], status="failed", error="Lead sans identifiant LinkedIn — envoie d'abord une demande de connexion.")
        return False

    result = unipile.start_new_chat(account_id, provider_id, text)
    chat_id = unipile.chat_id_of(result)
    db.admin_log_outreach_action(
        user_id, action_type="message", status="sent", origin="queue",
        lead_id=lead["id"], provider_id=provider_id, chat_id=chat_id,
    )
    db.admin_update_lead_outreach(user_id, lead["id"], {"outreach_status": "messaged", "outreach_chat_id": chat_id})
    db.admin_update_queue_item(user_id, item["id"], status="sent")
    logger.info(f"[{user_id}] message envoyé au lead {lead['id']}.")
    return True


def send_item(account: dict[str, Any], item: dict[str, Any]) -> bool:
    """Envoie UNE action de la file. Retourne True si une action a réellement été
    envoyée (donc si le délai avant la prochaine doit être posé).

    Toute erreur Unipile est journalisée (le client doit la voir), et une erreur de
    type limite/restriction **gèle le compte** au lieu de continuer à taper."""
    user_id = account["user_id"]
    lead = db.admin_get_lead(user_id, item["lead_id"])
    if not lead:
        db.admin_update_queue_item(user_id, item["id"], status="failed", error="Lead introuvable.")
        return False

    # Garde-fou multi-client, juste avant l'appel réseau (voir en-tête du module).
    engine.assert_same_owner(
        account.get("user_id"), item.get("user_id"), lead.get("user_id"),
        context=f"action {item.get('id')}",
    )

    try:
        if item["action_type"] == "invite":
            return _send_invite(account, item, lead)
        if item["action_type"] == "message":
            return _send_message(account, item, lead)
        db.admin_update_queue_item(user_id, item["id"], status="failed", error=f"Type d'action inconnu : {item['action_type']}")
        return False
    except unipile.UnipileError as exc:
        message = str(exc)
        db.admin_log_outreach_action(
            user_id, action_type=item["action_type"], status="failed", origin="queue",
            lead_id=lead.get("id"), error=message,
        )
        db.admin_update_queue_item(user_id, item["id"], status="failed", error=message)
        if engine.is_restriction_error(message):
            db.admin_freeze_outreach_account(user_id, f"LinkedIn a signalé une limite : {message}")
            logger.error(f"[{user_id}] compte GELÉ après une erreur de restriction : {message}")
        else:
            logger.error(f"[{user_id}] échec d'envoi ({item['action_type']}) : {message}")
        return False


def _check_acceptance(account: dict[str, Any], lead: dict[str, Any]) -> bool:
    """Vérifie l'acceptation de l'invitation d'UN lead. True si elle vient d'être vue.

    C'est une lecture Unipile (le profil), pas un envoi : aucun quota n'est consommé.
    Cas positif → le lead passe « en relation » (le premier message reste un clic
    humain). Cas négatif → on note juste la date du re-check (cadence)."""
    user_id = account["user_id"]
    account_id = account["unipile_account_id"]
    # Garde-fou multi-client, juste avant l'appel réseau (voir en-tête du module).
    engine.assert_same_owner(
        account.get("user_id"), lead.get("user_id"),
        context=f"acceptation lead {lead.get('id')}",
    )
    provider_id, profile = _resolve_provider_id(account_id, lead)
    if profile is not None and unipile.is_first_degree(profile):
        db.admin_update_lead_outreach(user_id, lead["id"], {
            "outreach_status": "connected",
            "provider_id": provider_id or lead.get("provider_id"),
            "outreach_last_checked_at": _now().isoformat(),
        })
        logger.info(f"[{user_id}] invitation acceptée — lead {lead['id']} passe en relation.")
        return True
    db.admin_mark_lead_checked(user_id, lead["id"])
    return False


def check_acceptances(account: dict[str, Any]) -> int:
    """Balaie les leads en attente d'acceptation et bascule ceux qui ont accepté.

    Sans ça, un lead reste bloqué en « en attente d'acceptation » tant que le client
    ne clique pas manuellement — même si la personne a accepté depuis des jours.

    Suspendu pendant un gel : LinkedIn a signalé une limite, on ne tape plus son API,
    même en lecture. Une erreur de restriction pendant le balayage gèle le compte et
    stoppe le balayage (comme pour les envois)."""
    user_id = account.get("user_id")
    if not user_id:
        return 0
    now = _now()
    if engine.freeze_active(now, account):
        return 0

    leads = db.admin_list_leads_awaiting_acceptance(user_id)
    due = engine.pick_acceptance_checks(now, leads)
    accepted = 0
    for lead in due:
        try:
            if _check_acceptance(account, lead):
                accepted += 1
        except unipile.UnipileError as exc:
            message = str(exc)
            logger.error(f"[{user_id}] vérification d'acceptation échouée (lead {lead.get('id')}) : {message}")
            if engine.is_restriction_error(message):
                db.admin_freeze_outreach_account(user_id, f"LinkedIn a signalé une limite : {message}")
                logger.error(f"[{user_id}] compte GELÉ après une restriction en lecture : {message}")
                break
    if accepted:
        logger.info(f"[{user_id}] {accepted} invitation(s) nouvellement acceptée(s).")
    return accepted


# ── ALE-284 — Autopilote : dépose les actions, n'en envoie jamais ─────────────
#
# Le planificateur tourne AVANT le dépilage, et ne fait qu'écrire dans la file
# d'ALE-174. Toute la protection du compte (plage horaire, warm-up, délai aléatoire,
# plafonds, gel) reste donc l'affaire du moteur : l'autopilote ne peut pas la
# contourner, même en cas de bug, parce qu'il n'a aucun accès à Unipile.


def _plan_invites(account: dict[str, Any], settings: autopilot.AutopilotSettings, leads: list[dict[str, Any]]) -> int:
    """Dépose les invitations automatiques du passage. Retourne le nombre déposé."""
    user_id = account["user_id"]
    remaining = settings.daily_invite_cap - db.admin_count_auto_invites_today(user_id)
    if remaining <= 0:
        return 0

    picked = autopilot.pick_invites(
        leads, settings,
        known_lead_ids=db.admin_queue_lead_ids(user_id, "invite"),
        remaining_cap=remaining,
    )
    queued = 0
    for lead in picked:
        # Garde-fou multi-client : le lead vient d'une lecture service-role, on revérifie
        # qu'il appartient bien au compte pour lequel on planifie (voir en-tête du module).
        engine.assert_same_owner(account.get("user_id"), lead.get("user_id"), context=f"auto-invite lead {lead.get('id')}")
        if db.admin_enqueue_outreach_action(user_id, lead_id=lead["id"], action_type="invite"):
            queued += 1
    if queued:
        logger.info(f"[{user_id}] autopilote : {queued} invitation(s) déposée(s) en file.")
    return queued


def _compose_message(settings: autopilot.AutopilotSettings, targeting: dict[str, Any] | None, lead: dict[str, Any]) -> str | None:
    """Texte du premier message d'un lead, selon le mode choisi. None si impossible.

    ⚠️ Le texte est rédigé MAINTENANT, au dépôt en file — jamais au moment de l'envoi.
    C'est la règle posée par ALE-174 : ce qui part est exactement ce qui a été déposé
    (et, si le client a demandé une relecture, exactement ce qu'il a relu). Générer à
    l'envoi rendrait la relecture mensongère."""
    if settings.message_mode == autopilot.MESSAGE_MODE_TEMPLATE:
        return autopilot.render_template(settings.template, lead) or None
    if settings.message_mode == autopilot.MESSAGE_MODE_AI:
        if not targeting:
            # Sans ciblage ICP, l'IA écrirait un message hors sujet. On préfère ne rien
            # proposer : un lead sans message reste contactable à la main.
            return None
        try:
            return (llm.generate_first_message(targeting, autopilot.message_context(lead)) or "").strip() or None
        except Exception as exc:  # noqa: BLE001 — un lead en échec n'arrête pas les autres
            logger.error(f"[autopilote] rédaction IA échouée (lead {lead.get('id')}) : {exc}")
            return None
    return None


def _plan_messages(account: dict[str, Any], settings: autopilot.AutopilotSettings, leads: list[dict[str, Any]]) -> int:
    """Dépose les premiers messages des leads devenus « en relation ».

    C'est le chaînon qui manquait : depuis la détection automatique d'acceptation
    (0051), un lead pouvait passer « en relation » sans que rien n'enchaîne — il
    attendait un clic humain qui ne venait pas."""
    user_id = account["user_id"]
    picked = autopilot.pick_messages(leads, settings, known_lead_ids=db.admin_queue_lead_ids(user_id, "message"))
    if not picked:
        return 0

    targeting = db.admin_get_lead_targeting(user_id) if settings.message_mode == autopilot.MESSAGE_MODE_AI else None
    status = autopilot.message_queue_status(settings)
    now = _now()
    queued = 0
    for lead in picked:
        engine.assert_same_owner(account.get("user_id"), lead.get("user_id"), context=f"auto-message lead {lead.get('id')}")
        body = _compose_message(settings, targeting, lead)
        if not body:
            continue
        # Un brouillon attend le client : lui poser un délai n'aurait pas de sens (il
        # ne partira qu'après validation). Le délai ne s'applique qu'aux envois directs.
        not_before = None if status == "draft" else (now + autopilot.pick_message_delay()).isoformat()
        if db.admin_enqueue_outreach_action(
            user_id, lead_id=lead["id"], action_type="message",
            body=body, status=status, not_before=not_before,
        ):
            queued += 1
    if queued:
        label = "brouillon(s) à valider" if status == "draft" else "message(s) déposé(s) en file"
        logger.info(f"[{user_id}] autopilote : {queued} {label}.")
    return queued


def plan_account(account: dict[str, Any]) -> int:
    """Un passage de l'autopilote sur un compte. Retourne le nombre d'actions déposées.

    Sort immédiatement si l'opt-in est absent — c'est la garantie qu'un client qui n'a
    jamais ouvert la pop-up ne verra jamais rien partir en son nom. Sort aussi pendant
    un gel : le compte est déjà en difficulté, ce n'est pas le moment de remplir sa file."""
    user_id = account.get("user_id")
    if not user_id:
        return 0
    settings = autopilot.settings_of(account)
    if not settings.enabled:
        return 0

    # Déploiement progressif : le compte doit TOUJOURS avoir la fonctionnalité. Sans ce
    # contrôle, retirer le flag à quelqu'un ne couperait pas l'autopilote qu'il a déjà
    # armé — le flag ne serait qu'un masque d'affichage, pas un interrupteur.
    #
    # Fail CLOSED : si on n'arrive pas à lire ses droits, on ne planifie rien à ce
    # passage. Sauter un tour est sans conséquence (le suivant est dans 10 min) ;
    # déposer des invitations pour un compte dont on ignore les droits, non.
    meta = db.admin_user_app_metadata(user_id)
    if meta is None:
        logger.warning(f"[{user_id}] droits illisibles — autopilote ignoré à ce passage.")
        return 0
    if not features.has_feature({"app_metadata": meta}, "autopilot"):
        return 0

    if engine.freeze_active(_now(), account):
        return 0

    leads = db.admin_list_leads_for_autopilot(user_id)
    if not leads:
        return 0
    return _plan_invites(account, settings, leads) + _plan_messages(account, settings, leads)


def process_account(account: dict[str, Any]) -> int:
    """Un passage du moteur sur un compte. Retourne le nombre d'actions envoyées.

    Trace le passage dans TOUS les cas (même quand rien ne part) : c'est la fraîcheur
    de cette date qui permet à l'app de détecter un moteur à l'arrêt."""
    user_id = account.get("user_id")
    if not user_id:
        return 0

    now = _now()

    # Gel expiré : on le lève (et on repart). Le client, lui, ne peut pas le lever —
    # ce serait son premier réflexe, au pire moment.
    if account.get("frozen") and not engine.freeze_active(now, account):
        db.admin_unfreeze_outreach_account(user_id)
        account = {**account, "frozen": False, "frozen_at": None, "freeze_reason": None}
        logger.info(f"[{user_id}] gel expiré — envois réautorisés.")

    pending = db.admin_pending_queue_count(user_id)
    if not pending:
        db.admin_record_engine_run(user_id, sent=0, error=None)
        return 0

    # Fail CLOSED : sans compteurs fiables, on n'envoie rien (un garde-fou
    # anti-restriction ne doit jamais s'effacer parce qu'une lecture a échoué).
    try:
        counts = db.admin_outreach_counts(user_id)
        counts_ok = True
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[{user_id}] compteurs de quota illisibles : {exc}")
        db.admin_record_engine_run(user_id, sent=0, error=f"Compteurs de quota illisibles : {exc}")
        return 0

    items = db.admin_due_queue_items(user_id, limit=10)
    if not items:
        db.admin_record_engine_run(user_id, sent=0, error=None)
        return 0

    sent = 0
    for _ in range(SEND_PER_TICK):
        item, decision = engine.pick_sendable(now, account, counts, items, counts_ok=counts_ok)
        if not item:
            logger.info(f"[{user_id}] rien envoyé : {decision.reason}")
            break
        if send_item(account, item):
            sent += 1
            next_at = (_now() + engine.pick_gap()).isoformat()
            db.admin_mark_outreach_sent(user_id, next_action_at=next_at)
        items = [i for i in items if i["id"] != item["id"]]
        if not items:
            break

    db.admin_record_engine_run(user_id, sent=sent, error=None)
    return sent


def run() -> None:
    if not db.admin_enabled():
        logger.warning("SUPABASE_SERVICE_ROLE_KEY absent — moteur d'envoi ignoré.")
        return
    if not unipile.enabled():
        logger.warning("UNIPILE_DSN / UNIPILE_API_KEY absents — moteur d'envoi ignoré.")
        return

    accounts = db.admin_list_outreach_accounts()
    logger.info(f"Moteur d'envoi : {len(accounts)} compte(s) de prospection connecté(s).")

    total = 0
    accepted = 0
    planned = 0
    for account in accounts:
        user_id = account.get("user_id")
        try:
            # L'ordre des trois étapes n'est pas indifférent :
            # 1. détection d'acceptation — indépendante de la file (un lead peut attendre
            #    son acceptation sans qu'aucune action ne soit en file) ;
            # 2. autopilote — planifie APRÈS, pour qu'une acceptation vue à ce passage
            #    puisse enchaîner sur son premier message dès le même passage ;
            # 3. dépilage — envoie ensuite, dans les limites du moteur.
            accepted += check_acceptances(account)
            planned += plan_account(account)
            total += process_account(account)
        except engine.OwnershipError as exc:
            # Ne devrait jamais arriver. Si ça arrive, on n'envoie rien et on hurle.
            logger.error(f"[{user_id}] CLOISONNEMENT VIOLÉ, envoi refusé : {exc}")
            db.admin_record_engine_run(user_id, sent=0, error=f"Incohérence de propriétaire : {exc}")
        except Exception as exc:  # noqa: BLE001 — un compte en échec n'arrête pas les autres
            logger.error(f"[{user_id}] passage en échec : {exc}")
            db.admin_record_engine_run(user_id, sent=0, error=str(exc))

    logger.info(
        f"Moteur d'envoi : {total} action(s) envoyée(s), {accepted} acceptation(s) détectée(s), "
        f"{planned} action(s) déposée(s) par l'autopilote."
    )


if __name__ == "__main__":
    run()
