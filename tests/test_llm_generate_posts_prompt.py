import unittest
from unittest.mock import patch

import src.llm as llm


class GeneratePostsPromptTest(unittest.TestCase):
    def test_prompt_discourages_formulaic_linkedin_ai_openings(self):
        captured = {}

        def fake_call(system, user, **kwargs):
            captured["system"] = system
            captured["user"] = user
            captured["kwargs"] = kwargs
            return {
                "variants": [
                    {
                        "hook_type": "stat+contrarian",
                        "strategy": "Angle test",
                        "predicted_lift": "+40-80% vs post standard",
                        "post": "Un post naturel.",
                    }
                ]
            }

        with patch.object(llm, "_call", side_effect=fake_call):
            variants = llm.generate_posts(
                "Pourquoi les projets IA bloquent",
                top_posts_examples=[
                    {
                        "influencer": "Ada",
                        "engagement": 120,
                        "hook_type": "story",
                        "text": "Hier, un dirigeant m'a montré son vrai problème...",
                    }
                ],
                benchmark={"hook_distribution": {"story": 3}},
                user_context={
                    "display_name": "Client Test",
                    "tone": "direct, terrain, sans emphase",
                    "target_audience": "dirigeants de PME",
                },
                editorial_role="performance",
            )

        self.assertEqual(variants[0]["editorial_role"], "performance")
        self.assertIn("imiter un style réel", captured["system"])
        self.assertIn("direct, terrain, sans emphase", captured["user"])
        self.assertIn("style générique \"LinkedIn IA\"", captured["user"])
        self.assertIn("X.\n\nPas Y.", captured["user"])
        self.assertIn("La majorité des projets IA en PME", captured["user"])
        self.assertIn("Dans 7 ans de missions IA", captured["user"])
        self.assertIn("CTA clair, sobre, 1 action principale", captured["user"])
        self.assertIn("rythme, précision métier", captured["user"])


if __name__ == "__main__":
    unittest.main()
