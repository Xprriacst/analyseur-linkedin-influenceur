"""Le compte LinkedIn (Unipile) d'un client ne peut plus être capté par un autre.

Contexte (audit sécurité 2026-09-09). Une seule clé API Unipile sert TOUS les
clients : le cloisonnement tient entièrement à la colonne `unipile_account_id`.
Deux chemins permettaient de s'approprier le compte LinkedIn d'un autre client,
donc de lire sa messagerie et d'envoyer des invitations en son nom :

  1. `POST /me/linkedin/outreach/refresh` retombait sur « le compte le plus
     récent non encore rattaché en base ». La déconnexion SUPPRIMANT la ligne
     sans délier le compte chez Unipile, un compte déconnecté redevenait
     « libre » tout en restant connecté : le rattachement suivant de n'importe
     quel client se l'attribuait.
  2. La table était écrivable par le client (clé anon + son JWT) : il pouvait y
     écrire directement l'`unipile_account_id` d'autrui, et supprimer/recréer sa
     ligne pour effacer son gel anti-restriction et son warm-up.

Ces tests verrouillent les deux fermetures : le registre permanent de propriété
et le passage des écritures en service-role (migration 0075).
"""

import datetime
import pathlib
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
API_SOURCE = (ROOT / "api.py").read_text(encoding="utf-8")
DB_SOURCE = (ROOT / "src" / "db.py").read_text(encoding="utf-8")
MIGRATION = (ROOT / "supabase" / "migrations" / "0075_unipile_account_claims.sql").read_text(encoding="utf-8")

try:
    import api as api_module

    HAS_API = True
except Exception:  # pragma: no cover - dépend de l'environnement
    api_module = None
    HAS_API = False


def _iso(minutes_ago: int) -> str:
    moment = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes_ago)
    return moment.isoformat().replace("+00:00", "Z")


@unittest.skipUnless(HAS_API, "fastapi absent de cet environnement")
class ResolveUnipileAccountTest(unittest.TestCase):
    """`_resolve_unipile_account` : à qui appartient le compte fraîchement connecté."""

    def _resolve(self, accounts, owners, *, requested_minutes_ago=5, user_id="me"):
        current = {"connect_requested_at": _iso(requested_minutes_ago)} if requested_minutes_ago is not None else {}
        with mock.patch.object(api_module.unipile, "list_accounts", return_value=accounts), \
             mock.patch.object(api_module.db, "unipile_account_owners", return_value=owners), \
             mock.patch.object(api_module.db, "get_linkedin_outreach_account", return_value=current):
            return api_module._resolve_unipile_account("tok", user_id)

    def test_an_account_claimed_by_someone_else_is_never_attached(self) -> None:
        """LE test du lot : le compte d'un autre client, même le plus récent,
        ne doit jamais être attribué."""
        accounts = [{"id": "acc-victime", "name": "Nom LinkedIn", "created_at": _iso(1)}]
        got = self._resolve(accounts, {"acc-victime": "un-autre-user"})
        self.assertIsNone(got)

    def test_a_disconnected_account_stays_claimed(self) -> None:
        """La déconnexion ne rend pas le compte au pot commun : il reste connecté
        chez Unipile, donc revendiqué. C'était le chemin d'attaque principal."""
        accounts = [{"id": "acc-orphelin", "name": "Nom LinkedIn", "created_at": _iso(60 * 24)}]
        self.assertIsNone(self._resolve(accounts, {"acc-orphelin": "ancien-proprietaire"}))

    def test_owner_finds_his_own_account_again(self) -> None:
        """Reconnexion : le propriétaire retrouve son compte, même ancien."""
        accounts = [{"id": "acc-a-moi", "name": "Nom LinkedIn", "created_at": _iso(60 * 24 * 30)}]
        got = self._resolve(accounts, {"acc-a-moi": "me"})
        self.assertEqual(api_module.unipile.account_id_of(got), "acc-a-moi")

    def test_strong_name_match_wins(self) -> None:
        """Le `name` est posé côté serveur depuis le jeton vérifié : un client ne
        peut pas le forger, il tranche donc seul."""
        accounts = [
            {"id": "acc-autre", "name": "Nom LinkedIn", "created_at": _iso(1)},
            {"id": "acc-a-moi", "name": "me", "created_at": _iso(30)},
        ]
        got = self._resolve(accounts, {})
        self.assertEqual(api_module.unipile.account_id_of(got), "acc-a-moi")

    def test_unreadable_registry_refuses_every_fallback(self) -> None:
        """`None` = « on ne sait pas qui possède quoi ». Se rabattre sur un
        registre vide reviendrait au comportement vulnérable."""
        accounts = [{"id": "acc-libre", "name": "Nom LinkedIn", "created_at": _iso(1)}]
        self.assertIsNone(self._resolve(accounts, None))

    def test_account_older_than_the_connect_request_is_refused(self) -> None:
        """Un compte qui existait AVANT que ce client clique « Connecter » n'est
        pas le sien, même s'il n'est revendiqué par personne."""
        accounts = [{"id": "acc-anterieur", "name": "Nom LinkedIn", "created_at": _iso(90)}]
        self.assertIsNone(self._resolve(accounts, {}, requested_minutes_ago=10))

    def test_account_created_after_the_connect_request_is_accepted(self) -> None:
        accounts = [{"id": "acc-neuf", "name": "Nom LinkedIn", "created_at": _iso(2)}]
        got = self._resolve(accounts, {}, requested_minutes_ago=10)
        self.assertEqual(api_module.unipile.account_id_of(got), "acc-neuf")

    def test_unparseable_timestamp_is_refused(self) -> None:
        """Sans horodatage exploitable, impossible de prouver que le compte est
        celui qu'on vient de connecter."""
        accounts = [{"id": "acc-sans-date", "name": "Nom LinkedIn", "created_at": "n'importe quoi"}]
        self.assertIsNone(self._resolve(accounts, {}, requested_minutes_ago=10))

    def test_without_connect_timestamp_only_a_very_recent_account_passes(self) -> None:
        """Repli de secours si l'horodatage n'a pas pu être écrit : fenêtre
        courte, pour ne pas enfermer le client dehors — mais un vieil orphelin
        reste exclu."""
        recent = [{"id": "acc-neuf", "name": "X", "created_at": _iso(2)}]
        old = [{"id": "acc-vieux", "name": "X", "created_at": _iso(120)}]
        self.assertIsNotNone(self._resolve(recent, {}, requested_minutes_ago=None))
        self.assertIsNone(self._resolve(old, {}, requested_minutes_ago=None))


