"""Mode Pilote — composition du plan du jour.

`compose_pilot_plan` reste de la logique pure (0 LLM, 0 Apify) : testable
sans réseau. `build_pilot_today` agrège, puis — une fois les 3 contacts
choisis — demande un appel modèle pour les accroches manquantes (persistées,
0 crédit). Une panne modèle n'empêche pas d'afficher le plan.
"""
from __future__ import annotations

import datetime
import re
from typing import Any
from urllib.parse import unquote

from src import db
from src import prospect_pool
from src.daily_ideas import maybe_bootstrap_daily_idea
from src.invite_openers import PILOT_INVITE_PREVIEW_CAP, fill_invite_previews

PILOT_CONTACT_LIMIT = 3
# Sans LinkedIn : le vivier peut contenir des dizaines de fiches (l'admin
# en colle plein d'un coup). On n'en montre qu'UNE par jour calendaire.
PILOT_UNCONNECTED_DAILY_LIMIT = 1
PILOT_FOLLOW_LIMIT = 5
PILOT_WEEKLY_TOTAL = 3

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


def pick_contacts(
    leads: list[dict[str, Any]],
    limit: int = PILOT_CONTACT_LIMIT,
    *,
    outreach_connected: bool = True,
    now: datetime.datetime | None = None,
) -> list[dict[str, Any]]:
    """Leads scorés verts/oranges, jamais contactés ni écartés.

    Compte LinkedIn relié : jusqu'à ``limit`` (3). Sans LinkedIn : **1 seul**,
    et si le vivier a copié quelqu'un aujourd'hui c'est LUI — pas les N
    fiches que l'admin vient de coller dans un autre compte.
    """
    invitables: list[dict[str, Any]] = []
    for lead in leads:
        if not lead_invitable(lead):
            continue
        invitables.append(lead)
    if outreach_connected:
        return invitables[:limit]
    today_pool = [
        lead for lead in invitables
        if prospect_pool.is_pool_lead(lead)
        and prospect_pool.assigned_from_pool_today([lead], now)
    ]
    if today_pool:
        return today_pool[:PILOT_UNCONNECTED_DAILY_LIMIT]
    return invitables[:PILOT_UNCONNECTED_DAILY_LIMIT]


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
    """Gabarit de repli — utilisé seulement si le modèle n'a pas produit d'accroche."""
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


def contact_opener(lead: dict[str, Any], targeting: dict[str, Any] | None) -> str:
    """Texte affiché sur la carte : accroche générée si elle existe, sinon gabarit."""
    stored = str(lead.get("invite_preview") or "").strip()
    if stored:
        return stored[:PILOT_INVITE_PREVIEW_CAP]
    return contact_message_preview(lead, targeting)


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


DAILY_POST_LABEL = "1 post par jour — ton agent l'écrit chaque matin"


def format_weekly_frequency(
    slots: list[dict[str, Any]],
    daily_ideas_enabled: bool = False,
) -> str:
    """Rythme de publication annoncé au client.

    ⚠️ L'idée du jour compte comme un rythme à part entière : sans elle,
    un compte tout neuf (aucun créneau hebdo programmé) lisait « Aucun créneau
    programmé » alors qu'un post lui est écrit chaque matin — un rythme réel
    présenté comme une absence de rythme.
    """
    day_labels = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
    parts: list[str] = []

    def _sort_key(slot: dict[str, Any]) -> int:
        # ⚠️ La clé de tri s'exécute AVANT le try/except de la boucle : un
        # `day_of_week` illisible y levait, et emportait tout le plan du jour
        # (rattrapé par le fail-safe de `build_pilot_today`, donc en silence).
        try:
            return int(slot.get("day_of_week") or 0)
        except (TypeError, ValueError):
            return 0

    for slot in sorted(slots or [], key=_sort_key):
        try:
            dow = int(slot.get("day_of_week", 0))
            hour = int(slot.get("hour", 9))
        except (TypeError, ValueError):
            continue
        if 0 <= dow < len(day_labels):
            parts.append(f"{day_labels[dow]} {hour}h")
    if not parts:
        if daily_ideas_enabled:
            return DAILY_POST_LABEL
        return "Aucun créneau programmé — règle ton rythme dans Mon profil."
    weekly = f"{len(parts)} posts / semaine · {', '.join(parts)}"
    if daily_ideas_enabled:
        return f"1 post par jour · {weekly} programmés"
    return weekly


