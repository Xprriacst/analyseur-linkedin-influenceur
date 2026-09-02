"""Mémoire des posts déjà créés/publiés — « l'IA se souvient des posts faits ».

Couvre les briques :
- db.dedupe_post_memory : dédoublonnage (un post existe souvent en double,
  généré PUIS publié) + plafond d'entrées ;
- llm._format_recent_posts / _format_memory_entry : rendu du bloc mémoire dans
  les prompts (fiche structurée si disponible, texte brut tronqué en repli),
  règles anti-répétition + continuité, chaîne vide quand il n'y a rien ;
- injection réelle dans generate_posts et le system prompt du chat — perdre la
  mémoire en route serait une panne parfaitement silencieuse ;
- mémoire posts structurée (ALE-102bis) : llm.build_post_memory_card (appel IA
  annexe fail-safe) + db._build_memory_card (calcul à la création, jamais à la
  lecture) + repli sur le texte brut pour les lignes sans fiche.
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

    def test_own_linkedin_status_wins_over_generated_duplicate(self):
        # Le post live est mis en premier par `_post_memory_from_client` :
        # s'il perdait au dédoublonnage, le modèle croirait n'avoir que le brouillon Cibl.
        entries = [
            {"text": "Cloud vs local en officine.", "status": db.OWN_LINKEDIN_STATUS},
            {"text": "Cloud vs local en officine.", "status": "généré (brouillon)"},
        ]
        out = db.dedupe_post_memory(entries)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["status"], db.OWN_LINKEDIN_STATUS)

    def test_has_own_linkedin_memory(self):
        self.assertFalse(db.has_own_linkedin_memory([]))
        self.assertFalse(db.has_own_linkedin_memory([{"status": "publié"}]))
        self.assertTrue(db.has_own_linkedin_memory([
            {"status": "publié"},
            {"status": db.OWN_LINKEDIN_STATUS},
        ]))

    def test_own_posts_to_memory_entries_keeps_order_and_skips_empty(self):
        rows = [
            {"text": "Premier post.", "posted_at": "2026-09-01T10:00:00Z"},
            {"text": "   "},
            {"text": "Second post.", "posted_at": "2026-08-20"},
        ]
        out = db.own_posts_to_memory_entries(rows)
        self.assertEqual([e["text"] for e in out], ["Premier post.", "Second post."])
        self.assertEqual(out[0]["status"], db.OWN_LINKEDIN_STATUS)
        self.assertEqual(out[0]["date"], "2026-09-01")
        self.assertEqual(out[1]["date"], "2026-08-20")

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

    def test_live_linkedin_posts_are_called_out_in_the_rules(self):
        block = llm._format_recent_posts([
            {
                "text": "Hier j'ai parlé du cloud vs local en pharmacie.",
                "status": db.OWN_LINKEDIN_STATUS,
            },
        ])
        self.assertIn("[publié sur LinkedIn]", block)
        self.assertIn("tes vrais posts live", block)
        self.assertIn("ne les recycle pas", block)

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


class NormalizeMemoryCardTest(unittest.TestCase):
    def test_valid_card_is_trimmed_and_capped(self):
        card = llm._normalize_memory_card({
            "subject": "  Crédits IA  ",
            "angle": "x" * 500,
            "products": "",
            "hook": "Une question choc",
        })
        self.assertEqual(card["subject"], "Crédits IA")
        self.assertEqual(len(card["angle"]), 140)
        self.assertEqual(card["products"], "")
        self.assertEqual(card["hook"], "Une question choc")

    def test_entirely_empty_card_returns_none(self):
        self.assertIsNone(llm._normalize_memory_card({"subject": "", "angle": "  "}))
        self.assertIsNone(llm._normalize_memory_card({}))

    def test_non_dict_input_returns_none(self):
        self.assertIsNone(llm._normalize_memory_card(None))
        self.assertIsNone(llm._normalize_memory_card("pas un dict"))
        self.assertIsNone(llm._normalize_memory_card(["a", "b"]))


class BuildPostMemoryCardTest(unittest.TestCase):
    def test_empty_text_returns_none_without_calling_llm(self):
        with patch.object(llm, "_call") as mocked:
            self.assertIsNone(llm.build_post_memory_card(""))
            self.assertIsNone(llm.build_post_memory_card("   "))
        mocked.assert_not_called()

    def test_success_returns_normalized_card(self):
        with patch.object(llm, "_call", return_value={
            "subject": "Prospection LinkedIn",
            "angle": "L'automatisation tue la confiance",
            "products": "Cibl",
            "hook": "Et si on arrêtait d'automatiser ?",
        }):
            card = llm.build_post_memory_card("Un post sur la prospection.")
        self.assertEqual(card["subject"], "Prospection LinkedIn")
        self.assertEqual(card["products"], "Cibl")

    def test_llm_call_uses_light_model_and_no_temperature_sampling_issue(self):
        # Vérifie que le modèle est bien surchargeable (patron _scoring_model)
        # et que l'appel ne débite jamais de crédit (aucune notion de crédit
        # ici — le point est juste que build_post_memory_card ne passe QUE par
        # _call, jamais par une route facturée).
        captured = {}

        def fake_call(system, user, **kwargs):
            captured.update(kwargs)
            return {"subject": "x", "angle": "y", "products": "", "hook": "z"}

        with patch.object(llm, "_call", side_effect=fake_call):
            with patch.dict("os.environ", {"POST_MEMORY_CARD_MODEL": "claude-haiku-4-5"}):
                llm.build_post_memory_card("Un post.")
        self.assertEqual(captured.get("model"), "claude-haiku-4-5")

    def test_llm_failure_is_fail_safe_returns_none(self):
        with patch.object(llm, "_call", side_effect=RuntimeError("boom")):
            self.assertIsNone(llm.build_post_memory_card("Un post."))

    def test_malformed_json_response_is_fail_safe(self):
        # _call renvoie un dict même en cas de JSON mal formé (la réparation
        # vit dans _extract_json) — mais un type inattendu ne doit jamais lever.
        with patch.object(llm, "_call", return_value="pas un dict"):
            self.assertIsNone(llm.build_post_memory_card("Un post."))


class FormatMemoryEntryTest(unittest.TestCase):
    def test_structured_card_renders_compact_fiche(self):
        line = llm._format_memory_entry({
            "text": "Texte brut complet du post, ignoré quand la fiche existe.",
            "status": "publié",
            "date": "2026-08-11",
            "card": {
                "subject": "Prospection LinkedIn",
                "angle": "L'automatisation tue la confiance",
                "products": "Cibl",
                "hook": "Et si on arrêtait d'automatiser ?",
            },
        })
        self.assertIn("[publié · 2026-08-11]", line)
        self.assertIn("sujet: Prospection LinkedIn", line)
        self.assertIn("angle: L'automatisation tue la confiance", line)
        self.assertIn("produits cités: Cibl", line)
        self.assertIn("accroche: Et si on arrêtait d'automatiser ?", line)
        # La fiche est nettement plus courte que le texte brut qu'elle remplace.
        self.assertLess(len(line), 200)
        self.assertNotIn("ignoré quand la fiche existe", line)

    def test_card_with_only_some_fields_omits_the_rest(self):
        line = llm._format_memory_entry({
            "text": "Texte brut.",
            "card": {"subject": "Sujet seul", "angle": "", "products": "", "hook": ""},
        })
        self.assertIn("sujet: Sujet seul", line)
        self.assertNotIn("angle:", line)
        self.assertNotIn("produits cités:", line)
        self.assertNotIn("accroche:", line)

    def test_missing_card_falls_back_to_truncated_text(self):
        # Rétrocompatibilité : posts créés avant ce lot (memory_card NULL en
        # base) ou fiche jamais calculée avec succès.
        line = llm._format_memory_entry({
            "text": "Texte brut de secours " + "x" * 400,
            "status": "sauvegardé",
        })
        self.assertIn("[sauvegardé]", line)
        self.assertIn("Texte brut de secours", line)
        self.assertNotIn("sujet:", line)

    def test_card_present_but_entirely_empty_falls_back_to_text(self):
        # Une fiche techniquement présente mais vide (tous champs "") doit se
        # comporter comme une fiche absente — pas de ligne vide dans le prompt.
        line = llm._format_memory_entry({
            "text": "Texte brut de secours.",
            "card": {"subject": "", "angle": "", "products": "", "hook": ""},
        })
        self.assertIn("Texte brut de secours.", line)
        self.assertNotIn("sujet:", line)

    def test_empty_text_returns_none(self):
        self.assertIsNone(llm._format_memory_entry({"text": "  ", "card": {"subject": "x"}}))


class FormatRecentPostsMixedEntriesTest(unittest.TestCase):
    def test_block_mixes_structured_and_fallback_entries(self):
        block = llm._format_recent_posts([
            {
                "text": "Texte brut du post structuré.",
                "status": "publié",
                "date": "2026-08-10",
                "card": {"subject": "Sujet A", "angle": "", "products": "", "hook": ""},
            },
            {"text": "Un vieux post sans fiche.", "status": "sauvegardé", "card": None},
        ])
        self.assertIn("sujet: Sujet A", block)
        self.assertNotIn("Texte brut du post structuré.", block)
        self.assertIn("Un vieux post sans fiche.", block)

    def test_structured_card_uses_fewer_characters_than_raw_text(self):
        long_text = "Un post très long qui parle de prospection LinkedIn. " * 6
        raw_block = llm._format_recent_posts([{"text": long_text, "status": "publié"}])
        card_block = llm._format_recent_posts([{
            "text": long_text,
            "status": "publié",
            "card": {"subject": "Prospection LinkedIn", "angle": "", "products": "", "hook": ""},
        }])
        self.assertLess(len(card_block), len(raw_block))


class DbBuildMemoryCardTest(unittest.TestCase):
    def test_empty_text_returns_none_without_import(self):
        self.assertIsNone(db._build_memory_card(""))
        self.assertIsNone(db._build_memory_card("   "))

    def test_delegates_to_llm_and_returns_card(self):
        with patch("src.llm.build_post_memory_card", return_value={"subject": "x"}):
            self.assertEqual(db._build_memory_card("Un post."), {"subject": "x"})

    def test_llm_failure_is_fail_safe_never_raises(self):
        with patch("src.llm.build_post_memory_card", side_effect=RuntimeError("boom")):
            self.assertIsNone(db._build_memory_card("Un post."))

    def test_import_error_is_fail_safe(self):
        # Simule un environnement où le SDK Anthropic ne s'importe pas du tout
        # (clé absente, dépendance manquante...) : ne doit jamais remonter.
        with patch("src.llm.build_post_memory_card", side_effect=ImportError("no anthropic")):
            self.assertIsNone(db._build_memory_card("Un post."))


class SaveGeneratedPostsMemoryCardTest(unittest.TestCase):
    """`save_generated_posts` doit calculer la fiche UNE FOIS, à la création."""

    def test_memory_card_computed_once_per_row_at_save_time(self):
        calls = []

        class FakeInsertResult:
            def __init__(self, rows):
                self.data = rows

        class FakeTable:
            def __init__(self, name):
                self.name = name
                self._rows = None

            def insert(self, rows):
                calls.append(rows)
                self._rows = rows
                return self

            def execute(self):
                return FakeInsertResult(self._rows)

        class FakeClient:
            def table(self, name):
                return FakeTable(name)

        with patch.object(db, "supabase_enabled", return_value=True), \
             patch.object(db, "get_user", return_value={"id": "u1"}), \
             patch.object(db, "client_for_token", return_value=FakeClient()), \
             patch("src.llm.build_post_memory_card", return_value={"subject": "s"}) as mocked_card:
            variants = [{"post": "Un premier post."}, {"post": "Un second post."}]
            db.save_generated_posts("token", "Sujet", variants)

        self.assertEqual(mocked_card.call_count, 2)
        self.assertEqual(len(calls), 1)
        rows = calls[0]
        self.assertEqual(rows[0]["memory_card"], {"subject": "s"})
        self.assertEqual(rows[1]["memory_card"], {"subject": "s"})

    def test_memory_card_failure_does_not_block_save(self):
        class FakeInsertResult:
            def __init__(self, rows):
                self.data = rows

        class FakeTable:
            def insert(self, rows):
                self._rows = rows
                return self

            def execute(self):
                return FakeInsertResult(self._rows)

        class FakeClient:
            def table(self, name):
                return FakeTable()

        with patch.object(db, "supabase_enabled", return_value=True), \
             patch.object(db, "get_user", return_value={"id": "u1"}), \
             patch.object(db, "client_for_token", return_value=FakeClient()), \
             patch("src.llm.build_post_memory_card", side_effect=RuntimeError("boom")):
            saved = db.save_generated_posts("token", "Sujet", [{"post": "Un post."}])

        self.assertEqual(len(saved), 1)
        self.assertIsNone(saved[0]["memory_card"])


class UnipileOwnPostsMemoryTest(unittest.TestCase):
    """Repli Unipile : normalisation pure, sans réseau."""

    def test_normalize_skips_empty_text(self):
        from src import unipile
        self.assertIsNone(unipile.normalize_own_post(None))
        self.assertIsNone(unipile.normalize_own_post({"text": ""}))
        self.assertIsNone(unipile.normalize_own_post({"date": "2026-09-01"}))

    def test_normalize_accepts_nested_text_and_parsed_datetime(self):
        from src import unipile
        entry = unipile.normalize_own_post({
            "text": {"text": "  Un post live Unipile.  "},
            "parsed_datetime": "2026-08-28T09:12:00.000Z",
        })
        self.assertEqual(entry["text"], "Un post live Unipile.")
        self.assertEqual(entry["status"], "publié sur LinkedIn")
        self.assertEqual(entry["date"], "2026-08-28")

    def test_list_own_posts_hits_me_identifier(self):
        from src import unipile
        captured = {}

        def fake_request(method, path, **kwargs):
            captured["method"] = method
            captured["path"] = path
            captured["params"] = kwargs.get("params")
            return {"items": [{"text": "ok", "date": "2026-09-01"}]}

        with patch.object(unipile, "_request", side_effect=fake_request):
            items = unipile.list_own_posts("acc-1", limit=10)
        self.assertEqual(captured["method"], "GET")
        self.assertEqual(captured["path"], "/users/me/posts")
        self.assertEqual(captured["params"]["account_id"], "acc-1")
        self.assertEqual(len(items), 1)

    def test_own_posts_to_memory_drops_image_only(self):
        from src import unipile
        mem = unipile.own_posts_to_memory([
            {"text": "Dit à voix haute."},
            {"share_url": "https://linkedin.com/feed/update/urn"},
        ])
        self.assertEqual(len(mem), 1)
        self.assertEqual(mem[0]["text"], "Dit à voix haute.")


if __name__ == "__main__":
    unittest.main()
