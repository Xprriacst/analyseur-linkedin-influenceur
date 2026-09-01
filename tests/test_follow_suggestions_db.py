"""Tests unitaires — `db.list_influencer_cache_candidates`.

Source des suggestions « à suivre » (ticket Notion « Onboarding —
propositions automatiques de profils LinkedIn à suivre »). Ce test verrouille
la seule chose qui compte vraiment ici : la projection.

`influencer_cache` est un cache d'analyses MUTUALISÉ entre tous les comptes.
Y ajouter `raw_profile` ou `synthesis` à la projection passerait sans erreur
et exposerait à un client le contenu brut analysé pour un autre — une fuite
parfaitement silencieuse. Le test échoue si quelqu'un élargit le `select`.
"""
import unittest
from unittest.mock import patch

from src import db


class _FakeQuery:
    def __init__(self, rows: list[dict], captured: dict):
        self._rows = rows
        self._captured = captured

    def select(self, cols):
        self._captured["select"] = cols
        return self

    def eq(self, key, value):
        self._captured.setdefault("eq", []).append((key, value))
        return self

    def order(self, key, desc=False):
        self._captured["order"] = (key, desc)
        return self

    def limit(self, n):
        self._captured["limit"] = n
        return self

    def execute(self):
        return type("Resp", (), {"data": self._rows})()


class _FakeAdminClient:
    def __init__(self, rows: list[dict]):
        self._rows = rows
        self.captured: dict = {}

    def table(self, name):
        assert name == "influencer_cache"
        return _FakeQuery(self._rows, self.captured)


class ListInfluencerCacheCandidatesTest(unittest.TestCase):
    def test_noop_when_service_role_absent(self):
        with patch.object(db, "admin_enabled", return_value=False), \
             patch.object(db, "admin_client") as client:
            self.assertEqual(db.list_influencer_cache_candidates(), [])
        client.assert_not_called()

    def test_returns_rows_and_projects_only_public_fields(self):
        rows = [
            {"id": "c1", "handle": "marie", "name": "Marie", "headline": "Coach B2B",
             "follower_count": 100, "profile_url": "https://www.linkedin.com/in/marie/"},
        ]
        fake = _FakeAdminClient(rows)
        with patch.object(db, "admin_enabled", return_value=True), \
             patch.object(db, "admin_client", return_value=fake):
            out = db.list_influencer_cache_candidates(limit=50)
        self.assertEqual(out, rows)
        # Jamais raw_profile/synthesis (données brutes potentiellement sensibles),
        # ni user_id (la table n'en a de toute façon pas).
        cols = fake.captured["select"]
        self.assertNotIn("raw_profile", cols)
        self.assertNotIn("synthesis", cols)
        self.assertNotIn("user_id", cols)
        # …mais l'URL publique doit bien y être : l'écran en fait un lien vers
        # le profil LinkedIn, sans elle la suggestion n'est pas vérifiable.
        self.assertIn("profile_url", cols)
        self.assertIn(("platform", "linkedin"), fake.captured["eq"])
        self.assertEqual(fake.captured["limit"], 50)

    def test_failure_is_swallowed(self):
        with patch.object(db, "admin_enabled", return_value=True), \
             patch.object(db, "admin_client", side_effect=RuntimeError("boom")):
            self.assertEqual(db.list_influencer_cache_candidates(), [])


if __name__ == "__main__":
    unittest.main()
