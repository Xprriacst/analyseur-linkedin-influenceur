"""Tests unitaires — composition du plan Mode Pilote."""
import unittest

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


class ComposePlanTest(unittest.TestCase):
    def test_empty_post_and_contacts(self):
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
        )
        self.assertTrue(out["meta"]["post_empty"])
        self.assertEqual(out["plan"]["contacts"], [])
        self.assertIn("Connecte ton compte", out["meta"]["contacts_blocked_reason"] or "")

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


if __name__ == "__main__":
    unittest.main()
