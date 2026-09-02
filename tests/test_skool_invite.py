"""Invitation Skool du groupe privé — landing `/pilote`.

Le lien n'est servi qu'après inscription. Ces tests verrouillent la fonction
pure : une variable absente ou une URL non-https se comporte comme « pas de
lien » (le front n'affiche pas de bouton, jamais un href `javascript:`).
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import skool_invite  # noqa: E402


class InviteUrlTest(unittest.TestCase):
    def test_absent_returns_none(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SKOOL_INVITE_URL", None)
            self.assertIsNone(skool_invite.invite_url())

    def test_blank_returns_none(self):
        with patch.dict(os.environ, {"SKOOL_INVITE_URL": "   "}):
            self.assertIsNone(skool_invite.invite_url())

    def test_https_is_kept(self):
        url = "https://www.skool.com/example/about"
        with patch.dict(os.environ, {"SKOOL_INVITE_URL": url}):
            self.assertEqual(skool_invite.invite_url(), url)

    def test_http_is_rejected(self):
        with patch.dict(os.environ, {"SKOOL_INVITE_URL": "http://www.skool.com/example"}):
            self.assertIsNone(skool_invite.invite_url())

    def test_javascript_is_rejected(self):
        with patch.dict(os.environ, {"SKOOL_INVITE_URL": "javascript:alert(1)"}):
            self.assertIsNone(skool_invite.invite_url())


if __name__ == "__main__":
    unittest.main()
