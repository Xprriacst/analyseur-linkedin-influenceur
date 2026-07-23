"""Retry des posts programmés en échec — cron + reset manuel."""
from __future__ import annotations

import unittest
from unittest import mock

from src import db, scheduler


class PublishOneTest(unittest.TestCase):
    def test_marks_failed_when_linkedin_disconnected(self):
        post = {
            "id": "p1",
            "user_id": "u1",
            "post_text": "hello",
            "media_items": [],
            "cross_posts": {},
            "zernio_account_id": None,
        }
        with mock.patch.object(db, "bump_scheduled_publish_attempt") as bump, \
             mock.patch.object(db, "update_scheduled_post_status") as upd:
            result = scheduler.publish_one(post)
        self.assertFalse(result["ok"])
        self.assertIn("non connecté", result["error"])
        bump.assert_called_once_with("p1")
        upd.assert_called_once()
        self.assertEqual(upd.call_args.args[1], "failed")

    def test_publishes_and_marks_published(self):
        post = {
            "id": "p2",
            "user_id": "u1",
            "post_text": "hello",
            "media_items": [],
            "cross_posts": {},
            "zernio_account_id": "acc",
        }
        with mock.patch.object(db, "bump_scheduled_publish_attempt"), \
             mock.patch.object(db, "update_scheduled_post_status") as upd, \
             mock.patch("src.scheduler.zernio.prepare_image_media_items", return_value=[]), \
             mock.patch("src.scheduler.zernio.create_post", return_value={"post": {"_id": "z1"}}):
            result = scheduler.publish_one(post)
        self.assertTrue(result["ok"])
        self.assertEqual(result["zernio_post_id"], "z1")
        upd.assert_called_once()
        self.assertEqual(upd.call_args.args[1], "published")
        self.assertEqual(upd.call_args.kwargs.get("zernio_post_id"), "z1")

    def test_create_post_error_marks_failed(self):
        post = {
            "id": "p3",
            "user_id": "u1",
            "post_text": "hello",
            "media_items": [],
            "cross_posts": {},
            "zernio_account_id": "acc",
        }
        with mock.patch.object(db, "bump_scheduled_publish_attempt"), \
             mock.patch.object(db, "update_scheduled_post_status") as upd, \
             mock.patch("src.scheduler.zernio.prepare_image_media_items", return_value=[]), \
             mock.patch("src.scheduler.zernio.create_post", side_effect=RuntimeError("boom")):
            result = scheduler.publish_one(post)
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["error"])
        self.assertEqual(upd.call_args.args[1], "failed")


class GetDueIncludesFailedRetryTest(unittest.TestCase):
    """Le cron doit rejouer les failed récents (sinon Tom reste bloqué)."""

    def test_merges_pending_and_failed_retries(self):
        pending = [{"id": "a", "user_id": "u1", "post_text": "p", "media_items": [], "cross_posts": {}, "status": "pending", "publish_attempts": 0, "updated_at": "2026-07-22T10:00:00Z"}]
        failed = [{"id": "b", "user_id": "u1", "post_text": "f", "media_items": [], "cross_posts": {}, "status": "failed", "publish_attempts": 1, "updated_at": "2026-07-22T09:00:00Z"}]

        class FakeQuery:
            def __init__(self, rows):
                self._rows = rows
            def select(self, *_a, **_k): return self
            def eq(self, *_a, **_k): return self
            def is_(self, *_a, **_k): return self
            def lte(self, *_a, **_k): return self
            def gte(self, *_a, **_k): return self
            def lt(self, *_a, **_k): return self
            def in_(self, *_a, **_k): return self
            def limit(self, *_a, **_k): return self
            def execute(self):
                return mock.Mock(data=self._rows)

        calls = {"n": 0}

        def fake_table(name):
            calls["n"] += 1
            if name == "scheduled_posts":
                # 1er appel = pending, 2e = failed
                return FakeQuery(pending if calls["n"] == 1 else failed)
            return FakeQuery([{"user_id": "u1", "zernio_account_id": "acc", "zernio_x_account_id": None, "zernio_reddit_account_id": None}])

        fake_admin = mock.Mock()
        fake_admin.table.side_effect = fake_table

        with mock.patch.object(db, "admin_enabled", return_value=True), \
             mock.patch.object(db, "admin_client", return_value=fake_admin):
            due = db.get_due_scheduled_posts()

        ids = {p["id"] for p in due}
        self.assertEqual(ids, {"a", "b"})
        by_id = {p["id"]: p for p in due}
        self.assertEqual(by_id["a"]["zernio_account_id"], "acc")
        self.assertEqual(by_id["b"]["zernio_account_id"], "acc")


if __name__ == "__main__":
    unittest.main()
