"""ALE-174 — Moteur d'envoi cadencé : la LOGIQUE PURE (aucun I/O).

Séparé du cron (`src/outreach_sender.py`) exprès : tout ce qui décide *si* et
*quand* une action de prospection peut partir vit ici, en fonctions pures — donc
testable sans Supabase, sans Unipile et sans horloge réelle (`tests/`).

Ce que ce module protège :
- le **rythme** (délai aléatoire entre deux actions, plage horaire, jours ouvrés) ;
- l'**ancienneté du compte** (palier de warm-up : un compte neuf monte doucement) ;
- le **volume** (les plafonds d'ALE-230, repris tels quels) ;
- le compte lui-même (**gel automatique** sur restriction LinkedIn).

⚠️ Un plafond n'est PAS un cadençage : les plafonds d'ALE-230 empêchaient d'envoyer
plus de 25 invitations par jour, mais pas de les envoyer en deux minutes à 3 h du
matin le jour de la connexion du compte. C'est ce trou-là que ce module ferme.
"""
from __future__ import annotations

import datetime
import random
from dataclasses import dataclass
from typing import Any, Sequence

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - garde-fou, Render est en 3.11
    ZoneInfo = None  # type: ignore[assignment]

# ── Réglages du moteur ────────────────────────────────────────────────────────

# Palier de warm-up : nombre MAXIMUM d'actions par jour (invitations + messages
# confondus) selon l'âge du compte connecté. Au-delà de la dernière semaine listée,
# c'est le plafond configuré par l'utilisateur qui s'applique.
# Réf HeyReach : compte neuf → ~3 semaines de montée avant le régime de croisière.
WARMUP_STEPS: tuple[int, ...] = (8, 15, 20)  # semaine 1, semaine 2, semaine 3

# Délai aléatoire entre deux actions d'un même compte. Tiré à chaque envoi et posé
# sur le compte (`next_action_at`) : deux actions ne partent jamais collées, et le
# rythme n'est pas régulier (un rythme *parfaitement* régulier est aussi un signal).
MIN_GAP_MINUTES = 11
MAX_GAP_MINUTES = 37

# Soupape « envoyer maintenant » : envois immédiats autorisés par 24 h, hors file.
# Pour le cas « je sors d'une visio avec cette personne ». Ces envois comptent dans
# les plafonds comme les autres.
IMMEDIATE_DAILY_CAP = 3

# Au-delà de ce délai sans passage du moteur ALORS QU'IL RESTE des actions en file,
# l'app lève un bandeau « ta prospection est à l'arrêt ». Le cron passe toutes les
# 10 min : 40 min = 4 passages manqués, ce n'est plus un hoquet.
ENGINE_STALE_MINUTES = 40

# Durée du gel automatique après une restriction LinkedIn. Le client ne peut pas le
# lever (aucun bouton : ce serait le premier réflexe, et le pire). Il se lève seul
# une fois la période passée — un gel définitif serait une impasse, pas un garde-fou.
FREEZE_COOLDOWN_HOURS = 24

# Détection automatique de l'acceptation des invitations. Le moteur balaie les leads
# en « invitation envoyée » et bascule en « en relation » ceux qui ont accepté — sans
# ça, le lead reste bloqué tant que le client ne clique pas « Vérifier l'acceptation ».
# C'est une LECTURE (pas d'invitation/message envoyé, aucun quota consommé), mais on la
# cadence quand même : re-checker un lead en boucle taperait l'API Unipile pour rien.
ACCEPTANCE_CHECKS_PER_TICK = 5
# LinkedIn met lui-même jusqu'à ~8 h à propager l'acceptation : re-vérifier plus souvent
# ne révèle rien de nouveau. On re-checke chaque lead au plus une fois toutes les 4 h →
# l'acceptation est vue dans les ~4-8 h, pour ~6 lectures/jour/lead au pire.
ACCEPTANCE_RECHECK_HOURS = 4
# Au-delà de ce délai depuis l'envoi de l'invitation, on arrête de guetter l'acceptation :
# une invitation vieille de 3 semaines ne sera quasi jamais acceptée, et continuer à la
# re-vérifier gonflerait sans fin les appels Unipile (donc les requêtes LinkedIn du
# compte du client). Le bouton manuel reste disponible pour un cas particulier.
ACCEPTANCE_MAX_AGE_DAYS = 21

