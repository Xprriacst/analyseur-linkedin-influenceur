"""Mode Pilote — composition du plan du jour (lecture seule, sans LLM ni Apify)
et plan « Pilote gratuit » (quotas 1 post/jour, 3 contacts/jour)."""
from __future__ import annotations

import datetime
import os
import re
from typing import Any
from urllib.parse import unquote

from src import db

PILOT_CONTACT_LIMIT = 3
PILOT_FOLLOW_LIMIT = 5
PILOT_WEEKLY_TOTAL = 3


# --------------------------------------------------------------------------- #
# Plan « Pilote gratuit » (décision Alex 2026-09-01)
#
# Le gratuit = le Mode Pilote plafonné (1 post / jour, jusqu'à 3 contacts / jour).
# Le mode Expert (l'app complète) est payant : visible mais grisé pour ces comptes.
# Remplace « essai 7 j + 1000 crédits » pour les nouveaux inscrits de la landing.
#
# ⚠️ Où vit le plan : dans **`app_metadata.plan`**, JAMAIS `user_metadata` — le
# client peut éditer `user_metadata` depuis son navigateur (`supabase.auth.updateUser`),
# et c'est précisément là que la landing écrit `landing='pilote'` (compteur funnel).
# Ce tag NE doit JAMAIS ouvrir un droit : la seule source du plan est `app_metadata`,
# écrivable uniquement en service-role (même patron que `src/features.py` et le rôle
# `ideas_only`).
#
# Défaut (plan absent) = comportement historique intact : crédits de bienvenue,
# essai, abonnés Stripe, comptes agence — RIEN ne change pour l'existant. Les
# quotas ne s'appliquent qu'aux comptes explicitement `plan='pilot_free'`.
# --------------------------------------------------------------------------- #

PLAN_PILOT_FREE = "pilot_free"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


# Quotas quotidiens (fenêtre glissante de 24 h, calculée depuis les données
# existantes — patron des compteurs outreach : aucun compteur à réinitialiser).
# Surchargeables par env sans release, comme les autres plafonds du repo.
PILOT_FREE_POSTS_PER_DAY = _env_int("PILOT_FREE_POSTS_PER_DAY", 1)
# ⚠️ Aligné sur PILOT_CONTACT_LIMIT : le rail « À contacter » du plan du jour
# montre exactement le nombre de contacts que le quota autorise. Les faire
# diverger montrerait au client des contacts qu'il n'a pas le droit d'inviter.
PILOT_FREE_LEADS_PER_DAY = _env_int("PILOT_FREE_LEADS_PER_DAY", PILOT_CONTACT_LIMIT)

# Fenêtre d'attribution du plan à l'inscription : passé ce délai, un compte
# existant ne peut plus basculer seul en Pilote gratuit (il garde le modèle
# historique — crédits de bienvenue puis abonnement/essai).
PILOT_ENROLL_WINDOW_HOURS = _env_int("PILOT_ENROLL_WINDOW_HOURS", 48)

_UPGRADE_HINT = "Passe en mode Expert (abonnement) pour continuer sans attendre."


def plan_of(user: dict[str, Any] | None) -> str | None:
    """Plan du compte, lu depuis `app_metadata` UNIQUEMENT.

    `user_metadata` n'est jamais consulté : il est modifiable par l'utilisateur
    lui-même, il ne peut ni ouvrir ni fermer un droit. Absent/illisible → None
    (= comportement historique, pas de quota)."""
    meta = (user or {}).get("app_metadata") or {}
    if not isinstance(meta, dict):
        return None
    plan = meta.get("plan")
    if isinstance(plan, str) and plan.strip():
        return plan.strip().lower()
    return None


def is_pilot_free(user: dict[str, Any] | None) -> bool:
    """Ce compte est-il au plan Pilote gratuit ? None/illisible → non (historique)."""
    return plan_of(user) == PLAN_PILOT_FREE


