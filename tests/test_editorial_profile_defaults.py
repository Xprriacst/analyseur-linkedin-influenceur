"""Tests unitaires — valeurs par défaut à la CRÉATION du profil éditorial.

Le Mode Pilote promet « 1 post par jour ». Un compte qui sort de l'onboarding
avec `daily_ideas_enabled = false` découvre donc un écran d'accueil vide et n'a
aucune raison d'aller chercher un interrupteur dont il ignore l'existence.

⚠️ La contrepartie est la règle que ces tests verrouillent : on n'active QU'À la
création. Un profil déjà en base garde son réglage — rallumer l'idée du jour
chez quelqu'un qui l'a volontairement coupée serait un envoi non demandé, en
son nom, sur son LinkedIn.
"""
import unittest
from unittest.mock import patch

from src import db


class _FakeTable:
    def __init__(self, captured: dict):
        self._captured = captured

    def upsert(self, row, on_conflict=None):
        self._captured["row"] = row
        self._captured["on_conflict"] = on_conflict
        return self

    def execute(self):
        return type("Resp", (), {"data": [self._captured["row"]]})()


class _FakeClient:
    def __init__(self, captured: dict):
        self._captured = captured

    def table(self, name):
        self._captured["table"] = name
        return _FakeTable(self._captured)


class UpsertEditorialProfileTest(unittest.TestCase):
    def _upsert(self, existing_profile, payload=None):
        captured: dict = {}
        with patch.object(db, "get_user", return_value={"id": "u1"}), \
             patch.object(db, "client_for_token", return_value=_FakeClient(captured)), \
             patch.object(db, "get_editorial_profile", return_value=existing_profile), \
             patch.object(db, "_clean_editorial_profile", side_effect=lambda p: dict(p or {})):
            db.upsert_editorial_profile("tok", payload or {"display_name": "Alex"})
        return captured.get("row", {})

    def test_creation_enables_the_daily_post(self):
        row = self._upsert(existing_profile=None)
        self.assertIs(row.get("daily_ideas_enabled"), True)

    def test_update_never_touches_the_optin(self):
        row = self._upsert(existing_profile={"user_id": "u1", "daily_ideas_enabled": False})
        self.assertNotIn("daily_ideas_enabled", row)

    def test_update_of_a_profile_that_had_it_on_is_left_alone_too(self):
        row = self._upsert(existing_profile={"user_id": "u1", "daily_ideas_enabled": True})
        self.assertNotIn("daily_ideas_enabled", row)

    def test_explicit_payload_wins_over_the_default(self):
        # `setdefault` et non une écriture sèche : si un jour l'appelant décide,
        # c'est lui qui décide.
        row = self._upsert(
            existing_profile=None,
            payload={"display_name": "Alex", "daily_ideas_enabled": False},
        )
        self.assertIs(row.get("daily_ideas_enabled"), False)

    def test_still_upserts_on_user_id(self):
        captured: dict = {}
        with patch.object(db, "get_user", return_value={"id": "u1"}), \
             patch.object(db, "client_for_token", return_value=_FakeClient(captured)), \
             patch.object(db, "get_editorial_profile", return_value=None), \
             patch.object(db, "_clean_editorial_profile", side_effect=lambda p: dict(p or {})):
            db.upsert_editorial_profile("tok", {"display_name": "Alex"})
        self.assertEqual(captured["on_conflict"], "user_id")
        self.assertEqual(captured["row"]["user_id"], "u1")


if __name__ == "__main__":
    unittest.main()