DEFAULT_TIMEZONE = "Europe/Paris"
DEFAULT_HOUR_START = 9
DEFAULT_HOUR_END = 18
DEFAULT_SEND_DAYS: tuple[int, ...] = (1, 2, 3, 4, 5)  # ISO : 1 = lundi … 7 = dimanche

# Plafonds d'ALE-230 (repris ici pour que la décision soit calculable hors API).
DAILY_CAP_DEFAULT = 25
WEEKLY_INVITE_CAP_DEFAULT = 100


class OwnershipError(Exception):
    """Une action, un lead et un compte qui n'appartiennent pas au même client.

    Ne devrait JAMAIS arriver. Si ça arrive, on refuse d'envoyer : mieux vaut une
    action en échec qu'un message du client A parti depuis le compte LinkedIn du
    client B (le moteur tourne en service-role, donc sans le cloisonnement
    automatique de la base — voir `assert_same_owner`)."""


@dataclass(frozen=True)
class Decision:
    """Verdict du moteur pour un compte à un instant donné."""

    can_send: bool
    code: str  # ok | frozen | closed | quota | warmup | gap | counts_unavailable
    reason: str | None = None


# ── Fenêtre d'envoi (heures de bureau, dans le fuseau du client) ──────────────


def _tz(account: dict[str, Any]) -> datetime.tzinfo:
    name = (account or {}).get("timezone") or DEFAULT_TIMEZONE
    if ZoneInfo is None:
        return datetime.timezone.utc
    try:
        return ZoneInfo(str(name))
    except Exception:  # noqa: BLE001 — fuseau inconnu : on ne casse pas, on retombe sur Paris
        try:
            return ZoneInfo(DEFAULT_TIMEZONE)
        except Exception:  # noqa: BLE001
            return datetime.timezone.utc


def send_days(account: dict[str, Any]) -> tuple[int, ...]:
    """Jours d'envoi (ISO 1..7). Vide/absent → jours ouvrés."""
    raw = (account or {}).get("send_days")
    if not raw:
        return DEFAULT_SEND_DAYS
    days = tuple(sorted({int(d) for d in raw if 1 <= int(d) <= 7}))
    return days or DEFAULT_SEND_DAYS


def send_hours(account: dict[str, Any]) -> tuple[int, int]:
    """Plage horaire (début, fin) en heures locales. Bornée, cohérente."""
    start = int((account or {}).get("send_hour_start") or DEFAULT_HOUR_START)
    end = int((account or {}).get("send_hour_end") or DEFAULT_HOUR_END)
    start = max(0, min(23, start))
    end = max(1, min(24, end))
    if end <= start:
        end = min(24, start + 1)
    return start, end


def in_send_window(now: datetime.datetime, account: dict[str, Any]) -> bool:
    """Sommes-nous dans la plage horaire ET un jour d'envoi du client ?"""
    local = now.astimezone(_tz(account))
    start, end = send_hours(account)
    return local.isoweekday() in send_days(account) and start <= local.hour < end


def next_window_start(now: datetime.datetime, account: dict[str, Any]) -> datetime.datetime:
    """Prochain instant où la fenêtre d'envoi s'ouvre (pour dire à l'utilisateur
    « partira demain vers 9 h » plutôt que de le laisser deviner)."""
    tz = _tz(account)
    local = now.astimezone(tz)
    start, end = send_hours(account)
    days = send_days(account)

    if local.isoweekday() in days and local.hour < start:
        candidate = local.replace(hour=start, minute=0, second=0, microsecond=0)
        return candidate.astimezone(datetime.timezone.utc)

    if local.isoweekday() in days and start <= local.hour < end:
        return now  # déjà ouvert

    # Sinon : premier jour d'envoi suivant, à l'heure d'ouverture.
    for offset in range(1, 8):
        day = local + datetime.timedelta(days=offset)
        if day.isoweekday() in days:
            candidate = day.replace(hour=start, minute=0, second=0, microsecond=0)
            return candidate.astimezone(datetime.timezone.utc)
    return now + datetime.timedelta(days=1)  # pragma: no cover — days est non vide


# ── Warm-up ───────────────────────────────────────────────────────────────────


