import base64
import unittest
import urllib.error
from unittest.mock import patch

from src import zernio


class FakeUploadResponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b""


class ZernioMediaTest(unittest.TestCase):
    def test_create_post_includes_media_items(self):
        calls = []

        def fake_request(method, path, *, params=None, body=None):
            calls.append((method, path, body))
            return {"post": {"_id": "post-1"}}

        media_items = [{"type": "image", "url": "https://cdn.example.com/image.png"}]
        with patch.object(zernio, "_request", side_effect=fake_request):
            result = zernio.create_post("Hello", "acc-1", media_items=media_items)

        self.assertEqual(result["post"]["_id"], "post-1")
        self.assertEqual(calls[0][0:2], ("POST", "/posts"))
        self.assertEqual(calls[0][2]["mediaItems"], media_items)
        self.assertEqual(calls[0][2]["platforms"], [{"platform": "linkedin", "accountId": "acc-1"}])

    def test_prepare_image_media_items_uploads_data_url(self):
        png_data = b"fake-png"
        data_url = "data:image/png;base64," + base64.b64encode(png_data).decode("ascii")
        presign_calls = []
        upload_calls = []

        def fake_request(method, path, *, params=None, body=None):
            presign_calls.append((method, path, body))
            return {"uploadUrl": "https://upload.example.com/put", "publicUrl": "https://media.example.com/image.png"}

        def fake_urlopen(req, timeout=0):
            upload_calls.append((req.full_url, req.data, req.headers, timeout))
            return FakeUploadResponse()

        with (
            patch.object(zernio, "_request", side_effect=fake_request),
            patch("src.zernio.urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            media_items = zernio.prepare_image_media_items([
                {"data_url": data_url, "filename": "post image.png"},
            ])

        self.assertEqual(media_items, [{"type": "image", "url": "https://media.example.com/image.png", "title": "post image.png"}])
        self.assertEqual(presign_calls[0][0:2], ("POST", "/media/presign"))
        self.assertEqual(presign_calls[0][2]["filename"], "post-image.png")
        self.assertEqual(presign_calls[0][2]["contentType"], "image/png")
        self.assertEqual(presign_calls[0][2]["size"], len(png_data))
        self.assertEqual(upload_calls[0][0], "https://upload.example.com/put")
        self.assertEqual(upload_calls[0][1], png_data)

    def test_upload_media_bytes_retries_until_public_url_readable(self):
        """PUT réussit tout de suite, mais l'URL publique n'est lisible qu'au 3e essai."""
        png_data = b"fake-png"
        attempts = {"n": 0}

        def fake_request(method, path, *, params=None, body=None):
            return {"uploadUrl": "https://upload.example.com/put", "publicUrl": "https://media.example.com/image.png"}

        def fake_urlopen(req, timeout=0):
            if req.get_method() == "PUT":
                return FakeUploadResponse()
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise urllib.error.URLError("not ready yet")
            return FakeUploadResponse(status=200)

        with (
            patch.object(zernio, "_request", side_effect=fake_request),
            patch("src.zernio.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("src.zernio.time.sleep") as fake_sleep,
        ):
            public_url = zernio.upload_media_bytes("photo.png", "image/png", png_data)

        self.assertEqual(public_url, "https://media.example.com/image.png")
        self.assertEqual(attempts["n"], 3)
        self.assertEqual(fake_sleep.call_count, 2)

    def test_create_post_retries_once_on_media_upload_failure(self):
        """Filet de sécurité : si Zernio répond 'failed to upload' malgré l'attente, on retente une fois."""
        media_items = [{"type": "image", "url": "https://cdn.example.com/image.png"}]
        calls = {"n": 0}

        def fake_request(method, path, *, params=None, body=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise zernio.ZernioError("Zernio POST /posts a échoué (400) : Some media files failed to upload.")
            return {"post": {"_id": "post-1"}}

        with (
            patch.object(zernio, "_request", side_effect=fake_request),
            patch("src.zernio.time.sleep") as fake_sleep,
        ):
            result = zernio.create_post("Hello", "acc-1", media_items=media_items)

        self.assertEqual(result["post"]["_id"], "post-1")
        self.assertEqual(calls["n"], 2)
        fake_sleep.assert_called_once()

    def test_create_post_does_not_retry_unrelated_errors(self):
        media_items = [{"type": "image", "url": "https://cdn.example.com/image.png"}]

        def fake_request(method, path, *, params=None, body=None):
            raise zernio.ZernioError("Zernio POST /posts a échoué (401) : Unauthorized.")

        with patch.object(zernio, "_request", side_effect=fake_request):
            with self.assertRaises(zernio.ZernioError):
                zernio.create_post("Hello", "acc-1", media_items=media_items)


if __name__ == "__main__":
    unittest.main()
