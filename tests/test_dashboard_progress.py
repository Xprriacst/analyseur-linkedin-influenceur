"""Tests unitaires pour src/dashboard_progress.py (Mon profil → Dashboard,
backlog Notion, priorité Alex 2026-08-31).

Stdlib uniquement, aucune dépendance réseau/base — patron des autres fichiers
de `tests/` (cf. tests/test_actor_health.py, tests/test_lead_search.py).
"""
from __future__ import annotations

import unittest

from src.dashboard_progress import follower_progress, reply_progress


class FollowerProgressTest(unittest.TestCase):
    def test_no_snapshot_is_unavailable_not_zero(self) -> None:
        result = follower_progress([])
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "no_own_profile_analyzed")
        # Aucun chiffre de suivi ne doit apparaître dans une réponse indisponible —
        # sinon un « 0 abonné » se ferait passer pour un vrai relevé.
        self.assertNotIn("current", result)
        self.assertNotIn("delta", result)

    def test_single_snapshot_baseline_equals_current_zero_delta(self) -> None:
        result = follower_progress([{"captured_on": "2026-08-01", "follower_count": 1200}])
        self.assertTrue(result["available"])
        self.assertEqual(result["current"], 1200)
        self.assertEqual(result["baseline"], 1200)
        self.assertEqual(result["delta"], 0)
        self.assertEqual(len(result["history"]), 1)

    def test_progression_computed_from_first_and_last(self) -> None:
        snapshots = [
            {"captured_on": "2026-07-01", "follower_count": 1000},
            {"captured_on": "2026-07-15", "follower_count": 1080},
            {"captured_on": "2026-08-01", "follower_count": 1150},
        ]
        result = follower_progress(snapshots)
        self.assertEqual(result["baseline"], 1000)
        self.assertEqual(result["baseline_at"], "2026-07-01")
        self.assertEqual(result["current"], 1150)
        self.assertEqual(result["current_at"], "2026-08-01")
        self.assertEqual(result["delta"], 150)
        self.assertEqual(len(result["history"]), 3)

    def test_negative_delta_when_followers_dropped(self) -> None:
        snapshots = [
            {"captured_on": "2026-07-01", "follower_count": 1000},
            {"captured_on": "2026-08-01", "follower_count": 950},
        ]
        result = follower_progress(snapshots)
        self.assertEqual(result["delta"], -50)

    def test_rows_missing_follower_count_are_ignored(self) -> None:
        snapshots = [
            {"captured_on": "2026-07-01", "follower_count": None},
            {"captured_on": "2026-08-01", "follower_count": 1200},
        ]
        result = follower_progress(snapshots)
        self.assertTrue(result["available"])
        self.assertEqual(result["baseline"], 1200)
        self.assertEqual(result["current"], 1200)

    def test_none_input_is_unavailable(self) -> None:
        result = follower_progress(None)  # type: ignore[arg-type]
        self.assertFalse(result["available"])


