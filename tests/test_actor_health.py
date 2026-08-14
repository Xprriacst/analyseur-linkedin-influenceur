"""Tests unitaires pour src/actor_health.py (backlog « Surveiller la
fiabilité des acteurs Apify + fallback »).

Stdlib uniquement, aucune dépendance réseau/Apify — patron des autres
fichiers de `tests/` (cf. tests/test_lead_search.py, tests/test_features.py).
"""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout

from src import actor_health


class RecordCallTest(unittest.TestCase):
    def setUp(self) -> None:
        # Le module tient un ring buffer module-level : on le vide entre
        # chaque test pour ne pas polluer les assertions sur `recent_events`.
        actor_health._events.clear()

    def test_success_no_anomaly_no_log(self) -> None:
        """Un succès normal (items ramenés) ne produit AUCUNE ligne de log —
        le but est de repérer les pannes, pas de noyer les logs Render."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            actor_health.record_call(
                "harvestapi/linkedin-profile-posts",
                ok=True,
                item_count=25,
                expected_min_items=1,
                context="fetch_posts",
            )
        self.assertEqual(buf.getvalue(), "")
        events = actor_health.recent_events()
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["ok"])
        self.assertFalse(events[0]["anomaly"])
        self.assertEqual(events[0]["item_count"], 25)

    def test_hard_failure_is_logged_with_prefix(self) -> None:
        """Un échec franc (exception réseau/API) est tracé ÉCHEC avec le
        préfixe grepable [apify.health]."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            actor_health.record_call(
                "harvestapi/linkedin-profile-scraper",
                ok=False,
                error="This Actor requires full access to your account",
                context="fetch_profile",
            )
        out = buf.getvalue()
        self.assertIn(actor_health.LOG_PREFIX, out)
        self.assertIn("ÉCHEC", out)
        self.assertIn("harvestapi/linkedin-profile-scraper", out)
        self.assertIn("full access", out)
        events = actor_health.recent_events()
        self.assertFalse(events[0]["ok"])
        self.assertFalse(events[0]["anomaly"])

    def test_zero_items_unexpected_is_flagged_as_anomaly(self) -> None:
        """Incident #407 : le run réussit (ok=True) mais renvoie 0 item alors
        qu'on en attendait — doit être tracé ANOMALIE, sans jamais lever."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            actor_health.record_call(
                "harvestapi/linkedin-post-comments",
                ok=True,
                item_count=0,
                expected_min_items=1,
                context="fetch_post_commenters",
            )
        out = buf.getvalue()
        self.assertIn(actor_health.LOG_PREFIX, out)
        self.assertIn("ANOMALIE", out)
        events = actor_health.recent_events()
        self.assertTrue(events[0]["ok"])
        self.assertTrue(events[0]["anomaly"])

    def test_zero_items_expected_is_not_an_anomaly(self) -> None:
        """0 item n'est une anomalie QUE si on en attendait — un run qui
        n'attend rien de particulier (expected_min_items=0) ne doit pas
        déclencher de faux positif."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            actor_health.record_call(
                "some/actor", ok=True, item_count=0, expected_min_items=0
            )
        self.assertEqual(buf.getvalue(), "")
        events = actor_health.recent_events()
        self.assertFalse(events[0]["anomaly"])

    def test_never_raises_on_malformed_input(self) -> None:
        """Best-effort : même un appel bancal (types inattendus) ne doit
        jamais lever — le tracking ne doit jamais casser l'appelant."""
        try:
            actor_health.record_call(
                None,  # type: ignore[arg-type]
                ok="yes",  # type: ignore[arg-type]
                item_count="not-an-int",  # type: ignore[arg-type]
                expected_min_items="also-not-an-int",  # type: ignore[arg-type]
                error={"weird": "object"},  # type: ignore[arg-type]
                context=12345,  # type: ignore[arg-type]
            )
        except Exception as exc:  # noqa: BLE001
            self.fail(f"record_call a levé alors qu'il doit être best-effort : {exc}")

    def test_ring_buffer_is_bounded(self) -> None:
        """Le buffer ne grossit pas indéfiniment (mémoire process)."""
        for i in range(actor_health._MAX_EVENTS + 50):
            actor_health.record_call("actor", ok=True, item_count=1, context=str(i))
        self.assertEqual(len(actor_health.recent_events(10_000)), actor_health._MAX_EVENTS)


class SummaryTest(unittest.TestCase):
    def setUp(self) -> None:
        actor_health._events.clear()

    def test_summary_aggregates_by_actor(self) -> None:
        actor_health.record_call("actor-a", ok=True, item_count=5)
        actor_health.record_call("actor-a", ok=False, error="boom")
        actor_health.record_call("actor-b", ok=True, item_count=0, expected_min_items=1)

        summary = actor_health.summary()
        self.assertEqual(summary["window"], 3)
        self.assertEqual(summary["actors"]["actor-a"]["calls"], 2)
        self.assertEqual(summary["actors"]["actor-a"]["failures"], 1)
        self.assertEqual(summary["actors"]["actor-a"]["last_error"], "boom")
        self.assertEqual(summary["actors"]["actor-b"]["anomalies"], 1)

    def test_summary_never_raises_on_empty_state(self) -> None:
        summary = actor_health.summary()
        self.assertEqual(summary["window"], 0)
        self.assertEqual(summary["actors"], {})


class CallWithFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        actor_health._events.clear()

    def test_success_on_primary_never_calls_fallback(self) -> None:
        calls: list[str] = []

        def call_fn(actor: str) -> list[dict]:
            calls.append(actor)
            return [{"ok": True}]

        items, used = actor_health.call_with_fallback(
            "primary-actor",
            call_fn,
            fallback_actor="fallback-actor",
            expected_min_items=1,
        )
        self.assertEqual(items, [{"ok": True}])
        self.assertEqual(used, "primary-actor")
        self.assertEqual(calls, ["primary-actor"])  # pas de fallback appelé

    def test_hard_failure_on_primary_triggers_fallback(self) -> None:
        """Échec franc (exception) du primaire → repli automatique sur le
        fallback, comme le patron déjà existant pour le profil."""
        calls: list[str] = []

        def call_fn(actor: str) -> list[dict]:
            calls.append(actor)
            if actor == "primary-actor":
                raise RuntimeError("This Actor requires full access to your account")
            return [{"basic_info": {"follower_count": 42}}]

        items, used = actor_health.call_with_fallback(
            "primary-actor",
            call_fn,
            fallback_actor="fallback-actor",
            context="fetch_profile",
            expected_min_items=1,
        )
        self.assertEqual(calls, ["primary-actor", "fallback-actor"])
        self.assertEqual(used, "fallback-actor")
        self.assertEqual(items, [{"basic_info": {"follower_count": 42}}])

        events = actor_health.recent_events()
        self.assertEqual(len(events), 2)
        self.assertFalse(events[0]["ok"])  # tentative primaire tracée en échec
        self.assertEqual(events[0]["actor"], "primary-actor")
        self.assertTrue(events[1]["ok"])  # tentative de repli tracée en succès
        self.assertEqual(events[1]["actor"], "fallback-actor")

    def test_empty_result_on_primary_also_triggers_fallback(self) -> None:
        """Même sans exception : un run "réussi" mais vide bascule aussi sur
        le repli (c'est ce que fait déjà scraper.py::fetch_profile)."""
        calls: list[str] = []

        def call_fn(actor: str) -> list[dict]:
            calls.append(actor)
            return [] if actor == "primary-actor" else [{"name": "ok"}]

        items, used = actor_health.call_with_fallback(
            "primary-actor", call_fn, fallback_actor="fallback-actor"
        )
        self.assertEqual(calls, ["primary-actor", "fallback-actor"])
        self.assertEqual(used, "fallback-actor")
        self.assertEqual(items, [{"name": "ok"}])

    def test_both_fail_returns_empty_without_raising(self) -> None:
        def call_fn(actor: str) -> list[dict]:
            raise RuntimeError(f"{actor} down")

        items, used = actor_health.call_with_fallback(
            "primary-actor", call_fn, fallback_actor="fallback-actor"
        )
        self.assertEqual(items, [])
        self.assertEqual(used, "fallback-actor")
        events = actor_health.recent_events()
        self.assertEqual(len(events), 2)
        self.assertFalse(events[0]["ok"])
        self.assertFalse(events[1]["ok"])

    def test_no_fallback_actor_does_not_retry(self) -> None:
        calls: list[str] = []

        def call_fn(actor: str) -> list[dict]:
            calls.append(actor)
            return []

        items, used = actor_health.call_with_fallback("primary-actor", call_fn)
        self.assertEqual(calls, ["primary-actor"])
        self.assertEqual(items, [])
        self.assertEqual(used, "primary-actor")

    def test_fallback_same_as_primary_does_not_double_call(self) -> None:
        """Repli == acteur primaire (ex. APIFY_PROFILE_ACTOR déjà réglé sur
        l'acteur de secours) : pas de second appel inutile."""
        calls: list[str] = []

        def call_fn(actor: str) -> list[dict]:
            calls.append(actor)
            return []

        items, used = actor_health.call_with_fallback(
            "same-actor", call_fn, fallback_actor="same-actor"
        )
        self.assertEqual(calls, ["same-actor"])
        self.assertEqual(used, "same-actor")
        self.assertEqual(items, [])

    def test_tracking_never_blocks_a_call_that_would_otherwise_succeed(self) -> None:
        """Défense en profondeur : même si `record_call` lui-même se mettait à
        lever (bug interne, pas juste une entrée malformée), le résultat réel
        de `call_fn` — le vrai appel Apify — doit quand même être renvoyé.
        Un souci du module de santé ne doit JAMAIS faire échouer un appel qui
        aurait autrement réussi."""

        def broken_record_call(*args, **kwargs):  # noqa: ANN001, ANN002
            raise RuntimeError("tracking module misbehaving")

        original = actor_health.record_call
        actor_health.record_call = broken_record_call  # type: ignore[assignment]
        try:
            items, used = actor_health.call_with_fallback(
                "primary-actor", lambda a: [{"ok": True}]
            )
        finally:
            actor_health.record_call = original  # type: ignore[assignment]

        self.assertEqual(items, [{"ok": True}])
        self.assertEqual(used, "primary-actor")


if __name__ == "__main__":
    unittest.main()
