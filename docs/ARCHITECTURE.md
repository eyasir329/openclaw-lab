# Architecture

This document describes how OpenClaw Lab is organised after the 1.0 pro
restructure. If you want to *use* the lab, start with the
[README](../README.md) and [DEPLOYMENT.md](DEPLOYMENT.md). If you want to
extend it, read this first.

---

## High-level shape

```text
┌───────────────────────────────────────────────────────────────────┐
│ Operator entry points                                             │
│   • Claude Code (CLI / VS Code / web)                             │
│   • Telegram bot (@oc_lab329_bot)                                 │
│   • Direct CLI: `python skills/<name>/<name>.py`                  │
└────────────────────┬──────────────────────────────────────────────┘
                     │
                     ▼
┌───────────────────────────────────────────────────────────────────┐
│ OpenClaw Gateway (port 18789 / 8787 forwarded)                    │
│   • Routes Telegram updates → agent runs                          │
│   • Provides slash commands (/model, /think, /new, …)             │
│   • Lives in ~/.openclaw/  (runtime config, sessions, secrets)    │
└────────────────────┬──────────────────────────────────────────────┘
                     │
        ┌────────────┴───────────────────────────┐
        ▼                                        ▼
┌──────────────────────┐                ┌────────────────────────────┐
│ core/                │◀───imports────│ skills/                    │
│   config.py          │                │   caveman/                 │
│   nim_client.py      │                │   caveman-commit/          │
│   ensemble.py        │                │   caveman-compress/        │
│   auth.py            │                │   caveman-review/          │
│   logging.py         │                │   caveman-stats/           │
│   cost.py            │                │   cavecrew/                │
└──────────────────────┘                │   job-search/      ┐       │
                                        │   search/          │ live  │
                                        │   research/  [NEW] │ NIM   │
                                        │   review/    [NEW] ┘       │
                                        └──────────────┬─────────────┘
                                                       │
                                                       ▼
                                        ┌──────────────────────────────┐
                                        │ NVIDIA NIM (42 models)       │
                                        │ integrate.api.nvidia.com/v1  │
                                        └──────────────────────────────┘
```

---

## Directory layout

| Path | Purpose | Notes |
| --- | --- | --- |
| `core/` | Shared Python library imported by every skill | Pure-Python, no I/O at import. |
| `skills/` | One subdir per skill | Each owns its own CLI, prompts, formatting. |
| `agents/` | Claude Code subagents (`.md` frontmatter) | Three cavecrew agents — investigator, builder, reviewer. |
| `src/hooks/` | Claude Code session hooks (Node.js) | Caveman mode tracking, statusline, stats. |
| `src/mcp-servers/` | MCP servers exposed to Claude Code | `caveman-shrink` compresses tool descriptions. |
| `src/rules/` | System prompt fragments injected at session start | Caveman activation, OpenClaw bootstrap. |
| `tests/` | pytest unit tests for `core/` | No network calls. |
| `docs/` | Long-form documentation | This file, deployment, contributing, changelog. |
| `.github/` | Workflows, dependabot, issue/PR templates, CODEOWNERS | CI, secret scan, CodeQL. |
| `.claude/` | Project-wide Claude Code policy | `settings.json` shared; `settings.local.json` gitignored. |
| `data/`, `logs/`, `workspace/` | Runtime state | Contents gitignored, only `.gitkeep` tracked. |

---

## The `core/` library

Six small modules, each with a single responsibility:

### `core.config`

Resolves runtime configuration from `~/.openclaw/openclaw.json` + env vars +
hard-coded defaults. Returns a frozen `RuntimeConfig` dataclass. Never reads
secrets from the file; the NVIDIA API key is **always** env-only (`NVIDIA_API_KEY`).

Public entry points:

- `load_runtime_config(require_nim=True) -> RuntimeConfig`
- `load_config() -> (bot_token, chat_id, nim_key)` (back-compat shim used by older skills)
- `cached_runtime_config()` (memoised)

### `core.nim_client`

Single-call NIM (NVIDIA NIM / OpenAI-compatible) wrapper.

- `call_nim(session, key, model, *, system, user, ...) -> NIMResult` — always
  returns a result; never raises. `NIMResult` carries `ok`, `elapsed`,
  `content`, `parsed` (when `expect_json=True`), `usage`, `http_status`,
  `error`.