class ReplyProgressTest(unittest.TestCase):
    def test_counts_replied_among_verified_only(self) -> None:
        result = reply_progress([True, False, True, None], total_messaged=10, checked_cap=20)
        # `None` = conversation non vérifiable : exclue du décompte des vérifiées.
        self.assertEqual(result["checked"], 3)
        self.assertEqual(result["replied"], 2)
        self.assertEqual(result["total_messaged"], 10)

    def test_failed_checks_never_counted_as_no_reply(self) -> None:
        # Une panne Unipile sur TOUTES les conversations ne doit jamais dire
        # « personne n'a répondu » — elle doit dire « rien de vérifié ».
        result = reply_progress([None, None, None], total_messaged=3, checked_cap=20)
        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["replied"], 0)
        self.assertTrue(result["available"])

    def test_capped_flag_reflects_sample_vs_total(self) -> None:
        under_cap = reply_progress([True], total_messaged=5, checked_cap=20)
        self.assertFalse(under_cap["capped"])
        over_cap = reply_progress([True] * 20, total_messaged=57, checked_cap=20)
        self.assertTrue(over_cap["capped"])

    def test_empty_checks_with_no_messaged_leads(self) -> None:
        result = reply_progress([], total_messaged=0, checked_cap=20)
        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["replied"], 0)
        self.assertFalse(result["capped"])


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    """Client Supabase fluide de test : enregistre les filtres appliqués.

    Chaque méthode chaînable renvoie `self` ; `execute()` rend la réponse canned.
    `not_` est une propriété (patron `.not_.is_(...)` de supabase-py)."""

    def __init__(self, data):
        self._data = data
        self.calls: list[tuple] = []

    def table(self, name):
        self.calls.append(("table", name))
        return self

    def select(self, cols):
        self.calls.append(("select", cols))
        return self

    def eq(self, col, val):
        self.calls.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self.calls.append(("in_", col, tuple(vals)))
        return self

    def is_(self, col, val):
        self.calls.append(("is_", col, val))
        return self

    def order(self, col, desc=False):
        self.calls.append(("order", col, desc))
        return self

    def limit(self, n):
        self.calls.append(("limit", n))
        return self

    def upsert(self, row, on_conflict=None):
        self.calls.append(("upsert", tuple(sorted(row.items())), on_conflict))
        return self

    @property
    def not_(self):
        return self

    def execute(self):
        return _FakeResponse(self._data)


class _DbPatch:
    """Neutralise les accès réseau/base de `src.db` le temps d'un test."""

    def __init__(self, testcase, *, profile, rows):
        from src import db as db_module

        self.db = db_module
        self.fake = _FakeQuery(rows)
        self._originals = {
            "get_editorial_profile": db_module.get_editorial_profile,
            "get_user": db_module.get_user,
            "client_for_token": db_module.client_for_token,
            "supabase_enabled": db_module.supabase_enabled,
        }
        db_module.get_editorial_profile = lambda _t: profile
        db_module.get_user = lambda _t: {"id": "user-1"}
        db_module.client_for_token = lambda _t: self.fake
        db_module.supabase_enabled = lambda: True
        testcase.addCleanup(self.restore)

    def restore(self):
        for name, fn in self._originals.items():
            setattr(self.db, name, fn)


class OwnFollowerCountTest(unittest.TestCase):
    """`db.own_follower_count` — la source du chiffre d'abonnés du dashboard."""

    def test_zero_is_unknown_not_zero_followers(self) -> None:
        # Régression : quand le scrape de profil échoue (permissions de l'acteur
        # Apify, plafond mensuel), `_influencer_row` écrit `follower_count = 0`
        # SANS erreur. Le prendre au mot poserait une baseline à 0, puis un bond de
        # « +1 200 abonnés » à la première analyse réussie — un chiffre faux sur son
        # propre compte, affiché comme un fait.
        from src import db as db_module

        _DbPatch(
            self,
            profile={"linkedin_url": "https://www.linkedin.com/in/alex/"},
            rows=[{"follower_count": 0}],
        )
        self.assertIsNone(db_module.own_follower_count("tok"))

    def test_real_count_is_returned(self) -> None:
        from src import db as db_module

        _DbPatch(
            self,
            profile={"linkedin_url": "https://www.linkedin.com/in/alex/"},
            rows=[{"follower_count": 1200}],
        )
        self.assertEqual(db_module.own_follower_count("tok"), 1200)

    def test_query_is_scoped_to_linkedin_platform(self) -> None:
        # Le même handle peut exister en ligne Instagram (analyse IG) : sans ce
        # filtre, le nombre d'abonnés Instagram pourrait s'afficher comme LinkedIn.
        from src import db as db_module

        patch = _DbPatch(
            self,
            profile={"linkedin_url": "https://www.linkedin.com/in/alex/"},
            rows=[{"follower_count": 1200}],
        )
        db_module.own_follower_count("tok")
        self.assertIn(("eq", "platform", "linkedin"), patch.fake.calls)

    def test_no_linkedin_url_means_unavailable(self) -> None:
        from src import db as db_module

        _DbPatch(self, profile={"linkedin_url": ""}, rows=[])
        self.assertIsNone(db_module.own_follower_count("tok"))

    def test_profile_never_analyzed_means_unavailable(self) -> None:
        from src import db as db_module

        _DbPatch(
            self,
            profile={"linkedin_url": "https://www.linkedin.com/in/alex/"},
            rows=[],
        )
        self.assertIsNone(db_module.own_follower_count("tok"))


