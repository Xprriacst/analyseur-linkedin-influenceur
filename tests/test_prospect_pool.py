"""Tests unitaires — vivier partagé de prospects (Mode Pilote).

Ce que ces tests verrouillent, dans l'ordre d'importance :

1. **Sans mot-clé de niche, RIEN** — et le vivier n'est même pas lu.
2. **Correspondance par début de mot** : « vente » ≠ « inventaire »,
   « coach » = « coaching ».
3. **Copie dans les leads du RECEVEUR**, jamais de l'admin qui a rempli
   le stock. Score vert (75) pour que `pick_contacts` le voie.
4. **1 par jour calendaire UTC** : rouvrir l'écran ne duplique pas.
5. **Les lignes sans URL sont comptées**, pas avalées.
6. **Fail-safe** : une panne d'insert n'explose pas.
"""
import datetime
import unittest
from unittest.mock import patch

from src import prospect_pool as pp
from src.pilot_plan import pick_contacts


def _profile(**kwargs):
    base = {"industry": "pharmacie officine", "target_audience": "titulaires"}
    base.update(kwargs)
    return base


def _pool_row(slug, name="Marie", headline="Pharmacienne titulaire"):
    return {
        "profile_url": f"https://www.linkedin.com/in/{slug}",
        "name": name,
        "headline": headline,
    }


class KeywordHitsTest(unittest.TestCase):
    def test_word_start_not_substring(self):
        """« vente » ne doit pas matcher « inventaire » — faux positif silencieux."""
        self.assertEqual(pp.keyword_hits("responsable inventaire magasin", ["vente"]), [])
        self.assertEqual(pp.keyword_hits("coach en vente B2B", ["vente"]), ["vente"])

    def test_coach_matches_coaching(self):
        self.assertEqual(pp.keyword_hits("Coaching business pour indépendants", ["coach"]), ["coach"])

    def test_preserves_keyword_order(self):
        hits = pp.keyword_hits("pharmacienne titulaire officine", ["officine", "pharmacie", "titulaire"])
        self.assertEqual(hits, ["officine", "pharmacie", "titulaire"])


class PickBestTest(unittest.TestCase):
    def test_empty_keywords_returns_none(self):
        self.assertIsNone(pp.pick_best([_pool_row("marie")], [], set()))

    def test_no_hit_returns_none(self):
        self.assertIsNone(pp.pick_best(
            [_pool_row("sam", headline="Jardinier paysagiste")],
            ["pharmacie"],
            set(),
        ))

    def test_excludes_already_owned_url(self):
        owned = {"https://www.linkedin.com/in/marie"}
        self.assertIsNone(pp.pick_best([_pool_row("marie")], ["pharmacie"], owned))

    def test_canonicalizes_excluded_forms(self):
        owned = {"https://fr.linkedin.com/in/marie/?trk=x"}
        self.assertIsNone(pp.pick_best([_pool_row("marie")], ["pharmacie"], owned))

    def test_more_keyword_hits_win(self):
        rows = [
            _pool_row("a", headline="Coach sportif"),
            _pool_row("b", headline="Pharmacienne titulaire d'officine"),
        ]
        picked = pp.pick_best(rows, ["pharmacie", "titulaire", "officine"], set())
        self.assertEqual(picked["profile_url"], "https://www.linkedin.com/in/b")
        self.assertGreaterEqual(len(picked["matched_keywords"]), 2)

    def test_canonical_url_on_output(self):
        rows = [{
            "profile_url": "https://fr.linkedin.com/in/lea-pharma/?trk=abc",
            "name": "Léa",
            "headline": "Pharmacienne",
        }]
        picked = pp.pick_best(rows, ["pharmacie"], set())
        self.assertEqual(picked["profile_url"], "https://www.linkedin.com/in/lea-pharma")


