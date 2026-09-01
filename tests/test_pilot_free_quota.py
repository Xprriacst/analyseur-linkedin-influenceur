"""Plan « Pilote gratuit » — quotas 1 post / jour, 3 contacts / jour.

C'est un garde-fou de COÛT : chaque génération autorisée à tort est un appel
Anthropic payé par nous pour un compte qui ne paie rien. Il échoue donc FERMÉ —
une lecture de compteur qui casse doit BLOQUER, jamais laisser passer.

Ce fichier verrouille les quatre pannes qui seraient silencieuses en production :
  1. le plafond ne borne rien (le compte génère sans fin) ;
  2. une lecture de compteur en échec ouvre les vannes au lieu de les fermer ;
  3. un job annulé/en échec brûle le quota du jour (le client perd son post sur
     un hoquet du modèle) ;
  4. la fenêtre glissante ne glisse pas (le quota ne se libère jamais, ou
     l'inverse : il compte des jobs d'il y a une semaine).

Et LE test de sécurité : un droit ne se décide jamais depuis `user_metadata`,
que l'utilisateur édite lui-même depuis son navigateur.
"""
from __future__ import annotations

import datetime
import unittest
from unittest.mock import MagicMock, patch

from src import pilot_plan as pp

UTC = datetime.timezone.utc


def _user(**app_meta):
    return {"id": "u1", "email": "x@y.z", "app_metadata": app_meta}


# --------------------------------------------------------------------------- #
# 1. La source du plan : app_metadata, et rien d'autre
# --------------------------------------------------------------------------- #

class PlanSourceTest(unittest.TestCase):
    def test_plan_read_from_app_metadata(self):
        self.assertTrue(pp.is_pilot_free(_user(plan="pilot_free")))
        self.assertEqual(pp.plan_of(_user(plan="pilot_free")), "pilot_free")

    def test_no_plan_is_historic_behaviour(self):
        """Défaut = aucun quota : abonnés Stripe, comptes agence, comptes à crédits."""
        self.assertFalse(pp.is_pilot_free(_user()))
        self.assertIsNone(pp.plan_of(_user()))

    def test_case_and_spacing_tolerated(self):
        """Un plan posé à la main en SQL peut arriver avec une casse ou un espace."""
        self.assertTrue(pp.is_pilot_free(_user(plan="  Pilot_Free ")))

    def test_another_plan_is_not_pilot_free(self):
        self.assertFalse(pp.is_pilot_free(_user(plan="expert")))

    def test_malformed_metadata_is_not_pilot_free(self):
        for forged in (None, {}, {"app_metadata": None}, {"app_metadata": "nimportequoi"},
                       {"app_metadata": {"plan": 42}}, {"app_metadata": {"plan": "   "}}):
            self.assertFalse(pp.is_pilot_free(forged), forged)


class UserMetadataIsNotATrustSourceTest(unittest.TestCase):
    """LE test de sécurité, jumeau de celui de `src/features.py`.

    `user_metadata` est modifiable par l'utilisateur depuis son navigateur
    (`supabase.auth.updateUser`) — et la landing /pilote y écrit déjà
    `landing='pilote'` pour son compteur de funnel. Si le plan s'y lisait, la
    manœuvre inverse serait triviale : poser `plan: "expert"` en une ligne de
    console pour se débarrasser du plafond. Seul `app_metadata` fait foi."""

    def test_user_metadata_never_sets_the_plan(self):
        forged = {"id": "u1", "user_metadata": {"plan": "expert"}, "app_metadata": {"plan": "pilot_free"}}
        self.assertTrue(pp.is_pilot_free(forged))
        self.assertEqual(pp.plan_of(forged), "pilot_free")

    def test_user_metadata_alone_grants_no_plan(self):
        forged = {"id": "u1", "user_metadata": {"plan": "pilot_free", "landing": "pilote"}, "app_metadata": {}}
        self.assertIsNone(pp.plan_of(forged))


# --------------------------------------------------------------------------- #
# 2. La décision : le plafond borne vraiment
# --------------------------------------------------------------------------- #

