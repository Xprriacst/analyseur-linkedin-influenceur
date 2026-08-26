"""Images durables : self-photos, bibliothèque, vignettes anciennes.

Ce fichier verrouille trois points :
- une photo de soi n'est plus envoyée dans le `/temp/` de Zernio mais dans le
  stockage durable de l'app ;
- un template importé depuis LinkedIn réhéberge son image avant persistance ;
- les anciennes URLs temporaires sont signalées honnêtement au front.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:  # noqa: SIM105 - l'env local du dépôt n'a pas toujours fastapi
    import api  # noqa: E402
except ModuleNotFoundError:
    api = None  # type: ignore
from src import db, media_store  # noqa: E402


class _FakeBucket:
    def __init__(self):
        self.upload_calls = []

    def upload(self, *, path, file, file_options):
        self.upload_calls.append((path, file, file_options))
        return {"path": path}

    def get_public_url(self, path):
        return f"https://storage.example.com/{path}"


class _FakeStorage:
    def __init__(self, bucket):
        self._bucket = bucket
        self.bucket_name = None

    def from_(self, bucket_name):
        self.bucket_name = bucket_name
        return self._bucket


class MediaStoreUploadTest(unittest.TestCase):
    @patch("src.media_store.db.admin_enabled", return_value=True)
    @patch("src.media_store.db.admin_client")
    def test_upload_image_data_url_goes_to_app_media_bucket(self, admin_client, _enabled):
        bucket = _FakeBucket()
        admin = MagicMock()
        admin.storage = _FakeStorage(bucket)
        admin_client.return_value = admin

        url = media_store.upload_image_data_url(
            "data:image/png;base64,QUJDRA==",
            filename="Portrait Tom.png",
            scope="self-photos",
        )

        self.assertTrue(url.startswith("https://storage.example.com/self-photos/"))
        self.assertEqual(admin.storage.bucket_name, "app-media")
        path, payload, options = bucket.upload_calls[0]
        self.assertIn("Portrait-Tom.png", path)
        self.assertEqual(payload, b"ABCD")
        self.assertEqual(options["content-type"], "image/png")
        self.assertEqual(options["upsert"], "false")


@unittest.skipIf(api is None, "fastapi absent de l'environnement local")
class LibraryRehostTest(unittest.TestCase):
    def test_imported_link_rehosts_image_before_insert(self):
        detail = {
            "text": "Post utile sur la titularisation en pharmacie.",
            "author": "Stephen",
            "url": "https://www.linkedin.com/posts/x",
            "image_url": "https://media.licdn.com/dms/image/v2/abc",
        }
        inserted = {"id": "tpl-1", "image_url": "https://storage.example.com/library/post.png"}
        with (
            patch.object(api, "fetch_post_detail", return_value=detail),
            patch.object(api.media_store, "rehost_external_image", return_value="https://storage.example.com/library/post.png") as rehost,
            patch.object(api.db, "add_post_template", return_value=inserted) as add,
            patch.object(api, "_detect_library_lead_magnet", return_value=None),
        ):
            out = api._add_library_entry(
                "tok",
                url="https://www.linkedin.com/posts/x",
                text=None,
                note=None,
                author=None,
                structure_label=None,
                structure_text=None,
                fmt=None,
                image_url=None,
                image_note=None,
                source="influencer",
            )

        self.assertEqual(out["id"], "tpl-1")
        rehost.assert_called_once_with(
            "https://media.licdn.com/dms/image/v2/abc",
            filename_stem="linkedin-post-image",
            scope="library",
        )
        self.assertEqual(add.call_args.kwargs["image_url"], "https://storage.example.com/library/post.png")

    def test_failed_rehost_drops_image_instead_of_persisting_ephemeral_url(self):
        detail = {
            "text": "Post utile sur la titularisation en pharmacie.",
            "author": "Stephen",
            "url": "https://www.linkedin.com/posts/x",
            "image_url": "https://media.licdn.com/dms/image/v2/abc",
        }
        with (
            patch.object(api, "fetch_post_detail", return_value=detail),
            patch.object(api.media_store, "rehost_external_image", side_effect=media_store.MediaStoreError("403")) as rehost,
            patch.object(api.db, "add_post_template", return_value={"id": "tpl-1"}) as add,
            patch.object(api, "_detect_library_lead_magnet", return_value=None),
        ):
            api._add_library_entry(
                "tok",
                url="https://www.linkedin.com/posts/x",
                text=None,
                note=None,
                author=None,
                structure_label=None,
                structure_text=None,
                fmt=None,
                image_url=None,
                image_note=None,
                source="influencer",
            )

        rehost.assert_called_once()
        self.assertIsNone(add.call_args.kwargs["image_url"])


class SelfPhotoListingTest(unittest.TestCase):
    @patch("src.db.client_for_token")
    @patch("src.db.get_user", return_value={"id": "u1"})
    @patch("src.db.supabase_enabled", return_value=True)
    def test_list_self_photos_marks_temporary_urls(self, _enabled, _user, client_for):
        fake = MagicMock()
        fake.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[
                {"id": "a", "image_url": "https://media.zernio.com/temp/abc.jpg", "filename": "old.jpg"},
                {"id": "b", "image_url": "https://storage.example.com/self-photos/new.jpg", "filename": "new.jpg"},
            ]
        )
        client_for.return_value = fake

        rows = db.list_self_photos("tok")

        self.assertTrue(rows[0]["is_temporary"])
        self.assertFalse(rows[1]["is_temporary"])


if __name__ == "__main__":
    unittest.main()
