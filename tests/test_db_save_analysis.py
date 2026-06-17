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


class FakeProgressTable:
    def __init__(self, name, data, missing):
        self.name = name
        self.data = data
        self.missing = missing
        self.filters = []
        self.limit_count = None

    def select(self, columns):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, column, desc=False):
        return self

    def limit(self, count):
        self.limit_count = count
        return self

    def execute(self):
        if self.name in self.missing:
            raise RuntimeError(f"table {self.name} does not exist")
        rows = list(self.data.get(self.name, []))
        for column, value in self.filters:
            rows = [row for row in rows if row.get(column) == value]
        if self.limit_count is not None:
            rows = rows[:self.limit_count]
        return FakeResponse(rows)


class FakeProgressClient:
    def __init__(self, data, missing=None):
        self.data = data
        self.missing = set(missing or [])

    def table(self, name):
        return FakeProgressTable(name, self.data, self.missing)


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


class DashboardProgressTest(unittest.TestCase):
    def test_progress_tolerates_missing_future_tables(self):
        client = FakeProgressClient(
            {
                "influencers": [
                    {"id": "inf-1", "user_id": "user-1", "handle": "ada", "name": "Ada"}
                ],
                "analyses": [
                    {
                        "id": "analysis-1",
                        "user_id": "user-1",
                        "handle": "ada",
                        "updated_at": "2026-06-17T09:00:00Z",
                        "usage": {
                            "apify": {"items": 25, "runs": 2, "estimated_cost_usd": 0.04},
                            "anthropic": {
                                "calls": 1,
                                "input_tokens": 100,
                                "output_tokens": 50,
                                "estimated_cost_usd": 0.02,
                            },
                        },
                        "influencers": {"name": "Ada"},
                    }
                ],
                "generated_ideas": [],
            },
            missing={
                "generated_posts",
                "linkedin_connections",
                "user_credits",
                "user_draft_ideas",
            },
        )
        jobs = [
            {
                "id": "job-1",
                "status": "running",
                "items": [
                    {"id": "item-1", "status": "done"},
                    {"id": "item-2", "status": "error"},
                ],
            }
        ]

        with (
            patch.object(db, "get_user", return_value={"id": "user-1", "email": "ada@example.com"}),
            patch.object(db, "client_for_token", return_value=client),
            patch.object(db, "list_jobs", return_value=jobs),
        ):
            progress = db.get_dashboard_progress("token")

        self.assertEqual(progress["next_action"]["key"], "follow_running_job")
        self.assertEqual(progress["sections"][0]["metrics"]["job_items_failed"], 1)
        self.assertEqual(progress["sections"][2]["status"], "unavailable")
        self.assertEqual(
            progress["sections"][4]["metrics"]["estimated_cost_usd"],
            0.06,
        )


if __name__ == "__main__":
    unittest.main()
