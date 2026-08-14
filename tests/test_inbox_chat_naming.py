"""Nommage des conversations LinkedIn de l'Inbox (« Conversation LinkedIn » partout).

Causes successives du bug, toutes verrouillées ici :
  1. `normalize_chat` lisait le mauvais champ (`name`/`display_name`) alors qu'Unipile
     range le nom du participant dans `attendee_name` → même quand Unipile embarque le
     participant, le nom était perdu.
  2. Le rattrapage par le nom du lead ne se faisait que par `outreach_chat_id` (renseigné
     pour ~0 lead). On nomme aussi par `attendee_provider_id` (l'identifiant LinkedIn,
     présent sur chaque conversation ET sur chaque lead contacté).
  3. Unipile pose parfois le gabarit littéral `{{full_name}}` dans `name` — un non-vide
     qui bloquait le rattrapage et s'affichait tel quel dans l'Inbox.
  4. ⚠️ Le fond du problème : `GET /chats` ne renvoie, pour une conversation à deux, que
     l'`attendee_provider_id` — **jamais le nom**. Les leads ne couvrent que les gens
     sortis de la prospection ; tout le reste de l'Inbox (entrants, recruteurs, relations
     existantes) n'avait aucune source de nom. D'où `attendee_names` (participants du
     compte) en tête de la chaîne.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src import unipile


class UsableDisplayNameTest(unittest.TestCase):
    def test_real_name(self):
        self.assertEqual(unipile.usable_display_name(" Benjamin GREGOIRE "), "Benjamin GREGOIRE")

    def test_rejects_full_name_placeholder(self):
        self.assertIsNone(unipile.usable_display_name("{{full_name}}"))

    def test_rejects_first_name_placeholder(self):
        self.assertIsNone(unipile.usable_display_name("{{first_name}}"))

    def test_rejects_placeholder_with_spaces(self):
        self.assertIsNone(unipile.usable_display_name("  {{ full_name }}  "))

    def test_rejects_empty(self):
        self.assertIsNone(unipile.usable_display_name(""))
        self.assertIsNone(unipile.usable_display_name(None))
        self.assertIsNone(unipile.usable_display_name(123))


class NormalizeChatTest(unittest.TestCase):
    def test_reads_attendee_name_and_provider_from_embedded_attendee(self):
        chat = {
            "id": "chatAAA",
            "attendees": [
                {
                    "attendee_name": "Benjamin GREGOIRE",
                    "attendee_provider_id": "ACoAACZ_pid",
                    "attendee_profile_url": "https://linkedin.com/in/bg",
                }
            ],
        }
        out = unipile.normalize_chat(chat)
        self.assertEqual(out["id"], "chatAAA")
        self.assertEqual(out["name"], "Benjamin GREGOIRE")
        self.assertEqual(out["attendee_name"], "Benjamin GREGOIRE")
        self.assertEqual(out["attendee_provider_id"], "ACoAACZ_pid")
        self.assertEqual(out["provider_url"], "https://linkedin.com/in/bg")

    def test_reads_attendee_provider_id_at_chat_top_level(self):
        # Le cas réel d'une conversation à deux : Unipile met l'identifiant au niveau du
        # chat et n'embarque aucun participant → aucun nom disponible ici.
        chat = {"id": "chatBBB", "attendee_provider_id": "ACoAA_top"}
        out = unipile.normalize_chat(chat)
        self.assertEqual(out["attendee_provider_id"], "ACoAA_top")
        self.assertIsNone(out["name"])
        self.assertIsNone(out["attendee_name"])
        self.assertFalse(out["is_group"])

    def test_group_is_flagged_from_unipile_type(self):
        out = unipile.normalize_chat({"id": "g1", "name": "Groupe projet", "type": 1})
        self.assertEqual(out["name"], "Groupe projet")
        self.assertTrue(out["is_group"])

    def test_no_participant_no_name(self):
        out = unipile.normalize_chat({"id": "c0"})
        self.assertIsNone(out["name"])
        self.assertIsNone(out["attendee_provider_id"])

    def test_placeholder_chat_name_falls_through_to_attendee_name(self):
        # Cas produit : Unipile met `{{full_name}}` en titre, le vrai nom est dans l'attendee.
        chat = {
            "id": "chatPH",
            "name": "{{full_name}}",
            "attendees": [
                {
                    "attendee_name": "Camille Dupont",
                    "attendee_provider_id": "ACoAA_cam",
                }
            ],
        }
        out = unipile.normalize_chat(chat)
        self.assertEqual(out["name"], "Camille Dupont")
        self.assertEqual(out["attendee_provider_id"], "ACoAA_cam")

    def test_placeholder_alone_yields_no_name(self):
        out = unipile.normalize_chat(
            {"id": "chatPH2", "name": "{{full_name}}", "attendee_provider_id": "ACoAA_x"}
        )
        self.assertIsNone(out["name"])
        self.assertEqual(out["attendee_provider_id"], "ACoAA_x")


class ApplyChatNamesTest(unittest.TestCase):
    def _apply(self, chats, *, by_attendee=None, by_lead_provider=None, by_lead_chat=None):
        return unipile.apply_chat_names(
            chats,
            by_attendee=by_attendee or {},
            by_lead_provider=by_lead_provider or {},
            by_lead_chat=by_lead_chat or {},
        )

    def test_names_from_account_attendees_when_person_is_not_a_lead(self):
        # LE cas de l'Inbox d'Alex : conversation entrante, aucun lead correspondant.
        chats = [{"id": "c1", "name": None, "attendee_provider_id": "ACoAA_ben"}]
        self._apply(chats, by_attendee={"ACoAA_ben": "Benjamin GREGOIRE"})
        self.assertEqual(chats[0]["name"], "Benjamin GREGOIRE")

    def test_names_by_lead_provider_id_when_unipile_has_no_attendee(self):
        chats = [{"id": "c1", "name": None, "attendee_provider_id": "ACoAA_ben"}]
        self._apply(chats, by_lead_provider={"ACoAA_ben": "Benjamin GREGOIRE"})
        self.assertEqual(chats[0]["name"], "Benjamin GREGOIRE")

    def test_attendee_wins_over_lead_maps(self):
        chats = [{"id": "c1", "name": None, "attendee_provider_id": "ACoAA_ben"}]
        self._apply(
            chats,
            by_attendee={"ACoAA_ben": "Nom LinkedIn"},
            by_lead_provider={"ACoAA_ben": "Nom Lead"},
        )
        self.assertEqual(chats[0]["name"], "Nom LinkedIn")

    def test_lead_provider_wins_over_chat_id(self):
        chats = [{"id": "c1", "name": None, "attendee_provider_id": "ACoAA_ben"}]
        self._apply(
            chats,
            by_lead_provider={"ACoAA_ben": "Nom Provider"},
            by_lead_chat={"c1": "Nom ChatId"},
        )
        self.assertEqual(chats[0]["name"], "Nom Provider")

    def test_falls_back_to_chat_id_map(self):
        chats = [{"id": "c1", "name": None, "attendee_provider_id": "ACoAA_inconnu"}]
        self._apply(chats, by_lead_chat={"c1": "Nom ChatId"})
        self.assertEqual(chats[0]["name"], "Nom ChatId")

    def test_inmail_subject_is_replaced_by_the_person(self):
        # « Astek s'intéresse à votre profil » est l'OBJET d'un InMail, pas un nom :
        # une Inbox liste des personnes.
        chats = [
            {
                "id": "c1",
                "name": "Astek s'intéresse à votre profil",
                "attendee_provider_id": "ACoAA_rh",
                "is_group": False,
            }
        ]
        self._apply(chats, by_attendee={"ACoAA_rh": "Marie Astek"})
        self.assertEqual(chats[0]["name"], "Marie Astek")

    def test_unipile_title_is_kept_when_nobody_is_identified(self):
        # Repli : un titre imparfait vaut mieux que « Conversation LinkedIn ».
        chats = [{"id": "c1", "name": "Astek s'intéresse à votre profil"}]
        self._apply(chats)
        self.assertEqual(chats[0]["name"], "Astek s'intéresse à votre profil")

    def test_group_keeps_its_title_over_a_participant_name(self):
        # Un groupe n'a que son titre pour nom — l'écraser par un seul de ses membres
        # rendrait la conversation méconnaissable.
        chats = [
            {
                "id": "g1",
                "name": "Groupe projet",
                "is_group": True,
                "attendee_provider_id": "ACoAA_ben",
            }
        ]
        self._apply(chats, by_attendee={"ACoAA_ben": "Benjamin GREGOIRE"})
        self.assertEqual(chats[0]["name"], "Groupe projet")

    def test_placeholder_is_replaced(self):
        # Sans ce correctif, `{{full_name}}` (truthy) bloquait toute la chaîne.
        chats = [{"id": "c1", "name": "{{full_name}}", "attendee_provider_id": "ACoAA_ben"}]
        self._apply(chats, by_attendee={"ACoAA_ben": "Benjamin GREGOIRE"})
        self.assertEqual(chats[0]["name"], "Benjamin GREGOIRE")

    def test_placeholder_in_the_attendee_map_is_ignored(self):
        chats = [{"id": "c1", "name": None, "attendee_provider_id": "ACoAA_ben"}]
        self._apply(chats, by_attendee={"ACoAA_ben": "{{full_name}}"}, by_lead_provider={"ACoAA_ben": "Nom Lead"})
        self.assertEqual(chats[0]["name"], "Nom Lead")

    def test_generic_fallback_when_nothing_matches(self):
        chats = [{"id": "c1", "name": None, "attendee_provider_id": None}]
        self._apply(chats)
        self.assertEqual(chats[0]["name"], "Conversation LinkedIn")


class AttendeeNamesTest(unittest.TestCase):
    """`GET /chat_attendees` — la seule source de nom pour un non-lead."""

    def test_builds_provider_id_to_name_map(self):
        page = {
            "items": [
                {"provider_id": "ACoAA_1", "name": "Benjamin GREGOIRE", "is_self": 0},
                {"provider_id": "ACoAA_2", "name": "Camille Dupont", "is_self": 0},
            ],
            "cursor": None,
        }
        with patch.object(unipile, "_request", return_value=page):
            out = unipile.attendee_names("acc1")
        self.assertEqual(out, {"ACoAA_1": "Benjamin GREGOIRE", "ACoAA_2": "Camille Dupont"})

    def test_excludes_self_and_placeholders(self):
        # Se nommer soi-même donnerait à toutes les conversations le nom du client.
        page = {
            "items": [
                {"provider_id": "ACoAA_me", "name": "Alexandre Errasti", "is_self": 1},
                {"provider_id": "ACoAA_ph", "name": "{{full_name}}", "is_self": 0},
                {"provider_id": "ACoAA_ok", "name": "Camille Dupont", "is_self": 0},
            ],
            "cursor": None,
        }
        with patch.object(unipile, "_request", return_value=page):
            out = unipile.attendee_names("acc1")
        self.assertEqual(out, {"ACoAA_ok": "Camille Dupont"})

    def test_paginates_until_wanted_ids_are_all_found(self):
        pages = [
            {"items": [{"provider_id": "ACoAA_1", "name": "Un", "is_self": 0}], "cursor": "cur1"},
            {"items": [{"provider_id": "ACoAA_2", "name": "Deux", "is_self": 0}], "cursor": "cur2"},
            {"items": [{"provider_id": "ACoAA_3", "name": "Trois", "is_self": 0}], "cursor": "cur3"},
        ]
        calls: list[dict] = []

        def fake(method, path, *, params=None, **kw):
            calls.append(params or {})
            return pages[len(calls) - 1]

        with patch.object(unipile, "_request", side_effect=fake):
            out = unipile.attendee_names("acc1", wanted={"ACoAA_1", "ACoAA_2"})
        # S'arrête dès que les deux noms cherchés sont trouvés : pas de pagination inutile
        # sur un compte qui traîne des milliers de participants.
        self.assertEqual(len(calls), 2)
        self.assertEqual(out, {"ACoAA_1": "Un", "ACoAA_2": "Deux"})
        self.assertEqual(calls[1].get("cursor"), "cur1")

    def test_stops_at_max_pages_when_ids_are_never_found(self):
        page = {"items": [{"provider_id": "ACoAA_x", "name": "Inconnu", "is_self": 0}], "cursor": "c"}
        with patch.object(unipile, "_request", return_value=page) as req:
            unipile.attendee_names("acc1", wanted={"ACoAA_absent"}, max_pages=3)
        self.assertEqual(req.call_count, 3)

    def test_no_account_no_call(self):
        with patch.object(unipile, "_request") as req:
            self.assertEqual(unipile.attendee_names(""), {})
        req.assert_not_called()


class ChatAttendeeNamesTest(unittest.TestCase):
    """`GET /chats/{id}/attendees` — repli ciblé quand le listing par compte ne couvre
    pas les conversations affichées (compte à gros historique)."""

    def test_builds_map_and_excludes_self(self):
        page = {
            "items": [
                {"provider_id": "ACoAA_me", "name": "Alexandre Errasti", "is_self": 1},
                {"provider_id": "ACoAA_1", "name": "Benjamin GREGOIRE", "is_self": 0},
            ]
        }
        with patch.object(unipile, "_request", return_value=page) as req:
            out = unipile.chat_attendee_names("chat1")
        self.assertEqual(out, {"ACoAA_1": "Benjamin GREGOIRE"})
        self.assertIn("/chats/chat1/attendees", req.call_args[0][1])

    def test_no_chat_no_call(self):
        with patch.object(unipile, "_request") as req:
            self.assertEqual(unipile.chat_attendee_names(""), {})
        req.assert_not_called()


if __name__ == "__main__":
    unittest.main()
