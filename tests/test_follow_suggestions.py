"""Tests unitaires — suggestions de profils à suivre (matching niche/ICP).

Ticket Notion « Onboarding — propositions automatiques de profils LinkedIn à
suivre ». Ce que ces tests verrouillent, dans l'ordre d'importance :

1. **Un profil vide ne suggère RIEN.** C'est la garantie produit : mieux vaut
   une section absente qu'une liste de profils sans rapport avec le métier du
   client, qui décrédibiliserait toutes les recommandations de l'app.
2. **Le score de niche prime sur le nombre d'abonnés.** Sans ce test, un
   refacto du tri suggérerait les mêmes grosses célébrités LinkedIn à tout le
   monde, ce qui a l'air normal à l'écran et ne lève aucune erreur.
3. **Pas de faux positif de sous-chaîne** (« vente » ne matche pas
   « inventaire ») **mais les dérivés passent** (« coach » matche
   « coaching ») — le pluriel et les dérivés sont le cas normal sur une fiche.
4. **Aucun appel réseau, aucun crédit** : tout est testable sans base ni
   modèle, c'est bien la preuve qu'il n'y a ni IA ni Apify dans ce chemin.
"""
import unittest
from unittest.mock import patch

from src import follow_suggestions as fs


class ExtractNicheKeywordsTest(unittest.TestCase):
    def test_pulls_from_profile_and_targeting(self):
        keywords = fs.extract_niche_keywords(
            {"industry": "coaching business", "target_audience": "indépendants"},
            {"ideal_client": "consultants freelances", "interest_keywords": ["automatisation", "b2b"]},
        )
        for expected in ("coaching", "business", "indépendants", "consultants", "automatisation"):
            self.assertIn(expected, keywords)

    def test_empty_when_nothing_filled(self):
        """Le cas d'un compte qui vient de s'inscrire : la section doit disparaître."""
        self.assertEqual(fs.extract_niche_keywords(None, None), [])
        self.assertEqual(fs.extract_niche_keywords({}, {}), [])
        self.assertEqual(fs.extract_niche_keywords({"industry": "   "}, {"offer": ""}), [])

    def test_stopwords_and_short_words_dropped(self):
        self.assertEqual(
            fs.extract_niche_keywords({"business_description": "pour vous et avec sans plus tout"}, None),
            [],
        )

    def test_form_fields_are_not_read(self):
        """`tone`/`topics_to_avoid` décrivent la FORME, pas le secteur : les lire
        ferait matcher des profils sur « bienveillant » ou « jargon »."""
        keywords = fs.extract_niche_keywords(
            {"tone": "bienveillant", "topics_to_avoid": "politique", "constraints": "jargon"},
            None,
        )
        self.assertEqual(keywords, [])

    def test_deduplicates_and_respects_max(self):
        keywords = fs.extract_niche_keywords(
            {"industry": "coaching", "business_description": "coaching pour dirigeants"}, None,
        )
        self.assertEqual(keywords.count("coaching"), 1)
        long_text = " ".join(f"motcle{i}" for i in range(80))
        self.assertEqual(len(fs.extract_niche_keywords({"industry": long_text}, None, max_keywords=10)), 10)

    def test_string_interest_keywords_accepted(self):
        """`interest_keywords` est un jsonb : selon le chemin d'écriture il peut
        arriver en chaîne plutôt qu'en liste — ne pas le perdre en silence."""
        self.assertIn("automatisation", fs.extract_niche_keywords(None, {"interest_keywords": "automatisation"}))


class HandleFromProfileUrlTest(unittest.TestCase):
    def test_extracts_and_decodes(self):
        self.assertEqual(
            fs.handle_from_profile_url("https://www.linkedin.com/in/th%C3%A9ophile-dupont/?trk=x"),
            "théophile-dupont",
        )
        self.assertEqual(fs.handle_from_profile_url("linkedin.com/in/marie"), "marie")

    def test_empty_input(self):
        self.assertEqual(fs.handle_from_profile_url(None), "")
        self.assertEqual(fs.handle_from_profile_url("   "), "")


