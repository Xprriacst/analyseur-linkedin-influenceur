"""Tests unitaires — composition du plan Mode Pilote."""
import unittest
from unittest.mock import patch

from src import pilot_plan as pp


def _lead(**kwargs):
    base = {
        "id": "l1",
        "name": "Marie Dupont",
        "headline": "Fondatrice · TalentFlow",
        "score": 80,
        "contact_status": None,
        "outreach_status": "none",
        "comment_text": "Super post, merci pour le partage",
    }
    base.update(kwargs)
    return base


class LeadInvitableTest(unittest.TestCase):
    def test_green_lead_ok(self):
        self.assertTrue(pp.lead_invitable(_lead(score=72)))

    def test_orange_lead_ok(self):
        self.assertTrue(pp.lead_invitable(_lead(score=55)))

    def test_red_rejected(self):
        self.assertFalse(pp.lead_invitable(_lead(score=30)))

    def test_unscored_rejected(self):
        self.assertFalse(pp.lead_invitable(_lead(score=None)))

    def test_skip_rejected(self):
        self.assertFalse(pp.lead_invitable(_lead(contact_status="skip")))

    def test_invite_sent_rejected(self):
        self.assertFalse(pp.lead_invitable(_lead(outreach_status="invite_sent")))

    def test_connected_rejected(self):
        self.assertFalse(pp.lead_invitable(_lead(outreach_status="connected")))


def _pool_lead(**kwargs):
    now = kwargs.pop("created_at", "2026-09-02T09:00:00Z")
    base = _lead(
        score=75,
        comment_text="",
        created_at=now,
        signals=[{"origin": "prospect_pool"}],
    )
    base.update(kwargs)
    return base


class PickContactsTest(unittest.TestCase):
    def test_max_three(self):
        leads = [_lead(id=f"l{i}", score=70 + i) for i in range(10)]
        picked = pp.pick_contacts(leads, limit=3)
        self.assertEqual(len(picked), 3)

    def test_skips_unscored_and_contacted(self):
        leads = [
            _lead(id="a", score=None),
            _lead(id="b", outreach_status="invite_sent", score=90),
            _lead(id="c", score=85),
            _lead(id="d", score=75),
            _lead(id="e", score=65),
            _lead(id="f", score=95),
        ]
        picked = pp.pick_contacts(leads, limit=3)
        self.assertEqual([p["id"] for p in picked], ["c", "d", "e"])

    def test_empty_when_none_eligible(self):
        self.assertEqual(pp.pick_contacts([_lead(score=10)]), [])

    def test_unconnected_caps_at_one_even_if_pool_is_full(self):
        now = pp.datetime.datetime(2026, 9, 2, 12, 0, tzinfo=pp.datetime.timezone.utc)
        leads = [
            _pool_lead(id=f"p{i}", name=f"Prospect {i}", created_at="2026-09-02T08:00:00Z")
            for i in range(8)
        ]
        picked = pp.pick_contacts(leads, outreach_connected=False, now=now)
        self.assertEqual(len(picked), 1)
        self.assertEqual(picked[0]["id"], "p0")

    def test_unconnected_prefers_today_pool_over_other_invitables(self):
        now = pp.datetime.datetime(2026, 9, 2, 12, 0, tzinfo=pp.datetime.timezone.utc)
        leads = [
            _lead(id="import-1", name="Importé", score=90),
            _pool_lead(id="yesterday", name="Hier", created_at="2026-09-01T10:00:00Z"),
            _pool_lead(id="today", name="Léa Moreau", created_at="2026-09-02T08:00:00Z"),
        ]
        picked = pp.pick_contacts(leads, outreach_connected=False, now=now)
        self.assertEqual([p["id"] for p in picked], ["today"])

    def test_connected_still_shows_three(self):
        now = pp.datetime.datetime(2026, 9, 2, 12, 0, tzinfo=pp.datetime.timezone.utc)
        leads = [
            _pool_lead(id=f"p{i}", created_at="2026-09-02T08:00:00Z")
            for i in range(5)
        ]
        picked = pp.pick_contacts(leads, outreach_connected=True, now=now)
        self.assertEqual(len(picked), 3)


