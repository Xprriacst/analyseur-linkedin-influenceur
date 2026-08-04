"""Mémoire des posts déjà créés/publiés — « l'IA se souvient des posts faits ».

Couvre les trois briques :
- db.dedupe_post_memory : dédoublonnage (un post existe souvent en double,
  généré PUIS publié) + plafond d'entrées ;
- llm._format_recent_posts : rendu du bloc mémoire dans les prompts (règles
  anti-répétition + continuité), chaîne vide quand il n'y a rien ;
- injection réelle dans generate_posts et le system prompt du chat — perdre la
  mémoire en route serait une panne parfaitement silencieuse.
"""
import unittest
from unittest.mock import patch

import src.db as db
import src.llm as llm


class DedupePostMemoryTest(unittest.TestCase):
    def test_keeps_first_occurrence_of_duplicate_text(self):
        # Même post généré puis publié : le publié est mis en premier par les
        # appelants et doit gagner.
        entries = [
            {"text": "Mon post sur les crédits IA.", "status": "publié"},
            {"text": "  mon post   sur les crédits ia. ", "status": "généré (brouillon)"},
            {"text": "Un autre post.", "status": "généré (brouillon)"},
        ]
        out = db.dedupe_post_memory(entries)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["status"], "publié")
        self.assertEqual(out[1]["text"], "Un autre post.")

    def test_skips_empty_texts_and_honours_limit(self):
        entries = [{"text": ""}, {"text": "   "}] + [
            {"text": f"Post numéro {i}"} for i in range(20)
        ]
        out = db.dedupe_post_memory(entries, limit=5)
        self.assertEqual(len(out), 5)
        self.assertEqual(out[0]["text"], "Post numéro 0")

    def test_no_supabase_returns_empty_never_raises(self):
        # Fail-safe : sans session/Supabase, la mémoire est vide, jamais une erreur.
        self.assertEqual(db.get_recent_post_memory(None), [])


class FormatRecentPostsTest(unittest.TestCase):
    def test_empty_input_renders_nothing(self):
        self.assertEqual(llm._format_recent_posts(None), "")
        self.assertEqual(llm._format_recent_posts([]), "")
        self.assertEqual(llm._format_recent_posts([{"text": "  "}]), "")

    def test_block_contains_posts_labels_and_memory_rules(self):
        block = llm._format_recent_posts([
            {"text": "Mon post publié hier.", "status": "publié", "date": "2026-08-03"},
            {"text": "Un brouillon récent.", "status": "généré (brouillon)"},
        ])
        self.assertIn("Mémoire — posts déjà créés par le client", block)
        self.assertIn("[publié · 2026-08-03] Mon post publié hier.", block)
        self.assertIn("[généré (brouillon)] Un brouillon récent.", block)
        # Les deux effets voulus : anti-répétition ET continuité.
        self.assertIn("Ne reproduis pas un sujet", block)
        self.assertIn("faire écho à un post précédent", block)

    def test_caps_entries_and_truncates_text(self):
        posts = [{"text": f"Post {i} " + "x" * 500} for i in range(20)]
        block = llm._format_recent_posts(posts)
        self.assertIn("Post 11", block)
        self.assertNotIn("Post 12", block)  # plafond : 12 entrées
        # Chaque texte est tronqué à 300 caractères.
        for line in block.splitlines():
            if line.startswith("- "):
                self.assertLessEqual(len(line), 320)


class PromptInjectionTest(unittest.TestCase):
    def _fake_call(self, captured):
        def fake(system, user, **kwargs):
            captured["system"] = system
            captured["user"] = user
            return {"variants": [{"post": "ok"}]}
        return fake

    def test_generate_posts_injects_memory_block(self):
        captured = {}
        with patch.object(llm, "_call", side_effect=self._fake_call(captured)):
            llm.generate_posts(
                "Sujet test",
                top_posts_examples=[],
                benchmark={},
                recent_posts=[{"text": "Mon post d'avant sur les délais.", "status": "publié"}],
            )
        self.assertIn("Mémoire — posts déjà créés par le client", captured["user"])
        self.assertIn("Mon post d'avant sur les délais.", captured["user"])

    def test_generate_posts_without_memory_has_no_block(self):
        captured = {}
        with patch.object(llm, "_call", side_effect=self._fake_call(captured)):
            llm.generate_posts("Sujet test", top_posts_examples=[], benchmark={})
        self.assertNotIn("Mémoire — posts déjà créés", captured["user"])

    def test_reel_packs_inject_memory_block(self):
        captured = {}
        with patch.object(llm, "_call", side_effect=self._fake_call(captured)):
            llm.generate_instagram_reel_packs(
                "Sujet reel",
                top_posts_examples=[],
                benchmark={},
                recent_posts=[{"text": "Caption du reel déjà posté.", "status": "généré (brouillon)"}],
            )
        self.assertIn("Mémoire — posts déjà créés par le client", captured["user"])
        self.assertIn("Caption du reel déjà posté.", captured["user"])

    def test_one_line_ideas_inject_memory_block(self):
        captured = {}

        def fake(system, user, **kwargs):
            captured["user"] = user
            return {"ideas": []}

        with patch.object(llm, "_call", side_effect=fake):
            llm.generate_one_line_ideas(
                real_posts=[],
                benchmark={},
                recent_posts=[{"text": "Post déjà publié sur le sujet X.", "status": "publié"}],
            )
        self.assertIn("Post déjà publié sur le sujet X.", captured["user"])

    def test_chat_system_prompt_includes_memory(self):
        system = llm._chat_system_prompt(
            [],
            {},
            recent_posts=[{"text": "Mon dernier post publié.", "status": "publié", "date": "2026-08-01"}],
        )
        self.assertIn("Mémoire — posts déjà créés par le client", system)
        self.assertIn("Mon dernier post publié.", system)

    def test_chat_system_prompt_without_memory_unchanged(self):
        system = llm._chat_system_prompt([], {})
        self.assertNotIn("Mémoire — posts déjà créés", system)


if __name__ == "__main__":
    unittest.main()
