"""Preview d'analyse onboarding — normalisation pure (zéro réseau)."""
from __future__ import annotations

import unittest

from src.llm import linkedin_handle_from_url, normalize_onboarding_preview
from src.normalize import normalize_profile


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

    def test_strips_at_prefix_from_handle(self):
        # Le front préfixe lui-même « @ » — un handle déjà préfixé donnait « @@ ».
        raw = {
            "handle": "@remi-campana",
            "niche": "N",
            "summary": "S",
            "strengths": ["a"],
            "improvements": ["b"],
        }
        out = normalize_onboarding_preview(raw)
        assert out is not None
        self.assertEqual(out["handle"], "remi-campana")

    def test_avatar_comes_from_scrape_never_from_llm(self):
        raw = {
            "niche": "N",
            "summary": "S",
            "strengths": ["a"],
            "improvements": ["b"],
            "avatar_url": "https://evil.example/fake.png",
        }
        seed = {
            "linkedin_apify_profile": {
                "profile": {"avatar_url": "https://media.licdn.com/real.png"},
                "top_posts": [],
            },
        }
        out = normalize_onboarding_preview(raw, seed=seed)
        assert out is not None
        self.assertEqual(out["avatar_url"], "https://media.licdn.com/real.png")
        # Sans scrape : pas de photo, jamais celle proposée par le modèle.
        out2 = normalize_onboarding_preview(raw)
        assert out2 is not None
        self.assertEqual(out2["avatar_url"], "")

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


class NormalizeProfileAvatarTests(unittest.TestCase):
    def test_harvestapi_picture_dict(self):
        raw = {
            "firstName": "Rémi",
            "lastName": "Campana",
            "pictureUrl": {"100x100": "https://cdn/100.png", "400x400": "https://cdn/400.png"},
        }
        self.assertEqual(normalize_profile(raw)["avatar_url"], "https://cdn/400.png")

    def test_apimaestro_flat_url(self):
        raw = {"basic_info": {"fullname": "Rémi", "profile_picture_url": "https://cdn/pic.png"}}
        self.assertEqual(normalize_profile(raw)["avatar_url"], "https://cdn/pic.png")

    def test_absent_picture_is_empty(self):
        self.assertEqual(normalize_profile({"firstName": "A"})["avatar_url"], "")


if __name__ == "__main__":
    unittest.main()
