"""Publication Zernio : timeout honnête, rejeu idempotent, 409 et 207.

Contexte (2026-09-08) : en prod, 14 des 18 posts programmés en échec l'étaient
sur « The read operation timed out » — un timeout de 30 s sur une publication
synchrone avec média. Pire : sur un timeout, on ne sait PAS si Zernio a publié,
et le post était marqué `failed` (donc « à reprogrammer » = doublon).
"""
from __future__ import annotations

import io
import json
import os
import socket
import unittest
import urllib.error
from unittest import mock

from src import zernio


class _Resp:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._raw


def _http_error(code: int, payload: dict) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://zernio.com/api/v1/posts", code, "err", {}, io.BytesIO(json.dumps(payload).encode("utf-8"))
    )


class RequestErrorMappingTest(unittest.TestCase):
    """`_request` doit distinguer « pas de réponse » (peut-être abouti) d'un refus."""

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"ZERNIO_API_KEY": "k"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_read_timeout_raises_zernio_timeout(self):
        # urllib lève socket.timeout NU sur un timeout de lecture (pas un URLError)
        with mock.patch("src.zernio.urllib.request.urlopen", side_effect=socket.timeout("The read operation timed out")):
            with self.assertRaises(zernio.ZernioTimeout) as ctx:
                zernio._request("POST", "/posts", body={}, timeout=45)
        self.assertIn("45 s", str(ctx.exception))

    def test_connect_timeout_wrapped_in_urlerror_raises_zernio_timeout(self):
        with mock.patch("src.zernio.urllib.request.urlopen", side_effect=urllib.error.URLError(socket.timeout("timed out"))):
            with self.assertRaises(zernio.ZernioTimeout):
                zernio._request("GET", "/accounts")

    def test_plain_network_error_is_not_a_timeout(self):
        with mock.patch("src.zernio.urllib.request.urlopen", side_effect=urllib.error.URLError("dns down")):
            with self.assertRaises(zernio.ZernioError) as ctx:
                zernio._request("GET", "/accounts")
        self.assertNotIsInstance(ctx.exception, zernio.ZernioTimeout)

    def test_409_raises_duplicate_with_existing_post_id(self):
        payload = {
            "error": "This exact content is already scheduled, publishing, or was posted to this account within the last 24 hours.",
            "details": {"accountId": "acc", "platform": "linkedin", "existingPostId": "65f1c0a9e2b5af0012ab34cd"},
        }
        with mock.patch("src.zernio.urllib.request.urlopen", side_effect=_http_error(409, payload)):
            with self.assertRaises(zernio.ZernioDuplicate) as ctx:
                zernio._request("POST", "/posts", body={})
        self.assertEqual(ctx.exception.existing_post_id, "65f1c0a9e2b5af0012ab34cd")
        self.assertIn("déjà publié", str(ctx.exception))

    def test_400_is_a_plain_error(self):
        with mock.patch("src.zernio.urllib.request.urlopen", side_effect=_http_error(400, {"error": "bad"})):
            with self.assertRaises(zernio.ZernioError) as ctx:
                zernio._request("POST", "/posts", body={})
        self.assertNotIsInstance(ctx.exception, zernio.ZernioDuplicate)
        self.assertNotIsInstance(ctx.exception, zernio.ZernioTimeout)

    def test_headers_and_timeout_reach_urlopen(self):
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["rid"] = req.get_header("X-request-id")
            seen["timeout"] = timeout
            return _Resp({"post": {"_id": "p"}})

        with mock.patch("src.zernio.urllib.request.urlopen", side_effect=fake_urlopen):
            zernio._request("POST", "/posts", body={}, headers={"x-request-id": "rid-1"}, timeout=77)
        self.assertEqual(seen, {"rid": "rid-1", "timeout": 77})


