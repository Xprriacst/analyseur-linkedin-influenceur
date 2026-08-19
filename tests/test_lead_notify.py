"""Alerte e-mail « nouveau lead » (src/lead_notify.py).

Ce que ces tests verrouillent — les propriétés dont la perte serait SILENCIEUSE :

- **exactement une fois** : la réservation en base commande l'envoi. Si elle
  échoue (doublon, ou base indisponible), aucun e-mail ne part — sans ça, un
  cron qui tourne toutes les 10 min ré-enverrait le même lead indéfiniment ;
- **rien n'est perdu quand Resend hoquette** : la réservation est RENDUE, donc
  le passage suivant retente. L'oublier perdrait le lead pour toujours, en
  laissant croire que le travail est fait ;
- **le délai de grâce** : un compte sans profil attend (l'e-mail serait vide de
  tout ce qui sert à rappeler la personne), mais jamais au-delà du délai —
  quelqu'un qui referme l'onglet doit quand même être signalé ;
- **best-effort de bout en bout** : ni une panne de Resend ni une panne de base
  ne peuvent faire échouer l'inscription ou le paiement qui les a déclenchées ;
- **le contenu** : l'e-mail « compte créé » porte bien ce qui permet d'agir
  (nom, LinkedIn, offre, cible) quand le profil existe.

Aucun réseau, aucune base : `db` et `mailer` sont remplacés.
"""

import datetime
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import lead_notify  # noqa: E402

NOW = datetime.datetime(2026, 8, 19, 9, 56, tzinfo=datetime.timezone.utc)

PROFILE = {
    "display_name": "Emmanuel Preizal",
    "industry": "IA & Data",
    "core_offer": "Des prestations sur-mesure",
    "target_audience": "Dirigeants de PME, Freelances & solopreneurs",
    "linkedin_objective": "Générer des leads",
    "linkedin_url": "https://www.linkedin.com/in/emmanuelpreizal/",
    "location": "Portugal",
    "business_description": "Consultant automatisation no-code.",
}


class RenderTest(unittest.TestCase):
    def test_signup_email_porte_de_quoi_rappeler_la_personne(self):
        subject, html = lead_notify.render_signup("a@b.com", NOW, PROFILE)
        self.assertIn("Emmanuel Preizal", subject)
        self.assertIn("IA & Data", subject)
        for expected in (
            "a@b.com",
            "Des prestations sur-mesure",
            "Dirigeants de PME",
            "linkedin.com/in/emmanuelpreizal",
        ):
            self.assertIn(expected, html)

    def test_signup_sans_profil_le_dit_au_lieu_de_mentir(self):
        subject, html = lead_notify.render_signup("a@b.com", NOW, None)
        self.assertIn("a@b.com", subject)
        self.assertIn("aucun profil", html)

    def test_html_injecte_est_echappe(self):
        # Le nom vient d'une analyse IA d'une page publique : il n'est pas de confiance.
        _, html = lead_notify.render_signup(
            "a@b.com", NOW, {**PROFILE, "display_name": "<script>x</script>"}
        )
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_optin_et_abonnement_ont_des_sujets_distincts(self):
        optin, _ = lead_notify.render_optin("a@b.com", "onboarding", NOW)
        subscription, _ = lead_notify.render_subscription("a@b.com", NOW, amount=49)
        trial, _ = lead_notify.render_subscription("a@b.com", NOW, trial=True)
        self.assertNotEqual(optin, subscription)
        self.assertIn("Essai", trial)


class RipenessTest(unittest.TestCase):
    def test_profil_present_envoie_tout_de_suite(self):
        self.assertTrue(lead_notify.signup_is_ripe(NOW, True, NOW))

    def test_sans_profil_on_patiente(self):
        just_after = NOW + datetime.timedelta(minutes=2)
        self.assertFalse(lead_notify.signup_is_ripe(NOW, False, just_after))

    def test_mais_jamais_au_dela_du_delai_de_grace(self):
        late = NOW + datetime.timedelta(minutes=lead_notify.SIGNUP_GRACE_MINUTES + 1)
        self.assertTrue(lead_notify.signup_is_ripe(NOW, False, late))


class _Mailer:
    """Faux mailer : enregistre les envois, peut simuler une panne."""

    def __init__(self, ok=True, on=True):
        self.ok, self.on, self.sent = ok, on, []

    def enabled(self):
        return self.on

    def internal_recipients(self):
        return ["alex@example.com"]

    def send_email_safe(self, to, subject, html, reply_to=None):
        self.sent.append((to, subject))
        return self.ok


