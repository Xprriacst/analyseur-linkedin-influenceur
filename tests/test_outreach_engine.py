"""ALE-174 — Tests de la logique du moteur d'envoi cadencé.

Tout est pur : ni Supabase, ni Unipile, ni horloge réelle. C'est le but du découpage
`outreach_engine` (décide) / `outreach_sender` (exécute) — la partie qui protège le
compte LinkedIn du client doit être vérifiable d'un bloc, sans réseau.
"""
import datetime
import unittest

from src import outreach_engine as engine

UTC = datetime.timezone.utc

# Mardi 14 juillet 2026, 10 h UTC (12 h à Paris) : en pleine fenêtre d'envoi.
TUESDAY_10H = datetime.datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
# Mardi 14 juillet 2026, 2 h UTC (4 h à Paris) : la nuit.
TUESDAY_NIGHT = datetime.datetime(2026, 7, 14, 2, 0, tzinfo=UTC)
# Dimanche 12 juillet 2026, 10 h UTC : hors jours d'envoi.
SUNDAY_10H = datetime.datetime(2026, 7, 12, 10, 0, tzinfo=UTC)

NO_COUNTS = {"invites_today": 0, "messages_today": 0, "invites_week": 0}


def account(**overrides):
    """Compte connecté il y a longtemps (warm-up terminé), réglages par défaut."""
    base = {
        "user_id": "user-a",
        "unipile_account_id": "acc-a",
        "daily_cap": 25,
        "weekly_invite_cap": 100,
        "timezone": "Europe/Paris",
        "send_hour_start": 9,
        "send_hour_end": 18,
        "send_days": [1, 2, 3, 4, 5],
        "connected_at": (TUESDAY_10H - datetime.timedelta(days=90)).isoformat(),
        "frozen": False,
    }
    base.update(overrides)
    return base


class WarmupTest(unittest.TestCase):
    """Un compte neuf ne doit PAS pouvoir envoyer 25 invitations dès le jour 1."""

    def test_semaine_1_plafonne_bas(self):
        acc = account(connected_at=(TUESDAY_10H - datetime.timedelta(days=2)).isoformat())
        self.assertEqual(engine.warmup_week(TUESDAY_10H, acc), 1)
        self.assertEqual(engine.warmup_cap(TUESDAY_10H, acc), engine.WARMUP_STEPS[0])

    def test_montee_progressive_par_semaine(self):
        for week, expected in enumerate(engine.WARMUP_STEPS, start=1):
            acc = account(connected_at=(TUESDAY_10H - datetime.timedelta(days=7 * (week - 1) + 1)).isoformat())
            self.assertEqual(engine.warmup_cap(TUESDAY_10H, acc), expected, f"semaine {week}")

    def test_apres_le_warmup_le_plafond_configure_sapplique(self):
        acc = account(daily_cap=25)  # connecté il y a 90 jours
        self.assertEqual(engine.warmup_cap(TUESDAY_10H, acc), 25)

    def test_le_warmup_ne_depasse_jamais_le_plafond_choisi(self):
        # Un client prudent qui met 5/jour reste à 5, même en semaine 1 (palier 8).
        acc = account(daily_cap=5, connected_at=(TUESDAY_10H - datetime.timedelta(days=1)).isoformat())
        self.assertEqual(engine.warmup_cap(TUESDAY_10H, acc), 5)

    def test_sans_date_connue_on_reste_prudent(self):
        acc = account(connected_at=None, warmup_started_at=None)
        self.assertEqual(engine.warmup_cap(TUESDAY_10H, acc), engine.WARMUP_STEPS[0])