class CreatePostPublishTest(unittest.TestCase):
    """create_post : x-request-id, timeout de publication, rejeu sûr, 207."""

    def _capture(self, responses, **kwargs):
        calls = []

        def fake_request(method, path, *, params=None, body=None, headers=None, timeout=None):
            calls.append({"path": path, "body": body, "headers": headers or {}, "timeout": timeout})
            outcome = responses[min(len(calls) - 1, len(responses) - 1)]
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        with mock.patch.object(zernio, "_request", side_effect=fake_request):
            result = zernio.create_post("Hello", "acc-1", **kwargs)
        return calls, result

    def test_publish_now_uses_publish_timeout_and_request_id(self):
        calls, _ = self._capture([{"post": {"_id": "p1"}}], request_id="cibl-sched-42")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["headers"]["x-request-id"], "cibl-sched-42")
        self.assertGreaterEqual(calls[0]["timeout"], zernio.PUBLISH_TIMEOUT_DEFAULT_S)
        self.assertGreater(calls[0]["timeout"], zernio.DEFAULT_TIMEOUT_S)

    def test_draft_keeps_short_timeout(self):
        calls, _ = self._capture([{"post": {"_id": "p1"}}], is_draft=True)
        self.assertEqual(calls[0]["timeout"], zernio.DEFAULT_TIMEOUT_S)

    def test_missing_request_id_gets_a_generated_one(self):
        calls, _ = self._capture([{"post": {"_id": "p1"}}])
        self.assertTrue(calls[0]["headers"]["x-request-id"].startswith("cibl-"))

    def test_publish_timeout_env_override_never_below_default(self):
        with mock.patch.dict(os.environ, {"ZERNIO_PUBLISH_TIMEOUT_S": "5"}):
            self.assertEqual(zernio._publish_timeout(), zernio.DEFAULT_TIMEOUT_S)
        with mock.patch.dict(os.environ, {"ZERNIO_PUBLISH_TIMEOUT_S": "300"}):
            self.assertEqual(zernio._publish_timeout(), 300)
        with mock.patch.dict(os.environ, {"ZERNIO_PUBLISH_TIMEOUT_S": "abc"}):
            self.assertEqual(zernio._publish_timeout(), zernio.PUBLISH_TIMEOUT_DEFAULT_S)

    def test_timeout_then_replay_returns_existing_post_with_same_request_id(self):
        """1re tentative sans réponse, 2e : Zernio renvoie le post créé entre-temps."""
        calls, result = self._capture(
            [zernio.ZernioTimeout("no answer"), {"existingPost": {"_id": "p-orig", "status": "published"}}],
            request_id="cibl-sched-7",
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["headers"]["x-request-id"], calls[1]["headers"]["x-request-id"])
        self.assertEqual(result["post"]["_id"], "p-orig")
        self.assertTrue(result.get("replayed"))

    def test_two_timeouts_raise_honest_timeout_and_stop(self):
        calls_holder = {}
        with self.assertRaises(zernio.ZernioTimeout) as ctx:
            calls, _ = self._capture([zernio.ZernioTimeout("a"), zernio.ZernioTimeout("b"), {"post": {}}])
            calls_holder["calls"] = calls
        msg = str(ctx.exception)
        self.assertIn("PEUT-ÊTRE", msg)
        self.assertIn("vérifie", msg)

    def test_no_third_attempt_after_two_timeouts(self):
        count = {"n": 0}

        def fake_request(**kwargs):
            count["n"] += 1
            raise zernio.ZernioTimeout("x")

        with mock.patch.object(zernio, "_request", side_effect=lambda *a, **k: fake_request(**k)):
            with self.assertRaises(zernio.ZernioTimeout):
                zernio.create_post("Hello", "acc-1")
        self.assertEqual(count["n"], 2)

    def test_duplicate_is_not_retried_and_propagates(self):
        dup = zernio.ZernioDuplicate("déjà", existing_post_id="old")
        with self.assertRaises(zernio.ZernioDuplicate) as ctx:
            self._capture([dup, {"post": {"_id": "should-not-happen"}}])
        self.assertEqual(ctx.exception.existing_post_id, "old")

    def test_media_upload_retry_uses_a_fresh_request_id(self):
        """Le 1er essai a été REFUSÉ (400) : rejouer son id pourrait rendre ce refus."""
        media = [{"type": "image", "url": "https://cdn.example.com/a.png"}]
        with mock.patch("src.zernio.time.sleep"):
            calls, result = self._capture(
                [zernio.ZernioError("Zernio POST /posts a échoué (400) : Some media files failed to upload."), {"post": {"_id": "ok"}}],
                media_items=media,
                request_id="cibl-gp-9",
            )
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["headers"]["x-request-id"], "cibl-gp-9")
        self.assertNotEqual(calls[1]["headers"]["x-request-id"], "cibl-gp-9")
        self.assertTrue(calls[1]["headers"]["x-request-id"].startswith("cibl-gp-9"))
        self.assertEqual(result["post"]["_id"], "ok")

    def test_207_with_failed_status_is_an_error_not_a_success(self):
        body = {
            "post": {"_id": "p-fail", "status": "failed", "platforms": [{"platform": "linkedin", "errorMessage": "LinkedIn a refusé le média"}]},
            "message": "Publish failed",
            "error": "No platform published",
            "platformResults": [{"platform": "linkedin", "status": "failed", "error": "LinkedIn a refusé le média"}],
        }
        with self.assertRaises(zernio.ZernioError) as ctx:
            self._capture([body])
        self.assertNotIsInstance(ctx.exception, zernio.ZernioTimeout)
        self.assertIn("No platform published", str(ctx.exception))

    def test_207_failed_falls_back_to_platform_error_message(self):
        body = {"post": {"_id": "p", "status": "failed", "platforms": [{"platform": "linkedin", "errorMessage": "quota"}]}}
        with self.assertRaises(zernio.ZernioError) as ctx:
            self._capture([body])
        self.assertIn("quota", str(ctx.exception))

    def test_published_and_transient_scheduled_pass_through(self):
        _, ok = self._capture([{"post": {"_id": "p1", "status": "published"}}])
        self.assertEqual(ok["post"]["_id"], "p1")
        # « scheduled » = erreur transitoire, Zernio republie seul : pas un échec.
        _, later = self._capture([{"post": {"_id": "p2", "status": "scheduled"}}])
        self.assertEqual(later["post"]["_id"], "p2")


