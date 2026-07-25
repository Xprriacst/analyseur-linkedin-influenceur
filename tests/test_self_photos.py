"""Tests pour la génération d'image à identité (photos de soi)."""
from __future__ import annotations

import io
import unittest
from unittest.mock import MagicMock, patch

from openai import BadRequestError

from src.image_gen import (
    ImageGenError,
    fallback_scene_prompt,
    generate_post_image,
    normalize_reference_image,
    resolve_image_prompt,
    with_identity_prefix,
)


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


class FallbackAndResolvePromptTest(unittest.TestCase):
    def test_fallback_scene_never_empty(self):
        self.assertTrue(fallback_scene_prompt("", identity=False).strip())
        self.assertTrue(fallback_scene_prompt("", identity=True).strip())
        self.assertIn("délégation", fallback_scene_prompt("Post sur la délégation", identity=True))

    @patch("src.image_gen.build_image_prompt", return_value="")
    def test_resolve_falls_back_when_claude_returns_empty(self, _build):
        prompt = resolve_image_prompt("Un post sur la vente", prompt=None, identity=False)
        self.assertTrue(prompt.strip())
        self.assertIn("vente", prompt)

    @patch("src.image_gen.build_image_prompt", return_value="")
    def test_resolve_identity_never_prefix_only(self, _build):
        prompt = resolve_image_prompt("", prompt=None, identity=True)
        self.assertIn("Préserve fidèlement", prompt)
        # Au-delà du préfixe : une scène concrète (sinon OpenAI 400).
        self.assertGreater(len(prompt), 120)
        self.assertIn("bureau", prompt.lower())


class NormalizeReferenceImageTest(unittest.TestCase):
    def test_octet_stream_becomes_image_png(self):
        filename, data, ct = normalize_reference_image(
            ("self-1.png", b"\x89PNG", "application/octet-stream")
        )
        self.assertEqual(filename, "self-1.png")
        self.assertEqual(data, b"\x89PNG")
        self.assertEqual(ct, "image/png")

    def test_image_jpg_alias_normalized(self):
        _, _, ct = normalize_reference_image(("a.jpg", b"xxxx", "image/jpg"))
        self.assertEqual(ct, "image/jpeg")


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
        files = list(kwargs["image"])
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0][0], "self-1.png")
        self.assertIsInstance(files[0][1], io.BytesIO)
        self.assertEqual(files[0][1].getvalue(), b"img1")
        self.assertEqual(files[0][2], "image/png")
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
        files = list(client.images.edit.call_args.kwargs["image"])
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0][0], "ref.png")
        self.assertEqual(files[0][1].getvalue(), b"bytes")
        self.assertEqual(files[0][2], "image/png")

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False)
    @patch("src.image_gen.OpenAI")
    def test_openai_no_valid_description_becomes_friendly_error(self, openai_cls):
        import httpx

        client = MagicMock()
        openai_cls.return_value = client
        req = httpx.Request("POST", "https://api.openai.com/v1/images/edits")
        resp = httpx.Response(
            400,
            request=req,
            json={"error": {"message": "No valid description provided."}},
        )
        client.images.edit.side_effect = BadRequestError(
            message="Error code: 400 - {'error': {'message': 'No valid description provided.'}}",
            response=resp,
            body={"error": {"message": "No valid description provided."}},
        )
        with self.assertRaises(ImageGenError) as ctx:
            generate_post_image(
                "post",
                prompt="Une scène de bureau",
                reference_image=("self.png", b"img", "image/png"),
                identity=True,
            )
        self.assertIn("aucune description valide", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
