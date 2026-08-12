"""Photos jointes aux idées du réservoir (idea_seeds.media_items)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src import daily_ideas


class AddIdeaSeedMediaTest(unittest.TestCase):
    """add_idea_seed / update_idea_seed acceptent media_items."""

    @patch("src.db.client_for_token")
    @patch("src.db.get_user", return_value={"id": "u1"})
    @patch("src.db.supabase_enabled", return_value=True)
    def test_add_persists_media_items(self, _en, _user, client_for):
        from src import db as dbmod

        db = MagicMock()
        client_for.return_value = db
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )
        inserted = {"id": "s1", "text": "Mon bien", "media_items": [{"type": "image", "url": "https://cdn.example/a.jpg"}]}
        db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[inserted])

        row = dbmod.add_idea_seed(
            "tok",
            "Mon bien",
            media_items=[{"type": "image", "url": "https://cdn.example/a.jpg"}],
        )
        self.assertEqual(row["media_items"][0]["url"], "https://cdn.example/a.jpg")
        insert_payload = db.table.return_value.insert.call_args[0][0]
        self.assertEqual(insert_payload["media_items"][0]["url"], "https://cdn.example/a.jpg")

    @patch("src.db.client_for_token")
    @patch("src.db.get_user", return_value={"id": "u1"})
    @patch("src.db.supabase_enabled", return_value=True)
    def test_update_clears_media_with_empty_list(self, _en, _user, client_for):
        from src import db as dbmod

        db = MagicMock()
        client_for.return_value = db
        updated = {"id": "s1", "text": "Mon bien", "media_items": []}
        db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[updated]
        )

        row = dbmod.update_idea_seed("tok", "s1", media_items=[])
        self.assertEqual(row["media_items"], [])
        update_payload = db.table.return_value.update.call_args[0][0]
        self.assertEqual(update_payload["media_items"], [])


class DailyIdeaUsesSeedMediaTest(unittest.TestCase):
    """Le cron d'idée du jour reprend les photos jointes à la seed si pas d'annonce."""

    @patch("src.daily_ideas.generate_posts")
    @patch("src.daily_ideas.build_benchmark", return_value=([], {}))
    @patch("src.daily_ideas.enrich_influencers", return_value=[{"handle": "x"}])
    @patch("src.daily_ideas.db")
    def test_seed_media_becomes_image_url(self, fake_db, _enr, _bench, gen_posts):
        fake_db.daily_idea_exists.return_value = False
        fake_db.get_corpus_for_user.return_value = [{"handle": "x"}]
        fake_db.get_ai_context_for_user.return_value = {}
        fake_db.pop_unused_seed.return_value = {
            "id": "seed-1",
            "text": "Visite d'un T3 lumineux à Nantes",
            "comment": None,
            "media_items": [{"type": "image", "url": "https://cdn.example/bien.jpg"}],
        }
        fake_db.get_recent_post_memory_for_user.return_value = []
        gen_posts.return_value = [{"post": "Voici le T3…", "editorial_role": "storyteller"}]

        ok = daily_ideas._generate_for_user("u1", "2026-08-11")
        self.assertTrue(ok)
        kwargs = fake_db.insert_daily_idea.call_args.kwargs
        self.assertEqual(kwargs.get("image_url") or fake_db.insert_daily_idea.call_args[1].get("image_url"), "https://cdn.example/bien.jpg")


if __name__ == "__main__":
    unittest.main()
