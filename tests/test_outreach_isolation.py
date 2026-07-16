"""ALE-174 — Cloisonnement multi-client du moteur d'envoi (test de non-régression).

LE test qui compte. Le moteur tourne en **service-role** : la base ne refuse plus
d'elle-même les lignes des autres clients (contrairement aux appels portant le jeton
d'un utilisateur, où la RLS s'en charge). Une confusion de propriétaire enverrait le
message du client A **depuis le compte LinkedIn du client B** — sans la moindre
erreur côté Unipile, donc sans que personne ne s'en aperçoive.

Deux remparts, testés séparément ici :
  1. chaque accès base filtre sur `user_id` (`db.admin_*`) ;
  2. `assert_same_owner` revérifie compte/action/lead juste avant l'appel réseau,
     au cas où le rempart 1 serait un jour cassé par un refacto.

C'est ce fichier, pas la vigilance humaine, qui protège des refactos futurs.
"""
from __future__ import annotations

import datetime
import unittest
from unittest.mock import patch

from src import outreach_engine as engine
from src import outreach_sender, unipile

UTC = datetime.timezone.utc
TUESDAY_10H = datetime.datetime(2026, 7, 14, 10, 0, tzinfo=UTC)  # mardi midi à Paris
TUESDAY_NIGHT = datetime.datetime(2026, 7, 14, 2, 0, tzinfo=UTC)


def _account(user_id: str, account_id: str) -> dict:
    return {
        "user_id": user_id,
        "unipile_account_id": account_id,
        "daily_cap": 25,
        "weekly_invite_cap": 100,
        "timezone": "Europe/Paris",
        "send_hour_start": 9,
        "send_hour_end": 18,
        "send_days": [1, 2, 3, 4, 5],
        "connected_at": (TUESDAY_10H - datetime.timedelta(days=90)).isoformat(),
        "frozen": False,
    }


class FakeDB:
    """Base en mémoire. `scoped=False` simule un rempart 1 CASSÉ (les requêtes
    ignorent le `user_id`) pour vérifier que le rempart 2 tient quand même."""

    def __init__(self, *, scoped: bool = True):
        self.scoped = scoped
        self.accounts = [_account("user-a", "acc-a"), _account("user-b", "acc-b")]
        self.leads = {
            "lead-a": {"id": "lead-a", "user_id": "user-a", "profile_url": "https://linkedin.com/in/alice", "provider_id": "prov-a"},
            "lead-b": {"id": "lead-b", "user_id": "user-b", "profile_url": "https://linkedin.com/in/bob", "provider_id": "prov-b"},
        }
        self.queue: list[dict] = []
        self.logged: list[dict] = []
        self.frozen: list[tuple[str, str]] = []
        self.runs: list[tuple[str, int, str | None]] = []
        self.item_updates: list[tuple[str, str, str, str | None]] = []
        self.lead_updates: list[tuple[str, str, dict]] = []
        self.checked: list[tuple[str, str]] = []

    # — accès du cron (service-role) —
    def admin_enabled(self) -> bool:
        return True

    def admin_list_outreach_accounts(self) -> list[dict]:
        return list(self.accounts)

    def admin_pending_queue_count(self, user_id: str) -> int:
        return len([i for i in self.queue if i["status"] == "pending" and (not self.scoped or i["user_id"] == user_id)])

    def admin_due_queue_items(self, user_id: str, *, limit: int = 10) -> list[dict]:
        items = [i for i in self.queue if i["status"] == "pending" and (not self.scoped or i["user_id"] == user_id)]
        return items[:limit]

    def admin_outreach_counts(self, user_id: str) -> dict:
        return {"invites_today": 0, "messages_today": 0, "invites_week": 0}

    def admin_get_lead(self, user_id: str, lead_id: str):
        lead = self.leads.get(lead_id)
        if not lead:
            return None
        if self.scoped and lead["user_id"] != user_id:
            return None  # ← le filtre `user_id` de la vraie requête, qui est LE rempart n°1
        return dict(lead)

    def admin_update_lead_outreach(self, user_id: str, lead_id: str, fields: dict):
        self.lead_updates.append((user_id, lead_id, dict(fields)))
        lead = self.leads.get(lead_id)
        if lead is not None and (not self.scoped or lead["user_id"] == user_id):
            lead.update(fields)
        return lead

    def admin_list_leads_awaiting_acceptance(self, user_id: str, *, limit: int = 100) -> list[dict]:
        leads = [
            dict(lead) for lead in self.leads.values()
            if lead.get("outreach_status") == "invite_sent" and (not self.scoped or lead["user_id"] == user_id)
        ]
        return leads[:limit]

    def admin_mark_lead_checked(self, user_id: str, lead_id: str):
        self.checked.append((user_id, lead_id))

    def admin_log_outreach_action(self, user_id: str, **kwargs):
        self.logged.append({"user_id": user_id, **kwargs})

    def admin_update_queue_item(self, user_id: str, item_id: str, *, status: str, error: str | None = None):
        for item in self.queue:
            if item["id"] == item_id:
                item["status"] = status
        self.item_updates.append((user_id, item_id, status, error))

    def admin_mark_outreach_sent(self, user_id: str, *, next_action_at: str):
        pass

    def admin_freeze_outreach_account(self, user_id: str, reason: str):
        self.frozen.append((user_id, reason))

    def admin_unfreeze_outreach_account(self, user_id: str):
        pass

    def admin_record_engine_run(self, user_id: str, *, sent: int = 0, error: str | None = None):
        self.runs.append((user_id, sent, error))