def post_quota_error(used_today: int, requested: int = 1,
                     limit: int | None = None) -> str | None:
    """None si la génération est autorisée ; sinon le message d'erreur (402).

    Fonction pure (patron décide/exécute) : le comptage vit dans `src/db.py`,
    la décision ici — testable sans base ni réseau."""
    cap = PILOT_FREE_POSTS_PER_DAY if limit is None else limit
    requested = max(1, int(requested or 1))
    if int(used_today) + requested <= cap:
        return None
    if cap <= 1:
        return (
            "Mode Pilote : ton post du jour est déjà généré (1/1 sur 24 h). "
            "Reviens demain pour le suivant. " + _UPGRADE_HINT
        )
    return (
        f"Mode Pilote : {cap} posts par jour ({used_today}/{cap} sur 24 h). "
        "Reviens demain. " + _UPGRADE_HINT
    )


def lead_quota_error(used_today: int, limit: int | None = None) -> str | None:
    """None si l'invitation est autorisée ; sinon le message d'erreur (402)."""
    cap = PILOT_FREE_LEADS_PER_DAY if limit is None else limit
    if int(used_today) < cap:
        return None
    return (
        f"Mode Pilote : {cap} contacts par jour ({used_today}/{cap} sur 24 h). "
        "Reviens demain pour les suivants. " + _UPGRADE_HINT
    )


def can_enroll_pilot_free(
    *,
    current_plan: str | None,
    has_subscription: bool,
    created_at: str | None,
    now: datetime.datetime | None = None,
    window_hours: int | None = None,
) -> tuple[str, str | None]:
    """L'attribution du plan `pilot_free` est-elle permise pour ce compte ?

    Retourne ``(statut, message)`` avec statut ∈ {"ok", "already", "refused"}.
    Fonction pure : l'endpoint lit l'état (plan, abonnement, date de création)
    et applique la décision.

    Garde-fous — l'endpoint est appelable par le compte lui-même (c'est le point
    de branchement de la landing /pilote, juste après le signUp), donc il ne doit
    JAMAIS servir d'échappatoire à un compte existant :
    - un plan déjà posé (autre que pilot_free) ne se remplace pas ;
    - un compte qui a déjà touché à l'abonnement/essai Stripe reste sur le modèle
      historique ;
    - passé `PILOT_ENROLL_WINDOW_HOURS` après la création, refus — le plan se pose
      à l'inscription, pas des mois plus tard ;
    - date de création absente/illisible → refus (fail closed)."""
    if current_plan == PLAN_PILOT_FREE:
        return "already", None
    if current_plan:
        return "refused", "Un plan est déjà posé sur ce compte."
    if has_subscription:
        return "refused", "Ce compte a déjà un abonnement ou un essai — le plan Pilote gratuit est réservé aux nouveaux comptes."
    window = PILOT_ENROLL_WINDOW_HOURS if window_hours is None else window_hours
    if not created_at:
        return "refused", "Date de création du compte illisible — attribution refusée."
    try:
        created = datetime.datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return "refused", "Date de création du compte illisible — attribution refusée."
    if created.tzinfo is None:
        created = created.replace(tzinfo=datetime.timezone.utc)
    ref = now or datetime.datetime.now(datetime.timezone.utc)
    if ref - created > datetime.timedelta(hours=window):
        return "refused", "Le plan Pilote gratuit se choisit à l'inscription — ce compte est trop ancien."
    return "ok", None

_PILOT_ACCENTS = (
    "linear-gradient(135deg, #6366f1, #4338ca)",
    "linear-gradient(135deg, #ec4899, #be185d)",
    "linear-gradient(135deg, #0ea5e9, #0369a1)",
    "linear-gradient(135deg, #10b981, #047857)",
    "linear-gradient(135deg, #f59e0b, #d97706)",
)

_INVITABLE_OUTREACH = frozenset({None, "", "none"})


def initials(name: str | None, fallback: str = "?") -> str:
    parts = (name or "").strip().split()
    if not parts:
        return fallback[:2].upper() or "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return ((parts[0][:1] or "") + (parts[1][:1] or "")).upper() or "?"


def first_name(name: str | None) -> str:
    part = (name or "").strip().split()
    return part[0] if part else "Bonjour"


def score_tier(score: int | None) -> str | None:
    if score is None:
        return None
    if score >= 70:
        return "green"
    if score >= 40:
        return "orange"
    return "red"


def lead_invitable(lead: dict[str, Any]) -> bool:
    if lead.get("contact_status") == "skip":
        return False
    score = lead.get("score")
    if score is None:
        return False
    if score_tier(int(score)) not in ("green", "orange"):
        return False
    status = (lead.get("outreach_status") or "none").strip().lower()
    return status in _INVITABLE_OUTREACH


