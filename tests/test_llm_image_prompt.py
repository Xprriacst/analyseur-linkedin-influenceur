import unittest
from unittest.mock import patch

from src.llm import generate_image_prompt


class GenerateImagePromptTest(unittest.TestCase):
    def test_returns_validated_image_prompt_payload(self):
        fake_payload = {
            "visual_concept": "Un pont entre idee et execution",
            "composition": "Sujet central, trois blocs simples, espace blanc genereux",
            "style": "Illustration vectorielle B2B minimaliste",
            "colors": ["bleu nuit", "violet", "blanc casse"],
            "text_overlay": "De l'idee au post",
            "negative_prompt": "pas de logo, pas de capture d'ecran, pas de texte long",
            "image_prompt": "Create a minimalist B2B vector illustration...",
        }

        with patch("src.llm._call", return_value=fake_payload) as call:
            result = generate_image_prompt(
                "Post LinkedIn sur la transformation d'une idee en contenu actionnable.",
                angle="Montrer le passage de l'intuition au systeme.",
                tone="premium et clair",
            )

        self.assertEqual(result, fake_payload)
        _, user_prompt = call.call_args.args[:2]
        self.assertIn("Montrer le passage de l'intuition au systeme.", user_prompt)
        self.assertIn("premium et clair", user_prompt)


if __name__ == "__main__":
    unittest.main()