class PostQuotaDecisionTest(unittest.TestCase):
    def test_first_post_of_the_day_allowed(self):
        self.assertIsNone(pp.post_quota_error(0, 1, limit=1))

    def test_second_post_refused(self):
        msg = pp.post_quota_error(1, 1, limit=1)
        self.assertIsNotNone(msg)
        self.assertIn("Reviens demain", msg)

    def test_a_batch_that_would_bust_the_cap_is_refused_whole(self):
        """Demander 3 posts d'un coup sous un plafond de 1 ne passe pas « en partie ».

        Sans cette borne, `count=3` sur un compteur à 0 passerait le test
        `used < cap` et livrerait 3 posts pour un quota de 1."""
        self.assertIsNotNone(pp.post_quota_error(0, 3, limit=1))
        self.assertIsNone(pp.post_quota_error(0, 3, limit=3))
        self.assertIsNotNone(pp.post_quota_error(1, 3, limit=3))

    def test_already_over_stays_refused(self):
        self.assertIsNotNone(pp.post_quota_error(9, 1, limit=1))

    def test_default_cap_is_one_per_day(self):
        """La landing promet « 1 post par jour » — le défaut doit le tenir."""
        self.assertEqual(pp.PILOT_FREE_POSTS_PER_DAY, 1)
        self.assertIsNone(pp.post_quota_error(0))
        self.assertIsNotNone(pp.post_quota_error(1))


class LeadQuotaDecisionTest(unittest.TestCase):
    def test_three_contacts_allowed_then_refused(self):
        self.assertIsNone(pp.lead_quota_error(0))
        self.assertIsNone(pp.lead_quota_error(2))
        self.assertIsNotNone(pp.lead_quota_error(3))

    def test_default_cap_is_three_per_day(self):
        """La landing promet « jusqu'à 3 contacts par jour »."""
        self.assertEqual(pp.PILOT_FREE_LEADS_PER_DAY, 3)

    def test_cap_matches_the_daily_plan_rail(self):
        """Le rail « À contacter » montre `PILOT_CONTACT_LIMIT` contacts.

        Si le quota était plus bas, l'écran proposerait des contacts que le
        serveur refuse d'inviter — une promesse contredite au clic."""
        self.assertEqual(pp.PILOT_FREE_LEADS_PER_DAY, pp.PILOT_CONTACT_LIMIT)

    def test_message_names_the_cap_and_the_way_out(self):
        msg = pp.lead_quota_error(3)
        self.assertIn("3 contacts par jour", msg)
        self.assertIn("Expert", msg)


# --------------------------------------------------------------------------- #
# 3. Le comptage : fenêtre glissante, jobs perdus non facturés
# --------------------------------------------------------------------------- #

class _FakeQuery:
    """Chaîne postgrest minimale ; mémorise les filtres pour les assertions."""

    def __init__(self, rows, calls):
        self._rows, self._calls = rows, calls

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._calls.setdefault("eq", []).append((col, val))
        return self

    def gte(self, col, val):
        self._calls.setdefault("gte", []).append((col, val))
        return self

    def execute(self):
        return MagicMock(data=self._rows)


class _FakeDB:
    def __init__(self, tables):
        self.tables, self.calls = tables, {}

    def table(self, name):
        self.calls.setdefault("tables", []).append(name)
        return _FakeQuery(self.tables.get(name, []), self.calls)


def _jobs(rows):
    return _FakeDB({"generation_jobs": rows})


