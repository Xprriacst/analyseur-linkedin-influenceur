"""Preview d'analyse onboarding — normalisation pure (zéro réseau)."""
from __future__ import annotations

import unittest

from src.llm import linkedin_handle_from_url, normalize_onboarding_preview


class LinkedinHandleTests(unittest.TestCase):
    def test_extracts_slug(self):
        self.assertEqual(
            linkedin_handle_from_url("https://www.linkedin.com/in/tom-auclairr/"),
            "tom-auclairr",
        )

    def test_decodes_percent(self):
        self.assertEqual(
            linkedin_handle_from_url("https://linkedin.com/in/cl%C3%A9ment-geynet"),
            "clément-geynet",
        )

    def test_empty_on_garbage(self):
        self.assertEqual(linkedin_handle_from_url("https://example.com"), "")


class NormalizePreviewTests(unittest.TestCase):
    def test_rejects_incomplete(self):
        self.assertIsNone(normalize_onboarding_preview({"niche": "SaaS"}))

    def test_fills_stats_from_seed_not_llm(self):
        raw = {
            "niche": "Founder SaaS B2B",
            "summary": "Tu documentes ton build. Les posts concrets performent, le reste stagne.",
            "hook": "Tu postes sans framework clair.",
            "hashtags": ["BuildInPublic", "#SaaS"],
            "strengths": ["A", "B", "C"],
            "improvements": ["D", "E", "F"],
            # Le modèle tente d'inventer — on ignore au profit du scrape.
            "followers": 99999,
            "posts_count": 99999,
        }
        seed = {
            "linkedin_url": "https://linkedin.com/in/tom.auclairr",
            "linkedin_apify_profile": {
                "profile": {
                    "name": "Tom Auclair",
                    "headline": "Founder",
                    "follower_count": 1300,
                    "connections_count": 500,
                },
                "top_posts": [{"text": "a"}, {"text": "b"}, {"text": "c"}],
            },
        }
        out = normalize_onboarding_preview(raw, seed=seed)
        assert out is not None
        self.assertEqual(out["followers"], 1300)
        self.assertEqual(out["connections"], 500)
        self.assertEqual(out["posts_count"], 3)
        self.assertEqual(out["handle"], "tom.auclairr")
        self.assertEqual(out["name"], "Tom Auclair")
        self.assertEqual(out["hashtags"][0], "#BuildInPublic")
        self.assertEqual(len(out["strengths"]), 3)
        self.assertEqual(len(out["improvements"]), 3)

    def test_caps_lists(self):
        raw = {
            "niche": "N",
            "summary": "S",
            "strengths": [f"s{i}" for i in range(10)],
            "improvements": [f"i{i}" for i in range(10)],
            "hashtags": [f"t{i}" for i in range(20)],
        }
        out = normalize_onboarding_preview(raw)
        assert out is not None
        self.assertEqual(len(out["strengths"]), 3)
        self.assertEqual(len(out["improvements"]), 3)
        self.assertEqual(len(out["hashtags"]), 8)


if __name__ == "__main__":
    unittest.main()
