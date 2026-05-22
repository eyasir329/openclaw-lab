"""
core.cost — rough cost / token accounting helpers.

NVIDIA NIM free tier doesn't bill per token today, but we still want to know
how much we'd be on the hook for if NIM ever flips on metering. This module
provides:

    * `estimate_cost(usage, model)` — $USD from a NIM `usage` dict.
    * `accumulate(records)` — fold a list of usage records into totals.

Prices are placeholders documented as `(prompt_per_M, completion_per_M)` in
USD. They are intentionally per-model so the table can be refreshed without
touching call sites. When pricing for a model is unknown, the helper returns
zero and flags the model in the result — never silently treats it as free.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Pricing table ─────────────────────────────────────────────────────────────
# Values are illustrative placeholders. Refresh when NIM publishes real rates.

_NIM_PRICES_PER_M: dict[str, tuple[float, float]] = {
    "moonshotai/kimi-k2.6":                     (0.50, 1.50),
    "qwen/qwen3.5-397b-a17b":                   (0.60, 1.80),
    "nvidia/nemotron-3-super-120b-a12b":        (0.40, 1.20),
    "nvidia/llama-3.3-nemotron-super-49b-v1.5": (0.20, 0.60),
    "meta/llama-4-maverick-17b-128e-instruct":  (0.10, 0.30),
    "mistralai/mistral-small-4-119b-2603":      (0.30, 0.90),
    "nvidia/openai/gpt-oss-120b":               (0.40, 1.20),
    "nvidia/openai/gpt-oss-20b":                (0.10, 0.30),
    "nvidia/meta/llama-3.3-70b-instruct":       (0.25, 0.75),
}


@dataclass
class CostBreakdown:
    """Per-call cost result."""

    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_usd: float
    has_price: bool


@dataclass
class CostTotal:
    """Aggregate across N calls."""

    calls: int
    total_tokens: int
    total_usd: float
    unpriced_models: list[str]


def _prices_for(model: str) -> tuple[float, float] | None:
    # Strip provider prefix and accept canonical id
    candidates = [model]
    if "/" in model and model.startswith("nvidia/"):
        candidates.append(model[len("nvidia/"):])
    for c in candidates:
        if c in _NIM_PRICES_PER_M:
            return _NIM_PRICES_PER_M[c]
    return None


def estimate_cost(usage: dict, model: str) -> CostBreakdown:
    """
    Compute USD cost from a NIM `usage` dict.

    `usage` is the dict returned in the OpenAI-compatible `response.usage`
    field — keys `prompt_tokens`, `completion_tokens`, `total_tokens`.
    """
    p_tok = int(usage.get("prompt_tokens", 0) or 0)
    c_tok = int(usage.get("completion_tokens", 0) or 0)
    t_tok = int(usage.get("total_tokens", p_tok + c_tok) or 0)
    prices = _prices_for(model)
    if not prices:
        return CostBreakdown(model, p_tok, c_tok, t_tok, 0.0, has_price=False)
    p_rate, c_rate = prices
    usd = (p_tok / 1_000_000) * p_rate + (c_tok / 1_000_000) * c_rate
    return CostBreakdown(model, p_tok, c_tok, t_tok, round(usd, 6), has_price=True)


def accumulate(breakdowns: list[CostBreakdown]) -> CostTotal:
    """Sum a list of per-call breakdowns; collect any unpriced model ids."""
    total_tokens = sum(b.total_tokens for b in breakdowns)
    total_usd = round(sum(b.estimated_usd for b in breakdowns), 6)
    unpriced = sorted({b.model for b in breakdowns if not b.has_price})
    return CostTotal(
        calls=len(breakdowns),
        total_tokens=total_tokens,
        total_usd=total_usd,
        unpriced_models=unpriced,
    )


__all__ = [
    "CostBreakdown",
    "CostTotal",
    "accumulate",
    "estimate_cost",
]
