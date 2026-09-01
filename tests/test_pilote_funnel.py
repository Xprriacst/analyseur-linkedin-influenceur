"""Funnel de la landing `/pilote` — compteur pages vues vs comptes créés.

Backlog Notion : « Funnel /pilote — compteur pages vues vs comptes créés »
(décision Alex 2026-09-01). Ce que ces tests verrouillent :

- `POST /pilote/page-view` journalise une ligne avec un discriminant PROPRE
  (`input_kind='pilote_page_view'`) dans `onboarding_preview_events` — la table
  existante (migration 0055), pas une nouvelle table ;
- ce discriminant NE COLLISIONNE PAS avec celui de `/onboarding` : les deux
  landings partagent la table, mélanger leurs vues rendrait les deux taux de
  conversion faux d'un coup, et faux en silence ;
- l'endpoint ne renvoie JAMAIS d'erreur au visiteur anonyme, même si l'écriture
  échoue (best-effort à deux niveaux, comme `/onboarding/page-view`) ;
- son rate-limit est un compteur DÉDIÉ : ni partagé avec `/onboarding`, ni avec
  les routes payantes — sinon le bruit d'un tunnel effacerait les vues de
  l'autre, exactement ce que le compteur doit rendre visible ;
- au-delà du plafond, l'appel répond quand même `{"ok": True}` sans écrire.

On appelle la fonction d'endpoint directement (pas de TestClient : la suite du
repo est stdlib + deps du projet) — même patron que
`tests/test_onboarding_page_view.py`.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api  # noqa: E402
from src import db  # noqa: E402


class _FakeHeaders(dict):
    def get(self, key, default=""):  # Starlette Headers est case-insensitive.
        return super().get(key.lower(), default)


class _FakeRequest:
    """Le strict nécessaire de `Request` pour l'endpoint : headers + client."""

    def __init__(self, ip: str = "198.51.100.7"):
        self.headers = _FakeHeaders({"x-forwarded-for": ip})
        self.client = None


class _FakeSupabaseClient:
    """Le strict nécessaire de `Client.table(...).insert(...).execute()`."""

    def __init__(self):
        self.inserted_row = None

    def table(self, name):
        assert name == "onboarding_preview_events"
        return self

    def insert(self, row):
        self.inserted_row = row
        return self

    def execute(self):
        return None


class PilotePageViewEndpointTest(unittest.TestCase):
    def setUp(self):
        api._pilote_page_view_hits.clear()

    def test_valid_call_logs_a_pilote_view(self):
        with patch.object(api.db, "log_pilote_page_view_event") as log:
            out = api.pilote_page_view(_FakeRequest())
        self.assertTrue(out.get("ok"))
        log.assert_called_once()
        self.assertIn("ip_hash", log.call_args.kwargs)

    def test_db_failure_never_raises_to_the_visitor(self):
        with patch.object(api.db, "log_pilote_page_view_event", side_effect=RuntimeError("boom")):
            out = api.pilote_page_view(_FakeRequest())
        self.assertTrue(out.get("ok"))

    def test_rate_limit_counter_is_dedicated_not_shared(self):
        api._onboarding_page_view_hits.clear()
        api._audit_lead_hits.clear()
        api._onboarding_draft_hits.clear()
        with patch.object(api.db, "log_pilote_page_view_event"):
            api.pilote_page_view(_FakeRequest(ip="198.51.100.7"))
        self.assertIn("198.51.100.7", api._pilote_page_view_hits)
        # Une vue de /pilote ne consomme JAMAIS le quota d'une autre route.
        self.assertNotIn("198.51.100.7", api._onboarding_page_view_hits)
        self.assertNotIn("198.51.100.7", api._audit_lead_hits)
        self.assertNotIn("198.51.100.7", api._onboarding_draft_hits)

    def test_beyond_rate_limit_still_answers_ok_without_extra_logging(self):
        ip = "198.51.100.8"
        with patch.object(api.db, "log_pilote_page_view_event") as log:
            for _ in range(api._PILOTE_PAGE_VIEW_MAX):
                self.assertTrue(api.pilote_page_view(_FakeRequest(ip=ip)).get("ok"))
            calls_before_overflow = log.call_count
            out = api.pilote_page_view(_FakeRequest(ip=ip))
        self.assertTrue(out.get("ok"))
        self.assertEqual(calls_before_overflow, api._PILOTE_PAGE_VIEW_MAX)
        self.assertEqual(log.call_count, api._PILOTE_PAGE_VIEW_MAX)


class LogPilotePageViewEventTest(unittest.TestCase):
    def _insert(self):
        fake_client = _FakeSupabaseClient()
        with patch.object(db, "supabase_enabled", return_value=True), \
             patch.object(db, "admin_enabled", return_value=True), \
             patch.object(db, "admin_client", return_value=fake_client):
            db.log_pilote_page_view_event(ip_hash="cafe1234")
        return fake_client.inserted_row

    def test_inserts_with_pilote_discriminant_and_neutral_fields(self):
        row = self._insert()
        self.assertEqual(row["input_kind"], "pilote_page_view")
        self.assertIsNone(row["linkedin_url"])
        self.assertIsNone(row["website_url"])
        self.assertFalse(row["used_apify"])
        self.assertFalse(row["preview_ok"])
        self.assertEqual(row["ip_hash"], "cafe1234")

    def test_pilote_and_onboarding_views_never_share_a_discriminant(self):
        """Le verrou central : deux landings, une table, deux comptages distincts.

        Si les deux valeurs devenaient égales (copier-coller malheureux), les
        requêtes de conversion des DEUX tunnels renverraient un chiffre gonflé
        sans qu'aucune erreur ne se produise nulle part.
        """
        self.assertNotEqual(db.PILOTE_PAGE_VIEW_KIND, db.ONBOARDING_PAGE_VIEW_KIND)
        pilote_row = self._insert()
        onboarding_client = _FakeSupabaseClient()
        with patch.object(db, "supabase_enabled", return_value=True), \
             patch.object(db, "admin_enabled", return_value=True), \
             patch.object(db, "admin_client", return_value=onboarding_client):
            db.log_onboarding_page_view_event(ip_hash="cafe1234")
        self.assertNotEqual(pilote_row["input_kind"], onboarding_client.inserted_row["input_kind"])

    def test_onboarding_discriminant_is_not_renamed(self):
        """`page_view` est historique : des lignes le portent déjà en prod.

        Le renommer (par symétrie avec `pilote_page_view`, par exemple) ferait
        disparaître d'un coup toutes les vues `/onboarding` déjà comptées.
        """
        self.assertEqual(db.ONBOARDING_PAGE_VIEW_KIND, "page_view")

    def test_noop_when_supabase_not_configured(self):
        with patch.object(db, "supabase_enabled", return_value=False), \
             patch.object(db, "admin_enabled", return_value=True), \
             patch.object(db, "admin_client") as client:
            db.log_pilote_page_view_event(ip_hash="cafe1234")
        client.assert_not_called()

    def test_noop_when_no_service_role(self):
        with patch.object(db, "supabase_enabled", return_value=True), \
             patch.object(db, "admin_enabled", return_value=False), \
             patch.object(db, "admin_client") as client:
            db.log_pilote_page_view_event(ip_hash="cafe1234")
        client.assert_not_called()

    def test_failure_is_swallowed(self):
        with patch.object(db, "supabase_enabled", return_value=True), \
             patch.object(db, "admin_enabled", return_value=True), \
             patch.object(db, "admin_client", side_effect=RuntimeError("boom")):
            db.log_pilote_page_view_event(ip_hash="cafe1234")


if __name__ == "__main__":
    unittest.main()
