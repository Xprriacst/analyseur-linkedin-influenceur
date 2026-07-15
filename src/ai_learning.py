"""Cron de distillation des règles apprises (ALE-253).

Run périodiquement sur Render (`python -m src.ai_learning`). Utilise le
client service-role (`db.admin_client`) : pas de session utilisateur ici.

Pour chaque canal (instagram, linkedin) et chaque utilisateur ayant des
corrections non apprises depuis le dernier passage (`ai_reply_feedback`,
`learn_opt_out=false`, `edited=true`, `learned_at is null`) : distille les
règles de style à jour (fusion avec l'existant, pas un remplacement) via
`llm.distill_learned_rules`, les écrit dans `ai_learned_rules`, puis marque
les lignes traitées.

Idempotent et isolé par user/canal : un échec (LLM, réseau) sur un
utilisateur n'empêche jamais les autres de progresser.
"""
from __future__ import annotations

import sys

from src import db
from src.llm import distill_learned_rules

CHANNELS = ("instagram", "linkedin")

# En dessous de ce nombre de corrections en attente, on repousse la
# distillation au prochain passage — une seule édition isolée est trop peu
# pour dégager un vrai pattern, et coûte un appel LLM pour rien.
_MIN_EDITS_TO_DISTILL = 3


def _distill_for_user(user_id: str, channel: str) -> bool:
    pending = db.admin_list_pending_feedback(user_id, channel)
    if len(pending) < _MIN_EDITS_TO_DISTILL:
        print(f"  · {user_id} [{channel}]: {len(pending)} édition(s) en attente, sous le seuil, skip")
        return False

    current_rules = db.admin_get_learned_rules(user_id, channel)
    edits = [{"suggested": p["suggested_text"], "sent": p["sent_text"]} for p in pending]
    try:
        new_rules = distill_learned_rules(current_rules, edits, channel)
    except Exception as exc:
        print(f"  ✗ {user_id} [{channel}]: distillation échouée ({exc})", file=sys.stderr)
        return False
    if not new_rules:
        print(f"  · {user_id} [{channel}]: distillation vide, skip (rien marqué appris)")
        return False

    db.admin_set_learned_rules(user_id, channel, new_rules)
    db.admin_mark_feedback_learned([p["id"] for p in pending])
    print(f"  ✓ {user_id} [{channel}]: {len(pending)} édition(s) distillée(s)")
    return True


def main() -> int:
    if not db.admin_enabled():
        print("SUPABASE_SERVICE_ROLE_KEY manquant — cron désactivé.", file=sys.stderr)
        return 1

    total_ok = 0
    total_users = 0
    for channel in CHANNELS:
        users = db.admin_list_users_with_pending_feedback(channel)
        total_users += len(users)
        print(f"Apprentissage {channel} — {len(users)} utilisateur(s) avec des corrections en attente")
        for user_id in users:
            try:
                if _distill_for_user(user_id, channel):
                    total_ok += 1
            except Exception as exc:  # isolation par user : un échec ne bloque pas les autres
                print(f"  ✗ {user_id} [{channel}]: {exc}", file=sys.stderr)

    print(f"Terminé : {total_ok}/{total_users} distillation(s) appliquée(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