def _parse_dt(value: Any) -> datetime.datetime | None:
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        dt = value
    else:
        try:
            dt = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def warmup_start(account: dict[str, Any]) -> datetime.datetime | None:
    """Départ du warm-up : la date explicite, sinon la connexion du compte.
    Ce repli évite tout backfill de la colonne sur les comptes déjà connectés."""
    return _parse_dt((account or {}).get("warmup_started_at")) or _parse_dt((account or {}).get("connected_at"))


def warmup_week(now: datetime.datetime, account: dict[str, Any]) -> int:
    """Semaine de warm-up en cours, 1-based. Sans date de départ connue, on est
    prudent : semaine 1 (le palier le plus bas)."""
    start = warmup_start(account)
    if not start:
        return 1
    days = max(0, (now - start).days)
    return days // 7 + 1


def warmup_cap(now: datetime.datetime, account: dict[str, Any]) -> int:
    """Plafond d'actions du jour (invitations + messages) une fois le warm-up pris
    en compte. Ne dépasse JAMAIS le plafond configuré par l'utilisateur."""
    configured = int((account or {}).get("daily_cap") or DAILY_CAP_DEFAULT)
    week = warmup_week(now, account)
    if week <= len(WARMUP_STEPS):
        return min(configured, WARMUP_STEPS[week - 1])
    return configured


# ── Décision ──────────────────────────────────────────────────────────────────


def decide(
    now: datetime.datetime,
    account: dict[str, Any],
    counts: dict[str, int],
    *,
    action_type: str,
    counts_ok: bool = True,
    ignore_pacing: bool = False,
) -> Decision:
    """Peut-on envoyer MAINTENANT une action de ce type sur ce compte ?

    L'ordre des vérifications est volontaire : on part du plus protecteur (gel) vers
    le plus circonstanciel (délai), pour que la raison affichée soit la plus utile.

    `ignore_pacing=True` : soupape « envoyer maintenant » (le client sort d'une visio
    et veut inviter cette personne tout de suite). Elle saute la plage horaire et le
    délai aléatoire — MAIS PAS le gel, ni les plafonds, ni le warm-up. Une soupape
    qui contourne les garde-fous n'est plus une soupape, c'est un trou. C'est la même
    fonction qui décide dans les deux cas, exprès : une seule source de vérité."""
    # Fail CLOSED : sans compteurs fiables, on n'envoie pas. Un garde-fou
    # anti-restriction ne doit jamais s'effacer parce qu'une lecture a échoué.
    if not counts_ok:
        return Decision(False, "counts_unavailable", "Compteurs de quota illisibles — envoi suspendu par sécurité.")

    if freeze_active(now, account):
        reason = (account or {}).get("freeze_reason") or "Compte en pause de sécurité."
        return Decision(False, "frozen", f"Envois en pause : {reason}")

    if not ignore_pacing and not in_send_window(now, account):
        return Decision(False, "closed", "Hors de la plage d'envoi (heures/jours configurés).")

    daily_cap = int((account or {}).get("daily_cap") or DAILY_CAP_DEFAULT)
    weekly_cap = int((account or {}).get("weekly_invite_cap") or WEEKLY_INVITE_CAP_DEFAULT)
    invites_today = int(counts.get("invites_today", 0))
    messages_today = int(counts.get("messages_today", 0))
    invites_week = int(counts.get("invites_week", 0))

    # Palier de warm-up : porte sur le TOTAL des actions du jour (invitations +
    # messages). Plus strict que les plafonds par type — c'est voulu : un compte
    # neuf ne doit pas faire 8 invitations ET 8 messages.
    cap_today = warmup_cap(now, account)
    if invites_today + messages_today >= cap_today:
        if cap_today < daily_cap:
            week = warmup_week(now, account)
            return Decision(
                False,
                "warmup",
                f"Palier de mise en route atteint ({cap_today} actions/jour en semaine {week}). "
                "Le compte monte en puissance progressivement.",
            )
        return Decision(False, "quota", f"Plafond du jour atteint ({cap_today} actions).")

    if action_type == "invite":
        if invites_week >= weekly_cap:
            return Decision(
                False,
                "quota",
                f"Sécurité hebdomadaire atteinte ({invites_week}/{weekly_cap} invitations sur 7 jours glissants).",
            )
        if invites_today >= daily_cap:
            return Decision(False, "quota", f"Plafond du jour atteint ({invites_today}/{daily_cap} invitations).")
    elif messages_today >= daily_cap:
        return Decision(False, "quota", f"Plafond du jour atteint ({messages_today}/{daily_cap} messages).")

    # Délai aléatoire depuis la dernière action (posé à l'envoi précédent).
    if not ignore_pacing:
        next_at = _parse_dt((account or {}).get("next_action_at"))
        if next_at and now < next_at:
            return Decision(False, "gap", "Délai entre deux actions non écoulé.")

    return Decision(True, "ok")


