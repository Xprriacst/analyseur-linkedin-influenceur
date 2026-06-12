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
}

# Actor inconnu : estimation prudente plutôt que $0.0 trompeur
DEFAULT_APIFY_COST = {"per_run": 0.0, "per_item": 0.002}

ANTHROPIC_PRICES_PER_MTOK = {
    "opus": {"input": 15.0, "output": 75.0},
    "sonnet": {"input": 3.0, "output": 15.0},
    "haiku": {"input": 0.25, "output": 1.25},
}

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
    ml = model.lower()
    if "sonnet" in ml:
        return ANTHROPIC_PRICES_PER_MTOK["sonnet"]
    if "haiku" in ml:
        return ANTHROPIC_PRICES_PER_MTOK["haiku"]
    return ANTHROPIC_PRICES_PER_MTOK["opus"]


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