class ComposePlanTest(unittest.TestCase):
    def test_empty_post_shows_searching_agent_when_not_simulating(self):
        """Sans simulation : pas de noms fictifs, mais l'agent cherche — pas un vide silencieux."""
        created = pp.datetime.datetime.now(pp.datetime.timezone.utc) - pp.datetime.timedelta(minutes=5)
        out = pp.compose_pilot_plan(
            profile={"display_name": "Alex"},
            targeting={"ideal_client": "SaaS B2B"},
            generated_posts=[],
            daily_ideas=[],
            leads=[],
            library=[],
            followed_handles=set(),
            schedule=[],
            outreach_connected=False,
            publish_connected=False,
            weekly_done=0,
            weekly_total=3,
            is_pilote_landing=False,
            account_created_at=created,
        )
        self.assertTrue(out["meta"]["post_empty"])
        self.assertIn("Connecte ton compte", out["meta"]["contacts_blocked_reason"] or "")
        agent = out["meta"]["prospect_agent"]
        self.assertTrue(agent["active"])
        self.assertIn("cherche des prospects", agent["message"] or "")
        self.assertIn("Un profil par jour", agent["detail"] or "")
        self.assertEqual(out["plan"]["contacts"], [])

    def test_simulation_disabled_shows_agent_not_empty_column(self):
        out = pp.compose_pilot_plan(
            profile={"display_name": "Alex"},
            targeting=None,
            generated_posts=[],
            daily_ideas=[],
            leads=[],
            library=[],
            followed_handles=set(),
            schedule=[],
            outreach_connected=False,
            publish_connected=False,
            weekly_done=0,
            weekly_total=3,
            simulate_prospects=False,
        )
        self.assertEqual(out["plan"]["contacts"], [])
        self.assertTrue(out["meta"]["prospect_agent"]["active"])
        self.assertIn("Connecte ton compte", out["meta"]["contacts_blocked_reason"] or "")

    def test_pilote_landing_shows_agent_not_connect_message(self):
        out = pp.compose_pilot_plan(
            profile={"display_name": "Alex"},
            targeting={"ideal_client": "SaaS B2B"},
            generated_posts=[],
            daily_ideas=[],
            leads=[],
            library=[],
            followed_handles=set(),
            schedule=[],
            outreach_connected=False,
            publish_connected=False,
            weekly_done=0,
            weekly_total=3,
            is_pilote_landing=True,
            simulate_prospects=True,
            account_created_at=pp.datetime.datetime.now(pp.datetime.timezone.utc),
        )
        self.assertIsNone(out["meta"]["contacts_blocked_reason"])
        agent = out["meta"]["prospect_agent"]
        self.assertTrue(agent["active"])
        self.assertIn("agent IA", agent["message"] or "")

    def test_pilote_simulated_contacts_reveal(self):
        created = pp.datetime.datetime.now(pp.datetime.timezone.utc) - pp.datetime.timedelta(minutes=5)
        out = pp.compose_pilot_plan(
            profile={"display_name": "Alex"},
            targeting={"ideal_client": "SaaS"},
            generated_posts=[],
            daily_ideas=[],
            leads=[],
            library=[],
            followed_handles=set(),
            schedule=[],
            outreach_connected=False,
            publish_connected=False,
            weekly_done=0,
            weekly_total=3,
            is_pilote_landing=True,
            simulate_prospects=True,
            account_created_at=created,
        )
        self.assertEqual(len(out["plan"]["contacts"]), 2)
        self.assertTrue(all(c["simulated"] for c in out["plan"]["contacts"]))

    def test_simulated_reveal_count_timing(self):
        now = pp.datetime.datetime.now(pp.datetime.timezone.utc)
        self.assertEqual(pp.simulated_prospect_reveal_count(now), 0)
        self.assertEqual(
            pp.simulated_prospect_reveal_count(now - pp.datetime.timedelta(minutes=2)),
            1,
        )
        self.assertEqual(
            pp.simulated_prospect_reveal_count(now - pp.datetime.timedelta(minutes=10)),
            3,
        )

    def test_generated_post_preferred(self):
        out = pp.compose_pilot_plan(
            profile={"display_name": "Alex"},
            targeting={"ideal_client": "SaaS"},
            generated_posts=[{
                "id": "gp1",
                "platform": "linkedin",
                "post": "Hook accrocheur.\n\nCorps du post.",
                "hook_type": "Histoire",
            }],
            daily_ideas=[{"id": "d1", "idea_markdown": "Idée", "idea_date": "2026-08-31"}],
            leads=[_lead()],
            library=[],
            followed_handles=set(),
            schedule=[{"day_of_week": 1, "hour": 9}],
            outreach_connected=True,
            publish_connected=True,
            weekly_done=1,
            weekly_total=3,
        )
        self.assertEqual(out["meta"]["post_source"], "generated")
        self.assertEqual(out["meta"]["post_id"], "gp1")
        self.assertEqual(out["plan"]["post"]["hook"], "Hook accrocheur.")
        self.assertEqual(len(out["plan"]["contacts"]), 1)

    def test_follow_excludes_already_followed(self):
        library = [{
            "influencer_id": "inf1",
            "handle": "romain",
            "name": "Romain",
            "headline": "SaaS",
        }]
        out = pp.compose_pilot_plan(
            profile={},
            targeting=None,
            generated_posts=[],
            daily_ideas=[],
            leads=[],
            library=library,
            followed_handles={"romain"},
            schedule=[],
            outreach_connected=True,
            publish_connected=False,
            weekly_done=0,
            weekly_total=3,
        )
        self.assertEqual(out["plan"]["followProfiles"], [])


