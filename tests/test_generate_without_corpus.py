"""Génération sans corpus d'influenceurs — les deux portes du wizard.

Contexte (2026-09-11) : Alex a tenté de générer un post pour Joëlle, compte
``ideas_only``, « avec une idée » ET « sans idée ». Les deux ont échoué.

Cause : ``/ideas`` et ``/generate/jobs`` (et ``_prepare_generate_context``,
utilisé par ``/generate``) levaient un 400 « Lance d'abord une analyse » dès
que ``_get_influencers`` rendait []. Or un compte ``ideas_only`` n'analyse
pas d'influenceurs : son carburant est le profil éditorial + l'idée. Le
bootstrap daily-idea savait déjà générer sans corpus ; le wizard, non.

Deux niveaux de test :
- lecture de ``api.py`` (toujours joué, même sans fastapi) ;
- appel réel des endpoints (joué en CI, où requirements.txt est installé).
"""
from __future__ import annotations

import pathlib
import unittest
from unittest import mock

API_SOURCE = (pathlib.Path(__file__).resolve().parents[1] / "api.py").read_text(encoding="utf-8")

# Le 400 qui a cassé les deux portes du wizard. On cible le ``raise``, pas le
# commentaire qui le nomme (sinon le commentaire de garde ferait échouer le test).
WIZARD_CORPUS_400 = 'detail="Aucun influenceur analysé. Lance d\'abord une analyse."'

try:  # fastapi n'est pas installé sur le Python local du Mac (cf. changelog).
    import api as api_module  # noqa: F401

    HAS_API = True
except Exception:  # pragma: no cover - dépend de l'environnement
    api_module = None
    HAS_API = False


def _slice(start_marker: str, end_marker: str) -> str:
    start = API_SOURCE.index(start_marker)
    end = API_SOURCE.index(end_marker, start + 1)
    return API_SOURCE[start:end]


class GenerationCorpusGateSourceTest(unittest.TestCase):
    def test_ideas_no_longer_requires_an_analysis(self) -> None:
        """« Je n'ai pas d'idée » appelle POST /ideas en premier."""
        body = _slice('@app.post("/ideas")', '@app.post("/generate")')
        self.assertIn("_generation_influencers", body)
        self.assertNotIn(WIZARD_CORPUS_400, body)
        self.assertNotIn("if not influencers:", body)

    def test_prepare_generate_no_longer_requires_an_analysis(self) -> None:
        """``/generate`` et ``/generate/stream`` passent par ce helper."""
        body = _slice("def _prepare_generate_context", "def _save_generated_variants")
        self.assertIn("_generation_influencers", body)
        self.assertNotIn(WIZARD_CORPUS_400, body)
        self.assertNotIn("if not influencers:", body)

    def test_generate_jobs_no_longer_requires_an_analysis(self) -> None:
        """« J'ai une idée » lance POST /generate/jobs après rôle + structure."""
        body = _slice('@app.post("/generate/jobs")', '@app.get("/generate/jobs")')
        self.assertNotIn(WIZARD_CORPUS_400, body)
        self.assertNotIn("if not influencers:", body)
        self.assertNotIn("_get_influencers", body)

    def test_daily_idea_regenerate_no_longer_requires_an_analysis(self) -> None:
        body = _slice('@app.post("/me/daily-ideas/regenerate")', "class SlackConnectRequest")
        self.assertIn("_generation_influencers", body)
        self.assertNotIn(WIZARD_CORPUS_400, body)
        self.assertNotIn("if not influencers:", body)

    def test_dashboard_ai_analysis_still_requires_a_corpus(self) -> None:
        """L'analyse stratégique n'a rien à dire sans influenceurs : le 400 reste."""
        body = _slice('@app.post("/dashboard/ai-analysis")', "class IdeasRequest")
        self.assertIn("Aucun influenceur analysé.", body)
        self.assertIn("if not influencers:", body)

    def test_chat_still_requires_a_corpus(self) -> None:
        """Le chat Assistant s'appuie sur le benchmark : le 400 historique reste."""
        self.assertIn(WIZARD_CORPUS_400, API_SOURCE)
        body = _slice('@app.post("/chat")', '@app.post("/analyze")')
        self.assertIn(WIZARD_CORPUS_400, body)


