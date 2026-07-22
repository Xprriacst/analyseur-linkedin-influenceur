"""Tests des feature flags (déploiement progressif).

Ce module décide qui voit quoi. Les cas couverts ici sont ceux où une erreur ouvre
une fonctionnalité à quelqu'un qui ne devrait pas l'avoir — pas les cas nominaux.
"""
import unittest

from src import features


def user(**meta):
    return {"id": "u1", "email": "x@y.z", "app_metadata": meta}


class GrantTest(unittest.TestCase):
    def test_flag_posed_on_the_account_grants_it(self):
        self.assertTrue(features.has_feature(user(features=["autopilot"]), "autopilot"))

    def test_account_without_flag_has_nothing(self):
        self.assertFalse(features.has_feature(user(), "autopilot"))
        self.assertFalse(features.has_feature(user(features=[]), "autopilot"))

    def test_other_metadata_does_not_grant(self):
        """Le rôle `ideas_only` cohabite dans app_metadata : il ne doit rien ouvrir."""
        self.assertFalse(features.has_feature(user(role="ideas_only"), "autopilot"))

    def test_a_flag_grants_only_itself(self):
        u = user(features=["autopilot"])
        self.assertFalse(features.has_feature(u, "une-autre-feature"))

    def test_unknown_flag_name_grants_nothing(self):
        """Un nom mal orthographié ne doit pas ouvrir autre chose en silence."""
        self.assertEqual(features.features_of(user(features=["autopilott"])), set(features.DEFAULT_FEATURES))

    def test_case_and_spacing_tolerated(self):
        self.assertTrue(features.has_feature(user(features=["  AutoPilot "]), "autopilot"))

    def test_string_instead_of_list_is_tolerated(self):
        """Une valeur posée à la main en SQL peut être une chaîne plutôt qu'un tableau."""
        self.assertTrue(features.has_feature(user(features="autopilot"), "autopilot"))


class FailClosedTest(unittest.TestCase):
    """Un doute sur l'identité ne doit JAMAIS ouvrir une fonctionnalité en bêta."""

    def test_no_user_grants_nothing(self):
        self.assertFalse(features.has_feature(None, "autopilot"))

    def test_missing_or_malformed_metadata_grants_nothing(self):
        self.assertFalse(features.has_feature({"id": "u1"}, "autopilot"))
        self.assertFalse(features.has_feature({"app_metadata": None}, "autopilot"))
        self.assertFalse(features.has_feature({"app_metadata": "nimportequoi"}, "autopilot"))
        self.assertFalse(features.has_feature({"app_metadata": {"features": 42}}, "autopilot"))


class UserMetadataIsNotATrustSourceTest(unittest.TestCase):
    """LE test de sécurité de ce module.

    `user_metadata` est modifiable par l'utilisateur lui-même depuis son navigateur
    (`supabase.auth.updateUser`). S'il y suffisait de poser `features: ["autopilot"]`
    pour ouvrir la fonctionnalité, n'importe qui se l'octroierait en une ligne de
    console. Seul `app_metadata` (service-role uniquement) fait foi."""

    def test_user_metadata_never_grants_a_feature(self):
        forged = {"id": "u1", "user_metadata": {"features": ["autopilot"]}, "app_metadata": {}}
        self.assertFalse(features.has_feature(forged, "autopilot"))
        self.assertEqual(features.features_of(forged), set(features.DEFAULT_FEATURES))


class RolloutTest(unittest.TestCase):
    def test_a_graduated_feature_is_open_to_everyone(self):
        """Sortir de bêta = déplacer le nom dans DEFAULT_FEATURES, et c'est tout."""
        original = features.DEFAULT_FEATURES
        try:
            features.DEFAULT_FEATURES = frozenset({"autopilot"})
            self.assertTrue(features.has_feature(user(), "autopilot"))
            self.assertTrue(features.has_feature(None, "autopilot") is False)  # sans identité : toujours non
        finally:
            features.DEFAULT_FEATURES = original

    def test_every_default_feature_is_in_the_catalogue(self):
        """Un défaut absent du catalogue serait un droit que personne ne peut nommer."""
        self.assertTrue(set(features.DEFAULT_FEATURES) <= set(features.KNOWN_FEATURES))


if __name__ == "__main__":
    unittest.main()
