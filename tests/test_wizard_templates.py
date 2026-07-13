"""ALE-286 — Choix des 3 templates du parcours de génération.

Le parcours promet TROIS posts appuyés sur TROIS structures différentes. Ce
choix est confié au modèle, donc faillible de trois façons : il peut inventer un
identifiant (qui ferait échouer l'insertion du job sur la clé étrangère), en
rendre moins de trois, ou ne pas répondre du tout.

Aucune de ces trois pannes ne doit empêcher un client d'obtenir ses posts — pas
plus qu'une bibliothèque vide (le cas de tout compte neuf). C'est ce que ce
fichier verrouille : le repli, pas le choix lui-même.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src import llm


def _library(n: int) -> list[dict]:
    return [
        {"id": f"tpl-{i}", "structure_label": f"Structure {i}", "structure_text": f"Étape {i}"}
        for i in range(1, n + 1)
    ]


class PickTemplatesTest(unittest.TestCase):
    def test_bibliotheque_plus_petite_que_demande_rend_tout_sans_appeler_le_modele(self):
        """2 entrées pour 3 posts : rien à choisir — et surtout, aucun appel LLM à payer."""
        with patch.object(llm, "_call") as call:
            picked = llm.pick_templates_for_idea("mon idée", "story", _library(2), count=3)
        call.assert_not_called()
        self.assertEqual(picked, ["tpl-1", "tpl-2"])

    def test_bibliotheque_vide_rend_une_liste_vide(self):
        """Compte neuf : l'appelant complète en structure libre, il n'est jamais bloqué."""
        with patch.object(llm, "_call") as call:
            self.assertEqual(llm.pick_templates_for_idea("mon idée", "story", [], count=3), [])
        call.assert_not_called()

    def test_choix_du_modele_respecte_dans_son_ordre(self):
        with patch.object(llm, "_call", return_value={"template_ids": ["tpl-4", "tpl-1", "tpl-5"]}):
            picked = llm.pick_templates_for_idea("mon idée", "story", _library(6), count=3)
        self.assertEqual(picked, ["tpl-4", "tpl-1", "tpl-5"])

    def test_identifiant_invente_ecarte_puis_complete(self):
        """Un id inventé passerait la clé étrangère à la trappe : on l'écarte et on comble."""
        with patch.object(llm, "_call", return_value={"template_ids": ["tpl-9000", "tpl-3"]}):
            picked = llm.pick_templates_for_idea("mon idée", "story", _library(6), count=3)
        self.assertNotIn("tpl-9000", picked)
        self.assertIn("tpl-3", picked)
        self.assertEqual(len(picked), 3)
        self.assertEqual(len(set(picked)), 3, "les 3 templates doivent être distincts")

    def test_doublon_rendu_par_le_modele_ne_donne_pas_deux_fois_la_meme_structure(self):
        with patch.object(llm, "_call", return_value={"template_ids": ["tpl-2", "tpl-2", "tpl-2"]}):
            picked = llm.pick_templates_for_idea("mon idée", "story", _library(6), count=3)
        self.assertEqual(len(set(picked)), 3)

    def test_modele_en_panne_replie_sur_la_bibliotheque(self):
        """Anthropic indisponible : le client obtient quand même 3 structures."""
        with patch.object(llm, "_call", side_effect=RuntimeError("Anthropic indisponible")):
            picked = llm.pick_templates_for_idea("mon idée", "story", _library(6), count=3)
        self.assertEqual(picked, ["tpl-1", "tpl-2", "tpl-3"])

    def test_reponse_vide_replie_sur_la_bibliotheque(self):
        with patch.object(llm, "_call", return_value={}):
            picked = llm.pick_templates_for_idea("mon idée", "story", _library(6), count=3)
        self.assertEqual(len(picked), 3)


class PlanWizardTemplatesTest(unittest.TestCase):
    """La promesse faite au client est « 3 posts », pas « 3 templates ».

    Trois cases à remplir : un template dans chacune quand la bibliothèque suit,
    « structure libre » (None) sinon. Rendre moins de trois posts alors que trois
    ont été facturés serait le pire des échecs — silencieux.
    """

    def test_bibliotheque_vide_rend_trois_cases_en_structure_libre(self):
        """Compte neuf : il obtient quand même ses 3 posts, sans appel LLM à payer."""
        with patch.object(llm, "_call") as call:
            plan = llm.plan_wizard_templates("mon idée", "story", [])
        call.assert_not_called()
        self.assertEqual(plan, [None, None, None])

    def test_une_seule_entree_utilisable_complete_les_deux_autres(self):
        with patch.object(llm, "_call") as call:
            plan = llm.plan_wizard_templates("mon idée", "story", _library(1))
        call.assert_not_called()  # rien à choisir : 1 entrée pour 3 cases
        self.assertEqual(plan, ["tpl-1", None, None])

    def test_entree_sans_structure_ni_texte_ignoree(self):
        """Une entrée vide n'apprend rien au modèle et ne peut rien structurer."""
        library = [{"id": "vide"}, {"id": "tpl-1", "post_text": "Un vrai post."}]
        with patch.object(llm, "_call"):
            plan = llm.plan_wizard_templates("mon idée", "story", library)
        self.assertEqual(plan, ["tpl-1", None, None])

    def test_bibliotheque_fournie_rend_trois_templates_distincts(self):
        """Le modèle rend un doublon : la répartition doit quand même sortir 3 structures."""
        with patch.object(llm, "_call", return_value={"template_ids": ["tpl-2", "tpl-2", "tpl-5"]}):
            plan = llm.plan_wizard_templates("mon idée", "story", _library(6))
        self.assertEqual(len(plan), 3)
        self.assertNotIn(None, plan)
        self.assertEqual(len(set(plan)), 3, "trois structures DIFFÉRENTES, c'est la promesse")

    def test_toujours_exactement_trois_cases(self):
        """Le modèle sur-génère : on facture 3 posts, on en produit 3, pas 4."""
        with patch.object(llm, "_call", return_value={"template_ids": ["tpl-1", "tpl-2", "tpl-3", "tpl-4"]}):
            self.assertEqual(len(llm.plan_wizard_templates("mon idée", "story", _library(8))), 3)


class RecommendRoleTest(unittest.TestCase):
    def test_role_inconnu_replie_sur_un_role_valide(self):
        """Un rôle inventé ferait échouer la génération : on ne le laisse pas sortir."""
        with patch.object(llm, "_call", return_value={"editorial_role": "poete_maudit", "reason": "…"}):
            reco = llm.recommend_editorial_role("mon idée")
        self.assertIn(reco["editorial_role"], llm.ROLE_SPECS)

    def test_role_connu_conserve_avec_sa_justification(self):
        with patch.object(llm, "_call", return_value={"editorial_role": "story", "reason": "C'est du vécu."}):
            reco = llm.recommend_editorial_role("mon idée")
        self.assertEqual(reco, {"editorial_role": "story", "reason": "C'est du vécu."})


if __name__ == "__main__":
    unittest.main()
