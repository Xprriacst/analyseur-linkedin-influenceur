"""Tests avatar IA vidéo (HeyGen) — client, normalisations, job de fond (0065)."""
from __future__ import annotations

import base64
import unittest
from unittest.mock import patch

from src import heygen


class FilePayloadTest(unittest.TestCase):
    def test_data_url_becomes_base64_payload(self):
        raw = base64.b64encode(b"fake-jpeg-bytes").decode()
        payload = heygen._file_payload(f"data:image/jpeg;base64,{raw}")
        self.assertEqual(payload["type"], "base64")
        self.assertEqual(payload["media_type"], "image/jpeg")
        self.assertEqual(payload["data"], raw)

    def test_https_url_passes_through(self):
        payload = heygen._file_payload("https://media.zernio.com/photo.jpg")
        self.assertEqual(payload, {"type": "url", "url": "https://media.zernio.com/photo.jpg"})

    def test_http_url_rejected(self):
        with self.assertRaises(heygen.HeygenError):
            heygen._file_payload("http://example.com/photo.jpg")

    def test_unsupported_content_type_rejected(self):
        raw = base64.b64encode(b"gif").decode()
        with self.assertRaises(heygen.HeygenError):
            heygen._file_payload(f"data:image/gif;base64,{raw}")

    def test_broken_base64_rejected(self):
        with self.assertRaises(heygen.HeygenError):
            heygen._file_payload("data:image/png;base64,%%%pas-du-base64%%%")

    def test_empty_source_rejected(self):
        with self.assertRaises(heygen.HeygenError):
            heygen._file_payload("  ")


class NormalizeTest(unittest.TestCase):
    def test_status_mapping(self):
        self.assertEqual(heygen._normalize_status("completed"), "completed")
        self.assertEqual(heygen._normalize_status("SUCCESS"), "completed")
        self.assertEqual(heygen._normalize_status("failed"), "failed")
        self.assertEqual(heygen._normalize_status("processing"), "processing")
        # Statut inconnu ou absent = « en cours » (jamais un faux succès).
        self.assertEqual(heygen._normalize_status("waiting"), "processing")
        self.assertEqual(heygen._normalize_status(None), "processing")

    def test_normalize_avatar_from_create_response(self):
        data = {
            "avatar_item": {
                "id": "look_abc",
                "group_id": "group_xyz",
                "status": "processing",
                "preview_image_url": "https://files.heygen.ai/p.png",
                "default_voice_id": None,
            },
            "avatar_group": {"id": "group_xyz", "default_voice_id": "v1"},
        }
        avatar = heygen._normalize_avatar(data)
        self.assertEqual(avatar["look_id"], "look_abc")
        self.assertEqual(avatar["group_id"], "group_xyz")
        self.assertEqual(avatar["status"], "processing")
        self.assertEqual(avatar["default_voice_id"], "v1")

    def test_normalize_avatar_flat_shape(self):
        # Le schéma HeyGen n'est pas garanti : la forme à plat doit passer aussi.
        avatar = heygen._normalize_avatar({"id": "look_1", "status": "completed"})
        self.assertEqual(avatar["look_id"], "look_1")
        self.assertEqual(avatar["status"], "completed")

    def test_normalize_avatar_without_id_raises(self):
        with self.assertRaises(heygen.HeygenError):
            heygen._normalize_avatar({"status": "completed"})


class ListVoicesTest(unittest.TestCase):
    def test_normalizes_and_skips_malformed_entries(self):
        raw = {
            "voices": [
                {"voice_id": "v1", "name": "Claire", "gender": "Female", "preview_audio_url": "https://x/p.mp3"},
                {"name": "sans id — ignorée"},
                "pas-un-dict",
                {"id": "v2"},
            ]
        }
        with patch.object(heygen, "_request", return_value=raw):
            voices = heygen.list_voices()
        self.assertEqual([v["voice_id"] for v in voices], ["v1", "v2"])
        self.assertEqual(voices[0]["gender"], "female")
        self.assertEqual(voices[1]["name"], "Voix")


