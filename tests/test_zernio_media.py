import base64
import unittest
from unittest.mock import patch

from src import zernio


class FakeUploadResponse:
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


if __name__ == "__main__":
    unittest.main()