class AssignedTodayTest(unittest.TestCase):
    def test_detects_pool_signal_from_today(self):
        now = datetime.datetime(2026, 9, 2, 15, 0, tzinfo=datetime.timezone.utc)
        leads = [{
            "profile_url": "https://www.linkedin.com/in/marie",
            "created_at": "2026-09-02T08:00:00Z",
            "signals": [{"origin": "prospect_pool"}],
        }]
        self.assertTrue(pp.assigned_from_pool_today(leads, now))

    def test_yesterday_does_not_count(self):
        now = datetime.datetime(2026, 9, 2, 15, 0, tzinfo=datetime.timezone.utc)
        leads = [{
            "profile_url": "https://www.linkedin.com/in/marie",
            "created_at": "2026-09-01T22:00:00Z",
            "signals": [{"origin": "prospect_pool"}],
        }]
        self.assertFalse(pp.assigned_from_pool_today(leads, now))

    def test_ignores_non_pool_leads(self):
        now = datetime.datetime(2026, 9, 2, 15, 0, tzinfo=datetime.timezone.utc)
        leads = [{
            "profile_url": "https://www.linkedin.com/in/marie",
            "created_at": "2026-09-02T08:00:00Z",
            "signals": [{"post_url": "import://abc"}],
        }]
        self.assertFalse(pp.assigned_from_pool_today(leads, now))


class ParseProfileUrlsTest(unittest.TestCase):
    def test_counts_ignored_and_dedupes(self):
        text = (
            "https://www.linkedin.com/in/marie\n"
            "pas une url\n"
            "https://fr.linkedin.com/in/marie/?trk=x\n"
            "https://www.linkedin.com/in/jean\n"
            "\n"
        )
        out = pp.parse_profile_urls(text)
        self.assertEqual(len(out["leads"]), 2)
        self.assertEqual(out["ignored"], 1)
        self.assertEqual(out["rows"], 4)
        urls = {r["profile_url"] for r in out["leads"]}
        self.assertEqual(urls, {
            "https://www.linkedin.com/in/marie",
            "https://www.linkedin.com/in/jean",
        })


