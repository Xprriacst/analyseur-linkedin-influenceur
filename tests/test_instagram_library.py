"""Backlog Notion — « Ma bibliothèque Instagram au niveau LinkedIn », lot 1
(import par lien + trames réutilisables à la génération de reels).

Ce que ce fichier verrouille :

- `scraper_instagram.fetch_ig_post_detail` (le pendant Instagram de
  `scraper.fetch_post_detail`) : mapping des champs, item en erreur ignoré,
  caption vide ignorée.
- `llm.extract_reel_template` : trame hook/script/caption extraite d'une
  caption, jamais le format LinkedIn.
- `llm.generate_instagram_reel_packs` : une trame de bibliothèque
  (`custom_trame`) prend le pas sur le catalogue statique dans le prompt.
- `jobs._resolve_ig_custom_trame` : un id `lib:{id}` résout la trame réelle du
  client ; un id de catalogue (`None`/id nu) ou une entrée supprimée entre le
  choix et le lancement replient sur le catalogue statique — jamais une
  génération cassée par une bibliothèque qui a bougé entre-temps.
- `api._add_library_entry` : une entrée `platform="instagram"` importe via
  l'acteur reel (pas l'acteur LinkedIn), ne déclenche jamais la détection
  lead-magnet (ALE-234, LinkedIn only), et persiste `platform="instagram"`.
- `GET /generate/instagram/trames` : les trames de la bibliothèque du client
  passent AVANT le catalogue statique, avec l'id `lib:` et une description non
  vide seulement — sinon une entrée sans structure ni caption polluerait le
  choix du client d'une option vide.
- `GET/POST /me/post-templates` : `platform=instagram` est gardé par le flag
  `instagram` (masquer l'onglet ne protège rien), `platform=linkedin` (défaut)
  ne l'est jamais — pas de régression sur le parcours existant.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import llm  # noqa: E402
from src import jobs  # noqa: E402
from src import scraper_instagram  # noqa: E402


class FetchIgPostDetailTest(unittest.TestCase):
    def _run(self, items):
        with patch.object(scraper_instagram, "_client") as client, \
             patch.object(scraper_instagram, "track_apify"), \
             patch.object(scraper_instagram, "actor_health"):
            client.return_value.actor.return_value.call.return_value = {"defaultDatasetId": "d"}
            client.return_value.dataset.return_value.iterate_items.return_value = iter(items)
            return scraper_instagram.fetch_ig_post_detail("https://www.instagram.com/reel/abc/")

    def test_maps_caption_owner_and_display_url(self):
        detail = self._run([
            {"caption": "Un conseil en 30s #entrepreneur", "ownerFullName": "Camille Martin",
             "ownerUsername": "camillem", "url": "https://www.instagram.com/reel/abc/", "displayUrl": "https://img/x.jpg"},
        ])
        self.assertEqual(detail["text"], "Un conseil en 30s #entrepreneur")
        self.assertEqual(detail["author"], "Camille Martin")
        self.assertEqual(detail["image_url"], "https://img/x.jpg")

    def test_falls_back_to_username_when_full_name_missing(self):
        detail = self._run([
            {"caption": "hello", "ownerUsername": "camillem", "url": "https://p"},
        ])
        self.assertEqual(detail["author"], "camillem")

    def test_error_item_is_skipped(self):
        detail = self._run([
            {"error": "not_found", "errorDescription": "Post introuvable"},
            {"caption": "le vrai reel", "ownerUsername": "x", "url": "https://p"},
        ])
        self.assertEqual(detail["text"], "le vrai reel")

    def test_empty_caption_is_none(self):
        detail = self._run([{"caption": "  ", "ownerUsername": "x", "url": "https://p"}])
        self.assertIsNone(detail)

    def test_no_items_is_none(self):
        detail = self._run([])
        self.assertIsNone(detail)

    def test_actor_failure_returns_none(self):
        with patch.object(scraper_instagram, "_client", side_effect=RuntimeError("Apify down")), \
             patch.object(scraper_instagram, "track_apify"), \
             patch.object(scraper_instagram, "actor_health"):
            detail = scraper_instagram.fetch_ig_post_detail("https://p")
        self.assertIsNone(detail)


class ExtractReelTemplateTest(unittest.TestCase):
    def test_returns_trimmed_label_and_structure(self):
        with patch.object(llm, "_call", return_value={
            "structure_label": "  Hook question + 3 étapes  ",
            "structure_text": "  1. Hook\n2. Étape\n3. CTA  ",
        }):
            extracted = llm.extract_reel_template("Une caption de reel quelconque")
        self.assertEqual(extracted["structure_label"], "Hook question + 3 étapes")
        self.assertEqual(extracted["structure_text"], "1. Hook\n2. Étape\n3. CTA")

    def test_missing_fields_become_empty_strings_not_none(self):
        with patch.object(llm, "_call", return_value={}):
            extracted = llm.extract_reel_template("caption")
        self.assertEqual(extracted, {"structure_label": "", "structure_text": ""})

    def test_prompt_asks_for_reel_vocabulary_not_linkedin(self):
        """Le prompt doit parler hook/script/caption — pas le format post LinkedIn."""
        with patch.object(llm, "_call", return_value={}) as call:
            llm.extract_reel_template("caption")
        user_prompt = call.call_args.args[1]
        self.assertIn("hook", user_prompt.lower())
        self.assertNotIn("post lead-magnet", user_prompt.lower())


class GenerateInstagramReelPacksCustomTrameTest(unittest.TestCase):
    _VALID_RESPONSE = {
        "variants": [{
            "editorial_role": "story", "hook": "h", "script": "s", "caption": "c", "hashtags": ["#x"],
        }],
    }

    def test_custom_trame_overrides_static_catalog_in_prompt(self):
        with patch.object(llm, "_call", return_value=self._VALID_RESPONSE) as call:
            llm.generate_instagram_reel_packs(
                "mon sujet", [], {}, editorial_role="story", trame_id="lib:abc",
                custom_trame={"label": "Ma trame perso", "description": "Hook choc puis démonstration"},
            )
        user_prompt = call.call_args.args[1]
        self.assertIn("Ma trame perso", user_prompt)
        self.assertIn("Hook choc puis démonstration", user_prompt)
        self.assertIn("depuis ta bibliothèque", user_prompt)

    def test_no_custom_trame_falls_back_to_static_catalog(self):
        static_id = llm.IG_TRAMES[0]["id"]
        with patch.object(llm, "_call", return_value=self._VALID_RESPONSE) as call:
            llm.generate_instagram_reel_packs(
                "mon sujet", [], {}, editorial_role="story", trame_id=static_id, custom_trame=None,
            )
        user_prompt = call.call_args.args[1]
        self.assertIn(llm.IG_TRAMES[0]["label"], user_prompt)

    def test_empty_custom_trame_description_falls_back(self):
        """Une entrée bibliothèque sans description exploitable ne doit pas
        produire une directive de trame vide dans le prompt."""
        static_id = llm.IG_TRAMES[0]["id"]
        with patch.object(llm, "_call", return_value=self._VALID_RESPONSE) as call:
            llm.generate_instagram_reel_packs(
                "mon sujet", [], {}, editorial_role="story", trame_id=static_id,
                custom_trame={"label": "Vide", "description": "   "},
            )
        user_prompt = call.call_args.args[1]
        self.assertIn(llm.IG_TRAMES[0]["label"], user_prompt)
        self.assertNotIn("Vide", user_prompt)


class ResolveIgCustomTrameTest(unittest.TestCase):
    def test_static_catalog_id_resolves_to_none(self):
        self.assertIsNone(jobs._resolve_ig_custom_trame("tok", "storytelling"))

    def test_missing_trame_id_resolves_to_none(self):
        self.assertIsNone(jobs._resolve_ig_custom_trame("tok", None))

    def test_lib_prefixed_id_fetches_the_template(self):
        with patch.object(jobs.db, "get_post_template", return_value={
            "structure_label": "Ma trame", "structure_text": "1. Hook\n2. Script",
        }) as get:
            resolved = jobs._resolve_ig_custom_trame("tok", "lib:abc-123")
        get.assert_called_once_with("tok", "abc-123")
        self.assertEqual(resolved, {"label": "Ma trame", "description": "1. Hook\n2. Script"})

    def test_lib_entry_without_structure_falls_back_to_post_text(self):
        with patch.object(jobs.db, "get_post_template", return_value={
            "structure_label": None, "structure_text": None, "post_text": "La caption importée",
        }):
            resolved = jobs._resolve_ig_custom_trame("tok", "lib:abc-123")
        self.assertEqual(resolved["description"], "La caption importée")
        self.assertEqual(resolved["label"], "Trame personnalisée")

    def test_deleted_entry_between_choice_and_launch_falls_back_to_none(self):
        """L'entrée a été supprimée entre le choix du client et le lancement du
        job : la génération continue en catalogue statique, jamais une erreur."""
        with patch.object(jobs.db, "get_post_template", return_value=None):
            resolved = jobs._resolve_ig_custom_trame("tok", "lib:gone")
        self.assertIsNone(resolved)


class AddLibraryEntryPlatformTest(unittest.TestCase):
    """`api._add_library_entry(..., platform="instagram")` : import Instagram,
    jamais l'acteur LinkedIn, jamais la détection lead-magnet (LinkedIn only)."""

    def setUp(self):
        try:
            import api  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("fastapi indisponible dans cet environnement (venv du repo cassé)")

    def test_instagram_import_uses_ig_scraper_not_linkedin(self):
        import api
        with patch.object(api, "fetch_ig_post_detail", return_value={
            "text": "Une caption Instagram assez longue pour passer.",
            "author": "Camille", "url": "https://www.instagram.com/reel/abc/", "image_url": None,
        }) as ig_fetch, \
             patch.object(api, "fetch_post_detail") as li_fetch, \
             patch.object(api.db, "add_post_template", return_value={"id": "t1", "platform": "instagram"}), \
             patch.object(api, "_detect_library_lead_magnet") as lead_magnet:
            entry = api._add_library_entry(
                "tok", url="https://www.instagram.com/reel/abc/", text=None, note=None, author=None,
                structure_label=None, structure_text=None, fmt=None, image_url=None, image_note=None,
                source="user", platform="instagram",
            )
        ig_fetch.assert_called_once()
        li_fetch.assert_not_called()
        lead_magnet.assert_not_called()
        self.assertEqual(entry["platform"], "instagram")

    def test_linkedin_import_unchanged_still_uses_linkedin_scraper(self):
        """Non-régression : le chemin LinkedIn existant garde son comportement."""
        import api
        with patch.object(api, "fetch_post_detail", return_value={
            "text": "Un post LinkedIn assez long pour passer la validation.",
            "author": "Alex", "url": "https://www.linkedin.com/posts/abc", "image_url": None,
        }) as li_fetch, \
             patch.object(api, "fetch_ig_post_detail") as ig_fetch, \
             patch.object(api.db, "add_post_template", return_value={"id": "t2", "platform": "linkedin"}), \
             patch.object(api, "_detect_library_lead_magnet", return_value=None) as lead_magnet:
            api._add_library_entry(
                "tok", url="https://www.linkedin.com/posts/abc", text=None, note=None, author=None,
                structure_label=None, structure_text=None, fmt=None, image_url=None, image_note=None,
                source="user",
            )
        li_fetch.assert_called_once()
        ig_fetch.assert_not_called()
        lead_magnet.assert_called_once()

    def test_platform_passed_through_to_add_post_template(self):
        import api
        with patch.object(api, "fetch_ig_post_detail", return_value={
            "text": "Une caption Instagram assez longue pour passer.",
            "author": None, "url": "https://p", "image_url": None,
        }), patch.object(api.db, "add_post_template", return_value={"id": "t3"}) as add:
            api._add_library_entry(
                "tok", url="https://p", text=None, note=None, author=None,
                structure_label=None, structure_text=None, fmt=None, image_url=None, image_note=None,
                source="user", platform="instagram",
            )
        self.assertEqual(add.call_args.kwargs["platform"], "instagram")


