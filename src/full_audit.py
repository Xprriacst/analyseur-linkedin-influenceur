"""Audit LinkedIn complet gratuit (lead magnet de la landing).

À la fin de l'audit léger (/onboarding/draft), le visiteur laisse nom + email +
téléphone pour recevoir un « pack semi-personnalisé » par e-mail : synthèse,
plan 30/60/90 jours, headline / À propos / bannière, influenceurs à suivre,
angles de posts, ciblage prospection et offre Clareo adaptée.

Décisions de cadrage (2026-08-08) :
- Pack SEMI-personnalisé : un seul appel LLM sur les données DÉJÀ scrapées par
  l'audit léger (preview + brouillon de profil) — zéro re-scrape Apify, livrable
  en < 1 min, coût marginal ~1 appel Claude par lead.
- Aucun chiffre inventé : mêmes règles que l'audit léger. Les influenceurs
  proposés sont des créateurs connus de la niche, SANS compteur d'abonnés ni URL
  inventés (nom + pourquoi les suivre uniquement).
- La bannière est un CONCEPT (accroche + description visuelle), pas une image
  générée (mockup CSS côté app, décision V1).
"""
from __future__ import annotations

import html as html_lib
import json
import os
from typing import Any

from .llm import _call

CALENDLY_URL = "https://calendly.com/tom-clareo-solutions/15min"

# Contexte de l'offre injecté dans le prompt (surchargeable sans redéploiement).
# Volontairement factuel et court : le modèle adapte l'angle, pas les faits.
DEFAULT_OFFER_CONTEXT = (
    "Clareo Solutions accompagne les fondateurs, dirigeants et experts B2B pour "
    "générer des clients via LinkedIn : stratégie éditoriale, création de contenu "
    "assistée par IA (application Cibl), optimisation de profil et prospection "
    "ciblée. Premier pas : un appel gratuit de 15 minutes avec Tom pour décoder "
    "l'audit et définir un plan d'action."
)


def _offer_context() -> str:
    return os.environ.get("CLAREO_OFFER_CONTEXT", "").strip() or DEFAULT_OFFER_CONTEXT


def _clean_list(values: Any, cap: int, item_cap: int = 300) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for v in values:
        s = str(v or "").strip()
        if s:
            out.append(s[:item_cap])
        if len(out) >= cap:
            break
    return out


def _clean_influencers(values: Any, cap: int = 12) -> list[dict[str, str]]:
    """Nom + raison uniquement — jamais d'URL ni de compteur d'abonnés (invérifiables)."""
    if not isinstance(values, list):
        return []
    out: list[dict[str, str]] = []
    for v in values:
        if isinstance(v, dict):
            name = str(v.get("name") or "").strip()
            why = str(v.get("why") or v.get("reason") or "").strip()
        else:
            name, why = str(v or "").strip(), ""
        if name:
            out.append({"name": name[:80], "why": why[:220]})
        if len(out) >= cap:
            break
    return out


def normalize_full_audit(data: Any) -> dict[str, Any] | None:
    """Normalisation défensive de la sortie modèle — mêmes principes que la preview :
    sans les sections cœur (synthèse + plan), l'audit ne vaut pas d'être envoyé."""
    if not isinstance(data, dict):
        return None
    audit = data.get("audit", data)
    if not isinstance(audit, dict):
        return None

    summary = str(audit.get("summary") or "").strip()
    plan_raw = audit.get("plan") if isinstance(audit.get("plan"), dict) else {}
    plan = {
        "d30": _clean_list(plan_raw.get("d30"), 5),
        "d60": _clean_list(plan_raw.get("d60"), 5),
        "d90": _clean_list(plan_raw.get("d90"), 5),
    }
    if not summary or not (plan["d30"] and plan["d60"] and plan["d90"]):
        return None

    return {
        "summary": summary[:2500],
        "plan": plan,
        "headlines": _clean_list(audit.get("headlines"), 3, item_cap=220),
        "about": str(audit.get("about") or "").strip()[:1500],
        "banners": _clean_list(audit.get("banners"), 2, item_cap=400),
        "influencers": _clean_influencers(audit.get("influencers")),
        "post_angles": _clean_list(audit.get("post_angles"), 8, item_cap=220),
        "prospecting": _clean_list(audit.get("prospecting"), 5, item_cap=300),
        "offer_pitch": str(audit.get("offer_pitch") or "").strip()[:900],
    }


