"""ALE-284 — Autopilote de prospection : la LOGIQUE PURE (aucun I/O).

Même découpage que le moteur d'envoi (`src/outreach_engine.py`), et pour la même
raison : tout ce qui décide **qui** l'app va contacter en son nom, et **quoi** elle
va lui écrire, doit être lisible et testable sans Supabase, sans Unipile et sans
horloge réelle. Le cron (`src/outreach_sender.py`) n'orchestre que des appels.

Ce que ce module décide :
- quels leads méritent une invitation automatique (seuil de score ICP, curation,
  état d'outreach, plafond quotidien d'invitations auto) ;
- quels leads fraîchement passés « en relation » méritent un premier message ;
- le texte de ce message quand il vient d'un template (substitution des variables) ;
- s'il part en file (`pending`) ou en brouillon à relire (`draft`).

⚠️ Ce que ce module ne fait PAS, volontairement : envoyer. L'autopilote ne fait que
**déposer** des actions dans la file d'ALE-174. C'est ce qui lui fait hériter
gratuitement du warm-up, de la plage horaire, du délai aléatoire, des plafonds durs
et du gel automatique. Un autopilote qui appellerait Unipile en direct contournerait
tous les garde-fous anti-restriction — c'est la contrainte d'architecture n°1.
"""
from __future__ import annotations

import datetime
import random
import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

# ── Paliers de score ICP ──────────────────────────────────────────────────────
#
# Ces deux seuils ne sont pas arbitraires : ce sont EXACTEMENT ceux des pastilles
# de couleur déjà affichées sur la liste de leads (frontend `scoreColor`). Si
# « vert » dans la pop-up d'autopilote ne désignait pas les mêmes leads que les
# pastilles vertes que le client a sous les yeux, il réglerait son autopilote sur
# autre chose que ce qu'il croit voir. Toute modification doit être faite des deux
# côtés en même temps.
GREEN_MIN_SCORE = 70   # « correspond vraiment à ton client idéal »
ORANGE_MIN_SCORE = 40  # « plausible, à creuser »

# Les trois choix offerts par la pop-up, du plus prudent au plus large.
TIER_GREEN = "green"
TIER_ORANGE = "orange"
TIER_ALL = "all"

TIER_MIN_SCORE: dict[str, int] = {
    TIER_GREEN: GREEN_MIN_SCORE,   # vert seul
    TIER_ORANGE: ORANGE_MIN_SCORE,  # vert + orange
    TIER_ALL: 0,                    # tout le monde, y compris hors cible
}

# ── Modes de message ──────────────────────────────────────────────────────────

MESSAGE_MODE_NONE = "none"          # demande de connexion seule
MESSAGE_MODE_AI = "ai"              # rédigé par l'IA, lead par lead
MESSAGE_MODE_TEMPLATE = "template"  # texte du client, variables substituées
MESSAGE_MODES = (MESSAGE_MODE_NONE, MESSAGE_MODE_AI, MESSAGE_MODE_TEMPLATE)

# Délai entre l'acceptation de l'invitation et la mise en file du premier message.
# Écrire trois minutes après l'acceptation est un signal de robot aussi net qu'un
# rythme régulier : personne ne surveille ses acceptations en temps réel. Le tirage
# est large exprès, et le moteur d'ALE-174 recalera de toute façon l'envoi dans la
# plage horaire du client.
MIN_MESSAGE_DELAY_HOURS = 3
MAX_MESSAGE_DELAY_HOURS = 20

# Longueur maximale d'un message LinkedIn accepté par l'API d'envoi (api.py borne
# déjà les envois manuels à 1500 caractères — on tient la même limite).
MESSAGE_MAX_CHARS = 1500

# Variables reconnues dans un template, et le champ du lead qui les remplit.
# Tolérant à la casse et aux espaces : `{{ Prenom }}` marche comme `{{prenom}}`.
_TEMPLATE_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_]+)\s*\}\}")


