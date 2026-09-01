"""Mon profil → Dashboard (backlog Notion, priorité Alex du 2026-08-31).

Vue d'ensemble en lecture seule de la prospection : abonnés (baseline +
progression), invitations, messages, retours. Ce module ne fait QUE de la mise
en forme — pure, testable sans réseau ni base : la lecture des données
(snapshots d'abonnés, `leads`, `linkedin_outreach_actions`, conversations
Unipile) reste dans `api.py` / `src/db.py` / `src/unipile.py`.
"""

from __future__ import annotations

from typing import Any


def follower_progress(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """Baseline (1er relevé connu) + valeur actuelle (dernier relevé) + delta.

    `snapshots` doit déjà être trié du plus ancien au plus récent (fait par la
    requête SQL, pas ici — cette fonction ne trie pas, elle se contente de lire
    le premier et le dernier élément). Aucun relevé ⇒ rien à afficher : ce n'est
    pas une erreur, juste un compte dont le profil LinkedIn n'a jamais été
    analysé (l'app ne scrape jamais pour remplir ce dashboard, cf. l'appelant).
    Un seul relevé ⇒ baseline = current, delta = 0 — pas encore de progression
    mesurable, mais la section reste 'disponible' (le point de départ existe)."""
    clean = [
        s for s in (snapshots or [])
        if isinstance(s, dict) and s.get("follower_count") is not None
    ]
    if not clean:
        return {"available": False, "reason": "no_own_profile_analyzed"}
    baseline = clean[0]
    current = clean[-1]
    delta = int(current["follower_count"]) - int(baseline["follower_count"])
    return {
        "available": True,
        "current": int(current["follower_count"]),
        "current_at": current.get("captured_on"),
        "baseline": int(baseline["follower_count"]),
        "baseline_at": baseline.get("captured_on"),
        "delta": delta,
        "history": [
            {"date": s.get("captured_on"), "followers": int(s["follower_count"])}
            for s in clean
        ],
    }


def reply_progress(
    checks: list[bool | None], total_messaged: int, checked_cap: int
) -> dict[str, Any]:
    """Combien de prospects contactés ont répondu, sur un échantillon BORNÉ
    (best-effort — vérifier chaque conversation coûte un appel Unipile).

    `checks` porte un booléen par conversation vérifiée (True = au moins un
    message venant d'eux trouvé dans les derniers messages lus) ou `None` si
    CETTE conversation précise n'a pas pu être vérifiée (Unipile en échec) —
    exclue du compte plutôt que comptée comme « pas de réponse », sinon une
    panne réseau ferait mentir le chiffre à la baisse."""
    verified = [c for c in (checks or []) if c is not None]
    replied = sum(1 for c in verified if c)
    return {
        "available": True,
        "replied": replied,
        "checked": len(verified),
        "total_messaged": total_messaged,
        "capped": total_messaged > checked_cap,
    }
