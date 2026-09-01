"""Audit LinkedIn complet envoyé par e-mail après le tunnel de la landing.

C'est la contrepartie promise au visiteur qui a laissé ses coordonnées : l'audit
léger montre trois points à améliorer, celui-ci livre un plan exploitable.

Trois partis pris qui expliquent la forme du prompt :

1. **On ne refait pas le scrape.** La preview affichée au visiteur (profil, posts,
   forces, faiblesses) est passée telle quelle au modèle. Relancer Apify coûterait
   une seconde fois pour produire les mêmes faits, et surtout l'audit reçu par
   e-mail doit correspondre à ce que la personne a vu à l'écran.

2. **Aucune URL de profil inventée.** Le modèle est bon pour nommer des figures
   d'un secteur, mauvais pour restituer l'URL LinkedIn exacte de quelqu'un — et
   une liste de liens morts dans un audit « offert » détruit la crédibilité qu'on
   vient de construire. On ne demande donc que des NOMS, et on fabrique nous-mêmes
   un lien de recherche LinkedIn, qui, lui, marche toujours.

3. **Les services proposés ne sont pas inventés par le modèle** : il choisit dans
   un catalogue défini ici et se contente de justifier. Laisser une IA improviser
   une offre commerciale au nom de l'entreprise est le genre de détail qui se
   retrouve dans un e-mail signé, envoyé à un prospect.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import urllib.parse
from html import escape
from typing import Any

from src import db, mailer, notion_pages

# Audit complet = Opus 5 (pas Fable : Fable est réservé à la preview légère).
_AUDIT_MODEL_DEFAULT = "claude-opus-5"

# Catalogue de services proposables. ⚠️ Contenu commercial : à ajuster par l'équipe
# — le modèle CHOISIT dans cette liste, il n'en ajoute jamais.
SERVICE_CATALOG: list[dict[str, str]] = [
    {
        "key": "profil",
        "name": "Optimisation du profil LinkedIn",
        "pitch": "Titre, section « Infos », bannière et sélection à la une retravaillés pour convertir les visiteurs en demandes.",
    },
    {
        "key": "contenu",
        "name": "Contenu régulier assisté par l'IA",
        "pitch": "Une idée de post chaque matin, des posts rédigés dans ta voix à partir de ce qui marche sur ton marché, publication et programmation incluses.",
    },
    {
        "key": "prospection",
        "name": "Prospection LinkedIn outillée",
        "pitch": "Les prospects qui commentent les posts de tes concurrents deviennent des leads scorés, invités et relancés depuis l'app, dans les plafonds de sécurité LinkedIn.",
    },
    {
        "key": "veille",
        "name": "Veille concurrentielle chiffrée",
        "pitch": "Analyse des comptes qui performent dans ta niche : formats, accroches et appels à l'action qui génèrent réellement de l'engagement.",
    },
    {
        "key": "accompagnement",
        "name": "Accompagnement sur-mesure",
        "pitch": "Un point régulier avec l'équipe pour arbitrer la stratégie, les cibles et les offres mises en avant.",
    },
]

_MAX_INFLUENCERS = 8


def linkedin_search_url(name: str) -> str:
    """Lien de recherche LinkedIn pour un nom — jamais une URL de profil devinée."""
    query = urllib.parse.quote((name or "").strip())
    return f"https://www.linkedin.com/search/results/people/?keywords={query}"


def _service_by_key(key: str) -> dict[str, str] | None:
    for service in SERVICE_CATALOG:
        if service["key"] == key:
            return service
    return None


def normalize_audit(data: dict[str, Any] | None) -> dict[str, Any]:
    """Met la sortie du modèle en forme, en jetant tout ce qui n'est pas exploitable.

    Défensif par principe : cet objet part directement dans un e-mail envoyé à un
    prospect. Une clé manquante doit produire une section vide, jamais une trace
    d'erreur ou un « None » au milieu du texte.
    """
    data = data if isinstance(data, dict) else {}

    def _text(key: str, limit: int = 2000) -> str:
        value = data.get(key)
        return str(value).strip()[:limit] if isinstance(value, (str, int, float)) else ""

    def _list_of_str(key: str, limit: int, item_limit: int = 300) -> list[str]:
        raw = data.get(key)
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                out.append(item.strip()[:item_limit])
            if len(out) >= limit:
                break
        return out

    # Bannières : 3 concepts { title, subtitle, direction }.
    banners: list[dict[str, str]] = []
    for item in data.get("banners") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:120]
        if not title:
            continue
        banners.append({
            "title": title,
            "subtitle": str(item.get("subtitle") or "").strip()[:160],
            "direction": str(item.get("direction") or "").strip()[:300],
        })
        if len(banners) >= 3:
            break

    # Influenceurs : nom + raison. L'URL est FABRIQUÉE ici (recherche LinkedIn),
    # jamais reprise du modèle — voir l'entête du module.
    influencers: list[dict[str, str]] = []
    for item in data.get("influencers") or []:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:120]
        if not name:
            continue
        influencers.append({
            "name": name,
            "reason": str(item.get("reason") or "").strip()[:220],
            "search_url": linkedin_search_url(name),
        })
        if len(influencers) >= _MAX_INFLUENCERS:
            break

    # Services : uniquement ceux du catalogue, avec la justification du modèle.
    services: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for item in data.get("services") or []:
        if isinstance(item, str):
            item = {"key": item}
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        service = _service_by_key(key)
        if not service or key in seen_keys:
            continue
        seen_keys.add(key)
        services.append({
            "name": service["name"],
            "pitch": service["pitch"],
            "reason": str(item.get("reason") or "").strip()[:220],
        })
    if not services:
        # Un audit sans recommandation de service n'a pas de suite logique : on
        # retombe sur le socle plutôt que d'envoyer une section vide.
        services = [
            {"name": s["name"], "pitch": s["pitch"], "reason": ""}
            for s in SERVICE_CATALOG[:3]
        ]

    plan: list[dict[str, Any]] = []
    for item in data.get("plan") or []:
        if not isinstance(item, dict):
            continue
        horizon = str(item.get("horizon") or "").strip()[:40]
        actions = [
            str(a).strip()[:220]
            for a in (item.get("actions") or [])
            if isinstance(a, str) and a.strip()
        ][:4]
        if horizon and actions:
            plan.append({"horizon": horizon, "actions": actions})
        if len(plan) >= 3:
            break

    return {
        "headline": _text("headline", 220),
        "about": _text("about", 2600),
        "positioning": _text("positioning", 600),
        "banners": banners,
        "influencers": influencers,
        "post_angles": _list_of_str("post_angles", 6),
        "prospecting": _text("prospecting", 1200),
        "plan": plan,
        "services": services,
    }


def generate_full_audit(
    preview: dict[str, Any] | None,
    profile: dict[str, Any] | None,
) -> dict[str, Any]:
    """Produit l'audit complet à partir de ce que le visiteur a déjà vu."""
    from src.llm import _call  # import tardif : évite de charger le SDK sans besoin

    catalog = [{"key": s["key"], "name": s["name"]} for s in SERVICE_CATALOG]
    system = (
        "Tu es un stratège LinkedIn B2B francophone. Tu rédiges un audit complet, "
        "concret et actionnable, à partir des seules sources fournies. Tu n'inventes "
        "aucun chiffre d'engagement, aucune vue, aucun taux. Tu ne fournis JAMAIS "
        "d'URL. Réponds UNIQUEMENT en JSON valide, sans markdown."
    )
    user = (
        "Sources disponibles sur la personne :\n"
        + json.dumps(
            {"analyse_legere": preview or {}, "profil_declare": profile or {}},
            ensure_ascii=False,
            indent=2,
        )
        + "\n\nCatalogue de services (choisis-en 2 ou 3, uniquement par leur clé) :\n"
        + json.dumps(catalog, ensure_ascii=False)
        + """

Règles :
- Français, tutoiement, ton direct et professionnel. Zéro remplissage.
- headline : une proposition de titre LinkedIn (max 220 caractères), prête à copier.
- about : une section « Infos » réécrite, 900 à 1500 caractères, prête à copier.
- positioning : 2 phrases qui résument le positionnement à tenir.
- banners : exactement 3 concepts de bannière. Chacun : title (accroche affichée), subtitle (une ligne de preuve ou d'offre), direction (indication visuelle : couleurs, composition, éléments).
- influencers : 6 à 8 personnes réellement connues dans ce secteur francophone, dont s'inspirer. Donne UNIQUEMENT name (le nom de la personne) et reason (ce qu'il fait bien, 1 phrase). N'invente PAS d'URL ni de pseudo.
- post_angles : 5 angles de posts précis, ancrés sur son métier (pas de généralités).
- prospecting : qui cibler et comment l'aborder sur LinkedIn (profil type, déclencheur, angle du premier message), 4 à 6 phrases.
- plan : 3 étapes, horizon « 30 jours », « 60 jours », « 90 jours », 3 actions concrètes chacune.
- services : 2 ou 3 entrées, chacune { "key": "<clé du catalogue>", "reason": "pourquoi c'est celui-là pour cette personne" }.

Schéma JSON attendu :
{
  "headline": "",
  "about": "",
  "positioning": "",
  "banners": [{"title": "", "subtitle": "", "direction": ""}],
  "influencers": [{"name": "", "reason": ""}],
  "post_angles": ["", ""],
  "prospecting": "",
  "plan": [{"horizon": "30 jours", "actions": ["", "", ""]}],
  "services": [{"key": "", "reason": ""}]
}"""
    )
    model = (
        os.environ.get("AUDIT_FULL_MODEL", "").strip()
        or _AUDIT_MODEL_DEFAULT
    )
    # Budget large : Opus 5 avec thinking disabled occupe quand même plus
    # de tokens de sortie qu'un Sonnet sur un audit long.
    data = _call(system, user, max_tokens=8000, temperature=0.5, model=model)
    return normalize_audit(data)


