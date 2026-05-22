---
name: research
description: >
  Deep-research skill. Given a question, gathers web + news + (optional)
  academic context, then runs a 6-model NIM ensemble to produce a fused
  long-form briefing with citations, key facts, and follow-up queries.
  Higher latency than `/search`; use for questions where accuracy matters.
---

# /research — Ensemble Deep Research

## When to use

- "Investigate X" / "research Y" — anything where you'd skim 6+ sources.
- Decisions where conflicting source claims need reconciling.
- Pre-write briefings for a PR description or design doc.

For quick lookups, use `/search` — same backends, smaller payload, faster.

## Pipeline

1. Gather up to 30 sources via DDG web, DDG news, Stack Overflow, GitHub,
   Semantic Scholar (intent-driven, same backends as `/search`).
2. Fan out to 6 NIM models (Tier-S: Kimi-K2.6 + Qwen3.5-397B; Tier-A:
   Nemotron-120B + Nemotron-49B; Tier-B: Llama-4 + Mistral-119B).
3. Fuse with Kimi-K2.6 at temperature=0.
4. Emit a long-form briefing: summary, key findings (4-8), best sources (5-8),
   conflicting claims (if any), follow-up questions.

CLI:

```bash
python skills/research/research.py "your research question"
python skills/research/research.py "your question" --academic
python skills/research/research.py "your question" --json
```
