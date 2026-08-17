"""Compteur d'ouverture du tunnel `/onboarding` (alias `/founders`).

Backlog Notion : « Compteur : pages vues du tunnel /onboarding vs e-mails
laissés ». Ce que ces tests verrouillent :

- `POST /onboarding/page-view` journalise une ligne avec le bon discriminant
  (`input_kind='page_view'`) dans `onboarding_preview_events` — la table
  existante (migration 0055), pas une nouvelle table ;
- l'endpoint ne renvoie JAMAIS d'erreur au visiteur anonyme, même si l'écriture
  échoue (best-effort, à deux niveaux de protection : `db.py` avale déjà ses
  erreurs, l'endpoint s'en protège une seconde fois) ;
- le rate-limit de ce compteur est un compteur DÉDIÉ, pas partagé avec
  `_onboarding_draft_hits`/`_audit_lead_hits` (une ouverture de page est
  gratuite et peut légitimement se répéter plus souvent qu'une analyse ou un
  lead) ;
- au-delà du plafond, l'appel répond quand même `{"ok": True}` (pas de 429
  visible pour un simple bruit de compteur) et n'écrit rien de plus.

On appelle la fonction d'endpoint directement (pas de TestClient : la suite du
repo est stdlib + deps du projet, on n'y ajoute pas de dépendance de test) —
même patron que `tests/test_founders_lead.py`.
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

    def __init__(self, ip: str = "203.0.113.9"):
        self.headers = _FakeHeaders({"x-forwarded-for": ip})
        self.client = None


class OnboardingPageViewEndpointTest(unittest.TestCase):
    def setUp(self):
        # État module : on vide le compteur dédié entre chaque test, et on
        # vérifie qu'on ne touche jamais aux compteurs des autres routes.
        api._onboarding_page_view_hits.clear()

    def test_valid_call_logs_with_page_view_discriminant(self):
        with patch.object(api.db, "log_onboarding_page_view_event") as log:
            out = api.onboarding_page_view(_FakeRequest())
        self.assertTrue(out.get("ok"))
        log.assert_called_once()
        # ip_hash passé explicitement — vérifie l'appel, pas l'implémentation
        # interne de `_client_ip_hash` (déjà couverte ailleurs).
        self.assertIn("ip_hash", log.call_args.kwargs)

    def test_db_failure_never_raises_to_the_visitor(self):
        with patch.object(api.db, "log_onboarding_page_view_event", side_effect=RuntimeError("boom")):
            out = api.onboarding_page_view(_FakeRequest())
        self.assertTrue(out.get("ok"))

    def test_rate_limit_counter_is_dedicated_not_shared(self):
        api._audit_lead_hits.clear()
        api._onboarding_draft_hits.clear()
        with patch.object(api.db, "log_onboarding_page_view_event"):
            api.onboarding_page_view(_FakeRequest(ip="203.0.113.9"))
        self.assertIn("203.0.113.9", api._onboarding_page_view_hits)
        # Aucun effet de bord sur les compteurs des autres routes publiques.
        self.assertNotIn("203.0.113.9", api._audit_lead_hits)
        self.assertNotIn("203.0.113.9", api._onboarding_draft_hits)

    def test_beyond_rate_limit_still_answers_ok_without_extra_logging(self):
        ip = "203.0.113.10"
        with patch.object(api.db, "log_onboarding_page_view_event") as log:
            for _ in range(api._ONBOARDING_PAGE_VIEW_MAX):
                out = api.onboarding_page_view(_FakeRequest(ip=ip))
                self.assertTrue(out.get("ok"))
            calls_before_overflow = log.call_count
            # Le plafond est atteint : l'appel suivant ne doit ni lever, ni
            # écrire une ligne de plus — juste répondre OK en silence.
            out = api.onboarding_page_view(_FakeRequest(ip=ip))
        self.assertTrue(out.get("ok"))
        self.assertEqual(calls_before_overflow, api._ONBOARDING_PAGE_VIEW_MAX)
        self.assertEqual(log.call_count, api._ONBOARDING_PAGE_VIEW_MAX)


class LogOnboardingPageViewEventTest(unittest.TestCase):
    """Fonction `db.log_onboarding_page_view_event` — insertion réelle mockée."""

    def test_noop_when_supabase_not_configured(self):
        with patch.object(db, "supabase_enabled", return_value=False), \
             patch.object(db, "admin_enabled", return_value=True), \
             patch.object(db, "admin_client") as client:
            db.log_onboarding_page_view_event(ip_hash="abc123")
        client.assert_not_called()

    def test_noop_when_no_service_role(self):
        with patch.object(db, "supabase_enabled", return_value=True), \
             patch.object(db, "admin_enabled", return_value=False), \
             patch.object(db, "admin_client") as client:
            db.log_onboarding_page_view_event(ip_hash="abc123")
        client.assert_not_called()

    def test_inserts_with_page_view_discriminant_and_neutral_fields(self):
        fake_client = _FakeSupabaseClient()
        with patch.object(db, "supabase_enabled", return_value=True), \
             patch.object(db, "admin_enabled", return_value=True), \
             patch.object(db, "admin_client", return_value=fake_client):
            db.log_onboarding_page_view_event(ip_hash="abc123")
        row = fake_client.inserted_row
        self.assertEqual(row["input_kind"], "page_view")
        self.assertIsNone(row["linkedin_url"])
        self.assertIsNone(row["website_url"])
        self.assertFalse(row["used_apify"])
        self.assertFalse(row["preview_ok"])
        self.assertEqual(row["ip_hash"], "abc123")

    def test_failure_is_swallowed(self):
        with patch.object(db, "supabase_enabled", return_value=True), \
             patch.object(db, "admin_enabled", return_value=True), \
             patch.object(db, "admin_client", side_effect=RuntimeError("boom")):
            # Ne doit lever aucune exception.
            db.log_onboarding_page_view_event(ip_hash="abc123")


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


if __name__ == "__main__":
    unittest.main()