class CreateVideoTest(unittest.TestCase):
    def test_empty_script_rejected_before_network(self):
        with patch.object(heygen, "_request") as req:
            with self.assertRaises(heygen.HeygenError):
                heygen.create_avatar_video("look_1", "   ", "v1")
            req.assert_not_called()

    def test_script_too_long_rejected_before_network(self):
        with patch.object(heygen, "_request") as req:
            with self.assertRaises(heygen.HeygenError):
                heygen.create_avatar_video("look_1", "x" * (heygen.MAX_SCRIPT_CHARS + 1), "v1")
            req.assert_not_called()

    def test_missing_voice_rejected(self):
        with self.assertRaises(heygen.HeygenError):
            heygen.create_avatar_video("look_1", "Bonjour", "")

    def test_body_carries_9_16_and_avatar_iv(self):
        captured: dict = {}

        def fake_request(method, path, **kwargs):
            captured["method"] = method
            captured["path"] = path
            captured["body"] = kwargs.get("body")
            return {"video_id": "vid_1"}

        with patch.object(heygen, "_request", side_effect=fake_request):
            video_id = heygen.create_avatar_video("look_1", "Bonjour à tous", "v1")
        self.assertEqual(video_id, "vid_1")
        self.assertEqual(captured["path"], "/v3/videos")
        body = captured["body"]
        # Le 9:16 et l'engine sont ce qui fait un Reel — les perdre donnerait une
        # vidéo paysage d'apparence normale, panne silencieuse.
        self.assertEqual(body["aspect_ratio"], "9:16")
        self.assertEqual(body["engine"], {"type": "avatar_iv"})
        self.assertEqual(body["avatar_id"], "look_1")
        self.assertEqual(body["voice_id"], "v1")

    def test_missing_video_id_raises(self):
        with patch.object(heygen, "_request", return_value={}):
            with self.assertRaises(heygen.HeygenError):
                heygen.create_avatar_video("look_1", "Bonjour", "v1")


class GetVideoTest(unittest.TestCase):
    def test_prefers_captioned_video_url(self):
        raw = {
            "status": "completed",
            "video_url": "https://files.heygen.ai/raw.mp4",
            "captioned_video_url": "https://files.heygen.ai/sub.mp4",
            "duration": "42.5",
        }
        with patch.object(heygen, "_request", return_value=raw):
            video = heygen.get_video("vid_1")
        self.assertEqual(video["status"], "completed")
        self.assertEqual(video["video_url"], "https://files.heygen.ai/sub.mp4")
        self.assertEqual(video["duration"], 42.5)

    def test_failure_message_surfaces(self):
        raw = {"status": "failed", "failure_message": "moderation"}
        with patch.object(heygen, "_request", return_value=raw):
            video = heygen.get_video("vid_1")
        self.assertEqual(video["status"], "failed")
        self.assertEqual(video["error"], "moderation")


class AvatarJobProjectionTest(unittest.TestCase):
    """Toute colonne écrite par create_avatar_video_job doit être relue.

    Une colonne absente de `_AVATAR_VIDEO_JOB_COLS` serait lue `None` par le
    thread SANS erreur — 5ᵉ occurrence du piège ALE-216/ALE-286/#387/lead-jobs
    si ce test n'existait pas.
    """

    def test_every_written_column_is_read_back(self):
        from src import db

        projected = set(db._AVATAR_VIDEO_JOB_COLS.split(","))
        written = {"user_id", "status", "script", "target_key", "avatar_look_id", "voice_id"}
        self.assertEqual(written - {"user_id"} - projected, set())
        # Celles que le thread écrit en cours de route doivent revenir aussi.
        for col in ("heygen_video_id", "result", "error"):
            self.assertIn(col, projected)


