"""Audit complet gratuit (lead magnet landing) — logique pure, zéro réseau.

Couvre la normalisation défensive du pack (sections cœur exigées, listes
bornées, influenceurs sans URL/compteur), le rendu de l'e-mail (échappement
HTML, CTA Calendly) et le fail-safe de l'emailer (clé absente ⇒ disabled).
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from src import emailer
from src.full_audit import (
    CALENDLY_URL,
    normalize_full_audit,
    render_audit_email_html,
    render_notify_email_html,
)


def _valid_audit() -> dict:
    return {
        "audit": {
            "summary": "Ton profil attire mais ne convertit pas.\n\nLe levier n°1 : ta headline.",
            "plan": {
                "d30": ["Réécrire ta headline", "Publier 2 posts/semaine"],
                "d60": ["Lancer la prospection ciblée"],
                "d90": ["Systématiser avec un calendrier éditorial"],
            },
            "headlines": ["J'aide les PME à générer des leads via LinkedIn"],
            "about": "Depuis 5 ans, j'accompagne…",
            "banners": ["Accroche : « 30 leads en 90 jours » — fond sombre, photo à droite"],
            "influencers": [{"name": "Justine Hutteau", "why": "Storytelling de marque"}],
            "post_angles": ["Retour d'expérience chiffré sur un client"],
            "prospecting": ["Cibler les dirigeants de PME industrielles"],
            "offer_pitch": "On peut le faire ensemble.",
        }
    }


class NormalizeFullAuditTests(unittest.TestCase):
    def test_accepts_valid_payload(self):
        audit = normalize_full_audit(_valid_audit())
        self.assertIsNotNone(audit)
        self.assertIn("headline", audit["summary"])
        self.assertEqual(len(audit["plan"]["d30"]), 2)
        self.assertEqual(audit["influencers"][0]["name"], "Justine Hutteau")

    def test_rejects_missing_plan_section(self):
        payload = _valid_audit()
        payload["audit"]["plan"]["d60"] = []
        self.assertIsNone(normalize_full_audit(payload))

    def test_rejects_missing_summary(self):
        payload = _valid_audit()
        payload["audit"]["summary"] = ""
        self.assertIsNone(normalize_full_audit(payload))

    def test_rejects_non_dict(self):
        self.assertIsNone(normalize_full_audit(None))
        self.assertIsNone(normalize_full_audit("pas un dict"))
        self.assertIsNone(normalize_full_audit({"audit": []}))

    def test_influencers_capped_and_cleaned(self):
        payload = _valid_audit()
        # Mélange de formes renvoyées par le modèle : dicts, strings, entrées vides.
        payload["audit"]["influencers"] = (
            [{"name": f"Nom {i}", "why": "raison"} for i in range(20)]
            + ["Juste un nom", {"name": ""}, 42]
        )
        audit = normalize_full_audit(payload)
        self.assertEqual(len(audit["influencers"]), 12)  # plafond dur
        for inf in audit["influencers"]:
            self.assertNotIn("url", inf)        # jamais d'URL (invérifiable)
            self.assertNotIn("followers", inf)  # jamais de compteur inventé

    def test_influencer_string_entries_survive(self):
        payload = _valid_audit()
        payload["audit"]["influencers"] = ["Grégoire Gambatto"]
        audit = normalize_full_audit(payload)
        self.assertEqual(audit["influencers"], [{"name": "Grégoire Gambatto", "why": ""}])

    def test_lists_capped(self):
        payload = _valid_audit()
        payload["audit"]["post_angles"] = [f"Angle {i}" for i in range(30)]
        payload["audit"]["headlines"] = [f"Headline {i}" for i in range(10)]
        audit = normalize_full_audit(payload)
        self.assertEqual(len(audit["post_angles"]), 8)
        self.assertEqual(len(audit["headlines"]), 3)

    def test_flat_payload_without_audit_key(self):
        # Le modèle renvoie parfois le contenu à plat, sans l'enveloppe {"audit": …}.
        audit = normalize_full_audit(_valid_audit()["audit"])
        self.assertIsNotNone(audit)


class RenderEmailTests(unittest.TestCase):
    def test_contains_sections_and_calendly(self):
        audit = normalize_full_audit(_valid_audit())
        html = render_audit_email_html("Camille Dupont", audit)
        self.assertIn("Salut Camille", html)          # prénom seul
        self.assertIn("Jours 1-30", html)
        self.assertIn("Justine Hutteau", html)
        self.assertIn(CALENDLY_URL, html)

    def test_escapes_html_in_content(self):
        payload = _valid_audit()
        payload["audit"]["summary"] = "<script>alert(1)</script>\n\nSuite du plan."
        audit = normalize_full_audit(payload)
        html = render_audit_email_html("<b>Léa</b>", audit)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_empty_optional_sections_are_skipped(self):
        payload = _valid_audit()
        payload["audit"]["influencers"] = []
        payload["audit"]["about"] = ""
        audit = normalize_full_audit(payload)
        html = render_audit_email_html("Camille", audit)
        self.assertNotIn("Influenceurs à suivre", html)
        self.assertNotIn("À propos", html)

    def test_notify_email_contains_lead_fields(self):
        html = render_notify_email_html({
            "name": "Camille", "email": "c@d.fr", "phone": "0612345678",
            "linkedin_url": "https://linkedin.com/in/camille", "status": "sent",
        })
        self.assertIn("Camille", html)
        self.assertIn("0612345678", html)


class EmailerTests(unittest.TestCase):
    def test_disabled_without_key(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RESEND_API_KEY", None)
            self.assertFalse(emailer.enabled())
            with self.assertRaises(emailer.EmailError):
                emailer.send_email("a@b.fr", "sujet", "<p>corps</p>")

    def test_sender_overridable(self):
        with mock.patch.dict(os.environ, {"AUDIT_EMAIL_FROM": "Alex <a@clareo.fr>"}):
            self.assertEqual(emailer.sender(), "Alex <a@clareo.fr>")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AUDIT_EMAIL_FROM", None)
            self.assertEqual(emailer.sender(), emailer.DEFAULT_FROM)

    def test_notify_recipients_csv(self):
        with mock.patch.dict(os.environ, {"AUDIT_NOTIFY_EMAILS": "a@x.fr, b@y.fr ,"}):
            self.assertEqual(emailer.notify_recipients(), ["a@x.fr", "b@y.fr"])
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AUDIT_NOTIFY_EMAILS", None)
            self.assertEqual(emailer.notify_recipients(), [])


if __name__ == "__main__":
    unittest.main()