class FakeUnipile:
    """Unipile en mémoire : on enregistre QUEL compte a servi à envoyer QUOI."""

    UnipileError = unipile.UnipileError

    def __init__(self, *, fail_with: str | None = None, accepted: set | None = None):
        self.invitations: list[tuple[str, str]] = []   # (account_id, provider_id)
        self.messages: list[tuple[str, str, str]] = []  # (account_id, provider_id, texte)
        self.fail_with = fail_with
        # Provider_ids déjà en relation (1er niveau) : simule des invitations acceptées.
        self.accepted = accepted or set()
        self.profile_lookups: list[tuple[str, str]] = []  # (account_id, identifier)

    def enabled(self) -> bool:
        return True

    def profile_identifier(self, url):
        return (url or "").rstrip("/").split("/")[-1] or None

    def get_user_profile(self, account_id, identifier):
        # `identifier` = un provider_id déjà connu, sinon le slug public du profil.
        self.profile_lookups.append((account_id, identifier))
        provider_id = identifier if str(identifier).startswith("prov-") else f"prov-{str(identifier)[0]}"
        distance = "DISTANCE_1" if provider_id in self.accepted else "DISTANCE_2"
        return {"provider_id": provider_id, "network_distance": distance}

    def provider_id_of(self, profile):
        return (profile or {}).get("provider_id")

    def is_first_degree(self, profile):
        return (profile or {}).get("network_distance") == "DISTANCE_1"

    def chat_id_of(self, result):
        return (result or {}).get("id")

    def send_invitation(self, account_id, provider_id):
        if self.fail_with:
            raise unipile.UnipileError(self.fail_with)
        self.invitations.append((account_id, provider_id))
        return {"ok": True}

    def start_new_chat(self, account_id, provider_id, text):
        if self.fail_with:
            raise unipile.UnipileError(self.fail_with)
        self.messages.append((account_id, provider_id, text))
        return {"id": "chat-1"}


def _queued(item_id: str, user_id: str, lead_id: str, action_type: str = "invite", body=None) -> dict:
    return {
        "id": item_id, "user_id": user_id, "lead_id": lead_id,
        "action_type": action_type, "body": body, "status": "pending",
        "not_before": (TUESDAY_10H - datetime.timedelta(hours=1)).isoformat(),
    }


