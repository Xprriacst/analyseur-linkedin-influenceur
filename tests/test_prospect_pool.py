"""Pool partagé de prospects — Mode Pilote (src/prospect_pool.py).

Ce que ces tests verrouillent — les propriétés dont la perte serait SILENCIEUSE :

- **la frontière d'anonymisation**, la raison d'être de ce fichier. Ici, de la
  donnée traverse d'un compte CLIENT à un autre : c'est le seul endroit du
  produit où ça arrive. Seules les données publiques du profil ont le droit de
  passer (nom, headline, URL LinkedIn) ; jamais le contexte privé du compte
  source — commentaire capté, score ICP et sa justification, signaux, curation
  « ne pas contacter », identifiants de conversation. Une fuite ne lèverait
  aucune erreur : elle s'afficherait simplement dans l'écran d'un autre client.
  Le module annonce **deux remparts indépendants**, un test pour chacun :
    1. la projection SQL explicite (`db._POOL_PUBLIC_LEAD_COLS`) ne SELECT que
       les colonnes publiques — vérifiée sur la constante ET sur l'appel réel ;
    2. `public_prospect()` re-filtre par whitelist **même si la projection
       régressait** — on lui donne exprès un lead complet, contexte privé inclus.
  Un seul rempart suffirait aujourd'hui ; c'est justement pour ça qu'ils sont
  deux, et que chacun est testé isolément.

- **un compte AVEC LinkedIn connecté ne consomme jamais le pool** : il travaille
  sur ses propres leads. Sans ce garde, il brûlerait des réservations dont il
  n'a pas l'usage, et priverait de prospects les comptes qui en dépendent.

- **le plafond de 3/jour et la réservation** : un prospect n'est proposé qu'à UN
  compte par jour. Le verrou est l'index unique `(day, profile_url)`, pas un
  select préalable — deux comptes qui ouvrent l'app au même instant ne peuvent
  pas se voir attribuer la même personne. Le code doit donc savoir encaisser un
  insert refusé et passer au candidat suivant, sans jamais lever.

- **fail-safe** : pool vide, service-role absent ou base en panne ⇒ liste vide.
  Jamais une exception qui casserait le plan du jour tout entier.

Aucun réseau, aucune base : `db` est remplacé.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import prospect_pool as pool  # noqa: E402

# Un lead COMPLET, tel qu'il vit dans la table `leads` du compte SOURCE : les
# données publiques du profil, et tout le contexte privé qui ne doit jamais en
# sortir. C'est la pièce à conviction des tests de rempart.
FULL_LEAD = {
    "id": "lead-1",
    "user_id": "owner-account",
    "profile_url": "https://www.linkedin.com/in/camille-dupont/",
    "name": "Camille Dupont",
    "headline": "Fondatrice · TalentFlow",
    # ── Contexte PRIVÉ du compte source — rien de tout ça ne doit traverser ──
    "comment_text": "Je cherche un outil de prospection, tu as un retour ?",
    "commented_at": "2026-08-30T09:00:00Z",
    "reaction_count": 12,
    "score": 87,
    "score_reason": "Fondatrice SaaS B2B, correspond exactement à l'ICP du compte",
    "signals": ["a commenté un post lead-magnet", "recherche un outil"],
    "contact_status": "skip",
    "skip_reason": "déjà cliente d'un concurrent",
    "outreach_status": "invite_sent",
    "outreach_chat_id": "chat-99",
    "provider_id": "ACoAAB12345",
    "post_url": "https://www.linkedin.com/posts/concurrent_activity-1",
    "source_id": "src-7",
}

# Tout ce qui, présent dans une sortie destinée à un AUTRE compte, serait une fuite.
PRIVATE_KEYS = (
    "comment_text",
    "commented_at",
    "reaction_count",
    "score",
    "score_reason",
    "signals",
    "contact_status",
    "skip_reason",
    "outreach_status",
    "outreach_chat_id",
    "provider_id",
    "post_url",
    "source_id",
    "user_id",
    "id",
)


def _lead(**kwargs):
    base = dict(FULL_LEAD)
    base.update(kwargs)
    return base


# ─────────────────────────── REMPART 1 : la projection SQL ────────────────────


class PoolProjectionTest(unittest.TestCase):
    """La lecture des candidats ne RAMÈNE que des colonnes publiques.

    Premier rempart : ce qui n'est jamais lu ne peut pas fuir. La projection est
    explicite justement pour ça — un `select("*")` ferait entrer tout le contexte
    privé du compte source dans le process, à un `return` de distance de l'écran
    d'un autre client.
    """

    def test_projection_ne_contient_que_les_colonnes_publiques(self):
        from src import db

        projected = {c.strip() for c in db._POOL_PUBLIC_LEAD_COLS.split(",")}
        # `user_id` sert UNIQUEMENT à la ceinture d'exclusion côté logique pure ;
        # il ne ressort jamais vers le receveur (cf. PublicProspectTest).
        self.assertEqual(projected, {"user_id", "profile_url", "name", "headline"})

    def test_aucune_colonne_privee_dans_la_projection(self):
        from src import db

        projected = {c.strip() for c in db._POOL_PUBLIC_LEAD_COLS.split(",")}
        # Le joker est la régression la plus probable (et la pire) : il ne
        # nomme aucune colonne privée, donc il passerait une simple recherche
        # par nom tout en ramenant TOUT le contexte du compte source.
        self.assertNotIn(
            "*",
            db._POOL_PUBLIC_LEAD_COLS,
            "select(\"*\") ramènerait tout le contexte privé du compte source "
            "dans le pool partagé : la projection doit rester explicite.",
        )
        for private in PRIVATE_KEYS:
            if private in ("user_id", "id"):
                continue
            self.assertNotIn(
                private,
                projected,
                f"« {private} » est du contexte privé du compte source : il ne doit "
                "jamais être lu par le pool partagé.",
            )

    def test_la_lecture_reelle_utilise_bien_cette_projection(self):
        """La constante ne protège rien si la requête ne s'en sert pas.

        On capture l'appel `.select(...)` réel : c'est lui qui décide de ce qui
        entre en mémoire, pas le commentaire au-dessus de la constante.
        """
        from src import db

        captured = {}

        class FakeQuery:
            def select(self, cols):
                captured["select"] = cols
                return self

            def neq(self, col, value):
                captured["neq"] = (col, value)
                return self

            def order(self, *a, **k):
                return self

            def limit(self, n):
                captured["limit"] = n
                return self

            def execute(self):
                return type("R", (), {"data": []})()

        class FakeClient:
            def table(self, name):
                captured["table"] = name
                return FakeQuery()

        with patch("src.db.admin_enabled", return_value=True), \
             patch("src.db.admin_client", return_value=FakeClient()):
            db.admin_pool_candidate_leads("receiver-account")

        self.assertEqual(captured["table"], "leads")
        self.assertEqual(captured["select"], db._POOL_PUBLIC_LEAD_COLS)
        # Les leads du receveur lui-même ne sont pas des candidats du pool.
        self.assertEqual(captured["neq"], ("user_id", "receiver-account"))

    def test_assignation_relit_toute_colonne_ecrite(self):
        """Piège de projection (6ᵉ occurrence documentée dans ce dépôt).

        Toute colonne écrite par `assignment_row` et absente de la projection de
        relecture serait lue `None` SANS erreur : le prospect s'afficherait sans
        nom ni headline le lendemain, et la réservation semblerait « vide ».
        """
        from src import db

        projected = {c.strip() for c in db._POOL_ASSIGNMENT_COLS.split(",")}
        written = set(pool.assignment_row("u1", "2026-09-01", 0, {
            "profile_url": "https://www.linkedin.com/in/x",
            "name": "X",
            "headline": "H",
        }))
        self.assertEqual(written - projected, set())


# ────────────────── REMPART 2 : la whitelist de public_prospect ────────────────


class PublicProspectTest(unittest.TestCase):
    """`public_prospect()` tient MÊME SI la projection régressait.

    On lui donne délibérément un lead complet — celui qu'un `select("*")`
    ramènerait. Rien d'autre que la whitelist ne doit en sortir.
    """

    def test_un_lead_complet_ne_rend_que_les_champs_publics(self):
        out = pool.public_prospect(FULL_LEAD)
        self.assertEqual(set(out), set(pool.PUBLIC_PROSPECT_FIELDS))

    def test_aucune_donnee_privee_ne_survit(self):
        out = pool.public_prospect(FULL_LEAD)
        for private in PRIVATE_KEYS:
            self.assertNotIn(
                private,
                out,
                f"FUITE : « {private} » (contexte privé du compte source) est "
                "ressorti vers un autre compte.",
            )
        # Et pas seulement par le nom de la clé : aucune VALEUR privée non plus.
        values = " ".join(str(v) for v in out.values())
        self.assertNotIn("concurrent", values)
        self.assertNotIn("ICP", values)
        self.assertNotIn("ACoAA", values)

    def test_le_score_icp_ne_traverse_jamais(self):
        # Le score appartient au compte qui a fait la notation ; le receveur n'a
        # rien noté. L'afficher lui ferait croire à une note qui n'est pas la sienne.
        self.assertNotIn("score", pool.public_prospect(FULL_LEAD))

    def test_url_canonicalisee(self):
        # Deux formes de la même personne doivent produire la même clé, sinon la
        # dédup et la réservation laissent passer des doublons.
        a = pool.public_prospect(_lead(profile_url="https://fr.linkedin.com/in/camille-dupont?trk=x"))
        b = pool.public_prospect(_lead(profile_url="https://www.linkedin.com/in/camille-dupont/"))
        self.assertEqual(a["profile_url"], b["profile_url"])

    def test_sans_url_ou_sans_nom_rien_ne_sort(self):
        self.assertIsNone(pool.public_prospect(_lead(profile_url=None)))
        self.assertIsNone(pool.public_prospect(_lead(name="  ")))
        self.assertIsNone(pool.public_prospect(None))
        self.assertIsNone(pool.public_prospect("pas un dict"))

    def test_assignment_row_ne_porte_que_du_public(self):
        # La table des attributions est un snapshot : ce qu'on y écrit y reste.
        row = pool.assignment_row("receiver", "2026-09-01", 0, pool.public_prospect(FULL_LEAD))
        for private in PRIVATE_KEYS:
            if private == "user_id":
                continue  # le user_id du RECEVEUR, pas celui du compte source
            self.assertNotIn(private, row)
        self.assertEqual(row["user_id"], "receiver")

    def test_la_selection_complete_ne_laisse_fuir_aucun_champ_prive(self):
        # Bout en bout du chemin pur : candidats bruts → ce qui part à l'écran.
        picked = pool.select_daily([FULL_LEAD], receiver_id="receiver")
        self.assertEqual(len(picked), 1)
        for private in PRIVATE_KEYS:
            self.assertNotIn(private, picked[0])


# ─────────────────────────── Sélection : qui, et combien ──────────────────────


class SelectDailyTest(unittest.TestCase):
    def _candidates(self, n, owner="owner-account"):
        return [
            _lead(
                id=f"l{i}",
                user_id=owner,
                profile_url=f"https://www.linkedin.com/in/p{i}",
                name=f"Prospect {i}",
            )
            for i in range(n)
        ]

    def test_plafond_trois_par_jour(self):
        picked = pool.select_daily(self._candidates(10), receiver_id="receiver")
        self.assertEqual(len(picked), pool.POOL_DAILY_LIMIT)
        self.assertEqual(pool.POOL_DAILY_LIMIT, 3)

    def test_limit_none_rend_toute_la_liste(self):
        # L'orchestrateur sur-provisionne : les courses de réservation en consomment.
        picked = pool.select_daily(self._candidates(10), receiver_id="receiver", limit=None)
        self.assertEqual(len(picked), 10)

    def test_jamais_un_lead_du_receveur_lui_meme(self):
        mixed = self._candidates(2, owner="receiver") + self._candidates(2, owner="autre")
        picked = pool.select_daily(mixed, receiver_id="receiver", limit=None)
        # Les 2 premiers appartiennent au receveur : mêmes URLs, exclues par la
        # ceinture `user_id`. Il ne reste que celles vues chez « autre ».
        self.assertEqual(len(picked), 2)

    def test_jamais_un_prospect_deja_dans_les_leads_du_receveur(self):
        picked = pool.select_daily(
            self._candidates(3),
            receiver_id="receiver",
            # Forme non canonique exprès : la comparaison doit canonicaliser.
            own_urls={"https://fr.linkedin.com/in/p1?trk=abc"},
            limit=None,
        )
        self.assertNotIn(
            "https://www.linkedin.com/in/p1", [p["profile_url"] for p in picked]
        )
        self.assertEqual(len(picked), 2)

    def test_jamais_un_prospect_reserve_par_un_autre_compte_aujourdhui(self):
        picked = pool.select_daily(
            self._candidates(3),
            receiver_id="receiver",
            reserved_urls={"https://www.linkedin.com/in/p0"},
            limit=None,
        )
        self.assertEqual(len(picked), 2)

    def test_jamais_deux_fois_le_meme_prospect_au_meme_compte(self):
        picked = pool.select_daily(
            self._candidates(3),
            receiver_id="receiver",
            history_urls={"https://www.linkedin.com/in/p2"},
            limit=None,
        )
        self.assertEqual(len(picked), 2)

    def test_une_personne_vue_par_deux_comptes_est_un_seul_candidat(self):
        doublon = [
            _lead(user_id="a", profile_url="https://www.linkedin.com/in/x", name="X"),
            _lead(user_id="b", profile_url="https://fr.linkedin.com/in/x/", name="X"),
        ]
        self.assertEqual(len(pool.select_daily(doublon, receiver_id="r", limit=None)), 1)

    def test_ordre_par_affinite_avec_le_ciblage_du_RECEVEUR(self):
        candidates = [
            _lead(profile_url="https://www.linkedin.com/in/a", name="A", headline="Plombier"),
            _lead(profile_url="https://www.linkedin.com/in/b", name="B", headline="Fondatrice SaaS B2B"),
        ]
        picked = pool.select_daily(
            candidates,
            receiver_id="r",
            targeting={"ideal_client": "Fondateurs SaaS", "offer": "prospection B2B"},
            limit=None,
        )
        self.assertEqual(picked[0]["name"], "B")

    def test_sans_ciblage_l_ordre_d_arrivee_est_conserve(self):
        picked = pool.select_daily(self._candidates(3), receiver_id="r", limit=None)
        self.assertEqual([p["name"] for p in picked], ["Prospect 0", "Prospect 1", "Prospect 2"])

    def test_entrees_malformees_ignorees_sans_lever(self):
        picked = pool.select_daily(
            [None, "texte", {}, _lead()], receiver_id="r", limit=None
        )
        self.assertEqual(len(picked), 1)


# ───────────────── Orchestration : réservation, mémo du jour, fail-safe ───────


class EnsureDailyAssignmentsTest(unittest.TestCase):
    """Le seul point qui écrit. Rien ne doit pouvoir casser le plan du jour."""

    def _row(self, url, position=0):
        return {
            "id": f"a-{position}",
            "user_id": "receiver",
            "day": "2026-09-01",
            "position": position,
            "profile_url": url,
            "name": "N",
            "headline": "H",
        }

    def _candidates(self, n):
        return [
            _lead(
                user_id="owner",
                profile_url=f"https://www.linkedin.com/in/p{i}",
                name=f"Prospect {i}",
            )
            for i in range(n)
        ]

    def test_le_memo_du_jour_est_relu_sans_re_selectionner(self):
        """Deux ouvertures du Mode Pilote le même jour = les mêmes prospects.

        Sans ce chemin, la liste changerait à chaque rafraîchissement et brûlerait
        des réservations à chaque fois.
        """
        existing = [self._row("https://www.linkedin.com/in/deja", 0)]
        with patch("src.db.admin_enabled", return_value=True), \
             patch("src.db.admin_pool_assignments_for_day", return_value=existing), \
             patch("src.db.admin_pool_candidate_leads") as candidates, \
             patch("src.db.admin_create_pool_assignment") as create:
            out = pool.ensure_daily_assignments("receiver", None, [], day="2026-09-01")
        self.assertEqual(out, existing)
        candidates.assert_not_called()
        create.assert_not_called()

    def test_attribue_au_plus_trois_prospects(self):
        created = []

        def _create(row):
            created.append(row)
            return row

        with patch("src.db.admin_enabled", return_value=True), \
             patch("src.db.admin_pool_assignments_for_day", return_value=[]), \
             patch("src.db.admin_pool_candidate_leads", return_value=self._candidates(10)), \
             patch("src.db.admin_pool_reserved_urls", return_value=set()), \
             patch("src.db.admin_pool_user_history_urls", return_value=set()), \
             patch("src.db.admin_create_pool_assignment", side_effect=_create):
            out = pool.ensure_daily_assignments("receiver", None, [], day="2026-09-01")
        self.assertEqual(len(out), 3)
        self.assertEqual(len(created), 3)
        self.assertEqual([r["position"] for r in created], [0, 1, 2])

    def test_un_prospect_pris_par_un_autre_compte_passe_au_suivant(self):
        """LE cas de la réservation : l'insert perd la course, on n'abandonne pas.

        Le verrou est l'index unique en base. Si le code s'arrêtait au premier
        refus, un compte se retrouverait avec 0 prospect un jour de forte
        affluence — sans la moindre erreur visible.
        """
        refused = {"https://www.linkedin.com/in/p0", "https://www.linkedin.com/in/p1"}

        def _create(row):
            if row["profile_url"] in refused:
                return None  # doublon (day, profile_url) : un autre compte a gagné
            return row

        with patch("src.db.admin_enabled", return_value=True), \
             patch("src.db.admin_pool_assignments_for_day", return_value=[]), \
             patch("src.db.admin_pool_candidate_leads", return_value=self._candidates(8)), \
             patch("src.db.admin_pool_reserved_urls", return_value=set()), \
             patch("src.db.admin_pool_user_history_urls", return_value=set()), \
             patch("src.db.admin_create_pool_assignment", side_effect=_create):
            out = pool.ensure_daily_assignments("receiver", None, [], day="2026-09-01")
        self.assertEqual(len(out), 3)
        for row in out:
            self.assertNotIn(row["profile_url"], refused)

    def test_aucune_donnee_privee_n_est_ecrite_en_base(self):
        written = []
        with patch("src.db.admin_enabled", return_value=True), \
             patch("src.db.admin_pool_assignments_for_day", return_value=[]), \
             patch("src.db.admin_pool_candidate_leads", return_value=[FULL_LEAD]), \
             patch("src.db.admin_pool_reserved_urls", return_value=set()), \
             patch("src.db.admin_pool_user_history_urls", return_value=set()), \
             patch("src.db.admin_create_pool_assignment",
                   side_effect=lambda row: written.append(row) or row):
            pool.ensure_daily_assignments("receiver", None, [], day="2026-09-01")
        self.assertEqual(len(written), 1)
        for private in PRIVATE_KEYS:
            if private == "user_id":
                continue
            self.assertNotIn(private, written[0])

    def test_pool_vide_rend_une_liste_vide(self):
        with patch("src.db.admin_enabled", return_value=True), \
             patch("src.db.admin_pool_assignments_for_day", return_value=[]), \
             patch("src.db.admin_pool_candidate_leads", return_value=[]):
            self.assertEqual(pool.ensure_daily_assignments("r", None, [], day="d"), [])

    def test_sans_service_role_rien_ne_se_passe(self):
        with patch("src.db.admin_enabled", return_value=False):
            self.assertEqual(pool.ensure_daily_assignments("r", None, [], day="d"), [])

    def test_sans_user_id_rien_ne_se_passe(self):
        with patch("src.db.admin_enabled", return_value=True):
            self.assertEqual(pool.ensure_daily_assignments(None, None, [], day="d"), [])

    def test_une_panne_de_base_ne_casse_jamais_le_plan_du_jour(self):
        with patch("src.db.admin_enabled", return_value=True), \
             patch("src.db.admin_pool_assignments_for_day", side_effect=RuntimeError("boom")):
            self.assertEqual(pool.ensure_daily_assignments("r", None, [], day="d"), [])


# ───────────── Aiguillage : qui a droit au pool, et qui n'y touche pas ────────


class RoutingTest(unittest.TestCase):
    """Un compte AVEC LinkedIn connecté ne consomme JAMAIS le pool."""

    def test_compte_connecte_garde_ses_propres_leads(self):
        from src import pilot_plan as pp

        own = {
            "id": "mine",
            "name": "Lead Maison",
            "headline": "Fondateur · MonSaaS",
            "score": 80,
            "contact_status": None,
            "outreach_status": "none",
        }
        out = pp.compose_pilot_plan(
            profile={}, targeting=None, generated_posts=[], daily_ideas=[],
            leads=[own], library=[], followed_handles=set(), schedule=[],
            outreach_connected=True, publish_connected=False,
            weekly_done=0, weekly_total=3,
            pool_prospects=[{"profile_url": "https://www.linkedin.com/in/pool",
                             "name": "Prospect Pool", "headline": "X"}],
        )
        self.assertEqual(out["meta"]["contacts_source"], "leads")
        self.assertEqual([c["name"] for c in out["plan"]["contacts"]], ["Lead Maison"])

    def test_compte_non_connecte_recoit_le_pool_sans_score(self):
        from src import pilot_plan as pp

        out = pp.compose_pilot_plan(
            profile={}, targeting=None, generated_posts=[], daily_ideas=[],
            leads=[], library=[], followed_handles=set(), schedule=[],
            outreach_connected=False, publish_connected=False,
            weekly_done=0, weekly_total=3,
            pool_prospects=[{"profile_url": "https://www.linkedin.com/in/pool",
                             "name": "Prospect Pool", "headline": "Fondatrice · Acme"}],
        )
        self.assertEqual(out["meta"]["contacts_source"], "pool")
        contact = out["plan"]["contacts"][0]
        self.assertEqual(contact["source"], "pool")
        # Pas de score : il appartiendrait au compte source (privé), et le
        # receveur n'a rien noté. L'UI masque la pastille sur `score: None`.
        self.assertIsNone(contact["score"])
        self.assertEqual(contact["role"], "Fondatrice")
        self.assertEqual(contact["company"], "Acme")

    def test_build_pilot_today_ne_reserve_rien_pour_un_compte_connecte(self):
        """Le garde au VRAI niveau : la réservation n'est même pas tentée.

        Un compte connecté qui appellerait `ensure_daily_assignments` prendrait
        des prospects à des comptes qui, eux, n'ont que ça — panne silencieuse
        (personne ne verrait d'erreur, le pool s'assécherait simplement).
        """
        from src import pilot_plan as pp

        with patch("src.db.get_editorial_profile", return_value={}), \
             patch("src.db.get_lead_targeting", return_value=None), \
             patch("src.db.list_generated_posts", return_value=[]), \
             patch("src.db.list_daily_ideas", return_value=[]), \
             patch("src.db.list_leads", return_value=[]), \
             patch("src.db.list_influencer_library", return_value=[]), \
             patch("src.db.list_followed_influencers", return_value=[]), \
             patch("src.db.get_weekly_schedule", return_value=[]), \
             patch("src.db.get_linkedin_outreach_account",
                   return_value={"unipile_account_id": "acc-1"}), \
             patch.object(pp, "weekly_progress", return_value=(0, 3)), \
             patch("src.prospect_pool.ensure_daily_assignments") as ensure:
            out = pp.build_pilot_today("token")
        ensure.assert_not_called()
        self.assertEqual(out["meta"]["contacts_source"], "leads")

    def test_build_pilot_today_sert_le_pool_a_un_compte_non_connecte(self):
        from src import pilot_plan as pp

        with patch("src.db.get_editorial_profile", return_value={}), \
             patch("src.db.get_lead_targeting", return_value=None), \
             patch("src.db.list_generated_posts", return_value=[]), \
             patch("src.db.list_daily_ideas", return_value=[]), \
             patch("src.db.list_leads", return_value=[]), \
             patch("src.db.list_influencer_library", return_value=[]), \
             patch("src.db.list_followed_influencers", return_value=[]), \
             patch("src.db.get_weekly_schedule", return_value=[]), \
             patch("src.db.get_linkedin_outreach_account", return_value=None), \
             patch("src.db.get_user", return_value={"id": "receiver"}), \
             patch.object(pp, "weekly_progress", return_value=(0, 3)), \
             patch("src.prospect_pool.ensure_daily_assignments",
                   return_value=[{"profile_url": "https://www.linkedin.com/in/pool",
                                  "name": "Prospect Pool", "headline": "H"}]) as ensure:
            out = pp.build_pilot_today("token")
        ensure.assert_called_once()
        self.assertEqual(out["meta"]["contacts_source"], "pool")
        self.assertEqual(out["plan"]["contacts"][0]["name"], "Prospect Pool")


if __name__ == "__main__":
    unittest.main()
