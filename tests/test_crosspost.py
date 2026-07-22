"""ALE-59 — Tests de la logique pure de publication multi-réseaux.

Couvre : normalisation des sorties du modèle (défensif), découpage en thread,
bibliothèque de subreddits, et construction des payloads Zernio
(platformSpecificData au bon endroit — un mauvais emplacement serait une panne
silencieuse : Zernio ignorerait le subreddit/le thread sans erreur).
"""
from __future__ import annotations

import unittest
from unittest import mock

from src import crosspost, zernio


class SubredditNameTest(unittest.TestCase):
    def test_strips_r_prefix_and_slashes(self):
        for raw in ("r/marketing", "/r/marketing/", "marketing", " R/marketing "):
            self.assertEqual(crosspost.normalize_subreddit_name(raw), "marketing")

    def test_preserves_case_and_underscores(self):
        self.assertEqual(crosspost.normalize_subreddit_name("r/B2BMarketing"), "B2BMarketing")
        self.assertEqual(crosspost.normalize_subreddit_name("content_marketing"), "content_marketing")

    def test_rejects_invalid_names(self):
        for raw in ("", None, 42, "r/", "has space", "a", "x" * 30, "sub#reddit"):
            self.assertEqual(crosspost.normalize_subreddit_name(raw), "")


class SubredditLibraryTest(unittest.TestCase):
    def test_library_loads_and_entries_are_wellformed(self):
        library = crosspost.load_subreddit_library()
        self.assertGreater(len(library), 10)
        for entry in library:
            # Chaque entrée doit avoir un nom valide (sans préfixe r/) : c'est
            # ce que le prompt injecte et ce que library_entry compare.
            self.assertEqual(crosspost.normalize_subreddit_name(entry["name"]), entry["name"])
            self.assertIn(entry.get("selfpromo_tolerance"), (1, 2, 3, 4, 5))

    def test_library_entry_lookup_is_prefix_and_case_insensitive(self):
        entry = crosspost.library_entry("r/MARKETING")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["name"], "marketing")

    def test_unknown_subreddit_metadata_has_no_badges(self):
        meta = crosspost.suggestion_metadata("nonexistent_sub_xyz")
        self.assertFalse(meta["in_library"])
        self.assertIsNone(meta["selfpromo_tolerance"])
        self.assertIsNone(meta["min_karma_advised"])


class SplitIntoTweetsTest(unittest.TestCase):
    def test_short_text_is_single_tweet(self):
        self.assertEqual(crosspost.split_into_tweets("Un tweet court."), ["Un tweet court."])

    def test_paragraphs_are_grouped_up_to_limit(self):
        text = "\n\n".join(["Para un.", "Para deux.", "X" * 270])
        tweets = crosspost.split_into_tweets(text)
        self.assertEqual(tweets[0], "Para un.\n\nPara deux.")
        self.assertEqual(tweets[1], "X" * 270)
        for t in tweets:
            self.assertLessEqual(len(t), crosspost.X_TWEET_MAX)

    def test_long_paragraph_splits_on_sentences_never_mid_word(self):
        sentence = "Voici une phrase complète qui apporte une idée précise et documentée. "
        tweets = crosspost.split_into_tweets(sentence * 12)
        self.assertGreater(len(tweets), 1)
        for t in tweets:
            self.assertLessEqual(len(t), crosspost.X_TWEET_MAX)
            self.assertFalse(t.startswith(" "))

    def test_empty_text_yields_nothing(self):
        self.assertEqual(crosspost.split_into_tweets("   "), [])

    def test_thread_is_capped(self):
        text = "\n\n".join(["Paragraphe %d %s" % (i, "y" * 250) for i in range(30)])
        self.assertLessEqual(len(crosspost.split_into_tweets(text)), crosspost.X_THREAD_MAX_ITEMS)


