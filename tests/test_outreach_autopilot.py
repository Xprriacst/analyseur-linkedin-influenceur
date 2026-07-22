"""ALE-284 — Tests de la logique de l'autopilote de prospection.

Tout est pur : ni Supabase, ni Unipile, ni horloge réelle. Même raison que pour le
moteur d'envoi — ce module décide **qui** l'app va contacter au nom du client et
**quoi** elle va lui écrire sans qu'il clique. Ça doit être vérifiable d'un bloc.

Les cas couverts ici sont ceux qui font mal en production, pas les cas nominaux :
un lead non noté qu'on inviterait par erreur, un brouillon refusé qui reviendrait en
boucle, un template qui partirait avec « {{prenom}} » en clair, un réglage illisible
qui élargirait la cible au lieu de la restreindre.
"""
import unittest

from src import outreach_autopilot as autopilot


def account(**overrides):
    """Compte avec autopilote armé : leads verts, message IA, relecture demandée."""
    base = {
        "user_id": "user-a",
        "auto_prospection_enabled": True,
        "auto_invite_min_score": autopilot.GREEN_MIN_SCORE,
        "auto_invite_daily_cap": 15,
        "auto_message_mode": autopilot.MESSAGE_MODE_AI,
        "auto_message_template": None,
        "auto_message_requires_validation": True,
    }
    base.update(overrides)
    return base


def lead(lead_id="lead-1", *, score=90, status="none", contact="to_contact", **extra):
    base = {
        "id": lead_id,
        "user_id": "user-a",
        "score": score,
        "outreach_status": status,
        "contact_status": contact,
        "name": "Camille Durand",
        "headline": "Head of Growth",
    }
    base.update(extra)
    return base


class TierTest(unittest.TestCase):
    """Les paliers doivent coller aux pastilles déjà affichées dans la liste de leads."""

    def test_tier_boundaries(self):
        self.assertEqual(autopilot.tier_of(100), autopilot.TIER_GREEN)
        self.assertEqual(autopilot.tier_of(70), autopilot.TIER_GREEN)
        self.assertEqual(autopilot.tier_of(69), autopilot.TIER_ORANGE)
        self.assertEqual(autopilot.tier_of(40), autopilot.TIER_ORANGE)
        self.assertEqual(autopilot.tier_of(39), "red")
        self.assertEqual(autopilot.tier_of(0), "red")

    def test_unscored_lead_has_no_tier(self):
        self.assertIsNone(autopilot.tier_of(None))

    def test_tier_and_min_score_round_trip(self):
        """La pop-up et la base doivent parler de la même chose dans les deux sens."""
        for tier in (autopilot.TIER_GREEN, autopilot.TIER_ORANGE, autopilot.TIER_ALL):
            self.assertEqual(autopilot.tier_for_min_score(autopilot.min_score_for_tier(tier)), tier)

    def test_unknown_tier_falls_back_to_the_most_cautious(self):
        """Un palier illisible ne doit JAMAIS élargir la cible."""
        self.assertEqual(autopilot.min_score_for_tier("jaune"), autopilot.GREEN_MIN_SCORE)
        self.assertEqual(autopilot.min_score_for_tier(None), autopilot.GREEN_MIN_SCORE)


class SettingsTest(unittest.TestCase):
    def test_unknown_message_mode_falls_back_to_no_message(self):
        s = autopilot.settings_of(account(auto_message_mode="carrier-pigeon"))
        self.assertEqual(s.message_mode, autopilot.MESSAGE_MODE_NONE)
        self.assertFalse(s.sends_message)

    def test_template_mode_without_template_sends_no_message(self):
        """Sinon le moteur rejetterait des messages vides un par un, en silence."""
        s = autopilot.settings_of(account(auto_message_mode="template", auto_message_template="   "))
        self.assertEqual(s.message_mode, autopilot.MESSAGE_MODE_NONE)

    def test_missing_validation_flag_defaults_to_requiring_review(self):
        """L'absence de réglage ne doit jamais valoir « envoie sans me demander »."""
        s = autopilot.settings_of(account(auto_message_requires_validation=None))
        self.assertTrue(s.requires_validation)

    def test_empty_account_is_disabled(self):
        self.assertFalse(autopilot.settings_of({}).enabled)
        self.assertFalse(autopilot.settings_of(None).enabled)


