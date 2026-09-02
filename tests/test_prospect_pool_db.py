"""Tests unitaires — projection et écriture `prospect_cache` / copie vers `leads`.

Même discipline que `tests/test_follow_suggestions_db.py` : élargir le
`select` du vivier passerait sans erreur et exposerait un jour trop de
champs. Le test échoue si la projection s'élargit.

Et : `admin_insert_pool_lead` écrit le `user_id` du RECEVEUR, pose un
signal `origin=prospect_pool`, et ne lève jamais.
"""
from __future__ import annotations

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

    def in_(self, key, values):
        self._captured.setdefault("in_", []).append((key, list(values)))
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

    def insert(self, row):
        self._captured["insert"] = row
        if isinstance(row, list):
            self._rows = list(row)
        else:
            self._rows = [row]
        return self

    def update(self, patch):
        self._captured["update"] = patch
        return self

    def execute(self):
        return type("Resp", (), {"data": self._rows})()


class _FakeAdminClient:
    def __init__(self, rows: list[dict] | None = None):
        self._rows = rows or []
        self.captured: dict = {}

    def table(self, name):
        self.captured["table"] = name
        return _FakeQuery(self._rows, self.captured)


class ListProspectCacheCandidatesTest(unittest.TestCase):
    def test_noop_when_service_role_absent(self):
        with patch.object(db, "admin_enabled", return_value=False), \
             patch.object(db, "admin_client") as client:
            self.assertEqual(db.list_prospect_cache_candidates(), [])
        client.assert_not_called()

    def test_projects_only_public_fields(self):
        rows = [{
            "id": "p1",
            "profile_url": "https://www.linkedin.com/in/marie",
            "name": "Marie",
            "headline": "Pharmacienne",
            "created_at": "2026-09-02T00:00:00Z",
        }]
        fake = _FakeAdminClient(rows)
        with patch.object(db, "admin_enabled", return_value=True), \
             patch.object(db, "admin_client", return_value=fake):
            out = db.list_prospect_cache_candidates(limit=80)
        self.assertEqual(out, rows)
        cols = fake.captured["select"]
        self.assertEqual(fake.captured["table"], "prospect_cache")
        for forbidden in ("raw_profile", "synthesis", "user_id", "comment_text", "signals"):
            self.assertNotIn(forbidden, cols)
        for required in ("profile_url", "name", "headline"):
            self.assertIn(required, cols)
        self.assertEqual(fake.captured["limit"], 80)

    def test_failure_is_swallowed(self):
        with patch.object(db, "admin_enabled", return_value=True), \
             patch.object(db, "admin_client", side_effect=RuntimeError("boom")):
            self.assertEqual(db.list_prospect_cache_candidates(), [])


class AdminInsertPoolLeadTest(unittest.TestCase):
    def test_writes_receiver_user_id_and_pool_signal(self):
        fake = _FakeAdminClient()
        with patch.object(db, "admin_enabled", return_value=True), \
             patch.object(db, "admin_client", return_value=fake):
            out = db.admin_insert_pool_lead(
                "user-lia",
                profile_url="https://www.linkedin.com/in/marie",
                name="Marie",
                headline="Pharmacienne",
                score=75,
                score_reason="correspond à ta niche : pharmacie",
                matched_keywords=["pharmacie"],
            )
        self.assertEqual(fake.captured["table"], "leads")
        row = fake.captured["insert"]
        self.assertEqual(row["user_id"], "user-lia")
        self.assertNotEqual(row["user_id"], "admin-alex")
        self.assertEqual(row["score"], 75)
        self.assertIsNone(row["comment_text"])
        self.assertEqual(row["signals"][0]["origin"], "prospect_pool")
        self.assertEqual(out["user_id"], "user-lia")

    def test_unique_violation_returns_none(self):
        class Boom:
            def table(self, _name):
                raise RuntimeError("duplicate key")

        with patch.object(db, "admin_enabled", return_value=True), \
             patch.object(db, "admin_client", return_value=Boom()):
            self.assertIsNone(db.admin_insert_pool_lead(
                "user-lia",
                profile_url="https://www.linkedin.com/in/marie",
                name="Marie",
                headline=None,
                score=75,
                score_reason=None,
                matched_keywords=[],
            ))


class UpsertProspectCacheTest(unittest.TestCase):
    def test_url_only_does_not_wipe_existing_name(self):
        existing = [{
            "id": "p1",
            "profile_url": "https://www.linkedin.com/in/marie",
            "name": "Marie Pharmacienne",
            "headline": "Titulaire",
            "created_at": "2026-09-01T00:00:00Z",
        }]
        fake = _FakeAdminClient(existing)
        with patch.object(db, "admin_enabled", return_value=True), \
             patch.object(db, "admin_client", return_value=fake):
            out = db.upsert_prospect_cache([
                {"profile_url": "https://www.linkedin.com/in/marie", "name": None, "headline": None},
            ])
        self.assertEqual(out["skipped"], 1)
        self.assertEqual(out["inserted"], 0)
        self.assertNotIn("update", fake.captured)


if __name__ == "__main__":
    unittest.main()