class IsolationTest(unittest.TestCase):
    def _run(self, fake_db: FakeDB, fake_unipile: FakeUnipile, now=TUESDAY_10H):
        with patch.object(outreach_sender, "db", fake_db), \
             patch.object(outreach_sender, "unipile", fake_unipile), \
             patch.object(outreach_sender, "_now", lambda: now):
            outreach_sender.run()

    def test_chaque_client_envoie_depuis_SON_compte(self):
        """Deux clients, deux comptes LinkedIn, une action chacun : personne ne croise."""
        db = FakeDB()
        db.queue = [_queued("q-a", "user-a", "lead-a"), _queued("q-b", "user-b", "lead-b")]
        uni = FakeUnipile()

        self._run(db, uni)

        self.assertEqual(sorted(uni.invitations), [("acc-a", "prov-a"), ("acc-b", "prov-b")])
        # Chaque action est journalisée sous son propre propriétaire.
        self.assertEqual({log["user_id"] for log in db.logged}, {"user-a", "user-b"})

    def test_une_action_de_A_ne_touche_JAMAIS_le_compte_de_B(self):
        """Le compte de B n'est jamais sollicité quand seul A a du travail en file."""
        db = FakeDB()
        db.queue = [_queued("q-a", "user-a", "lead-a")]
        uni = FakeUnipile()

        self._run(db, uni)

        self.assertEqual(uni.invitations, [("acc-a", "prov-a")])
        self.assertNotIn("acc-b", [account_id for account_id, _ in uni.invitations])

    def test_action_de_A_pointant_le_lead_de_B_rien_ne_part(self):
        """Rempart n°1 : le filtre `user_id` de la requête. Le lead d'un autre client
        est simplement introuvable → l'action échoue, aucun appel réseau."""
        db = FakeDB()
        db.queue = [_queued("q-poison", "user-a", "lead-b")]  # ← lead de B dans la file de A
        uni = FakeUnipile()

        self._run(db, uni)

        self.assertEqual(uni.invitations, [], "aucune invitation ne doit partir")
        self.assertEqual(uni.messages, [])
        statuses = [status for (_, item_id, status, _) in db.item_updates if item_id == "q-poison"]
        self.assertEqual(statuses, ["failed"])

    def test_si_la_base_cesse_de_cloisonner_le_garde_fou_tient(self):
        """Rempart n°2 : on simule un refacto qui casse le filtre `user_id` (la base
        renvoie le lead d'un autre client). `assert_same_owner` doit refuser l'envoi —
        c'est ce qui empêche le message de A de partir depuis le compte de B."""
        db = FakeDB(scoped=False)  # ← la base ne cloisonne plus rien
        db.queue = [_queued("q-poison", "user-a", "lead-b")]
        uni = FakeUnipile()

        self._run(db, uni)

        self.assertEqual(uni.invitations, [], "un propriétaire incohérent ne doit JAMAIS partir sur le réseau")
        errors = [error for (_, _, error) in db.runs if error]
        self.assertTrue(any("propriétaire" in (error or "").lower() for error in errors),
                        f"la violation doit être tracée, pas avalée : {errors}")

    def test_le_garde_fou_leve_bien_sur_des_proprietaires_melanges(self):
        account = _account("user-a", "acc-a")
        item = _queued("q-a", "user-a", "lead-b")
        foreign_lead = {"id": "lead-b", "user_id": "user-b"}
        with self.assertRaises(engine.OwnershipError):
            engine.assert_same_owner(account["user_id"], item["user_id"], foreign_lead["user_id"])


class EngineBehaviourTest(unittest.TestCase):
    """Le cadençage vu de bout en bout (le moteur, pas seulement la décision)."""

    def _run(self, fake_db, fake_unipile, now=TUESDAY_10H):
        with patch.object(outreach_sender, "db", fake_db), \
             patch.object(outreach_sender, "unipile", fake_unipile), \
             patch.object(outreach_sender, "_now", lambda: now):
            outreach_sender.run()

    def test_hors_plage_horaire_rien_ne_part(self):
        db = FakeDB()
        db.queue = [_queued("q-a", "user-a", "lead-a")]
        uni = FakeUnipile()

        self._run(db, uni, now=TUESDAY_NIGHT)  # 4 h du matin à Paris

        self.assertEqual(uni.invitations, [])
        self.assertEqual(db.queue[0]["status"], "pending", "l'action reste en file, elle n'est pas perdue")

    def test_compte_gele_rien_ne_part(self):
        db = FakeDB()
        db.accounts[0] = {**db.accounts[0], "frozen": True, "frozen_at": TUESDAY_10H.isoformat(),
                          "freeze_reason": "limite LinkedIn"}
        db.queue = [_queued("q-a", "user-a", "lead-a")]
        uni = FakeUnipile()

        self._run(db, uni)

        self.assertEqual([account_id for account_id, _ in uni.invitations], [],
                         "un compte gelé ne doit rien envoyer")

    def test_une_seule_action_par_passage(self):
        """Le rythme, c'est le cœur du sujet : on ne vide pas la file d'un coup."""
        db = FakeDB()
        db.queue = [
            _queued("q-1", "user-a", "lead-a"),
            _queued("q-2", "user-a", "lead-a", action_type="message", body="Salut"),
        ]
        uni = FakeUnipile()

        self._run(db, uni)

        self.assertEqual(len(uni.invitations) + len(uni.messages), 1)

    def test_une_restriction_LinkedIn_gele_le_compte(self):
        db = FakeDB()
        db.queue = [_queued("q-a", "user-a", "lead-a")]
        uni = FakeUnipile(fail_with="Invitation limit reached")

        self._run(db, uni)

        self.assertEqual([user_id for user_id, _ in db.frozen], ["user-a"])
        self.assertEqual(db.queue[0]["status"], "failed")

    def test_une_erreur_banale_ne_gele_pas_le_compte(self):
        db = FakeDB()
        db.queue = [_queued("q-a", "user-a", "lead-a")]
        uni = FakeUnipile(fail_with="Profile not found")

        self._run(db, uni)

        self.assertEqual(db.frozen, [], "un profil introuvable n'est pas une restriction")

    def test_le_passage_est_trace_meme_quand_rien_ne_part(self):
        """La fraîcheur de cette trace est le SEUL moyen de voir un moteur mort."""
        db = FakeDB()
        uni = FakeUnipile()

        self._run(db, uni)

        self.assertEqual(sorted(user_id for user_id, _, _ in db.runs), ["user-a", "user-b"])


