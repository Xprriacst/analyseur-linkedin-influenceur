"""Client Resend (src/mailer.py).

Le seul test qui compte vraiment ici : la requête porte un **User-Agent
applicatif**. `api.resend.com` est derrière Cloudflare, dont la protection
anti-bot refuse le UA par défaut d'urllib avec un 403 « error code: 1010 » —
un refus qui ne ressemble à aucune erreur de l'API Resend (ni clé invalide,
ni domaine non vérifié). Constaté en réel le 2026-08-19 : aucune alerte ne
partait, et le message d'erreur ne mettait sur aucune piste.

Retirer cet en-tête casserait TOUS les e-mails du produit, silencieusement du
point de vue de l'appelant (`send_email_safe` avale, les alertes se contentent
de ne jamais arriver).
"""

import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import mailer  # noqa: E402


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b'{"id": "abc"}'


class SendEmailRequestTest(unittest.TestCase):
    def _capture(self, **kwargs):
        seen = {}

        def _urlopen(request, timeout=None):
            seen["headers"] = {k.lower(): v for k, v in request.headers.items()}
            seen["body"] = json.loads(request.data.decode())
            seen["url"] = request.full_url
            return _Resp()

        with patch.dict(os.environ, {"RESEND_API_KEY": "re_test"}), \
             patch.object(mailer.urllib.request, "urlopen", _urlopen):
            mailer.send_email(["a@b.com"], "Sujet", "<p>x</p>", **kwargs)
        return seen

    def test_user_agent_applicatif_present(self):
        seen = self._capture()
        self.assertIn("user-agent", seen["headers"])
        ua = seen["headers"]["user-agent"]
        self.assertTrue(ua.startswith("Cibl/"), ua)
        self.assertNotIn("urllib", ua.lower())

    def test_authentification_et_destinataires(self):
        seen = self._capture()
        self.assertEqual(seen["headers"]["authorization"], "Bearer re_test")
        self.assertEqual(seen["body"]["to"], ["a@b.com"])
        self.assertEqual(seen["url"], "https://api.resend.com/emails")

    def test_reply_to_transmis_seulement_si_fourni(self):
        self.assertNotIn("reply_to", self._capture()["body"])
        self.assertEqual(self._capture(reply_to="z@b.com")["body"]["reply_to"], "z@b.com")

    def test_sans_destinataire_on_leve_avant_tout_appel_reseau(self):
        with patch.dict(os.environ, {"RESEND_API_KEY": "re_test"}):
            with self.assertRaises(mailer.MailError):
                mailer.send_email([], "Sujet", "<p>x</p>")

    def test_sans_cle_on_leve(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(mailer.enabled())
            with self.assertRaises(mailer.MailError):
                mailer.send_email(["a@b.com"], "Sujet", "<p>x</p>")


if __name__ == "__main__":
    unittest.main()