def pick_gap(rng: random.Random | None = None) -> datetime.timedelta:
    """Délai aléatoire jusqu'à la prochaine action autorisée."""
    r = rng or random
    return datetime.timedelta(minutes=r.randint(MIN_GAP_MINUTES, MAX_GAP_MINUTES))


def freeze_active(now: datetime.datetime, account: dict[str, Any]) -> bool:
    """Le compte est-il gelé *en ce moment* ?

    Le gel est posé par le moteur sur restriction LinkedIn et n'est PAS levable
    depuis l'interface (sinon le premier réflexe du client serait de le lever, au
    pire moment). Il expire en revanche tout seul au bout de `FREEZE_COOLDOWN_HOURS` :
    un gel définitif serait une impasse, pas un garde-fou."""
    if not (account or {}).get("frozen"):
        return False
    since = _parse_dt((account or {}).get("frozen_at"))
    if not since:
        return True  # gel sans date : on reste prudent, il tient
    return now < since + datetime.timedelta(hours=FREEZE_COOLDOWN_HOURS)


def freeze_until(account: dict[str, Any]) -> datetime.datetime | None:
    """Fin du gel en cours (pour l'afficher au client), ou None."""
    since = _parse_dt((account or {}).get("frozen_at"))
    if not (account or {}).get("frozen") or not since:
        return None
    return since + datetime.timedelta(hours=FREEZE_COOLDOWN_HOURS)


def estimate_send_at(now: datetime.datetime, account: dict[str, Any]) -> datetime.datetime:
    """Créneau plausible de la prochaine action — pour dire au client « partira
    aujourd'hui vers 14 h » au lieu de le laisser deviner.

    Estimation volontairement optimiste (elle ignore le nombre d'actions déjà en
    file devant) : elle sert à rassurer, pas à contractualiser. Le moteur reste seul
    juge à l'exécution."""
    at = now
    gap_end = _parse_dt((account or {}).get("next_action_at"))
    if gap_end and gap_end > at:
        at = gap_end
    frozen_end = freeze_until(account) if freeze_active(now, account) else None
    if frozen_end and frozen_end > at:
        at = frozen_end
    if not in_send_window(at, account):
        at = next_window_start(at, account)
    return at


# ── Gel automatique ───────────────────────────────────────────────────────────

# Signatures d'erreur Unipile/LinkedIn qui veulent dire « ce compte est en train de
# se faire taper sur les doigts ». On ne réessaie pas : on gèle et on prévient.
_RESTRICTION_MARKERS = (
    "limit",           # "invitation limit reached", "rate limit"
    "restrict",        # "account restricted"
    "too many",
    "quota",
    "blocked",
    "checkpoint",      # LinkedIn demande une vérification
    "captcha",
    "suspended",
    "cannot_resend_yet",
)


def is_restriction_error(message: str | None) -> bool:
    """Cette erreur Unipile signale-t-elle une limite / restriction LinkedIn ?
    Si oui, l'appelant gèle le compte (plutôt que de continuer à taper)."""
    if not message:
        return False
    low = str(message).lower()
    return any(marker in low for marker in _RESTRICTION_MARKERS)


# ── Cloisonnement multi-client ────────────────────────────────────────────────


def assert_same_owner(*owners: Any, context: str = "") -> str:
    """Toutes ces lignes appartiennent-elles au MÊME client ? Sinon on lève.

    ⚠️ Garde-fou central du moteur. Le cron tourne en service-role : la base ne
    cloisonne plus rien pour nous (contrairement aux appels portant le jeton d'un
    utilisateur, où la RLS refuse d'elle-même les lignes des autres). Une confusion
    de propriétaire enverrait le message du client A depuis le compte LinkedIn du
    client B — silencieusement, sans erreur côté Unipile. D'où cette vérification
    juste avant l'appel réseau, en plus du filtrage par `user_id` de chaque requête.
    """
    ids = [str(o) for o in owners if o]
    if len(ids) != len(owners) or not ids:
        raise OwnershipError(f"Propriétaire manquant ({context or 'action de prospection'}).")
    if len(set(ids)) != 1:
        raise OwnershipError(
            f"Incohérence de propriétaire ({context or 'action de prospection'}) : {sorted(set(ids))}."
        )
    return ids[0]