class InstagramTramesEndpointTest(unittest.TestCase):
    """`GET /generate/instagram/trames` : bibliothèque du client devant le
    catalogue statique."""

    def setUp(self):
        try:
            import api  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("fastapi indisponible dans cet environnement (venv du repo cassé)")

    def test_library_entries_come_first_with_lib_prefixed_ids(self):
        import api
        library = [
            {"id": "abc-1", "structure_label": "Ma trame", "structure_text": "1. Hook\n2. Script"},
        ]
        with patch.object(api, "require_feature"), \
             patch.object(api.db, "list_post_templates", return_value=library):
            out = api.list_instagram_trames(token="tok")
        self.assertEqual(out["trames"][0]["id"], "lib:abc-1")
        self.assertEqual(out["trames"][0]["label"], "Ma trame")
        # Le catalogue statique reste entièrement présent derrière.
        self.assertEqual(out["trames"][len(library):], api.IG_TRAMES)

    def test_entry_without_exploitable_content_is_excluded(self):
        """Une entrée sans structure ni caption ne doit pas apparaître comme
        une trame vide et indistincte dans le choix du client."""
        import api
        library = [
            {"id": "empty-1", "structure_label": None, "structure_text": "", "post_text": None},
            {"id": "ok-1", "structure_label": None, "structure_text": None, "post_text": "Une caption importée"},
        ]
        with patch.object(api, "require_feature"), \
             patch.object(api.db, "list_post_templates", return_value=library):
            out = api.list_instagram_trames(token="tok")
        ids = [t["id"] for t in out["trames"]]
        self.assertNotIn("lib:empty-1", ids)
        self.assertIn("lib:ok-1", ids)

    def test_library_lookup_failure_falls_back_to_static_catalog_only(self):
        import api
        with patch.object(api, "require_feature"), \
             patch.object(api.db, "list_post_templates", side_effect=RuntimeError("Supabase down")):
            out = api.list_instagram_trames(token="tok")
        self.assertEqual(out["trames"], api.IG_TRAMES)

    def test_feature_gate_enforced(self):
        import api
        from fastapi import HTTPException
        with patch.object(api, "require_feature", side_effect=HTTPException(status_code=404)):
            with self.assertRaises(HTTPException):
                api.list_instagram_trames(token="tok")


