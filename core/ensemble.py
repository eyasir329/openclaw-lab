"""
core.ensemble — multi-model parallel scoring with weighted fusion.

This is the "max accuracy at any cost" path: fan out the same prompt to N
diverse NIM models in parallel, then either:
    (a) ask Kimi-K2.6 at temperature=0 to fuse them (LLM consensus), or
    (b) fall back to a pure-Python weighted-average fusion (zero API risk).

Extracted from skills/job-search/job_search.py + skills/search/search.py so
multiple skills can reuse the same primitive. Behavior preserved bit-for-bit.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import aiohttp

from .nim_client import NIMResult, call_nim, strip_fences, try_parse_json


# ── Default ensemble roster ───────────────────────────────────────────────────
#
# Tier S — maximum intelligence; kimi-k2.6 also serves as fusion model.
# Tier A — structured JSON specialists.
# Tier B — fast, architecturally diverse.
#
# Weights below feed the local fallback fuser. The Kimi fusion model receives
# the weights in its prompt and applies them in natural language.

DEFAULT_ENSEMBLE: list[dict[str, Any]] = [
    {"id": "moonshotai/kimi-k2.6",                     "label": "kimi-k2.6",           "tier": "S", "weight": 2.0, "timeout": 180},
    {"id": "qwen/qwen3.5-397b-a17b",                   "label": "qwen3.5-397b",        "tier": "S", "weight": 1.8, "timeout": 150},
    {"id": "nvidia/nemotron-3-super-120b-a12b",        "label": "nemotron-super-120b", "tier": "A", "weight": 1.5, "timeout": 120},
    {"id": "nvidia/llama-3.3-nemotron-super-49b-v1.5", "label": "nemotron-super-49b",  "tier": "A", "weight": 1.4, "timeout": 90},
    {"id": "meta/llama-4-maverick-17b-128e-instruct",  "label": "llama4-maverick",     "tier": "B", "weight": 1.0, "timeout": 30},
    {"id": "mistralai/mistral-small-4-119b-2603",      "label": "mistral-small-119b",  "tier": "B", "weight": 1.0, "timeout": 60},
]

DEFAULT_FUSION_MODEL = "moonshotai/kimi-k2.6"
DEFAULT_FUSION_TIMEOUT = 180


# ── Public dataclasses ────────────────────────────────────────────────────────

@dataclass
class ScorerOutput:
    """One model's parsed response plus metadata."""

    label: str
    tier: str
    weight: float
    elapsed_secs: float
    parsed: Any
    raw: str = ""


@dataclass
class EnsembleResult:
    """End-to-end ensemble outcome — raw model outputs + fused result."""

    fused: Any
    outputs: list[ScorerOutput]
    fusion_source: str  # "kimi" | "local" | "single" | "none"
    total_elapsed_secs: float
    failed_models: list[str] = field(default_factory=list)


# ── Scoring fan-out ───────────────────────────────────────────────────────────

async def _score_one(
    session: aiohttp.ClientSession,
    nim_key: str,
    model_cfg: dict[str, Any],
    system: str,
    user: str,
    *,
    expect_json: bool,
    max_tokens: int,
    temperature: float,
) -> ScorerOutput | None:
    result: NIMResult = await call_nim(
        session,
        nim_key,
        model_cfg["id"],
        system=system,
        user=user,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=float(model_cfg.get("timeout", 60)),
        expect_json=expect_json,
    )
    label = model_cfg.get("label", model_cfg["id"])
    if not result.ok:
        print(f"[ensemble] {label} ✗ {result.error}")
        return None
    print(f"[ensemble] {label} ✓ {result.elapsed_secs}s")
    return ScorerOutput(
        label=label,
        tier=model_cfg.get("tier", "B"),
        weight=float(model_cfg.get("weight", 1.0)),
        elapsed_secs=result.elapsed_secs,
        parsed=result.parsed if expect_json else result.content,
        raw=result.content,
    )


