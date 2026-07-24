"""Tests collecte de commentateurs — curseur/volume + job de fond (ALE-240)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src import lead_finder


class CreditCostTest(unittest.TestCase):
    def test_proportional_ceil_min_one(self):
        # 3 commentateurs par crédit, arrondi au supérieur, minimum 1.
        self.assertEqual(lead_finder.lead_collect_credit_cost(0), 0)
        self.assertEqual(lead_finder.lead_collect_credit_cost(1), 1)
        self.assertEqual(lead_finder.lead_collect_credit_cost(3), 1)
        self.assertEqual(lead_finder.lead_collect_credit_cost(4), 2)
        self.assertEqual(lead_finder.lead_collect_credit_cost(100), 34)
        self.assertEqual(lead_finder.lead_collect_credit_cost(1000), 334)

    def test_negative_is_zero(self):
        self.assertEqual(lead_finder.lead_collect_credit_cost(-5), 0)


class EffectiveMaxCommentsTest(unittest.TestCase):
    def test_flagged_account_honors_volume(self):
        self.assertEqual(lead_finder.effective_max_comments(2000, True), 2000)
        self.assertEqual(lead_finder.effective_max_comments(50, True), 50)

    def test_unflagged_account_clamped_to_default(self):
        # Sans le flag, un gros volume est ramené au défaut, même par appel direct.
        self.assertEqual(lead_finder.effective_max_comments(2000, False), lead_finder.DEFAULT_MAX_ITEMS)
        # En-dessous du défaut, on respecte la demande.
        self.assertEqual(lead_finder.effective_max_comments(30, False), 30)

    def test_none_falls_back_to_default(self):
        self.assertEqual(lead_finder.effective_max_comments(None, True), lead_finder.DEFAULT_MAX_ITEMS)
        self.assertEqual(lead_finder.effective_max_comments(None, False), lead_finder.DEFAULT_MAX_ITEMS)


class CommenterNormalizeTest(unittest.TestCase):
    def test_maps_actor_fields(self):
        lead = lead_finder._commenter_from_item({
            "actor": {"name": "Camille Roy", "linkedinUrl": "https://lnkd.in/x", "position": "CMO"},
            "commentary": "CLAUDE",
            "createdAt": "2026-07-24",
            "engagement": {"likes": 7},
        })
        self.assertEqual(lead["name"], "Camille Roy")
        self.assertEqual(lead["headline"], "CMO")
        self.assertEqual(lead["comment_text"], "CLAUDE")
        self.assertEqual(lead["reaction_count"], 7)

    def test_empty_item_returns_none(self):
        self.assertIsNone(lead_finder._commenter_from_item({"actor": {}}))

    def test_likes_fallback_to_reactions_sum(self):
        lead = lead_finder._commenter_from_item({
            "actor": {"name": "X", "linkedinUrl": "u"},
            "engagement": {"reactions": [{"count": 2}, {"count": 3}]},
        })
        self.assertEqual(lead["reaction_count"], 5)


class FetchCommentersTest(unittest.TestCase):
    def _run_with_items(self, items, max_items):
        with patch("src.lead_finder._call_actor", return_value={"defaultDatasetId": "d"}), \
             patch("src.lead_finder._default_dataset_id", return_value="d"), \
             patch("src.lead_finder.track_apify"), \
             patch("src.lead_finder._client") as client:
            client.return_value.dataset.return_value.iterate_items.return_value = iter(items)
            return lead_finder.fetch_post_commenters("https://post", max_items=max_items)

    def test_dedup_by_profile_and_sort_by_reactions(self):
        items = [
            {"actor": {"name": "A", "linkedinUrl": "a"}, "engagement": {"likes": 1}},
            {"actor": {"name": "B", "linkedinUrl": "b"}, "engagement": {"likes": 9}},
            {"actor": {"name": "A again", "linkedinUrl": "a"}, "engagement": {"likes": 5}},  # doublon profil a
        ]
        leads = self._run_with_items(items, 100)
        self.assertEqual(len(leads), 2)  # a dédupliqué
        self.assertEqual(leads[0]["profile_url"], "b")  # trié par engagement décroissant

    def test_max_items_capped(self):
        # Un max démesuré est ramené sous le plafond dur avant l'appel actor.
        captured = {}

        def fake_call(actor, run_input, timeout_secs):
            captured["maxItems"] = run_input["maxItems"]
            return {"defaultDatasetId": "d"}

        with patch("src.lead_finder._call_actor", side_effect=fake_call), \
             patch("src.lead_finder._default_dataset_id", return_value="d"), \
             patch("src.lead_finder.track_apify"), \
             patch("src.lead_finder._client") as client:
            client.return_value.dataset.return_value.iterate_items.return_value = iter([])
            lead_finder.fetch_post_commenters("https://post", max_items=999999)
        self.assertEqual(captured["maxItems"], lead_finder.MAX_ITEMS_CAP)
        self.assertGreater(lead_finder.MAX_ITEMS_CAP, 500)  # le plafond a bien été levé


class CollectAndPersistTest(unittest.TestCase):
    def test_debits_proportional_and_reports_counts(self):
        source = {"id": "s1", "post_url": "https://post", "trigger_keyword": "CLAUDE"}
        commenters = [
            {"name": "A", "profile_url": "a", "reaction_count": 1},
            {"name": "B", "profile_url": "b", "reaction_count": 2},
            {"name": "C", "profile_url": "c", "reaction_count": 3},
            {"name": "D", "profile_url": "d", "reaction_count": 4},
        ]
        with patch("src.lead_finder.fetch_post_commenters", return_value=commenters), \
             patch("src.db.debit_credits", return_value=(True, 990)) as debit, \
             patch("src.db.save_leads", return_value={"inserted": 4, "updated": 0, "skipped": 0, "ids_by_url": {"a": "id-a"}}), \
             patch("src.db.update_lead_source", return_value=None), \
             patch("src.db.get_lead_targeting", return_value=None):
            result = lead_finder.collect_and_persist("tok", source, 250)

        # 4 commentateurs → ceil(4/3) = 2 crédits débités.
        debit.assert_called_once_with("tok", "collect_leads", 2)
        self.assertEqual(result["comments_count"], 4)
        self.assertEqual(result["leads"]["inserted"], 4)
        # ids_by_url (interne au scoring) n'est jamais exposé au job.
        self.assertNotIn("ids_by_url", result["leads"])
        self.assertEqual(result["credits"], 990)

    def test_zero_commenters_no_debit(self):
        source = {"id": "s1", "post_url": "https://post"}
        with patch("src.lead_finder.fetch_post_commenters", return_value=[]), \
             patch("src.db.debit_credits", return_value=(True, 0)) as debit, \
             patch("src.db.save_leads", return_value={"inserted": 0, "updated": 0, "skipped": 0}), \
             patch("src.db.update_lead_source", return_value=None), \
             patch("src.db.get_lead_targeting", return_value=None):
            result = lead_finder.collect_and_persist("tok", source, 100)
        debit.assert_not_called()
        self.assertEqual(result["comments_count"], 0)
        self.assertIsNone(result["credits"])


class PostDetailTotalCommentsTest(unittest.TestCase):
    def test_extracts_stats_comments(self):
        from src import scraper
        item = {
            "post": {"text": "Commente CLAUDE pour recevoir le guide", "url": "https://p"},
            "author": {"name": "Ugo"},
            "stats": {"comments": 842},
        }
        with patch("src.scraper._call_actor", return_value={"defaultDatasetId": "d"}), \
             patch("src.scraper._default_dataset_id", return_value="d"), \
             patch("src.scraper.track_apify"), \
             patch("src.scraper._client") as client:
            client.return_value.dataset.return_value.iterate_items.return_value = iter([item])
            detail = scraper.fetch_post_detail("https://p")
        self.assertEqual(detail["total_comments"], 842)

    def test_missing_stats_is_none(self):
        from src import scraper
        item = {"post": {"text": "hello", "url": "https://p"}, "author": {"name": "X"}}
        with patch("src.scraper._call_actor", return_value={"defaultDatasetId": "d"}), \
             patch("src.scraper._default_dataset_id", return_value="d"), \
             patch("src.scraper.track_apify"), \
             patch("src.scraper._client") as client:
            client.return_value.dataset.return_value.iterate_items.return_value = iter([item])
            detail = scraper.fetch_post_detail("https://p")
        self.assertIsNone(detail["total_comments"])


if __name__ == "__main__":
    unittest.main()
