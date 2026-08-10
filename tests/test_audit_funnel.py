"""Tunnel « audit complet » : projection des gains, mise en forme et e-mail.

Ces tests portent sur du contenu montré à un prospect (des chiffres présentés
comme un gain potentiel, puis un e-mail signé). Les cas couverts sont donc moins
« la fonction calcule » que « la fonction ne peut pas mentir » : pas de fourchette
inversée, pas d'URL de profil inventée, pas de service hors catalogue, pas de
statut « envoyé » sans envoi.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import audit_projection as proj  # noqa: E402
from src import audit_report, mailer  # noqa: E402


class ProjectionTest(unittest.TestCase):
    def test_ranges_are_ordered_and_never_zero(self):
        """Une borne basse à 0 (« 0 à 4 clients ») annulerait tout l'écran."""
        for followers in (0, 42, 1240, 90000):
            p = proj.project_gains(followers=followers, deal_value=3000)
            for key in (
                "relations_per_month",
                "conversations_per_month",
                "clients_per_month",
                "followers_gain",
            ):
                with self.subTest(followers=followers, key=key):
                    self.assertGreaterEqual(p[key]["low"], 1)
                    self.assertGreaterEqual(p[key]["high"], p[key]["low"])

    def test_small_account_gets_absolute_floor_not_a_percentage(self):
        """18 % de 40 abonnés ne veut rien dire : le plancher absolu doit primer."""
        p = proj.project_gains(followers=40)
        self.assertGreaterEqual(p["followers_gain"]["low"], proj.FOLLOWER_FLOOR_LOW)

    def test_large_account_scales_with_its_audience(self):
        """Au-delà du plancher, la croissance suit bien la taille du compte."""
        p = proj.project_gains(followers=50000)
        self.assertGreater(p["followers_gain"]["low"], proj.FOLLOWER_FLOOR_LOW)
        self.assertEqual(
            p["followers_after"]["low"],
            50000 + p["followers_gain"]["low"],
        )

    def test_prospecting_volume_ignores_audience_size(self):
        """Le volume de prospection vient des plafonds d'envoi, pas des abonnés."""
        small = proj.project_gains(followers=10)
        big = proj.project_gains(followers=80000)
        self.assertEqual(small["relations_per_month"], big["relations_per_month"])

    def test_revenue_follows_the_selected_deal_band(self):
        cheap = proj.project_gains(followers=1000, deal_value=600)
        rich = proj.project_gains(followers=1000, deal_value=30000)
        self.assertLess(cheap["revenue_per_month"]["high"], rich["revenue_per_month"]["high"])

    def test_no_deal_value_means_no_revenue_claim(self):
        """Sans panier moyen, on n'affiche pas un montant sorti de nulle part."""
        p = proj.project_gains(followers=1000, deal_value=0)
        self.assertEqual(p["revenue_per_month"], {"low": 0, "high": 0})

    def test_values_are_rounded_to_readable_steps(self):
        """Un « 1 247 € » de projection sonne faux et fait perdre confiance."""
        self.assertEqual(proj._round_nice(1247), 1200)
        self.assertEqual(proj._round_nice(47), 45)
        self.assertEqual(proj._round_nice(23480), 23500)

    def test_all_bands_carry_their_own_assumptions(self):
        result = proj.project_all_bands(followers=1240, connections=800, posts_count=25)
        self.assertEqual(len(result["bands"]), len(proj.DEAL_BANDS))
        self.assertTrue(any(b["key"] == result["default_band"] for b in result["bands"]))
        for band in result["bands"]:
            with self.subTest(band=band["key"]):
                self.assertTrue(band["assumptions"])
                # Le panier retenu doit être écrit noir sur blanc sous les chiffres.
                self.assertTrue(any(band["label"] in line for line in band["assumptions"]))
                # Et la nature indicative de la projection, toujours rappelée.
                self.assertTrue(any("garantie" in line for line in band["assumptions"]))

    def test_negative_inputs_do_not_produce_negative_gains(self):
        p = proj.project_gains(followers=-500, deal_value=-10)
        self.assertEqual(p["followers_now"], 0)
        self.assertGreaterEqual(p["followers_after"]["low"], 0)
        self.assertEqual(p["revenue_per_month"], {"low": 0, "high": 0})


