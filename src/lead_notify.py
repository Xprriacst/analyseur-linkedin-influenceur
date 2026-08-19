"""Alerte e-mail « nouveau lead » — les trois portes d'entrée du funnel.

Trois événements méritent un e-mail, et ils n'arrivent pas par le même chemin :

1. **E-mail déposé** sur la landing `/onboarding` (`audit_leads`, statut
   `founders_optin`) — le serveur est dans la boucle, la notification part en
   direct depuis l'endpoint.
2. **Abonnement pris** — Stripe nous appelle, la notification part depuis le
   webhook. Temps réel gratuit dans les deux cas.
3. **Compte créé** — personne ne prévient le serveur : l'inscription se joue
   entre le navigateur et Supabase Auth. C'est le seul cas qui exige un
   balayage périodique (`main()`, cron toutes les ~10 min).

⚠️ Tout est **best-effort et silencieux en cas de panne** : une alerte interne
qui ferait échouer une inscription ou un paiement serait une régression bien
pire que l'alerte manquée qu'elle prétend éviter. `mailer.send_email_safe` ne
lève jamais, et sans `RESEND_API_KEY` la fonction ne fait simplement rien.

⚠️ Exactement-une-fois : garanti par l'index unique de `lead_notifications`
(migration 0067), pas par un test préalable. Voir `db.admin_claim_lead_notification`.
"""
from __future__ import annotations

import datetime
import html as html_lib
import os
import sys
from typing import Any

from src import db, mailer

# Un compte tout juste créé n'a pas encore de profil éditorial : l'analyse de son
# LinkedIn arrive quelques minutes plus tard. On patiente pour envoyer UN e-mail
# riche (qui il est, ce qu'il vend, à qui) plutôt que deux e-mails pauvres — mais
# jamais au-delà de ce délai : un lead signalé tard reste utile, un lead jamais
# signalé ne l'est pas. Quelqu'un qui s'inscrit et referme l'onglet doit sortir.
SIGNUP_GRACE_MINUTES = int(os.environ.get("LEAD_NOTIFY_SIGNUP_GRACE_MIN", "20"))

# Fenêtre de rattrapage du balayage. Large devant la période du cron pour qu'une
# panne passagère (Render qui redémarre, Resend indisponible) ne perde rien.
SIGNUP_LOOKBACK_HOURS = int(os.environ.get("LEAD_NOTIFY_LOOKBACK_HOURS", "24"))

_DEFAULT_RECIPIENT = "alexandre@clareo-solutions.fr"


def recipients() -> list[str]:
    """À qui part l'alerte. `LEAD_NOTIFY_TO` d'abord, sinon l'existant, sinon Alex.

    Un défaut est posé volontairement : l'objectif est qu'il suffise de poser
    `RESEND_API_KEY` pour que les alertes arrivent. Une seconde variable oubliée,
    et la fonctionnalité reste muette en donnant l'illusion d'être en place.
    """
    raw = os.environ.get("LEAD_NOTIFY_TO", "").strip()
    if raw:
        return [addr.strip() for addr in raw.split(",") if addr.strip()]
    return mailer.internal_recipients() or [_DEFAULT_RECIPIENT]


def _esc(value: Any) -> str:
    return html_lib.escape(str(value if value not in (None, "") else "—"), quote=True)


def _paris(moment: datetime.datetime) -> str:
    """Horodatage lisible pour un humain à Paris (repli UTC si tzdata absent)."""
    try:
        from zoneinfo import ZoneInfo

        local = moment.astimezone(ZoneInfo("Europe/Paris"))
        return local.strftime("%d/%m à %Hh%M")
    except Exception:  # noqa: BLE001 — base tzdata absente de l'image
        return moment.astimezone(datetime.timezone.utc).strftime("%d/%m à %Hh%M UTC")


def _table(rows: list[tuple[str, Any]]) -> str:
    cells = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#555'>{_esc(label)}</td>"
        f"<td style='padding:4px 0'><strong>{_esc(value)}</strong></td></tr>"
        for label, value in rows
    )
    return f"<table cellpadding='0' cellspacing='0'>{cells}</table>"


def _linkify(url: str | None) -> str:
    if not url:
        return "—"
    safe = _esc(url)
    return f"<a href='{safe}'>{safe}</a>"


# --- Rendu des e-mails (fonctions pures : testables sans réseau ni base) ------


def render_optin(email: str, source: str, when: datetime.datetime) -> tuple[str, str]:
    subject = f"Nouvel e-mail laissé — {email}"
    html = (
        "<h2 style='margin:0 0 4px'>Nouvel e-mail laissé sur la landing</h2>"
        f"<p style='margin:0 0 16px;color:#666'>{_esc(_paris(when))}</p>"
        + _table([("E-mail", email), ("Entré par", source or "onboarding")])
        + "<p style='margin-top:16px;color:#666'>Il n'est pas allé plus loin pour "
        "l'instant : ni analyse lancée, ni compte créé.</p>"
    )
    return subject, html