# --- Rendu e-mail -------------------------------------------------------------
#
# HTML écrit à la main, en styles inline : les clients e-mail (Outlook en tête)
# ignorent les feuilles de style et la moitié du CSS moderne. Pas de dépendance
# de templating pour trois sections.

_BRAND = "#4648d4"
_INK = "#15161f"
_MUTED = "#5d6070"


def _p(text: str, size: int = 15) -> str:
    return (
        f'<p style="margin:0 0 12px;font-size:{size}px;line-height:1.6;color:{_INK};">'
        f"{escape(text)}</p>"
    )


def _section(title: str, inner: str) -> str:
    if not inner:
        return ""
    return (
        '<tr><td style="padding:26px 28px 0;">'
        f'<h2 style="margin:0 0 14px;font-size:19px;line-height:1.3;color:{_INK};">{escape(title)}</h2>'
        f"{inner}</td></tr>"
    )


def _card(inner: str) -> str:
    return (
        '<div style="margin:0 0 12px;padding:16px 18px;border:1px solid #e6e7ef;'
        'border-radius:14px;background:#fafaff;">' + inner + "</div>"
    )


def _copyable(text: str) -> str:
    """Bloc « prêt à copier » — le contenu doit se distinguer du commentaire."""
    return (
        '<div style="margin:0 0 12px;padding:16px 18px;border-left:3px solid '
        f'{_BRAND};background:#f5f5ff;border-radius:0 12px 12px 0;font-size:15px;'
        f'line-height:1.65;color:{_INK};white-space:pre-wrap;">{escape(text)}</div>'
    )


