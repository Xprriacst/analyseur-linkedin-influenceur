"""Tunnel fondateurs SaaS (/founders) : grille de paliers ACV + essai gratuit Stripe.

Deux sujets, une même préoccupation : **ce qui est montré doit être ce qui se
passe**. Un tunnel d'acquisition peut mentir de deux façons parfaitement
silencieuses — afficher des montants calculés sur une grille qui ne correspond
pas à l'audience, et promettre un essai que la session Checkout n'accorde pas.
Les tests ci-dessous ferment ces deux portes.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import audit_projection as proj  # noqa: E402
from src import stripe_billing  # noqa: E402


class SaasBandsTest(unittest.TestCase):
    def test_saas_audience_uses_its_own_bands(self):
        """Les paliers SaaS raisonnent en ACV : ce ne sont pas ceux de /start."""
        saas = proj.project_all_bands(followers=1200, audience="saas")
        default = proj.project_all_bands(followers=1200)
        self.assertNotEqual(
            [b["key"] for b in saas["bands"]],
            [b["key"] for b in default["bands"]],
        )
        self.assertEqual(
            [b["key"] for b in saas["bands"]],
            [b["key"] for b in proj.SAAS_DEAL_BANDS],
        )

    def test_saas_default_band_exists_in_its_own_grid(self):
        """Un `default_band` absent de la grille ferait retomber l'écran sur le 1er palier."""
        for audience in ("saas", "default", None):
            with self.subTest(audience=audience):
                result = proj.project_all_bands(followers=500, audience=audience)
                keys = [b["key"] for b in result["bands"]]
                self.assertIn(result["default_band"], keys)

    def test_saas_bands_say_the_amounts_are_arr(self):
        """Le montant projeté est de l'ARR signé : le dire, sinon on promet ×12."""
        result = proj.project_all_bands(followers=1200, audience="saas")
        for band in result["bands"]:
            with self.subTest(band=band["key"]):
                self.assertTrue(any("ARR" in line for line in band["assumptions"]))
        self.assertIn("ARR", result["revenue_label"])

    def test_default_audience_never_mentions_arr(self):
        """La grille générique parle de prestation : y glisser de l'ARR serait faux."""
        result = proj.project_all_bands(followers=1200)
        for band in result["bands"]:
            self.assertFalse(any("ARR" in line for line in band["assumptions"]))
        self.assertNotIn("ARR", result["revenue_label"])

    def test_unknown_audience_falls_back_instead_of_breaking(self):
        """Une audience inconnue (URL de campagne fautive) dégrade, elle ne casse pas."""
        result = proj.project_all_bands(followers=1200, audience="fondateurs-de-licornes")
        self.assertEqual(
            [b["key"] for b in result["bands"]],
            [b["key"] for b in proj.DEAL_BANDS],
        )

    def test_prospecting_math_is_shared_between_audiences(self):
        """Seuls les paliers changent : le moteur d'envoi, lui, est le même."""
        saas = proj.project_all_bands(followers=1200, audience="saas")["bands"][0]["projection"]
        default = proj.project_all_bands(followers=1200)["bands"][0]["projection"]
        self.assertEqual(saas["relations_per_month"], default["relations_per_month"])
        self.assertEqual(saas["followers_after"], default["followers_after"])

    def test_labels_travel_with_the_projection(self):
        """Le front n'invente pas les libellés : ils viennent avec les chiffres."""
        result = proj.project_all_bands(followers=10, audience="saas")
        self.assertTrue(result["deal_label"])
        self.assertTrue(result["revenue_label"])