class InviteCandidateTest(unittest.TestCase):
    def setUp(self):
        self.settings = autopilot.settings_of(account())

    def test_green_lead_is_invited(self):
        self.assertTrue(autopilot.is_invite_candidate(lead(score=85), self.settings))

    def test_lead_below_the_tier_is_not_invited(self):
        self.assertFalse(autopilot.is_invite_candidate(lead(score=55), self.settings))

    def test_unscored_lead_is_never_invited_even_when_targeting_everyone(self):
        """Sans score, on ne sait rien de son adéquation — l'inviter viderait le ciblage
        de son sens. Il reste invitable à la main."""
        loose = autopilot.settings_of(account(auto_invite_min_score=0))
        self.assertFalse(autopilot.is_invite_candidate(lead(score=None), loose))

    def test_manually_skipped_lead_is_never_touched(self):
        self.assertFalse(autopilot.is_invite_candidate(lead(contact="skip"), self.settings))

    def test_already_engaged_lead_is_not_re_invited(self):
        for status in ("invite_sent", "connected", "messaged"):
            self.assertFalse(autopilot.is_invite_candidate(lead(status=status), self.settings), status)


class PickInvitesTest(unittest.TestCase):
    def setUp(self):
        self.settings = autopilot.settings_of(account())

    def test_daily_cap_bites_on_the_weakest_leads(self):
        """Si le plafond mord, il doit mordre sur les moins bons, jamais sur les meilleurs."""
        leads = [lead("a", score=72), lead("b", score=95), lead("c", score=80)]
        picked = autopilot.pick_invites(leads, self.settings, remaining_cap=2)
        self.assertEqual([l["id"] for l in picked], ["b", "c"])

    def test_leads_already_seen_by_the_queue_are_never_re_proposed(self):
        """Une invitation annulée par le client ne doit pas revenir au passage suivant."""
        leads = [lead("a", score=90), lead("b", score=88)]
        picked = autopilot.pick_invites(leads, self.settings, known_lead_ids=["a"], remaining_cap=10)
        self.assertEqual([l["id"] for l in picked], ["b"])

    def test_nothing_is_picked_without_opt_in(self):
        off = autopilot.settings_of(account(auto_prospection_enabled=False))
        self.assertEqual(autopilot.pick_invites([lead()], off, remaining_cap=10), [])

    def test_exhausted_cap_picks_nothing(self):
        self.assertEqual(autopilot.pick_invites([lead()], self.settings, remaining_cap=0), [])


class PickMessagesTest(unittest.TestCase):
    def test_connected_lead_gets_a_message(self):
        settings = autopilot.settings_of(account())
        picked = autopilot.pick_messages([lead(status="connected")], settings)
        self.assertEqual(len(picked), 1)

    def test_no_message_when_the_client_chose_invitation_only(self):
        settings = autopilot.settings_of(account(auto_message_mode="none"))
        self.assertEqual(autopilot.pick_messages([lead(status="connected")], settings), [])

    def test_lead_still_awaiting_acceptance_gets_no_message(self):
        settings = autopilot.settings_of(account())
        self.assertEqual(autopilot.pick_messages([lead(status="invite_sent")], settings), [])

    def test_refused_draft_does_not_come_back(self):
        """`known_lead_ids` couvre TOUS les statuts, y compris `canceled` : sans ça, le
        « non » du client ne vaudrait rien et le brouillon reviendrait en boucle."""
        settings = autopilot.settings_of(account())
        leads = [lead("a", status="connected")]
        self.assertEqual(autopilot.pick_messages(leads, settings, known_lead_ids=["a"]), [])

    def test_out_of_tier_lead_invited_by_hand_gets_no_auto_message(self):
        """Le client a choisi à qui son autopilote écrit — un lead hors palier ne doit
        pas récupérer un message automatique par la bande."""
        settings = autopilot.settings_of(account())
        self.assertEqual(autopilot.pick_messages([lead(score=20, status="connected")], settings), [])