@dataclass(frozen=True)
class AutopilotSettings:
    """Réglages de l'autopilote, normalisés depuis la ligne de compte."""

    enabled: bool
    min_score: int
    daily_invite_cap: int
    message_mode: str
    template: str
    requires_validation: bool

    @property
    def sends_message(self) -> bool:
        return self.message_mode in (MESSAGE_MODE_AI, MESSAGE_MODE_TEMPLATE)

    @property
    def tier(self) -> str:
        return tier_for_min_score(self.min_score)


# ── Paliers : conversions dans les deux sens ──────────────────────────────────


def tier_of(score: int | None) -> str | None:
    """Palier de couleur d'un lead. `None` si le lead n'a pas encore été noté."""
    if score is None:
        return None
    if score >= GREEN_MIN_SCORE:
        return TIER_GREEN
    if score >= ORANGE_MIN_SCORE:
        return TIER_ORANGE
    return "red"


def min_score_for_tier(tier: str | None) -> int:
    """Seuil de score correspondant à un choix de la pop-up. Défaut = le plus prudent."""
    return TIER_MIN_SCORE.get((tier or "").strip().lower(), GREEN_MIN_SCORE)


def tier_for_min_score(min_score: int | None) -> str:
    """Choix de la pop-up correspondant à un seuil stocké (l'inverse du précédent).

    Le seuil est stocké en entier pour rester lisible en base et permettre un réglage
    fin plus tard ; l'interface, elle, n'offre que trois valeurs."""
    value = int(min_score or 0)
    if value >= GREEN_MIN_SCORE:
        return TIER_GREEN
    if value >= ORANGE_MIN_SCORE:
        return TIER_ORANGE
    return TIER_ALL


def settings_of(account: dict[str, Any] | None) -> AutopilotSettings:
    """Lit les réglages d'autopilote d'un compte, en refusant toute valeur douteuse.

    Tout ce qui n'est pas explicitement compris retombe sur le choix le plus prudent :
    un réglage illisible ne doit jamais élargir la cible ni supprimer la relecture."""
    acc = account or {}
    mode = str(acc.get("auto_message_mode") or MESSAGE_MODE_NONE).strip().lower()
    if mode not in MESSAGE_MODES:
        mode = MESSAGE_MODE_NONE

    template = str(acc.get("auto_message_template") or "").strip()
    # Un template vide ne peut rien produire : plutôt que d'enfiler des messages vides
    # (que le moteur rejetterait un par un en « Message vide »), on retombe sur
    # « invitation seule ». Le client verra le schéma de séquence le lui dire.
    if mode == MESSAGE_MODE_TEMPLATE and not template:
        mode = MESSAGE_MODE_NONE

    raw_validation = acc.get("auto_message_requires_validation")
    requires_validation = True if raw_validation is None else bool(raw_validation)

    return AutopilotSettings(
        enabled=bool(acc.get("auto_prospection_enabled")),
        min_score=max(0, min(100, int(acc.get("auto_invite_min_score") or 0))),
        daily_invite_cap=max(0, min(50, int(acc.get("auto_invite_daily_cap") or 0))),
        message_mode=mode,
        template=template,
        requires_validation=requires_validation,
    )


# ── Éligibilité des leads ─────────────────────────────────────────────────────


def _is_skipped(lead: dict[str, Any]) -> bool:
    """Lead écarté à la main par le client (ALE-243) — l'autopilote ne le touche jamais."""
    return str(lead.get("contact_status") or "to_contact") == "skip"


def _outreach_status(lead: dict[str, Any]) -> str:
    return str(lead.get("outreach_status") or "none")


def _score(lead: dict[str, Any]) -> int | None:
    raw = lead.get("score")
    return None if raw is None else int(raw)


def is_invite_candidate(lead: dict[str, Any], settings: AutopilotSettings) -> bool:
    """Ce lead mérite-t-il une invitation automatique ?

    ⚠️ Un lead **non noté** n'est jamais invité automatiquement, même en mode « tous ».
    Sans score, on ne sait rien de son adéquation : l'inviter reviendrait à faire
    exactement ce que le ciblage ICP sert à éviter. Il reste invitable à la main, et
    redeviendra candidat dès qu'il aura été noté."""
    if _is_skipped(lead):
        return False
    if _outreach_status(lead) != "none":
        return False
    score = _score(lead)
    if score is None:
        return False
    return score >= settings.min_score


