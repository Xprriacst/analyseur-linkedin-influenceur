"""Tests unitaires — liste des leads onboarding (dashboard /leads)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import src.db as db


class ListOnboardingLeadsTest(unittest.TestCase):
    def test_merges_audits_and_optins_with_type_and_sort(self) -> None:
        audits_data = [
            {
                "id": "a1",
                "created_at": "2026-08-19T10:00:00+00:00",
                "full_name": "Alice",
                "email": "alice@example.com",
                "phone": "0600000000",
                "status": "pending",
            },
        ]
        optins_data = [
            {
                "id": "o1",
                "created_at": "2026-08-19T12:00:00+00:00",
                "full_name": "",
                "email": "optin@example.com",
                "phone": "",
                "status": "founders_optin",
            },
        ]

        audits_res = MagicMock(data=audits_data)
        optins_res = MagicMock(data=optins_data)
        table = MagicMock()
        table.select.return_value.neq.return_value.order.return_value.limit.return_value.execute.return_value = audits_res
        table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = optins_res
        client = MagicMock()
        client.table.return_value = table

        with patch.object(db, "supabase_enabled", return_value=True), patch.object(
            db, "admin_enabled", return_value=True
        ), patch.object(db, "admin_client", return_value=client):
            rows = db.list_onboarding_leads(limit=50)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["id"], "o1")
        self.assertEqual(rows[0]["type"], "founders_optin")
        self.assertEqual(rows[1]["id"], "a1")
        self.assertEqual(rows[1]["type"], "audit")

    def test_returns_empty_when_supabase_disabled(self) -> None:
        with patch.object(db, "supabase_enabled", return_value=False):
            self.assertEqual(db.list_onboarding_leads(), [])


if __name__ == "__main__":
    unittest.main()
