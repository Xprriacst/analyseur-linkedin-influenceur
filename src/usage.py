"""Usage counters for Apify and Anthropic calls."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


APIFY_COSTS = {
    "supreme_coder/linkedin-profile-scraper": {"per_run": 0.003, "per_item": 0.0},
    "apimaestro/linkedin-profile-posts": {"per_run": 0.0, "per_item": 0.00005},
    "harvestapi/linkedin-company-posts": {"per_run": 0.0, "per_item": 0.002},
    "harvestapi/linkedin-profile-posts": {"per_run": 0.00005, "per_item": 0.002},
    "harvestapi/linkedin-profile-scraper": {"per_run": 0.00005, "per_item": 0.004},
    "apimaestro/linkedin-profile-detail": {"per_run": 0.0, "per_item": 0.005},
}

# Actor inconnu : estimation prudente plutôt que $0.0 trompeur
DEFAULT_APIFY_COST = {"per_run": 0.0, "per_item": 0.002}

# Prix réels par MILLION de tokens (input/output), mesurés en prod le
# 2026-09-02 sur les appels déjà migrés vers Sonnet 5 : l'ancienne table
# (opus 15/75, sonnet 3/15, haiku 0.25/1.25) surestimait le coût réel de ~50%.
# Clé = identifiant EXACT de modèle, PAS une sous-chaîne — c'était le bug :
# tout modèle qui n'était ni "sonnet" ni "haiku" retombait sur le tarif "opus"
# en silence (Fable, un futur modèle…), deux fois trop bas pour Fable (10/50).
ANTHROPIC_PRICES_PER_MTOK: dict[str, dict[str, float]] = {
    "claude-opus-5": {"input": 5.0, "output": 25.0},
    "claude-opus-4-8": {"input": 5.0, "output": 25.0},
    "claude-opus-4-7": {"input": 5.0, "output": 25.0},
    "claude-opus-4-6": {"input": 5.0, "output": 25.0},
    "claude-sonnet-5": {"input": 2.0, "output": 10.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
    "claude-fable-5-1": {"input": 10.0, "output": 50.0},
    "claude-fable-5": {"input": 10.0, "output": 50.0},
    "claude-mythos-5-1": {"input": 10.0, "output": 50.0},
}

# Repli EXPLICITE si le modèle exact est absent de la table ci-dessus (modèle
# pas encore répertorié ici) : tarif du palier Opus, le plus courant en prod —
# mais nommé comme un repli assumé, pas un match par sous-chaîne qui range
# n'importe quel modèle inconnu sous "opus" sans que ça se voie. Un modèle qui
# atterrit ici mérite d'être ajouté explicitement à la table ci-dessus.
_DEFAULT_PRICE_PER_MTOK = {"input": 5.0, "output": 25.0}

_USAGE: dict[str, Any] = {}


def reset_usage() -> None:
    global _USAGE
    _USAGE = {
        "apify": {
            "runs": 0,
            "items": 0,
            "cached_runs": 0,
            "estimated_cost_usd": 0.0,
            "calls": [],
        },
        "anthropic": {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_usd": 0.0,
            "details": [],
        },
    }


def get_usage() -> dict[str, Any]:
    if not _USAGE:
        reset_usage()
    return deepcopy(_USAGE)


def _apify_cost(actor: str, items: int) -> float:
    cfg = APIFY_COSTS.get(actor, DEFAULT_APIFY_COST)
    return round(cfg["per_run"] + cfg["per_item"] * items, 6)


def track_apify(actor: str, items: int, cached: bool = False) -> None:
    if not _USAGE:
        reset_usage()
    cost = 0.0 if cached else _apify_cost(actor, items)
    _USAGE["apify"]["runs"] += 0 if cached else 1
    _USAGE["apify"]["cached_runs"] += 1 if cached else 0
    _USAGE["apify"]["items"] += items
    _USAGE["apify"]["estimated_cost_usd"] = round(_USAGE["apify"]["estimated_cost_usd"] + cost, 6)
    _USAGE["apify"]["calls"].append(
        {"actor": actor, "items": items, "cached": cached, "estimated_cost_usd": cost}
    )


def _anthropic_price(model: str) -> dict[str, float]:
    return ANTHROPIC_PRICES_PER_MTOK.get(model, _DEFAULT_PRICE_PER_MTOK)


def track_anthropic(model: str, input_tokens: int, output_tokens: int) -> None:
    if not _USAGE:
        reset_usage()
    price = _anthropic_price(model)
    cost = round((input_tokens / 1_000_000) * price["input"] + (output_tokens / 1_000_000) * price["output"], 6)
    _USAGE["anthropic"]["calls"] += 1
    _USAGE["anthropic"]["input_tokens"] += input_tokens
    _USAGE["anthropic"]["output_tokens"] += output_tokens
    _USAGE["anthropic"]["estimated_cost_usd"] = round(_USAGE["anthropic"]["estimated_cost_usd"] + cost, 6)
    _USAGE["anthropic"]["details"].append(
        {"model": model, "input_tokens": input_tokens, "output_tokens": output_tokens, "estimated_cost_usd": cost}
    )


reset_usage()
