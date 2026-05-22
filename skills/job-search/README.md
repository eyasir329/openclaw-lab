# job-search Skill

Scrapes 22 BD tech company career pages and 3 job platforms concurrently. Scores results
using a 6-model NVIDIA NIM parallel ensemble fused by Kimi-K2.6. Deduplicates via SQLite.
Delivers formatted job cards to Telegram via `@oc_lab329_bot`.

---

## Table of Contents

- [Architecture](#architecture)
- [Pipeline](#pipeline)
- [Files](#files)
- [Configuration](#configuration)
- [Usage](#usage)
- [Scheduler](#scheduler)
- [Model Ensemble](#model-ensemble)
- [Scrapers](#scrapers)
- [Database Schema](#database-schema)
- [Message Format](#message-format)
- [Error Handling](#error-handling)
- [Troubleshooting](#troubleshooting)

---

## Architecture

```text
/skill job-search  (Telegram trigger)
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  run_job_search()                                       │
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │  SCRAPERS (all concurrent via asyncio.gather)    │  │
│  │                                                  │  │
│  │  Tier 1 (10 companies)   ← career pages         │  │
│  │  Tier 2 (12 companies)   ← career pages         │  │
│  │  BDJobs (10 keywords)    ← IT/Telecom category  │  │
│  │  BDTechJobs              ← all tech listings    │  │
│  │  LinkedIn (6 searches)   ← last 7 days, BD      │  │
│  └──────────────────────────────────────────────────┘  │
│                   │                                     │
│                   ▼                                     │
│         SQLite deduplication                            │
│         (seen_jobs table — SHA-256 hash)                │
│                   │                                     │
│                   ▼                                     │
│  ┌──────────────────────────────────────────────────┐  │
│  │  6-MODEL PARALLEL ENSEMBLE (asyncio.gather)      │  │
│  │                                                  │  │
│  │  [S] kimi-k2.6          weight 2.0  timeout 180s│  │
│  │  [S] qwen3.5-397b       weight 1.8  timeout 150s│  │
│  │  [A] nemotron-super-120b weight 1.5  timeout 120s│  │
│  │  [A] nemotron-super-49b  weight 1.4  timeout 90s │  │
│  │  [B] llama4-maverick     weight 1.0  timeout 30s │  │
│  │  [B] mistral-small-119b  weight 1.0  timeout 60s │  │
│  └──────────────────────────────────────────────────┘  │
│                   │                                     │
│                   ▼                                     │
│  ┌──────────────────────────────────────────────────┐  │
│  │  KIMI-K2.6 FUSION  (temperature=0, deterministic)│  │
│  │  Weighted consensus + veto + dedup               │  │
│  │  Fallback: local_fusion() — pure Python          │  │
│  └──────────────────────────────────────────────────┘  │
│                   │                                     │
│                   ▼                                     │
│         Persist to SQLite + log search                  │
│                   │                                     │
│                   ▼                                     │
│      Telegram: formatted job cards                      │
└─────────────────────────────────────────────────────────┘
```

---

## Pipeline

Full wall-clock timeline (all 6 scorers run in parallel):

```text
t = 0s    Scrapers start (all concurrent)
t = ~15s  Scrapers complete
          SQLite dedup → new_jobs identified
          6-model ensemble starts (all simultaneous)

t = ~30s  llama4-maverick returns   (~0.2s inference, 30s timeout)
t = ~60s  mistral-small-119b returns
t = ~90s  nemotron-super-49b returns
t = ~120s nemotron-super-120b returns
t = ~150s qwen3.5-397b returns
t = ~180s kimi-k2.6 scorer returns
           → Kimi-K2.6 fusion starts

t = ~240s Kimi-K2.6 fusion returns
           → Telegram message sent

Total: ~4 minutes (full run) / ~60-90s (tier1 only)
```

Batching: jobs are processed in batches of 20 through the ensemble (with 2s pause between
batches) to stay within NIM context limits and avoid rate-limiting.

---

## Files

```text
skills/job-search/
├── SKILL.md          OpenClaw skill definition — trigger, args, schedule
├── README.md         This file
├── job_search.py     Full executor (~1200 lines)
└── requirements.txt  pip dependencies

data/
└── job_search.db     SQLite database (created on first run)
```

---

## Configuration

All secrets come from `~/.openclaw/openclaw.json` and environment variables. Nothing is
hardcoded in `job_search.py`.

### Telegram token and chat ID

Loaded from `~/.openclaw/openclaw.json`:

```json
{
  "channels": {
    "telegram": {
      "botToken": "...",
      "chatId": "..."          // optional — inferred from ownerAllowFrom if absent
    }
  },
  "commands": {
    "ownerAllowFrom": ["telegram:1536307563"]   // chat ID inferred from here if chatId missing
  }
}
```

Resolution order for chat ID:
1. `channels.telegram.chatId`
2. `TELEGRAM_CHAT_ID` environment variable
3. First `telegram:*` entry in `commands.ownerAllowFrom`

### NVIDIA NIM key

```bash
export NVIDIA_API_KEY="nvapi-..."
```

Never read from config file — environment variable only.

### Skill registration in openclaw.json

```json
{
  "skills": {
    "job-search": {
      "description": "Search CSE/SWE/AI-ML jobs in Bangladesh — 22 companies + job boards, 6-model NIM ensemble",
      "executor": "python3",
      "script": "/workspaces/openclaw-lab/skills/job-search/job_search.py",
      "schedule": "0 9 * * *",
      "timezone": "Asia/Dhaka"
    }
  }
}
```

### Companies

Edit `TIER1` and `TIER2` lists in `job_search.py` to add/remove companies:

```python
TIER1 = [
    {"name": "Brain Station 23", "url": "https://brainstation-23.com/career/"},
    {"name": "Enosis Solutions",  "url": "https://www.enosisbd.com/career", "remote": True},
    # ...
]
```

Set `"remote": True` on a company dict to tag all its jobs as remote-friendly.

### User profile

Edit the `USER` dict at the top of `job_search.py`:

```python
USER = {
    "name":    "Eyasir",
    "roles":   ["Software Engineer", "AI/ML Engineer", ...],
    "exclude": ["HR", "Finance", "Sales", ...],
    "location": "Bangladesh",
    "accept_remote": True,
}
```

The `roles` and `exclude` lists are injected verbatim into the scorer and fusion system
prompts — all 6 models see them.

---

## Usage

### Telegram

```text
/job_search              full run — all 22 companies + job boards (~4 min)
/job_search_tier1        Tier 1 only — 10 companies (~60-90s)
/job_search_fresh        clear cache + full search
```

Or via the OpenClaw skill system:

```text
/skill job-search
/skill job-search tier1
/skill job-search fresh
```

### CLI

```bash
# On-demand full search
python3 skills/job-search/job_search.py

# Tier 1 companies only (faster)
python3 skills/job-search/job_search.py tier1

# Clear seen-jobs cache, then search
python3 skills/job-search/job_search.py fresh

# Start the daily scheduler (blocking)
python3 skills/job-search/job_search.py --schedule

# Scraper smoke test — no AI calls, no Telegram
python3 skills/job-search/job_search.py --test
```

### Flags

| Flag | Effect |
|------|--------|
| `tier1` | Search only Tier 1 companies (10 companies, no job boards) |
| `fresh` | Delete all rows from `seen_jobs` before searching — shows all current openings |
| `silent` | Skip all Telegram output (used by the scheduler internally) |
| `--schedule` | Start APScheduler (blocking loop, run in tmux) |
| `--test` | Smoke-test 3 scrapers + BDJobs + BDTechJobs; no AI, no Telegram |

---

## Scheduler

The scheduler uses APScheduler inside the asyncio event loop. Run it in a dedicated
tmux window alongside the OpenClaw gateway.

```bash
# Create new tmux window
tmux new-window -n job-search

# Start scheduler
cd /workspaces/openclaw-lab
python3 skills/job-search/job_search.py --schedule
```

Schedule:

| Job | Time | Description |
|-----|------|-------------|
| `daily_digest` | 09:00 Asia/Dhaka | Full job search, results sent to Telegram |
| `weekly_summary` | Sunday 09:05 Asia/Dhaka | Count of jobs found in past 7 days |

The scheduler prints the next run time on startup:

```text
[scheduler] Daily digest: 09:00 Asia/Dhaka (next: 2026-05-23 09:00:00+06:00)
[scheduler] Weekly summary: Sunday 09:05 Asia/Dhaka
[scheduler] Running. Ctrl+C to stop.
```

---

## Model Ensemble

### Roster

| Tier | Model ID | Label | Weight | Timeout | Role |
|------|----------|-------|--------|---------|------|
| S | `moonshotai/kimi-k2.6` | kimi-k2.6 | 2.0 | 180s | 1T total / 32B active, #1 open-weights, 256k ctx, fusion model |
| S | `qwen/qwen3.5-397b-a17b` | qwen3.5-397b | 1.8 | 150s | 397B total / 17B active, SOTA reasoning + Bengali |
| A | `nvidia/nemotron-3-super-120b-a12b` | nemotron-super-120b | 1.5 | 120s | Best structured JSON + agentic on NIM |
| A | `nvidia/llama-3.3-nemotron-super-49b-v1.5` | nemotron-super-49b | 1.4 | 90s | Reasoning specialist, RAG + tool-calling |
| B | `meta/llama-4-maverick-17b-128e-instruct` | llama4-maverick | 1.0 | 30s | ~0.2s latency, 1M context, never a bottleneck |
| B | `mistralai/mistral-small-4-119b-2603` | mistral-small-119b | 1.0 | 60s | Different architecture = genuine signal diversity |

All use `https://integrate.api.nvidia.com/v1/chat/completions` with `NVIDIA_API_KEY`.

### Scoring

Each scorer receives the full job batch as JSON. System prompt instructs it to:
- Return only jobs with `relevance_score >= 5`
- Exclude non-tech roles (HR, Finance, Sales, etc.)
- Score against target roles list
- Return raw JSON array — no markdown, no explanation

Scorer settings: `temperature: 0.1`, `max_tokens: 4000`

### Fusion rules (Kimi-K2.6 at temperature=0)

1. `final_score` = weighted average across all models that included the job
2. Boost ×1.15 — job in 5-6 models (very high consensus)
3. Boost ×1.05 — job in 3-4 models
4. Drop — job in only 1 model AND score < 7 (noise)
5. Veto — if `kimi-k2.6` OR `qwen3.5-397b` scored job below 5, drop it regardless
6. Sort: `model_agreement DESC`, then `final_score DESC`
7. Deduplicate by URL — keep highest-scored entry
8. `why_relevant`: pick sharpest explanation across all models

### Confidence assignment

| `model_agreement` | `confidence` |
|-------------------|--------------|
| 5-6 models | `high` 🟢 |
| 3-4 models | `medium` 🟡 |
| 1-2 models | `low` 🟠 |
| 0 (ensemble failed) | `none` ⚪ |

### Local fusion fallback

If the Kimi-K2.6 fusion API call fails for any reason, `local_fusion()` runs instead.
It is pure Python — zero API dependency — and implements the same weighted-average logic,
consensus boosts, Tier S veto, and sort order as the FUSION_SYSTEM_PROMPT. The system
never crashes due to model unavailability.

---

## Scrapers

### Career page scraper

- Fetches company URL
- Parses `<a href>` tags whose text contains job keywords: `engineer`, `developer`,
  `intern`, `trainee`, `analyst`, `scientist`, `devops`, `architect`, `lead`,
  `researcher`, `qa`, `tester`, `programmer`
- Resolves relative URLs to absolute via `urllib.parse.urljoin`
- Caps at 15 jobs per company; deduplicates by URL within company
- On any failure: logs warning, returns `[]` — does not block other scrapers

### BDJobs scraper

- URL: `https://jobs.bdjobs.com/jobsearch.asp?txtsearch={keyword}&fcat=14`
- Category 14 = IT/Telecom
- Parses `.job-list-single`, `.norm-jobs`, `.InnJobListCom` rows
- Adds 0.5s sleep after each keyword to stay polite
- Caps at 20 results per keyword

### BDTechJobs scraper

- URL: `https://www.bdtechjobs.com/jobs`
- Parses `a[href*='/job']` and `a[href*='/jobs/']` links
- Best-effort company extraction from nearest container element
- Caps at 30 results

### LinkedIn scraper

- Randomized pre-request sleep: 2-4s (reduces 429 probability)
- Parses `.base-card` and `.job-search-card` selectors
- Strips tracking params from URLs: `href.split("?")[0]`
- If no cards found (rate-limited or CAPTCHA): logs warning, returns `[]` gracefully
- Caps at 20 results per search URL

LinkedIn returns [] frequently in cloud environments due to IP reputation. This is expected
and does not affect the rest of the pipeline.

---

## Database Schema

SQLite database at `data/job_search.db`.

### `seen_jobs`

Deduplication table. A job's ID is a 16-char SHA-256 hash of `title + company + url`
(all lowercased and stripped).

```sql
CREATE TABLE seen_jobs (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    company         TEXT NOT NULL,
    url             TEXT NOT NULL,
    platform        TEXT,
    tier            INTEGER DEFAULT 2,
    relevance_score REAL    DEFAULT 5.0,
    found_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### `search_log`

Audit trail of every run.

```sql
CREATE TABLE search_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    searched_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    trigger         TEXT,            -- "command" | "scheduler"
    total_scraped   INTEGER,         -- raw jobs before dedup
    new_jobs        INTEGER,         -- jobs that passed dedup
    ensemble_models INTEGER,         -- models that succeeded (0-6)
    duration_secs   REAL             -- wall-clock time for full run
);
```

### Useful queries

```bash
# Jobs found in the last 24 hours
sqlite3 data/job_search.db \
  "SELECT company, title, platform FROM seen_jobs WHERE found_at >= datetime('now','-1 day') ORDER BY found_at DESC;"

# Search history
sqlite3 data/job_search.db \
  "SELECT searched_at, trigger, total_scraped, new_jobs, ensemble_models, duration_secs FROM search_log ORDER BY id DESC LIMIT 10;"

# Jobs per company
sqlite3 data/job_search.db \
  "SELECT company, COUNT(*) as n FROM seen_jobs GROUP BY company ORDER BY n DESC;"

# Clear cache (same as running with 'fresh' flag)
sqlite3 data/job_search.db "DELETE FROM seen_jobs;"
```

---

## Message Format

Telegram MarkdownV2. All dynamic text is escaped through `tg_escape()` before insertion.

### Header

```
🔍 CSE Job Search — Bangladesh            ← on-demand trigger
— OR —
🌅 Good morning Eyasir! Your daily job digest:   ← scheduler trigger

📅 Thu, 22 May 2026  09:00 AM
🆕 12 new relevant jobs found
🤖 6-model ensemble  |  🔀 Kimi-K2.6 fusion
🟢 7 high  🟡 4 medium  🟠 1 low
```

### Job card

```
🏆 Tier 1 — Top BD Tech

━━━━━━━━━━━━━━
🏢 Brain Station 23
💼 Junior Software Engineer
⭐ 9.2/10  🟢 high  [●●●●●○] 5/6
📍 Bangladesh  |  Career Page
💡 Matches full-stack + active BD company
🔗 Apply Here
```

Agreement bar: `●` × agreement + `○` × (6 - agreement). Remote jobs show `🌐 Remote`
instead of `📍 Bangladesh`.

### Footer

```
Powered by: Kimi-K2.6 (1T) + Qwen3.5-397B + Nemotron-120B + Nemotron-49B + Llama-4 + Mistral-119B
```

Messages are split at 4000 chars for Telegram's 4096-char limit.

---

## Error Handling

Every failure is isolated — one component failing never stops others.

| Component | Failure | Response |
|-----------|---------|----------|
| Career page | HTTP error / timeout / parse error | Log warning, return `[]` |
| LinkedIn | 429 / no cards found | Log `⚠️ LinkedIn rate-limited`, return `[]` |
| BDJobs | Any error | Log error, return `[]` |
| NIM model | HTTP error / timeout / bad JSON | Log with model label + tier, return `None` |
| All 6 models fail | — | Return unscored jobs with `⚠️ Ensemble unavailable` flag |
| 1 model succeeds | — | Return that model's output directly, skip fusion |
| Kimi fusion fails | API error / timeout / bad JSON | Fall back to `local_fusion()` |
| Telegram send | HTTP error | Retry 3× at 2s / 4s / 8s exponential backoff |

---

## Troubleshooting

### `NVIDIA_API_KEY is not set`

```bash
export NVIDIA_API_KEY="nvapi-..."
python3 skills/job-search/job_search.py
```

### All 6 models return `None`

Check API key is valid and has quota:

```bash
curl -s https://integrate.api.nvidia.com/v1/models \
  -H "Authorization: Bearer $NVIDIA_API_KEY" | python3 -m json.tool | head -20
```

### Zero jobs scraped

Career pages may block Codespaces IPs. Run `--test` to see which scrapers succeed:

```bash
python3 skills/job-search/job_search.py --test
```

BDJobs and LinkedIn are most likely to block cloud IPs. The career page scrapers are
less likely to block since they receive normal GET requests with rotating User-Agents.

### Telegram message not received

Verify the chat ID is resolved correctly:

```python
python3 -c "
import json, os
from pathlib import Path
cfg = json.load(open(Path.home() / '.openclaw/openclaw.json'))
print('token prefix:', cfg['channels']['telegram']['botToken'][:20])
owner = cfg.get('commands', {}).get('ownerAllowFrom', [])
print('ownerAllowFrom:', owner)
"
```

### MarkdownV2 parse error in Telegram

Job titles or company names containing special characters can cause parse errors.
The `tg_escape()` function should handle all cases, but if a message fails, check
the Telegram API response logged as `[telegram] HTTP 400`.

To debug, temporarily switch `parse_mode` to `"HTML"` in `send_telegram()` — then
revert once the offending character is identified.

### Reset seen-jobs cache

```bash
# Via flag
python3 skills/job-search/job_search.py fresh

# Via SQLite directly
sqlite3 data/job_search.db "DELETE FROM seen_jobs;"

# Via Telegram
/job_search_fresh
```

### Scheduler fires but sends no Telegram message

Check if the `silent` flag is set. The scheduler calls `run_job_search(trigger="scheduler")`
without any args — `silent` should be `False`. If no jobs are found (all seen), the
message "No new jobs since last check" is sent instead.

---

## Company Reference

### Tier 1 — Top BD Tech (10 companies)

| Company | Career URL |
|---------|-----------|
| Brain Station 23 | brainstation-23.com/career |
| Enosis Solutions | enosisbd.com/career *(remote-friendly)* |
| Samsung R&D Bangladesh | research.samsung.com/srbd |
| Viva Soft | vivasoft.com.bd/career |
| Cefalo Bangladesh | cefalo.com/en/jobs |
| Therap BD | therapbd.com/career |
| BJIT Group | bjitgroup.com/career |
| Pathao | careers.pathao.com/jobs |
| Optimizely | careers.optimizely.com/viewalljobs |
| bKash | bkash.com/bn/careers |

### Tier 2 — BD Tech (12 companies)

| Company | Career URL |
|---------|-----------|
| Augmedix Bangladesh | augmedix.com/careers |
| TigerIT Bangladesh | tigerit.com/career |
| SELISE Digital | selise.ch/careers |
| DataSoft Systems | datasoft-bd.com/career |
| ReliSource Technologies | relisource.com/careers |
| Shohoz | shohoz.com/career |
| Grameenphone | grameenphone.com/about/career |
| Robi Axiata | robi.com.bd/en/corporate/career |
| Kaz Software | kazsoftware.com/career |
| Shajgoj | shajgoj.com/careers |
| Field Nation | careers.fieldnation.com |
| Impulse BD | impulsebdltd.com/career |

### Job Boards (Tier 3)

| Platform | Coverage |
|----------|----------|
| BDJobs | 10 keyword searches in IT/Telecom category |
| BDTechJobs | All current tech listings |
| LinkedIn | 6 keyword searches — last 7 days, Bangladesh |