class TemplateTest(unittest.TestCase):
    def test_variables_are_substituted(self):
        text = autopilot.render_template("Bonjour {{prenom}}, vu ton poste de {{titre}}.", lead())
        self.assertEqual(text, "Bonjour Camille, vu ton poste de Head of Growth.")

    def test_case_and_spacing_are_tolerated(self):
        self.assertEqual(autopilot.render_template("Salut {{ Prenom }} !", lead()), "Salut Camille !")

    def test_missing_value_never_leaks_the_placeholder(self):
        """Le pire cas : « Bonjour {{prenom}}, » qui part tel quel chez le prospect."""
        text = autopilot.render_template("Bonjour {{prenom}}, ravi d'échanger.", lead(name=None))
        self.assertNotIn("{{", text)
        self.assertNotIn("None", text)
        self.assertEqual(text, "Bonjour, ravi d'échanger.")

    def test_unknown_variable_is_dropped_not_printed(self):
        text = autopilot.render_template("Salut {{entreprise}}fin", lead())
        self.assertNotIn("{{", text)

    def test_output_is_capped_to_the_send_limit(self):
        text = autopilot.render_template("x" * 5000, lead())
        self.assertLessEqual(len(text), autopilot.MESSAGE_MAX_CHARS)

    def test_blank_template_is_rejected(self):
        self.assertFalse(autopilot.template_is_usable("   \n "))
        self.assertTrue(autopilot.template_is_usable("Bonjour"))


class QueueStatusTest(unittest.TestCase):
    """La garantie centrale du lot : un message à relire est INENVOYABLE, pas juste
    « pas encore envoyé ». Le moteur ne lit que le statut `pending`."""

    def test_validation_requested_produces_a_draft(self):
        settings = autopilot.settings_of(account(auto_message_requires_validation=True))
        self.assertEqual(autopilot.message_queue_status(settings), "draft")

    def test_validation_waived_produces_a_queued_action(self):
        settings = autopilot.settings_of(account(auto_message_requires_validation=False))
        self.assertEqual(autopilot.message_queue_status(settings), "pending")

    def test_message_delay_stays_within_bounds(self):
        """Écrire trois minutes après l'acceptation est un signal de robot."""
        for _ in range(50):
            delay = autopilot.pick_message_delay()
            self.assertGreaterEqual(delay.total_seconds(), autopilot.MIN_MESSAGE_DELAY_HOURS * 3600)
            self.assertLessEqual(delay.total_seconds(), autopilot.MAX_MESSAGE_DELAY_HOURS * 3600)


class SequenceStepsTest(unittest.TestCase):
    """Le schéma affiché à côté du bouton doit décrire ce que le cron fera vraiment."""

    def test_invitation_only_greys_out_both_message_steps(self):
        steps = autopilot.sequence_steps(autopilot.settings_of(account(auto_message_mode="none")))
        by_key = {s["key"]: s for s in steps}
        self.assertTrue(by_key["invite"]["active"])
        self.assertFalse(by_key["compose"]["active"])
        self.assertFalse(by_key["send"]["active"])

    def test_review_mode_marks_the_send_step_as_awaiting_the_user(self):
        steps = autopilot.sequence_steps(autopilot.settings_of(account()))
        send = {s["key"]: s for s in steps}["send"]
        self.assertTrue(send["active"])
        self.assertTrue(send["awaits_user"])

    def test_full_auto_mode_does_not_await_the_user(self):
        settings = autopilot.settings_of(account(auto_message_requires_validation=False))
        send = {s["key"]: s for s in autopilot.sequence_steps(settings)}["send"]
        self.assertTrue(send["active"])
        self.assertFalse(send["awaits_user"])

    def test_everything_is_greyed_out_when_the_autopilot_is_off(self):
        steps = autopilot.sequence_steps(autopilot.settings_of(account(auto_prospection_enabled=False)))
        self.assertTrue(all(not s["active"] for s in steps))

    def test_tier_is_spelled_out_in_the_first_step(self):
        steps = autopilot.sequence_steps(autopilot.settings_of(account(auto_invite_min_score=0)))
        self.assertIn("tous les leads", steps[0]["detail"])


if __name__ == "__main__":
    unittest.main()