class WeeklyFrequencyTest(unittest.TestCase):
    """⚠️ Le rythme annoncé doit refléter l'idée du jour, sinon un compte neuf
    (aucun créneau hebdo) lit « Aucun créneau programmé » alors qu'un post lui
    est écrit chaque matin — un rythme réel présenté comme une absence."""

    def test_no_slot_no_daily_says_nothing_scheduled(self):
        self.assertIn("Aucun créneau", pp.format_weekly_frequency([]))

    def test_no_slot_but_daily_announces_the_daily_post(self):
        out = pp.format_weekly_frequency([], daily_ideas_enabled=True)
        self.assertEqual(out, pp.DAILY_POST_LABEL)
        self.assertNotIn("Aucun créneau", out)

    def test_slots_alone_keep_the_weekly_wording(self):
        out = pp.format_weekly_frequency([{"day_of_week": 0, "hour": 9}])
        self.assertEqual(out, "1 posts / semaine · lun 9h")

    def test_slots_and_daily_mention_both(self):
        out = pp.format_weekly_frequency(
            [{"day_of_week": 2, "hour": 8}], daily_ideas_enabled=True
        )
        self.assertIn("1 post par jour", out)
        self.assertIn("mer 8h", out)

    def test_unparsable_slot_falls_back_on_the_daily_post(self):
        # Un créneau illisible ne doit pas effacer le rythme réel du client.
        out = pp.format_weekly_frequency(
            [{"day_of_week": "?", "hour": None}], daily_ideas_enabled=True
        )
        self.assertEqual(out, pp.DAILY_POST_LABEL)


class BuildStrategyTest(unittest.TestCase):
    def test_uses_targeting_then_profile(self):
        out = pp.build_strategy(
            {"target_audience": "Coachs", "core_offer": "Formation"},
            {"ideal_client": "Dirigeants de PME", "offer": "Audit IA"},
            [],
        )
        self.assertEqual(out["target"], "Dirigeants de PME · Audit IA")

    def test_empty_profile_says_what_to_do(self):
        out = pp.build_strategy(None, None, [])
        self.assertIn("Complète ton ciblage", out["target"])
        self.assertTrue(out["structureHint"])

    def test_keeps_at_most_three_handles(self):
        out = pp.build_strategy(None, None, [], ["a", "b", "c", "d"])
        self.assertEqual(out["profiles"], ["a", "b", "c"])

    def test_daily_flag_reaches_the_frequency(self):
        out = pp.build_strategy(None, None, [], daily_ideas_enabled=True)
        self.assertEqual(out["frequency"], pp.DAILY_POST_LABEL)