class ProcessAvatarVideoJobTest(unittest.TestCase):
    """Le job de fond : débit au succès uniquement, annulation respectée."""

    JOB = {
        "id": "job-1",
        "status": "queued",
        "script": "Bonjour",
        "target_key": "reel:abc",
        "avatar_look_id": "look_1",
        "voice_id": "v1",
        "heygen_video_id": None,
    }

    def _run(self, *, statuses, video_states, download=b"x" * 10, upload_url="https://media.zernio.com/reel.mp4"):
        """statuses : réponses successives de get_avatar_video_job_status ;
        video_states : réponses successives de heygen.get_video."""
        from src import jobs

        updates: list[dict] = []
        debits: list[str] = []

        def fake_update(token, job_id, **fields):
            updates.append(fields)

        with patch("src.db.get_avatar_video_job", return_value=dict(self.JOB)), \
             patch("src.db.get_avatar_video_job_status", side_effect=statuses), \
             patch("src.db.update_avatar_video_job", side_effect=fake_update), \
             patch("src.db.debit_credits", side_effect=lambda t, a: (debits.append(a), (True, 42))[1]), \
             patch("src.heygen.create_avatar_video", return_value="vid_1"), \
             patch("src.heygen.get_video", side_effect=video_states), \
             patch("src.heygen.download_video", return_value=download), \
             patch("src.zernio.upload_reel_video", return_value=upload_url), \
             patch("time.sleep"):
            jobs.process_avatar_video_job("token", "job-1")
        return updates, debits

    def test_success_debits_once_and_stores_hosted_url(self):
        updates, debits = self._run(
            statuses=["running"] * 10,
            video_states=[
                {"status": "processing", "video_url": None, "thumbnail_url": None, "duration": None, "error": None},
                {"status": "completed", "video_url": "https://files.heygen.ai/tmp.mp4",
                 "thumbnail_url": "https://files.heygen.ai/t.jpg", "duration": 42.0, "error": None},
            ],
        )
        self.assertEqual(debits, ["avatar_video"])
        done = [u for u in updates if u.get("status") == "done"]
        self.assertEqual(len(done), 1)
        result = done[0]["result"]
        # C'est l'URL RE-HÉBERGÉE (pérenne) qui doit être stockée — l'URL HeyGen
        # est pré-signée et expire : la persister casserait la publication différée.
        self.assertEqual(result["video_url"], "https://media.zernio.com/reel.mp4")
        self.assertEqual(result["credits"], 42)

    def test_cancelled_during_render_never_debits_nor_completes(self):
        updates, debits = self._run(
            statuses=["running", "cancelled"],
            video_states=[
                {"status": "processing", "video_url": None, "thumbnail_url": None, "duration": None, "error": None},
            ],
        )
        self.assertEqual(debits, [])
        self.assertFalse(any(u.get("status") == "done" for u in updates))

    def test_heygen_failure_marks_error_without_debit(self):
        updates, debits = self._run(
            statuses=["running"] * 10,
            video_states=[{"status": "failed", "video_url": None, "thumbnail_url": None, "duration": None, "error": "moderation"}],
        )
        self.assertEqual(debits, [])
        errors = [u for u in updates if u.get("status") == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("moderation", errors[0]["error"])

    def test_completed_without_url_is_an_error(self):
        updates, debits = self._run(
            statuses=["running"] * 10,
            video_states=[{"status": "completed", "video_url": None, "thumbnail_url": None, "duration": None, "error": None}],
        )
        self.assertEqual(debits, [])
        self.assertTrue(any(u.get("status") == "error" for u in updates))


class CreditCostTest(unittest.TestCase):
    def test_avatar_video_has_a_credit_cost(self):
        from src import db

        self.assertIn("avatar_video", db.CREDIT_COSTS)
        self.assertGreater(db.CREDIT_COSTS["avatar_video"], 0)


if __name__ == "__main__":
    unittest.main()