@unittest.skipUnless(HAS_API, "fastapi absent de cet environnement")
class ResolveUnipileDiagnosticsTest(unittest.TestCase):
    """Un refus de rattachement doit DIRE pourquoi.

    Ce chemin ne peut pas être joué hors production : la base dev n'a aucun
    compte Unipile connecté. Le premier test réel est donc celui d'Alex, en prod.
    Sans motif dans les logs, « je n'arrive plus à connecter LinkedIn » devient
    une enquête au lieu d'un grep.
    """

    def _resolve_capturing_logs(self, accounts, owners, *, requested_minutes_ago=5, user_id="me"):
        import contextlib
        import io

        current = {"connect_requested_at": _iso(requested_minutes_ago)} if requested_minutes_ago is not None else {}
        buffer = io.StringIO()
        with mock.patch.object(api_module.unipile, "list_accounts", return_value=accounts), \
             mock.patch.object(api_module.db, "unipile_account_owners", return_value=owners), \
             mock.patch.object(api_module.db, "get_linkedin_outreach_account", return_value=current), \
             contextlib.redirect_stdout(buffer):
            got = api_module._resolve_unipile_account("tok", user_id)
        return got, buffer.getvalue()

    def test_refusal_names_the_account_claimed_by_someone_else(self) -> None:
        accounts = [{"id": "acc-victime", "name": "Nom LinkedIn", "created_at": _iso(1)}]
        got, logs = self._resolve_capturing_logs(accounts, {"acc-victime": "un-autre"})
        self.assertIsNone(got)
        self.assertIn("[unipile]", logs)
        self.assertIn("1 revendiqué(s) par un autre", logs)

    def test_refusal_names_the_out_of_window_account(self) -> None:
        accounts = [{"id": "acc-vieux", "name": "Nom LinkedIn", "created_at": _iso(90)}]
        got, logs = self._resolve_capturing_logs(accounts, {}, requested_minutes_ago=10)
        self.assertIsNone(got)
        self.assertIn("antérieur(s) à la demande de connexion", logs)

    def test_refusal_names_the_undated_account(self) -> None:
        accounts = [{"id": "acc-sans-date", "name": "X", "created_at": "n'importe quoi"}]
        got, logs = self._resolve_capturing_logs(accounts, {}, requested_minutes_ago=10)
        self.assertIsNone(got)
        self.assertIn("sans date de création exploitable", logs)

    def test_unreadable_registry_says_so(self) -> None:
        accounts = [{"id": "acc", "name": "X", "created_at": _iso(1)}]
        got, logs = self._resolve_capturing_logs(accounts, None)
        self.assertIsNone(got)
        self.assertIn("registre des propriétés", logs)

    def test_success_says_which_path_ran(self) -> None:
        """Savoir si c'est la correspondance forte ou le repli qui a joué change
        le diagnostic du jour où Unipile se mettra à renvoyer le `name`."""
        _, strong = self._resolve_capturing_logs(
            [{"id": "a1", "name": "me", "created_at": _iso(1)}], {}
        )
        self.assertIn("correspondance forte", strong)
        _, fallback = self._resolve_capturing_logs(
            [{"id": "a2", "name": "Nom LinkedIn", "created_at": _iso(1)}], {}
        )
        self.assertIn("repli borné", fallback)


