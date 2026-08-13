"""Opt-in e-mail de la landing /founders (`POST /onboarding/founders-lead`).

Ce que ces tests verrouillent :
- un e-mail invalide est refusé net (422) — la validation vit au serveur, pas
  seulement dans le navigateur ;
- un opt-in valide est bien ÉCRIT, avec le statut `founders_optin` et jamais
  `pending` : `pending` est le statut des demandes d'audit, un opt-in qui le
  porterait ressemblerait à une demande d'audit ;
- une re-soumission ne crée pas de doublon ;
- un échec d'écriture ne bloque JAMAIS le visiteur (best-effort assumé).

On appelle la fonction d'endpoint directement (pas de TestClient : la suite du
repo est stdlib + deps du projet, on n'y ajoute pas de dépendance de test).
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException  # noqa: E402

import api  # noqa: E402


class _FakeHeaders(dict):
    def get(self, key, default=""):  # Starlette Headers est case-insensitive.
        return super().get(key.lower(), default)


class _FakeRequest:
    """Le strict nécessaire de `Request` pour l'endpoint : headers + client."""

    def __init__(self, ip: str = "203.0.113.7"):
        self.headers = _FakeHeaders({"x-forwarded-for": ip})
        self.client = None


class FoundersLeadTest(unittest.TestCase):
    def setUp(self):
        # Le rate-limit par IP est partagé avec le formulaire d'audit et persiste
        # entre les tests (état module) : on le vide pour isoler chaque cas.
        api._audit_lead_hits.clear()

    def _call(self, email, source=None):
        payload = api.FoundersLeadRequest(email=email, source=source)
        return api.onboarding_founders_lead(payload, _FakeRequest())

    def test_invalid_email_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            self._call("pas-un-email")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_valid_optin_is_written_with_optin_status(self):
        with patch.object(api.db, "find_recent_audit_lead", return_value=None), \
             patch.object(api.db, "insert_audit_lead", return_value={"id": "x"}) as ins:
            out = self._call("Lea@Northstack.io", source="founders")
        self.assertTrue(out.get("ok"))
        row = ins.call_args.args[0]
        self.assertEqual(row["email"], "lea@northstack.io")
        # ⚠️ Pas « pending » : ce statut-là est celui des demandes d'audit.
        self.assertEqual(row["status"], "founders_optin")
        self.assertEqual(row["input_kind"], "founders")

    def test_resubmission_does_not_duplicate(self):
        with patch.object(api.db, "find_recent_audit_lead", return_value={"id": "x"}), \
             patch.object(api.db, "insert_audit_lead") as ins:
            out = self._call("lea@northstack.io")
        self.assertTrue(out.get("duplicate"))
        ins.assert_not_called()

    def test_db_failure_never_blocks_the_visitor(self):
        with patch.object(api.db, "find_recent_audit_lead", return_value=None), \
             patch.object(api.db, "insert_audit_lead", side_effect=RuntimeError("boom")):
            out = self._call("lea@northstack.io")
        self.assertTrue(out.get("ok"))


if __name__ == "__main__":
    unittest.main()
