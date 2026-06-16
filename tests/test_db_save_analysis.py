import unittest
from unittest.mock import patch

import src.db as db


class FakeResponse:
    def __init__(self, data=None):
        self.data = data or []


class FakeTable:
    def __init__(self, name, calls):
        self.name = name
        self.calls = calls
        self.last_operation = None

    def upsert(self, row, on_conflict=None):
        self.last_operation = "upsert"
        self.calls.append(("upsert", self.name, row, on_conflict))
        return self

    def insert(self, rows):
        self.last_operation = "insert"
        self.calls.append(("insert", self.name, rows, None))
        return self

    def delete(self):
        self.last_operation = "delete"
        self.calls.append(("delete", self.name, None, None))
        return self

    def select(self, columns):
        self.calls.append(("select", self.name, columns, None))
        return self

    def eq(self, column, value):
        self.calls.append(("eq", self.name, column, value))
        return self

    def execute(self):
        if self.name == "influencers" and self.last_operation == "upsert":
            return FakeResponse([{"id": "influencer-1"}])
        if self.name == "analyses" and self.last_operation == "upsert":
            return FakeResponse([{"id": "analysis-1"}])
        return FakeResponse()


class FakeClient:
    def __init__(self):
        self.calls = []

    def table(self, name):
        return FakeTable(name, self.calls)


class SaveAnalysisTest(unittest.TestCase):
    def test_replaces_current_analysis_for_influencer(self):
        client = FakeClient()
        result = {
            "handle": "ada-lovelace",
            "profile": {"name": "Ada Lovelace"},
            "posts": [{"url": "https://linkedin.com/feed/update/1", "likes": 7}],
            "markdown": "# Report",
            "stats": {"count": 1},
        }

        with (
            patch.object(db, "get_user", return_value={"id": "user-1", "email": "ada@example.com"}),
            patch.object(db, "client_for_token", return_value=client),
        ):
            saved = db.save_analysis("token", result, posts_limit=10)

        self.assertEqual(saved, {"influencer_id": "influencer-1", "analysis_id": "analysis-1"})
        analysis_upserts = [
            call for call in client.calls
            if call[0] == "upsert" and call[1] == "analyses"
        ]
        self.assertEqual(len(analysis_upserts), 1)
        _, _, row, on_conflict = analysis_upserts[0]
        self.assertEqual(on_conflict, "user_id,influencer_id")
        self.assertEqual(row["user_id"], "user-1")
        self.assertEqual(row["influencer_id"], "influencer-1")
        self.assertEqual(row["handle"], "ada-lovelace")
        self.assertIn("updated_at", row)

        analysis_inserts = [
            call for call in client.calls
            if call[0] == "insert" and call[1] == "analyses"
        ]
        self.assertEqual(analysis_inserts, [])


if __name__ == "__main__":
    unittest.main()
