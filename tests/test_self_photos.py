"""Tests pour la génération d'image à identité (photos de soi)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.image_gen import with_identity_prefix, generate_post_image


class IdentityPromptTest(unittest.TestCase):
    def test_prefix_added_once(self):
        p = with_identity_prefix("Une scène de bureau lumineuse.")
        self.assertIn("Préserve fidèlement", p)
        self.assertIn("Une scène de bureau lumineuse.", p)
        # Idempotent
        p2 = with_identity_prefix(p)
        self.assertEqual(p.count("Préserve fidèlement"), p2.count("Préserve fidèlement"))

    def test_empty_prompt_gets_prefix(self):
        p = with_identity_prefix("")
        self.assertIn("Préserve fidèlement", p)


class GenerateWithSelfPhotosTest(unittest.TestCase):
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False)
    @patch("src.image_gen.OpenAI")
    def test_passes_multiple_reference_images_and_identity_prefix(self, openai_cls):
        client = MagicMock()
        openai_cls.return_value = client
        edit = client.images.edit
        edit.return_value = MagicMock(data=[MagicMock(b64_json="abcd")])

        refs = [
            ("self-1.png", b"img1", "image/png"),
            ("self-2.png", b"img2", "image/png"),
        ]
        result = generate_post_image(
            "Post sur la délégation",
            prompt="Personne en visioconférence dans un bureau.",
            reference_images=refs,
            identity=True,
        )
        self.assertTrue(result["image_data"].startswith("data:image/png;base64,"))
        self.assertIn("Préserve fidèlement", result["prompt_used"])
        kwargs = edit.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-image-2")
        self.assertEqual(list(kwargs["image"]), list(refs))
        self.assertIn("Préserve fidèlement", kwargs["prompt"])
        client.images.generate.assert_not_called()

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False)
    @patch("src.image_gen.OpenAI")
    def test_single_reference_image_still_uses_edit(self, openai_cls):
        client = MagicMock()
        openai_cls.return_value = client
        client.images.edit.return_value = MagicMock(data=[MagicMock(b64_json="xy")])
        ref = ("ref.png", b"bytes", "image/png")
        generate_post_image("texte assez long pour le post", prompt="style", reference_image=ref)
        self.assertEqual(list(client.images.edit.call_args.kwargs["image"]), [ref])


if __name__ == "__main__":
    unittest.main()