def is_message_candidate(lead: dict[str, Any], settings: AutopilotSettings) -> bool:
    """Ce lead, désormais en relation, mérite-t-il un premier message automatique ?

    Le filtre de score s'applique ici AUSSI, y compris pour un lead invité à la main :
    le client a choisi à qui son autopilote écrit, et un lead hors palier ne doit pas
    récupérer un message automatique par la bande."""
    if not settings.sends_message:
        return False
    if _is_skipped(lead):
        return False
    if _outreach_status(lead) != "connected":
        return False
    score = _score(lead)
    if score is None:
        return False
    return score >= settings.min_score


def pick_invites(
    leads: Sequence[dict[str, Any]],
    settings: AutopilotSettings,
    *,
    known_lead_ids: Iterable[str] = (),
    remaining_cap: int,
) -> list[dict[str, Any]]:
    """Leads à inviter à ce passage, les mieux notés d'abord.

    `known_lead_ids` = leads ayant DÉJÀ une invitation connue de la file (quel que soit
    son statut : en attente, envoyée, échouée, annulée). On ne repropose jamais une
    invitation pour un lead déjà passé par là — sans ça, une invitation annulée par le
    client reviendrait au passage suivant, en boucle."""
    if not settings.enabled or remaining_cap <= 0:
        return []
    known = {str(x) for x in known_lead_ids}
    picked = [
        lead for lead in leads
        if str(lead.get("id")) not in known and is_invite_candidate(lead, settings)
    ]
    # Le meilleur score d'abord : si le plafond quotidien mord, il doit mordre sur les
    # leads les moins bons, jamais sur les meilleurs.
    picked.sort(key=lambda l: (-(_score(l) or 0), str(l.get("created_at") or "")))
    return picked[:remaining_cap]


