"""Surcharges de modèle par usage (Notion « Modèles IA par usage »).

Trois nouvelles variables d'env, patron `_scoring_model`/`_memory_card_model`
déjà en place (`os.environ.get("X_MODEL", _model())`) : absence de variable =
comportement actuel inchangé, aucune régression possible.

- CLASSIFY_MODEL   -> classify_posts (haut volume, modèle léger)
- STRATEGY_MODEL   -> synthesize_strategy + analyze_dashboard_strategy
                      (ce que le client lit directement)
- EDITORIAL_PROFILE_MODEL -> draft_editorial_profile (conditionne toute la
                      génération ensuite)
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import src.llm as llm


def _fake_call_capturing(result: dict):
    captured = {}

    def fake_call(system, user, **kwargs):
        captured.update(kwargs)
        return result

    return captured, fake_call


class ClassifyModelOverrideTest(unittest.TestCase):
    def test_no_env_var_falls_back_to_configured_model(self):
        captured, fake_call = _fake_call_capturing({"classifications": []})
        with patch.object(llm, "_call", side_effect=fake_call):
            with patch.dict("os.environ", {}, clear=False):
                import os

                os.environ.pop("CLASSIFY_MODEL", None)
                llm.classify_posts([{"format": "text", "text": "Un post."}])
        self.assertEqual(captured.get("model"), llm._model())

    def test_env_var_overrides_model_for_this_call_only(self):
        captured, fake_call = _fake_call_capturing({"classifications": []})
        with patch.object(llm, "_call", side_effect=fake_call):
            with patch.dict("os.environ", {"CLASSIFY_MODEL": "claude-haiku-4-5"}):
                llm.classify_posts([{"format": "text", "text": "Un post."}])
        self.assertEqual(captured.get("model"), "claude-haiku-4-5")


class StrategyModelOverrideTest(unittest.TestCase):
    _VALID_SYNTHESIS = {
        "positioning": "",
        "audience": "",
        "content_pillars": [],
        "hook_patterns": [],
        "structural_patterns": [],
        "cta_strategy": "",
        "strengths": [],
        "gaps": [],
        "actions_to_replicate": [],
    }

    def test_synthesize_strategy_no_env_var_falls_back(self):
        captured, fake_call = _fake_call_capturing(self._VALID_SYNTHESIS)
        with patch.object(llm, "_call", side_effect=fake_call):
            with patch.dict("os.environ", {}, clear=False):
                import os

                os.environ.pop("STRATEGY_MODEL", None)
                llm.synthesize_strategy({}, [], [])
        self.assertEqual(captured.get("model"), llm._model())

    def test_synthesize_strategy_env_var_overrides(self):
        captured, fake_call = _fake_call_capturing(self._VALID_SYNTHESIS)
        with patch.object(llm, "_call", side_effect=fake_call):
            with patch.dict("os.environ", {"STRATEGY_MODEL": "claude-opus-5"}):
                llm.synthesize_strategy({}, [], [])
        self.assertEqual(captured.get("model"), "claude-opus-5")

    def test_analyze_dashboard_strategy_env_var_overrides(self):
        # analyze_dashboard_strategy n'utilise pas _call() (appel direct au
        # client) : on capture le kwarg model passé à client.messages.create.
        captured = {}

        class FakeMessages:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text="## Analyse")],
                    stop_reason="end_turn",
                    usage=None,
                )

        fake_client = SimpleNamespace(messages=FakeMessages())
        with patch.object(llm, "_client", return_value=fake_client):
            with patch.object(llm, "_web_search_tools", return_value=[]):
                with patch.dict("os.environ", {"STRATEGY_MODEL": "claude-opus-5"}):
                    llm.analyze_dashboard_strategy([{"name": "x"}])
        self.assertEqual(captured.get("model"), "claude-opus-5")

    def test_analyze_dashboard_strategy_no_env_var_falls_back(self):
        captured = {}

        class FakeMessages:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text="## Analyse")],
                    stop_reason="end_turn",
                    usage=None,
                )

        fake_client = SimpleNamespace(messages=FakeMessages())
        with patch.object(llm, "_client", return_value=fake_client):
            with patch.object(llm, "_web_search_tools", return_value=[]):
                with patch.dict("os.environ", {}, clear=False):
                    import os

                    os.environ.pop("STRATEGY_MODEL", None)
                    llm.analyze_dashboard_strategy([{"name": "x"}])
        self.assertEqual(captured.get("model"), llm._model())


class EditorialProfileModelOverrideTest(unittest.TestCase):
    _VALID_PROFILE = {"profile": {k: "" for k in llm.EDITORIAL_PROFILE_KEYS}}

    def test_no_env_var_falls_back_to_configured_model(self):
        captured, fake_call = _fake_call_capturing(self._VALID_PROFILE)
        with patch.object(llm, "_call", side_effect=fake_call):
            with patch.dict("os.environ", {}, clear=False):
                import os

                os.environ.pop("EDITORIAL_PROFILE_MODEL", None)
                llm.draft_editorial_profile({"description": "Un consultant."})
        self.assertEqual(captured.get("model"), llm._model())

    def test_env_var_overrides_model_for_this_call_only(self):
        captured, fake_call = _fake_call_capturing(self._VALID_PROFILE)
        with patch.object(llm, "_call", side_effect=fake_call):
            with patch.dict("os.environ", {"EDITORIAL_PROFILE_MODEL": "claude-opus-5"}):
                llm.draft_editorial_profile({"description": "Un consultant."})
        self.assertEqual(captured.get("model"), "claude-opus-5")


if __name__ == "__main__":
    unittest.main()
