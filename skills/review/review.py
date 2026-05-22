#!/usr/bin/env python3
"""
OpenClaw skill: /review — ensemble code review.

Resolves a review target (uncommitted diff, branch diff, or single file),
fans out to a 6-model NVIDIA NIM ensemble, fuses findings via Kimi-K2.6,
and prints a severity-sorted list with file:line citations.

CLI:
    python review.py              # diff vs HEAD (staged + unstaged)
    python review.py <branch>     # diff <branch>...HEAD
    python review.py <file>       # whole-file review
    python review.py --pr         # gh pr diff (current branch)
    python review.py --json       # machine-readable output
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import aiohttp

# ── Add repo root to sys.path so `core.*` is importable ───────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.config import load_runtime_config
from core.ensemble import (
    DEFAULT_ENSEMBLE,
    EnsembleResult,
    run_ensemble,
    weighted_average_fusion,
)
from core.logging import audit_log

# ══════════════════════════════════════════════════════════════════════════════
# PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

SCORER_SYSTEM = """You are a senior code reviewer. You receive a code diff or
file and return findings as a JSON array. Each finding MUST have exactly:

{
  "file": "string — relative path",
  "line": 42,
  "severity": "bug" | "risk" | "nit" | "question",
  "title": "string — ≤80 chars, what is wrong",
  "explanation": "string — ≤300 chars, why it matters, with code context",
  "fix": "string — concrete actionable fix, ≤200 chars",
  "confidence": 0.0
}

Rules:
- "bug"      = wrong output, crash, security hole, data loss, off-by-one
- "risk"     = edge case, race, leak, perf cliff, missing guard
- "nit"      = style/naming/micro-perf — only if asked thorough
- "question" = need author intent before judging

Confidence is your own 0.0-1.0 score. Skip findings you wouldn't bet $1 on.
No praise. No "looks good". No preamble. Return ONLY the raw JSON array.
"""

FUSION_SYSTEM = """You are the fusion layer for a 6-model code review ensemble.
You receive each model's findings list (with model label + weight) and must
produce ONE unified finding list using weighted consensus.

Rules:
1. Group findings by (file, line) — within ±2 lines they're the same finding.
2. Drop findings hit by only 1 model unless severity=bug AND confidence>0.8.
3. Boost confidence by +0.10 when 3+ models agree; +0.20 when 5+ agree.
4. Veto: if Tier-S models (kimi-k2.6, qwen3.5-397b) gave confidence<0.3, drop.
5. Pick the sharpest "explanation" and "fix" across the cluster.
6. Sort by: severity (bug>risk>nit>question), then -final_confidence, then file:line.
7. Cap output at 30 findings (most important first).

Return a JSON array. Each item:
{
  "file": "...", "line": int, "severity": "...", "title": "...",
  "explanation": "...", "fix": "...",
  "final_confidence": float, "model_agreement": int
}