class PostTemplatesPlatformGateTest(unittest.TestCase):
    """`GET`/`POST /me/post-templates` : `platform=instagram` gardé par le flag,
    `platform=linkedin` (défaut, comportement historique) jamais impacté."""

    def setUp(self):
        try:
            import api  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("fastapi indisponible dans cet environnement (venv du repo cassé)")

    def test_list_instagram_requires_feature(self):
        import api
        with patch.object(api, "require_feature") as gate, \
             patch.object(api.db, "list_post_templates", return_value=[]) as listing:
            api.me_post_templates(platform="instagram", token="tok")
        gate.assert_called_once_with("tok", "instagram")
        listing.assert_called_once_with("tok", platform="instagram")

    def test_list_linkedin_default_never_gated(self):
        """Non-régression : le parcours LinkedIn existant n'est jamais soumis
        au flag `instagram`, feature indisponible ou non."""
        import api
        with patch.object(api, "require_feature") as gate, \
             patch.object(api.db, "list_post_templates", return_value=[]) as listing:
            api.me_post_templates(token="tok")
        gate.assert_not_called()
        listing.assert_called_once_with("tok", platform="linkedin")

    def test_add_instagram_requires_feature(self):
        import api
        payload = api.PostTemplateRequest(text="Une caption assez longue pour être valide.", platform="instagram")
        with patch.object(api, "require_feature") as gate, \
             patch.object(api, "_add_library_entry", return_value={"id": "t1"}) as add:
            api.add_me_post_template(payload, token="tok")
        gate.assert_called_once_with("tok", "instagram")
        self.assertEqual(add.call_args.kwargs["platform"], "instagram")

    def test_add_without_platform_defaults_to_linkedin_ungated(self):
        import api
        payload = api.PostTemplateRequest(text="Un post assez long pour être valide.")
        with patch.object(api, "require_feature") as gate, \
             patch.object(api, "_add_library_entry", return_value={"id": "t1"}) as add:
            api.add_me_post_template(payload, token="tok")
        gate.assert_not_called()
        self.assertEqual(add.call_args.kwargs["platform"], "linkedin")


if __name__ == "__main__":
    unittest.main()
