"""Accroches d'invitation Mode Pilote — un appel modèle, persistées.

`compose_pilot_plan` reste de la logique pure (0 LLM). C'est `build_pilot_today`
qui appelle `fill_invite_previews` APRÈS `pick_contacts` : au plus 3 leads, et
seulement ceux qui n'ont pas encore de `invite_preview` en base.

Zéro crédit (même patron que le scoring ICP). Best-effort : une panne modèle
n'empêche jamais d'afficher le plan — on retombe sur le gabarit.
Les invitations LinkedIn restent SANS note (quotas). Le texte généré est
l'aperçu du premier message, pas le corps de l'invitation.
"""
from __future__ import annotations

import os
from typing import Any

from src import db, llm

PILOT_INVITE_PREVIEW_CAP = 500


def needs_preview(lead: dict[str, Any] | None) -> bool:
    """Vrai si ce lead doit passer par le modèle (pas simulé, pas déjà persisté)."""
    if not isinstance(lead, dict):
        return False
    lid = str(lead.get("id") or "").strip()
    if not lid or lid.startswith("sim-"):
        return False
    if str(lead.get("invite_preview") or "").strip():
        return False
    return True


def fill_invite_previews(
    access_token: str,
    targeting: dict[str, Any] | None,
    leads: list[dict[str, Any]],
) -> None:
    """Écrit `invite_preview` sur les leads du lot. Mutates the dicts in place.

    Ne lève jamais : un hoquet Anthropic / persist ne doit pas faire tomber
    la vue du jour. Si la persistance échoue, le texte reste sur le dict pour
    CETTE requête — le prochain chargement retentera.
    """
    try:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return
        pending = [lead for lead in leads if needs_preview(lead)]
        if not pending:
            return
        generated = llm.generate_invite_openers(targeting or {}, pending)
    except Exception as exc:
        print(f"[invite_openers] génération échouée : {exc}", flush=True)
        return
    for lead in pending:
        lid = str(lead.get("id") or "").strip()
        text = str(generated.get(lid) or "").strip()
        if not text:
            continue
        text = text[:PILOT_INVITE_PREVIEW_CAP]
        lead["invite_preview"] = text
        try:
            db.save_lead_invite_preview(access_token, lid, text)
        except Exception:
            # Le texte reste sur le dict pour cette requête.
            continue
