"""Tests pour la génération d'image à identité (photos de soi)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from openai import InternalServerError

from src.image_gen import ImageGenError, with_identity_prefix, generate_post_image


def _openai_http_error(status: int, message: str):
    import httpx

    req = httpx.Request("POST", "https://api.openai.com/v1/images/generations")
    resp = httpx.Response(status, request=req, json={"error": message})
    return InternalServerError(
        message=f"Error code: {status} - {{'error': '{message}'}}",
        response=resp,
        body={"error": message},
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

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False)
    @patch("src.image_gen.time.sleep", return_value=None)
    @patch("src.image_gen.OpenAI")
    def test_retries_on_too_many_concurrent_then_succeeds(self, openai_cls, _sleep):
        client = MagicMock()
        openai_cls.return_value = client
        busy = _openai_http_error(503, "Too many concurrent requests")
        client.images.generate.side_effect = [
            busy,
            busy,
            MagicMock(data=[MagicMock(b64_json="okimg")]),
        ]
        result = generate_post_image("un post assez long", prompt="Bureau lumineux")
        self.assertTrue(result["image_data"].endswith("okimg"))
        self.assertEqual(client.images.generate.call_count, 3)
        self.assertEqual(_sleep.call_count, 2)

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False)
    @patch("src.image_gen.time.sleep", return_value=None)
    @patch("src.image_gen.OpenAI")
    def test_concurrent_exhausted_becomes_friendly_error(self, openai_cls, _sleep):
        client = MagicMock()
        openai_cls.return_value = client
        busy = _openai_http_error(503, "Too many concurrent requests")
        client.images.generate.side_effect = busy
        with self.assertRaises(ImageGenError) as ctx:
            generate_post_image("un post assez long", prompt="Bureau lumineux")
        self.assertIn("saturé", str(ctx.exception).lower())
        self.assertEqual(client.images.generate.call_count, 4)


if __name__ == "__main__":
    unittest.main()