class SendTest(unittest.TestCase):
    def test_sans_reservation_aucun_envoi(self):
        """Doublon OU base indisponible : dans les deux cas on se tait."""
        mail = _Mailer()
        with patch.object(lead_notify, "mailer", mail), \
             patch.object(lead_notify.db, "admin_claim_lead_notification", return_value=False):
            self.assertFalse(lead_notify.notify_optin("a@b.com"))
        self.assertEqual(mail.sent, [])

    def test_reservation_puis_envoi(self):
        mail = _Mailer()
        with patch.object(lead_notify, "mailer", mail), \
             patch.object(lead_notify.db, "admin_claim_lead_notification", return_value=True):
            self.assertTrue(lead_notify.notify_optin("a@b.com"))
        self.assertEqual(len(mail.sent), 1)

    def test_echec_resend_rend_la_reservation(self):
        """Sinon le lead serait perdu pour toujours en paraissant traité."""
        mail = _Mailer(ok=False)
        with patch.object(lead_notify, "mailer", mail), \
             patch.object(lead_notify.db, "admin_claim_lead_notification", return_value=True), \
             patch.object(lead_notify.db, "admin_release_lead_notification") as release:
            self.assertFalse(lead_notify.notify_optin("a@b.com"))
        release.assert_called_once()

    def test_resend_non_configure_ne_reserve_meme_pas(self):
        mail = _Mailer(on=False)
        with patch.object(lead_notify, "mailer", mail), \
             patch.object(lead_notify.db, "admin_claim_lead_notification") as claim:
            self.assertFalse(lead_notify.notify_optin("a@b.com"))
        claim.assert_not_called()

    def test_une_panne_ne_remonte_jamais_a_l_appelant(self):
        """notify_* est appelé depuis une inscription et depuis un paiement."""
        boom = _Mailer()
        boom.enabled = lambda: (_ for _ in ()).throw(RuntimeError("boum"))
        with patch.object(lead_notify, "mailer", boom):
            self.assertFalse(lead_notify.notify_optin("a@b.com"))
            self.assertFalse(lead_notify.notify_subscription("evt_1", "a@b.com"))

    def test_abonnement_reference_l_evenement_stripe_pas_l_email(self):
        """Stripe rejoue ses événements : la clé de dédoublonnage doit être l'événement."""
        mail = _Mailer()
        with patch.object(lead_notify, "mailer", mail), \
             patch.object(lead_notify.db, "admin_claim_lead_notification", return_value=True) as claim:
            lead_notify.notify_subscription("evt_123", "a@b.com", amount=49)
        claim.assert_called_once_with("subscription", "evt_123")


class ScanTest(unittest.TestCase):
    def _accounts(self, *, minutes_ago):
        now = datetime.datetime.now(datetime.timezone.utc)
        return [{
            "user_id": "u1",
            "email": "a@b.com",
            "created_at": now - datetime.timedelta(minutes=minutes_ago),
        }]

    def test_compte_avec_profil_est_signale(self):
        mail = _Mailer()
        with patch.object(lead_notify, "mailer", mail), \
             patch.object(lead_notify.db, "admin_list_recent_signups",
                          return_value=self._accounts(minutes_ago=1)), \
             patch.object(lead_notify.db, "get_ai_context_for_user", return_value=PROFILE), \
             patch.object(lead_notify.db, "admin_claim_lead_notification", return_value=True):
            self.assertEqual(lead_notify.scan_signups(), 1)
        self.assertIn("Emmanuel Preizal", mail.sent[0][1])

    def test_compte_tout_neuf_sans_profil_attend_le_passage_suivant(self):
        mail = _Mailer()
        with patch.object(lead_notify, "mailer", mail), \
             patch.object(lead_notify.db, "admin_list_recent_signups",
                          return_value=self._accounts(minutes_ago=1)), \
             patch.object(lead_notify.db, "get_ai_context_for_user", return_value=None), \
             patch.object(lead_notify.db, "admin_claim_lead_notification", return_value=True):
            self.assertEqual(lead_notify.scan_signups(), 0)
        self.assertEqual(mail.sent, [])

    def test_profil_illisible_ne_fait_pas_perdre_le_lead(self):
        """La lecture du profil est un confort ; le lead, lui, doit sortir."""
        mail = _Mailer()
        boom = lambda _uid: (_ for _ in ()).throw(RuntimeError("base HS"))  # noqa: E731
        with patch.object(lead_notify, "mailer", mail), \
             patch.object(lead_notify.db, "admin_list_recent_signups",
                          return_value=self._accounts(minutes_ago=120)), \
             patch.object(lead_notify.db, "get_ai_context_for_user", side_effect=boom), \
             patch.object(lead_notify.db, "admin_claim_lead_notification", return_value=True):
            self.assertEqual(lead_notify.scan_signups(), 1)


class RecipientsTest(unittest.TestCase):
    def test_variable_dediee_prioritaire(self):
        with patch.dict(os.environ, {"LEAD_NOTIFY_TO": "a@x.com, b@x.com"}):
            self.assertEqual(lead_notify.recipients(), ["a@x.com", "b@x.com"])

    def test_repli_sur_un_destinataire_par_defaut(self):
        """Poser RESEND_API_KEY doit suffire : une 2ᵉ variable oubliée = alertes muettes."""
        empty = _Mailer()
        empty.internal_recipients = lambda: []
        with patch.dict(os.environ, {"LEAD_NOTIFY_TO": ""}), \
             patch.object(lead_notify, "mailer", empty):
            self.assertEqual(lead_notify.recipients(), [lead_notify._DEFAULT_RECIPIENT])


if __name__ == "__main__":
    unittest.main()
