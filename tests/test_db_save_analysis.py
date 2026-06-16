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

    def update(self, fields):
        self.last_operation = "update"
        self.calls.append(("update", self.name, fields, None))
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

    def order(self, column, desc=False):
        self.calls.append(("order", self.name, column, desc))
        return self

    def limit(self, value):
        self.calls.append(("limit", self.name, value, None))
        return self

    def execute(self):
        if self.name == "influencers" and self.last_operation == "upsert":
            return FakeResponse([{"id": "influencer-1"}])
        if self.name == "analyses" and self.last_operation == "upsert":
            return FakeResponse([{"id": "analysis-1"}])
        if self.name == "generated_posts" and self.last_operation == "insert":
            insert_call = next(
                call for call in reversed(self.calls)
                if call[0] == "insert" and call[1] == "generated_posts"
            )
            rows = insert_call[2]
            return FakeResponse([{**row, "id": f"post-{i}"} for i, row in enumerate(rows)])
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

    def test_saves_generated_post_variants(self):
        client = FakeClient()
        variants = [
            {
                "hook_type": "question",
                "strategy": "Tester un angle direct",
                "predicted_lift": "+40%",
                "post": "Et si ton process IA tenait en 3 questions ?",
            },
            {
                "hook_type": "story+result",
                "strategy": "Preuve narrative",
                "predicted_lift": "+60%",
                "post": "Hier, un client a gagne 4h avec ce workflow.",
            },
        ]

        with (
            patch.object(db, "supabase_enabled", return_value=True),
            patch.object(db, "get_user", return_value={"id": "user-1", "email": "ada@example.com"}),
            patch.object(db, "client_for_token", return_value=client),
        ):
            saved = db.save_generated_posts("token", "Automatiser la prospection", variants, idea_id="idea-1")

        self.assertEqual([row["id"] for row in saved], ["post-0", "post-1"])
        post_inserts = [
            call for call in client.calls
            if call[0] == "insert" and call[1] == "generated_posts"
        ]
        self.assertEqual(len(post_inserts), 1)
        rows = post_inserts[0][2]
        self.assertEqual(rows[0]["user_id"], "user-1")
        self.assertEqual(rows[0]["idea_id"], "idea-1")
        self.assertEqual(rows[0]["topic"], "Automatiser la prospection")
        self.assertEqual(rows[0]["post_text"], variants[0]["post"])
        self.assertEqual(rows[0]["variant_index"], 0)
        self.assertEqual(rows[0]["status"], "draft")


if __name__ == "__main__":
    unittest.main()