async def run_scorer_fanout(
    session: aiohttp.ClientSession,
    nim_key: str,
    system: str,
    user: str,
    *,
    models: list[dict[str, Any]] | None = None,
    expect_json: bool = True,
    max_tokens: int = 4000,
    temperature: float = 0.1,
) -> list[ScorerOutput]:
    """
    Fire all `models` in parallel with the same (system, user) prompt.
    Returns only the models that responded successfully.
    """
    roster = models or DEFAULT_ENSEMBLE
    print(f"[ensemble] firing {len(roster)} models in parallel …")
    raw = await asyncio.gather(
        *[
            _score_one(
                session, nim_key, cfg, system, user,
                expect_json=expect_json,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            for cfg in roster
        ],
        return_exceptions=True,
    )
    outputs = [o for o in raw if isinstance(o, ScorerOutput)]
    print(f"[ensemble] {len(outputs)}/{len(roster)} responded")
    return outputs


# ── Kimi fusion ───────────────────────────────────────────────────────────────

async def fuse_with_kimi(
    session: aiohttp.ClientSession,
    nim_key: str,
    fusion_prompt_system: str,
    fusion_payload: Any,
    *,
    model: str = DEFAULT_FUSION_MODEL,
    timeout: float = DEFAULT_FUSION_TIMEOUT,
    max_tokens: int = 6000,
) -> Any:
    """
    Send pre-built fusion payload to Kimi-K2.6 at temperature=0.
    Returns parsed JSON, or None on failure (caller should fall back).
    """
    user_msg = (
        fusion_payload
        if isinstance(fusion_payload, str)
        else json.dumps(fusion_payload, ensure_ascii=False)
    )
    result = await call_nim(
        session,
        nim_key,
        model,
        system=fusion_prompt_system,
        user=user_msg,
        temperature=0.0,
        max_tokens=max_tokens,
        timeout=timeout,
        expect_json=True,
    )
    if not result.ok:
        print(f"[ensemble] kimi fusion failed: {result.error}")
        return None
    print(f"[ensemble] kimi fusion ✓ {result.elapsed_secs}s")
    return result.parsed


# ── Local fallback: weighted-average fusion over list-of-objects ──────────────

def weighted_average_fusion(
    outputs: list[ScorerOutput],
    *,
    key_fn: Callable[[dict[str, Any]], str],
    score_key: str = "relevance_score",
    tier_s_multiplier: float = 1.2,
    consensus_thresholds: tuple[tuple[int, float], ...] = ((5, 1.15), (3, 1.05)),
    veto_tier: str = "S",
    veto_below: float = 5.0,
    drop_singleton_below: float = 7.0,
) -> list[dict[str, Any]]:
    """
    Pure-Python fusion for list-of-objects outputs. Mirrors the rules baked into
    `skills/job-search/job_search.py` so behavior is identical when this fallback
    fires.

    Rules:
      - per-key score = weighted average across models that included that key
      - if a Tier-S model scored < `veto_below` for a key, drop it
      - if only 1 model included a key AND its score < `drop_singleton_below`, drop
      - boost by `consensus_thresholds` (sorted high → low; first match wins)
      - confidence: high (≥5), medium (3-4), low (1-2)

    `key_fn` extracts the dedup key (typically `lambda o: o["url"]`).
    """
    from collections import defaultdict

    bucket: dict[str, list[tuple[float, float, str, str]]] = defaultdict(list)
    best: dict[str, dict[str, Any]] = {}

    for out in outputs:
        items = out.parsed
        if not isinstance(items, list):
            continue
        eff_w = out.weight * (tier_s_multiplier if out.tier == veto_tier else 1.0)
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                k = key_fn(item)
            except Exception:
                continue
            if not k:
                continue
            try:
                s = float(item.get(score_key, 5.0))
            except (TypeError, ValueError):
                s = 5.0
            bucket[k].append((s, eff_w, out.tier, out.label))
            if k not in best:
                best[k] = dict(item)
            # Merge: prefer longer "why" + first non-empty "note"
            for txt_field in ("why_relevant", "why", "apply_note", "note"):
                cur = best[k].get(txt_field, "")
                inc = item.get(txt_field, "")
                if isinstance(inc, str) and len(inc) > len(cur or ""):
                    best[k][txt_field] = inc

    fused: list[dict[str, Any]] = []
    for k, entries in bucket.items():
        agreement = len(entries)

        if agreement == 1 and entries[0][0] < drop_singleton_below:
            continue

        tier_veto = [s for s, _, t, _ in entries if t == veto_tier]
        if tier_veto and max(tier_veto) < veto_below:
            continue

        total_w = sum(w for _, w, _, _ in entries)
        score = sum(s * w for s, w, _, _ in entries) / total_w

        for threshold, multiplier in sorted(consensus_thresholds, reverse=True):
            if agreement >= threshold:
                score = min(score * multiplier, 10.0)
                break

        confidence = "high" if agreement >= 5 else "medium" if agreement >= 3 else "low"

        record = dict(best[k])
        record.update({
            "final_score": round(score, 1),
            "model_agreement": agreement,
            "confidence": confidence,
        })
        fused.append(record)

    fused.sort(key=lambda x: (-x["model_agreement"], -x["final_score"]))
    return fused


# ── High-level orchestrator ───────────────────────────────────────────────────

async def run_ensemble(
    session: aiohttp.ClientSession,
    nim_key: str,
    scorer_system: str,
    scorer_user: str,
    fusion_system: str,
    *,
    models: list[dict[str, Any]] | None = None,
    fusion_model: str = DEFAULT_FUSION_MODEL,
    local_fallback: Callable[[list[ScorerOutput]], Any] | None = None,
    expect_json: bool = True,
    scorer_max_tokens: int = 4000,
    scorer_temperature: float = 0.1,
    fusion_max_tokens: int = 6000,
) -> EnsembleResult:
    """
    Full multi-model ensemble pipeline:

      1. Fan-out scorer to N models (parallel).
      2. If 0 models respond  → return empty fused, fusion_source="none".
      3. If 1 model responds  → return its parsed output as `fused`, source="single".
      4. If ≥2 models respond → call Kimi fusion at temperature=0.
      5. If Kimi fails → call `local_fallback(outputs)` if provided, source="local".

    `local_fallback` is a pure-python fuser; most callers pass
    `lambda outs: weighted_average_fusion(outs, key_fn=lambda o: o["url"])`.
    """
    t0 = time.monotonic()

    outputs = await run_scorer_fanout(
        session, nim_key, scorer_system, scorer_user,
        models=models,
        expect_json=expect_json,
        max_tokens=scorer_max_tokens,
        temperature=scorer_temperature,
    )

    roster_labels = {m.get("label", m["id"]) for m in (models or DEFAULT_ENSEMBLE)}
    success_labels = {o.label for o in outputs}
    failed = sorted(roster_labels - success_labels)

    if not outputs:
        return EnsembleResult(
            fused=None,
            outputs=[],
            fusion_source="none",
            total_elapsed_secs=round(time.monotonic() - t0, 2),
            failed_models=failed,
        )

    if len(outputs) == 1:
        return EnsembleResult(
            fused=outputs[0].parsed,
            outputs=outputs,
            fusion_source="single",
            total_elapsed_secs=round(time.monotonic() - t0, 2),
            failed_models=failed,
        )

    fusion_payload = {
        "models": [
            {
                "label": o.label,
                "tier": o.tier,
                "weight": o.weight,
                "elapsed_secs": o.elapsed_secs,
                "output": o.parsed,
            }
            for o in outputs
        ],
    }
    fused = await fuse_with_kimi(
        session, nim_key, fusion_system, fusion_payload,
        model=fusion_model,
        max_tokens=fusion_max_tokens,
    )

    if fused is not None:
        return EnsembleResult(
            fused=fused,
            outputs=outputs,
            fusion_source="kimi",
            total_elapsed_secs=round(time.monotonic() - t0, 2),
            failed_models=failed,
        )

    if local_fallback is not None:
        fused = local_fallback(outputs)
        return EnsembleResult(
            fused=fused,
            outputs=outputs,
            fusion_source="local",
            total_elapsed_secs=round(time.monotonic() - t0, 2),
            failed_models=failed,
        )

    return EnsembleResult(
        fused=None,
        outputs=outputs,
        fusion_source="none",
        total_elapsed_secs=round(time.monotonic() - t0, 2),
        failed_models=failed,
    )


__all__ = [
    "DEFAULT_ENSEMBLE",
    "DEFAULT_FUSION_MODEL",
    "DEFAULT_FUSION_TIMEOUT",
    "ScorerOutput",
    "EnsembleResult",
    "run_scorer_fanout",
    "fuse_with_kimi",
    "weighted_average_fusion",
    "run_ensemble",
    "strip_fences",
    "try_parse_json",
]
