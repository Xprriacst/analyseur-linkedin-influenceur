"""Bootstrap du premier post du jour — comptes neufs sans corpus."""
import unittest
from unittest.mock import patch

from src import daily_ideas


class MaybeBootstrapDailyIdeaTest(unittest.TestCase):
    def test_skips_when_today_already_has_an_idea(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}, clear=False), \
             patch.object(daily_ideas.db, "admin_enabled", return_value=True), \
             patch.object(daily_ideas.db, "get_user", return_value={"id": "u1"}), \
             patch.object(daily_ideas.db, "daily_idea_exists", return_value=True):
            self.assertFalse(daily_ideas.maybe_bootstrap_daily_idea("tok"))

    def test_skips_when_optin_is_off(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}, clear=False), \
             patch.object(daily_ideas.db, "admin_enabled", return_value=True), \
             patch.object(daily_ideas.db, "get_user", return_value={"id": "u1"}), \
             patch.object(daily_ideas.db, "daily_idea_exists", return_value=False), \
             patch.object(
                 daily_ideas.db,
                 "get_editorial_profile",
                 return_value={"daily_ideas_enabled": False},
             ):
            self.assertFalse(daily_ideas.maybe_bootstrap_daily_idea("tok"))

    def test_skips_when_user_already_had_past_daily_ideas(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}, clear=False), \
             patch.object(daily_ideas.db, "admin_enabled", return_value=True), \
             patch.object(daily_ideas.db, "get_user", return_value={"id": "u1"}), \
             patch.object(daily_ideas.db, "daily_idea_exists", return_value=False), \
             patch.object(
                 daily_ideas.db,
                 "get_editorial_profile",
                 return_value={"daily_ideas_enabled": True},
             ), \
             patch.object(
                 daily_ideas.db,
                 "list_daily_ideas",
                 return_value=[{"idea_date": "2026-09-01", "idea_markdown": "x"}],
             ):
            self.assertFalse(daily_ideas.maybe_bootstrap_daily_idea("tok"))

    def test_bootstraps_from_profile_when_no_corpus(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}, clear=False), \
             patch.object(daily_ideas.db, "admin_enabled", return_value=True), \
             patch.object(daily_ideas.db, "get_user", return_value={"id": "u1"}), \
             patch.object(daily_ideas.db, "daily_idea_exists", return_value=False), \
             patch.object(
                 daily_ideas.db,
                 "get_editorial_profile",
                 return_value={"daily_ideas_enabled": True},
             ), \
             patch.object(daily_ideas.db, "list_daily_ideas", return_value=[]), \
             patch.object(daily_ideas.db, "list_generated_posts", return_value=[]), \
             patch.object(daily_ideas.db, "get_corpus_for_user", return_value=[]), \
             patch.object(
                 daily_ideas.db,
                 "get_user_ai_context",
                 return_value={"display_name": "Test", "business_description": "SaaS"},
             ), \
             patch.object(
                 daily_ideas,
                 "generate_posts",
                 return_value=[{"post": "Mon premier post LinkedIn."}],
             ) as gen, \
             patch.object(daily_ideas.db, "replace_daily_idea", return_value={"id": "d1"}) as save:
            self.assertTrue(daily_ideas.maybe_bootstrap_daily_idea("tok"))
            gen.assert_called_once()
            save.assert_called_once()
            self.assertIn("Mon premier post", save.call_args[0][1])

    def test_never_raises_on_failure(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}, clear=False), \
             patch.object(daily_ideas.db, "admin_enabled", return_value=True), \
             patch.object(daily_ideas.db, "get_user", side_effect=RuntimeError("boom")):
            self.assertFalse(daily_ideas.maybe_bootstrap_daily_idea("tok"))


if __name__ == "__main__":
    unittest.main()