class SchedulerPublishOutcomeTest(unittest.TestCase):
    """Le cron : un 409 = publié (pas failed), un timeout = message honnête."""

    def _run_with(self, create_post_side_effect):
        from src import scheduler

        post = {
            "id": "sp-1",
            "user_id": "u-1",
            "post_text": "texte",
            "media_items": [{"type": "image", "url": "https://x/y.png"}],
            "cross_posts": None,
            "zernio_account_id": "li-acc",
        }
        updates = []
        with (
            mock.patch.object(scheduler.db, "admin_enabled", return_value=True),
            mock.patch.object(scheduler.zernio, "enabled", return_value=True),
            mock.patch.object(scheduler.db, "get_due_scheduled_posts", return_value=[post]),
            mock.patch.object(scheduler.db, "update_scheduled_post_status", side_effect=lambda *a, **k: updates.append((a, k))),
            mock.patch.object(scheduler.zernio, "prepare_image_media_items", side_effect=lambda items: items),
            mock.patch.object(scheduler.zernio, "create_post", side_effect=create_post_side_effect) as cp,
        ):
            scheduler.run()
        return updates, cp

    def test_duplicate_marks_published_with_existing_id(self):
        updates, cp = self._run_with(zernio.ZernioDuplicate("déjà", existing_post_id="z-old"))
        self.assertEqual(len(updates), 1)
        args, kwargs = updates[0]
        self.assertEqual(args[:2], ("sp-1", "published"))
        self.assertEqual(kwargs.get("zernio_post_id"), "z-old")
        # x-request-id stable = l'id du post programmé
        self.assertEqual(cp.call_args.kwargs.get("request_id"), "cibl-sched-sp-1")

    def test_timeout_marks_failed_with_honest_message(self):
        updates, _ = self._run_with(zernio.ZernioTimeout("Zernio n'a pas confirmé… Le post est PEUT-ÊTRE déjà en ligne"))
        args, kwargs = updates[0]
        self.assertEqual(args[:2], ("sp-1", "failed"))
        self.assertIn("PEUT-ÊTRE", kwargs.get("error", ""))
        self.assertNotIn("read operation timed out", kwargs.get("error", ""))

    def test_success_records_zernio_id(self):
        updates, _ = self._run_with(lambda *a, **k: {"post": {"_id": "z-new", "status": "published"}})
        args, kwargs = updates[0]
        self.assertEqual(args[:2], ("sp-1", "published"))
        self.assertEqual(kwargs.get("zernio_post_id"), "z-new")


try:  # pragma: no cover - dépend de l'env local
    import api  # noqa: E402

    _HAS_API = True
except Exception:  # noqa: BLE001
    _HAS_API = False


@unittest.skipUnless(_HAS_API, "fastapi absent de l'environnement local")
class PublishHttpErrorMappingTest(unittest.TestCase):
    def test_timeout_is_504_not_502(self):
        exc = api._publish_http_error(zernio.ZernioTimeout("peut-être en ligne"))
        self.assertEqual(exc.status_code, 504)
        self.assertIn("peut-être", exc.detail)

    def test_duplicate_is_409(self):
        exc = api._publish_http_error(zernio.ZernioDuplicate("déjà", existing_post_id="o"), prefix="Publication LinkedIn impossible : ")
        self.assertEqual(exc.status_code, 409)
        self.assertTrue(exc.detail.startswith("Publication LinkedIn impossible : "))

    def test_other_errors_stay_502(self):
        self.assertEqual(api._publish_http_error(zernio.ZernioError("boom")).status_code, 502)


if __name__ == "__main__":
    unittest.main()
