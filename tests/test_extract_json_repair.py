"""Réparation JSON : guillemets internes non échappés dans un post généré.

Reproduit le bug « Expecting ',' delimiter » remonté par Alex : le modèle
glisse un `"` dans le corps du post sans l'échapper → json.loads casse en
plein milieu du texte.
"""
import json
import unittest

from src.llm import _extract_json, _loads_lenient, _repair_inner_quotes


class ExtractJsonRepairTest(unittest.TestCase):
    def test_unescaped_inner_quote_is_repaired(self):
        padding = "a" * 1380  # place l'erreur autour du char 1400, comme en prod
        bad = (
            '{"variants":[{"post":"'
            + padding
            + ' il m\'a dit "banco" et c\'est parti",'
            + '"hook_type":"question"}]}'
        )
        # le parse strict casse exactement comme en prod
        with self.assertRaises(json.JSONDecodeError):
            json.loads(bad)
        data = _extract_json(bad)
        post = data["variants"][0]["post"]
        self.assertIn('"banco"', post)
        self.assertTrue(post.endswith("c'est parti"))
        self.assertEqual(data["variants"][0]["hook_type"], "question")

    def test_multiple_inner_quotes(self):
        bad = '{"post":"un "mot" puis "un autre" ici","k":1}'
        data = _loads_lenient(bad)
        self.assertEqual(data["post"], 'un "mot" puis "un autre" ici')
        self.assertEqual(data["k"], 1)

    def test_literal_newline_still_ok(self):
        data = _loads_lenient('{"post":"ligne1\nligne2"}')
        self.assertEqual(data["post"].count("\n"), 1)

    def test_already_valid_json_untouched(self):
        good = '{"post":"il dit \\"ok\\" vraiment","k":2}'
        data = _loads_lenient(good)
        self.assertEqual(data["post"], 'il dit "ok" vraiment')
        self.assertEqual(data["k"], 2)

    def test_repair_is_noop_on_valid_string(self):
        # une chaîne déjà correcte ne doit pas être altérée par la réparation
        self.assertEqual(
            _repair_inner_quotes('{"a":"b","c":"d"}'), '{"a":"b","c":"d"}'
        )

    def test_fenced_json_with_inner_quote(self):
        text = '```json\n{"post":"il a dit "oui" enfin"}\n```'
        self.assertEqual(_extract_json(text)["post"], 'il a dit "oui" enfin')


if __name__ == "__main__":
    unittest.main()
