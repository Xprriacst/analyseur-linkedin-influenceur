"""Tests avatar IA — mode Digital Twin (vidéo d'entraînement + consentement HeyGen, 0066).

Le mode photo (0065) reste par défaut et non touché par ce lot — un test dédié
verrouille qu'il continue d'envoyer `type: "photo"`. Le mode digital_twin
n'a jamais été exécuté contre la vraie API HeyGen (clé non accessible dans ce
bac à sable) : ces tests verrouillent le CONTRAT qu'on a construit (payloads
envoyés, normalisation tolérante des réponses), pas un comportement HeyGen
vérifié en direct.
"""
from __future__ import annotations

import datetime
import unittest
from unittest.mock import MagicMock, patch

from src import heygen


class VideoUrlPayloadTest(unittest.TestCase):
    def test_https_url_passes_through(self):
        payload = heygen._video_url_payload("https://media.zernio.com/training.mp4")
        self.assertEqual(payload, {"type": "url", "url": "https://media.zernio.com/training.mp4"})

    def test_http_url_rejected(self):
        with self.assertRaises(heygen.HeygenError):
            heygen._video_url_payload("http://example.com/training.mp4")

    def test_data_url_rejected(self):
        # Volontairement pas de branche data: URL pour la vidéo — un clip de
        # 2 min en base64 dans un body JSON serait énorme (leçon OOM).
        with self.assertRaises(heygen.HeygenError):
            heygen._video_url_payload("data:video/mp4;base64,AAAA")

    def test_empty_source_rejected(self):
        with self.assertRaises(heygen.HeygenError):
            heygen._video_url_payload("   ")


class CreateDigitalTwinAvatarTest(unittest.TestCase):
    def test_body_carries_digital_twin_type_and_video_url(self):
        captured: dict = {}

        def fake_request(method, path, **kwargs):
            captured["method"] = method
            captured["path"] = path
            captured["body"] = kwargs.get("body")
            return {
                "avatar_item": {"id": "look_dt1", "group_id": "group_dt1", "status": "processing"},
            }

        with patch.object(heygen, "_request", side_effect=fake_request):
            avatar = heygen.create_digital_twin_avatar("Ma vidéo", "https://media.zernio.com/train.mp4")

        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["path"], "/v3/avatars")
        body = captured["body"]
        # Le champ `type` est ce qui distingue un digital twin d'une photo côté
        # HeyGen — l'écraser reviendrait à créer un simple avatar photo.
        self.assertEqual(body["type"], heygen.AVATAR_TYPE_DIGITAL_TWIN)
        self.assertEqual(body["file"], {"type": "url", "url": "https://media.zernio.com/train.mp4"})
        self.assertEqual(avatar["look_id"], "look_dt1")
        self.assertEqual(avatar["group_id"], "group_dt1")

    def test_name_defaults_and_is_truncated(self):
        with patch.object(heygen, "_request", return_value={"id": "look_1"}) as req:
            heygen.create_digital_twin_avatar("", "https://media.zernio.com/train.mp4")
        self.assertEqual(req.call_args.kwargs["body"]["name"], "Avatar")

    def test_invalid_video_source_rejected_before_network(self):
        with patch.object(heygen, "_request") as req:
            with self.assertRaises(heygen.HeygenError):
                heygen.create_digital_twin_avatar("Nom", "http://not-https.example.com/x.mp4")
            req.assert_not_called()


