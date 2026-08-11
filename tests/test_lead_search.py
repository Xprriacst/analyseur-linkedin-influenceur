"""Tests import d'un lien de recherche LinkedIn (source de prospection 'search')."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src import lead_search, unipile


class ValidateSearchUrlTest(unittest.TestCase):
    def test_accepts_classic_people_search_and_keeps_query(self):
        url = lead_search.validate_search_url(
            "https://www.linkedin.com/search/results/people/?keywords=CTO&geoUrn=%5B%22105015875%22%5D"
        )
        # La query PORTE les critères : la perdre donnerait une recherche vide.
        self.assertIn("keywords=CTO", url)
        self.assertIn("geoUrn", url)

    def test_accepts_sales_navigator_and_lead_list(self):
        for raw in (
            "https://www.linkedin.com/sales/search/people?query=abc",
            "https://www.linkedin.com/sales/lists/people/123456",
            "https://www.linkedin.com/talent/search?searchContextId=x",
        ):
            self.assertTrue(lead_search.validate_search_url(raw).startswith("https://"))

    def test_adds_scheme_and_drops_fragment(self):
        # Le fragment ne sert à rien côté serveur mais casserait la dédup
        # (user_id, post_url) : deux fois la même recherche = deux sources.
        url = lead_search.validate_search_url("www.linkedin.com/search/results/people/?k=1#zone")
        self.assertEqual(url, "https://www.linkedin.com/search/results/people/?k=1")

    def test_rejects_non_people_tabs_with_actionable_message(self):
        with self.assertRaises(lead_search.LeadSearchError) as ctx:
            lead_search.validate_search_url("https://www.linkedin.com/search/results/companies/?k=1")
        self.assertIn("Personnes", str(ctx.exception))

    def test_rejects_profile_url(self):
        with self.assertRaises(lead_search.LeadSearchError):
            lead_search.validate_search_url("https://www.linkedin.com/in/satyanadella/")

    def test_rejects_other_hosts_and_empty(self):
        with self.assertRaises(lead_search.LeadSearchError):
            lead_search.validate_search_url("https://linkedin.com.evil.tld/search/results/people/")
        with self.assertRaises(lead_search.LeadSearchError):
            lead_search.validate_search_url("")


class CanonicalProfileUrlTest(unittest.TestCase):
    def test_all_shapes_collapse_to_one_url(self):
        # Garantie de dédup : la même personne vue par un commentaire ET par une
        # recherche doit produire la MÊME clé, sinon deux lignes de lead → deux
        # invitations à la même personne.
        forms = [
            "https://www.linkedin.com/in/camille-roy/",
            "http://linkedin.com/in/camille-roy",
            "https://fr.linkedin.com/in/camille-roy?trk=public_profile",
            "linkedin.com/in/camille-roy/",
        ]
        canon = {lead_search.canonical_profile_url(f) for f in forms}
        self.assertEqual(canon, {"https://www.linkedin.com/in/camille-roy"})

    def test_encodes_accented_slug(self):
        url = lead_search.canonical_profile_url("https://www.linkedin.com/in/clément-geynet")
        self.assertEqual(url, "https://www.linkedin.com/in/cl%C3%A9ment-geynet")

    def test_returns_none_without_slug(self):
        self.assertIsNone(lead_search.canonical_profile_url("https://www.linkedin.com/company/acme"))
        self.assertIsNone(lead_search.canonical_profile_url(None))


class EffectiveMaxResultsTest(unittest.TestCase):
    def test_clamped_between_min_and_linkedin_cap(self):
        self.assertEqual(lead_search.effective_max_results(None), lead_search.DEFAULT_MAX_RESULTS)
        self.assertEqual(lead_search.effective_max_results(1), lead_search.MIN_MAX_RESULTS)
        self.assertEqual(lead_search.effective_max_results(250), 250)
        # LinkedIn ne rend jamais plus de 1000 profils par recherche.
        self.assertEqual(lead_search.effective_max_results(99999), lead_search.MAX_RESULTS_CAP)
        self.assertEqual(lead_search.effective_max_results("oops"), lead_search.DEFAULT_MAX_RESULTS)


class NormalizeSearchProfileTest(unittest.TestCase):
    def test_builds_url_from_public_identifier_and_joins_name(self):
        profile = unipile.normalize_search_profile({
            "public_identifier": "camille-roy",
            "first_name": "Camille",
            "last_name": "Roy",
            "headline": "CMO @ Acme",
            "provider_id": "ACoAAB1",
            "location": {"name": "Paris"},
        })
        self.assertEqual(profile["profile_url"], "https://www.linkedin.com/in/camille-roy")
        self.assertEqual(profile["name"], "Camille Roy")
        self.assertEqual(profile["provider_id"], "ACoAAB1")
        self.assertEqual(profile["location"], "Paris")

    def test_rejects_item_without_any_identifier(self):
        self.assertIsNone(unipile.normalize_search_profile({"headline": "CTO"}))
        self.assertIsNone(unipile.normalize_search_profile("nope"))

    def test_ignores_placeholder_name(self):
        profile = unipile.normalize_search_profile(
            {"public_identifier": "x", "name": "{{full_name}}"}
        )
        self.assertIsNone(profile["name"])


def _page(ids, cursor=None, total=None):
    items = [{"public_identifier": i, "name": i, "provider_id": f"ACo{i}"} for i in ids]
    page = {"items": items}
    if cursor:
        page["cursor"] = cursor
    if total is not None:
        page["paging"] = {"total_count": total}
    return page


class CollectSearchProfilesTest(unittest.TestCase):
    def test_paginates_until_cursor_exhausted(self):
        pages = [_page(["a", "b"], cursor="c1", total=42), _page(["c"], cursor=None)]
        with patch("src.unipile.search_page", side_effect=pages) as sp:
            leads, total = lead_search.collect_search_profiles("acc", "https://x", 100)
        self.assertEqual([l["profile_url"].rsplit("/", 1)[-1] for l in leads], ["a", "b", "c"])
        self.assertEqual(total, 42)
        # Le curseur de la page 1 est bien réinjecté dans l'appel suivant.
        self.assertEqual(sp.call_args_list[1].kwargs["cursor"], "c1")

    def test_stops_at_requested_volume_mid_page(self):
        # 2 pages de 20 profils, 25 demandés : on rend exactement 25 et on
        # n'appelle jamais la 3e page (chaque appel évité est une sollicitation
        # de moins sur le compte LinkedIn du client).
        pages = [
            _page([f"a{i}" for i in range(20)], cursor="c1"),
            _page([f"b{i}" for i in range(20)], cursor="c2"),
            _page(["never"], cursor="c3"),
        ]
        with patch("src.unipile.search_page", side_effect=pages) as sp:
            leads, _ = lead_search.collect_search_profiles("acc", "https://x", 25)
        self.assertEqual(len(leads), 25)
        self.assertEqual(sp.call_count, 2)

    def test_dedups_across_pages(self):
        pages = [_page(["a", "b"], cursor="c1"), _page(["b", "c"], cursor=None)]
        with patch("src.unipile.search_page", side_effect=pages):
            leads, _ = lead_search.collect_search_profiles("acc", "https://x", 100)
        self.assertEqual(len(leads), 3)

    def test_stops_when_a_page_brings_nothing_new(self):
        # Curseur qui tourne en rond : sans garde-fou on rappellerait LinkedIn
        # jusqu'au plafond de pages pour rien — exactement ce qui fait flaguer
        # un compte.
        looping = [_page(["a"], cursor="same") for _ in range(10)]
        with patch("src.unipile.search_page", side_effect=looping) as sp:
            leads, _ = lead_search.collect_search_profiles("acc", "https://x", 100)
        self.assertEqual(len(leads), 1)
        self.assertEqual(sp.call_count, 2)

    def test_empty_first_page_is_not_an_error(self):
        with patch("src.unipile.search_page", return_value={"items": []}):
            leads, total = lead_search.collect_search_profiles("acc", "https://x", 100)
        self.assertEqual(leads, [])
        self.assertIsNone(total)


class CollectAndPersistSearchTest(unittest.TestCase):
    def test_requires_a_connected_linkedin_account(self):
        with patch("src.db.get_linkedin_outreach_account", return_value={}):
            with self.assertRaises(RuntimeError) as ctx:
                lead_search.collect_and_persist_search("tok", {"id": "s1", "post_url": "u"}, 100)
        self.assertIn("compte LinkedIn", str(ctx.exception))

    def test_persists_scores_and_never_debits_credits(self):
        profiles = [{"public_identifier": "a", "name": "A", "provider_id": "ACoA"}]
        with patch("src.db.get_linkedin_outreach_account", return_value={"unipile_account_id": "acc"}), \
             patch("src.unipile.search_page", return_value=_page(["a"], total=7)), \
             patch("src.db.save_leads", return_value={"inserted": 1, "updated": 0, "skipped": 0, "ids_by_url": {"u": "l1"}}) as save, \
             patch("src.lead_finder._score_leads_for_source") as score, \
             patch("src.db.update_lead_source") as upd, \
             patch("src.db.debit_credits") as debit:
            result = lead_search.collect_and_persist_search("tok", {"id": "s1", "post_url": "u"}, 100)

        self.assertEqual(result["profiles_count"], 1)
        self.assertEqual(result["search_total"], 7)
        self.assertIsNone(result["credits"])
        # Gratuit : la recherche passe par le compte du client (forfait Unipile).
        debit.assert_not_called()
        score.assert_called_once()
        # `ids_by_url` reste interne au scoring, jamais renvoyé au job.
        self.assertNotIn("ids_by_url", result["leads"])
        # Le lead persisté porte le provider_id (évite un appel de résolution
        # de profil au moment de l'invitation) et une URL canonique.
        saved = save.call_args[0][2]
        self.assertEqual(saved[0]["provider_id"], "ACoa")
        self.assertEqual(saved[0]["profile_url"], "https://www.linkedin.com/in/a")
        self.assertEqual(upd.call_args[0][2]["search_total"], 7)
        self.assertIsNone(saved[0]["comment_text"])
        _ = profiles


if __name__ == "__main__":
    unittest.main()