class CountRecentGeneratedPostsTest(unittest.TestCase):
    @patch("src.db.get_user", return_value={"id": "u1"})
    @patch("src.db.supabase_enabled", return_value=True)
    def _count(self, rows, _en, _user, **kwargs):
        from src import db as dbmod

        fake = _jobs(rows)
        with patch("src.db.client_for_token", return_value=fake):
            return dbmod.count_recent_generated_posts("tok", **kwargs), fake

    def test_counts_requested_variants_not_rows(self):
        total, _ = self._count([{"count": 2, "status": "done"}, {"count": 1, "status": "running"}])
        self.assertEqual(total, 3)

    def test_cancelled_and_error_jobs_do_not_burn_the_quota(self):
        """Un post jamais produit ne consomme pas l'unique post du jour.

        Sans ça, un plantage du modèle coûterait au client sa journée — et il
        n'aurait aucun moyen de le récupérer."""
        total, _ = self._count([
            {"count": 1, "status": "cancelled"},
            {"count": 1, "status": "error"},
            {"count": 1, "status": "done"},
        ])
        self.assertEqual(total, 1)

    def test_queued_and_running_jobs_count(self):
        """Sinon, lancer 10 jobs avant qu'aucun n'ait fini contournerait le plafond."""
        total, _ = self._count([{"count": 1, "status": "queued"}, {"count": 1, "status": "running"}])
        self.assertEqual(total, 2)

    def test_missing_or_bogus_count_falls_back_to_one(self):
        total, _ = self._count([{"status": "done"}, {"count": None, "status": "done"},
                                {"count": "trois", "status": "done"}, {"count": 0, "status": "done"}])
        self.assertEqual(total, 4)

    def test_sliding_window_is_scoped_to_the_user_and_to_24h(self):
        """La fenêtre glisse (aucun compteur à réinitialiser) ET la requête est
        bornée au propriétaire : un compteur non scopé additionnerait les
        générations de tous les clients."""
        before = datetime.datetime.now(UTC) - datetime.timedelta(hours=24)
        _, fake = self._count([])
        self.assertIn(("user_id", "u1"), fake.calls["eq"])
        (col, since), = fake.calls["gte"]
        self.assertEqual(col, "created_at")
        parsed = datetime.datetime.fromisoformat(since)
        self.assertLess(abs((parsed - before).total_seconds()), 5)

    def test_window_is_configurable(self):
        _, fake = self._count([], hours=48)
        (_, since), = fake.calls["gte"]
        expected = datetime.datetime.now(UTC) - datetime.timedelta(hours=48)
        self.assertLess(abs((datetime.datetime.fromisoformat(since) - expected).total_seconds()), 5)

    def test_a_job_outside_the_window_is_never_read(self):
        """Le filtre `created_at >= since` est porté par la REQUÊTE, pas par un
        tri en Python : un job d'il y a une semaine n'est jamais rendu."""
        from src import db as dbmod

        old = (datetime.datetime.now(UTC) - datetime.timedelta(days=7)).isoformat()
        recent = datetime.datetime.now(UTC).isoformat()

        class WindowedDB(_FakeDB):
            def table(self, name):  # applique vraiment le gte, comme Postgres
                rows = self.tables.get(name, [])
                calls = self.calls

                class Q(_FakeQuery):
                    def gte(self, col, val):
                        self._rows = [r for r in self._rows if r.get("created_at", "") >= val]
                        return super().gte(col, val)

                return Q(list(rows), calls)

        fake = WindowedDB({"generation_jobs": [
            {"count": 5, "status": "done", "created_at": old},
            {"count": 1, "status": "done", "created_at": recent},
        ]})
        with patch("src.db.supabase_enabled", return_value=True), \
             patch("src.db.get_user", return_value={"id": "u1"}), \
             patch("src.db.client_for_token", return_value=fake):
            self.assertEqual(dbmod.count_recent_generated_posts("tok"), 1)


class CountRecentLeadInvitesTest(unittest.TestCase):
    def _count(self, queue_rows, action_rows):
        from src import db as dbmod

        fake = _FakeDB({
            "linkedin_outreach_queue": queue_rows,
            "linkedin_outreach_actions": action_rows,
        })
        with patch("src.db.supabase_enabled", return_value=True), \
             patch("src.db.get_user", return_value={"id": "u1"}), \
             patch("src.db.client_for_token", return_value=fake):
            return dbmod.count_recent_lead_invites("tok"), fake

    def test_queue_and_immediate_add_up(self):
        total, _ = self._count(
            [{"id": "q1", "status": "pending"}, {"id": "q2", "status": "sent"}],
            [{"id": "a1"}],
        )
        self.assertEqual(total, 3)

    def test_a_queued_invite_is_not_counted_twice(self):
        """Le moteur journalise ses envois en `origin='queue'`. Le journal n'est
        relu QUE pour `origin='immediate'` — sinon chaque invitation partie de la
        file compterait double et le client perdrait la moitié de ses contacts."""
        _, fake = self._count([{"id": "q1", "status": "sent"}], [])
        self.assertIn(("origin", "immediate"), fake.calls["eq"])

    def test_cancelled_or_failed_queue_items_give_the_slot_back(self):
        total, _ = self._count(
            [{"id": "q1", "status": "cancelled"}, {"id": "q2", "status": "canceled"},
             {"id": "q3", "status": "failed"}, {"id": "q4", "status": "skipped"}],
            [],
        )
        self.assertEqual(total, 0)

    def test_only_invites_are_counted_and_only_for_this_user(self):
        _, fake = self._count([], [])
        self.assertIn(("action_type", "invite"), fake.calls["eq"])
        self.assertIn(("user_id", "u1"), fake.calls["eq"])
        self.assertEqual(fake.calls["eq"].count(("user_id", "u1")), 2)  # les deux tables


