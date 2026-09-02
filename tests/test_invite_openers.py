"""Accroches d'invitation Mode Pilote — pain point + question, commentaire optionnel."""
import os
import unittest
from unittest.mock import patch

import src.llm as llm
from src import invite_openers, pilot_plan as pp


def _lead(**kwargs):
    base = {
        "id": "l1",
        "name": "Charlie Hartig",
        "headline": "CEO at Hartig Drug Company",
        "comment_text": "",
    }
    base.update(kwargs)
    return base


class InviteOpenerPromptTest(unittest.TestCase):
    def test_system_forbids_the_bateau_and_does_not_require_a_comment(self):
        sys = llm.INVITE_OPENER_SYSTEM
        self.assertIn("pain point", sys)
        self.assertIn("question", sys)
        self.assertIn("ton profil correspond", sys)
        self.assertIn("correspond à ce que je cible", sys)
        self.assertIn("BONUS", sys)
        self.assertNotIn("elle a commenté un post", sys)

    def test_batch_maps_messages_by_id(self):
        captured = {}

        def fake(system, user, **kwargs):
            captured["system"] = system
            captured["user"] = user
            return {
                "openers": [
                    {"id": "a", "message": "A, le stock dort encore en linéaire ?"},
                    {"id": "b", "message": "B, tu valides encore les commandes à la main ?"},
                ]
            }

        with patch.object(llm, "_call", side_effect=fake):
            out = llm.generate_invite_openers(
                {"offer": "IA locale pharmacie", "ideal_client": "titulaires"},
                [_lead(id="a"), _lead(id="b", name="Léa")],
            )
        self.assertEqual(out["a"], "A, le stock dort encore en linéaire ?")
        self.assertEqual(out["b"], "B, tu valides encore les commandes à la main ?")
        self.assertIn("comment", captured["user"])
        self.assertIn("Hartig Drug Company", captured["user"])
        self.assertEqual(captured["system"], llm.INVITE_OPENER_SYSTEM)

    def test_works_without_a_comment(self):
        def fake(system, user, **kwargs):
            self.assertIn('"comment": ""', user)
            return {"openers": [{"id": "l1", "message": "Charlie, the overnight count still happens on paper?"}]}

        with patch.object(llm, "_call", side_effect=fake):
            out = llm.generate_invite_openers(
                {"offer": "on-prem AI for pharmacies"},
                [_lead()],
            )
        self.assertIn("overnight count", out["l1"])

    def test_generate_first_message_reuses_the_batch(self):
        with patch.object(
            llm,
            "generate_invite_openers",
            return_value={"_one": "Léa, tu perds encore des heures sur les ruptures ?"},
        ) as batch:
            text = llm.generate_first_message(
                {"offer": "IA pharmacie"},
                {"name": "Léa", "headline": "Titulaire"},
            )
        self.assertIn("ruptures", text)
        sent = batch.call_args[0][1][0]
        self.assertEqual(sent["id"], "_one")
        self.assertEqual(sent["name"], "Léa")

    def test_generate_first_message_raises_when_empty(self):
        with patch.object(llm, "generate_invite_openers", return_value={}):
            with self.assertRaises(RuntimeError):
                llm.generate_first_message({}, {"name": "X"})


class FillInvitePreviewsTest(unittest.TestCase):
    def test_skips_simulated_and_already_stored(self):
        self.assertFalse(invite_openers.needs_preview({"id": "sim-1"}))
        self.assertFalse(invite_openers.needs_preview({"id": "l1", "invite_preview": "déjà là"}))
        self.assertFalse(invite_openers.needs_preview({"id": ""}))
        self.assertTrue(invite_openers.needs_preview(_lead()))

    def test_writes_preview_on_the_lead_and_persists(self):
        lead = _lead()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}, clear=False), \
             patch.object(
                 invite_openers.llm,
                 "generate_invite_openers",
                 return_value={"l1": "Charlie, inventory still a Sunday-night job?"},
             ), \
             patch.object(invite_openers.db, "save_lead_invite_preview") as save:
            invite_openers.fill_invite_previews("tok", {"offer": "x"}, [lead])
        self.assertIn("Sunday-night", lead["invite_preview"])
        save.assert_called_once_with("tok", "l1", lead["invite_preview"])

    def test_llm_failure_does_not_raise(self):
        lead = _lead()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}, clear=False), \
             patch.object(
                 invite_openers.llm,
                 "generate_invite_openers",
                 side_effect=RuntimeError("boom"),
             ):
            invite_openers.fill_invite_previews("tok", {}, [lead])
        self.assertNotIn("invite_preview", lead)

    def test_no_key_is_a_noop(self):
        lead = _lead()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False), \
             patch.object(invite_openers.llm, "generate_invite_openers") as gen:
            invite_openers.fill_invite_previews("tok", {}, [lead])
        gen.assert_not_called()

    def test_persist_failure_still_keeps_in_memory_text(self):
        lead = _lead()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}, clear=False), \
             patch.object(
                 invite_openers.llm,
                 "generate_invite_openers",
                 return_value={"l1": "Charlie, still counting pills by hand?"},
             ), \
             patch.object(
                 invite_openers.db,
                 "save_lead_invite_preview",
                 side_effect=RuntimeError("db down"),
             ):
            invite_openers.fill_invite_previews("tok", {}, [lead])
        self.assertIn("counting pills", lead["invite_preview"])


class ComposeUsesStoredPreviewTest(unittest.TestCase):
    def test_stored_preview_is_the_card_message(self):
        lead = {
            "id": "l1",
            "name": "Charlie Hartig",
            "headline": "CEO at Hartig Drug Company",
            "score": 80,
            "outreach_status": "none",
            "invite_preview": "Charlie, inventory still a Sunday-night job at Hartig?",
        }
        out = pp.compose_pilot_plan(
            profile={"display_name": "Alex"},
            targeting={"offer": "IA pharmacie"},
            generated_posts=[],
            daily_ideas=[],
            leads=[lead],
            library=[],
            followed_handles=set(),
            schedule=[],
            outreach_connected=True,
            publish_connected=True,
            weekly_done=0,
            weekly_total=3,
        )
        self.assertEqual(
            out["plan"]["contacts"][0]["message"],
            "Charlie, inventory still a Sunday-night job at Hartig?",
        )
        self.assertNotIn("correspond à ce que je cible", out["plan"]["contacts"][0]["message"])

    def test_without_preview_falls_back_to_template(self):
        msg = pp.contact_opener(
            {"name": "Charlie", "headline": "CEO at Hartig Drug Company"},
            {"offer": "l'IA en pharmacie"},
        )
        self.assertIn("correspond à ce que je cible", msg)


if __name__ == "__main__":
    unittest.main()