class SendWindowTest(unittest.TestCase):
    """Des invitations à 3 h du matin un dimanche, c'est le signal le plus facile à voir."""

    def test_en_pleine_journee_ouvree(self):
        self.assertTrue(engine.in_send_window(TUESDAY_10H, account()))

    def test_la_nuit_cest_ferme(self):
        self.assertFalse(engine.in_send_window(TUESDAY_NIGHT, account()))

    def test_le_dimanche_cest_ferme(self):
        self.assertFalse(engine.in_send_window(SUNDAY_10H, account()))

    def test_la_fenetre_suit_le_fuseau_du_client(self):
        # 10 h UTC = 12 h à Paris (ouvert) mais 6 h à New York (fermé).
        self.assertTrue(engine.in_send_window(TUESDAY_10H, account(timezone="Europe/Paris")))
        self.assertFalse(engine.in_send_window(TUESDAY_10H, account(timezone="America/New_York")))

    def test_un_fuseau_invalide_ne_casse_rien(self):
        self.assertTrue(engine.in_send_window(TUESDAY_10H, account(timezone="Mars/Olympus")))

    def test_prochaine_ouverture_apres_la_nuit(self):
        nxt = engine.next_window_start(TUESDAY_NIGHT, account())
        local = nxt.astimezone(engine._tz(account()))
        self.assertEqual((local.isoweekday(), local.hour), (2, 9))  # mardi 9 h

    def test_prochaine_ouverture_depuis_le_dimanche_saute_au_lundi(self):
        nxt = engine.next_window_start(SUNDAY_10H, account())
        local = nxt.astimezone(engine._tz(account()))
        self.assertEqual((local.isoweekday(), local.hour), (1, 9))  # lundi 9 h


class DecideTest(unittest.TestCase):
    def test_cas_nominal(self):
        self.assertTrue(engine.decide(TUESDAY_10H, account(), NO_COUNTS, action_type="invite").can_send)

    def test_compteurs_illisibles_on_nenvoie_pas(self):
        """Fail CLOSED : un garde-fou anti-restriction ne s'efface pas sur une erreur de lecture."""
        d = engine.decide(TUESDAY_10H, account(), NO_COUNTS, action_type="invite", counts_ok=False)
        self.assertFalse(d.can_send)
        self.assertEqual(d.code, "counts_unavailable")

    def test_hors_plage_horaire(self):
        d = engine.decide(TUESDAY_NIGHT, account(), NO_COUNTS, action_type="invite")
        self.assertFalse(d.can_send)
        self.assertEqual(d.code, "closed")

    def test_plafond_hebdo_invitations(self):
        counts = {"invites_today": 0, "messages_today": 0, "invites_week": 100}
        d = engine.decide(TUESDAY_10H, account(), counts, action_type="invite")
        self.assertFalse(d.can_send)
        self.assertEqual(d.code, "quota")
        # …mais un message reste possible : la sécurité hebdo ne porte que sur les invitations.
        self.assertTrue(engine.decide(TUESDAY_10H, account(), counts, action_type="message").can_send)

    def test_le_palier_de_warmup_porte_sur_le_total_du_jour(self):
        """Un compte neuf ne doit pas faire 8 invitations ET 8 messages."""
        acc = account(connected_at=(TUESDAY_10H - datetime.timedelta(days=1)).isoformat())  # semaine 1 → 8
        counts = {"invites_today": 4, "messages_today": 4, "invites_week": 4}
        d = engine.decide(TUESDAY_10H, acc, counts, action_type="invite")
        self.assertFalse(d.can_send)
        self.assertEqual(d.code, "warmup")

    def test_delai_entre_deux_actions(self):
        acc = account(next_action_at=(TUESDAY_10H + datetime.timedelta(minutes=15)).isoformat())
        d = engine.decide(TUESDAY_10H, acc, NO_COUNTS, action_type="invite")
        self.assertFalse(d.can_send)
        self.assertEqual(d.code, "gap")
        # Une fois le délai écoulé, ça repart.
        later = TUESDAY_10H + datetime.timedelta(minutes=16)
        self.assertTrue(engine.decide(later, acc, NO_COUNTS, action_type="invite").can_send)

    def test_le_delai_est_aleatoire_et_borne(self):
        gaps = {engine.pick_gap().total_seconds() / 60 for _ in range(50)}
        self.assertGreater(len(gaps), 1, "un rythme parfaitement régulier est aussi un signal")
        self.assertTrue(all(engine.MIN_GAP_MINUTES <= g <= engine.MAX_GAP_MINUTES for g in gaps))


