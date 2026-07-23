"""Nommage des conversations LinkedIn de l'Inbox (correctif « Conversation LinkedIn »).

Deux causes du bug, verrouillées ici :
  1. `normalize_chat` lisait le mauvais champ (`name`/`display_name`) alors qu'Unipile
     range le nom du participant dans `attendee_name` → même quand Unipile embarque le
     participant, le nom était perdu.
  2. Le rattrapage par le nom du lead ne se faisait que par `outreach_chat_id` (renseigné
     pour ~0 lead). On nomme désormais d'abord par `attendee_provider_id` (l'identifiant
     LinkedIn, présent sur chaque conversation ET sur chaque lead contacté).
"""
from __future__ import annotations

import unittest

from src import unipile


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
        self.assertEqual(out["attendee_provider_id"], "ACoAACZ_pid")
        self.assertEqual(out["provider_url"], "https://linkedin.com/in/bg")

    def test_reads_attendee_provider_id_at_chat_top_level(self):
        # Cas 1-to-1 où Unipile met l'identifiant au niveau du chat, sans embarquer l'attendee.
        chat = {"id": "chatBBB", "attendee_provider_id": "ACoAA_top"}
        out = unipile.normalize_chat(chat)
        self.assertEqual(out["attendee_provider_id"], "ACoAA_top")
        # Pas de nom fourni par Unipile → None (l'endpoint nommera par le lead).
        self.assertIsNone(out["name"])

    def test_group_chat_keeps_its_name(self):
        out = unipile.normalize_chat({"id": "g1", "name": "Groupe projet"})
        self.assertEqual(out["name"], "Groupe projet")

    def test_no_participant_no_name(self):
        out = unipile.normalize_chat({"id": "c0"})
        self.assertIsNone(out["name"])
        self.assertIsNone(out["attendee_provider_id"])


class ApplyLeadNamesTest(unittest.TestCase):
    def test_names_by_provider_id_when_unipile_has_no_name(self):
        chats = [{"id": "c1", "name": None, "attendee_provider_id": "ACoAA_ben"}]
        unipile.apply_lead_names(chats, by_provider={"ACoAA_ben": "Benjamin GREGOIRE"}, by_chat={})
        self.assertEqual(chats[0]["name"], "Benjamin GREGOIRE")

    def test_provider_wins_over_chat_id(self):
        chats = [{"id": "c1", "name": None, "attendee_provider_id": "ACoAA_ben"}]
        unipile.apply_lead_names(
            chats, by_provider={"ACoAA_ben": "Nom Provider"}, by_chat={"c1": "Nom ChatId"}
        )
        self.assertEqual(chats[0]["name"], "Nom Provider")

    def test_falls_back_to_chat_id_map(self):
        chats = [{"id": "c1", "name": None, "attendee_provider_id": "ACoAA_inconnu"}]
        unipile.apply_lead_names(chats, by_provider={}, by_chat={"c1": "Nom ChatId"})
        self.assertEqual(chats[0]["name"], "Nom ChatId")

    def test_real_unipile_name_is_kept_over_lead_maps(self):
        chats = [{"id": "c1", "name": "Vrai Nom Unipile", "attendee_provider_id": "ACoAA_ben"}]
        unipile.apply_lead_names(chats, by_provider={"ACoAA_ben": "Nom Lead"}, by_chat={})
        self.assertEqual(chats[0]["name"], "Vrai Nom Unipile")

    def test_generic_fallback_when_nothing_matches(self):
        chats = [{"id": "c1", "name": None, "attendee_provider_id": None}]
        unipile.apply_lead_names(chats, by_provider={}, by_chat={})
        self.assertEqual(chats[0]["name"], "Conversation LinkedIn")


if __name__ == "__main__":
    unittest.main()