class AcceptanceDetectionTest(unittest.TestCase):
    """Détection automatique de l'acceptation, vue de bout en bout (via `run()`)."""

    def _run(self, fake_db, fake_unipile, now=TUESDAY_10H):
        with patch.object(outreach_sender, "db", fake_db), \
             patch.object(outreach_sender, "unipile", fake_unipile), \
             patch.object(outreach_sender, "_now", lambda: now):
            outreach_sender.run()

    def test_invitation_acceptee_bascule_en_relation(self):
        db = FakeDB()
        db.leads["lead-a"]["outreach_status"] = "invite_sent"
        uni = FakeUnipile(accepted={"prov-a"})  # A a accepté

        self._run(db, uni)

        # Le lead d'A passe « connected », vu depuis le compte d'A uniquement.
        flips = [(uid, lid, f.get("outreach_status")) for (uid, lid, f) in db.lead_updates]
        self.assertIn(("user-a", "lead-a", "connected"), flips)
        self.assertIn(("acc-a", "prov-a"), uni.profile_lookups)
        # Aucune invitation/message n'est envoyé : détecter n'est pas prospecter.
        self.assertEqual(uni.invitations, [])
        self.assertEqual(uni.messages, [])

    def test_invitation_non_acceptee_note_juste_le_re_check(self):
        db = FakeDB()
        db.leads["lead-a"]["outreach_status"] = "invite_sent"
        uni = FakeUnipile()  # personne n'a accepté (DISTANCE_2)

        self._run(db, uni)

        self.assertIn(("user-a", "lead-a"), db.checked)
        self.assertEqual([(u, l, f.get("outreach_status")) for (u, l, f) in db.lead_updates], [])

    def test_le_lead_dun_client_est_verifie_depuis_SON_compte(self):
        """Cloisonnement : le profil du lead de B n'est jamais lu via le compte d'A."""
        db = FakeDB()
        db.leads["lead-a"]["outreach_status"] = "invite_sent"
        db.leads["lead-b"]["outreach_status"] = "invite_sent"
        uni = FakeUnipile(accepted={"prov-a", "prov-b"})

        self._run(db, uni)

        # prov-a n'est lu que par acc-a, prov-b que par acc-b — jamais croisé.
        self.assertNotIn(("acc-a", "prov-b"), uni.profile_lookups)
        self.assertNotIn(("acc-b", "prov-a"), uni.profile_lookups)

    def test_compte_gele_aucune_verification(self):
        db = FakeDB()
        db.accounts[0] = {**db.accounts[0], "frozen": True, "frozen_at": TUESDAY_10H.isoformat(),
                          "freeze_reason": "limite LinkedIn"}
        db.leads["lead-a"]["outreach_status"] = "invite_sent"
        uni = FakeUnipile(accepted={"prov-a"})

        self._run(db, uni)

        # Pendant un gel, on ne tape pas l'API d'Unipile, même en lecture.
        self.assertNotIn(("acc-a", "prov-a"), uni.profile_lookups)


if __name__ == "__main__":
    unittest.main()
