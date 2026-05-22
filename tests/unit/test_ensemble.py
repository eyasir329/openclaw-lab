"""Tests for core.ensemble — focuses on the pure-Python fusion fallback."""

from __future__ import annotations

import pytest

from core.ensemble import (
    DEFAULT_ENSEMBLE,
    EnsembleResult,
    ScorerOutput,
    run_ensemble,
    weighted_average_fusion,
)


def _job(url: str, score: float, **extra):
    return {"url": url, "relevance_score": score, **extra}


def _output(label: str, tier: str, weight: float, items: list[dict]) -> ScorerOutput:
    return ScorerOutput(
        label=label, tier=tier, weight=weight,
        elapsed_secs=0.1, parsed=items, raw="",
    )


def test_fusion_drops_singleton_below_threshold():
    outputs = [_output("a", "B", 1.0, [_job("u1", 4.0)])]
    fused = weighted_average_fusion(outputs, key_fn=lambda o: o["url"])
    assert fused == []


def test_fusion_keeps_singleton_above_threshold():
    outputs = [_output("a", "B", 1.0, [_job("u1", 8.0, why="ok")])]
    fused = weighted_average_fusion(outputs, key_fn=lambda o: o["url"])
    assert len(fused) == 1
    assert fused[0]["url"] == "u1"
    assert fused[0]["model_agreement"] == 1
    assert fused[0]["confidence"] == "low"


def test_fusion_boosts_high_agreement():
    items = [_job("u1", 7.0)]
    outputs = [
        _output(f"m{i}", "B", 1.0, items) for i in range(6)
    ]
    fused = weighted_average_fusion(outputs, key_fn=lambda o: o["url"])
    assert len(fused) == 1
    assert fused[0]["model_agreement"] == 6
    assert fused[0]["confidence"] == "high"
    # Score boosted by 1.15x; capped at 10
    assert 7.0 < fused[0]["final_score"] <= 10.0


def test_fusion_tier_s_veto():
    outputs = [
        _output("kimi", "S", 2.0, [_job("u1", 3.0)]),     # veto
        _output("nemo", "A", 1.5, [_job("u1", 9.0)]),     # high score
        _output("mistral", "B", 1.0, [_job("u1", 9.0)]),
    ]
    fused = weighted_average_fusion(outputs, key_fn=lambda o: o["url"])
    assert fused == []  # Tier-S vetoed even though others scored 9.0


def test_fusion_picks_longest_why():
    outputs = [
        _output("a", "B", 1.0, [_job("u1", 8.0, why_relevant="short")]),
        _output("b", "B", 1.0, [_job("u1", 8.0, why_relevant="much longer explanation here")]),
        _output("c", "B", 1.0, [_job("u1", 8.0)]),  # no why
    ]
    fused = weighted_average_fusion(outputs, key_fn=lambda o: o["url"])
    assert fused[0]["why_relevant"] == "much longer explanation here"


def test_fusion_handles_non_list_outputs():
    outputs = [
        _output("a", "B", 1.0, "not a list"),  # type: ignore[arg-type]
        _output("b", "B", 1.0, [_job("u1", 8.0)]),
        _output("c", "B", 1.0, [_job("u1", 8.0)]),
    ]
    fused = weighted_average_fusion(outputs, key_fn=lambda o: o["url"])
    assert len(fused) == 1
    assert fused[0]["url"] == "u1"


def test_fusion_skips_missing_keys():
    outputs = [
        _output("a", "B", 1.0, [{"no_url_field": "x", "relevance_score": 9}]),
        _output("b", "B", 1.0, [_job("u1", 8.0)]),
        _output("c", "B", 1.0, [_job("u1", 8.0)]),
    ]
    fused = weighted_average_fusion(outputs, key_fn=lambda o: o.get("url", ""))
    assert len(fused) == 1


def test_fusion_sorted_by_agreement_then_score():
    outputs = [
        _output("a", "B", 1.0, [_job("u_low_agree", 9.5)]),
        _output("b", "B", 1.0, [
            _job("u_high_agree", 7.0),
            _job("u_low_agree", 9.5),
        ]),
        _output("c", "B", 1.0, [_job("u_high_agree", 7.0)]),
        _output("d", "B", 1.0, [_job("u_high_agree", 7.0)]),
    ]
    fused = weighted_average_fusion(outputs, key_fn=lambda o: o["url"])
    # u_high_agree wins despite lower score: 3 models vs 2.
    # Boost x1.05 applies (3-model consensus): 7.0 * 1.05 = 7.35 -> 7.4 (rounded).
    assert fused[0]["url"] == "u_high_agree"
    assert fused[0]["model_agreement"] == 3
    assert fused[1]["url"] == "u_low_agree"
    assert fused[1]["model_agreement"] == 2


@pytest.mark.asyncio
async def test_run_ensemble_zero_models_returns_none(monkeypatch):
    """If every scorer call fails, fusion_source is 'none' and fused is None."""

    async def fake_scorer_fanout(*args, **kwargs):
        return []

    import core.ensemble as ens
    monkeypatch.setattr(ens, "run_scorer_fanout", fake_scorer_fanout)

    result = await run_ensemble(
        session=None, nim_key="k",
        scorer_system="s", scorer_user="u",
        fusion_system="f",
    )
    assert isinstance(result, EnsembleResult)
    assert result.fusion_source == "none"
    assert result.fused is None
    assert result.outputs == []


@pytest.mark.asyncio
async def test_run_ensemble_single_model_skips_fusion(monkeypatch):
    async def fake_scorer_fanout(*args, **kwargs):
        return [_output("only", "B", 1.0, [{"url": "u1", "relevance_score": 8}])]

    import core.ensemble as ens
    monkeypatch.setattr(ens, "run_scorer_fanout", fake_scorer_fanout)

    result = await run_ensemble(
        session=None, nim_key="k",
        scorer_system="s", scorer_user="u",
        fusion_system="f",
    )
    assert result.fusion_source == "single"
    assert isinstance(result.fused, list)
    assert result.fused[0]["url"] == "u1"


@pytest.mark.asyncio
async def test_run_ensemble_uses_local_fallback_when_kimi_fails(monkeypatch):
    async def fake_scorer_fanout(*args, **kwargs):
        return [
            _output("a", "B", 1.0, [{"url": "u1", "relevance_score": 8.0}]),
            _output("b", "B", 1.0, [{"url": "u1", "relevance_score": 7.0}]),
        ]

    async def fake_fuse(*args, **kwargs):
        return None  # simulate Kimi failure

    import core.ensemble as ens
    monkeypatch.setattr(ens, "run_scorer_fanout", fake_scorer_fanout)
    monkeypatch.setattr(ens, "fuse_with_kimi", fake_fuse)

    result = await run_ensemble(
        session=None, nim_key="k",
        scorer_system="s", scorer_user="u",
        fusion_system="f",
        local_fallback=lambda outs: weighted_average_fusion(outs, key_fn=lambda o: o["url"]),
    )
    assert result.fusion_source == "local"
    assert isinstance(result.fused, list)
    assert len(result.fused) == 1
    assert result.fused[0]["url"] == "u1"


def test_default_ensemble_shape():
    assert len(DEFAULT_ENSEMBLE) == 6
    labels = {m["label"] for m in DEFAULT_ENSEMBLE}
    assert "kimi-k2.6" in labels
    for cfg in DEFAULT_ENSEMBLE:
        assert {"id", "label", "tier", "weight", "timeout"} <= cfg.keys()
        assert cfg["tier"] in ("S", "A", "B")
