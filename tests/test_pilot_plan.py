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

    def test_cross_user_suggestions_fill_empty_library(self):
        """Un compte tout juste sorti de l'onboarding : bibliothèque perso vide,
        mais un profil éditorial et un ciblage ICP renseignés — les suggestions
        cross-user doivent combler la section, pas la laisser vide."""
        out = pp.compose_pilot_plan(
            profile={"industry": "coaching business indépendants"},
            targeting={"ideal_client": "consultants freelances"},
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
            cross_user_candidates=[
                {"id": "c1", "handle": "marie-coach", "name": "Marie", "headline": "Coach business pour indépendants", "follower_count": 5000},
                {"id": "c2", "handle": "bob-photo", "name": "Bob", "headline": "Photographe animalier", "follower_count": 50000},
            ],
        )
        handles = [f["influencer_handle"] for f in out["plan"]["followProfiles"]]
        self.assertIn("marie-coach", handles)
        self.assertNotIn("bob-photo", handles)


class ExtractNicheKeywordsTest(unittest.TestCase):
    def test_pulls_from_profile_and_targeting(self):
        keywords = pp.extract_niche_keywords(
            {"industry": "coaching business", "target_audience": "indépendants"},
            {"ideal_client": "consultants freelances", "interest_keywords": ["automatisation", "b2b"]},
        )
        self.assertIn("coaching", keywords)
        self.assertIn("automatisation", keywords)
        self.assertIn("consultants", keywords)

    def test_empty_when_nothing_filled(self):
        self.assertEqual(pp.extract_niche_keywords(None, None), [])
        self.assertEqual(pp.extract_niche_keywords({}, {}), [])

    def test_stopwords_and_short_words_dropped(self):
        keywords = pp.extract_niche_keywords({"business_description": "pour vous et avec sans plus tout"}, None)
        self.assertEqual(keywords, [])

    def test_deduplicates(self):
        keywords = pp.extract_niche_keywords(
            {"industry": "coaching", "business_description": "coaching pour dirigeants"}, None,
        )
        self.assertEqual(keywords.count("coaching"), 1)


class PickCrossUserFollowProfilesTest(unittest.TestCase):
    def _candidates(self):
        return [
            {"id": "c1", "handle": "marie", "name": "Marie", "headline": "Coaching business B2B", "follower_count": 1000},
            {"id": "c2", "handle": "leo", "name": "Léo", "headline": "Coaching business et vente B2B", "follower_count": 200},
            {"id": "c3", "handle": "sam", "name": "Sam", "headline": "Jardinier paysagiste", "follower_count": 999999},
        ]

    def test_no_keywords_no_suggestions(self):
        self.assertEqual(pp.pick_cross_user_follow_profiles(self._candidates(), [], set(), 5), [])

    def test_ranks_by_keyword_hits_then_followers(self):
        rows = pp.pick_cross_user_follow_profiles(self._candidates(), ["coaching", "business"], set(), 5)
        handles = [r["influencer_handle"] for r in rows]
        # "leo" matche coaching+business+plus large intitulé -> devant "marie" à hits égaux ? on vérifie surtout
        # l'exclusion du profil hors-sujet malgré son gros score d'abonnés.
        self.assertNotIn("sam", handles)
        self.assertIn("marie", handles)
        self.assertIn("leo", handles)

    def test_excluded_handles_are_skipped(self):
        rows = pp.pick_cross_user_follow_profiles(
            self._candidates(), ["coaching"], {"marie"}, 5,
        )
        handles = [r["influencer_handle"] for r in rows]
        self.assertNotIn("marie", handles)
        self.assertIn("leo", handles)

    def test_limit_respected(self):
        rows = pp.pick_cross_user_follow_profiles(self._candidates(), ["coaching"], set(), 1)
        self.assertEqual(len(rows), 1)

    def test_own_handle_excluded_via_pick_follow_suggestions(self):
        rows = pp.pick_follow_suggestions(
            library=[],
            followed_handles=set(),
            cross_user_candidates=self._candidates(),
            niche_keywords=["coaching", "business"],
            own_handle="marie",
        )
        handles = [r["influencer_handle"] for r in rows]
        self.assertNotIn("marie", handles)


if __name__ == "__main__":
    unittest.main()