def pick_messages(
    leads: Sequence[dict[str, Any]],
    settings: AutopilotSettings,
    *,
    known_lead_ids: Iterable[str] = (),
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Leads en relation à qui proposer un premier message.

    `known_lead_ids` = leads ayant déjà un message connu de la file (tous statuts, y
    compris `draft` et `canceled`). L'autopilote ne propose qu'UNE fois : un brouillon
    refusé par le client ne doit pas réapparaître au passage suivant."""
    if not settings.enabled or not settings.sends_message:
        return []
    known = {str(x) for x in known_lead_ids}
    picked = [
        lead for lead in leads
        if str(lead.get("id")) not in known and is_message_candidate(lead, settings)
    ]
    picked.sort(key=lambda l: (-(_score(l) or 0), str(l.get("outreach_updated_at") or "")))
    return picked[:limit]


# ── Rédaction du message ──────────────────────────────────────────────────────


def first_name_of(lead: dict[str, Any]) -> str:
    """Prénom du lead. Chaîne vide si le nom est inconnu — jamais « None » dans le texte."""
    name = str(lead.get("name") or "").strip()
    if not name:
        return ""
    return name.split()[0]


def template_variables(lead: dict[str, Any]) -> dict[str, str]:
    name = str(lead.get("name") or "").strip()
    return {
        "prenom": first_name_of(lead),
        "nom": name,
        "titre": str(lead.get("headline") or "").strip(),
    }


def render_template(template: str, lead: dict[str, Any]) -> str:
    """Substitue les variables d'un template avec les données du lead.

    Une variable inconnue ou vide est remplacée par du vide, puis les espaces et les
    lignes en trop sont resserrés : un template « Bonjour {{prenom}}, » sur un lead
    sans nom doit donner « Bonjour, » — pas « Bonjour {{prenom}}, » (qui partirait tel
    quel chez le prospect) ni « Bonjour None, »."""
    values = template_variables(lead)

    def _sub(match: re.Match[str]) -> str:
        return values.get(match.group(1).strip().lower(), "")

    text = _TEMPLATE_VAR_RE.sub(_sub, template or "")
    # Resserrage après substitution. ⚠️ On ne touche QU'À la virgule et au point :
    # en français, « ! », « ? », « ; » et « : » veulent une espace AVANT. La coller
    # produirait « Bonjour Camille! », qui fait négligé dans un message de prospection
    # envoyé au nom du client.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([,.])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MESSAGE_MAX_CHARS]


def template_is_usable(template: str) -> bool:
    """Un template qui ne produirait jamais de texte ne doit pas être enregistré."""
    return bool((template or "").strip())


def message_context(lead: dict[str, Any]) -> dict[str, Any]:
    """Contexte passé à `llm.generate_first_message` pour rédiger le premier message.

    Défini ICI et pas dans `api.py` parce que deux chemins l'utilisent désormais :
    l'aperçu demandé à la main depuis le panneau du lead, et le planificateur de
    l'autopilote. S'ils divergeaient, le message relu en aperçu ne serait pas celui
    que l'autopilote enverrait — le genre d'écart qu'on ne remarque jamais avant
    qu'un client s'en plaigne."""
    signals = lead.get("signals") or []
    last = signals[-1] if signals else {}
    return {
        "name": lead.get("name"),
        "headline": lead.get("headline"),
        "comment_text": lead.get("comment_text"),
        "trigger_keyword": last.get("trigger_keyword"),
        "author": last.get("author"),
    }


# ── Dépôt en file ─────────────────────────────────────────────────────────────


def message_queue_status(settings: AutopilotSettings) -> str:
    """Statut du message déposé : brouillon à relire, ou directement en file.

    ⚠️ C'est ici que se joue la garantie de sécurité du lot : `draft` est un statut que
    le moteur d'envoi ne lit PAS (`db.admin_due_queue_items` filtre `status='pending'`).
    Un message en attente de relecture est donc structurellement inenvoyable, et pas
    seulement « pas encore envoyé »."""
    return "draft" if settings.requires_validation else "pending"


def pick_message_delay(rng: random.Random | None = None) -> datetime.timedelta:
    """Délai avant la mise en file du premier message (voir MIN/MAX_MESSAGE_DELAY_HOURS)."""
    r = rng or random
    minutes = r.randint(MIN_MESSAGE_DELAY_HOURS * 60, MAX_MESSAGE_DELAY_HOURS * 60)
    return datetime.timedelta(minutes=minutes)


def sequence_steps(settings: AutopilotSettings) -> list[dict[str, Any]]:
    """Le schéma de séquence affiché à côté du bouton Autopilote.

    Calculé côté serveur exprès : c'est la MÊME source que le comportement réel du
    planificateur. Un schéma reconstruit à part dans le frontend finirait par mentir le
    jour où une règle change ici — et un client qui croit relire ses messages alors
    qu'ils partent seuls, c'est le pire bug possible de cette fonctionnalité."""
    tier_labels = {
        TIER_GREEN: "leads verts",
        TIER_ORANGE: "leads verts et orange",
        TIER_ALL: "tous les leads",
    }
    steps: list[dict[str, Any]] = [
        {
            "key": "invite",
            "label": "Demande de connexion",
            "detail": f"Aux {tier_labels[settings.tier]}",
            "active": settings.enabled,
        }
    ]

    if settings.message_mode == MESSAGE_MODE_AI:
        write_detail = "Rédigé par l'IA pour chaque lead"
    elif settings.message_mode == MESSAGE_MODE_TEMPLATE:
        write_detail = "Ton template, personnalisé"
    else:
        write_detail = "Aucun message prévu"
    steps.append({
        "key": "compose",
        "label": "Premier message",
        "detail": write_detail,
        "active": settings.enabled and settings.sends_message,
    })

    if not settings.sends_message:
        send_detail = "Aucun message prévu"
    elif settings.requires_validation:
        send_detail = "Après ta relecture"
    else:
        send_detail = "Envoi sans relecture"
    steps.append({
        "key": "send",
        "label": "Envoi du message",
        "detail": send_detail,
        "active": settings.enabled and settings.sends_message,
        # Nuance importante : l'étape est bien active, mais elle attend le client.
        # Le schéma la marque d'un liseré au lieu d'un plein, sinon « relecture » et
        # « envoi automatique » se ressembleraient à l'écran.
        "awaits_user": settings.enabled and settings.sends_message and settings.requires_validation,
    })
    return steps
