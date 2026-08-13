"""Script de reel : le champ `script` ne porte QUE le texte prononcé.

Le script est lu tel quel — par le client face caméra, et surtout par son
avatar IA (HeyGen lit le champ mot pour mot). Une indication de tournage qui y
reste est donc PRONONCÉE dans la vidéo livrée, sans qu'aucune erreur ne soit
levée nulle part : c'est le genre de panne qu'on ne voit qu'en regardant la
vidéo finie. D'où ces tests.
"""
from __future__ import annotations

import unittest

from src.llm import normalize_shots, spoken_script

# Sortie réelle du modèle avant la séparation script / plan de tournage.
LEGACY_PACK = (
    "1. CE QU'ON DIT : « J'ai passé 6 mois à automatiser des installs techniques. "
    "Ce guide, je le vendais 47€ il y a encore 3 semaines. » "
    "CE QU'ON MONTRE : plan fixe, cadrage épaules, regard caméra direct.\n"
    "2. CE QU'ON DIT : « À l'intérieur : la checklist exacte que j'utilise avant "
    "chaque install, les 5 erreurs qui font planter 80% des setups. »\n"
    "   CE QU'ON MONTRE : léger zoom, main qui compte sur les doigts.\n"
    "3. CE QU'ON DIT : « Commente AGENT, je te l'envoie en DM dans la journée. »\n"
    "   Visuel : texte incrusté « COMMENTE AGENT »."
)


class SpokenScriptTest(unittest.TestCase):
    def test_ne_garde_que_le_texte_dit(self):
        out = spoken_script(LEGACY_PACK)
        self.assertIn("J'ai passé 6 mois à automatiser des installs techniques.", out)
        self.assertIn("Commente AGENT, je te l'envoie en DM dans la journée.", out)
        # Aucune didascalie ne survit : c'est ce que l'avatar prononcerait.
        for direction in ("CE QU'ON", "plan fixe", "cadrage épaules", "léger zoom", "incrusté"):
            self.assertNotIn(direction, out)

    def test_ni_numero_de_scene_ni_guillemets_enveloppants(self):
        out = spoken_script(LEGACY_PACK)
        self.assertFalse(out.startswith(("1", "«")), out[:40])
        self.assertNotIn("«", out)

    def test_script_deja_propre_reste_intact(self):
        clean = (
            "J'ai passé 6 mois à automatiser des installs techniques.\n\n"
            "À l'intérieur : la checklist exacte que j'utilise.\n\n"
            "Commente AGENT, je te l'envoie en DM."
        )
        self.assertEqual(spoken_script(clean), clean)

    def test_idempotent(self):
        once = spoken_script(LEGACY_PACK)
        self.assertEqual(spoken_script(once), once)

    def test_ne_mange_pas_une_phrase_qui_commence_par_un_mot_ambigu(self):
        # « Plan B : … » ou « Image de marque : … » sont des phrases que le
        # client dit vraiment — les couper amputerait le script en silence.
        parle = "Plan B : tu changes de fournisseur.\nImage de marque : on oublie."
        self.assertEqual(spoken_script(parle), parle)

    def test_vide_et_none(self):
        self.assertEqual(spoken_script(""), "")
        self.assertEqual(spoken_script(None), "")  # type: ignore[arg-type]

    def test_script_entierement_didascalique_donne_vide(self):
        # Le serveur s'en sert pour refuser proprement au lieu de faire dire
        # « plan fixe » à l'avatar.
        self.assertEqual(spoken_script("CE QU'ON MONTRE : plan fixe.\nVisuel : cut sec."), "")


class NormalizeShotsTest(unittest.TestCase):
    def test_liste_nettoyee(self):
        self.assertEqual(
            normalize_shots(["1. Plan fixe.", "CE QU'ON MONTRE : léger zoom.", "  ", "Cut sec."]),
            ["Plan fixe.", "léger zoom.", "Cut sec."],
        )

    def test_chaine_multiligne_acceptee(self):
        self.assertEqual(normalize_shots("Plan fixe.\n\nCut sec."), ["Plan fixe.", "Cut sec."])

    def test_schema_inattendu_du_modele(self):
        # Tolérance de schéma : le modèle range parfois la scène dans un objet.
        self.assertEqual(
            normalize_shots([{"scene": 1, "montre": "Carton final."}]), ["Carton final."]
        )
        self.assertEqual(normalize_shots(None), [])
        self.assertEqual(normalize_shots(42), [])

    def test_plafonne(self):
        self.assertEqual(len(normalize_shots([f"Scène {i}" for i in range(30)])), 12)


class PromptContractTest(unittest.TestCase):
    """Le prompt doit continuer d'exiger la séparation — sinon le nettoyage
    ci-dessus deviendrait le seul rempart, et il rognerait du texte utile."""

    def test_les_garde_fous_demandent_les_deux_champs(self):
        from src.llm import REEL_QUALITY_GUARDRAILS

        self.assertIn('"script"', REEL_QUALITY_GUARDRAILS)
        self.assertIn('"shots"', REEL_QUALITY_GUARDRAILS)
        self.assertIn("QUE le texte prononcé", REEL_QUALITY_GUARDRAILS)


if __name__ == "__main__":
    unittest.main()
