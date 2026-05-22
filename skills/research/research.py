#!/usr/bin/env python3
"""
OpenClaw skill: /research — ensemble deep research.

Same backend set as `/search` (DDG web/news, Stack Overflow, GitHub,
Semantic Scholar), but the synthesis layer emits a long-form briefing —
summary, key findings, conflicting claims, follow-up queries — instead of
the compact card the /search skill produces.

CLI:
    python research.py "your question"
    python research.py "your question" --academic
    python research.py "your question" --json
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import aiohttp

# ── Repo root on sys.path ─────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Reuse search.py's backend gather + intent helpers
sys.path.insert(0, str(_REPO_ROOT / "skills"))
from search.search import gather_results, parse_args  # noqa: E402

from core.config import load_runtime_config  # noqa: E402
from core.ensemble import (  # noqa: E402
    DEFAULT_ENSEMBLE,
    EnsembleResult,
    run_ensemble,
)
from core.logging import audit_log  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

SCORER_SYSTEM = """You are an expert research analyst. You receive a research
question and a list of search results, and return a JSON object analysing them:

{
  "answer": "string — 4-8 sentence direct answer, with key qualifiers",
  "confidence": 0.0-1.0,
  "key_findings": [
    {"claim": "...", "supporting_indices": [0, 3, 5], "confidence": 0.0-1.0}
  ],
  "best_sources": [
    {"index": 0, "title": "...", "why": "≤20 words"}
  ],
  "conflicting_claims": [
    {"claim_a": "...", "claim_b": "...", "verdict": "..."}
  ],
  "follow_ups": ["≤6 questions"],
  "limitations": ["≤4 honest gaps in the data"]
}

Rules:
- Cite by index. Never invent sources.
- If results are thin or contradictory, lower confidence — do not bluff.
- Prefer primary sources (paper / official docs) over blog summaries.
- Return ONLY the raw JSON object. No markdown fences. No preamble.
"""

FUSION_SYSTEM = """You are the synthesis layer for a 6-model research ensemble.
You receive 2-6 independent analyses (each with label, tier, weight). Produce
ONE authoritative briefing.

Rules:
1. Average confidence weighted by model weight. Tier-S models (kimi-k2.6,
   qwen3.5-397b) get 1.2x effective weight.
2. Veto: if ALL Tier-S models said confidence<0.3, output a "low-confidence"
   briefing instead of a polished answer.
3. Merge key_findings: keep claims hit by 2+ models, attribute to widest
   supporting_indices set. Drop loners under confidence 0.5.
4. conflicting_claims: keep all unique pairs, dedup by (claim_a, claim_b).
5. Pick best 5-8 sources by frequency-of-mention across models.
6. limitations: union, dedup, max 5.
7. follow_ups: union, dedup, max 8.

Schema:
{
  "answer": "...", "confidence": 0.0-1.0,
  "key_findings": [{"claim": "...", "supporting_indices": [int], "support_count": int}],
  "best_sources": [{"title": "...", "url": "...", "why": "..."}],
  "conflicting_claims": [{"claim_a": "...", "claim_b": "...", "verdict": "..."}],
  "follow_ups": [str], "limitations": [str],
  "model_agreement": int  // how many models contributed to consensus
}