Return ONLY the raw JSON array. No markdown fences. No preamble.
"""


# ══════════════════════════════════════════════════════════════════════════════
# TARGET RESOLUTION
# ══════════════════════════════════════════════════════════════════════════════

def _git(*args: str, cwd: Path = _REPO_ROOT) -> str:
    """Run a git command and return stdout. Empty on failure."""
    try:
        out = subprocess.check_output(
            ["git", *args], cwd=str(cwd), stderr=subprocess.DEVNULL, text=True, timeout=15,
        )
        return out
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def resolve_target(arg: str | None) -> tuple[str, str]:
    """
    Resolve CLI arg → (label, payload-text).
    label is short for the audit log; payload-text is what we send the models.
    """
    if arg is None:
        diff = _git("diff", "HEAD") or _git("diff", "--cached")
        return ("diff-HEAD", diff or "(no changes to review)")

    if arg == "--pr":
        branch = _git("rev-parse", "--abbrev-ref", "HEAD").strip()
        if not branch:
            return ("pr", "(could not resolve current branch)")
        diff = subprocess.run(
            ["gh", "pr", "diff", "--branch", branch],
            cwd=str(_REPO_ROOT),
            capture_output=True, text=True, timeout=30,
        ).stdout
        return (f"pr:{branch}", diff or "(no PR diff)")

    p = Path(arg)
    if p.exists() and p.is_file():
        return (f"file:{arg}", p.read_text(errors="replace"))

    branches = _git("branch", "-a", "--format=%(refname:short)")
    if arg in branches.split():
        diff = _git("diff", f"{arg}...HEAD")
        return (f"branch:{arg}", diff or "(no diff vs branch)")

    return (f"raw:{arg}", arg)


# ══════════════════════════════════════════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════════════════════════════════════════

async def run_review(target_arg: str | None, *, as_json: bool = False) -> int:
    rc = load_runtime_config(require_nim=True)
    label, payload = resolve_target(target_arg)

    if not payload.strip() or payload.startswith("("):
        print(f"[review] nothing to review — target={label}")
        return 0

    truncated = payload[:60_000]  # cap context so all models accept it
    if len(payload) > len(truncated):
        print(f"[review] payload truncated to 60_000 chars (was {len(payload)})")

    user_msg = f"REVIEW TARGET: {label}\n\n```\n{truncated}\n```"

    audit_log("skill.invoke", skill="review", target=label, payload_chars=len(truncated))

    async with aiohttp.ClientSession() as session:
        result: EnsembleResult = await run_ensemble(
            session,
            rc.nim_api_key,
            scorer_system=SCORER_SYSTEM,
            scorer_user=user_msg,
            fusion_system=FUSION_SYSTEM,
            models=DEFAULT_ENSEMBLE,
            local_fallback=lambda outs: weighted_average_fusion(
                outs,
                key_fn=lambda o: f"{o.get('file', '')}:{o.get('line', 0)}",
                score_key="confidence",
                drop_singleton_below=0.5,
                veto_below=0.3,
            ),
            scorer_max_tokens=3000,
        )

    audit_log(
        "skill.complete",
        skill="review",
        target=label,
        fusion_source=result.fusion_source,
        models_succeeded=len(result.outputs),
        models_failed=result.failed_models,
        elapsed_secs=result.total_elapsed_secs,
    )

    findings = result.fused if isinstance(result.fused, list) else []

    if as_json:
        print(json.dumps({
            "target": label,
            "fusion_source": result.fusion_source,
            "elapsed_secs": result.total_elapsed_secs,
            "models_succeeded": [o.label for o in result.outputs],
            "models_failed": result.failed_models,
            "findings": findings,
        }, indent=2))
        return 0

    _print_human(label, findings, result)
    return 0


def _print_human(label: str, findings: list[dict], result: EnsembleResult) -> None:
    sev_order = {"bug": 0, "risk": 1, "nit": 2, "question": 3}
    sev_emoji = {"bug": "🔴", "risk": "🟡", "nit": "🔵", "question": "❓"}

    def sort_key(f: dict) -> tuple:
        return (
            sev_order.get(f.get("severity", "nit"), 9),
            -float(f.get("final_confidence", f.get("confidence", 0.0)) or 0.0),
            f.get("file", ""),
            int(f.get("line", 0) or 0),
        )

    findings_sorted = sorted(findings, key=sort_key)

    print()
    print(f"# Review — {label}")
    print(
        f"# fusion: {result.fusion_source} · "
        f"models: {len(result.outputs)} ok / {len(result.failed_models)} failed · "
        f"{result.total_elapsed_secs}s"
    )
    print()

    if not findings_sorted:
        print("No issues.")
        return

    for f in findings_sorted:
        sev = f.get("severity", "nit")
        path = f.get("file", "?")
        line = f.get("line", "?")
        title = (f.get("title") or "").strip()
        emoji = sev_emoji.get(sev, "•")
        print(f"{path}:{line}: {emoji} {sev}: {title}")
        fix = (f.get("fix") or "").strip()
        if fix:
            print(f"    fix: {fix}")

    counts = {sev: 0 for sev in sev_order}
    for f in findings_sorted:
        counts[f.get("severity", "nit")] = counts.get(f.get("severity", "nit"), 0) + 1
    totals = "  ".join(
        f"{sev_emoji[s]} {counts[s]}"
        for s in ("bug", "risk", "nit", "question") if counts.get(s)
    )
    print()
    print(f"totals: {totals or 'none'}")


def main() -> int:
    args = sys.argv[1:]
    as_json = "--json" in args
    pos = [a for a in args if not a.startswith("--")]
    target = pos[0] if pos else None
    if "--pr" in args and target is None:
        target = "--pr"
    return asyncio.run(run_review(target, as_json=as_json))


if __name__ == "__main__":
    sys.exit(main())
