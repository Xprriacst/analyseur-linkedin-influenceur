"""Mode Pilote — composition du plan du jour (lecture seule, sans LLM ni Apify)."""
from __future__ import annotations

import datetime
import re
from typing import Any
from urllib.parse import unquote

from src import db

PILOT_CONTACT_LIMIT = 3
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

# ── Suggestions de profils à suivre — matching niche/ICP, sans IA ni Apify ── #
# Filtre purement textuel : mots trop courants pour discriminer une niche.
# Best-effort — un mot manquant à cette liste dégrade la pertinence, jamais
# la correction (aucune décision facturée ni aucun droit n'en dépend).
_NICHE_STOPWORDS = frozenset({
    "pour", "avec", "sans", "dans", "chez", "leur", "leurs", "plus", "tout",
    "tous", "toute", "toutes", "être", "avoir", "faire", "notre", "votre",
    "vos", "nos", "cette", "aussi", "comme", "sont", "cela", "donc", "mais",
    "elle", "elles", "ils", "nous", "vous", "que", "qui", "quoi", "dont",
    "très", "bien", "peut", "peuvent", "vers", "entre", "sous", "afin",
    "ainsi", "alors", "ceci", "encore", "leurs", "être", "sera", "seront",
    "avons", "avez", "ont", "est", "être", "the", "and", "for", "with",
    "your", "you", "are", "our",
})
_NICHE_WORD_RE = re.compile(r"[a-zàâäéèêëïîôöùûüçñ0-9]+")


def _handle_from_profile_url(url: str | None) -> str:
    """Handle LinkedIn décodé depuis une URL de profil, sans dépendre du scraper Apify."""
    if not url:
        return ""
    raw = url.strip().rstrip("/")
    raw = raw.split("/in/")[-1].split("/")[0].split("?")[0].split("#")[0]
    return unquote(raw)


def extract_niche_keywords(
    profile: dict[str, Any] | None,
    targeting: dict[str, Any] | None,
    max_keywords: int = 25,
) -> list[str]:
    """Mots-clés de niche/ICP tirés du profil éditorial + du ciblage prospection.

    Purement textuel, zéro appel IA — sert uniquement à FILTRER/CLASSER une
    liste de suggestions d'affichage, jamais à décider d'un droit ni à
    facturer quoi que ce soit. Profil sans ces champs renseignés (onboarding
    encore vide) ⇒ liste vide, et la section de suggestions cross-user ne
    s'affichera alors pas du tout, par construction.
    """
    texts: list[str] = []
    for source in (profile, targeting):
        if not isinstance(source, dict):
            continue
        for key in (
            "industry",
            "business_description",
            "target_audience",
            "core_offer",
            "topics_to_cover",
            "ideal_client",
            "offer",
        ):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                texts.append(value)

    raw_keywords = (targeting or {}).get("interest_keywords") if isinstance(targeting, dict) else None
    if isinstance(raw_keywords, list):
        texts.extend(str(k) for k in raw_keywords if str(k or "").strip())
    elif isinstance(raw_keywords, str) and raw_keywords.strip():
        texts.append(raw_keywords)

    words: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for token in _NICHE_WORD_RE.findall(text.lower()):
            if len(token) < 4 or token in _NICHE_STOPWORDS or token in seen:
                continue
            seen.add(token)
            words.append(token)
    return words[:max_keywords]


def _score_cross_user_match(candidate: dict[str, Any], keywords: list[str]) -> int:
    haystack = " ".join(
        str(candidate.get(field) or "") for field in ("headline", "name")
    ).lower()
    if not haystack.strip():
        return 0
    return sum(1 for kw in keywords if kw in haystack)


def pick_cross_user_follow_profiles(
    candidates: list[dict[str, Any]],
    keywords: list[str],
    excluded_handles: set[str],
    limit: int,
    start_index: int = 0,
) -> list[dict[str, Any]]:
    """Complète les suggestions avec des influenceurs analysés par D'AUTRES
    comptes (cache cross-user, aucune donnée privée — champs publics
    uniquement) dont la fiche correspond à la niche du client. Sans mot-clé,
    aucune suggestion n'est faite : on préfère une section absente à une liste
    de profils sans rapport avec l'activité du client.
    """
    if limit <= 0 or not keywords:
        return []
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for row in candidates:
        handle = unquote((row.get("handle") or "").strip())
        if not handle or handle in excluded_handles:
            continue
        score = _score_cross_user_match(row, keywords)
        if score <= 0:
            continue
        scored.append((score, int(row.get("follower_count") or 0), {**row, "handle": handle}))
    scored.sort(key=lambda item: (-item[0], -item[1]))

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _score, _followers, row in scored:
        handle = row["handle"]
        if handle in seen:
            continue
        seen.add(handle)
        headline = (row.get("headline") or "").strip()
        reason = (
            f"{headline} — dans ta niche." if headline else "Profil public dans ta niche, repéré sur Cibl."
        )
        idx = start_index + len(rows)
        rows.append({
            "id": row.get("id") or handle,
            "name": (row.get("name") or handle).strip(),
            "handle": f"@{handle}",
            "reason": reason,
            "initials": initials(row.get("name"), handle[:2].upper()),
            "accent": _PILOT_ACCENTS[idx % len(_PILOT_ACCENTS)],
            "influencer_handle": handle,
        })
        if len(rows) >= limit:
            break
    return rows


def pick_follow_suggestions(
    library: list[dict[str, Any]],
    followed_handles: set[str],
    cross_user_candidates: list[dict[str, Any]],
    niche_keywords: list[str],
    own_handle: str = "",
    limit: int = PILOT_FOLLOW_LIMIT,
) -> list[dict[str, Any]]:
    """Jusqu'à `limit` profils à suivre : d'abord ceux déjà analysés par le
    client (sa bibliothèque perso, comme avant), puis en repli des profils
    analysés par D'AUTRES comptes (cache cross-user, gratuit) dont la fiche
    publique correspond à sa niche. Un compte tout juste sorti de l'onboarding
    n'a presque jamais de bibliothèque perso (elle exige d'avoir lancé une
    analyse payante) — sans ce repli, la section serait vide pour la quasi-
    totalité des nouveaux comptes Pilote.
    """
    rows = pick_follow_profiles(library, followed_handles, limit)
    remaining = limit - len(rows)
    if remaining <= 0:
        return rows
    exclude = set(followed_handles) | {r["influencer_handle"] for r in rows}
    if own_handle:
        exclude.add(own_handle)
    extra = pick_cross_user_follow_profiles(
        cross_user_candidates, niche_keywords, exclude, remaining, start_index=len(rows)
    )
    return rows + extra


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
    cross_user_candidates: list[dict[str, Any]] | None = None,
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

    own_handle = _handle_from_profile_url((profile or {}).get("linkedin_url"))
    follow_rows = pick_follow_suggestions(
        library,
        followed_handles,
        cross_user_candidates or [],
        extract_niche_keywords(profile, targeting),
        own_handle=own_handle,
    )
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
        niche_keywords = extract_niche_keywords(profile, targeting)
        # Requête cross-user réservée aux cas où elle peut servir : pas de
        # mot-clé de niche ⇒ pick_follow_suggestions ne s'en servira de toute
        # façon jamais, autant éviter l'appel service-role pour rien.
        cross_user_candidates = db.list_influencer_cache_candidates() if niche_keywords else []
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
            cross_user_candidates=cross_user_candidates,
        )
    except Exception as exc:
        print(f"[pilot] build_pilot_today échoué : {exc}", flush=True)
        return empty_pilot_response()
