---
name: review
description: >
  Ensemble code-review skill. Sends `git diff` (or a target file/branch) to a
  6-model NVIDIA NIM ensemble in parallel, then fuses findings via Kimi-K2.6.
  Returns ranked bug/risk/nit list with file:line citations. Optimised for
  daily PR review and pre-commit self-review where false-negative cost is high.
---

# /review — Ensemble Code Review

## Trigger phrases

- `/review` — review staged + unstaged changes
- `/review <branch>` — review `git diff <branch>...HEAD`
- `/review <file>` — review a single file
- `/review --pr` — review GitHub PR for current branch (requires `gh`)

## Why ensemble

Single-model review misses ~25% of real bugs in our internal benchmark. Fusing
6 architecturally diverse models (Kimi-K2.6, Qwen3.5-397B, Nemotron-120B,
Nemotron-49B, Llama-4-Maverick, Mistral-119B) and weighting Tier-S models 1.2x
catches the long tail.

## Output

```text
path/to/file.py:42: 🔴 bug: race condition between line 38 and 42 — `state` mutated by another task
path/to/file.py:118: 🟡 risk: pool not closed on error path
totals: 1 🔴 1 🟡 (6 models, 142s)
```

## Implementation

`review.py` orchestrates:

1. Resolve target → text payload (diff / file / branch).
2. Fan-out scorer prompt to `core.ensemble.DEFAULT_ENSEMBLE` (6 models, parallel).
3. Fuse via Kimi-K2.6 at temperature=0. On failure: weighted-average local fusion.
4. Print findings sorted by severity then file:line.

CLI:

```bash
python skills/review/review.py             # diff vs HEAD
python skills/review/review.py main        # diff vs main branch
python skills/review/review.py src/auth.py # single file
```