# ── Observabilité ─────────────────────────────────────────────────────────────


def is_stalled(
    now: datetime.datetime,
    last_run_at: Any,
    pending_count: int,
    *,
    stale_minutes: int = ENGINE_STALE_MINUTES,
) -> bool:
    """Le moteur est-il à l'arrêt alors qu'il a du travail ?

    Un cron mort ne peut pas alerter sur sa propre mort : c'est donc l'app (qui,
    elle, tourne) qui le détecte, en regardant la date du dernier passage. Sans
    ça, le client croit que sa prospection avance et rien ne part pendant des jours
    (déjà vu sur ce projet avec le cron de publication)."""
    if pending_count <= 0:
        return False
    last = _parse_dt(last_run_at)
    if not last:
        return True
    return (now - last) > datetime.timedelta(minutes=stale_minutes)


def pick_sendable(
    now: datetime.datetime,
    account: dict[str, Any],
    counts: dict[str, int],
    items: Sequence[dict[str, Any]],
    *,
    counts_ok: bool = True,
) -> tuple[dict[str, Any] | None, Decision]:
    """Première action de la file qu'on a le droit d'envoyer maintenant.

    On parcourt les actions dues dans l'ordre : si la plus ancienne est un message
    et que les messages sont au plafond, on ne bloque pas toute la file pour autant —
    une invitation encore autorisée peut passer devant. La dernière raison de refus
    rencontrée est renvoyée pour être tracée telle quelle."""
    last = Decision(False, "quota", "Aucune action envoyable pour le moment.")
    for item in items:
        decision = decide(now, account, counts, action_type=str(item.get("action_type")), counts_ok=counts_ok)
        if decision.can_send:
            return item, decision
        last = decision
        # Ces trois-là ne dépendent pas du type d'action : inutile d'essayer les suivantes.
        if decision.code in ("frozen", "closed", "gap", "counts_unavailable", "warmup"):
            break
    return None, last


def pick_acceptance_checks(
    now: datetime.datetime,
    leads: Sequence[dict[str, Any]],
    *,
    limit: int = ACCEPTANCE_CHECKS_PER_TICK,
    recheck_hours: float = ACCEPTANCE_RECHECK_HOURS,
    max_age_days: float = ACCEPTANCE_MAX_AGE_DAYS,
) -> list[dict[str, Any]]:
    """Parmi les leads en attente d'acceptation, ceux à re-vérifier à ce passage.

    Trois garde-fous : on abandonne les invitations parties depuis plus de
    `max_age_days` jours (une invitation de 3 semaines ne sera quasi jamais acceptée,
    la re-guetter ne fait que gonfler les appels) ; on ne re-checke pas un lead vérifié
    il y a moins de `recheck_hours` heures (le signal LinkedIn met jusqu'à ~8 h à se
    propager) ; et on plafonne à `limit` leads par passage. Les leads jamais vérifiés —
    ou vérifiés le plus anciennement — passent en premier, pour qu'aucun ne soit affamé.

    L'âge de l'invitation se lit sur `outreach_updated_at` (posé à l'envoi et inchangé
    tant que le lead reste « invitation envoyée »). Un lead sans cette date n'est jamais
    abandonné (on préfère le vérifier que le perdre).

    Fonction PURE : l'appelant a déjà filtré sur `outreach_status = 'invite_sent'` ;
    ici on ne décide que du rythme.
    """
    if limit <= 0:
        return []
    recheck_cutoff = now - datetime.timedelta(hours=recheck_hours)
    age_cutoff = now - datetime.timedelta(days=max_age_days)
    epoch = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    due: list[dict[str, Any]] = []
    for lead in leads:
        invited = _parse_dt(lead.get("outreach_updated_at"))
        if invited is not None and invited < age_cutoff:
            continue  # invitation trop ancienne : on cesse de guetter
        checked = _parse_dt(lead.get("outreach_last_checked_at"))
        if checked is None or checked <= recheck_cutoff:
            due.append(lead)
    due.sort(key=lambda lead: _parse_dt(lead.get("outreach_last_checked_at")) or epoch)
    return due[:limit]