class CountersInactiveWithoutSupabaseTest(unittest.TestCase):
    """Sans Supabase (ou sans utilisateur), les compteurs valent 0 — la
    fonctionnalité est inactive, ce n'est pas une lecture qui a échoué."""

    def test_zero_without_supabase(self):
        from src import db as dbmod

        with patch("src.db.supabase_enabled", return_value=False):
            self.assertEqual(dbmod.count_recent_generated_posts("tok"), 0)
            self.assertEqual(dbmod.count_recent_lead_invites("tok"), 0)

    def test_zero_without_user(self):
        from src import db as dbmod

        with patch("src.db.supabase_enabled", return_value=True), \
             patch("src.db.get_user", return_value=None):
            self.assertEqual(dbmod.count_recent_generated_posts("tok"), 0)
            self.assertEqual(dbmod.count_recent_lead_invites("tok"), 0)


class CountersFailClosedTest(unittest.TestCase):
    """LE point de conception du lot : une lecture qui casse doit REMONTER.

    Le patron habituel du dépôt est le best-effort silencieux (`except: return
    []`). Ici il serait exactement à l'envers : Supabase indisponible et le
    plafond s'évapore, sans une ligne dans les logs. Les compteurs LÈVENT ;
    c'est l'appelant (api.py) qui traduit en 503."""

    def _boom(self):
        fake = MagicMock()
        fake.table.side_effect = RuntimeError("supabase down")
        return fake

    def test_generated_posts_counter_raises(self):
        from src import db as dbmod

        with patch("src.db.supabase_enabled", return_value=True), \
             patch("src.db.get_user", return_value={"id": "u1"}), \
             patch("src.db.client_for_token", return_value=self._boom()):
            with self.assertRaises(RuntimeError):
                dbmod.count_recent_generated_posts("tok")

    def test_lead_invites_counter_raises(self):
        from src import db as dbmod

        with patch("src.db.supabase_enabled", return_value=True), \
             patch("src.db.get_user", return_value={"id": "u1"}), \
             patch("src.db.client_for_token", return_value=self._boom()):
            with self.assertRaises(RuntimeError):
                dbmod.count_recent_lead_invites("tok")


# --------------------------------------------------------------------------- #
# 4. L'application : ce que fait l'endpoint du compteur qu'il vient de lire
# --------------------------------------------------------------------------- #

class QuotaEnforcementTest(unittest.TestCase):
    """Les gardes d'`api.py` reconstituées à l'identique (le module `api` ne
    s'importe pas hors du serveur : `fastapi` n'est pas installé en local).

    Ce qui est vérifié ici, c'est l'ENCHAÎNEMENT — lire le compteur, décider,
    et surtout : bloquer quand la lecture casse."""

    @staticmethod
    def _guard(user, counter, decide):
        """Copie fidèle de `_require_pilot_*_quota` (api.py)."""
        if not pp.is_pilot_free(user):
            return None                      # compte hors plan : rien n'est même lu
        try:
            used = counter()
        except Exception:
            return 503                       # fail closed
        return 402 if decide(used) else None

    def test_over_quota_is_blocked(self):
        code = self._guard(_user(plan="pilot_free"), lambda: 1,
                           lambda u: pp.post_quota_error(u, 1) is not None)
        self.assertEqual(code, 402)

    def test_under_quota_passes(self):
        code = self._guard(_user(plan="pilot_free"), lambda: 0,
                           lambda u: pp.post_quota_error(u, 1) is not None)
        self.assertIsNone(code)

    def test_counter_failure_blocks_instead_of_letting_through(self):
        """Le cas qui coûte de l'argent si on se trompe de sens."""
        def boom():
            raise RuntimeError("supabase down")

        code = self._guard(_user(plan="pilot_free"), boom, lambda u: False)
        self.assertEqual(code, 503)

    def test_counter_failure_on_a_normal_account_changes_nothing(self):
        """Un incident Supabase ne doit pas bloquer les comptes payants : sur un
        compte hors plan, le compteur n'est même pas lu."""
        reads = []

        def counter():
            reads.append(1)
            raise RuntimeError("supabase down")

        self.assertIsNone(self._guard(_user(), counter, lambda u: True))
        self.assertIsNone(self._guard(_user(plan="expert"), counter, lambda u: True))
        self.assertEqual(reads, [])

    def test_lead_quota_blocks_the_fourth_contact(self):
        for used, expected in ((0, None), (2, None), (3, 402)):
            code = self._guard(_user(plan="pilot_free"), lambda u=used: u,
                               lambda u: pp.lead_quota_error(u) is not None)
            self.assertEqual(code, expected, used)