class NormalizeAuditTest(unittest.TestCase):
    def test_influencer_urls_are_built_never_taken_from_the_model(self):
        """Le modèle invente des URLs de profil : une seule doit survivre, la nôtre."""
        out = audit_report.normalize_audit({
            "influencers": [
                {"name": "Jean Dupont", "reason": "Bon storytelling", "url": "https://linkedin.com/in/inventé"},
            ]
        })
        influencer = out["influencers"][0]
        self.assertNotIn("url", influencer)
        self.assertIn("search/results/people", influencer["search_url"])
        self.assertIn("Jean%20Dupont", influencer["search_url"])

    def test_influencers_accept_plain_strings(self):
        out = audit_report.normalize_audit({"influencers": ["Marie Martin"]})
        self.assertEqual(out["influencers"][0]["name"], "Marie Martin")

    def test_influencer_list_is_capped(self):
        out = audit_report.normalize_audit({
            "influencers": [{"name": f"Personne {i}"} for i in range(30)]
        })
        self.assertLessEqual(len(out["influencers"]), audit_report._MAX_INFLUENCERS)

    def test_services_outside_the_catalog_are_dropped(self):
        """Laisser le modèle improviser une offre commerciale est hors de question."""
        out = audit_report.normalize_audit({
            "services": [
                {"key": "prospection", "reason": "Tu as une cible claire"},
                {"key": "refonte-de-site-web", "reason": "Inventé par le modèle"},
            ]
        })
        names = [s["name"] for s in out["services"]]
        self.assertEqual(len(out["services"]), 1)
        self.assertIn("Prospection", names[0])

    def test_services_fall_back_to_the_catalog_when_none_are_valid(self):
        out = audit_report.normalize_audit({"services": [{"key": "inconnu"}]})
        self.assertGreaterEqual(len(out["services"]), 1)
        self.assertTrue(all(s["name"] for s in out["services"]))

    def test_duplicate_services_are_collapsed(self):
        out = audit_report.normalize_audit({
            "services": [{"key": "contenu"}, {"key": "contenu"}]
        })
        self.assertEqual(len(out["services"]), 1)

    def test_empty_model_output_never_raises(self):
        """Cet objet part dans un e-mail : une clé manquante = section vide, pas 500."""
        for payload in (None, {}, {"banners": "pas une liste"}, {"plan": [None, 3]}):
            with self.subTest(payload=payload):
                out = audit_report.normalize_audit(payload)  # type: ignore[arg-type]
                self.assertEqual(out["headline"], "")
                self.assertEqual(out["banners"], [])
                self.assertEqual(out["plan"], [])

    def test_plan_step_without_actions_is_dropped(self):
        out = audit_report.normalize_audit({
            "plan": [
                {"horizon": "30 jours", "actions": []},
                {"horizon": "60 jours", "actions": ["Publier 3 fois par semaine"]},
            ]
        })
        self.assertEqual(len(out["plan"]), 1)
        self.assertEqual(out["plan"][0]["horizon"], "60 jours")


class RenderAuditEmailTest(unittest.TestCase):
    def _audit(self, **overrides):
        base = audit_report.normalize_audit({
            "headline": "Fondateur SaaS — je parle cold call",
            "about": "Deux paragraphes.",
            "positioning": "Positionnement clair.",
            "influencers": [{"name": "Jean Dupont", "reason": "Storytelling"}],
            "post_angles": ["Angle 1"],
            "plan": [{"horizon": "30 jours", "actions": ["Action 1"]}],
            "services": [{"key": "contenu", "reason": "Tu publies peu"}],
        })
        base.update(overrides)
        return base

    def test_calendly_button_is_present_when_url_given(self):
        html = audit_report.render_audit_html("Camille Durand", self._audit(), None, "https://calendly.test/15min")
        self.assertIn("https://calendly.test/15min", html)
        self.assertIn("Réserver 15 minutes", html)

    def test_no_calendly_url_means_no_dangling_button(self):
        html = audit_report.render_audit_html("Camille", self._audit(), None, "")
        self.assertNotIn("Réserver 15 minutes", html)

    def test_empty_sections_disappear_instead_of_rendering_empty_titles(self):
        # On cible le TITRE de section (le chapô d'introduction, lui, cite les
        # bannières en toutes lettres et ne doit pas faire passer le test).
        with_banners = audit_report.render_audit_html(
            "Camille",
            self._audit(banners=[{"title": "Cold call", "subtitle": "", "direction": ""}]),
            None,
            "",
        )
        self.assertIn(">3 concepts de bannière</h2>", with_banners)

        without = audit_report.render_audit_html("Camille", self._audit(banners=[]), None, "")
        self.assertNotIn(">3 concepts de bannière</h2>", without)

    def test_model_output_is_escaped(self):
        """Le texte vient d'un modèle : il ne doit pas pouvoir injecter du HTML."""
        audit = self._audit(positioning="<script>alert(1)</script>")
        html = audit_report.render_audit_html("Camille", audit, None, "")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_first_name_only_in_the_greeting(self):
        html = audit_report.render_audit_html("Camille Durand", self._audit(), None, "")
        self.assertIn("Salut Camille,", html)

    def test_missing_name_does_not_produce_an_empty_greeting(self):
        html = audit_report.render_audit_html("", self._audit(), None, "")
        self.assertIn("Salut toi,", html)