class ServerSideWritesTest(unittest.TestCase):
    """Les écritures de la table quittent le navigateur (migration 0075)."""

    def _function_body(self, name: str) -> str:
        start = DB_SOURCE.index(f"def {name}(")
        end = DB_SOURCE.index("\ndef ", start + 10)
        return DB_SOURCE[start:end]

    def test_account_upsert_uses_the_service_role(self) -> None:
        body = self._function_body("upsert_linkedin_outreach_account")
        self.assertIn("db = admin_client()", body)
        self.assertNotIn("client_for_token", body)

    def test_disconnect_uses_the_service_role(self) -> None:
        body = self._function_body("disconnect_linkedin_outreach")
        self.assertIn("admin_client()", body)
        self.assertNotIn("client_for_token", body)

    def test_disconnect_never_releases_the_claim(self) -> None:
        """Effacer la revendication à la déconnexion rouvrirait la faille.

        On regarde le CODE, pas la docstring (qui, elle, cite la table pour
        expliquer précisément pourquoi on n'y touche pas)."""
        body = self._function_body("disconnect_linkedin_outreach")
        code = body.split('"""')[2] if body.count('"""') >= 2 else body
        self.assertNotIn("unipile_account_claims", code)
        self.assertIn('table("linkedin_outreach_accounts")', code)

    def test_registry_distinguishes_unknown_from_empty(self) -> None:
        body = self._function_body("unipile_account_owners")
        self.assertIn("return None", body)

    def test_migration_locks_the_table_for_clients(self) -> None:
        """Les trois écritures doivent être retirées à `authenticated` ET `anon`.

        L'assertion porte sur le CONTENU du revoke, pas sur une chaîne figée :
        ajouter un privilège à la liste (`truncate`…) est un durcissement, il ne
        doit pas faire tomber le test — seul le retrait d'un des trois compte."""
        for role in ("authenticated", "anon"):
            revoke = next(
                (
                    line for line in MIGRATION.splitlines()
                    if line.startswith("revoke ")
                    and "public.linkedin_outreach_accounts" in line
                    and line.rstrip(";").endswith(role)
                ),
                None,
            )
            self.assertIsNotNone(revoke, f"aucun revoke pour {role}")
            for privilege in ("insert", "update", "delete"):
                self.assertIn(privilege, revoke)
        self.assertIn("create table if not exists public.unipile_account_claims", MIGRATION)
        # RLS sans policy : service-role uniquement.
        self.assertIn("alter table public.unipile_account_claims enable row level security", MIGRATION)
        self.assertNotIn("create policy", MIGRATION)

    def test_migration_backfills_existing_accounts(self) -> None:
        """Sans reprise, les comptes DÉJÀ connectés passeraient pour libres au
        premier démarrage du nouveau code — donc resteraient captables."""
        self.assertIn("insert into public.unipile_account_claims", MIGRATION)
        self.assertIn("from public.linkedin_outreach_accounts", MIGRATION)

    def test_refresh_claims_before_attaching(self) -> None:
        """Attacher sans revendiquer laisserait le compte « libre » pour le
        prochain client qui rattache."""
        start = API_SOURCE.index("def me_linkedin_outreach_refresh(")
        body = API_SOURCE[start:API_SOURCE.index("\ndef ", start + 10)]
        self.assertLess(body.index("claim_unipile_account"), body.index("upsert_linkedin_outreach_account"))

    def test_connect_records_the_request_time(self) -> None:
        start = API_SOURCE.index("def me_linkedin_outreach_connect(")
        body = API_SOURCE[start:API_SOURCE.index("\ndef ", start + 10)]
        self.assertIn("set_unipile_connect_requested", body)


if __name__ == "__main__":
    unittest.main()