class TrialEligibilityTest(unittest.TestCase):
    """La règle « un seul essai, et seulement pour un premier abonnement »."""

    def test_fresh_account_gets_the_trial(self):
        with patch.dict(os.environ, {"STRIPE_TRIAL_DAYS": "7"}, clear=False):
            self.assertEqual(stripe_billing.granted_trial_days(None), 7)
            self.assertEqual(stripe_billing.granted_trial_days({}), 7)

    def test_customer_without_subscription_still_gets_the_trial(self):
        """Le client Stripe est créé dès l'affichage de la page : il ne prouve rien."""
        with patch.dict(os.environ, {"STRIPE_TRIAL_DAYS": "7"}, clear=False):
            self.assertEqual(
                stripe_billing.granted_trial_days({"stripe_customer_id": "cus_123"}), 7
            )

    def test_former_subscriber_gets_no_second_trial(self):
        """Sans cette garde, un abonné résilié se réoffre un mois gratuit à volonté."""
        with patch.dict(os.environ, {"STRIPE_TRIAL_DAYS": "7"}, clear=False):
            self.assertEqual(stripe_billing.granted_trial_days({"status": "canceled"}), 0)
            self.assertEqual(
                stripe_billing.granted_trial_days({"stripe_subscription_id": "sub_1"}), 0
            )

    def test_not_requested_means_no_trial(self):
        with patch.dict(os.environ, {"STRIPE_TRIAL_DAYS": "7"}, clear=False):
            self.assertEqual(stripe_billing.granted_trial_days({}, requested=False), 0)

    def test_trial_can_be_switched_off_by_configuration(self):
        with patch.dict(os.environ, {"STRIPE_TRIAL_DAYS": "0"}, clear=False):
            self.assertEqual(stripe_billing.trial_days(), 0)
            self.assertEqual(stripe_billing.granted_trial_days({}), 0)

    def test_misconfigured_duration_cannot_create_a_free_subscription(self):
        """Un « 3650 » saisi de travers ne doit pas offrir dix ans d'accès."""
        with patch.dict(os.environ, {"STRIPE_TRIAL_DAYS": "3650"}, clear=False):
            self.assertLessEqual(stripe_billing.trial_days(), 90)
        with patch.dict(os.environ, {"STRIPE_TRIAL_DAYS": "sept"}, clear=False):
            self.assertEqual(stripe_billing.trial_days(), stripe_billing.DEFAULT_TRIAL_DAYS)
        with patch.dict(os.environ, {"STRIPE_TRIAL_DAYS": "-5"}, clear=False):
            self.assertEqual(stripe_billing.trial_days(), 0)

    def test_trial_credits_default_to_the_plan(self):
        """Un essai qui n'ouvre pas le forfait ne démontre rien du produit."""
        env = {"STRIPE_PLAN_CREDITS": "1000"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("STRIPE_TRIAL_CREDITS", None)
            self.assertEqual(stripe_billing.trial_credits(), 1000)
        with patch.dict(os.environ, {**env, "STRIPE_TRIAL_CREDITS": "300"}, clear=False):
            self.assertEqual(stripe_billing.trial_credits(), 300)


class CheckoutTrialPayloadTest(unittest.TestCase):
    """Ce qui part réellement à Stripe — un essai mal formé se paie en silence."""

    def _session(self, **kwargs):
        captured = {}

        def fake_request(method, path, data=None):
            captured["method"] = method
            captured["path"] = path
            captured["data"] = data
            return {"url": "https://checkout.stripe.com/x"}

        with patch.dict(os.environ, {"STRIPE_PRICE_ID": "price_123"}, clear=False):
            with patch.object(stripe_billing, "_request", fake_request):
                with patch.object(
                    stripe_billing, "ensure_intro_coupon", return_value="cibl_first_month_40"
                ):
                    stripe_billing.create_checkout_session(
                        "cus_1", "user-1", "https://app/ok", "https://app/ko", **kwargs
                    )
        return captured["data"]

    def test_without_trial_nothing_changes(self):
        data = self._session()
        self.assertNotIn("trial_period_days", data["subscription_data"])
        self.assertNotIn("payment_method_collection", data)
        self.assertTrue(data["allow_promotion_codes"])
        self.assertNotIn("discounts", data)

    def test_trial_asks_for_the_card_and_cancels_without_one(self):
        """Sans ces deux réglages, Stripe peut créer un abonnement qui ne sera
        jamais encaissé et que l'app lirait pourtant comme un accès légitime."""
        data = self._session(trial_days=7)
        self.assertEqual(data["subscription_data"]["trial_period_days"], 7)
        self.assertEqual(data["payment_method_collection"], "always")
        self.assertEqual(
            data["subscription_data"]["trial_settings"]["end_behavior"]["missing_payment_method"],
            "cancel",
        )

    def test_trial_keeps_the_account_link(self):
        """Le rattachement au compte app doit survivre à l'essai, sinon le webhook
        crédite dans le vide au moment de la bascule."""
        data = self._session(trial_days=7)
        self.assertEqual(data["client_reference_id"], "user-1")
        self.assertEqual(data["subscription_data"]["metadata"]["user_id"], "user-1")

    def test_zero_days_is_not_a_trial(self):
        data = self._session(trial_days=0)
        self.assertNotIn("trial_period_days", data["subscription_data"])

    def test_trial_applies_the_intro_coupon_and_drops_promo_codes(self):
        """Sans ça, Checkout affiche 49 € alors que le tunnel promet 29,40 €.

        Stripe refuse discounts + allow_promotion_codes ensemble : la remise
        fondateurs est appliquée d'office, le champ CIBLDEMO reste sur /paiement.
        """
        data = self._session(trial_days=7)
        self.assertEqual(data["discounts"], [{"coupon": "cibl_first_month_40"}])
        self.assertNotIn("allow_promotion_codes", data)
        pairs = dict(stripe_billing._flatten(data))
        self.assertEqual(pairs["discounts[0][coupon]"], "cibl_first_month_40")

    def test_intro_amount_is_forty_percent_off(self):
        self.assertEqual(stripe_billing.intro_amount(49), 29.4)
        self.assertEqual(stripe_billing.intro_amount(None), None)

    def test_intro_coupon_is_repeating_one_month_not_once(self):
        """`duration=once` se consomme sur la facture d'essai à 0 €."""
        captured = {}

        def fake_request(method, path, data=None):
            captured["method"] = method
            captured["path"] = path
            captured["data"] = data
            if method == "GET":
                raise stripe_billing.StripeError("Stripe 404 : No such coupon")
            return {"id": "cibl_first_month_40"}

        with patch.object(stripe_billing, "_request", fake_request):
            cid = stripe_billing.ensure_intro_coupon()
        self.assertEqual(cid, "cibl_first_month_40")
        self.assertEqual(captured["data"]["percent_off"], 40)
        self.assertEqual(captured["data"]["duration"], "repeating")
        self.assertEqual(captured["data"]["duration_in_months"], 1)
        self.assertNotEqual(captured["data"]["duration"], "once")

    def test_intro_coupon_reuses_an_existing_one(self):
        calls = []

        def fake_request(method, path, data=None):
            calls.append((method, path))
            return {"id": "cibl_first_month_40"}

        with patch.object(stripe_billing, "_request", fake_request):
            cid = stripe_billing.ensure_intro_coupon()
        self.assertEqual(cid, "cibl_first_month_40")
        self.assertEqual(calls, [("GET", "/coupons/cibl_first_month_40")])

    def test_trial_survives_the_form_encoding(self):
        """Le payload est aplati en `a[b][c]` avant l'envoi : vérifié de bout en bout."""
        pairs = dict(stripe_billing._flatten(self._session(trial_days=7)))
        self.assertEqual(pairs["subscription_data[trial_period_days]"], "7")
        self.assertEqual(
            pairs["subscription_data[trial_settings][end_behavior][missing_payment_method]"],
            "cancel",
        )


class PreviewWithoutLinkedinTest(unittest.TestCase):
    """Le tunnel fondateurs n'analyse qu'un SITE : le modèle ne doit rien dire du compte.

    C'est un vrai bug remonté par Alex sur dev : la preview affirmait « ta présence
    LinkedIn est quasi inexistante » à partir d'un site, sans avoir lu le moindre
    profil. Faux, invérifiable, et dit au prospect en plein argumentaire.
    """

    def _prompt_for(self, seed):
        from unittest.mock import patch
        from src import llm

        captured = {}

        def fake_call(system, user, **kwargs):
            captured["system"] = system
            captured["user"] = user
            return {"preview": {
                "niche": "n", "summary": "s",
                "strengths": ["a"], "improvements": ["b"],
            }}

        with patch.object(llm, "_call", fake_call):
            llm.draft_onboarding_preview(seed)
        return captured

    def test_website_only_forbids_any_claim_about_the_account(self):
        c = self._prompt_for({"website_public_summary": {"summary": "un saas"}})
        self.assertIn("INTERDICTION ABSOLUE", c["system"])
        self.assertIn("aucun compte LinkedIn", c["user"])
        self.assertIn("ta présence LinkedIn est", c["user"])  # l'exemple à NE PAS écrire

    def test_linkedin_sources_keep_the_original_prompt(self):
        c = self._prompt_for({"linkedin_apify_profile": {"profile": {"name": "X"}}})
        self.assertNotIn("INTERDICTION ABSOLUE", c["system"])
        self.assertIn("Ancre-toi sur les posts fournis", c["user"])

    def test_json_schema_survives_the_formatting(self):
        """Le schéma est passé dans une f-string : ses accolades doivent survivre."""
        c = self._prompt_for({"website_public_summary": {"summary": "x"}})
        self.assertIn('"preview": {', c["user"])
        self.assertIn('"improvements"', c["user"])


if __name__ == "__main__":
    unittest.main()