class RequestAvatarConsentTest(unittest.TestCase):
    def test_posts_to_group_consent_endpoint_and_normalizes_response(self):
        captured: dict = {}

        def fake_request(method, path, **kwargs):
            captured["method"] = method
            captured["path"] = path
            return {"consent_url": "https://app.heygen.com/consent/abc", "expires_at": "2026-08-15T12:00:00Z"}

        with patch.object(heygen, "_request", side_effect=fake_request):
            consent = heygen.request_avatar_consent("group_dt1")

        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["path"], "/v3/avatars/group_dt1/consent")
        self.assertEqual(consent["consent_url"], "https://app.heygen.com/consent/abc")
        self.assertEqual(consent["expires_at"], "2026-08-15T12:00:00Z")

    def test_tolerates_alternate_field_names(self):
        with patch.object(heygen, "_request", return_value={"url": "https://app.heygen.com/c/1", "expire_at": "later"}):
            consent = heygen.request_avatar_consent("group_dt1")
        self.assertEqual(consent["consent_url"], "https://app.heygen.com/c/1")
        self.assertEqual(consent["expires_at"], "later")

    def test_missing_group_id_rejected_before_network(self):
        with patch.object(heygen, "_request") as req:
            with self.assertRaises(heygen.HeygenError):
                heygen.request_avatar_consent("")
            req.assert_not_called()

    def test_missing_consent_url_in_response_raises(self):
        with patch.object(heygen, "_request", return_value={"expires_at": "later"}):
            with self.assertRaises(heygen.HeygenError):
                heygen.request_avatar_consent("group_dt1")

    def test_re_requesting_yields_a_fresh_link(self):
        # Relance de consentement (lien expiré) : chaque appel doit repartir
        # sur l'API et renvoyer le lien qu'elle donne à ce moment-là, pas un
        # état mis en cache côté client.
        responses = [
            {"consent_url": "https://app.heygen.com/consent/first", "expires_at": "t1"},
            {"consent_url": "https://app.heygen.com/consent/second", "expires_at": "t2"},
        ]
        with patch.object(heygen, "_request", side_effect=responses):
            first = heygen.request_avatar_consent("group_dt1")
            second = heygen.request_avatar_consent("group_dt1")
        self.assertNotEqual(first["consent_url"], second["consent_url"])
        self.assertEqual(second["consent_url"], "https://app.heygen.com/consent/second")


class GetAvatarConsentStatusTest(unittest.TestCase):
    def test_given_status_normalized(self):
        for raw in ("given", "granted", "APPROVED", "completed", "confirmed", "success"):
            with patch.object(heygen, "_request", return_value={"status": raw}):
                self.assertEqual(heygen.get_avatar_consent_status("g1")["status"], "given", raw)

    def test_expired_status_normalized(self):
        for raw in ("expired", "TIMEOUT", "timed_out"):
            with patch.object(heygen, "_request", return_value={"status": raw}):
                self.assertEqual(heygen.get_avatar_consent_status("g1")["status"], "expired", raw)

    def test_unknown_status_falls_back_to_pending(self):
        # Fail-safe : mieux vaut re-poller qu'affirmer à tort un consentement
        # acquis ou expiré sur un schéma de réponse inattendu.
        with patch.object(heygen, "_request", return_value={"status": "waiting_for_review"}):
            self.assertEqual(heygen.get_avatar_consent_status("g1")["status"], "pending")
        with patch.object(heygen, "_request", return_value={}):
            self.assertEqual(heygen.get_avatar_consent_status("g1")["status"], "pending")

    def test_missing_group_id_rejected_before_network(self):
        with patch.object(heygen, "_request") as req:
            with self.assertRaises(heygen.HeygenError):
                heygen.get_avatar_consent_status(None)
            req.assert_not_called()


class IsConsentExpiredTest(unittest.TestCase):
    def test_past_deadline_is_expired(self):
        past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat()
        self.assertTrue(heygen.is_consent_expired(past))

    def test_future_deadline_is_not_expired(self):
        future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).isoformat()
        self.assertFalse(heygen.is_consent_expired(future))

    def test_z_suffix_is_handled(self):
        past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        self.assertTrue(heygen.is_consent_expired(past))

    def test_missing_or_malformed_value_is_not_expired(self):
        # Fail open sur l'AFFICHAGE seulement (jamais un accès) : mieux vaut ne
        # pas afficher « expiré » à tort que de bloquer le client sur un bug
        # de format côté HeyGen.
        self.assertFalse(heygen.is_consent_expired(None))
        self.assertFalse(heygen.is_consent_expired(""))
        self.assertFalse(heygen.is_consent_expired("pas-une-date"))


class PhotoAvatarNotRegressedTest(unittest.TestCase):
    """Le mode photo doit continuer à envoyer `type: "photo"` sans changement,
    et l'endpoint reste totalement indépendant de la nouvelle logique digital
    twin (aucun appel de consentement pour une photo)."""

    def test_photo_body_still_carries_photo_type(self):
        with patch.object(heygen, "_request", return_value={"id": "look_1"}) as req:
            heygen.create_photo_avatar("Nom", "https://media.zernio.com/photo.jpg")
        self.assertEqual(req.call_args.kwargs["body"]["type"], heygen.AVATAR_TYPE_PHOTO)
        self.assertEqual(heygen.AVATAR_TYPE_PHOTO, "photo")

    def test_avatar_type_constants_are_distinct(self):
        self.assertNotEqual(heygen.AVATAR_TYPE_PHOTO, heygen.AVATAR_TYPE_DIGITAL_TWIN)
        self.assertEqual(heygen.AVATAR_TYPE_DIGITAL_TWIN, "digital_twin")


