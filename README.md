# OpenClaw Lab

[![CI](https://github.com/eyasir329/openclaw-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/eyasir329/openclaw-lab/actions/workflows/ci.yml)
[![Secret scan](https://github.com/eyasir329/openclaw-lab/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/eyasir329/openclaw-lab/actions/workflows/secret-scan.yml)
[![CodeQL](https://github.com/eyasir329/openclaw-lab/actions/workflows/codeql.yml/badge.svg)](https://github.com/eyasir329/openclaw-lab/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A personal AI lab built around the OpenClaw gateway, NVIDIA NIM (42 verified
models on a single key), Telegram, and Claude Code. Optimised for **daily
work**: code review, deep research, web search, and job-search automation —
all routed through a 6-model parallel ensemble for accuracy where it matters.

> **v1.0 — professional restructure.** A shared `core/` library, 47 unit
> tests in CI, `gitleaks` + CodeQL scanning, a fail-closed Telegram
> allowlist, structured audit logging, and explicit Claude Code
> deny-rules. See [docs/CHANGELOG.md](docs/CHANGELOG.md).

## Documentation

| Reading order | Doc |
| --- | --- |
| 1 (start here) | This README — quick tour, setup, gateway, Telegram, models |
| 2              | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — Codespaces & local setup, ops tasks, troubleshooting |
| 3              | [docs/SKILLS.md](docs/SKILLS.md) — every skill, when to use it, CLI commands |
| 4              | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — `core/` library, skill conventions, data flow |
| 5              | [SECURITY.md](SECURITY.md) — threat model, hardening checklist, vuln reporting |
| 6              | [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) — code style, test layout, PR rules |
| 7              | [docs/CHANGELOG.md](docs/CHANGELOG.md) — release history |

## Table of Contents

- [Architecture](#architecture)
- [Directory Structure](#directory-structure)
- [Setup](#setup)
- [OpenClaw Gateway](#openclaw-gateway)
- [Telegram Usage](#telegram-usage)
- [Model Switching](#model-switching)
- [Available Models](#available-models)
- [Skills](#skills)
- [Agents](#agents)
- [Claude Code Integration](#claude-code-integration)
- [Environment Variables](#environment-variables)
- [Security](#security)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

---

## Architecture

```text
GitHub Codespaces
└── OpenClaw Gateway (port 18789)
      ├── NVIDIA NIM provider       ← 42 live models, single NVIDIA_API_KEY
      │     └── integrate.api.nvidia.com/v1 (timeout: 300s)
      ├── Telegram channel          ← @oc_lab329_bot
      │     ├── Native slash commands (/model, /new, /reset, /think …)
      │     ├── Agent chat (tool use, web search, file ops)
      │     └── Skills (/caveman, /caveman-compress …)
      └── Agent workspace (~/.openclaw/workspace/)
            ├── IDENTITY.md / SOUL.md / USER.md
            ├── Session memory (memory/)
            ├── Tool execution
            └── Subagent spawning (cavecrew)
```

One service. One API key. Everything through OpenClaw.

---

## Directory Structure

```text
openclaw-lab/
├── .devcontainer/
│   └── devcontainer.json          # Node 24, Docker-in-Docker
├── .github/
│   ├── workflows/                 # ci, secret-scan, codeql
│   ├── ISSUE_TEMPLATE/            # bug + feature templates
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── CODEOWNERS
│   └── dependabot.yml
├── core/                          # Shared library (NEW in 1.0)
│   ├── config.py                  #   env + ~/.openclaw/openclaw.json loader
│   ├── nim_client.py              #   single-call NIM wrapper
│   ├── ensemble.py                #   6-model fan-out + Kimi-K2.6 fusion
│   ├── auth.py                    #   Telegram user allowlist (fail-closed)
│   ├── logging.py                 #   JSONL audit log w/ redaction
│   └── cost.py                    #   token / USD accounting
├── agents/                        # Claude Code subagents
│   ├── cavecrew-builder.md
│   ├── cavecrew-investigator.md
│   └── cavecrew-reviewer.md
├── skills/
│   ├── caveman/                   # ~75% token reduction mode
│   ├── caveman-commit/            # Conventional Commits generator
│   ├── caveman-compress/          # Memory file compressor
│   ├── caveman-review/            # Code review comment style
│   ├── caveman-stats/             # Token usage stats
│   ├── cavecrew/                  # Subagent delegation guide
│   ├── common/tg.py               # Shared Telegram MarkdownV2 helpers
│   ├── job-search/                # BD CSE job scraper (ensemble)
│   ├── search/                    # Multi-backend web search (ensemble)
│   ├── research/                  # Deep-research briefing (ensemble) — NEW
│   └── review/                    # Ensemble code review — NEW
├── src/
│   ├── hooks/                     # Claude Code event hooks
│   ├── mcp-servers/caveman-shrink/ # MCP server: text compression
│   └── rules/                     # Session-start rule fragments
├── tests/
│   ├── conftest.py                # Shared fixtures, sys.path setup
│   └── unit/                      # 47 tests covering core/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DEPLOYMENT.md
│   ├── SKILLS.md
│   ├── CONTRIBUTING.md
│   └── CHANGELOG.md
├── data/                          # Persistent SQLite (gitignored content)
├── logs/                          # Audit + skill logs (gitignored content)
├── workspace/                     # Scratch dir (gitignored content)
├── .env.example                   # Documented env var template
├── .gitleaks.toml                 # Secret-scan rules
├── .claude/settings.json          # Team-shared Claude Code policy
├── pyproject.toml                 # Python deps, pytest, ruff, mypy
├── LICENSE                        # MIT
├── SECURITY.md
└── README.md
```

---

## Setup

### Step 1: Open in GitHub Codespaces

1. Click **Code** → **Codespaces** → **Create codespace on main**
2. Wait for VS Code to load

### Step 2: Rebuild Container (first time only)

`Ctrl+Shift+P` → **Codespaces: Rebuild Container**

Installs Node.js 24, Docker, and OpenClaw CLI automatically via `postCreateCommand`.

Verify:

```bash
openclaw --version
node -v
```

### Step 3: Add Codespaces Secret

Go to GitHub repo → **Settings** → **Secrets and variables** → **Codespaces**:

| Secret | Description |
|--------|-------------|
| `NVIDIA_API_KEY` | From [build.nvidia.com](https://build.nvidia.com) — free tier available |

After adding, rebuild container. Or set manually for the current session:

```bash
export NVIDIA_API_KEY="nvapi-..."
```

### Step 4: Initialize OpenClaw

```bash
openclaw onboard
```

Select **NVIDIA NIM** as provider, paste API key when prompted.

### Step 5: Start Gateway

```bash
openclaw gateway
```

Keep alive with tmux:

```bash
tmux new -s openclaw
openclaw gateway
# Ctrl+B, D  →  detach
# tmux attach -t openclaw  →  reattach
```

---

## OpenClaw Gateway

Persistent AI agent service on port `18789`.

### Configuration

Main config: `~/.openclaw/openclaw.json`

Key settings:

```json
{
  "agents": {
    "defaults": {
      "model": {
        "primary": "nvidia/nemotron-3-super-120b-a12b"
      },
      "models": {
        "nvidia/meta/llama-3.3-70b-instruct": {},
        "nvidia/openai/gpt-oss-120b": {}
      }
    }
  },
  "models": {
    "providers": {
      "nvidia": {
        "baseUrl": "https://integrate.api.nvidia.com/v1",
        "api": "openai-completions",
        "timeoutSeconds": 300
      }
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "botToken": "<your-bot-token>"
    }
  }
}
```

**Important config notes:**

- Model keys in `agents.defaults.models` must use format `{provider}/{model-id}` — e.g. `nvidia/meta/llama-3.1-70b-instruct`
- `timeoutSeconds` is provider-level only — applies to all models under that provider
- Per-model timeout is not configurable; set provider timeout high enough for slowest model

### Status and Logs

```bash
openclaw status                    # overall status
openclaw config validate           # validate config file
openclaw models list               # list configured models with auth status
openclaw models status             # active model, fallbacks, aliases
openclaw models fallbacks list     # fallback chain
```

### Diagnostics

```bash
openclaw doctor                    # diagnose and repair config issues
openclaw security audit            # audit security flags
```

---

## Telegram Usage

Bot: `@oc_lab329_bot`

### Native Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/model [id]` | Show or switch active model |
| `/models` | List all configured models |
| `/new` | Start a new session |
| `/reset` | Reset current session |
| `/stop` | Stop current run |
| `/compact` | Compress session context |
| `/think [level]` | Set reasoning level |
| `/fast` | Toggle fast mode |
| `/usage` | Show token usage summary |
| `/status` | Show current agent status |
| `/tasks` | List background tasks |
| `/steer` | Send guidance to active run |
| `/skill <name>` | Run a skill by name |

### Agent Chat

Send any message — OpenClaw responds with full tool access:

- File read/write/execute
- Bash execution
- Web search and fetch
- Session memory (persists across restarts)
- Subagent spawning

### Groups

In groups, bot requires a mention:

```text
@oc_lab329_bot what does this function do?
```

---

## Model Switching

Switch model in Telegram:

```text
/model nvidia/meta/llama-3.3-70b-instruct
```

Switch by alias:

```text
/model NVIDIA
```

List configured models:

```text
/models
```

Change default in `~/.openclaw/openclaw.json`:

```json
"model": {
  "primary": "nvidia/openai/gpt-oss-120b"
}
```

### Fallback Chain

If primary model fails, openclaw tries fallbacks in order:

1. `nvidia/meta/llama-3.3-70b-instruct`
2. `nvidia/openai/gpt-oss-120b`
3. `nvidia/meta/llama-4-maverick-17b-128e-instruct`
4. `nvidia/mistralai/mistral-small-4-119b-2603`

Manage fallbacks:

```bash
openclaw models fallbacks list
openclaw models fallbacks add nvidia/meta/llama-3.1-70b-instruct
openclaw models fallbacks remove nvidia/meta/llama-3.1-70b-instruct
```

---

## Available Models

42 verified-live models as of 2026-05-22. All via single `NVIDIA_API_KEY`.

### Recommended

| Model | Use case | Speed |
|-------|----------|-------|
| `nvidia/nemotron-3-super-120b-a12b` | Default — best quality ⭐ | ~1.4s |
| `nvidia/meta/llama-4-maverick-17b-128e-instruct` | Fast + capable, 1M ctx | ~0.2s |
| `nvidia/openai/gpt-oss-120b` | Large, reliable | ~0.2s |
| `nvidia/openai/gpt-oss-20b` | Coding | ~0.3s |
| `nvidia/meta/llama-3.3-70b-instruct` | Strong general | ~3.6s |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | Reasoning | ~0.2s |
| `nvidia/meta/llama-3.2-11b-vision-instruct` | Vision | ~0.2s |
| `nvidia/moonshotai/kimi-k2.6` | Long context (256k) | ~3.4s |
| `nvidia/qwen/qwen3.5-122b-a10b` | Large multilingual | ~0.7s |
| `nvidia/meta/llama-3.2-1b-instruct` | Fastest/cheapest | ~0.2s |

### Full List

<details>
<summary>All 42 models</summary>

| Model | Context |
|-------|---------|
| `nvidia/abacusai/dracarys-llama-3.1-70b-instruct` | 125k |
| `nvidia/bytedance/seed-oss-36b-instruct` | 125k |
| `nvidia/deepseek-ai/deepseek-v4-flash` | 64k (slow ~67s cold start) |
| `nvidia/google/gemma-2-2b-it` | 125k |
| `nvidia/google/gemma-3n-e2b-it` | 125k |
| `nvidia/google/gemma-3n-e4b-it` | 125k |
| `nvidia/ising-calibration-1-35b-a3b` | 195k |
| `nvidia/llama-3.1-nemotron-nano-8b-v1` | 195k |
| `nvidia/llama-3.1-nemotron-nano-vl-8b-v1` | 195k |
| `nvidia/llama-3.3-nemotron-super-49b-v1` | 195k |
| `nvidia/llama-3.3-nemotron-super-49b-v1.5` | 195k |
| `nvidia/meta/llama-3.1-70b-instruct` | 128k |
| `nvidia/meta/llama-3.1-8b-instruct` | 128k |
| `nvidia/meta/llama-3.2-11b-vision-instruct` | 128k |
| `nvidia/meta/llama-3.2-1b-instruct` | 128k |
| `nvidia/meta/llama-3.2-3b-instruct` | 128k |
| `nvidia/meta/llama-3.2-90b-vision-instruct` | 128k |
| `nvidia/meta/llama-3.3-70b-instruct` | 128k |
| `nvidia/meta/llama-4-maverick-17b-128e-instruct` | 1024k |
| `nvidia/microsoft/phi-4-mini-instruct` | 128k (slow ~141s cold start) |
| `nvidia/microsoft/phi-4-multimodal-instruct` | 128k |
| `nvidia/minimaxai/minimax-m2.7` | 192k (slow ~74s cold start) |
| `nvidia/mistralai/ministral-14b-instruct-2512` | 128k |
| `nvidia/mistralai/mistral-medium-3.5-128b` | 128k |
| `nvidia/mistralai/mistral-small-4-119b-2603` | 128k |
| `nvidia/mistralai/mixtral-8x7b-instruct-v0.1` | 125k |
| `nvidia/moonshotai/kimi-k2.6` | 256k |
| `nvidia/nemotron-3-nano-30b-a3b` | 195k |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | 195k |
| `nvidia/nemotron-3-super-120b-a12b` | 195k |
| `nvidia/nemotron-mini-4b-instruct` | 195k |
| `nvidia/nemotron-nano-12b-v2-vl` | 195k |
| `nvidia/nvidia-nemotron-nano-9b-v2` | 195k |
| `nvidia/openai/gpt-oss-120b` | 125k |
| `nvidia/openai/gpt-oss-20b` | 125k |
| `nvidia/qwen/qwen3-next-80b-a3b-instruct` | 128k |
| `nvidia/qwen/qwen3.5-122b-a10b` | 128k |
| `nvidia/qwen/qwen3.5-397b-a17b` | 128k |
| `nvidia/sarvamai/sarvam-m` | 125k |
| `nvidia/stepfun-ai/step-3.5-flash` | 125k |
| `nvidia/stockmark/stockmark-2-100b-instruct` | 125k |
| `nvidia/upstage/solar-10.7b-instruct` | 125k |

</details>

### Known Status

| Model | Status |
|-------|--------|
| `z-ai/glm-5.1` | In catalog, not in menu — streaming endpoint broken (sync-only) |
| `deepseek-ai/deepseek-v4-pro` | Removed — unresponsive on NVIDIA infrastructure |
| `google/gemma-4-31b-it` | Removed — unresponsive |
| `qwen/qwen3-coder-480b-a35b-instruct` | Removed — unresponsive |
| `mistralai/mistral-large-3-675b-instruct-2512` | Removed — unresponsive |

35 additional models were removed after returning HTTP 404 (decommissioned by NVIDIA).

---

## Skills

Quick map of every skill is in [docs/SKILLS.md](docs/SKILLS.md). All
ensemble-backed skills (`job-search`, `search`, `research`, `review`) share
the same six-model roster via `core.ensemble`.

Invoke via `/skill <name>` in Telegram, or `/<name>` if registered as a slash command.

### `/research` (new in 1.0)

Long-form research briefing. Gathers 20-30 sources from DDG web, DDG news,
Stack Overflow, GitHub, and Semantic Scholar (intent-driven), then fans
out to the 6-model ensemble and fuses with Kimi-K2.6 at temperature=0.
Output: summary, key findings, conflicting claims, best sources, follow-up
queries, limitations.

```bash
python skills/research/research.py "what's the state of speculative decoding in late 2025"
python skills/research/research.py "X vs Y" --academic
python skills/research/research.py "..." --json
```

Full docs: [`skills/research/SKILL.md`](skills/research/SKILL.md)

### `/review` (new in 1.0)

Ensemble code review for the current diff, a branch, a file, or a GitHub PR.
Returns `path:line: <emoji> <severity>: <problem>. fix: <suggestion>.` Sorted
by severity (bug → risk → nit → question), then confidence, then file:line.

```bash
python skills/review/review.py             # diff vs HEAD
python skills/review/review.py main        # diff vs main branch
python skills/review/review.py src/auth.py # whole-file review
python skills/review/review.py --pr        # current branch's PR
```

Full docs: [`skills/review/SKILL.md`](skills/review/SKILL.md)


### `/job-search`

Searches 22 BD tech company career pages and 3 job platforms concurrently. Filters results
using a 6-model NVIDIA NIM parallel ensemble fused by Kimi-K2.6. Deduplicates via SQLite.

| Trigger | Description |
|---------|-------------|
| `/job_search` | Full search — all 22 companies + job boards (~4 min) |
| `/job_search_tier1` | Tier 1 companies only, faster (~60-90s) |
| `/job_search_fresh` | Clear seen-jobs cache + full search |

**Ensemble:** Kimi-K2.6 (1T) · Qwen3.5-397B · Nemotron-120B · Nemotron-49B · Llama-4 · Mistral-119B — all parallel.
**Fusion:** Kimi-K2.6 at `temperature=0` (deterministic). Pure Python `local_fusion()` fallback if API fails.
**Schedule:** Daily at 09:00 Asia/Dhaka via APScheduler.

```text
/skill job-search
/skill job-search tier1
/skill job-search fresh
```

Full documentation: [`skills/job-search/README.md`](skills/job-search/README.md)

---

### `/caveman`

~75% token reduction mode. Full technical accuracy preserved.

| Level | Description |
|-------|-------------|
| `lite` | No filler, articles kept, professional |
| `full` | Drop articles, fragments OK — **default** |
| `ultra` | Max compression, arrows for causality (X→Y) |
| `wenyan-full` | Classical Chinese, 80-90% reduction |

```text
/caveman lite
/caveman ultra
stop caveman
```

### `/caveman-commit`

Conventional Commits message generator.

Format: `<type>(<scope>): <imperative summary>`

Types: `feat` `fix` `refactor` `perf` `docs` `test` `chore` `build` `ci` `style` `revert`

Rules:

- Subject ≤50 chars, imperative mood ("add" not "added")
- Body only when why isn't obvious from the diff
- No AI attribution

### `/caveman-compress <filepath>`

Compresses `.md`/`.txt` memory files to caveman format — reduces input tokens ~75%.

- Backs up original as `<filename>.original.md`
- Preserves code blocks, URLs, paths, commands exactly
- Validates output, retries up to 2 times on failure
- Uses `CAVEMAN_MODEL` env var to select compression model

```text
/caveman-compress ~/.claude/projects/myproject/memory/feedback.md
```

### `/caveman-review`

Code review comments. Findings only, no praise.

Format: `path:line: <emoji> <severity>: <problem>. <fix>.`

| Emoji | Severity |
|-------|----------|
| 🔴 | bug — broken behavior, crash, data loss |
| 🟡 | risk — edge case, race condition, missing guard |
| 🔵 | nit — style, naming (only if thorough review requested) |
| ❓ | question — need author intent before judging |

### `/caveman-stats`

Real token usage and estimated savings for current session. Reads session log directly — no estimation.

### `/cavecrew`

Decision guide for delegating to compressed subagents. Reduces main context growth ~60% per delegation.

---

## Agents

Three cavecrew subagents emit caveman-compressed output, keeping injected tool results small.

### `cavecrew-investigator`

**Model:** Claude Haiku | **Read-only**

Locates code. Returns `path:line — symbol — note` table. Never edits, never suggests fixes.

```text
Defs:
- src/auth.ts:42 — `validateToken` — expiry check
Refs:
- src/middleware.ts:18,33
2 defs, 2 refs.
```

Use for: "where is X defined", "what calls Y", "find all uses of Z"

### `cavecrew-builder`

**Scope:** 1-2 files max

Surgical edits only. Reads before editing. Returns diff receipt. Refuses 3+ file scope.

```text
src/auth.ts:42-42 — fix token expiry off-by-one.
verified: re-read OK
```

Use for: bounded edits where the file and change are already known.

### `cavecrew-reviewer`

**Model:** Claude Haiku | **Read-only**

Reviews diffs or files. Findings only, no praise.

```text
src/auth.ts:42: 🔴 bug: token expiry uses < not <=. Change to <=.
totals: 1🔴
```

Use for: "review this PR", "audit this file for bugs"

### Delegation Pattern

```text
1. cavecrew-investigator → locate files/symbols
2. cavecrew-builder      → targeted edit (1-2 files max)
3. cavecrew-reviewer     → verify the diff
```

---

## Claude Code Integration

### Hooks (`src/hooks/`)

| Hook | Trigger | Effect |
|------|---------|--------|
| `caveman-activate.js` | Session start | Activates caveman mode |
| `caveman-config.js` | Config read/write | Manages caveman level flag |
| `caveman-mode-tracker.js` | Each prompt | Tracks level, handles `/caveman-stats` |
| `caveman-stats.js` | `/caveman-stats` | Reads session log, computes savings |
| `caveman-statusline.sh` | Statusline render | Shows caveman level in terminal |

### MCP Server (`src/mcp-servers/caveman-shrink/`)

Exposes `compress_text` tool — strips filler, preserves code/URLs/structure via NVIDIA NIM.

```bash
cd src/mcp-servers/caveman-shrink && node index.js
```

### Rules (`src/rules/`)

Markdown files injected into Claude Code system context on session start:

- `caveman-activate.md` — global caveman mode bootstrap
- `caveman-openclaw-bootstrap.md` — OpenClaw-specific context and rules

---

## Environment Variables

The canonical list lives in [`.env.example`](.env.example). Hot vars:

| Variable                | Required | Description                                                         |
|-------------------------|----------|---------------------------------------------------------------------|
| `NVIDIA_API_KEY`        | yes      | NVIDIA NIM API key. Shared by all 42 models.                         |
| `TELEGRAM_BOT_TOKEN`    | when bot is exposed | Bot token from @BotFather.                              |
| `TELEGRAM_CHAT_ID`      | when bot is exposed | Numeric id the bot sends to.                           |
| `ALLOWED_TG_USER_IDS`   | **yes when bot is exposed** | Comma-separated allowlist. Empty = bot rejects everyone (fail-closed). |
| `CAVEMAN_MODEL`         | no       | Override model for `/caveman-compress`.                              |
| `CAVEMAN_DEFAULT_MODE`  | no       | `off | lite | full | ultra | wenyan-*`. Default: `full`.            |
| `OPENCLAW_AUDIT_LOG`    | no       | Override audit log path. Default: `<repo>/logs/audit.jsonl`.         |

Set as Codespaces secrets (never commit to repo) or via a local `.env`:

```bash
cp .env.example .env  # then edit and `source .env`
```

## Security

OpenClaw Lab runs an LLM with shell access on the operator's machine and
optionally exposes a Telegram entry point. Treat it as security-critical.

- **Fail-closed Telegram allowlist** (`core.auth`). Empty allowlist rejects every user.
- **`gitleaks` CI on every push + weekly cron** — see `.gitleaks.toml`.
- **CodeQL** static analysis for Python + JavaScript.
- **Claude Code policy** in `.claude/settings.json` with explicit `deny` rules for
  `rm -rf /*`, `git push --force`, secret-printing patterns, and reading
  `~/.openclaw/agents/main/agent/auth-profiles.json`.
- **Audit log** at `logs/audit.jsonl` (JSONL, append-only) with key-name redaction.
- **`.env.example`** documents every variable; nothing else is read from disk.

Threat model and reporting: [SECURITY.md](SECURITY.md).

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                                          # 47 unit tests
ruff check core tests skills/review skills/research
gitleaks detect --config .gitleaks.toml --redact -v
```

CI runs the same three commands on every push. See
[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for code style, test layout,
and PR rules.

---

## Troubleshooting

### Gateway not starting

```bash
openclaw doctor           # auto-diagnose and repair
openclaw config validate  # check for config errors
openclaw status           # check if already running
```

### `No API key found for provider "nvidia"`

```bash
export NVIDIA_API_KEY="nvapi-..."
openclaw gateway
```

Or add as Codespaces secret and rebuild container.

### Config validation errors

```bash
openclaw config validate
openclaw doctor --fix
```

Common causes:

- Unknown fields in model entries (e.g. `requestTimeoutMs` is not valid at model level — use `models.providers.nvidia.timeoutSeconds` instead)
- Model keys in `agents.defaults.models` missing `nvidia/` provider prefix

### Model switching fails — "No API key for provider google/openai/meta"

Model keys must use `{provider}/{model-id}` format. The provider is always `nvidia`, not the model's org:

```json
// Wrong
"google/gemma-2-2b-it": {}

// Correct
"nvidia/google/gemma-2-2b-it": {}
```

### Model timeout errors

Some models have slow cold starts (up to 141s). Ensure provider timeout is set high enough:

```json
"models": {
  "providers": {
    "nvidia": {
      "timeoutSeconds": 300
    }
  }
}
```

Models with known slow cold starts: `deepseek-v4-flash` (~67s), `minimax-m2.7` (~74s), `phi-4-mini` (~141s).

### Telegram bot not responding

```bash
openclaw status                    # check gateway and channels
```

Verify bot token in `~/.openclaw/openclaw.json` → `channels.telegram.botToken`.

### Too many commands in Telegram "/" menu

Previous gateway runs may have registered stale commands. Clear and restart:

```bash
curl -s "https://api.telegram.org/bot<TOKEN>/setMyCommands" \
  -d '{"commands":[]}'
openclaw gateway
```

### Session context too large

```text
/compact
```

Or start fresh:

```text
/new
```

### Check model health

Live API test against all configured models:

```bash
python3 << 'EOF'
import json, urllib.request, urllib.error, time, concurrent.futures

with open('/home/codespace/.openclaw/agents/main/agent/auth-profiles.json') as f:
    key = json.load(f)['profiles']['nvidia:default']['key']

with open('/home/codespace/.openclaw/openclaw.json') as f:
    data = json.load(f)
models = [m['id'] for m in data['models']['providers']['nvidia']['models']]

def test(mid):
    payload = json.dumps({"model": mid, "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 5, "stream": True}).encode()
    req = urllib.request.Request('https://integrate.api.nvidia.com/v1/chat/completions',
        data=payload, headers={'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json', 'Accept': 'text/event-stream'})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=35) as r:
            r.read(50)
            return mid, f"✓ {time.time()-start:.1f}s"
    except urllib.error.HTTPError as e:
        return mid, f"✗ HTTP{e.code}"
    except Exception as e:
        return mid, f"✗ {type(e).__name__}"

with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
    for mid, result in ex.map(lambda m: test(m), models):
        print(f"{result:20} {mid}")
EOF
```