def generate_full_audit(
    lead_name: str,
    preview: dict[str, Any] | None,
    profile_draft: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Génère le pack complet. Un seul appel Claude, ancré sur l'audit léger."""
    system = (
        "Tu es un stratège LinkedIn B2B senior de l'agence Clareo Solutions. Tu "
        "rédiges un audit complet, concret et personnalisé, envoyé par e-mail à un "
        "prospect qui vient de faire l'audit léger gratuit. Tu t'appuies UNIQUEMENT "
        "sur les sources fournies. Tu n'inventes AUCUN chiffre (ni vues, ni taux, ni "
        "nombre d'abonnés). Pour les influenceurs à suivre : uniquement des créateurs "
        "LinkedIn réels et connus de la niche (francophones en priorité), nom + raison "
        "de les suivre, JAMAIS d'URL ni de compteur d'abonnés. Si tu hésites sur un "
        "nom, propose-en moins. Réponds UNIQUEMENT en JSON valide, sans markdown."
    )
    sources = {
        "prenom_nom_du_lead": lead_name,
        "audit_leger": preview or {},
        "profil_editorial_deduit": profile_draft or {},
        "offre_clareo": _offer_context(),
    }
    user = (
        "Rédige l'audit LinkedIn complet de ce prospect.\n\n"
        + json.dumps({"sources": sources}, ensure_ascii=False, indent=2)
        + """

Règles :
- Français, tutoiement, ton direct et généreux (le lecteur doit sentir de la valeur immédiate).
- summary : 2-3 paragraphes courts séparés par \\n\\n — diagnostic global + le levier n°1.
- plan : d30 / d60 / d90 = 3 à 5 actions CONCRÈTES chacun (verbe d'action, ≤ 20 mots).
- headlines : 2-3 propositions de titre de profil LinkedIn prêtes à copier (≤ 200 caractères).
- about : une proposition de section « À propos » complète (600-1200 caractères), à sa voix.
- banners : 2 concepts de bannière — pour chacun : l'accroche à afficher + une courte description visuelle.
- influencers : 8 à 12 créateurs à suivre dans sa niche (objets {"name": "...", "why": "..."}).
- post_angles : 6 à 8 angles de posts adaptés à son positionnement (une ligne chacun).
- prospecting : 3-5 puces — qui cibler (ICP), où les trouver, quelle approche de premier message.
- offer_pitch : 2-3 phrases reliant SES points faibles à l'accompagnement Clareo, sans survendre.

Schéma JSON attendu :
{
  "audit": {
    "summary": "",
    "plan": {"d30": ["…"], "d60": ["…"], "d90": ["…"]},
    "headlines": ["…"],
    "about": "",
    "banners": ["…"],
    "influencers": [{"name": "", "why": ""}],
    "post_angles": ["…"],
    "prospecting": ["…"],
    "offer_pitch": ""
  }
}"""
    )
    # Modèle surchargeable pour cet appel seul (même patron qu'ONBOARDING_PREVIEW_MODEL).
    # ⚠️ Fable/Mythos : réflexion décomptée de max_tokens → budget large sinon JSON tronqué.
    model = os.environ.get("FULL_AUDIT_MODEL", "").strip() or None
    data = _call(system, user, max_tokens=6000, temperature=0.4, model=model)
    return normalize_full_audit(data)


# --- Rendu e-mail -------------------------------------------------------------
# HTML autonome, styles inline (les clients mail ignorent les <style> externes),
# palette sobre lisible partout. Tout le contenu passe par html.escape.

_ACCENT = "#4648d4"


def _esc(s: str) -> str:
    return html_lib.escape(str(s or ""), quote=True)


def _paras(text: str) -> str:
    return "".join(
        f'<p style="margin:0 0 12px;line-height:1.6;color:#2b2d42;">{_esc(p.strip())}</p>'
        for p in (text or "").split("\n\n")
        if p.strip()
    )


def _bullets(items: list[str]) -> str:
    lis = "".join(
        f'<li style="margin:0 0 8px;line-height:1.55;color:#2b2d42;">{_esc(i)}</li>'
        for i in items
    )
    return f'<ul style="margin:0;padding-left:20px;">{lis}</ul>'


def _section(title: str, inner: str) -> str:
    if not inner:
        return ""
    return (
        '<tr><td style="padding:0 28px 24px;">'
        f'<h2 style="margin:0 0 10px;font-size:17px;color:{_ACCENT};">{_esc(title)}</h2>'
        f"{inner}</td></tr>"
    )


def render_audit_email_html(lead_name: str, audit: dict[str, Any]) -> str:
    """L'audit complet, prêt à envoyer. `audit` = sortie de normalize_full_audit."""
    first_name = (lead_name or "").strip().split(" ")[0] or "bonjour"
    plan = audit.get("plan") or {}

    plan_html = ""
    for key, label in (("d30", "Jours 1-30"), ("d60", "Jours 31-60"), ("d90", "Jours 61-90")):
        items = plan.get(key) or []
        if items:
            plan_html += (
                f'<h3 style="margin:14px 0 8px;font-size:14px;color:#2b2d42;">{label}</h3>'
                + _bullets(items)
            )

    influencers = audit.get("influencers") or []
    inf_html = ""
    if influencers:
        inf_html = _bullets(
            [f"{i['name']} — {i['why']}" if i.get("why") else i["name"] for i in influencers]
        )

    headlines = audit.get("headlines") or []
    headlines_html = ""
    if headlines:
        headlines_html = "".join(
            f'<p style="margin:0 0 10px;padding:10px 14px;background:#f4f4fb;border-radius:8px;'
            f'line-height:1.5;color:#2b2d42;">{_esc(h)}</p>'
            for h in headlines
        )

    sections = (
        _section("Diagnostic", _paras(audit.get("summary", "")))
        + _section("Ton plan d'action 90 jours", plan_html)
        + _section("Propositions de titre de profil", headlines_html)
        + _section("Proposition de section « À propos »", _paras(audit.get("about", "")))
        + _section("Idées de bannière", _bullets(audit.get("banners") or []))
        + _section("Influenceurs à suivre dans ta niche", inf_html)
        + _section("Angles de posts à lancer", _bullets(audit.get("post_angles") or []))
        + _section("Ciblage prospection", _bullets(audit.get("prospecting") or []))
        + _section("Et si on le faisait ensemble ?", _paras(audit.get("offer_pitch", "")))
    )

    return f"""<!doctype html>
<html lang="fr"><body style="margin:0;padding:24px 12px;background:#eef0f6;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:14px;overflow:hidden;">
<tr><td style="padding:28px;background:{_ACCENT};">
  <h1 style="margin:0;font-size:20px;color:#ffffff;">Ton audit LinkedIn complet</h1>
  <p style="margin:6px 0 0;color:#dcdcf8;font-size:14px;">Offert par Clareo Solutions</p>
</td></tr>
<tr><td style="padding:24px 28px 8px;">
  <p style="margin:0 0 12px;line-height:1.6;color:#2b2d42;">Salut {_esc(first_name)},</p>
  <p style="margin:0 0 12px;line-height:1.6;color:#2b2d42;">Comme promis, voici ton audit complet — diagnostic, plan d'action et tout ce qu'il faut pour passer au niveau supérieur sur LinkedIn.</p>
</td></tr>
{sections}
<tr><td style="padding:4px 28px 30px;" align="center">
  <a href="{CALENDLY_URL}" style="display:inline-block;padding:13px 26px;background:{_ACCENT};color:#ffffff;text-decoration:none;border-radius:10px;font-weight:600;">Décoder cet audit avec Tom — 15 min offertes</a>
  <p style="margin:14px 0 0;font-size:12px;color:#8a8ca6;">Tu reçois cet e-mail parce que tu as demandé ton audit LinkedIn gratuit sur Cible.</p>
</td></tr>
</table></td></tr></table></body></html>"""


def render_notify_email_html(lead: dict[str, Any]) -> str:
    """Notification interne : un nouveau lead audit complet vient d'arriver."""
    rows = "".join(
        f'<tr><td style="padding:6px 10px;color:#8a8ca6;font-size:13px;">{_esc(k)}</td>'
        f'<td style="padding:6px 10px;color:#2b2d42;font-size:13px;">{_esc(v)}</td></tr>'
        for k, v in (
            ("Nom", lead.get("name", "")),
            ("Email", lead.get("email", "")),
            ("Téléphone", lead.get("phone", "")),
            ("LinkedIn", lead.get("linkedin_url", "") or "—"),
            ("Audit envoyé", lead.get("status", "")),
        )
    )
    return (
        '<html><body style="font-family:Arial,sans-serif;">'
        "<h2 style=\"color:#2b2d42;\">Nouveau lead — audit complet</h2>"
        f'<table style="border-collapse:collapse;background:#f4f4fb;border-radius:8px;">{rows}</table>'
        '<p style="color:#8a8ca6;font-size:12px;">Il part maintenant sur le Calendly de Tom.</p>'
        "</body></html>"
    )
