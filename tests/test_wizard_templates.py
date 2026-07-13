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


class SuggestStructuresTest(unittest.TestCase):
    """Les 3 structures proposées au client, la plus adaptée en tête.

    Le client doit pouvoir LIRE ce qu'il choisit : on rend les entrées de
    bibliothèque, pas des identifiants nus. Et une liste vide doit rester
    possible — c'est le signal qui fait enchaîner le parcours en structure libre
    plutôt que de bloquer un compte neuf sur une étape sans option.
    """

    def test_bibliotheque_vide_ne_propose_rien_et_ne_coute_rien(self):
        """Compte neuf : aucune option, aucun appel LLM à payer → structure libre en aval."""
        with patch.object(llm, "_call") as call:
            self.assertEqual(llm.suggest_structures("mon idée", "story", []), [])
        call.assert_not_called()

    def test_entree_sans_structure_ni_texte_ecartee(self):
        """Une entrée vide n'apprend rien au modèle et ne peut rien structurer."""
        library = [{"id": "vide"}, {"id": "tpl-1", "post_text": "Un vrai post."}]
        with patch.object(llm, "_call") as call:
            suggested = llm.suggest_structures("mon idée", "story", library)
        call.assert_not_called()  # une seule entrée utilisable : rien à choisir
        self.assertEqual([t["id"] for t in suggested], ["tpl-1"])

    def test_rend_les_entrees_completes_pas_des_identifiants(self):
        """Le client lit le nom et la structure : un id nu ne lui dirait rien."""
        with patch.object(llm, "_call", return_value={"template_ids": ["tpl-2"]}):
            suggested = llm.suggest_structures("mon idée", "story", _library(6))
        self.assertEqual(suggested[0]["structure_label"], "Structure 2")
        self.assertIn("structure_text", suggested[0])

    def test_trois_structures_distinctes_la_plus_adaptee_en_tete(self):
        with patch.object(llm, "_call", return_value={"template_ids": ["tpl-4", "tpl-1", "tpl-5"]}):
            suggested = llm.suggest_structures("mon idée", "story", _library(6))
        self.assertEqual([t["id"] for t in suggested], ["tpl-4", "tpl-1", "tpl-5"])
        self.assertEqual(len({t["id"] for t in suggested}), 3)

    def test_doublon_du_modele_ne_propose_pas_deux_fois_la_meme(self):
        """Deux fois la même option dans une liste de choix : le client ne comprendrait pas."""
        with patch.object(llm, "_call", return_value={"template_ids": ["tpl-2", "tpl-2", "tpl-2"]}):
            suggested = llm.suggest_structures("mon idée", "story", _library(6))
        self.assertEqual(len({t["id"] for t in suggested}), len(suggested))

    def test_modele_en_panne_propose_quand_meme_des_structures(self):
        """Anthropic indisponible : le client garde des options, il n'est pas coincé."""
        with patch.object(llm, "_call", side_effect=RuntimeError("Anthropic indisponible")):
            suggested = llm.suggest_structures("mon idée", "story", _library(6))
        self.assertEqual([t["id"] for t in suggested], ["tpl-1", "tpl-2", "tpl-3"])


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