def _candidates():
    return [
        {"handle": "marie", "name": "Marie", "headline": "Coaching business B2B", "follower_count": 1000},
        {"handle": "leo", "name": "Léo", "headline": "Coach business, vente et closing", "follower_count": 200},
        {"handle": "sam", "name": "Sam", "headline": "Jardinier paysagiste", "follower_count": 999999},
    ]


class RankSuggestionsTest(unittest.TestCase):
    def test_no_keywords_no_suggestions(self):
        self.assertEqual(fs.rank_suggestions(_candidates(), [], set()), [])

    def test_off_topic_profile_never_suggested(self):
        rows = fs.rank_suggestions(_candidates(), ["coaching", "business"], set())
        handles = [r["handle"] for r in rows]
        self.assertNotIn("sam", handles)
        self.assertIn("marie", handles)

    def test_niche_score_beats_follower_count(self):
        """Le gros compte matche UN mot-clé, le petit en matche deux : c'est le
        petit qui doit passer devant."""
        rows = fs.rank_suggestions(
            [
                {"handle": "gros", "name": "Gros", "headline": "Coaching", "follower_count": 500_000},
                {"handle": "petit", "name": "Petit", "headline": "Coaching pour indépendants", "follower_count": 80},
            ],
            ["coaching", "indépendants"],
            set(),
        )
        self.assertEqual([r["handle"] for r in rows], ["petit", "gros"])

    def test_followers_only_break_ties(self):
        rows = fs.rank_suggestions(
            [
                {"handle": "a", "name": "A", "headline": "Coaching", "follower_count": 10},
                {"handle": "b", "name": "B", "headline": "Coaching", "follower_count": 900},
            ],
            ["coaching"],
            set(),
        )
        self.assertEqual([r["handle"] for r in rows], ["b", "a"])

    def test_prefix_match_not_substring(self):
        """« vente » ne doit pas matcher « inventaire » (faux positif silencieux),
        mais « coach » doit matcher « coaching » (dérivé, cas normal)."""
        rows = fs.rank_suggestions(
            [
                {"handle": "faux", "name": "Faux", "headline": "Gestion d'inventaire", "follower_count": 10},
                {"handle": "vrai", "name": "Vrai", "headline": "Coaching d'équipe", "follower_count": 10},
            ],
            ["vente", "coach"],
            set(),
        )
        self.assertEqual([r["handle"] for r in rows], ["vrai"])

    def test_excluded_handles_are_skipped_case_insensitively(self):
        rows = fs.rank_suggestions(_candidates(), ["coaching", "coach"], {"MARIE"})
        self.assertNotIn("marie", [r["handle"] for r in rows])

    def test_limit_respected(self):
        self.assertEqual(len(fs.rank_suggestions(_candidates(), ["coach"], set(), limit=1)), 1)
        self.assertEqual(fs.rank_suggestions(_candidates(), ["coach"], set(), limit=0), [])

    def test_encoded_handle_decoded_and_url_kept_encoded(self):
        """Le handle sert au suivi (format décodé, comme `followed_influencers`)
        alors que l'URL doit rester dans sa forme encodée, sinon le lien casse."""
        rows = fs.rank_suggestions(
            [{"handle": "th%C3%A9o", "name": "Théo", "headline": "Coaching", "follower_count": 1}],
            ["coaching"],
            set(),
        )
        self.assertEqual(rows[0]["handle"], "théo")
        self.assertEqual(rows[0]["profile_url"], "https://www.linkedin.com/in/th%C3%A9o/")

    def test_duplicate_handles_collapsed(self):
        rows = fs.rank_suggestions(
            [
                {"handle": "marie", "name": "Marie", "headline": "Coaching", "follower_count": 5},
                {"handle": "marie", "name": "Marie bis", "headline": "Coaching", "follower_count": 9},
            ],
            ["coaching"],
            set(),
        )
        self.assertEqual(len(rows), 1)

    def test_row_shape_and_matched_keywords(self):
        rows = fs.rank_suggestions(
            [{"handle": "marie", "name": "Marie", "headline": "Coaching business B2B pour indépendants",
              "follower_count": "42"}],
            ["coaching", "business", "indépendants", "closing"],
            set(),
        )
        row = rows[0]
        self.assertEqual(row["follower_count"], 42)  # tolère un entier arrivé en chaîne
        self.assertEqual(row["matched_keywords"], ["coaching", "business", "indépendants"])
        self.assertNotIn("closing", row["matched_keywords"])

    def test_candidate_without_text_is_ignored(self):
        self.assertEqual(
            fs.rank_suggestions([{"handle": "vide", "name": "", "headline": ""}], ["coaching"], set()),
            [],
        )


