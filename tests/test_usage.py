"""Table de prix Anthropic (src/usage.py) — recalage sur les tarifs réels.

L'ancienne table matchait par sous-chaîne ("sonnet"/"haiku", sinon "opus" par
défaut) : un modèle qui n'était ni l'un ni l'autre (Fable, un futur modèle)
tombait silencieusement sur le tarif Opus — deux fois trop bas pour Fable.
Ces tests verrouillent le match par identifiant EXACT + le repli explicite.
"""
import unittest

from src import usage


class AnthropicPriceTest(unittest.TestCase):
    def test_known_models_use_their_exact_price(self):
        self.assertEqual(usage._anthropic_price("claude-opus-5"), {"input": 5.0, "output": 25.0})
        self.assertEqual(usage._anthropic_price("claude-sonnet-5"), {"input": 2.0, "output": 10.0})
        self.assertEqual(usage._anthropic_price("claude-haiku-4-5"), {"input": 1.0, "output": 5.0})

    def test_fable_is_not_silently_priced_as_opus(self):
        # Le bug corrigé : Fable (2x le prix d'Opus) tombait sur le tarif Opus
        # via le match par sous-chaîne "opus" par défaut.
        price = usage._anthropic_price("claude-fable-5-1")
        self.assertEqual(price, {"input": 10.0, "output": 50.0})
        self.assertNotEqual(price, usage._anthropic_price("claude-opus-5"))

    def test_unknown_model_falls_back_explicitly_not_by_substring(self):
        # Un modèle absent de la table retombe sur le repli documenté — pas
        # sur un match "contient opus/sonnet/haiku" qui pourrait se tromper.
        self.assertEqual(
            usage._anthropic_price("claude-unreleased-9"),
            usage._DEFAULT_PRICE_PER_MTOK,
        )

    def test_substring_matching_is_gone(self):
        # Un identifiant qui contient "sonnet" ou "haiku" en sous-chaîne mais
        # n'est pas un modèle connu ne doit plus matcher par accident.
        self.assertEqual(
            usage._anthropic_price("my-custom-sonnet-wrapper"),
            usage._DEFAULT_PRICE_PER_MTOK,
        )

    def test_track_anthropic_uses_exact_model_price(self):
        usage.reset_usage()
        usage.track_anthropic("claude-sonnet-5", input_tokens=1_000_000, output_tokens=1_000_000)
        data = usage.get_usage()
        self.assertAlmostEqual(data["anthropic"]["estimated_cost_usd"], 12.0)


if __name__ == "__main__":
    unittest.main()
