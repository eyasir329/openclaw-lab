"""Tests for core.cost — USD estimation from NIM usage dicts."""

from __future__ import annotations

from core.cost import accumulate, estimate_cost


def test_estimate_cost_known_model():
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    cb = estimate_cost(usage, "moonshotai/kimi-k2.6")
    assert cb.has_price is True
    # 0.50 + 1.50 = 2.00 USD for the assumed table
    assert cb.estimated_usd == 2.0
    assert cb.total_tokens == 2_000_000


def test_estimate_cost_unknown_model_returns_zero():
    cb = estimate_cost(
        {"prompt_tokens": 100, "completion_tokens": 100},
        "unknown/model-xyz",
    )
    assert cb.has_price is False
    assert cb.estimated_usd == 0.0


def test_estimate_cost_strips_nvidia_prefix():
    cb_full = estimate_cost(
        {"prompt_tokens": 1_000_000, "completion_tokens": 0},
        "nvidia/nemotron-3-super-120b-a12b",
    )
    cb_short = estimate_cost(
        {"prompt_tokens": 1_000_000, "completion_tokens": 0},
        "nvidia/nemotron-3-super-120b-a12b",
    )
    assert cb_full.has_price is True
    assert cb_short.estimated_usd == cb_full.estimated_usd


def test_accumulate_sums_breakdowns():
    breakdowns = [
        estimate_cost({"prompt_tokens": 100, "completion_tokens": 100}, "moonshotai/kimi-k2.6"),
        estimate_cost({"prompt_tokens": 50,  "completion_tokens": 50},  "unknown/x"),
    ]
    total = accumulate(breakdowns)
    assert total.calls == 2
    assert total.total_tokens == 300
    assert total.unpriced_models == ["unknown/x"]
    assert total.total_usd > 0


def test_estimate_cost_handles_missing_total_tokens():
    cb = estimate_cost(
        {"prompt_tokens": 100, "completion_tokens": 50},  # no total_tokens
        "moonshotai/kimi-k2.6",
    )
    assert cb.total_tokens == 150