class OneLineIdeasEmptyCorpusPromptTest(unittest.TestCase):
    def test_empty_corpus_forbids_inventing_influencers(self) -> None:
        captured: dict = {}

        def fake_call(system, user, **kwargs):
            captured["system"] = system
            captured["user"] = user
            return {"ideas": [{"line": "Annonce : ce que le prix ne dit pas", "source_type": "pattern"}]}

        import src.llm as llm

        with mock.patch.object(llm, "_call", side_effect=fake_call):
            ideas = llm.generate_one_line_ideas(
                real_posts=[],
                benchmark={},
                count=3,
                user_context={"display_name": "Joëlle", "core_offer": "transaction immobilière"},
            )
        self.assertEqual(len(ideas), 1)
        self.assertIn("N'invente ni nom d'influenceur", captured["user"])
        self.assertIn('source_type="pattern" uniquement', captured["user"])
        self.assertNotIn("Ancre chaque idée dans un post réel", captured["user"])

    def test_corpus_present_still_asks_to_anchor_on_real_posts(self) -> None:
        """Le chemin historique (agence avec analyses) ne doit pas régresser."""
        captured: dict = {}

        def fake_call(system, user, **kwargs):
            captured["user"] = user
            return {"ideas": []}

        import src.llm as llm

        with mock.patch.object(llm, "_call", side_effect=fake_call):
            llm.generate_one_line_ideas(
                real_posts=[{"name": "Ada", "engagement": 12, "url": "https://lnkd.in/x", "text": "post"}],
                benchmark={},
                count=3,
            )
        self.assertIn("Ancre chaque idée dans un post réel", captured["user"])
        self.assertNotIn("N'invente ni nom d'influenceur", captured["user"])

    def test_generate_posts_empty_corpus_forbids_inventing_influencers(self) -> None:
        captured: dict = {}

        def fake_call(system, user, **kwargs):
            captured["system"] = system
            captured["user"] = user
            return {"variants": [{"post": "ok", "editorial_role": "story"}]}

        import src.llm as llm

        with mock.patch.object(llm, "_call", side_effect=fake_call):
            llm.generate_posts(
                "Visite ce loft à Nantes",
                top_posts_examples=[],
                benchmark={},
                user_context={"display_name": "Joëlle", "core_offer": "transaction immobilière"},
            )
        self.assertIn("N'invente ni nom d'influenceur", captured["user"])
        self.assertNotIn("Exemples des posts les plus performants", captured["user"])

    def test_generate_posts_with_corpus_still_shows_examples(self) -> None:
        captured: dict = {}

        def fake_call(system, user, **kwargs):
            captured["user"] = user
            return {"variants": [{"post": "ok"}]}

        import src.llm as llm

        with mock.patch.object(llm, "_call", side_effect=fake_call):
            llm.generate_posts(
                "Sujet",
                top_posts_examples=[{"influencer": "Ada", "engagement": 12, "text": "post"}],
                benchmark={"top_hook_types": {"story": 1}},
            )
        self.assertIn("Exemples des posts les plus performants", captured["user"])
        self.assertNotIn("N'invente ni nom d'influenceur", captured["user"])


@unittest.skipUnless(HAS_API, "fastapi absent de cet environnement")
class GenerationWithoutCorpusBehaviourTest(unittest.TestCase):
    """Appelle les fonctions d'endpoint directement (pas de couche HTTP)."""

    def setUp(self) -> None:
        self.env = mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "y"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_ideas_succeeds_with_empty_corpus(self) -> None:
        payload = api_module.IdeasRequest(count=3)
        fake_ideas = [{"line": "Ce que le DPE ne dit pas sur ce 3 pièces", "source_type": "pattern"}]
        with mock.patch.object(api_module, "_generation_influencers", return_value=[]), \
             mock.patch.object(api_module.db, "debit_credits", return_value=(True, 42)) as debit, \
             mock.patch.object(api_module.db, "get_top_real_posts", return_value=[]), \
             mock.patch.object(api_module, "_build_benchmark", return_value=([], {})), \
             mock.patch.object(api_module.db, "get_user_ai_context", return_value={"core_offer": "immo"}), \
             mock.patch.object(api_module.db, "list_generated_ideas", return_value=[]), \
             mock.patch.object(api_module, "generate_one_line_ideas", return_value=fake_ideas) as gen, \
             mock.patch.object(api_module.db, "pick_reference_posts", return_value=[]), \
             mock.patch.object(api_module.db, "get_recent_post_memory", return_value=[]), \
             mock.patch.object(api_module.db, "save_ideas", side_effect=lambda tok, ideas: ideas):
            result = api_module.ideas(payload, token="tok")
        debit.assert_called_once()
        gen.assert_called_once()
        self.assertEqual(gen.call_args.kwargs["real_posts"], [])
        self.assertEqual(result["influencer_count"], 0)
        self.assertEqual(result["ideas"], fake_ideas)
        self.assertEqual(result["credits"], 42)

    def test_generate_jobs_succeeds_with_empty_corpus(self) -> None:
        payload = api_module.GenerationJobRequest(topic="Visite ce loft à Nantes", count=1)
        job = {"id": "job-1", "status": "pending", "topic": payload.topic}
        with mock.patch.object(api_module, "is_listing_url", return_value=False), \
             mock.patch.object(api_module.db, "debit_credits", return_value=(True, 37)) as debit, \
             mock.patch.object(api_module.db, "create_generation_job", return_value=job) as create, \
             mock.patch.object(api_module, "start_generation_job_thread") as start:
            result = api_module.create_generation_job(payload, token="tok")
        debit.assert_called_once()
        create.assert_called_once()
        start.assert_called_once_with("tok", "job-1")
        self.assertEqual(result["id"], "job-1")
        self.assertEqual(result["credits"], 37)

    def test_ideas_still_blocks_on_insufficient_credits(self) -> None:
        """Le 400 corpus ne doit pas masquer le 402 crédits : le débit reste fail-closed."""
        payload = api_module.IdeasRequest(count=3)
        with mock.patch.object(api_module, "_generation_influencers", return_value=[]), \
             mock.patch.object(api_module.db, "debit_credits", return_value=(False, 0)), \
             mock.patch.object(api_module, "generate_one_line_ideas") as gen:
            with self.assertRaises(api_module.HTTPException) as ctx:
                api_module.ideas(payload, token="tok")
        self.assertEqual(ctx.exception.status_code, 402)
        gen.assert_not_called()
