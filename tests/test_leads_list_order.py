"""Tests unitaires — `db.list_leads` / `db.count_leads` (incident prod 2026-09-04).

Ce que ces tests verrouillent, et pourquoi c'est un test et pas une relecture :

La liste Prospection est PLAFONNÉE côté serveur. Tant que le tri par score se
faisait après coup en Python, la base retenait N lignes sur un critère
(`signal_count desc`) et l'écran les classait sur un autre (le score) : les
meilleurs leads du compte pouvaient tomber hors fenêtre **sans lever la moindre
erreur**, et la liste avait l'air complète. Constaté en prod sur un compte à
1 133 leads : 12 des 50 meilleurs profils d'un import n'étaient pas affichés, et
le client en a conclu que des invitations de son autopilote n'existaient pas.

Un refacto qui remettrait le tri du score après la troncature repasserait tous
les tests fonctionnels de l'écran. D'où ces assertions sur l'ORDRE ENVOYÉ À LA
BASE, pas sur les lignes rendues.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src import db


class _FakeQuery:
    def __init__(self, rows: list[dict], captured: dict, count: int | None = None):
        self._rows = rows
        self._captured = captured
        self._count = count

    def select(self, cols, **kwargs):
        self._captured["select"] = cols
        self._captured["select_kwargs"] = kwargs
        return self

    def order(self, key, desc=False, nullsfirst=None):
        self._captured.setdefault("order", []).append((key, desc, nullsfirst))
        return self

    def limit(self, n):
        self._captured["limit"] = n
        return self

    def execute(self):
        return type("Resp", (), {"data": self._rows, "count": self._count})()


class _FakeClient:
    def __init__(self, rows: list[dict], count: int | None = None):
        self._rows = rows
        self._count = count
        self.captured: dict = {}

    def table(self, name):
        assert name == "leads"
        return _FakeQuery(self._rows, self.captured, self._count)


def _lead(**kw):
    base = {"id": "x", "score": None, "signal_count": 0, "created_at": "2026-01-01", "contact_status": "to_contact"}
    base.update(kw)
    return base


class ListLeadsOrderTest(unittest.TestCase):
    """La fenêtre d'affichage doit être décidée en base, sur le critère d'affichage."""

    def _run(self, rows):
        client = _FakeClient(rows)
        with patch.object(db, "supabase_enabled", return_value=True), \
             patch.object(db, "client_for_token", return_value=client):
            out = db.list_leads("tok")
        return out, client.captured

    def test_score_is_the_first_order_key_sent_to_the_database(self):
        """Le score doit trancher AVANT la troncature, sinon les meilleurs leads
        peuvent ne jamais sortir de la base."""
        _, captured = self._run([])
        self.assertEqual(captured["order"][0][0], "score")
        self.assertTrue(captured["order"][0][1], "le score doit être décroissant")

    def test_unscored_leads_are_ordered_last_in_the_database(self):
        """`order by score desc` place les NULL EN TÊTE en SQL. Sans `nullsfirst=False`,
        la liste s'ouvrirait sur les leads dont on ne sait justement rien."""
        _, captured = self._run([])
        self.assertIs(captured["order"][0][2], False)

    def test_signal_count_and_recency_only_break_ties(self):
        """Ils restent des départages — mais après le score, plus avant."""
        _, captured = self._run([])
        keys = [k for k, _, _ in captured["order"]]
        self.assertEqual(keys, ["score", "signal_count", "created_at"])

    def test_python_sort_stays_consistent_with_the_database_order(self):
        """Le raffinement Python ne doit pas contredire le `order by` : s'il réordonnait
        sur un autre critère, on retomberait exactement dans le défaut corrigé."""
        rows = [
            _lead(id="haut", score=80),
            _lead(id="bas", score=10),
            _lead(id="non_note", score=None),
        ]
        out, _ = self._run(rows)
        self.assertEqual([r["id"] for r in out], ["haut", "bas", "non_note"])

    def test_skipped_leads_go_last_but_are_never_hidden(self):
        """ALE-243 : « ne pas contacter » relègue, ne masque pas."""
        rows = [
            _lead(id="ecarte", score=95, contact_status="skip"),
            _lead(id="normal", score=40),
        ]
        out, _ = self._run(rows)
        self.assertEqual([r["id"] for r in out], ["normal", "ecarte"])

    def test_noop_without_supabase(self):
        with patch.object(db, "supabase_enabled", return_value=False), \
             patch.object(db, "client_for_token") as client:
            self.assertEqual(db.list_leads("tok"), [])
        client.assert_not_called()


class CountLeadsTest(unittest.TestCase):
    """Le total sert à ANNONCER la troncature — jamais à faire tomber la liste."""

    def test_returns_exact_count(self):
        client = _FakeClient([{"id": "x"}], count=1133)
        with patch.object(db, "supabase_enabled", return_value=True), \
             patch.object(db, "client_for_token", return_value=client):
            self.assertEqual(db.count_leads("tok"), 1133)
        self.assertEqual(client.captured["select_kwargs"].get("count"), "exact")

    def test_failure_never_raises(self):
        """Un compteur d'affichage ne doit jamais casser l'écran qu'il décore :
        le client doit voir ses leads même si le total est illisible."""
        def _boom(_token):
            raise RuntimeError("supabase indisponible")

        with patch.object(db, "supabase_enabled", return_value=True), \
             patch.object(db, "client_for_token", side_effect=_boom):
            self.assertEqual(db.count_leads("tok"), 0)

    def test_noop_without_supabase(self):
        with patch.object(db, "supabase_enabled", return_value=False):
            self.assertEqual(db.count_leads("tok"), 0)


if __name__ == "__main__":
    unittest.main()