class NormalizeXAdaptationTest(unittest.TestCase):
    def test_nominal_thread(self):
        data = {"tweets": ["Accroche.", "Idée 1.", "Conclusion."]}
        self.assertEqual(crosspost.normalize_x_adaptation(data), ["Accroche.", "Idée 1.", "Conclusion."])

    def test_empty_and_non_string_tweets_are_dropped(self):
        data = {"tweets": ["Ok.", "", "   ", None, 42]}
        self.assertEqual(crosspost.normalize_x_adaptation(data), ["Ok."])

    def test_overlong_tweet_is_resplit_instead_of_failing(self):
        # Un modèle qui ignore la limite ne doit pas produire un envoi voué au 400.
        data = {"tweets": ["Phrase A tout à fait normale. " * 15]}
        tweets = crosspost.normalize_x_adaptation(data)
        self.assertGreater(len(tweets), 1)
        for t in tweets:
            self.assertLessEqual(len(t), crosspost.X_TWEET_MAX)

    def test_missing_tweets_falls_back_to_content(self):
        self.assertEqual(crosspost.normalize_x_adaptation({"content": "Un seul tweet."}), ["Un seul tweet."])

    def test_garbage_yields_empty(self):
        self.assertEqual(crosspost.normalize_x_adaptation("n'importe quoi"), [])
        self.assertEqual(crosspost.normalize_x_adaptation({}), [])


class NormalizeRedditAdaptationTest(unittest.TestCase):
    def test_nominal(self):
        data = {
            "title": "I analyzed 400 LinkedIn posts",
            "body": "Here is what I found.",
            "subreddits": [{"name": "r/marketing", "reason": "cœur de cible"}, {"name": "B2BMarketing"}],
        }
        result = crosspost.normalize_reddit_adaptation(data)
        self.assertEqual(result["title"], "I analyzed 400 LinkedIn posts")
        self.assertEqual(
            [s["name"] for s in result["subreddits"]], ["marketing", "B2BMarketing"]
        )

    def test_missing_title_falls_back_to_first_body_line(self):
        result = crosspost.normalize_reddit_adaptation({"body": "Première ligne\n\nSuite du post."})
        self.assertEqual(result["title"], "Première ligne")

    def test_title_is_truncated_to_reddit_limit(self):
        result = crosspost.normalize_reddit_adaptation({"title": "T" * 400, "body": "corps"})
        self.assertEqual(len(result["title"]), crosspost.REDDIT_TITLE_MAX)

    def test_subreddits_are_deduped_and_invalid_dropped(self):
        data = {
            "title": "t", "body": "b",
            "subreddits": ["marketing", {"name": "r/Marketing"}, {"name": "has space"}, {"name": ""}, 42],
        }
        result = crosspost.normalize_reddit_adaptation(data)
        self.assertEqual([s["name"] for s in result["subreddits"]], ["marketing"])

    def test_suggestions_are_capped(self):
        data = {"title": "t", "body": "b", "subreddits": [{"name": f"sub{i}"} for i in range(10)]}
        result = crosspost.normalize_reddit_adaptation(data)
        self.assertEqual(len(result["subreddits"]), crosspost.MAX_SUBREDDIT_SUGGESTIONS)


class ZernioCrossPostPayloadTest(unittest.TestCase):
    """platformSpecificData doit voyager DANS l'entrée du tableau platforms
    (schéma OpenAPI Zernio) — ailleurs, Zernio l'ignorerait en silence."""

    def _capture_body(self, **kwargs):
        captured = {}

        def fake_request(method, path, params=None, body=None):
            captured.update({"method": method, "path": path, "body": body})
            return {"post": {"_id": "z1"}}

        with mock.patch.object(zernio, "_request", side_effect=fake_request):
            zernio.create_post("contenu", "acc-1", **kwargs)
        return captured

    def test_reddit_platform_specific_data_lives_in_platform_entry(self):
        captured = self._capture_body(
            platform="reddit",
            platform_specific_data={"subreddit": "marketing", "title": "Titre"},
        )
        body = captured["body"]
        entry = body["platforms"][0]
        self.assertEqual(entry["platform"], "reddit")
        self.assertEqual(entry["platformSpecificData"]["subreddit"], "marketing")
        self.assertEqual(entry["platformSpecificData"]["title"], "Titre")
        self.assertNotIn("platformSpecificData", body)

    def test_x_thread_items(self):
        captured = self._capture_body(
            platform="x",
            platform_specific_data={"threadItems": [{"content": "t1"}, {"content": "t2"}]},
        )
        entry = captured["body"]["platforms"][0]
        self.assertEqual(len(entry["platformSpecificData"]["threadItems"]), 2)

    def test_no_platform_specific_data_keeps_legacy_payload(self):
        captured = self._capture_body(platform="linkedin")
        entry = captured["body"]["platforms"][0]
        self.assertNotIn("platformSpecificData", entry)
        self.assertEqual(captured["body"]["publishNow"], True)

    def test_validate_subreddit_strips_prefix(self):
        captured = {}

        def fake_request(method, path, params=None, body=None):
            captured.update({"path": path, "params": params})
            return {"exists": True}

        with mock.patch.object(zernio, "_request", side_effect=fake_request):
            zernio.validate_subreddit("r/marketing", account_id="acc-9")
        self.assertEqual(captured["path"], "/tools/validate/subreddit")
        self.assertEqual(captured["params"], {"name": "marketing", "accountId": "acc-9"})