def build_strategy(
    profile: dict[str, Any] | None,
    targeting: dict[str, Any] | None,
    schedule: list[dict[str, Any]] | None,
    follow_handles: list[str] | None = None,
    daily_ideas_enabled: bool = False,
) -> dict[str, Any]:
    """Stratégie affichée dans Mon profil (et révélée en fin d'onboarding).

    Une seule composition pour les deux surfaces : deux versions finiraient par
    se contredire sous les yeux du client — l'onboarding lui promettrait un
    rythme que sa page profil dément le lendemain.
    """
    return {
        "profiles": list(follow_handles or [])[:3],
        "frequency": format_weekly_frequency(schedule or [], daily_ideas_enabled),
        "target": strategy_target(profile, targeting),
        "structureHint": strategy_structure_hint(profile),
    }


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


_PILOT_SIM_PROSPECTS: tuple[dict[str, str], ...] = (
    {
        "id": "sim-1",
        "name": "Camille Martin",
        "role": "Consultante IA",
        "company": "Indépendante",
        "headline": "Consultante IA · Indépendante",
    },
    {
        "id": "sim-2",
        "name": "Thomas Leroy",
        "role": "Directeur marketing",
        "company": "ScaleUp B2B",
        "headline": "Directeur marketing · ScaleUp B2B",
    },
    {
        "id": "sim-3",
        "name": "Sarah Benali",
        "role": "Fondatrice",
        "company": "Studio NoCode",
        "headline": "Fondatrice · Studio NoCode",
    },
)


def _parse_user_created_at(raw: str | None) -> datetime.datetime | None:
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


def simulated_prospect_reveal_count(created_at: datetime.datetime | None) -> int:
    """Nombre de prospects « découverts » simulés selon l'ancienneté du compte."""
    if not created_at:
        return 0
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=datetime.timezone.utc)
    age_min = (datetime.datetime.now(datetime.timezone.utc) - created_at).total_seconds() / 60
    if age_min < 1:
        return 0
    if age_min < 4:
        return 1
    if age_min < 8:
        return 2
    return PILOT_CONTACT_LIMIT


def build_prospect_agent_meta(
    *,
    simulate_prospects: bool,
    real_contact_count: int,
    reveal_count: int,
    outreach_connected: bool,
) -> dict[str, Any]:
    """État de l'agent IA de recherche de prospects (Mode Pilote gratuit).

    Chemin réel (vivier) : la carte « en recherche » s'affiche tant qu'on
    n'a personne à proposer aujourd'hui. Pas de noms inventés — juste le
    signal que l'agent travaille. Une fois un vrai profil copié, la carte
    disparaît : c'est la personne qui parle.
    """
    if not simulate_prospects:
        if outreach_connected or real_contact_count >= 1:
            return {"active": False, "status": "idle", "message": None, "detail": None}
        return {
            "active": True,
            "status": "searching",
            "message": "Ton agent cherche des prospects qui correspondent à ta cible.",
            "detail": "Un profil par jour — dès qu'un compte de ta niche est trouvé.",
        }

    if real_contact_count >= PILOT_CONTACT_LIMIT:
        return {"active": False, "status": "ready", "message": None, "detail": None}

    if reveal_count <= 0:
        return {
            "active": True,
            "status": "starting",
            "message": "Ton agent IA analyse LinkedIn pour trouver des prospects.",
            "detail": "Les profils correspondant à ton ICP apparaîtront ici au fur et à mesure.",
        }

    if real_contact_count < reveal_count:
        return {
            "active": True,
            "status": "searching",
            "message": "Recherche en cours — de nouveaux profils arrivent.",
            "detail": f"{reveal_count} prospect{'s' if reveal_count > 1 else ''} identifié{'s' if reveal_count > 1 else ''} pour l'instant.",
        }

    if not outreach_connected:
        return {
            "active": True,
            "status": "warming",
            "message": "Prospects repérés — connexion LinkedIn requise pour inviter.",
            "detail": "Relie ton compte dans Mon profil → Connexions quand tu es prêt à contacter.",
        }

    return {"active": False, "status": "ready", "message": None, "detail": None}