- `strip_fences(s)` / `try_parse_json(s)` — tolerant JSON parsing for
  model outputs that occasionally wrap themselves in ```json fences.

### `core.ensemble`

N-model parallel scoring + Kimi-K2.6 weighted-consensus fusion. Extracted
from the original `job_search.py` + `search.py` so multiple skills share one
implementation.

- `DEFAULT_ENSEMBLE` — the 6-model roster (Kimi-K2.6, Qwen3.5-397B,
  Nemotron-120B, Nemotron-49B, Llama-4-Maverick, Mistral-119B).
- `run_scorer_fanout()` — fans out a prompt to N models in parallel.
- `fuse_with_kimi()` — sends model outputs to Kimi-K2.6 at temperature=0.
- `weighted_average_fusion()` — pure-Python fusion fallback (no API risk).
- `run_ensemble()` — orchestrator that picks the right fusion path.

### `core.auth`

Telegram user allowlist. Fail-closed: an unconfigured allowlist rejects
every user. Wire-up paths:

- env var `ALLOWED_TG_USER_IDS=111,222,333`
- `openclaw.json` → `channels.telegram.allowedUsers: [111, 222]`
- both merge

`ensure_allowed(user_id)` raises `TelegramAuthError`. `format_denial()`
returns a generic message that does not leak the allowlist.

### `core.logging`

Append-only JSONL audit log. One event per line. Standard fields: `ts`,
`event`, `pid`, plus arbitrary caller-supplied fields. Known-sensitive keys
(`api_key`, `prompt`, `token`, ...) are recursively redacted before write.
Write failures are silent so a failed log can't take down a skill.

Default path: `<repo>/logs/audit.jsonl`. Override with `OPENCLAW_AUDIT_LOG`.

### `core.cost`

Rough cost / token accounting. NIM free tier doesn't bill today, but the
table is in place for when it does.

- `estimate_cost(usage, model) -> CostBreakdown`
- `accumulate(list_of_breakdowns) -> CostTotal`

---

## Skill conventions

A skill is a self-contained directory under `skills/`:

```text
skills/<name>/
    SKILL.md          ← trigger phrases, when to use, output format
    <name>.py         ← CLI entry: python skills/<name>/<name>.py [args]
    README.md         ← optional deep docs
    requirements.txt  ← optional skill-specific deps
```

Conventions:

1. **Imports from `core/`** — skills add the repo root to `sys.path` and
   import `core.*` directly. They never duplicate ensemble / NIM client
   logic.
2. **Tolerant of partial failure** — every skill returns useful output even
   when half the ensemble models time out. The fusion layer reports
   `models_failed`.
3. **Audit-logged at entry and exit** — `audit_log("skill.invoke", ...)`
   and `audit_log("skill.complete", ...)` bracket the run.
4. **No global state at import** — initialise inside `async def run_*`.
   This keeps `python skills/<name>/<name>.py --help` cheap.

---

## Communication patterns

```text
[CLI / Telegram]
       │
       ▼
 load_runtime_config()  ─────► RuntimeConfig (nim_key, bot_token, ...)
       │
       ▼
 audit_log("skill.invoke", ...)
       │
       ▼
 gather inputs (scrapers / git / files)
       │
       ▼
 run_ensemble(scorer_system, scorer_user, fusion_system, models=DEFAULT_ENSEMBLE)
   │
   ├─► fan-out N NIM calls in parallel
   ├─► fuse with Kimi-K2.6 (temperature=0)
   └─► local_fallback fusion if Kimi fails
       │
       ▼
 emit Telegram MarkdownV2 / stdout JSON / pretty stdout
       │
       ▼
 audit_log("skill.complete", ...)
```

---

## When to add a new skill vs extend an existing one

| Situation | Action |
| --- | --- |
| New question type, same backends as `/search` | Extend `search.py` with a flag |
| New question type, new sources | New skill in `skills/<name>/` |
| New code-review heuristic | Add to `skills/review/review.py` prompts |
| New data source (e.g., RSS feed) | Add a `scrape_*` function in the skill that needs it |
| New ensemble configuration | New constant in the skill; **don't** edit `DEFAULT_ENSEMBLE` |

---

## Testing strategy

- `tests/unit/` is where pure-Python tests live (no network).
- Live-API tests are explicitly marked `@pytest.mark.integration` and are
  not run in CI by default (`pyproject.toml: addopts = ["-ra", ...]` keeps
  the default green without keys).
- `core.ensemble.run_ensemble` is tested with monkeypatched
  `run_scorer_fanout` and `fuse_with_kimi` so behaviour is verified
  without a real API.

---

## Known gaps (future work)

- Telegram allowlist enforcement is provided by `core.auth` but the
  OpenClaw gateway is a Node service we don't control. Until the gateway
  exposes a hook for incoming-update filtering, allowlisting is enforced
  at the skill level — every script that calls NIM also reads the
  allowlist before sending output. See `SECURITY.md` for status.
- Cost table in `core.cost` uses placeholder prices. Refresh when NIM
  publishes its rate sheet.
- Search backends (DDG / Bing / Glassdoor) periodically break their HTML.
  The skill handles failures gracefully but new selectors land in PRs
  rather than auto-updates.