def pick_contacts(leads: list[dict[str, Any]], limit: int = PILOT_CONTACT_LIMIT) -> list[dict[str, Any]]:
    """Jusqu'à ``limit`` leads scorés verts/oranges, jamais contactés ni écartés."""
    picked: list[dict[str, Any]] = []
    for lead in leads:
        if not lead_invitable(lead):
            continue
        picked.append(lead)
        if len(picked) >= limit:
            break
    return picked


def pick_follow_profiles(
    library: list[dict[str, Any]],
    followed_handles: set[str],
    limit: int = PILOT_FOLLOW_LIMIT,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, row in enumerate(library):
        handle = (row.get("handle") or "").strip()
        if not handle or handle in followed_handles:
            continue
        headline = (row.get("headline") or "").strip()
        reason = (
            f"{headline} — repéré dans ton analyse."
            if headline
            else "Influenceur repéré dans ton analyse LinkedIn."
        )
        rows.append({
            "id": row.get("influencer_id") or handle,
            "name": (row.get("name") or handle).strip(),
            "handle": f"@{handle}",
            "reason": reason,
            "initials": initials(row.get("name"), handle[:2].upper()),
            "accent": _PILOT_ACCENTS[len(rows) % len(_PILOT_ACCENTS)],
            "influencer_handle": handle,
        })
        if len(rows) >= limit:
            break
    return rows


def contact_message_preview(lead: dict[str, Any], targeting: dict[str, Any] | None) -> str:
    """Aperçu court sans appel LLM — le vrai message IA reste sur Prospection."""
    name = first_name(lead.get("name"))
    offer = (targeting or {}).get("offer") or (targeting or {}).get("ideal_client") or "ton activité"
    comment = (lead.get("comment_text") or "").strip()
    if comment:
        excerpt = comment[:72].rstrip()
        if len(comment) > 72:
            excerpt += "…"
        return (
            f"Bonjour {name} — j'ai lu ton commentaire (« {excerpt} »). "
            f"Curieux d'échanger 15 min sur {offer} ?"
        )
    headline = (lead.get("headline") or "").strip()
    if headline:
        return (
            f"Bonjour {name} — ton profil ({headline}) correspond à ce que je cible. "
            f"On échange rapidement sur {offer} ?"
        )
    return f"Bonjour {name} — ton profil correspond à mon ICP. Curieux d'échanger 15 min ?"


def split_post_text(text: str) -> tuple[str, str]:
    """Découpe hook (1re phrase/ligne) + corps."""
    raw = (text or "").strip()
    if not raw:
        return "", ""
    parts = re.split(r"\n\s*\n", raw, maxsplit=1)
    if len(parts) == 2:
        hook = parts[0].strip()
        body = parts[1].strip()
        return hook, body
    sentences = re.split(r"(?<=[.!?])\s+", raw, maxsplit=1)
    if len(sentences) == 2 and len(sentences[0]) <= 220:
        return sentences[0].strip(), sentences[1].strip()
    lines = raw.splitlines()
    if len(lines) >= 2:
        return lines[0].strip(), "\n".join(lines[1:]).strip()
    return raw[:180].strip(), raw[180:].strip() if len(raw) > 180 else ""


def format_weekly_frequency(slots: list[dict[str, Any]]) -> str:
    if not slots:
        return "Aucun créneau programmé — règle ton rythme dans Mon profil."
    day_labels = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
    parts: list[str] = []
    for slot in sorted(slots, key=lambda s: int(s.get("day_of_week") or 0)):
        try:
            dow = int(slot.get("day_of_week", 0))
            hour = int(slot.get("hour", 9))
        except (TypeError, ValueError):
            continue
        if 0 <= dow < len(day_labels):
            parts.append(f"{day_labels[dow]} {hour}h")
    if not parts:
        return "Aucun créneau programmé — règle ton rythme dans Mon profil."
    return f"{len(slots)} posts / semaine · {', '.join(parts)}"


def strategy_target(profile: dict[str, Any] | None, targeting: dict[str, Any] | None) -> str:
    ideal = (targeting or {}).get("ideal_client") or (profile or {}).get("target_audience")
    offer = (targeting or {}).get("offer") or (profile or {}).get("core_offer")
    bits = [b for b in (ideal, offer) if b]
    if bits:
        return " · ".join(str(b).strip() for b in bits)
    return "Complète ton ciblage ICP dans Mon profil → Prospection."


def strategy_structure_hint(profile: dict[str, Any] | None) -> str:
    tone = (profile or {}).get("tone")
    objective = (profile or {}).get("linkedin_objective")
    if tone and objective:
        return f"{tone} — objectif : {objective}"
    if tone:
        return str(tone)
    if objective:
        return str(objective)
    return "Récit personnel + insight actionnable + question ouverte"


def pick_post_of_day(
    generated: list[dict[str, Any]],
    daily_ideas: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    """Retourne (source_row, source_kind) avec kind in generated|daily_idea|None."""
    for row in generated:
        if row.get("platform") not in (None, "", "linkedin"):
            continue
        if row.get("zernio_post_id"):
            continue
        text = (row.get("post") or "").strip()
        if text:
            return row, "generated"
    today = datetime.date.today().isoformat()
    for row in daily_ideas:
        if (row.get("idea_date") or "")[:10] == today:
            text = (row.get("idea_markdown") or row.get("post_text") or row.get("idea") or "").strip()
            if text:
                return row, "daily_idea"
    for row in daily_ideas:
        text = (row.get("idea_markdown") or row.get("post_text") or row.get("idea") or "").strip()
        if text:
            return row, "daily_idea"
    return None, None


def weekly_progress(access_token: str) -> tuple[int, int]:
    """Objectif hebdo simplifié : publication + invitations (max 3 points)."""
    done = 0
    try:
        counts = db.outreach_counts(access_token)
        done += min(2, int(counts.get("invites_week") or 0))
    except Exception:
        pass
    try:
        posts = db.list_generated_posts(access_token, limit=20, platform="linkedin")
        week_start = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
        for row in posts:
            if not row.get("zernio_post_id"):
                continue
            created = row.get("created_at") or ""
            try:
                ts = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
            except Exception:
                continue
            if ts >= week_start:
                done += 1
                break
    except Exception:
        pass
    return min(PILOT_WEEKLY_TOTAL, done), PILOT_WEEKLY_TOTAL


def compose_pilot_plan(
    *,
    profile: dict[str, Any] | None,
    targeting: dict[str, Any] | None,
    generated_posts: list[dict[str, Any]],
    daily_ideas: list[dict[str, Any]],
    leads: list[dict[str, Any]],
    library: list[dict[str, Any]],
    followed_handles: set[str],
    schedule: list[dict[str, Any]],
    outreach_connected: bool,
    publish_connected: bool,
    weekly_done: int,
    weekly_total: int,
) -> dict[str, Any]:
    display = (profile or {}).get("display_name") or (profile or {}).get("brand_name") or "toi"
    user_first = first_name(display if display != "toi" else None) if display != "toi" else "toi"

    author_name = (profile or {}).get("display_name") or (profile or {}).get("brand_name") or "Toi"
    author_headline = (profile or {}).get("business_description") or (profile or {}).get("linkedin_objective") or ""

    post_row, post_kind = pick_post_of_day(generated_posts, daily_ideas)
    post_empty = post_row is None
    post_text = ""
    post_structure = "Post LinkedIn"
    post_hook = ""
    post_body = ""
    post_id: str | None = None
    media_items: list[dict[str, Any]] = []

    if post_row:
        post_id = str(post_row.get("id") or "")
        if post_kind == "daily_idea":
            post_text = (
                post_row.get("idea_markdown") or post_row.get("post_text") or post_row.get("idea") or ""
            ).strip()
            post_structure = "Idée du jour"
        else:
            post_text = (post_row.get("post") or "").strip()
            post_structure = (
                (post_row.get("hook_type") or post_row.get("strategy") or post_row.get("editorial_role") or "")
                .strip()
                or "Post LinkedIn"
            )
            media_items = list(post_row.get("media_items") or [])
        post_hook, post_body = split_post_text(post_text)

    follow_rows = pick_follow_profiles(library, followed_handles)
    contact_leads = pick_contacts(leads)
    contacts = []
    for idx, lead in enumerate(contact_leads):
        company = ""
        headline = (lead.get("headline") or "").strip()
        if " · " in headline:
            role, company = headline.split(" · ", 1)
        elif " @ " in headline:
            role, company = headline.split(" @ ", 1)
        elif " chez " in headline.lower():
            parts = re.split(r"\s+chez\s+", headline, maxsplit=1, flags=re.I)
            role, company = (parts[0], parts[1]) if len(parts) == 2 else (headline, "")
        else:
            role = headline
        contacts.append({
            "id": str(lead.get("id") or idx),
            "name": (lead.get("name") or "Prospect").strip(),
            "role": role.strip() or "Profil LinkedIn",
            "company": company.strip(),
            "score": int(lead.get("score") or 0),
            "initials": initials(lead.get("name")),
            "accent": _PILOT_ACCENTS[idx % len(_PILOT_ACCENTS)],
            "message": contact_message_preview(lead, targeting),
        })

    now = datetime.datetime.now()
    iso = now.isocalendar()

    plan = {
        "userName": user_first,
        "dayNumber": now.isoweekday(),
        "weekNumber": iso.week,
        "weeklyDone": weekly_done,
        "weeklyTotal": weekly_total,
        "author": {
            "name": author_name,
            "headline": author_headline,
            "initials": initials(author_name, "TO"),
            "avatarUrl": None,
        },
        "post": {
            "structure": post_structure,
            "hook": post_hook,
            "body": post_body,
        },
        "followProfiles": follow_rows,
        "contacts": contacts,
        "strategy": {
            "profiles": [f["handle"] for f in follow_rows[:3]],
            "frequency": format_weekly_frequency(schedule),
            "target": strategy_target(profile, targeting),
            "structureHint": strategy_structure_hint(profile),
        },
    }

    meta = {
        "post_id": post_id,
        "post_source": post_kind,
        "post_text": post_text,
        "post_empty": post_empty,
        "media_items": media_items,
        "follow_handles": {f["id"]: f.get("influencer_handle") for f in follow_rows},
        "linkedin_outreach_connected": outreach_connected,
        "linkedin_publish_connected": publish_connected,
        "contacts_blocked_reason": (
            None
            if outreach_connected
            else "Connecte ton compte LinkedIn de prospection (Mon profil → Connexions) pour inviter des leads."
        ),
    }
    return {"plan": plan, "meta": meta}


def empty_pilot_response() -> dict[str, Any]:
    return compose_pilot_plan(
        profile=None,
        targeting=None,
        generated_posts=[],
        daily_ideas=[],
        leads=[],
        library=[],
        followed_handles=set(),
        schedule=[],
        outreach_connected=False,
        publish_connected=False,
        weekly_done=0,
        weekly_total=PILOT_WEEKLY_TOTAL,
    )


def build_pilot_today(access_token: str) -> dict[str, Any]:
    """Agrège le plan du jour pour l'utilisateur authentifié (fail-safe)."""
    try:
        profile = db.get_editorial_profile(access_token)
        targeting = db.get_lead_targeting(access_token)
        generated = db.list_generated_posts(access_token, limit=30, platform="linkedin")
        daily_ideas = db.list_daily_ideas(access_token, limit=10)
        leads = db.list_leads(access_token, limit=200)
        library = db.list_influencer_library(access_token)
        followed = db.list_followed_influencers(access_token)
        followed_handles = {unquote((f.get("handle") or "").strip()) for f in followed if f.get("handle")}
        schedule = db.get_weekly_schedule(access_token)
        outreach_account = db.get_linkedin_outreach_account(access_token)
        outreach_connected = bool(outreach_account and outreach_account.get("unipile_account_id"))
        publish_connected = bool(profile and profile.get("zernio_account_id"))
        weekly_done, weekly_total = weekly_progress(access_token)
        return compose_pilot_plan(
            profile=profile,
            targeting=targeting,
            generated_posts=generated,
            daily_ideas=daily_ideas,
            leads=leads,
            library=library,
            followed_handles=followed_handles,
            schedule=schedule,
            outreach_connected=outreach_connected,
            publish_connected=publish_connected,
            weekly_done=weekly_done,
            weekly_total=weekly_total,
        )
    except Exception as exc:
        print(f"[pilot] build_pilot_today échoué : {exc}", flush=True)
        return empty_pilot_response()
