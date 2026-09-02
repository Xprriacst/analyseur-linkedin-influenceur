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
            # Sans recent_posts, le bootstrap réécrirait le même post chaque jour
            # sans jamais avoir lu LinkedIn — le kwarg est le contrat, pas un confort.
            self.assertIn("recent_posts", gen.call_args.kwargs)

    def test_never_raises_on_failure(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}, clear=False), \
             patch.object(daily_ideas.db, "admin_enabled", return_value=True), \
             patch.object(daily_ideas.db, "get_user", side_effect=RuntimeError("boom")):
            self.assertFalse(daily_ideas.maybe_bootstrap_daily_idea("tok"))


class RecentPostsForGenerationTest(unittest.TestCase):
    def test_skips_unipile_when_own_linkedin_posts_are_already_in_memory(self):
        own = [{"text": "Post live.", "status": daily_ideas.db.OWN_LINKEDIN_STATUS}]
        with patch.object(daily_ideas.db, "get_recent_post_memory_for_user", return_value=own), \
             patch.object(daily_ideas, "_unipile_own_posts_memory") as unipile_mem:
            out = daily_ideas.recent_posts_for_generation(user_id="u1")
        unipile_mem.assert_not_called()
        self.assertEqual(out[0]["status"], daily_ideas.db.OWN_LINKEDIN_STATUS)

    def test_unipile_fills_in_when_cibl_has_no_live_posts(self):
        cibl = [{"text": "Brouillon Cibl.", "status": "généré (brouillon)"}]
        extra = [{"text": "Vrai post LinkedIn.", "status": daily_ideas.db.OWN_LINKEDIN_STATUS}]
        with patch.object(daily_ideas.db, "get_recent_post_memory_for_user", return_value=cibl), \
             patch.object(
                 daily_ideas.db,
                 "admin_linkedin_outreach_account",
                 return_value={"unipile_account_id": "acc-1"},
             ), \
             patch.object(daily_ideas, "_unipile_own_posts_memory", return_value=extra):
            out = daily_ideas.recent_posts_for_generation(user_id="u1")
        self.assertEqual(out[0]["status"], daily_ideas.db.OWN_LINKEDIN_STATUS)
        self.assertEqual(out[0]["text"], "Vrai post LinkedIn.")


if __name__ == "__main__":
    unittest.main()