class PlanStrategyMirrorsProfileFlagTest(unittest.TestCase):
    """La stratégie du plan du jour lit l'opt-in sur la ligne de profil
    (`select("*")`) — pas un paramètre séparé qu'on oublierait de passer."""

    def _plan(self, profile):
        return pp.compose_pilot_plan(
            profile=profile,
            targeting=None,
            generated_posts=[],
            daily_ideas=[],
            leads=[],
            library=[],
            followed_handles=set(),
            schedule=[],
            outreach_connected=False,
            publish_connected=False,
            weekly_done=0,
            weekly_total=3,
        )["plan"]["strategy"]

    def test_daily_enabled_profile(self):
        self.assertEqual(
            self._plan({"daily_ideas_enabled": True})["frequency"], pp.DAILY_POST_LABEL
        )

    def test_daily_disabled_profile(self):
        self.assertIn("Aucun créneau", self._plan({"daily_ideas_enabled": False})["frequency"])


class BuildPilotStrategyTest(unittest.TestCase):
    """`GET /me/pilot/strategy` — appelé pendant la révélation de fin
    d'onboarding. Il ne doit JAMAIS lever : l'écran qui le porte est le dernier
    d'un tunnel, une exception y enfermerait le client dehors."""

    def test_reads_profile_targeting_and_schedule(self):
        with patch.object(pp.db, "get_editorial_profile", return_value={"daily_ideas_enabled": True}), \
             patch.object(pp.db, "get_lead_targeting", return_value={"ideal_client": "Coachs"}), \
             patch.object(pp.db, "get_weekly_schedule", return_value=[]):
            out = pp.build_pilot_strategy("tok")
        self.assertEqual(out["target"], "Coachs")
        self.assertEqual(out["frequency"], pp.DAILY_POST_LABEL)

    def test_supabase_down_returns_the_generic_strategy(self):
        with patch.object(pp.db, "get_editorial_profile", side_effect=RuntimeError("boom")):
            out = pp.build_pilot_strategy("tok")
        self.assertIn("Complète ton ciblage", out["target"])
        self.assertIn("frequency", out)
        self.assertIn("structureHint", out)


class ContactOpenerTest(unittest.TestCase):
    def test_invite_preview_wins_over_the_bateau_template(self):
        lead = _lead(
            comment_text="",
            invite_preview="Charlie, inventory still a Sunday-night job?",
        )
        self.assertEqual(
            pp.contact_opener(lead, {"offer": "IA"}),
            "Charlie, inventory still a Sunday-night job?",
        )

    def test_compose_uses_stored_preview_on_the_card(self):
        out = pp.compose_pilot_plan(
            profile={"display_name": "Alex"},
            targeting={"offer": "IA pharmacie"},
            generated_posts=[],
            daily_ideas=[],
            leads=[_lead(comment_text="", invite_preview="Léa, tu valides encore les commandes à la main ?")],
            library=[],
            followed_handles=set(),
            schedule=[],
            outreach_connected=True,
            publish_connected=True,
            weekly_done=0,
            weekly_total=3,
        )
        self.assertEqual(
            out["plan"]["contacts"][0]["message"],
            "Léa, tu valides encore les commandes à la main ?",
        )