class ExcludedHandlesTest(unittest.TestCase):
    def test_merges_followed_library_and_self(self):
        excluded = fs.excluded_handles(
            [{"handle": "d%C3%A9jaanalyse"}, {"handle": "  autre  "}],
            {"Suivi"},
            own_handle="Moi",
        )
        self.assertEqual(excluded, {"suivi", "déjaanalyse", "autre", "moi"})

    def test_tolerates_empty_inputs(self):
        self.assertEqual(fs.excluded_handles([], set()), set())
        self.assertEqual(fs.excluded_handles(None, set(), ""), set())


class BuildFollowSuggestionsTest(unittest.TestCase):
    """Assemblage complet, sans base ni réseau (le module ne dépend pas de fastapi)."""

    def _patch_db(self, **overrides):
        defaults = {
            "get_editorial_profile": {"industry": "coaching business", "linkedin_url": "https://www.linkedin.com/in/moi/"},
            "get_lead_targeting": {"ideal_client": "indépendants"},
            "list_followed_influencers": [{"handle": "suivi"}],
            "list_influencer_library": [{"handle": "deja-analyse"}],
            "list_influencer_cache_candidates": [
                {"handle": "marie", "name": "Marie", "headline": "Coaching business", "follower_count": 10},
                {"handle": "suivi", "name": "Suivi", "headline": "Coaching business", "follower_count": 99},
                {"handle": "deja-analyse", "name": "Déjà", "headline": "Coaching business", "follower_count": 99},
                {"handle": "moi", "name": "Moi", "headline": "Coaching business", "follower_count": 99},
            ],
        }
        defaults.update(overrides)
        return [patch.object(fs.db, name, return_value=value) for name, value in defaults.items()]

    def _run(self, **overrides):
        patches = self._patch_db(**overrides)
        for p in patches:
            p.start()
        try:
            return fs.build_follow_suggestions("token")
        finally:
            for p in patches:
                p.stop()

    def test_excludes_followed_library_and_self(self):
        out = self._run()
        self.assertEqual([s["handle"] for s in out["suggestions"]], ["marie"])
        self.assertEqual(out["followed_count"], 1)

    def test_empty_profile_skips_the_service_role_query(self):
        """Sans mot-clé, la requête cross-user ne doit même pas être tentée :
        elle serait payée pour un résultat qu'on jette."""
        with patch.object(fs.db, "get_editorial_profile", return_value=None), \
             patch.object(fs.db, "get_lead_targeting", return_value=None), \
             patch.object(fs.db, "list_followed_influencers", return_value=[]), \
             patch.object(fs.db, "list_influencer_cache_candidates") as candidates:
            out = fs.build_follow_suggestions("token")
        self.assertEqual(out["suggestions"], [])
        candidates.assert_not_called()

    def test_db_failure_never_breaks_the_screen(self):
        with patch.object(fs.db, "get_editorial_profile", side_effect=RuntimeError("boom")):
            out = fs.build_follow_suggestions("token")
        self.assertEqual(out, {"suggestions": [], "followed_count": 0})

    def test_result_is_capped(self):
        many = [
            {"handle": f"h{i}", "name": f"N{i}", "headline": "Coaching business", "follower_count": i}
            for i in range(30)
        ]
        out = self._run(list_influencer_cache_candidates=many)
        self.assertEqual(len(out["suggestions"]), fs.FOLLOW_SUGGESTIONS_LIMIT)


if __name__ == "__main__":
    unittest.main()
