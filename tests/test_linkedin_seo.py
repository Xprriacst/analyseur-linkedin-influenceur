"""Audit SEO du profil LinkedIn (src/linkedin_seo.py) — logique pure.

Ce qui est verrouillé ici, c'est ce qui rendrait l'écran FAUX sans lever la
moindre erreur : un constat qui se trompe, un audit rendu sur un profil jamais
lu, ou une panne du modèle qui emporte les constats mesurés avec elle.
"""
import unittest
from unittest.mock import patch

from src import linkedin_seo
from src.normalize import normalize_profile


def _profile(**seo):
    base = {
        "skills": [], "job_titles": [], "public_identifier": "",
        "banner_url": "", "recommendations_count": 0, "open_to_work": False,
    }
    base.update(seo)
    return {"name": "X", "headline": "h", "summary": "", "seo": base}


def _by_key(findings):
    return {f["key"]: f for f in findings}


class CollectFindingsTest(unittest.TestCase):
    def test_profil_complet_marque_tout_ok(self):
        p = {
            "name": "Emmanuel", "headline": "Consultant SEO | Expert en acquisition e-commerce",
            "summary": "x" * 400,
            "seo": {
                "skills": [f"c{i}" for i in range(12)], "job_titles": ["Consultant SEO"],
                "public_identifier": "emmanuel-bismuth-seo", "banner_url": "https://cdn/b.jpg",
                "recommendations_count": 3, "open_to_work": False,
            },
        }
        self.assertEqual(linkedin_seo.score(linkedin_seo.collect_findings(p)), 100)

    def test_titre_de_statut_est_signale(self):
        # « Founder » ne se cherche pas : personne ne tape ça pour trouver un
        # prestataire. C'est le constat le plus rentable de tout l'audit.
        f = _by_key(linkedin_seo.collect_findings(_profile()) )
        self.assertFalse(f["headline"]["ok"])

    def test_banniere_absente_est_un_fait_pas_une_erreur_de_scrape(self):
        f = _by_key(linkedin_seo.collect_findings(_profile(banner_url="")))
        self.assertFalse(f["banner"]["ok"])
        self.assertIn("défaut", f["banner"]["detail"])

    def test_url_autogeneree_vs_choisie(self):
        auto = _by_key(linkedin_seo.collect_findings(_profile(public_identifier="martin-mourot-547097b6")))
        self.assertFalse(auto["url"]["ok"])
        choisie = _by_key(linkedin_seo.collect_findings(_profile(public_identifier="emmanuel-bismuth-seo")))
        self.assertTrue(choisie["url"]["ok"])

    def test_un_nom_a_rallonge_sans_chiffre_reste_une_url_choisie(self):
        # Garde-fou du faux positif inverse : un nom composé long ne doit pas
        # être pris pour un hash LinkedIn.
        f = _by_key(linkedin_seo.collect_findings(_profile(public_identifier="jean-baptiste-de-la-tour")))
        self.assertTrue(f["url"]["ok"])

    def test_posture_de_demandeur_signalee(self):
        f = _by_key(linkedin_seo.collect_findings(_profile(open_to_work=True)))
        self.assertIn("posture", f)

    def test_posture_absente_quand_le_profil_ne_quemande_pas(self):
        f = _by_key(linkedin_seo.collect_findings(_profile()))
        self.assertNotIn("posture", f)


class AuditTest(unittest.TestCase):
    def test_aucun_profil_lu_aucun_audit(self):
        # On n'audite pas un compte qu'on n'a pas vu : l'entrée par un site web
        # ne doit JAMAIS produire « ton profil est incomplet ».
        self.assertIsNone(linkedin_seo.audit({}))
        self.assertIsNone(linkedin_seo.audit(None))

    def test_modele_en_panne_les_constats_survivent(self):
        p = _profile(banner_url="")
        with patch.object(linkedin_seo.llm, "_call", side_effect=RuntimeError("boom")):
            out = linkedin_seo.audit(p, with_banner=False)
        self.assertIsNotNone(out)
        self.assertTrue(out["findings"])          # les faits mesurés restent
        self.assertEqual(out["keywords"], [])     # ce qui vient du modèle, non
        self.assertEqual(out["priorities"], [])

    def test_banniere_illisible_pas_de_verdict_invente(self):
        p = _profile(banner_url="https://cdn/mort.jpg")
        with patch.object(linkedin_seo, "fetch_banner", return_value=None), \
             patch.object(linkedin_seo.llm, "_call", return_value={"keywords": [], "priorities": [], "banner_verdict": "…"}):
            out = linkedin_seo.audit(p)
        self.assertTrue(out["has_banner"])        # elle existe
        self.assertFalse(out["banner_reviewed"])  # mais on ne l'a pas regardée

    def test_image_transmise_au_modele_quand_la_banniere_est_lue(self):
        p = _profile(banner_url="https://cdn/b.jpg")
        captured = {}

        def fake_call(system, user, **kwargs):
            captured.update(kwargs)
            return {"keywords": ["#seo", " growth "], "priorities": ["a", "b", "c", "d"], "banner_verdict": " ok "}

        with patch.object(linkedin_seo, "fetch_banner", return_value=("image/png", b"\x89PNG")), \
             patch.object(linkedin_seo.llm, "_call", side_effect=fake_call):
            out = linkedin_seo.audit(p)
        self.assertEqual(captured.get("images"), [("image/png", b"\x89PNG")])
        self.assertTrue(out["banner_reviewed"])
        self.assertEqual(out["keywords"], ["seo", "growth"])   # « # » retiré, trim
        self.assertEqual(len(out["priorities"]), 3)            # borné à 3
        self.assertEqual(out["banner_verdict"], "ok")


class NormalizeSeoSignalsTest(unittest.TestCase):
    """Les signaux étaient DÉJÀ scrapés et jetés — ils doivent remonter des deux
    schémas d'acteur, sinon l'audit s'exécute sur du vide selon le scraper."""

    def test_schema_harvestapi(self):
        seo = normalize_profile({
            "firstName": "E", "lastName": "B", "headline": "h",
            "publicIdentifier": "e-b-seo",
            "coverPicture": {"sizes": [{"width": 800, "url": "https://c/8.jpg"},
                                       {"width": 1400, "url": "https://c/14.jpg"}]},
            "topSkills": ["SEO"], "skills": [{"name": "SEA"}, {"name": "SEO"}],
            "experience": [{"position": "Consultant SEO"}, {"position": "Consultant SEO"}],
            "receivedRecommendations": [{"givenBy": "A"}, {"givenBy": "B"}],
        })["seo"]
        self.assertEqual(seo["banner_url"], "https://c/14.jpg")  # la plus grande
        self.assertEqual(seo["skills"], ["SEO", "SEA"])          # dédoublonné, ordre gardé
        self.assertEqual(seo["job_titles"], ["Consultant SEO"])
        self.assertEqual(seo["recommendations_count"], 2)

    def test_schema_apimaestro(self):
        seo = normalize_profile({"basic_info": {
            "fullname": "A B", "headline": "h",
            "background_picture_url": "https://c/bg.png",
            "top_skills": ["IA"], "public_identifier": "a-b", "open_to_work": True,
        }})["seo"]
        self.assertEqual(seo["banner_url"], "https://c/bg.png")
        self.assertEqual(seo["skills"], ["IA"])
        self.assertTrue(seo["open_to_work"])

    def test_profil_sans_banniere_rend_une_chaine_vide_pas_une_erreur(self):
        self.assertEqual(normalize_profile({"firstName": "A"})["seo"]["banner_url"], "")


if __name__ == "__main__":
    unittest.main()