def build_simulated_contacts(
    *,
    reveal_count: int,
    existing_count: int,
    targeting: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Complète la liste avec des prospects simulés (Mode Pilote, en attendant le vrai pipeline)."""
    need = max(0, reveal_count - existing_count)
    if need <= 0:
        return []
    rows: list[dict[str, Any]] = []
    for idx, seed in enumerate(_PILOT_SIM_PROSPECTS[:need]):
        score = 78 - idx * 4
        rows.append({
            "id": seed["id"],
            "name": seed["name"],
            "role": seed["role"],
            "company": seed["company"],
            "score": score,
            "initials": initials(seed["name"]),
            "accent": _PILOT_ACCENTS[(existing_count + idx) % len(_PILOT_ACCENTS)],
            "message": contact_message_preview(
                {"name": seed["name"], "headline": seed["headline"], "comment_text": ""},
                targeting,
            ),
            "simulated": True,
        })
    return rows


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
    is_pilote_landing: bool = False,
    simulate_prospects: bool = False,
    account_created_at: datetime.datetime | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    display = (profile or {}).get("display_name") or (profile or {}).get("brand_name") or "toi"
    user_first = first_name(display if display != "toi" else None) if display != "toi" else "toi"

    author_name = (profile or {}).get("display_name") or (profile or {}).get("brand_name") or "Toi"
    author_headline = (profile or {}).get("business_description") or (profile or {}).get("linkedin_objective") or ""

    # `get_editorial_profile` fait un `select("*")` : l'opt-in idée du jour est
    # déjà dans la ligne, aucun aller-retour supplémentaire.
    daily_ideas_enabled = bool((profile or {}).get("daily_ideas_enabled"))

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
    contact_leads = pick_contacts(
        leads, outreach_connected=outreach_connected, now=now,
    )
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
            "message": contact_opener(lead, targeting),
            "simulated": False,
        })

    reveal_count = (
        simulated_prospect_reveal_count(account_created_at) if simulate_prospects else 0
    )
    contacts.extend(
        build_simulated_contacts(
            reveal_count=reveal_count,
            existing_count=len(contacts),
            targeting=targeting,
        )
    )

    prospect_agent = build_prospect_agent_meta(
        simulate_prospects=simulate_prospects,
        real_contact_count=len(contact_leads),
        reveal_count=reveal_count,
        outreach_connected=outreach_connected,
    )

    if simulate_prospects:
        blocked_reason = None
    elif outreach_connected:
        blocked_reason = None
    else:
        blocked_reason = "Connecte ton compte LinkedIn pour inviter des leads."

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
        "strategy": build_strategy(
            profile,
            targeting,
            schedule,
            [f["handle"] for f in follow_rows],
            daily_ideas_enabled,
        ),
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
        "contacts_blocked_reason": blocked_reason,
        "prospect_agent": prospect_agent,
        "is_pilote_landing": is_pilote_landing,
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


def build_pilot_strategy(access_token: str) -> dict[str, Any]:
    """Stratégie seule — sans le plan du jour (leads, posts, veille).

    Sert la révélation de fin d'onboarding : à cet instant, le compte n'a ni
    lead ni post, et `build_pilot_today` ferait une dizaine de lectures pour
    n'en garder que trois lignes. Lecture seule : 0 crédit, 0 LLM, 0 Apify.

    Fail-safe : profil illisible ou Supabase en panne ⇒ la stratégie générique,
    jamais une erreur — l'écran qui la porte ne doit pas tomber pour ça.
    """
    try:
        profile = db.get_editorial_profile(access_token)
        targeting = db.get_lead_targeting(access_token)
        schedule = db.get_weekly_schedule(access_token)
        return build_strategy(
            profile,
            targeting,
            schedule,
            daily_ideas_enabled=bool((profile or {}).get("daily_ideas_enabled")),
        )
    except Exception as exc:  # noqa: BLE001 — best-effort, jamais bloquant
        print(f"[pilot] strategy indisponible: {exc}")
        return build_strategy(None, None, [])


def build_pilot_today(access_token: str) -> dict[str, Any]:
    """Agrège le plan du jour pour l'utilisateur authentifié (fail-safe)."""
    try:
        user = db.get_user(access_token)
        user_meta = (user or {}).get("user_metadata") or {}
        is_pilote_landing = user_meta.get("landing") == "pilote"
        account_created_at = _parse_user_created_at((user or {}).get("created_at"))
        profile = db.get_editorial_profile(access_token)
        targeting = db.get_lead_targeting(access_token)
        maybe_bootstrap_daily_idea(access_token)
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
        # Vivier partagé : 1 vrai profil / jour, seulement tant que LinkedIn
        # n'est pas connecté (une fois relié, le client a ses propres leads).
        # Fail-safe interne à maybe_assign_one — on ne mélange jamais ça avec
        # les noms inventés de `_PILOT_SIM_PROSPECTS` (`simulate_prospects`
        # reste False).
        if not outreach_connected and (user or {}).get("id"):
            # maybe_assign_one borne déjà à 1/jour UTC, même si le vivier
            # vient d'être rempli de 50 URLs. On n'attend plus d'avoir 3
            # cases vides : sans LinkedIn la vue n'en montre qu'une.
            assigned = prospect_pool.maybe_assign_one(
                user["id"], profile, targeting, leads,
            )
            if assigned:
                leads = db.list_leads(access_token, limit=200)
        chosen = pick_contacts(leads, outreach_connected=outreach_connected)
        fill_invite_previews(access_token, targeting, chosen)
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
            is_pilote_landing=is_pilote_landing,
            simulate_prospects=False,
            account_created_at=account_created_at,
        )
    except Exception as exc:
        print(f"[pilot] build_pilot_today échoué : {exc}", flush=True)
        return empty_pilot_response()
