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


if __name__ == "__main__":
    unittest.main()