class SetHeygenAvatarDbTest(unittest.TestCase):
    """`db.set_heygen_avatar` porte désormais `avatar_type` (0066) et efface
    le consentement en attente à la suppression — un lien/expiration orphelin
    resterait sinon affiché pour un avatar qui n'existe plus après recréation."""

    @patch("src.db.client_for_token")
    @patch("src.db.get_user", return_value={"id": "u1"})
    def test_creating_digital_twin_persists_avatar_type(self, _user, client_for):
        from src import db as dbmod

        fake = MagicMock()
        client_for.return_value = fake
        fake.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "row1"}])

        dbmod.set_heygen_avatar(
            "tok", "look_dt1", group_id="group_dt1", status="pending_consent",
            preview_url=None, avatar_type="digital_twin",
        )
        payload = fake.table.return_value.upsert.call_args[0][0]
        self.assertEqual(payload["heygen_avatar_type"], "digital_twin")
        self.assertEqual(payload["heygen_avatar_status"], "pending_consent")

    @patch("src.db.client_for_token")
    @patch("src.db.get_user", return_value={"id": "u1"})
    def test_photo_creation_persists_photo_type(self, _user, client_for):
        from src import db as dbmod

        fake = MagicMock()
        client_for.return_value = fake
        fake.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "row1"}])

        dbmod.set_heygen_avatar("tok", "look_1", avatar_type="photo")
        payload = fake.table.return_value.upsert.call_args[0][0]
        self.assertEqual(payload["heygen_avatar_type"], "photo")

    @patch("src.db.client_for_token")
    @patch("src.db.get_user", return_value={"id": "u1"})
    def test_deleting_avatar_clears_pending_consent_fields(self, _user, client_for):
        from src import db as dbmod

        fake = MagicMock()
        client_for.return_value = fake
        fake.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "row1"}])

        dbmod.set_heygen_avatar("tok", None)
        payload = fake.table.return_value.upsert.call_args[0][0]
        self.assertIsNone(payload["heygen_consent_url"])
        self.assertIsNone(payload["heygen_consent_expires_at"])
        self.assertIsNone(payload["heygen_avatar_type"])


class SetHeygenConsentDbTest(unittest.TestCase):
    @patch("src.db.client_for_token")
    @patch("src.db.get_user", return_value={"id": "u1"})
    def test_persists_consent_url_and_expiry(self, _user, client_for):
        from src import db as dbmod

        fake = MagicMock()
        client_for.return_value = fake
        fake.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])

        dbmod.set_heygen_consent("tok", "https://app.heygen.com/consent/1", "2026-08-15T12:00:00Z")
        payload = fake.table.return_value.update.call_args[0][0]
        self.assertEqual(payload["heygen_consent_url"], "https://app.heygen.com/consent/1")
        self.assertEqual(payload["heygen_consent_expires_at"], "2026-08-15T12:00:00Z")

    @patch("src.db.client_for_token")
    @patch("src.db.get_user", return_value={"id": "u1"})
    def test_can_clear_consent(self, _user, client_for):
        from src import db as dbmod

        fake = MagicMock()
        client_for.return_value = fake
        fake.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}])

        dbmod.set_heygen_consent("tok", None, None)
        payload = fake.table.return_value.update.call_args[0][0]
        self.assertIsNone(payload["heygen_consent_url"])
        self.assertIsNone(payload["heygen_consent_expires_at"])


class SetHeygenAvatarUserMissingTest(unittest.TestCase):
    """Best-effort : un token qui ne résout aucun user ne doit jamais lever."""

    @patch("src.db.get_user", return_value=None)
    def test_returns_none_when_user_unresolved(self, _user):
        from src import db as dbmod

        self.assertIsNone(dbmod.set_heygen_avatar("bad-token", "look_1"))

    @patch("src.db.get_user", return_value=None)
    def test_consent_setter_is_a_noop_when_user_unresolved(self, _user):
        from src import db as dbmod

        dbmod.set_heygen_consent("bad-token", "https://x", "later")


if __name__ == "__main__":
    unittest.main()
