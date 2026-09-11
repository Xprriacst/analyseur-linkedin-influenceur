"""Réparation JSON : guillemets internes et virgules finales dans un post généré.

Reproduit deux bugs remontés par Alex :
- « Expecting ',' delimiter » : le modèle glisse un `"` dans le corps du
  post sans l'échapper → json.loads casse en plein milieu du texte.
- « Illegal trailing comma before end of object » : le modèle termine le
  dernier champ d'un objet par une virgule (style JS) → json.loads refuse
  même en strict=False.
"""
import json
import unittest

from src.llm import (
    _extract_json,
    _loads_lenient,
    _repair_inner_quotes,
    _strip_trailing_commas,
)


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

    def test_trailing_comma_before_end_of_object(self):
        # Reproduit « Illegal trailing comma before end of object: line 8 column 973 (char 1460) »
        padding = "a" * 950
        bad = (
            "{\n"
            '  "variants": [\n'
            "    {\n"
            '      "editorial_role": "story",\n'
            '      "hook_type": "question",\n'
            '      "strategy": "lien",\n'
            '      "predicted_lift": "conversation",\n'
            f'      "post": "{padding}",\n'
            "    }\n"
            "  ]\n"
            "}"
        )
        with self.assertRaises(json.JSONDecodeError) as ctx:
            json.loads(bad)
        msg = str(ctx.exception).lower()
        self.assertTrue(
            "trailing comma" in msg or "expecting property name" in msg,
            msg,
        )
        data = _extract_json(bad)
        self.assertEqual(data["variants"][0]["post"], padding)
        self.assertEqual(data["variants"][0]["editorial_role"], "story")
        self.assertEqual(data["variants"][0]["hook_type"], "question")

    def test_trailing_comma_before_end_of_array(self):
        bad = '{"variants":[{"post":"hello"},]}'
        with self.assertRaises(json.JSONDecodeError):
            json.loads(bad)
        self.assertEqual(_extract_json(bad)["variants"][0]["post"], "hello")

    def test_trailing_comma_and_inner_quote_together(self):
        bad = '{"post":"il m\'a dit "banco" et c\'est parti","k":1,}'
        with self.assertRaises(json.JSONDecodeError):
            json.loads(bad)
        data = _loads_lenient(bad)
        self.assertEqual(data["post"], 'il m\'a dit "banco" et c\'est parti')
        self.assertEqual(data["k"], 1)

    def test_comma_inside_post_body_is_kept(self):
        good = '{"post":"wait, } still going","k":2}'
        self.assertEqual(_strip_trailing_commas(good), good)
        data = _loads_lenient(good)
        self.assertEqual(data["post"], "wait, } still going")
        self.assertEqual(data["k"], 2)

    def test_strip_is_noop_on_valid_object(self):
        good = '{"a":1,"b":[2,3]}'
        self.assertEqual(_strip_trailing_commas(good), good)

    def test_nested_trailing_commas(self):
        bad = '{"a":{"b":1,},}'
        with self.assertRaises(json.JSONDecodeError):
            json.loads(bad)
        self.assertEqual(_extract_json(bad), {"a": {"b": 1}})

    def test_quote_repair_alone_does_not_fix_trailing_comma(self):
        # vérifié par la négative : sans _strip_trailing_commas, le JSON d'Alex
        # resterait illisible (la passe guillemets #377 ne touche pas la virgule).
        bad = '{"a":1,}'
        with self.assertRaises(json.JSONDecodeError):
            json.loads(_repair_inner_quotes(bad))
        self.assertEqual(_loads_lenient(bad), {"a": 1})


if __name__ == "__main__":
    unittest.main()