class MaybeAssignOneTest(unittest.TestCase):
    def test_no_keywords_does_not_read_pool(self):
        reads = {"n": 0}

        def reader(**_kwargs):
            reads["n"] += 1
            return [_pool_row("marie")]

        out = pp.maybe_assign_one(
            "user-lia",
            {},
            {},
            [],
            list_candidates=reader,
            insert_lead=lambda *_a, **_k: {"id": "nope"},
        )
        self.assertIsNone(out)
        self.assertEqual(reads["n"], 0)

    def test_copies_to_receiver_not_admin(self):
        captured = {}

        def writer(user_id, **kwargs):
            captured["user_id"] = user_id
            captured.update(kwargs)
            return {"id": "lead-new", "user_id": user_id, **kwargs}

        out = pp.maybe_assign_one(
            "user-lia",
            _profile(),
            {"ideal_client": "pharmaciens titulaires"},
            [],
            list_candidates=lambda **_k: [_pool_row("marie")],
            insert_lead=writer,
        )
        self.assertEqual(captured["user_id"], "user-lia")
        self.assertNotEqual(captured["user_id"], "admin-alex")
        self.assertEqual(out["id"], "lead-new")
        self.assertEqual(captured["score"], pp.POOL_ASSIGN_SCORE)
        self.assertIn("pharmacie", captured["score_reason"])
        # Vert ⇒ pick_contacts l'accepte.
        copied = {
            "id": out["id"],
            "score": captured["score"],
            "contact_status": None,
            "outreach_status": "none",
        }
        self.assertEqual(pick_contacts([copied]), [copied])

    def test_skips_when_already_assigned_today(self):
        now = datetime.datetime(2026, 9, 2, 12, 0, tzinfo=datetime.timezone.utc)
        existing = [{
            "profile_url": "https://www.linkedin.com/in/deja",
            "created_at": "2026-09-02T09:00:00Z",
            "signals": [{"origin": "prospect_pool"}],
            "score": 75,
        }]
        writes = {"n": 0}

        def writer(*_a, **_k):
            writes["n"] += 1
            return {"id": "x"}

        out = pp.maybe_assign_one(
            "user-lia",
            _profile(),
            None,
            existing,
            now=now,
            list_candidates=lambda **_k: [_pool_row("marie")],
            insert_lead=writer,
        )
        self.assertIsNone(out)
        self.assertEqual(writes["n"], 0)

    def test_second_call_same_day_is_noop_after_insert(self):
        """Le 2ᵉ passage du jour voit le lead fraîchement copié → zéro 2ᵉ insert."""
        now = datetime.datetime(2026, 9, 2, 12, 0, tzinfo=datetime.timezone.utc)
        inserted = {
            "id": "lead-1",
            "user_id": "user-lia",
            "profile_url": "https://www.linkedin.com/in/marie",
            "created_at": now.isoformat(),
            "signals": [{"origin": "prospect_pool"}],
            "score": 75,
        }
        writes = {"n": 0}

        def writer(*_a, **_k):
            writes["n"] += 1
            return inserted

        first = pp.maybe_assign_one(
            "user-lia",
            _profile(),
            None,
            [],
            now=now,
            list_candidates=lambda **_k: [_pool_row("marie")],
            insert_lead=writer,
        )
        second = pp.maybe_assign_one(
            "user-lia",
            _profile(),
            None,
            [first],
            now=now,
            list_candidates=lambda **_k: [_pool_row("jean", headline="Pharmacien")],
            insert_lead=writer,
        )
        self.assertEqual(writes["n"], 1)
        self.assertIsNone(second)

    def test_skips_url_already_in_user_leads(self):
        existing = [{
            "profile_url": "https://www.linkedin.com/in/marie",
            "signals": [],
            "created_at": "2026-08-01T00:00:00Z",
        }]
        out = pp.maybe_assign_one(
            "user-lia",
            _profile(),
            None,
            existing,
            list_candidates=lambda **_k: [_pool_row("marie")],
            insert_lead=lambda *_a, **_k: {"id": "should-not"},
        )
        self.assertIsNone(out)

    def test_insert_failure_is_swallowed(self):
        def writer(*_a, **_k):
            raise RuntimeError("unique violation")

        out = pp.maybe_assign_one(
            "user-lia",
            _profile(),
            None,
            [],
            list_candidates=lambda **_k: [_pool_row("marie")],
            insert_lead=writer,
        )
        self.assertIsNone(out)

    def test_two_receivers_can_get_the_same_person(self):
        """Deux clients pharmacie voient la même fiche — chacun dans SES leads."""
        row = _pool_row("marie")
        seen = []

        def writer(user_id, **kwargs):
            seen.append(user_id)
            return {"id": f"lead-{user_id}", "user_id": user_id, **kwargs}

        a = pp.maybe_assign_one(
            "user-a", _profile(), None, [],
            list_candidates=lambda **_k: [row], insert_lead=writer,
        )
        b = pp.maybe_assign_one(
            "user-b", _profile(), None, [],
            list_candidates=lambda **_k: [row], insert_lead=writer,
        )
        self.assertEqual(a["profile_url"], b["profile_url"])
        self.assertEqual(seen, ["user-a", "user-b"])


class IngestRowsTest(unittest.TestCase):
    def test_canonicalizes_and_dedupes_before_db(self):
        captured = {}

        def upsert(rows):
            captured["rows"] = rows
            return {"inserted": len(rows), "updated": 0, "skipped": 0}

        with patch("src.prospect_pool.db.upsert_prospect_cache", side_effect=upsert):
            out = pp.ingest_rows([
                {"profile_url": "https://fr.linkedin.com/in/marie/?trk=x", "name": "Marie"},
                {"profile_url": "https://www.linkedin.com/in/marie", "name": "Marie Dupont"},
            ])
        self.assertEqual(len(captured["rows"]), 1)
        self.assertEqual(captured["rows"][0]["profile_url"], "https://www.linkedin.com/in/marie")
        self.assertEqual(out["inserted"], 1)


class NicheReasonTest(unittest.TestCase):
    def test_lists_matched_keywords(self):
        self.assertEqual(
            pp.niche_reason(["pharmacie", "officine"]),
            "correspond à ta niche : pharmacie · officine",
        )


if __name__ == "__main__":
    unittest.main()