class SchedulerCrossPublishTest(unittest.TestCase):
    """Le cron publie les versions X/Reddit et consigne le résultat par réseau."""

    def _post(self, **overrides):
        base = {
            "id": "sp-1",
            "user_id": "u-1",
            "post_text": "post linkedin",
            "media_items": [],
            "cross_posts": {
                "x": {"tweets": ["tweet un", "tweet deux"]},
                "reddit": {"subreddit": "marketing", "title": "Titre", "body": "Corps"},
            },
            "zernio_account_id": "li-acc",
            "zernio_x_account_id": "x-acc",
            "zernio_reddit_account_id": "rd-acc",
        }
        base.update(overrides)
        return base

    def test_publishes_both_networks_and_records_ids(self):
        from src import scheduler

        calls = []

        def fake_create_post(content, account_id, **kwargs):
            calls.append({"content": content, "account_id": account_id, **kwargs})
            return {"post": {"_id": f"z-{len(calls)}"}}

        with mock.patch.object(scheduler.zernio, "create_post", side_effect=fake_create_post):
            result = scheduler.publish_cross_posts(self._post())

        self.assertEqual(result["x"]["status"], "published")
        self.assertEqual(result["reddit"]["status"], "published")
        x_call = next(c for c in calls if c["platform"] == "x")
        self.assertEqual(
            [t["content"] for t in x_call["platform_specific_data"]["threadItems"]],
            ["tweet un", "tweet deux"],
        )
        reddit_call = next(c for c in calls if c["platform"] == "reddit")
        self.assertEqual(reddit_call["platform_specific_data"]["subreddit"], "marketing")
        self.assertEqual(reddit_call["account_id"], "rd-acc")

    def test_one_network_failure_does_not_block_the_other(self):
        from src import scheduler

        def fake_create_post(content, account_id, **kwargs):
            if kwargs.get("platform") == "x":
                raise zernio.ZernioError("X en panne")
            return {"post": {"_id": "z-ok"}}

        with mock.patch.object(scheduler.zernio, "create_post", side_effect=fake_create_post):
            result = scheduler.publish_cross_posts(self._post())

        self.assertEqual(result["x"]["status"], "failed")
        self.assertIn("X en panne", result["x"]["error"])
        self.assertEqual(result["reddit"]["status"], "published")

    def test_disconnected_account_is_recorded_not_raised(self):
        from src import scheduler

        with mock.patch.object(scheduler.zernio, "create_post") as create_post:
            result = scheduler.publish_cross_posts(self._post(zernio_x_account_id=None, zernio_reddit_account_id=None))

        create_post.assert_not_called()
        self.assertEqual(result["x"]["status"], "failed")
        self.assertEqual(result["reddit"]["status"], "failed")

    def test_single_tweet_publishes_without_thread(self):
        from src import scheduler

        calls = []

        def fake_create_post(content, account_id, **kwargs):
            calls.append({"content": content, **kwargs})
            return {"post": {"_id": "z"}}

        post = self._post()
        post["cross_posts"] = {"x": {"tweets": ["un seul tweet"]}}
        with mock.patch.object(scheduler.zernio, "create_post", side_effect=fake_create_post):
            result = scheduler.publish_cross_posts(post)

        self.assertEqual(result["x"]["status"], "published")
        self.assertIsNone(calls[0].get("platform_specific_data"))
        self.assertEqual(calls[0]["content"], "un seul tweet")


if __name__ == "__main__":
    unittest.main()