class UncountedGenerationPathTest(unittest.TestCase):
    """`/generate` et `/generate/stream` n'écrivent AUCUN job.

    Y poser le quota tel quel lisait un compteur qui restait à 0 : le plafond
    était décoratif et un compte gratuit pouvait générer sans fin. On refuse
    franchement — fail closed — et seulement pour les comptes plafonnés."""

    def test_message_points_to_the_app(self):
        msg = pp.uncounted_generation_error()
        self.assertIn("Générateur", msg)
        self.assertIn("Expert", msg)

    def test_only_pilot_free_accounts_are_refused(self):
        def guard(user):
            return 402 if pp.is_pilot_free(user) else None

        self.assertEqual(guard(_user(plan="pilot_free")), 402)
        self.assertIsNone(guard(_user()))                    # crédits / agence
        self.assertIsNone(guard(_user(plan="expert")))       # abonné
        self.assertIsNone(guard(None))                       # appel anonyme


# --------------------------------------------------------------------------- #
# 5. L'attribution du plan : auto-service, jamais une échappatoire
# --------------------------------------------------------------------------- #

class EnrollPilotFreeTest(unittest.TestCase):
    NOW = datetime.datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    def _call(self, **kw):
        base = {"current_plan": None, "has_subscription": False,
                "created_at": (self.NOW - datetime.timedelta(minutes=2)).isoformat(),
                "now": self.NOW}
        base.update(kw)
        return pp.can_enroll_pilot_free(**base)

    def test_fresh_account_gets_the_plan(self):
        self.assertEqual(self._call()[0], "ok")

    def test_idempotent_on_an_account_already_enrolled(self):
        """Re-appeler après un rechargement de page ne doit pas devenir une erreur."""
        self.assertEqual(self._call(current_plan="pilot_free")[0], "already")

    def test_an_existing_plan_is_never_replaced(self):
        self.assertEqual(self._call(current_plan="expert")[0], "refused")

    def test_a_subscriber_cannot_downgrade_itself(self):
        self.assertEqual(self._call(has_subscription=True)[0], "refused")

    def test_an_old_account_cannot_enrol_months_later(self):
        old = (self.NOW - datetime.timedelta(days=90)).isoformat()
        self.assertEqual(self._call(created_at=old)[0], "refused")

    def test_window_edges(self):
        inside = (self.NOW - datetime.timedelta(hours=47)).isoformat()
        outside = (self.NOW - datetime.timedelta(hours=49)).isoformat()
        self.assertEqual(self._call(created_at=inside)[0], "ok")
        self.assertEqual(self._call(created_at=outside)[0], "refused")

    def test_unreadable_creation_date_is_refused(self):
        """Fail closed : un compte dont on ne sait pas l'âge n'est pas « neuf »."""
        for bad in (None, "", "pas-une-date", "2026-13-45"):
            self.assertEqual(self._call(created_at=bad)[0], "refused", bad)

    def test_naive_and_z_suffixed_dates_are_accepted(self):
        """GoTrue rend tantôt un `Z`, tantôt un datetime sans fuseau."""
        self.assertEqual(self._call(created_at="2026-09-01T11:58:00Z")[0], "ok")
        self.assertEqual(self._call(created_at="2026-09-01T11:58:00")[0], "ok")


if __name__ == "__main__":
    unittest.main()