class PoolContactIsRealTest(unittest.TestCase):
    def test_pool_lead_is_not_a_simulated_name(self):
        """Un prospect du vivier est une vraie carte : pas de badge simulé, invite bloquée sans LinkedIn."""
        out = pp.compose_pilot_plan(
            profile={"display_name": "Alex"},
            targeting={"ideal_client": "pharmaciens"},
            generated_posts=[],
            daily_ideas=[],
            leads=[_lead(
                id="pool-1",
                name="Léa Moreau",
                headline="Pharmacienne titulaire · Officine",
                score=75,
                comment_text="",
            )],
            library=[],
            followed_handles=set(),
            schedule=[],
            outreach_connected=False,
            publish_connected=False,
            weekly_done=0,
            weekly_total=3,
            simulate_prospects=False,
        )
        contact = out["plan"]["contacts"][0]
        self.assertEqual(contact["name"], "Léa Moreau")
        self.assertFalse(contact["simulated"])
        self.assertNotIn(contact["name"], {"Camille Martin", "Thomas Leroy", "Sarah Benali"})
        self.assertIn("Connecte", out["meta"]["contacts_blocked_reason"] or "")
        self.assertFalse(out["meta"]["prospect_agent"]["active"])

    def test_simulation_off_never_fills_with_fake_names(self):
        out = pp.compose_pilot_plan(
            profile={"display_name": "Alex"},
            targeting={"ideal_client": "pharmaciens"},
            generated_posts=[],
            daily_ideas=[],
            leads=[],
            library=[],
            followed_handles=set(),
            schedule=[],
            outreach_connected=False,
            publish_connected=False,
            weekly_done=0,
            weekly_total=3,
            simulate_prospects=False,
        )
        self.assertEqual(out["plan"]["contacts"], [])
        self.assertTrue(out["meta"]["prospect_agent"]["active"])
        self.assertNotIn("Camille Martin", str(out))

    def test_unconnected_compose_shows_one_even_if_many_pool_leads(self):
        now = pp.datetime.datetime(2026, 9, 2, 12, 0, tzinfo=pp.datetime.timezone.utc)
        leads = [
            _pool_lead(
                id=f"p{i}",
                name=f"Prospect {i}",
                headline="Pharmacien titulaire",
                created_at="2026-09-02T08:00:00Z",
            )
            for i in range(6)
        ]
        out = pp.compose_pilot_plan(
            profile={"display_name": "Alex"},
            targeting={"ideal_client": "pharmaciens"},
            generated_posts=[],
            daily_ideas=[],
            leads=leads,
            library=[],
            followed_handles=set(),
            schedule=[],
            outreach_connected=False,
            publish_connected=False,
            weekly_done=0,
            weekly_total=3,
            simulate_prospects=False,
            now=now,
        )
        self.assertEqual(len(out["plan"]["contacts"]), 1)
        self.assertEqual(out["plan"]["contacts"][0]["name"], "Prospect 0")


class BuildPilotTodayPoolGateTest(unittest.TestCase):
    def _run(self, *, outreach_connected: bool, assign):
        from contextlib import ExitStack

        account = {"unipile_account_id": "acc-1"} if outreach_connected else None
        patches = [
            patch.object(pp.db, "get_user", return_value={"id": "u1", "user_metadata": {}, "created_at": None}),
            patch.object(pp.db, "get_editorial_profile", return_value={"industry": "pharmacie"}),
            patch.object(pp.db, "get_lead_targeting", return_value={"ideal_client": "titulaires"}),
            patch.object(pp.db, "list_generated_posts", return_value=[]),
            patch.object(pp.db, "list_daily_ideas", return_value=[]),
            patch.object(pp.db, "list_leads", return_value=[]),
            patch.object(pp.db, "list_influencer_library", return_value=[]),
            patch.object(pp.db, "list_followed_influencers", return_value=[]),
            patch.object(pp.db, "get_weekly_schedule", return_value=[]),
            patch.object(pp.db, "get_linkedin_outreach_account", return_value=account),
            patch.object(pp, "maybe_bootstrap_daily_idea"),
            patch.object(pp, "fill_invite_previews"),
            patch.object(pp, "weekly_progress", return_value=(0, 3)),
            patch.object(pp.prospect_pool, "maybe_assign_one", side_effect=assign),
        ]
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            return pp.build_pilot_today("tok")

    def test_assigns_from_pool_when_linkedin_is_not_connected(self):
        calls = {"n": 0}

        def assign(*_a, **_k):
            calls["n"] += 1
            return None

        self._run(outreach_connected=False, assign=assign)
        self.assertEqual(calls["n"], 1)

    def test_does_not_touch_pool_when_linkedin_is_connected(self):
        calls = {"n": 0}

        def assign(*_a, **_k):
            calls["n"] += 1
            return {"id": "x"}

        self._run(outreach_connected=True, assign=assign)
        self.assertEqual(calls["n"], 0)


if __name__ == "__main__":
    unittest.main()