class RecordFollowerSnapshotTest(unittest.TestCase):
    def test_upsert_is_idempotent_per_day(self) -> None:
        # Ouvrir le dashboard trois fois dans la journée ne doit créer qu'UNE ligne :
        # c'est `on_conflict="user_id,captured_on"` (migration 0071) qui le garantit,
        # pas un `select` préalable. Sans lui, l'historique se remplirait de doublons
        # et la « progression » deviendrait illisible.
        import datetime as _dt

        from src import db as db_module

        patch = _DbPatch(self, profile={}, rows=[])
        db_module.record_follower_snapshot("tok", 1200, source="dashboard")
        upserts = [c for c in patch.fake.calls if c[0] == "upsert"]
        self.assertEqual(len(upserts), 1)
        self.assertEqual(upserts[0][2], "user_id,captured_on")
        row = dict(upserts[0][1])
        self.assertEqual(row["captured_on"], _dt.date.today().isoformat())
        self.assertEqual(row["follower_count"], 1200)
        self.assertEqual(row["source"], "dashboard")

    def test_write_failure_never_raises(self) -> None:
        # Best-effort : un relevé de suivi ne doit jamais faire tomber le dashboard
        # (ni, via `save_analysis`, une analyse déjà payée en scrape et en modèle).
        from src import db as db_module

        patch = _DbPatch(self, profile={}, rows=[])

        def boom(*_a, **_k):
            raise RuntimeError("table absente")

        patch.fake.upsert = boom
        db_module.record_follower_snapshot("tok", 1200)  # ne doit pas lever


class OutreachLeadFunnelTest(unittest.TestCase):
    def test_counts_without_double_counting(self) -> None:
        # `outreach_status` avance dans un seul sens : un lead « messaged » a été
        # invité ET connecté. Le total « invité » est donc le nombre de lignes, pas
        # la somme des trois statuts (qui compterait le même lead trois fois).
        from src import db as db_module

        _DbPatch(
            self,
            profile={},
            rows=[
                {"outreach_status": "invite_sent"},
                {"outreach_status": "invite_sent"},
                {"outreach_status": "connected"},
                {"outreach_status": "messaged"},
                {"outreach_status": "messaged"},
            ],
        )
        funnel = db_module.outreach_lead_funnel("tok")
        self.assertEqual(funnel, {"invited": 5, "connected": 3, "messaged": 2})

    def test_empty_funnel_is_zeros_not_error(self) -> None:
        from src import db as db_module

        _DbPatch(self, profile={}, rows=[])
        self.assertEqual(
            db_module.outreach_lead_funnel("tok"),
            {"invited": 0, "connected": 0, "messaged": 0},
        )


class ApiModuleAliasTest(unittest.TestCase):
    def test_dashboard_progress_module_is_imported_under_an_alias(self) -> None:
        """`api.py` définit DÉJÀ `def dashboard_progress` (endpoint
        `GET /dashboard/progress`). Un `from src import dashboard_progress` y serait
        silencieusement écrasé par ce `def` au chargement, et chaque appel
        `dashboard_progress.follower_progress(...)` lèverait un AttributeError EN
        PRODUCTION — invisible pour py_compile comme pour le build front. Ce test
        verrouille l'alias ; il tombe si quelqu'un « nettoie » l'import."""
        import pathlib

        source = pathlib.Path(__file__).resolve().parents[1] / "api.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("from src import dashboard_progress as dashboard_fmt", text)
        self.assertNotIn("from src import dashboard_progress\n", text)
        # Le nom nu ne doit plus servir à appeler le module de mise en forme.
        self.assertNotIn("dashboard_progress.follower_progress(", text)
        self.assertNotIn("dashboard_progress.reply_progress(", text)


if __name__ == "__main__":
    unittest.main()