class MailerTest(unittest.TestCase):
    def test_disabled_without_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(mailer.enabled())
            # Best-effort : renvoie False, ne lève pas — un e-mail raté ne doit
            # jamais faire échouer la requête du visiteur.
            self.assertFalse(mailer.send_email_safe("a@b.fr", "Sujet", "<p>x</p>"))

    def test_send_email_without_key_raises_for_callers_that_care(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(mailer.MailError):
                mailer.send_email("a@b.fr", "Sujet", "<p>x</p>")

    def test_no_recipient_is_an_error(self):
        with patch.dict(os.environ, {"RESEND_API_KEY": "re_test"}, clear=True):
            with self.assertRaises(mailer.MailError):
                mailer.send_email([], "Sujet", "<p>x</p>")

    def test_internal_recipients_parsed_from_env(self):
        with patch.dict(os.environ, {"AUDIT_LEAD_NOTIFY_TO": "tom@x.fr, alex@x.fr ,"}, clear=True):
            self.assertEqual(mailer.internal_recipients(), ["tom@x.fr", "alex@x.fr"])

    def test_no_internal_recipients_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(mailer.internal_recipients(), [])


class ProcessAuditLeadTest(unittest.TestCase):
    """Le statut en base doit dire la vérité sur ce qui est réellement parti."""

    def test_missing_mail_key_marks_failed_not_sent(self):
        lead = {"id": "lead-1", "status": "pending", "email": "a@b.fr", "full_name": "A B"}
        updates: list[dict] = []
        with patch.object(audit_report.db, "get_audit_lead", return_value=lead), \
             patch.object(audit_report.db, "update_audit_lead", side_effect=lambda _id, patch_: updates.append(patch_)), \
             patch.object(audit_report, "generate_full_audit", return_value=audit_report.normalize_audit({})), \
             patch.object(audit_report.notion_pages, "create_audit_page_safe", return_value=None), \
             patch.object(audit_report.mailer, "enabled", return_value=False):
            audit_report.process_audit_lead("lead-1", "https://calendly.test")
        self.assertEqual(updates[-1]["status"], "failed")
        # L'audit produit n'est pas jeté : il reste rejouable sans repayer l'appel.
        self.assertIn("audit_payload", updates[-1])

    def test_already_sent_lead_is_not_regenerated(self):
        lead = {"id": "lead-1", "status": "sent", "email": "a@b.fr"}
        with patch.object(audit_report.db, "get_audit_lead", return_value=lead), \
             patch.object(audit_report, "generate_full_audit") as gen:
            audit_report.process_audit_lead("lead-1")
        gen.assert_not_called()

    def test_generation_failure_is_recorded(self):
        lead = {"id": "lead-1", "status": "pending", "email": "a@b.fr", "full_name": "A B"}
        updates: list[dict] = []
        with patch.object(audit_report.db, "get_audit_lead", return_value=lead), \
             patch.object(audit_report.db, "update_audit_lead", side_effect=lambda _id, patch_: updates.append(patch_)), \
             patch.object(audit_report, "generate_full_audit", side_effect=RuntimeError("modèle indisponible")):
            audit_report.process_audit_lead("lead-1")
        self.assertEqual(updates[-1]["status"], "failed")
        self.assertIn("modèle indisponible", updates[-1]["error_message"])

    def test_successful_send_marks_sent_and_stores_notion(self):
        lead = {"id": "lead-1", "status": "pending", "email": "a@b.fr", "full_name": "Camille Durand"}
        updates: list[dict] = []
        sent: list[tuple] = []
        with patch.object(audit_report.db, "get_audit_lead", return_value=lead), \
             patch.object(audit_report.db, "update_audit_lead", side_effect=lambda _id, patch_: updates.append(patch_)), \
             patch.object(audit_report.db, "now_iso", return_value="2026-08-08T00:00:00+00:00"), \
             patch.object(audit_report, "generate_full_audit", return_value=audit_report.normalize_audit({"headline": "H"})), \
             patch.object(audit_report.notion_pages, "create_audit_page_safe", return_value={
                 "page_id": "abc", "url": "https://www.notion.so/abc", "public_url": "https://clareo.notion.site/abc",
             }), \
             patch.object(audit_report.mailer, "enabled", return_value=True), \
             patch.object(audit_report.mailer, "send_email", side_effect=lambda *a, **k: sent.append((a, k))):
            audit_report.process_audit_lead("lead-1", "https://calendly.test/15min")
        self.assertEqual(updates[-1]["status"], "sent")
        self.assertEqual(updates[-1]["notion_url"], "https://clareo.notion.site/abc")
        self.assertEqual(len(sent), 1)
        self.assertIn("https://calendly.test/15min", sent[0][0][2])


class NotionBlocksTest(unittest.TestCase):
    def test_audit_to_blocks_contains_headline(self):
        from src import notion_pages
        blocks = notion_pages.audit_to_blocks(
            "Camille Durand",
            audit_report.normalize_audit({"headline": "Coach B2B | LinkedIn", "about": "Texte infos"}),
        )
        types = [b["type"] for b in blocks]
        self.assertIn("heading_2", types)
        self.assertIn("quote", types)