def render_audit_html(
    full_name: str,
    audit: dict[str, Any],
    projection: dict[str, Any] | None = None,
    calendly_url: str = "",
) -> str:
    """Assemble l'e-mail d'audit. Toute section vide disparaît proprement."""
    first_name = (full_name or "").strip().split(" ")[0] or "toi"
    parts: list[str] = []

    parts.append(_section("Ton positionnement", _p(audit.get("positioning", ""))))

    if audit.get("headline"):
        parts.append(_section(
            "Ton titre LinkedIn, réécrit",
            _p("À copier-coller directement dans ton profil :") + _copyable(audit["headline"]),
        ))

    if audit.get("about"):
        parts.append(_section(
            "Ta section « Infos », réécrite",
            _copyable(audit["about"]),
        ))

    if audit.get("banners"):
        inner = "".join(
            _card(
                f'<div style="font-size:16px;font-weight:700;color:{_INK};margin-bottom:4px;">'
                f'{escape(b["title"])}</div>'
                + (
                    f'<div style="font-size:14px;color:{_MUTED};margin-bottom:8px;">'
                    f'{escape(b["subtitle"])}</div>' if b.get("subtitle") else ""
                )
                + (
                    f'<div style="font-size:13.5px;color:{_MUTED};line-height:1.55;">'
                    f'<strong>Direction visuelle :</strong> {escape(b["direction"])}</div>'
                    if b.get("direction") else ""
                )
            )
            for b in audit["banners"]
        )
        parts.append(_section("3 concepts de bannière", inner))

    if audit.get("influencers"):
        rows = "".join(
            _card(
                f'<div style="font-size:15px;font-weight:700;color:{_INK};">'
                f'<a href="{escape(i["search_url"])}" style="color:{_BRAND};text-decoration:none;">'
                f'{escape(i["name"])}</a></div>'
                + (
                    f'<div style="font-size:13.5px;color:{_MUTED};margin-top:4px;line-height:1.5;">'
                    f'{escape(i["reason"])}</div>' if i.get("reason") else ""
                )
            )
            for i in audit["influencers"]
        )
        parts.append(_section(
            "Les comptes à suivre dans ta niche",
            _p("Chaque nom ouvre une recherche LinkedIn — on préfère un lien qui marche à une URL devinée.")
            + rows,
        ))

    if audit.get("post_angles"):
        items = "".join(
            f'<li style="margin:0 0 8px;font-size:15px;line-height:1.55;color:{_INK};">'
            f"{escape(a)}</li>"
            for a in audit["post_angles"]
        )
        parts.append(_section("5 angles de posts pour démarrer", f'<ul style="margin:0;padding-left:20px;">{items}</ul>'))

    if audit.get("prospecting"):
        parts.append(_section("Qui cibler, et comment l'aborder", _p(audit["prospecting"])))

    if audit.get("plan"):
        blocks = "".join(
            _card(
                f'<div style="font-size:15px;font-weight:700;color:{_BRAND};margin-bottom:8px;">'
                f'{escape(step["horizon"])}</div>'
                + '<ul style="margin:0;padding-left:18px;">'
                + "".join(
                    f'<li style="margin:0 0 6px;font-size:14.5px;line-height:1.5;color:{_INK};">'
                    f"{escape(a)}</li>"
                    for a in step["actions"]
                )
                + "</ul>"
            )
            for step in audit["plan"]
        )
        parts.append(_section("Ton plan sur 90 jours", blocks))

    if audit.get("services"):
        blocks = "".join(
            _card(
                f'<div style="font-size:15px;font-weight:700;color:{_INK};margin-bottom:4px;">'
                f'{escape(s["name"])}</div>'
                f'<div style="font-size:14px;color:{_MUTED};line-height:1.55;">{escape(s["pitch"])}</div>'
                + (
                    f'<div style="font-size:13.5px;color:{_INK};margin-top:8px;line-height:1.5;">'
                    f'<strong>Pour toi :</strong> {escape(s["reason"])}</div>'
                    if s.get("reason") else ""
                )
            )
            for s in audit["services"]
        )
        parts.append(_section("Ce qu'on peut faire ensemble", blocks))

    cta = ""
    if calendly_url:
        cta = (
            '<tr><td style="padding:26px 28px 32px;" align="center">'
            f'<a href="{escape(calendly_url)}" style="display:inline-block;padding:15px 30px;'
            f'background:{_BRAND};color:#ffffff;font-size:16px;font-weight:700;'
            'text-decoration:none;border-radius:999px;">Réserver 15 minutes avec Tom</a>'
            f'<div style="margin-top:10px;font-size:13px;color:{_MUTED};">'
            "On passe l'audit en revue ensemble et on priorise.</div></td></tr>"
        )

    return f"""<!doctype html>
<html lang="fr"><body style="margin:0;padding:0;background:#f2f2f7;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f2f2f7;padding:24px 12px;">
<tr><td align="center">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:620px;background:#ffffff;border-radius:18px;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
  <tr><td style="padding:30px 28px 6px;background:linear-gradient(140deg,#2b2d7e,#4648d4);">
    <div style="font-size:13px;font-weight:600;color:#c9caff;letter-spacing:.04em;text-transform:uppercase;">Audit LinkedIn complet</div>
    <h1 style="margin:8px 0 18px;font-size:26px;line-height:1.2;color:#ffffff;">Salut {escape(first_name)}, voici ton audit.</h1>
  </td></tr>
  <tr><td style="padding:24px 28px 0;">
    {_p("Tu as testé l'analyse rapide sur notre site. Voici la version complète : ton positionnement, ton profil réécrit, des concepts de bannière, les comptes à suivre, tes angles de posts et un plan sur 90 jours.")}
  </td></tr>
  {''.join(parts)}
  {cta}
  <tr><td style="padding:18px 28px 26px;border-top:1px solid #ececf4;">
    <div style="font-size:12px;color:{_MUTED};line-height:1.5;">
      Tu reçois cet e-mail parce que tu as demandé un audit LinkedIn gratuit sur notre site.
      Réponds simplement à ce message si tu ne veux plus être recontacté.
    </div>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


# --- Orchestration ------------------------------------------------------------


def _ensure_public_token(lead: dict[str, Any]) -> str:
    """Jeton opaque pour la page publique /a/<token> (sans auth)."""
    existing = (lead.get("public_token") or "").strip()
    if existing:
        return existing
    token = secrets.token_urlsafe(16)
    db.update_audit_lead(str(lead["id"]), {"public_token": token})
    return token


def _publish_notion(lead: dict[str, Any], audit: dict[str, Any], calendly_url: str) -> dict[str, str]:
    """Crée la page Notion et renvoie les champs à persister (éventuellement vides)."""
    created = notion_pages.create_audit_page_safe(
        lead.get("full_name") or "",
        audit,
        email=lead.get("email") or "",
        phone=lead.get("phone") or "",
        linkedin_url=lead.get("linkedin_url") or "",
        calendly_url=calendly_url,
    )
    if not created:
        return {}
    # Préférer l'URL publique Notion si le parent est publié ; sinon l'URL workspace.
    share = (created.get("public_url") or "").strip() or (created.get("url") or "").strip()
    return {
        "notion_page_id": created.get("page_id") or "",
        "notion_url": share,
    }


def process_audit_lead(lead_id: str, calendly_url: str = "") -> None:
    """Génère l'audit complet, page Notion, puis e-mail. Best-effort, tracé en base.

    Tourne dans un thread de fond : le visiteur est déjà parti sur Calendly quand
    ceci s'exécute. Toute erreur est consignée sur la ligne du lead (`status`,
    `error_message`) — un audit qui n'est pas parti doit être visible et rejouable,
    pas silencieusement perdu.

    ⚠️ Génération et envoi sont DEUX étapes. Un 403 Resend (domaine non
    vérifié) ne doit JAMAIS jeter un audit déjà produit : `audit_payload`
    est persisté dès que le modèle a répondu, AVANT tout appel réseau
    d'envoi. Statuts :
    - `failed` = la génération n'a pas abouti (rien à envoyer, rien à
      afficher sur `/a/{token}`) ;
    - `generated` = l'audit est en base, l'e-mail n'est pas parti ;
    - `sent` = les deux ont réussi.
    Rejouer un `generated` (ou un `failed` dont le payload a survécu)
    reprend l'envoi sans rappeler le modèle.
    """
    lead = db.get_audit_lead(lead_id)
    if not lead:
        return
    if lead.get("status") in {"generating", "sent"}:
        return  # déjà pris en charge (rejeu, double thread)

    already = lead.get("audit_payload")
    already = already if isinstance(already, dict) and already else None

    db.update_audit_lead(lead_id, {"status": "generating"})
    try:
        _ensure_public_token(lead)
        lead = db.get_audit_lead(lead_id) or lead
        if already:
            audit = already
            notion_fields: dict[str, str] = {}
        else:
            audit = generate_full_audit(lead.get("preview"), lead.get("profile"))
            notion_fields = _publish_notion(lead, audit, calendly_url)
        db.update_audit_lead(lead_id, {
            "status": "generated",
            "audit_payload": audit,
            **{k: v for k, v in notion_fields.items() if v},
        })
    except Exception as exc:
        print(f"[audit-lead] génération impossible ({lead_id}) : {exc}", file=sys.stderr)
        db.update_audit_lead(lead_id, {"status": "failed", "error_message": str(exc)[:500]})
        return

    try:
        html = render_audit_html(
            lead.get("full_name") or "",
            audit,
            lead.get("projection"),
            calendly_url,
        )
        if not mailer.enabled():
            db.update_audit_lead(lead_id, {
                "error_message": "RESEND_API_KEY absent : audit généré mais non envoyé.",
            })
            return
        mailer.send_email(
            lead["email"],
            "Ton audit LinkedIn complet",
            html,
            reply_to=(mailer.internal_recipients() or [None])[0],
        )
        db.update_audit_lead(lead_id, {
            "status": "sent",
            "error_message": None,
            "sent_at": db.now_iso(),
        })
    except Exception as exc:
        print(f"[audit-lead] envoi impossible ({lead_id}) : {exc}", file=sys.stderr)
        # Payload déjà en base : on ne rétrograde PAS en `failed`.
        db.update_audit_lead(lead_id, {
            "status": "generated",
            "error_message": str(exc)[:500],
        })


def start_audit_email_thread(lead_id: str, calendly_url: str = "") -> None:
    """Lance la génération en tâche de fond, sans jamais faire attendre l'appelant."""
    threading.Thread(
        target=process_audit_lead,
        args=(lead_id, calendly_url),
        daemon=True,
    ).start()