def render_signup(
    email: str, when: datetime.datetime, profile: dict[str, Any] | None
) -> tuple[str, str]:
    """E-mail « compte créé ». Le profil éditorial est optionnel — il n'existe pas
    encore si le visiteur a refermé l'onglet avant l'analyse de son LinkedIn."""
    profile = profile or {}
    name = str(profile.get("display_name") or "").strip()
    industry = str(profile.get("industry") or "").strip()
    headline = " — ".join(part for part in (name or email, industry) if part)
    subject = f"Nouveau compte — {headline}"

    rows: list[tuple[str, Any]] = [("E-mail", email), ("Inscrit le", _paris(when))]
    if name:
        rows.append(("Nom", name))
    body = _table(rows)

    if profile:
        detail = [
            ("Secteur", profile.get("industry")),
            ("Vend", profile.get("core_offer")),
            ("À qui", profile.get("target_audience")),
            ("Objectif LinkedIn", profile.get("linkedin_objective")),
            ("Où", profile.get("location")),
        ]
        body += (
            "<h3 style='margin:20px 0 6px'>Ce qu'il a rempli</h3>"
            + _table(detail)
            + "<p style='margin:12px 0 0'>LinkedIn : "
            + _linkify(str(profile.get("linkedin_url") or "").strip() or None)
            + "</p>"
        )
        pitch = str(profile.get("business_description") or "").strip()
        if pitch:
            body += (
                "<p style='margin:12px 0 0;color:#444;font-style:italic'>"
                f"{_esc(pitch[:600])}</p>"
            )
    else:
        body += (
            "<p style='margin-top:16px;color:#666'>Compte créé, mais aucun profil "
            "rempli — il s'est arrêté avant l'analyse de son LinkedIn.</p>"
        )

    return subject, "<h2 style='margin:0 0 12px'>Nouveau compte</h2>" + body


def render_subscription(
    email: str, when: datetime.datetime, amount: Any = None, trial: bool = False
) -> tuple[str, str]:
    label = "Essai démarré" if trial else "Nouvel abonné"
    subject = f"{label} — {email}"
    rows: list[tuple[str, Any]] = [("Compte", email), ("Quand", _paris(when))]
    if amount not in (None, ""):
        rows.append(("Montant", f"{amount} €/mois"))
    if trial:
        rows.append(("Statut", "période d'essai en cours"))
    return subject, f"<h2 style='margin:0 0 12px'>{_esc(label)}</h2>" + _table(rows)


# --- Envoi (best-effort de bout en bout) -------------------------------------


def _send(kind: str, ref: str, subject: str, html: str, reply_to: str | None = None) -> bool:
    """Réserve, envoie, et rend la réservation si l'envoi échoue."""
    if not mailer.enabled():
        return False
    targets = recipients()
    if not targets:
        return False
    if not db.admin_claim_lead_notification(kind, ref):
        return False  # déjà envoyé, ou base indisponible → le passage suivant retentera
    if mailer.send_email_safe(targets, subject, html, reply_to=reply_to):
        return True
    db.admin_release_lead_notification(kind, ref)
    print(f"[lead-notify] envoi échoué ({kind}/{ref}) — sera retenté.", file=sys.stderr)
    return False


def notify_optin(email: str, source: str = "onboarding") -> bool:
    """Appelée en direct par `POST /onboarding/founders-lead`. Ne lève jamais."""
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        subject, html = render_optin(email, source, now)
        return _send("optin", email.lower(), subject, html, reply_to=email)
    except Exception as exc:  # noqa: BLE001 — jamais au détriment du visiteur
        print(f"[lead-notify] optin {email} : {exc}", file=sys.stderr)
        return False


def notify_subscription(
    event_ref: str, email: str, *, amount: Any = None, trial: bool = False
) -> bool:
    """Appelée en direct par le webhook Stripe. Ne lève jamais.

    La référence est l'id de l'événement Stripe : Stripe REJOUE ses événements
    tant qu'il n'a pas de 2xx, et un rejeu ne doit pas produire un second e-mail.
    """
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        subject, html = render_subscription(email, now, amount=amount, trial=trial)
        return _send("subscription", event_ref or email, subject, html)
    except Exception as exc:  # noqa: BLE001 — jamais au détriment du paiement
        print(f"[lead-notify] abonnement {email} : {exc}", file=sys.stderr)
        return False


def signup_is_ripe(
    created_at: datetime.datetime, has_profile: bool, now: datetime.datetime
) -> bool:
    """Faut-il envoyer l'alerte pour ce compte maintenant ?

    Oui dès que le profil est là (l'e-mail sera complet), ou une fois le délai de
    grâce écoulé (tant pis, on envoie ce qu'on a). Règle isolée ici pour être
    testable sans base : c'est elle qui décide si un lead est signalé ou pas.
    """
    if has_profile:
        return True
    age = now - created_at
    return age >= datetime.timedelta(minutes=SIGNUP_GRACE_MINUTES)


def scan_signups() -> int:
    """Balaie les comptes récents et envoie les alertes dues. Renvoie le nombre envoyé."""
    now = datetime.datetime.now(datetime.timezone.utc)
    sent = 0
    for account in db.admin_list_recent_signups(hours=SIGNUP_LOOKBACK_HOURS):
        user_id = account["user_id"]
        try:
            profile = db.get_ai_context_for_user(user_id)
        except Exception as exc:  # noqa: BLE001 — un profil illisible ne perd pas le lead
            print(f"[lead-notify] profil illisible ({user_id}) : {exc}", file=sys.stderr)
            profile = None
        if not signup_is_ripe(account["created_at"], bool(profile), now):
            continue
        subject, html = render_signup(account["email"], account["created_at"], profile)
        if _send("signup", user_id, subject, html, reply_to=account["email"] or None):
            sent += 1
            print(f"  ✓ compte signalé : {account['email']}")
    return sent


def main() -> int:
    if not db.admin_enabled():
        print("SUPABASE_SERVICE_ROLE_KEY manquant — cron désactivé.", file=sys.stderr)
        return 1
    if not mailer.enabled():
        # Sortie propre et non silencieuse : sans clé, rien ne part, mais rien
        # n'est perdu non plus — les comptes restent dans la fenêtre de rattrapage.
        print("RESEND_API_KEY manquant — aucune alerte envoyée.", file=sys.stderr)
        return 0
    sent = scan_signups()
    print(f"Terminé : {sent} alerte(s) « nouveau compte » envoyée(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