Return ONLY the raw JSON object. No markdown fences. No preamble.
"""


# ══════════════════════════════════════════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def _format_results_for_prompt(results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(results):
        src = (r.get("source") or "web").upper()
        date = f" [{r['date']}]" if r.get("date") else ""
        lines.append(
            f"[{i}] [{src}]{date} {r.get('title', '')[:200]}\n"
            f"    {r.get('url', '')}\n"
            f"    {(r.get('snippet') or '')[:400]}"
        )
    return "\n".join(lines)


async def run_research(query: str, flags: dict, *, as_json: bool) -> int:
    rc = load_runtime_config(require_nim=True)
    audit_log("skill.invoke", skill="research", query_chars=len(query), flags=flags)

    print(f"[research] gathering sources for: {query!r}")
    results = await gather_results(query, flags)
    if not results:
        print("[research] no sources found")
        return 1

    cap = 30 if flags.get("deep") else 20
    results = results[:cap]
    print(f"[research] using {len(results)} sources")

    user_msg = f"QUESTION: {query}\n\nRESULTS ({len(results)}):\n{_format_results_for_prompt(results)}"

    async with aiohttp.ClientSession() as session:
        ensemble: EnsembleResult = await run_ensemble(
            session,
            rc.nim_api_key,
            scorer_system=SCORER_SYSTEM,
            scorer_user=user_msg,
            fusion_system=FUSION_SYSTEM,
            models=DEFAULT_ENSEMBLE,
            local_fallback=None,
            scorer_max_tokens=3000,
            fusion_max_tokens=4000,
        )

    audit_log(
        "skill.complete",
        skill="research",
        fusion_source=ensemble.fusion_source,
        models_succeeded=len(ensemble.outputs),
        models_failed=ensemble.failed_models,
        elapsed_secs=ensemble.total_elapsed_secs,
    )

    fused = ensemble.fused if isinstance(ensemble.fused, dict) else None

    if as_json:
        print(json.dumps({
            "query": query,
            "fusion_source": ensemble.fusion_source,
            "elapsed_secs": ensemble.total_elapsed_secs,
            "models_succeeded": [o.label for o in ensemble.outputs],
            "models_failed": ensemble.failed_models,
            "sources_used": len(results),
            "briefing": fused,
        }, indent=2))
        return 0

    _print_human(query, fused, ensemble, sources=results)
    return 0


def _print_human(query: str, fused: dict | None, ensemble: EnsembleResult, sources: list[dict]) -> None:
    print()
    print("=" * 72)
    print(f"RESEARCH: {query}")
    print(
        f"fusion: {ensemble.fusion_source} · "
        f"models: {len(ensemble.outputs)} ok / {len(ensemble.failed_models)} failed · "
        f"{ensemble.total_elapsed_secs}s · sources: {len(sources)}"
    )
    print("=" * 72)

    if not fused:
        print("\n(no synthesized briefing — fusion failed; raw model outputs above)")
        return

    conf = float(fused.get("confidence", 0.0) or 0.0)
    print(f"\nCONFIDENCE: {conf:.2f}")
    print(f"\nANSWER\n──────\n{fused.get('answer', '').strip()}")

    findings = fused.get("key_findings") or []
    if findings:
        print("\nKEY FINDINGS\n────────────")
        for i, kf in enumerate(findings, 1):
            claim = kf.get("claim", "").strip()
            support = kf.get("support_count") or len(kf.get("supporting_indices", []) or [])
            print(f"{i}. ({support}× supported) {claim}")

    conflicts = fused.get("conflicting_claims") or []
    if conflicts:
        print("\nCONFLICTING CLAIMS\n──────────────────")
        for c in conflicts:
            print(f"• A: {c.get('claim_a', '')}")
            print(f"  B: {c.get('claim_b', '')}")
            verdict = c.get("verdict", "")
            if verdict:
                print(f"  → {verdict}")

    best = fused.get("best_sources") or []
    if best:
        print("\nBEST SOURCES\n────────────")
        for i, s in enumerate(best, 1):
            title = s.get("title", "")
            url = s.get("url", "")
            why = s.get("why", "")
            print(f"{i}. {title}\n   {url}")
            if why:
                print(f"   why: {why}")

    follow_ups = fused.get("follow_ups") or []
    if follow_ups:
        print("\nFOLLOW-UPS\n──────────")
        for q in follow_ups:
            print(f"• {q}")

    limits = fused.get("limitations") or []
    if limits:
        print("\nLIMITATIONS\n───────────")
        for l in limits:
            print(f"• {l}")

    print()


def main() -> int:
    args = sys.argv[1:]
    as_json = "--json" in args
    cli_args = [a for a in args if a != "--json"]
    query, flags = parse_args(cli_args)
    if not query:
        print("Usage: research.py <question> [--web|--news|--code|--academic|--all|--deep] [--json]")
        return 2
    return asyncio.run(run_research(query, flags, as_json=as_json))


if __name__ == "__main__":
    sys.exit(main())
