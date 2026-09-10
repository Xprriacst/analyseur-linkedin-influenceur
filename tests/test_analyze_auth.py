"""L'analyse synchrone `POST /analyze` est authentifiée ET débitée.

Contexte (audit sécurité 2026-09-09) : la route portait `optional_token`, donc un
visiteur ANONYME pouvait déclencher deux runs Apify (argent réel) plus les appels
Claude, sans compte, sans crédit et sans plafond — alors que le chemin officiel
(`POST /jobs`) débite 20 crédits par profil. Le seul garde-fou était un drapeau
`localStorage` côté navigateur, levé en vidant le stockage ou en appelant l'API
directement.

Deux niveaux de test :
- lecture de `api.py` (toujours joué, même sans fastapi installé) ;
- appel réel de la fonction d'endpoint (joué en CI, où requirements.txt est installé).
"""

import pathlib
import unittest
from unittest import mock

API_SOURCE = (pathlib.Path(__file__).resolve().parents[1] / "api.py").read_text(encoding="utf-8")

try:  # fastapi n'est pas installé sur le Python local du Mac (cf. changelog).
    import api as api_module  # noqa: F401

    HAS_API = True
except Exception:  # pragma: no cover - dépend de l'environnement
    api_module = None
    HAS_API = False


def _analyze_source() -> str:
    """Corps de l'endpoint `/analyze`, isolé de la suite du fichier."""
    start = API_SOURCE.index('@app.post("/analyze")')
    end = API_SOURCE.index("class JobRequest(BaseModel):", start)
    return API_SOURCE[start:end]


class AnalyzeRouteSourceTest(unittest.TestCase):
    def test_route_requires_a_valid_token(self) -> None:
        """`optional_token` n'accepte AUCUNE authentification : il extrait juste
        l'en-tête. La route doit exiger `require_token`, qui valide le JWT."""
        body = _analyze_source()
        self.assertIn("token: str = Depends(require_token)", body)
        self.assertNotIn("Depends(optional_token)", body)

    def test_route_debits_credits(self) -> None:
        """Le travail payant (Apify + Claude) doit être débité comme dans la file."""
        body = _analyze_source()
        self.assertIn('db.debit_credits(token, "analyze_job", 1)', body)
        self.assertIn("status_code=402", body)

    def test_route_refunds_when_the_analysis_fails(self) -> None:
        """Analyse non livrée ⇒ crédit rendu (règle déjà appliquée à la file)."""
        body = _analyze_source()
        self.assertIn("refund_credits_admin", body)

    def test_route_filters_non_linkedin_urls(self) -> None:
        """Sans ce filtre, une URL quelconque partait chez Apify — run facturé."""
        body = _analyze_source()
        self.assertIn("_clean_urls([payload.profile_url])", body)


@unittest.skipUnless(HAS_API, "fastapi absent de cet environnement")
class AnalyzeRouteBehaviourTest(unittest.TestCase):
    """Appelle la fonction d'endpoint directement (pas de couche HTTP, pas de httpx)."""

    def setUp(self) -> None:
        self.payload = api_module.AnalyzeRequest(
            profile_url="https://www.linkedin.com/in/someone/", limit=25, use_cache=True, run_llm=False
        )
        self.env = mock.patch.dict("os.environ", {"APIFY_TOKEN": "x", "ANTHROPIC_API_KEY": "y"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_insufficient_credits_blocks_before_any_apify_run(self) -> None:
        """Le solde est vérifié AVANT le travail payant : rien ne doit partir."""
        with mock.patch.object(api_module.db, "debit_credits", return_value=(False, 3)), \
             mock.patch.object(api_module, "run_analysis") as run:
            with self.assertRaises(api_module.HTTPException) as ctx:
                api_module.analyze(self.payload, token="tok")
        self.assertEqual(ctx.exception.status_code, 402)
        run.assert_not_called()

    def test_non_linkedin_url_is_refused_without_debit(self) -> None:
        payload = api_module.AnalyzeRequest(profile_url="https://evil.example.com/x")
        with mock.patch.object(api_module.db, "debit_credits") as debit, \
             mock.patch.object(api_module, "run_analysis") as run:
            with self.assertRaises(api_module.HTTPException) as ctx:
                api_module.analyze(payload, token="tok")
        self.assertEqual(ctx.exception.status_code, 400)
        debit.assert_not_called()
        run.assert_not_called()

    def test_failed_analysis_refunds_the_credit(self) -> None:
        with mock.patch.object(api_module.db, "debit_credits", return_value=(True, 130)), \
             mock.patch.object(api_module.db, "get_user", return_value={"id": "u1"}), \
             mock.patch.object(api_module, "run_analysis", side_effect=RuntimeError("apify down")), \
             mock.patch.object(api_module.db, "refund_credits_admin") as refund:
            with self.assertRaises(api_module.HTTPException):
                api_module.analyze(self.payload, token="tok")
        refund.assert_called_once()
        self.assertEqual(refund.call_args.args[0], "u1")
        self.assertEqual(refund.call_args.args[1], "analyze_job")

    def test_successful_analysis_debits_once_and_returns_the_balance(self) -> None:
        with mock.patch.object(api_module.db, "debit_credits", return_value=(True, 130)) as debit, \
             mock.patch.object(api_module, "run_analysis", return_value={"stats": {}}), \
             mock.patch.object(api_module.db, "supabase_enabled", return_value=True), \
             mock.patch.object(api_module.db, "save_analysis", return_value={"analysis_id": "a1"}), \
             mock.patch.object(api_module.db, "refund_credits_admin") as refund:
            out = api_module.analyze(self.payload, token="tok")
        debit.assert_called_once()
        refund.assert_not_called()
        self.assertEqual(out["credits"], 130)


if __name__ == "__main__":
    unittest.main()