class SoupapeTest(unittest.TestCase):
    """La soupape « envoyer maintenant » saute le rythme — jamais les garde-fous."""

    def test_elle_saute_la_plage_horaire_et_le_delai(self):
        acc = account(next_action_at=(TUESDAY_NIGHT + datetime.timedelta(hours=2)).isoformat())
        self.assertTrue(
            engine.decide(TUESDAY_NIGHT, acc, NO_COUNTS, action_type="invite", ignore_pacing=True).can_send
        )

    def test_elle_ne_saute_PAS_les_plafonds(self):
        counts = {"invites_today": 25, "messages_today": 0, "invites_week": 25}
        d = engine.decide(TUESDAY_10H, account(), counts, action_type="invite", ignore_pacing=True)
        self.assertFalse(d.can_send)

    def test_elle_ne_saute_PAS_le_warmup(self):
        acc = account(connected_at=(TUESDAY_10H - datetime.timedelta(days=1)).isoformat())
        counts = {"invites_today": 8, "messages_today": 0, "invites_week": 8}
        d = engine.decide(TUESDAY_10H, acc, counts, action_type="invite", ignore_pacing=True)
        self.assertFalse(d.can_send)

    def test_elle_ne_saute_PAS_le_gel(self):
        acc = account(frozen=True, frozen_at=TUESDAY_10H.isoformat(), freeze_reason="limite")
        d = engine.decide(TUESDAY_10H, acc, NO_COUNTS, action_type="invite", ignore_pacing=True)
        self.assertFalse(d.can_send)
        self.assertEqual(d.code, "frozen")


class FreezeTest(unittest.TestCase):
    def test_une_erreur_de_limite_est_reconnue(self):
        for message in (
            "Invitation limit reached",
            "Account restricted by LinkedIn",
            "429 too many requests",
            "cannot_resend_yet",
        ):
            self.assertTrue(engine.is_restriction_error(message), message)

    def test_une_erreur_banale_ne_gele_pas_le_compte(self):
        for message in ("Profile not found", "Network timeout", "", None):
            self.assertFalse(engine.is_restriction_error(message), message)

    def test_le_gel_bloque_puis_expire_tout_seul(self):
        acc = account(frozen=True, frozen_at=TUESDAY_10H.isoformat())
        self.assertTrue(engine.freeze_active(TUESDAY_10H + datetime.timedelta(hours=1), acc))
        after = TUESDAY_10H + datetime.timedelta(hours=engine.FREEZE_COOLDOWN_HOURS + 1)
        self.assertFalse(engine.freeze_active(after, acc), "un gel définitif serait une impasse, pas un garde-fou")


class StalledTest(unittest.TestCase):
    """Un cron mort ne peut pas alerter sur sa propre mort : c'est l'app qui le voit."""

    def test_file_vide_pas_dalerte(self):
        self.assertFalse(engine.is_stalled(TUESDAY_10H, None, 0))

    def test_du_travail_en_file_et_aucun_passage_connu(self):
        self.assertTrue(engine.is_stalled(TUESDAY_10H, None, 3))

    def test_passage_recent_tout_va_bien(self):
        recent = (TUESDAY_10H - datetime.timedelta(minutes=8)).isoformat()
        self.assertFalse(engine.is_stalled(TUESDAY_10H, recent, 3))

    def test_moteur_muet_depuis_trop_longtemps(self):
        old = (TUESDAY_10H - datetime.timedelta(hours=3)).isoformat()
        self.assertTrue(engine.is_stalled(TUESDAY_10H, old, 3))


class PickSendableTest(unittest.TestCase):
    def test_une_invitation_bloquee_ne_bloque_pas_les_messages_derriere(self):
        counts = {"invites_today": 0, "messages_today": 0, "invites_week": 100}  # invitations au plafond hebdo
        items = [
            {"id": "1", "action_type": "invite"},
            {"id": "2", "action_type": "message"},
        ]
        item, decision = engine.pick_sendable(TUESDAY_10H, account(), counts, items)
        self.assertIsNotNone(item)
        self.assertEqual(item["id"], "2")
        self.assertTrue(decision.can_send)

    def test_rien_ne_part_hors_plage(self):
        items = [{"id": "1", "action_type": "invite"}]
        item, decision = engine.pick_sendable(TUESDAY_NIGHT, account(), NO_COUNTS, items)
        self.assertIsNone(item)
        self.assertEqual(decision.code, "closed")


class OwnershipTest(unittest.TestCase):
    """Le moteur tourne en service-role : la base ne cloisonne plus rien pour lui."""

    def test_meme_proprietaire_ok(self):
        self.assertEqual(engine.assert_same_owner("user-a", "user-a", "user-a"), "user-a")

    def test_proprietaires_differents_on_leve(self):
        with self.assertRaises(engine.OwnershipError):
            engine.assert_same_owner("user-a", "user-b", "user-a")

    def test_proprietaire_manquant_on_leve(self):
        with self.assertRaises(engine.OwnershipError):
            engine.assert_same_owner("user-a", None, "user-a")


if __name__ == "__main__":
    unittest.main()
