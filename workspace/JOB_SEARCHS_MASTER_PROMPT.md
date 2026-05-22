# MASTER PROMPT — OpenClaw `job-searchs` Skill
## Paste this entire file directly into Claude Code inside `openclaw-lab/`

---

## MISSION

Build a production-ready `job-searchs` OpenClaw skill for Eyasir
(CSE graduate, Bangladesh — Software Engineering / AI-ML / Intern / Trainee focus).

The skill:
1. Registers as `/job-searchs` Telegram slash command in the existing OpenClaw system
2. Scrapes **30+ BD tech companies** + **8 job platforms** + **Facebook groups** + **Twitter/X** concurrently
3. Filters results via **6-model parallel NVIDIA NIM ensemble** fused by **Kimi-K2.6**
4. Delivers rich job cards via `@oc_lab329_bot` Telegram bot (already running)
5. Runs **on-demand** (slash command) and **daily at 09:00 Asia/Dhaka** (APScheduler)
6. Deduplicates via SQLite — same job never appears twice

This is a new, standalone skill. Do NOT modify the existing `job-search` skill.

---

## STEP 0 — READ BEFORE WRITING ANY CODE

```bash
cat skills/caveman/SKILL.md          # match this exact SKILL.md format
cat ~/.openclaw/openclaw.json        # read config structure
ls skills/                           # understand project layout
ls data/                             # existing data directory
```

Key facts from config:
- Telegram bot token: in `channels.telegram.botToken`
- Chat ID: inferred from `commands.ownerAllowFrom[0]` → strip `"telegram:"` prefix
- NIM API key: `NVIDIA_API_KEY` environment variable (never hardcode)
- All NIM models use: `https://integrate.api.nvidia.com/v1/chat/completions`
- DB path: `data/job_searchs.db` (separate from existing `job_search.db`)

---

## STEP 1 — FILES TO CREATE

```
openclaw-lab/
└── skills/
    └── job-searchs/
        ├── SKILL.md            ← skill definition
        ├── job_searchs.py      ← full executor (~900 lines)
        └── requirements.txt    ← pip dependencies
```

Three files. No other files.

---

## STEP 2 — SKILL.md

Match the exact format of `skills/caveman/SKILL.md` (YAML frontmatter + markdown body):

```markdown
---
name: job-searchs
description: >
  Comprehensive CSE job search for Eyasir across 30+ BD tech companies, LinkedIn,
  BDJobs, BDTechJobs, Facebook job groups, Twitter/X, Glassdoor, and Indeed.
  Uses 6-model NVIDIA NIM ensemble + Kimi-K2.6 fusion. SQLite deduplication.
  Delivers formatted Telegram cards. Daily digest at 09:00 Asia/Dhaka.
---

Full-stack BD CSE job search. Searches career pages, job boards, social platforms,
and tech community groups simultaneously. 6-model AI ensemble ranks results by relevance
to Eyasir's profile (SWE / AI-ML / Intern / Trainee). Kimi-K2.6 fuses all model outputs.

## Trigger
/job-searchs

## Optional args
- `tier1`   → Tier 1 companies only, no job boards (~60s)
- `fresh`   → Clear seen-jobs cache, re-show all jobs
- `weekly`  → Send this week's summary only (no new search)
- `silent`  → No Telegram output (scheduler internal use)

## Telegram slash commands
/job_searchs              → full search (~4 min)
/job_searchs_tier1        → Tier 1 companies only (~60s)
/job_searchs_fresh        → clear cache + full search
/job_searchs_weekly       → weekly summary report

## Executor
skills/job-searchs/job_searchs.py

## Schedule
daily @ 09:00 Asia/Dhaka
```

---

## STEP 3 — requirements.txt

```
aiohttp==3.9.5
beautifulsoup4==4.12.3
lxml==5.2.2
apscheduler==3.10.4
fake-useragent==1.5.1
playwright==1.44.0
```

> Note: playwright is for JavaScript-heavy career pages. Install browsers with:
> `python -m playwright install chromium --with-deps`
> Gracefully degrade to aiohttp if playwright not available.

---

## STEP 4 — USER PROFILE (hardcode in job_searchs.py)

```python
USER = {
    "name":    "Eyasir",
    "degree":  "BSc Computer Science & Engineering",
    "linkedin": "https://www.linkedin.com/in/eyasir329/",
    "github":   "https://github.com/eyasir329",
    "facebook": "https://www.facebook.com/eyasir329",

    # All role types to accept
    "target_roles": [
        "Software Engineer",
        "Junior Software Engineer",
        "Associate Software Engineer",
        "Software Developer",
        "Backend Developer",
        "Frontend Developer",
        "Full-Stack Developer",
        "AI Engineer",
        "ML Engineer",
        "Machine Learning Engineer",
        "Deep Learning Engineer",
        "Data Engineer",
        "Data Scientist",
        "Research Engineer",
        "DevOps Engineer",
        "Site Reliability Engineer",
        "QA Engineer",
        "Software Engineer Intern",
        "Software Developer Intern",
        "Trainee Software Engineer",
        "Graduate Trainee",
        "Management Trainee (Tech Track)",
        "Junior Developer",
        "Competitive Programmer",
    ],

    # These must NOT appear in title or department
    "exclude_roles": [
        "HR", "Human Resources", "Finance", "Accounts", "Sales",
        "Marketing", "Admin", "Administrative", "Procurement",
        "Legal", "Logistics", "Customer Service", "Business Development",
        "Operations Manager", "Receptionist", "Driver", "Cashier",
    ],

    "location":          "Bangladesh",
    "preferred_cities":  ["Dhaka", "Chittagong"],
    "accept_remote":     True,  # remote-from-Bangladesh OK

    # Used in AI prompt for context
    "skills_summary": (
        "C++, Python, JavaScript/TypeScript, React, Node.js, "
        "SQL, competitive programming, algorithms & data structures, "
        "machine learning fundamentals, system design basics"
    ),
}
```

---

## STEP 5 — TARGET COMPANIES (30 companies + job boards)

### 5.1 Tier 1 — Top Priority (12 companies, scraped every run)

```python
TIER1 = [
    # ── High-activity, strong BD presence, frequently hire fresh grads ──
    {
        "name":      "Brain Station 23",
        "url":       "https://erp.bs-23.com/jobs",
        "linkedin":  "https://www.linkedin.com/company/brain-station-23-plc/jobs/",
        "notes":     "Large product company. Posts JS/React/Node/Python roles frequently.",
    },
    {
        "name":      "Enosis Solutions",
        "url":       "https://enosisbd.pinpointhq.com/",
        "linkedin":  "https://www.linkedin.com/company/enosis-solutions/jobs/",
        "remote":    True,
        "notes":     "Remote-friendly. Posts C#/.NET/Java/Python roles. Worth checking weekly.",
    },
    {
        "name":      "Samsung R&D Bangladesh",
        "url":       "https://research.samsung.com/srbd",
        "linkedin":  "https://www.linkedin.com/company/samsung-bangladesh/jobs/",
        "notes":     "Best for AI/ML and systems programming. Competitive selection.",
    },
    {
        "name":      "Cefalo Bangladesh",
        "url":       "https://cefalo.com/en/jobs/",
        "linkedin":  "https://www.linkedin.com/company/cefalo-bangladesh-ltd-/jobs/",
        "notes":     "Norwegian-owned. Hires full-stack and backend. Good for new grads.",
    },
    {
        "name":      "Therap BD",
        "url":       "https://therap.hire.trakstar.com/jobs/fk0hw8r",
        "linkedin":  "https://www.linkedin.com/company/therap-services/jobs/",
        "notes":     "US healthcare tech. Stable. Posts Java/React/QA regularly.",
    },
    {
        "name":      "BJIT Group",
        "url":       "https://bjitgroup.com/career",
        "linkedin":  "https://www.linkedin.com/company/bjit/jobs/",
        "notes":     "Japanese market. Posts embedded C, Java, Python.",
    },
    {
        "name":      "Pathao",
        "url":       "https://careers.pathao.com/jobs/",
        "linkedin":  "https://www.linkedin.com/company/pathao/jobs/",
        "notes":     "BD's biggest ride-share. Engineering org growing fast.",
    },
    {
        "name":      "Optimizely (BD office)",
        "url":       "https://www.optimizely.com/company/career/",
        "linkedin":  "https://www.linkedin.com/company/optimizely/jobs/",
        "notes":     "US product company with Dhaka engineering team.",
    },
    {
        "name":      "bKash",
        "url":       "https://www.bkash.com/bn/careers",
        "linkedin":  "https://www.linkedin.com/company/bkash-limited/jobs/",
        "notes":     "BD's largest fintech. Hires backend, data, DevOps.",
    },
    {
        "name":      "Viva Soft",
        "url":       "https://www.vivasoftltd.com/career/",
        "linkedin":  "https://www.linkedin.com/company/vivasoft-ltd/jobs/",
        "notes":     "Product and service hybrid. Hires full-stack regularly.",
    },
    {
        "name":      "Shikho",
        "url":       "https://shikho.com/careers",
        "linkedin":  "https://www.linkedin.com/company/shikhobangladesh/jobs/",
        "notes":     "EdTech unicorn candidate. Strong mobile and backend team.",
    },
    {
        "name":      "10 Minute School",
        "url":       "https://10minuteschool.com/careers",
        "linkedin":  "https://www.linkedin.com/company/10-minute-school/jobs/",
        "notes":     "Largest EdTech in BD. Hires React/Node/Python/DevOps.",
    },
]
```

### 5.2 Tier 2 — Important BD Tech (40 companies, skipped with `tier1` flag)

```python
TIER2 = [
    {"name": "Augmedix Bangladesh",          "url": "https://www.augmedix.com/careers/"},
    {"name": "TigerIT Bangladesh",           "url": "https://www.tigerit.com/"},
    {"name": "SELISE Digital",               "url": "https://selisegroup.com/join-the-team/"},
    {"name": "DataSoft Systems",             "url": "http://datasoft-bd.com/career/"},
    {"name": "ReliSource Technologies",      "url": "https://www.relisource.com/careers/"},
    {"name": "Shohoz",                       "url": "https://www.shohoz.com/career"},
    {"name": "Grameenphone",                 "url": "https://www.grameenphone.com/about/career"},
    {"name": "Robi Axiata",                  "url": "https://www.robi.com.bd/en/corporate/career"},
    {"name": "Kaz Software",                 "url": "https://kazsoftware.com/career/"},
    {"name": "Shajgoj",                      "url": "https://shajgoj.com/careers"},
    {"name": "Field Nation",                 "url": "https://careers.fieldnation.com/"},
    {"name": "Impulse BD",                   "url": "https://www.impulsebdltd.com/career"},
    {"name": "Chaldal",                      "url": "https://chaldal.com/careers"},
    {"name": "Chaldal Engineering",          "url": "https://chaldal.tech/freshgrad.html"},
    {"name": "SSL Wireless",                 "url": "https://www.sslwireless.com/career"},
    {"name": "Backspace Tech",               "url": "https://backspace.com.bd/career"},
    {"name": "Synesis IT",                   "url": "https://synesisit.com.bd/career/"},
    {"name": "Nascenia",                     "url": "https://www.nascenia.com/career/"},
    {"name": "Dohatec",                      "url": "https://www.dohatec-bd.com/career"},
    # ── Added from community list ────────────────────────────────────────────
    {"name": "WellDev",                      "url": "https://recruitment.welldev.io/public/jobs/db88764e-b85f-4f7f-b59f-61e5c77c3e77"},
    {"name": "Fifty-Two Digital",            "url": "https://fiftytwodigital.com/career/"},
    {"name": "Bit Mascot",                   "url": "https://www.bitmascot.com/careers/"},
    {"name": "Inverse.AI",                   "url": "https://inverseai.com/career",                "notes": "Sylhet-based"},
    {"name": "Kona Software Lab",            "url": "https://konasl.com/life-at-konasl/career-journey/"},
    {"name": "Shell Be Haken",               "url": "https://shellbeehaken.com/join-us"},
    {"name": "Kinetik",                      "url": "https://boards.greenhouse.io/kinetik"},
    {"name": "BroTecs",                      "url": "https://www.brotecs.com/job-openings/"},
    {"name": "Spring Rain",                  "url": "https://springrain.io/careers/"},
    {"name": "BRAC IT",                      "url": "https://www.bracits.com/career"},
    {"name": "IBOS",                         "url": "https://ibos.io/career/"},
    {"name": "Dynamic Solutions Innovator",  "url": "https://apply.workable.com/dsinnovators/"},
    {"name": "ShopUp",                       "url": "https://careers.smartrecruiters.com/ShopUp"},
    {"name": "Kite Games",                   "url": "https://www.kitegamesstudio.com/#career"},
    {"name": "AppsCode",                     "url": "https://appscode.com/"},
    {"name": "Streams Tech",                 "url": "https://streamstech.com/"},
    {"name": "SouthTech Group",              "url": "https://career.southtechgroup.com/"},
    {"name": "LeadSoft",                     "url": "https://leadsoft.com.bd/"},
    {"name": "ReveSoft",                     "url": "https://www.revesoft.com/careers"},
    {"name": "Tekarsh",                      "url": "https://tekarsh.com/"},
    {"name": "Muslim Pro",                   "url": "https://career.muslimpro.com/careers/"},
]
```

### 5.3 Job Platforms

```python
# BDJobs — Bangladesh's largest job board, IT/Telecom category
BDJOBS_KEYWORDS = [
    "software engineer",
    "junior software engineer",
    "associate software engineer",
    "machine learning engineer",
    "ai engineer",
    "software developer intern",
    "trainee software engineer",
    "graduate trainee it",
    "backend developer",
    "full stack developer",
    "data engineer",
    "devops engineer",
    "junior developer",
    "react developer",
    "node js developer",
    "python developer",
]
BDJOBS_BASE = "https://jobs.bdjobs.com/jobsearch.asp?txtsearch={kw}&fcat=14"

# BDTechJobs — tech-focused job board
BDTECHJOBS_URL = "https://www.bdtechjobs.com/jobs"

# Glassdoor BD tech search
GLASSDOOR_SEARCHES = [
    "https://www.glassdoor.com/Job/bangladesh-software-engineer-jobs-SRCH_IL.0,10_IN17_KO11,28.htm",
    "https://www.glassdoor.com/Job/bangladesh-machine-learning-engineer-jobs-SRCH_IL.0,10_IN17_KO11,36.htm",
]

# Indeed BD tech jobs
INDEED_SEARCHES = [
    "https://bd.indeed.com/jobs?q=software+engineer&l=Dhaka&fromage=7",
    "https://bd.indeed.com/jobs?q=machine+learning+engineer&l=Bangladesh&fromage=7",
    "https://bd.indeed.com/jobs?q=software+intern&l=Dhaka&fromage=7",
    "https://bd.indeed.com/jobs?q=junior+developer&l=Bangladesh&fromage=7",
    "https://bd.indeed.com/jobs?q=trainee+engineer&l=Bangladesh&fromage=7",
]

# LinkedIn public search — last 7 days, Bangladesh
LINKEDIN_SEARCHES = [
    "https://www.linkedin.com/jobs/search/?keywords=software+engineer&location=Bangladesh&f_TPR=r604800",
    "https://www.linkedin.com/jobs/search/?keywords=junior+software+engineer&location=Bangladesh&f_TPR=r604800",
    "https://www.linkedin.com/jobs/search/?keywords=ML+engineer&location=Bangladesh&f_TPR=r604800",
    "https://www.linkedin.com/jobs/search/?keywords=software+intern&location=Bangladesh&f_TPR=r604800",
    "https://www.linkedin.com/jobs/search/?keywords=trainee+engineer&location=Bangladesh&f_TPR=r604800",
    "https://www.linkedin.com/jobs/search/?keywords=AI+engineer&location=Bangladesh&f_TPR=r604800",
    "https://www.linkedin.com/jobs/search/?keywords=data+engineer&location=Bangladesh&f_TPR=r604800",
    "https://www.linkedin.com/jobs/search/?keywords=devops+engineer&location=Bangladesh&f_TPR=r604800",
]

# Facebook job groups — public group post feeds
# These groups contain BD tech job postings from community members
FACEBOOK_GROUPS = [
    {
        "name":    "BD Software Jobs",
        "gid":     "781773098552968",
        "url":     "https://mbasic.facebook.com/groups/781773098552968/?view=articles",
        "mobile":  "https://m.facebook.com/groups/781773098552968/",
    },
    {
        "name":    "BD Contest Programmers",
        "gid":     "bd.contest.programmers",
        "url":     "https://mbasic.facebook.com/groups/bd.contest.programmers/?view=articles",
        "mobile":  "https://m.facebook.com/groups/bd.contest.programmers/",
    },
    {
        "name":    "CSE Jobs Bangladesh",
        "gid":     "csejobsbangladesh",
        "url":     "https://mbasic.facebook.com/groups/csejobsbangladesh/?view=articles",
        "mobile":  "https://m.facebook.com/groups/csejobsbangladesh/",
    },
    {
        "name":    "Bangladesh Software Engineers",
        "gid":     "BangladeshSoftwareEngineers",
        "url":     "https://mbasic.facebook.com/groups/BangladeshSoftwareEngineers/?view=articles",
        "mobile":  "https://m.facebook.com/groups/BangladeshSoftwareEngineers/",
    },
]

# Twitter/X via Nitter (open-source Twitter frontend — no API key needed)
# Searches BD tech job tweets from the last 7 days
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
]
TWITTER_JOB_SEARCHES = [
    "#SWEjobsBD",
    "#BDtechjobs",
    "#CSEjobsBD",
    "hiring Bangladesh software engineer",
    "hiring Bangladesh intern developer",
    "software engineer job Bangladesh",
    "internship Bangladesh CSE 2025",
    "#BrainStation23 hiring",
    "#Enosis hiring",
    "#Pathao hiring",
    "#bKash hiring",
]
```

---

## STEP 6 — FULL IMPLEMENTATION: job_searchs.py

Build `skills/job-searchs/job_searchs.py` (~900 lines).
Implement every section below completely. No stubs. No TODOs.

### 6.1 Imports and constants

```python
#!/usr/bin/env python3
"""
OpenClaw Skill: job-searchs

Full-stack BD CSE job search for Eyasir (eyasir329).
Searches: 30 company career pages + BDJobs + BDTechJobs + LinkedIn +
          Indeed + Glassdoor + Facebook groups (mbasic) + Twitter/X (Nitter)
Scores: 6-model NVIDIA NIM parallel ensemble
Fuses:  Kimi-K2.6 at temperature=0 (deterministic)
Deduplicates: SQLite (data/job_searchs.db)
Notifies: @oc_lab329_bot via Telegram MarkdownV2

CLI:
  python job_searchs.py               → on-demand full search
  python job_searchs.py tier1         → Tier 1 only (~60s)
  python job_searchs.py fresh         → clear cache + search
  python job_searchs.py weekly        → send weekly summary, no search
  python job_searchs.py --schedule    → start daily scheduler (blocking)
  python job_searchs.py --test        → scraper smoke test only
"""

import asyncio
import hashlib
import json
import os
import random
import re
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, quote_plus
from zoneinfo import ZoneInfo

import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bs4 import BeautifulSoup

_FALLBACK_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

try:
    from fake_useragent import UserAgent as _FUA
    _ua_pool = _FUA()
    def random_ua() -> str:
        try:    return _ua_pool.random
        except: return _FALLBACK_UA
except ImportError:
    def random_ua() -> str:
        return _FALLBACK_UA

OPENCLAW_CONFIG = Path.home() / ".openclaw/openclaw.json"
DB_PATH         = Path(__file__).parent / "../../data/job_searchs.db"
DHAKA_TZ        = ZoneInfo("Asia/Dhaka")
NIM_ENDPOINT    = "https://integrate.api.nvidia.com/v1/chat/completions"

# Keywords for career page link detection
JOB_LINK_KEYWORDS = frozenset({
    "engineer", "developer", "intern", "trainee", "analyst", "scientist",
    "devops", "architect", "lead", "researcher", "qa", "tester", "programmer",
    "associate", "junior", "graduate", "backend", "frontend", "fullstack",
    "machine learning", "deep learning", "data engineer", "sre",
})

# Keywords that indicate a post/text contains a job opening
JOB_POST_KEYWORDS = frozenset({
    "hiring", "we are looking", "job opening", "job opportunity",
    "vacancy", "position available", "apply now", "join our team",
    "internship", "intern opening", "trainee", "fresh graduate",
    "recruitment", "career opportunity", "open position",
    "we're hiring", "software engineer", "developer wanted",
    "cse graduate", "looking for", "job circular",
})
```

### 6.2 Config loader

```python
def load_openclaw_config() -> tuple[str, str, str]:
    """Load Telegram token, chat ID, NIM key from OpenClaw config."""
    with open(OPENCLAW_CONFIG) as f:
        cfg = json.load(f)

    token = cfg["channels"]["telegram"]["botToken"]

    chat_id = cfg["channels"]["telegram"].get("chatId") or os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        for entry in cfg.get("commands", {}).get("ownerAllowFrom", []):
            if entry.startswith("telegram:"):
                chat_id = entry.split(":", 1)[1]
                break

    nim_key = os.environ.get("NVIDIA_API_KEY", "")
    if not nim_key:
        raise EnvironmentError("NVIDIA_API_KEY not set")

    return token, chat_id, nim_key
```

### 6.3 HTTP helpers

```python
def desktop_headers() -> dict:
    return {
        "User-Agent":      random_ua(),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }

def mobile_headers() -> dict:
    return {
        "User-Agent":      _MOBILE_UA,
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "X-Requested-With": "XMLHttpRequest",
    }

async def fetch_html(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict = None,
    timeout: int = 25,
    retries: int = 2,
) -> str | None:
    """
    GET request. Returns HTML string or None on failure.
    Retries once on connection error (transient Codespaces networking).
    Logs URL (truncated) and failure reason.
    """
    hdrs = headers or desktop_headers()
    for attempt in range(retries):
        try:
            async with session.get(
                url, headers=hdrs,
                timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=True,
            ) as r:
                if r.status == 200:
                    return await r.text(errors="replace")
                if r.status == 429:
                    wait = 2 ** attempt * 3
                    print(f"[scraper] 429 rate-limit on {url[:60]} — wait {wait}s")
                    await asyncio.sleep(wait)
                    continue
                print(f"[scraper] HTTP {r.status}: {url[:70]}")
                return None
        except asyncio.TimeoutError:
            print(f"[scraper] Timeout ({timeout}s): {url[:70]}")
            return None
        except aiohttp.ClientConnectorError as e:
            if attempt < retries - 1:
                await asyncio.sleep(1)
                continue
            print(f"[scraper] Connect error: {url[:70]} — {e}")
            return None
        except Exception as e:
            print(f"[scraper] {type(e).__name__}: {url[:70]} — {e}")
            return None
    return None
```

### 6.4 Database layer

```python
def init_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS seen_jobs (
            id              TEXT PRIMARY KEY,
            title           TEXT NOT NULL,
            company         TEXT NOT NULL,
            url             TEXT NOT NULL,
            platform        TEXT,
            tier            INTEGER DEFAULT 3,
            relevance_score REAL    DEFAULT 5.0,
            source_type     TEXT,   -- 'career_page' | 'job_board' | 'social'
            found_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS search_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            searched_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            trigger         TEXT,
            total_scraped   INTEGER DEFAULT 0,
            new_jobs        INTEGER DEFAULT 0,
            filtered_jobs   INTEGER DEFAULT 0,
            ensemble_models INTEGER DEFAULT 0,
            duration_secs   REAL    DEFAULT 0,
            platforms_hit   TEXT    DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS platform_stats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      INTEGER REFERENCES search_log(id),
            platform    TEXT,
            jobs_found  INTEGER DEFAULT 0,
            status      TEXT    DEFAULT 'ok'  -- 'ok' | 'blocked' | 'empty' | 'error'
        );
    """)
    conn.commit()
    return conn

def job_uid(title: str, company: str, url: str) -> str:
    """16-char SHA-256 hash — stable cross-run deduplication key."""
    key = f"{title.strip().lower()}{company.strip().lower()}{url.strip()}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]

def is_seen(conn: sqlite3.Connection, uid: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM seen_jobs WHERE id=?", (uid,)).fetchone())

def mark_seen(conn: sqlite3.Connection, job: dict):
    conn.execute(
        "INSERT OR IGNORE INTO seen_jobs "
        "VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
        (
            job["id"], job["title"], job["company"], job["url"],
            job.get("platform"), job.get("tier", 3),
            job.get("final_score", job.get("relevance_score", 5.0)),
            job.get("source_type", "unknown"),
        ),
    )
    conn.commit()

def log_run(conn, trigger, total, new_count, filtered, models, duration, platforms):
    cur = conn.execute(
        "INSERT INTO search_log "
        "(trigger,total_scraped,new_jobs,filtered_jobs,ensemble_models,duration_secs,platforms_hit) "
        "VALUES (?,?,?,?,?,?,?)",
        (trigger, total, new_count, filtered, models, round(duration,1), json.dumps(platforms)),
    )
    conn.commit()
    return cur.lastrowid

def get_weekly_stats(conn) -> dict:
    row = conn.execute("""
        SELECT
            COUNT(*)                                         AS total_jobs,
            COUNT(DISTINCT company)                          AS companies,
            COUNT(DISTINCT platform)                         AS platforms,
            MAX(found_at)                                    AS last_found,
            SUM(CASE WHEN tier=1 THEN 1 ELSE 0 END)         AS tier1_jobs,
            SUM(CASE WHEN source_type='social' THEN 1 ELSE 0 END) AS social_jobs
        FROM seen_jobs
        WHERE found_at >= datetime('now', '-7 days')
    """).fetchone()
    keys = ["total_jobs","companies","platforms","last_found","tier1_jobs","social_jobs"]
    return dict(zip(keys, row)) if row else {}
```

### 6.5 Scrapers

#### 6.5.1 Career page scraper (company websites)

```python
async def scrape_career_page(
    session: aiohttp.ClientSession,
    company: dict,
) -> list[dict]:
    """
    Scrape a company career page. Finds <a> tags whose text matches
    JOB_LINK_KEYWORDS. Resolves relative URLs. Caps at 15 per company.
    On any failure: logs warning, returns [] without blocking others.
    """
    url  = company["url"]
    name = company["name"]
    tier = company.get("tier", 2)

    html = await fetch_html(session, url)
    if not html:
        print(f"[career] ❓ Unreachable: {name}")
        return []

    try:
        soup = BeautifulSoup(html, "lxml")
        jobs: list[dict] = []
        seen_urls: set[str] = set()

        for a in soup.find_all("a", href=True):
            text = a.get_text(" ", strip=True)
            text_lower = text.lower()
            if not any(kw in text_lower for kw in JOB_LINK_KEYWORDS):
                continue
            href    = a["href"].strip()
            abs_url = urljoin(url, href)
            if abs_url in seen_urls or abs_url.rstrip("/") == url.rstrip("/"):
                continue
            seen_urls.add(abs_url)
            jobs.append({
                "title":       text[:120],
                "company":     name,
                "url":         abs_url,
                "platform":    "Career Page",
                "tier":        tier,
                "remote":      company.get("remote", False),
                "source_type": "career_page",
            })
            if len(jobs) >= 15:
                break

        print(f"[career] {name}: {len(jobs)} jobs")
        return jobs
    except Exception as e:
        print(f"[career] {name} parse error: {e}")
        return []
```

#### 6.5.2 LinkedIn scraper

```python
async def scrape_linkedin(
    session: aiohttp.ClientSession,
    search_url: str,
) -> list[dict]:
    """
    LinkedIn public job search. Sleep 2-5s before each request (randomized).
    Strips tracking params. Returns [] gracefully on any block.
    LinkedIn frequently returns empty pages in cloud environments — this is expected.
    """
    await asyncio.sleep(random.uniform(2.0, 5.0))
    html = await fetch_html(session, search_url, timeout=30)
    if not html:
        print("[linkedin] ⚠️ Fetch failed")
        return []

    try:
        soup  = BeautifulSoup(html, "lxml")
        cards = soup.select(".base-card, .job-search-card, .jobs-search__results-list li")
        if not cards:
            print("[linkedin] ⚠️ No cards found (rate-limited or CAPTCHA)")
            return []

        kw      = search_url.split("keywords=")[1].split("&")[0] if "keywords=" in search_url else "?"
        jobs    = []
        seen    : set[str] = set()

        for card in cards[:20]:
            title_el   = card.select_one(".base-search-card__title, h3, .job-result-card__title")
            company_el = card.select_one(".base-search-card__subtitle, h4, .job-result-card__subtitle")
            link_el    = card.select_one("a[href*='linkedin.com/jobs']")
            if not (title_el and link_el):
                continue
            title   = title_el.get_text(strip=True)[:120]
            company = company_el.get_text(strip=True)[:80] if company_el else "Unknown"
            href    = link_el["href"].split("?")[0]
            if href in seen:
                continue
            seen.add(href)
            jobs.append({
                "title":       title,
                "company":     company,
                "url":         href,
                "platform":    "LinkedIn",
                "tier":        3,
                "remote":      False,
                "source_type": "job_board",
            })

        print(f"[linkedin] '{kw}': {len(jobs)} jobs")
        return jobs
    except Exception as e:
        print(f"[linkedin] Parse error: {e}")
        return []
```

#### 6.5.3 BDJobs scraper

```python
async def scrape_bdjobs(
    session: aiohttp.ClientSession,
    keyword: str,
) -> list[dict]:
    """
    BDJobs IT/Telecom category search (fcat=14). Polite 0.5s sleep per keyword.
    Parses job listing rows. Caps at 20 per keyword.
    """
    url  = f"https://jobs.bdjobs.com/jobsearch.asp?txtsearch={quote_plus(keyword)}&fcat=14"
    html = await fetch_html(session, url)
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "lxml")
        jobs = []
        for row in soup.select("div.job-list-single, div.norm-jobs, .InnJobListCom"):
            ta = row.select_one("a.job-title-link, h2 a, .job-name a, a[href*='jobdetail']")
            ca = row.select_one(".company-name, .job-company, .org-name, .InnCom")
            if not ta:
                continue
            title = ta.get_text(strip=True)[:120]
            comp  = ca.get_text(strip=True)[:80] if ca else "Unknown"
            href  = urljoin("https://jobs.bdjobs.com/", ta.get("href", ""))
            if not title or href == "https://jobs.bdjobs.com/":
                continue
            jobs.append({
                "title": title, "company": comp, "url": href,
                "platform": "BDJobs", "tier": 3, "remote": False,
                "source_type": "job_board",
            })
            if len(jobs) >= 20:
                break
        print(f"[bdjobs] '{keyword}': {len(jobs)}")
        await asyncio.sleep(0.5)
        return jobs
    except Exception as e:
        print(f"[bdjobs] '{keyword}' error: {e}")
        return []
```

#### 6.5.4 BDTechJobs scraper

```python
async def scrape_bdtechjobs(session: aiohttp.ClientSession) -> list[dict]:
    """Scrape bdtechjobs.com. Caps at 30."""
    url  = "https://www.bdtechjobs.com/jobs"
    html = await fetch_html(session, url)
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "lxml")
        jobs = []
        seen: set[str] = set()
        for a in soup.select("a[href*='/job'], a[href*='/jobs/']"):
            text = a.get_text(strip=True)
            if not text or len(text) < 5:
                continue
            href = urljoin(url, a["href"])
            if href in seen or href == url:
                continue
            seen.add(href)
            parent = a.find_parent(["div", "li", "article"])
            co_el  = parent.select_one(".company, .org, [class*='company']") if parent else None
            comp   = co_el.get_text(strip=True)[:80] if co_el else "BD Tech Company"
            jobs.append({
                "title": text[:120], "company": comp, "url": href,
                "platform": "BDTechJobs", "tier": 3, "remote": False,
                "source_type": "job_board",
            })
            if len(jobs) >= 30:
                break
        print(f"[bdtechjobs] {len(jobs)} jobs")
        return jobs
    except Exception as e:
        print(f"[bdtechjobs] error: {e}")
        return []
```

#### 6.5.5 Indeed BD scraper

```python
async def scrape_indeed(
    session: aiohttp.ClientSession,
    search_url: str,
) -> list[dict]:
    """
    Indeed Bangladesh job search. Uses rotating desktop UA.
    Parses .job_seen_beacon, .tapItem, and jobsearch-ResultsList items.
    Rate-limit: sleep 1-2s between calls.
    """
    await asyncio.sleep(random.uniform(1.0, 2.0))
    html = await fetch_html(session, search_url, timeout=30)
    if not html:
        print("[indeed] ⚠️ Fetch failed")
        return []
    try:
        soup  = BeautifulSoup(html, "lxml")
        cards = soup.select(".job_seen_beacon, .tapItem, [data-testid='jobListing']")
        if not cards:
            print("[indeed] ⚠️ No cards found")
            return []
        jobs = []
        seen: set[str] = set()
        for card in cards[:20]:
            ta = card.select_one("h2 a, .jobTitle a, [data-testid='job-title'] a")
            ca = card.select_one(".companyName, [data-testid='company-name']")
            if not ta:
                continue
            title = ta.get_text(strip=True)[:120]
            comp  = ca.get_text(strip=True)[:80] if ca else "Unknown"
            href  = ta.get("href", "")
            if href and not href.startswith("http"):
                href = "https://bd.indeed.com" + href
            href = href.split("?")[0]
            if href in seen or not href:
                continue
            seen.add(href)
            jobs.append({
                "title": title, "company": comp, "url": href,
                "platform": "Indeed BD", "tier": 3, "remote": False,
                "source_type": "job_board",
            })
        print(f"[indeed] {len(jobs)} jobs from {search_url.split('q=')[1].split('&')[0]}")
        return jobs
    except Exception as e:
        print(f"[indeed] parse error: {e}")
        return []
```

#### 6.5.6 Glassdoor scraper

```python
async def scrape_glassdoor(
    session: aiohttp.ClientSession,
    search_url: str,
) -> list[dict]:
    """
    Glassdoor BD tech job search. Glassdoor frequently blocks scrapers.
    Returns [] gracefully on any block — does not affect other scrapers.
    """
    await asyncio.sleep(random.uniform(1.5, 3.0))
    html = await fetch_html(session, search_url, timeout=30)
    if not html:
        print("[glassdoor] ⚠️ Fetch failed (likely blocked)")
        return []
    try:
        soup  = BeautifulSoup(html, "lxml")
        cards = soup.select("[data-test='jobListing'], .react-job-listing, li[data-id]")
        if not cards:
            print("[glassdoor] ⚠️ No listings found (blocked or no results)")
            return []
        jobs = []
        seen: set[str] = set()
        for card in cards[:15]:
            ta = card.select_one("a[data-test='job-link'], a.jobLink, h2 a")
            ca = card.select_one(".job-search-key-l93tw3, .employer-name, [class*='EmployerName']")
            if not ta:
                continue
            title = ta.get_text(strip=True)[:120]
            comp  = ca.get_text(strip=True)[:80] if ca else "Unknown"
            href  = ta.get("href","")
            if href and not href.startswith("http"):
                href = "https://www.glassdoor.com" + href
            if href in seen or not href:
                continue
            seen.add(href)
            jobs.append({
                "title": title, "company": comp, "url": href,
                "platform": "Glassdoor", "tier": 3, "remote": False,
                "source_type": "job_board",
            })
        print(f"[glassdoor] {len(jobs)} jobs")
        return jobs
    except Exception as e:
        print(f"[glassdoor] parse error: {e}")
        return []
```

#### 6.5.7 Facebook groups scraper (mbasic)

```python
async def scrape_facebook_group(
    session: aiohttp.ClientSession,
    group: dict,
) -> list[dict]:
    """
    Scrape a Facebook group via mbasic.facebook.com (the lightweight mobile interface
    that works without JavaScript and with limited or no auth).

    Strategy:
    1. Try mbasic.facebook.com/groups/{gid}/?view=articles (no login needed for public groups)
    2. Parse post bodies looking for JOB_POST_KEYWORDS
    3. Extract company names, titles, and any external URLs from post text
    4. Fall back gracefully if login wall hit (return [])

    Limitations:
    - Private groups require session cookies (stored in config as facebook_cookies)
    - mbasic shows limited posts per page — captures most recent ~10-20 posts
    - Post text extraction is heuristic — company/title may need AI cleanup

    Rate limiting: sleep 3-5s per group request.
    """
    await asyncio.sleep(random.uniform(3.0, 5.0))
    url  = group["url"]
    name = group["name"]

    html = await fetch_html(session, url, headers=mobile_headers(), timeout=30)
    if not html:
        print(f"[facebook] ⚠️ {name}: fetch failed")
        return []

    # Detect login wall
    soup = BeautifulSoup(html, "lxml")
    if soup.select_one("#login_form, #loginbutton, input[name='pass']"):
        print(f"[facebook] 🔒 {name}: login required — group is private or mbasic blocked")
        return []

    try:
        jobs = []
        seen: set[str] = set()

        # mbasic renders posts as <div> blocks with class containing "story_body" or similar
        # The exact selectors vary — try multiple patterns
        post_containers = (
            soup.select("div[data-ft] div._5rgt._5msi") or
            soup.select("div.story_body_container") or
            soup.select("div[data-store] div") or
            soup.select("article") or
            soup.select("div.d div") or
            soup.select("._4prr div")
        )

        if not post_containers:
            # Fallback: find all paragraphs with job keywords
            post_containers = [
                p.find_parent("div") for p in soup.find_all("p")
                if any(kw in p.get_text().lower() for kw in JOB_POST_KEYWORDS)
            ]
            post_containers = [c for c in post_containers if c]

        for container in post_containers[:25]:
            text = container.get_text(" ", strip=True)
            text_lower = text.lower()

            # Must contain at least one job-related keyword
            if not any(kw in text_lower for kw in JOB_POST_KEYWORDS):
                continue

            # Exclude non-job posts (study tips, contest, etc.)
            if len(text) < 30 or len(text) > 3000:
                continue

            # Try to extract job title from text
            title = _extract_job_title_from_text(text)
            if not title:
                title = text[:80].strip()

            # Try to extract company name
            company = _extract_company_from_text(text) or name

            # Try to find a link in this post
            link_el = container.find("a", href=True)
            href    = ""
            if link_el:
                href = link_el["href"]
                # mbasic wraps external links: /l.php?u=https%3A%2F%2F...
                if "/l.php?u=" in href:
                    try:
                        from urllib.parse import unquote, urlparse, parse_qs
                        qs  = parse_qs(urlparse(href).query)
                        href = unquote(qs.get("u", [""])[0])
                    except Exception:
                        pass
                if not href.startswith("http"):
                    href = f"https://www.facebook.com{href}"

            # Use the group post link if no external link found
            if not href:
                # Construct a synthetic URL using the group name and a hash of text
                uid = hashlib.sha256(text[:100].encode()).hexdigest()[:8]
                href = f"https://www.facebook.com/groups/{group['gid']}/?post={uid}"

            if href in seen:
                continue
            seen.add(href)

            jobs.append({
                "title":       title,
                "company":     company,
                "url":         href,
                "platform":    f"Facebook/{name}",
                "tier":        3,
                "remote":      "remote" in text_lower,
                "source_type": "social",
                "raw_text":    text[:500],  # kept for AI scoring context
            })
            if len(jobs) >= 10:
                break

        print(f"[facebook] {name}: {len(jobs)} potential job posts")
        return jobs

    except Exception as e:
        print(f"[facebook] {name} parse error: {e}")
        return []


def _extract_job_title_from_text(text: str) -> str:
    """
    Heuristic extraction of job title from a social media post.
    Looks for patterns like:
    - "Looking for: Software Engineer"
    - "Position: Junior Developer"
    - "Role: ML Engineer"
    - "Hiring Software Engineer"
    - "Job: Backend Developer"
    """
    patterns = [
        r"(?:looking for|hiring|position|role|job|vacancy)[:\s]+([A-Za-z\s/&\-]+?)(?:\.|,|\n|at\s)",
        r"(?:software|junior|senior|associate|backend|frontend|full.?stack|ml|ai|data|devops)\s+(?:engineer|developer|intern|trainee)[^\n]{0,30}",
        r"(?:intern|trainee)[:\s]+([A-Za-z\s]+?)(?:\.|,|\n)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            found = m.group(0)[:80].strip()
            if found:
                return found
    return ""


def _extract_company_from_text(text: str) -> str:
    """
    Heuristic extraction of company name from a social media post.
    Looks for patterns like:
    - "at Brain Station 23"
    - "join Company Name"
    - "Company Name is hiring"
    """
    # Check for known BD company names first
    known_companies = [
        "Brain Station 23", "Enosis", "Samsung R&D", "Viva Soft",
        "Cefalo", "Therap", "BJIT", "Pathao", "bKash", "Optimizely",
        "Augmedix", "TigerIT", "SELISE", "DataSoft", "ReliSource",
        "Shohoz", "Grameenphone", "Robi", "Kaz Software", "Shajgoj",
        "Field Nation", "Impulse", "Chaldal", "SSL Wireless", "Synesis",
        "Nascenia", "Dohatec", "Backspace", "Shikho", "10 Minute School",
    ]
    for co in known_companies:
        if co.lower() in text.lower():
            return co

    patterns = [
        r"(?:at|@|join|company:\s*)([A-Z][A-Za-z0-9\s&\-\.]{2,40}?)(?:\s+is|\s+are|\.|,|\n)",
        r"([A-Z][A-Za-z0-9\s&\-]{2,30}?)\s+(?:is hiring|is looking for|has opening)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            name = m.group(1).strip()
            if 3 <= len(name) <= 50:
                return name
    return ""
```

#### 6.5.8 Twitter/X via Nitter scraper

```python
async def scrape_nitter(
    session: aiohttp.ClientSession,
    query: str,
    nitter_base: str,
) -> list[dict]:
    """
    Search Twitter/X job tweets via Nitter (open-source Twitter frontend).
    No API key needed. Nitter renders public tweets as plain HTML.
    Tries multiple Nitter instances in case one is down.

    Strategy:
    1. GET {nitter_base}/search?q={encoded_query}&f=tweets
    2. Parse .timeline-item elements
    3. Filter tweets containing JOB_POST_KEYWORDS
    4. Extract tweet text, author handle, tweet URL
    5. Return jobs where tweet clearly describes a job opening
    """
    encoded = quote_plus(query)
    url     = f"{nitter_base}/search?q={encoded}&f=tweets"

    await asyncio.sleep(random.uniform(0.5, 1.5))
    html = await fetch_html(session, url, timeout=20)
    if not html:
        return []

    try:
        soup   = BeautifulSoup(html, "lxml")
        tweets = soup.select(".timeline-item")
        if not tweets:
            return []

        jobs = []
        seen: set[str] = set()

        for tweet in tweets[:30]:
            content_el = tweet.select_one(".tweet-content, .tweet-body")
            author_el  = tweet.select_one(".username, .tweet-header .username")
            link_el    = tweet.select_one("a.tweet-link, a[href*='/status/']")
            if not content_el:
                continue

            text = content_el.get_text(" ", strip=True)
            if not any(kw in text.lower() for kw in JOB_POST_KEYWORDS):
                continue

            author = author_el.get_text(strip=True) if author_el else "@unknown"
            href   = link_el.get("href", "") if link_el else ""
            if href and not href.startswith("http"):
                href = f"https://twitter.com{href}"
            if href in seen or not href:
                continue
            seen.add(href)

            title   = _extract_job_title_from_text(text) or text[:80]
            company = _extract_company_from_text(text) or f"Twitter/{author}"

            jobs.append({
                "title":       title,
                "company":     company,
                "url":         href,
                "platform":    "Twitter/X",
                "tier":        3,
                "remote":      "remote" in text.lower(),
                "source_type": "social",
                "raw_text":    text[:500],
            })

        print(f"[twitter] '{query}': {len(jobs)} relevant tweets via {nitter_base}")
        return jobs
    except Exception as e:
        print(f"[twitter] parse error for '{query}': {e}")
        return []


async def scrape_twitter_jobs(session: aiohttp.ClientSession) -> list[dict]:
    """
    Try all NITTER_INSTANCES for each query. Use the first instance that responds.
    Aggregate results across all queries, deduplicate by tweet URL.
    """
    all_jobs = []
    seen_urls: set[str] = set()

    # Find the first working nitter instance
    working_nitter = None
    for instance in NITTER_INSTANCES:
        html = await fetch_html(session, instance, timeout=10)
        if html:
            working_nitter = instance
            print(f"[twitter] Using nitter: {instance}")
            break

    if not working_nitter:
        print("[twitter] ⚠️ All Nitter instances unreachable — skipping Twitter search")
        return []

    for query in TWITTER_JOB_SEARCHES:
        jobs = await scrape_nitter(session, query, working_nitter)
        for j in jobs:
            if j["url"] not in seen_urls:
                seen_urls.add(j["url"])
                all_jobs.append(j)
        await asyncio.sleep(0.3)

    print(f"[twitter] Total: {len(all_jobs)} unique job tweets")
    return all_jobs
```

### 6.6 Ensemble model config and prompts

```python
# ══════════════════════════════════════════════════════════
# ENSEMBLE MODEL ROSTER
#
# Tier S — Maximum intelligence:
#   kimi-k2.6    : 1T total / 32B active, #1 open-weights, 256k ctx.
#                  Also serves as FUSION model (temperature=0).
#   qwen3.5-397b : 397B/17B active. SOTA reasoning, Bengali-aware.
#
# Tier A — Structured JSON specialists:
#   nemotron-120b: OpenClaw default. Best JSON + agentic on NIM.
#   nemotron-49b : Reasoning specialist, top RAG tasks.
#
# Tier B — Fast, diverse signal:
#   llama4-maverick: ~0.2s latency, 1M context.
#   mistral-119b   : Different arch = blind-spot diversity.
# ══════════════════════════════════════════════════════════

ENSEMBLE_MODELS = [
    {"id": "moonshotai/kimi-k2.6",                     "label": "kimi-k2.6",          "tier": "S", "weight": 2.0, "timeout": 180},
    {"id": "qwen/qwen3.5-397b-a17b",                   "label": "qwen3.5-397b",        "tier": "S", "weight": 1.8, "timeout": 150},
    {"id": "nvidia/nemotron-3-super-120b-a12b",        "label": "nemotron-super-120b", "tier": "A", "weight": 1.5, "timeout": 120},
    {"id": "nvidia/llama-3.3-nemotron-super-49b-v1.5", "label": "nemotron-super-49b",  "tier": "A", "weight": 1.4, "timeout": 90},
    {"id": "meta/llama-4-maverick-17b-128e-instruct",  "label": "llama4-maverick",     "tier": "B", "weight": 1.0, "timeout": 30},
    {"id": "mistralai/mistral-small-4-119b-2603",      "label": "mistral-small-119b",  "tier": "B", "weight": 1.0, "timeout": 60},
]

FUSION_MODEL   = "moonshotai/kimi-k2.6"
FUSION_TIMEOUT = 180

SCORER_SYSTEM_PROMPT = f"""You are a precise job relevance scorer for Eyasir, a CSE graduate in Bangladesh.

Profile:
- Degree: BSc Computer Science & Engineering
- Skills: {USER['skills_summary']}
- LinkedIn: {USER['linkedin']}
- GitHub:   {USER['github']}
- Location: Bangladesh (Dhaka preferred, remote from BD accepted)

Target roles (include any of these):
{chr(10).join(f'  - {r}' for r in USER['target_roles'])}

Exclude non-tech roles (drop if title or department matches):
{', '.join(USER['exclude_roles'])}

For each job in the input JSON:
- Score relevance 0-10 for Eyasir specifically
- Drop jobs with relevance_score < 5
- Drop jobs from excluded role types
- Social-source jobs (from Facebook/Twitter) may have noisy titles — use raw_text field
  if present to understand the actual role before scoring
- Remote jobs from BD-based companies score same as on-site

Return a valid JSON array. Each entry MUST have EXACTLY these fields:
{{
  "job_id":          "string — copy exactly from input",
  "title":           "string — clean up noisy social titles",
  "company":         "string",
  "url":             "string",
  "platform":        "string",
  "tier":            1,
  "source_type":     "career_page",
  "relevance_score": 8,
  "why_relevant":    "max 10 words — specific technical reason",
  "remote":          false,
  "apply_note":      "max 8 words — any key info for applicant or empty string"
}}

Return ONLY the raw JSON array. No markdown. No explanation."""

FUSION_SYSTEM_PROMPT = """You are an elite job search result fusion engine for a CSE graduate in Bangladesh.
You receive scored job lists from 6 AI models with labels, tiers, and weights.
Produce ONE final ranked list using weighted consensus.

Fusion rules (apply all):
1. final_score = weighted average of relevance_score across models that included this job
2. BOOST ×1.15 → job in 5-6 models
3. BOOST ×1.05 → job in 3-4 models
4. DROP → single model AND score < 7
5. VETO → kimi-k2.6 OR qwen3.5-397b scored job < 5
6. Sort → model_agreement DESC, final_score DESC
7. Deduplicate by url — keep highest-scored
8. why_relevant → sharpest explanation across all models
9. apply_note → most useful applicant tip across all models
10. Social-source jobs (Facebook/Twitter) → apply score penalty of -0.5 unless
    multiple models independently scored it >= 7 (high confidence from noisy source)

Return ONLY a raw JSON array. Each entry must have exactly:
title, company, url, platform, tier, source_type, final_score (float 0-10),
why_relevant, apply_note, remote, model_agreement (int 1-6), confidence (high/medium/low)

confidence: >= 5 models = "high", 3-4 = "medium", 1-2 = "low"
No markdown. Raw JSON array only."""
```

### 6.7 call_model, local_fusion, fuse_with_kimi, filter_with_ensemble

Implement these four functions identically to the existing `job-search` skill's
implementation (`skills/job-search/job_search.py` lines ~500-750), with these changes:

1. In `call_model()`: include `"source_type"` and `"raw_text"` in the payload
   (so social posts get context in the prompt)
2. In `local_fusion()`: apply -0.5 penalty to social-source jobs with agreement < 3
3. In `FUSION_SYSTEM_PROMPT`: already instructs this (see above)
4. Everything else: identical logic — same weighted average, same veto, same boosts

Copy the function signatures and docstrings from the existing skill, adapt for the above.

### 6.8 Telegram formatter

```python
def tg_escape(text: str) -> str:
    """Escape for Telegram MarkdownV2."""
    return re.sub(r'([\\_*\[\]()~`>#+\-=|{}.!])', r'\\\1', str(text))


def format_jobs(jobs: list[dict], trigger: str = "command", run_stats: dict = None) -> str:
    """
    Format final job list as Telegram MarkdownV2 message.

    Header shows:
    - Trigger type (on-demand vs scheduler greeting)
    - Date/time in Dhaka timezone
    - Count breakdown: total / high / medium / low
    - Platform summary (how many sources contributed)
    - Ensemble metadata

    Per-job card shows:
    - Company + tier badge
    - Clean title
    - Score / confidence / agreement bar (6 models)
    - Location (remote vs Bangladesh + city if known)
    - Platform / source type
    - Why relevant (short AI reason)
    - Apply note (if any — e.g. "fresh grads only", "apply via email")
    - Apply link

    Social-source jobs (Facebook/Twitter) get a 📢 badge to indicate
    community-sourced — applicant should verify details.

    Footer: model credits + Eyasir's profile links.
    """
    now = datetime.now(DHAKA_TZ).strftime("%a, %d %b %Y  %I:%M %p")

    if trigger == "scheduler":
        header = f"🌅 *Good morning Eyasir\\!* Daily job digest\n"
    else:
        header = f"🔍 *CSE Job Search — Bangladesh*\n"

    high_c   = sum(1 for j in jobs if j.get("confidence") == "high")
    medium_c = sum(1 for j in jobs if j.get("confidence") == "medium")
    low_c    = sum(1 for j in jobs if j.get("confidence") == "low")
    social_c = sum(1 for j in jobs if j.get("source_type") == "social")
    platforms = sorted(set(j.get("platform","?") for j in jobs))

    lines = [
        header,
        f"📅 {tg_escape(now)}",
        f"🆕 *{len(jobs)} new relevant jobs*",
        f"🤖 6\\-model ensemble  \\|  🔀 Kimi\\-K2\\.6 fusion",
        f"🟢 {high_c} high  🟡 {medium_c} medium  🟠 {low_c} low",
    ]
    if social_c:
        lines.append(f"📢 {social_c} community\\-sourced \\(verify details\\)")
    if platforms:
        plat_str = tg_escape(" · ".join(platforms[:6]))
        lines.append(f"📡 {plat_str}")
    lines.append("")

    TIER_LABELS = {1: "🏆 *Tier 1 — Top BD Tech*", 2: "⭐ *Tier 2 — BD Tech*", 3: "📋 *Job Boards & Community*"}
    CONF_BADGE  = {"high": "🟢", "medium": "🟡", "low": "🟠", "none": "⚪"}

    sorted_jobs = sorted(
        jobs,
        key=lambda x: (x.get("tier",3), -x.get("model_agreement",0), -x.get("final_score",0)),
    )

    current_tier = None
    for j in sorted_jobs:
        t = j.get("tier", 3)
        if t != current_tier:
            lines.append(f"\n{TIER_LABELS.get(t, '📋 *Other*')}")
            current_tier = t

        agreement   = j.get("model_agreement", 0)
        final_score = round(j.get("final_score", j.get("relevance_score", 0)), 1)
        confidence  = j.get("confidence", "low")
        why         = j.get("why_relevant", "")
        note        = j.get("apply_note", "")
        remote      = j.get("remote", False)
        source      = j.get("source_type", "")

        conf_badge = CONF_BADGE.get(confidence, "⚪")
        agree_bar  = "●" * min(agreement, 6) + "○" * max(0, 6 - agreement)
        location   = "🌐 Remote" if remote else "📍 Bangladesh"
        src_badge  = "📢 " if source == "social" else ""

        card = (
            f"\n━━━━━━━━━━━━━━\n"
            f"🏢 *{tg_escape(j.get('company','Unknown'))}*\n"
            f"💼 {src_badge}{tg_escape(j.get('title','Unknown'))}\n"
            f"⭐ {tg_escape(str(final_score))}/10  "
            f"{conf_badge} {tg_escape(confidence)}  "
            f"\\[{agree_bar}\\] {agreement}/6\n"
            f"{tg_escape(location)}  \\|  {tg_escape(j.get('platform',''))}\n"
        )
        if why:
            card += f"💡 _{tg_escape(why)}_\n"
        if note:
            card += f"📌 _{tg_escape(note)}_\n"
        card += f"🔗 [Apply Here]({j.get('url','')})"
        lines.append(card)

    # Eyasir's profile links in footer
    lines.append(
        f"\n\n👤 [LinkedIn](https://www.linkedin.com/in/eyasir329/)  "
        f"\\|  [GitHub](https://github.com/eyasir329)  "
        f"\\|  [Facebook](https://www.facebook.com/eyasir329)\n"
        f"_Powered by: Kimi\\-K2\\.6 \\+ Qwen3\\.5\\-397B \\+ "
        f"Nemotron\\-120B \\+ Nemotron\\-49B \\+ Llama\\-4 \\+ Mistral\\-119B_"
    )

    if not jobs:
        return "✅ No new jobs since last check\\. I'll notify you tomorrow\\!"

    return "\n".join(lines)
```

### 6.9 send_telegram

Identical to existing `job-search` skill's `send_telegram()`. Copy verbatim:
- Split at 4000 chars
- Retry 3× with exponential backoff (2s/4s/8s)
- parse_mode: MarkdownV2

### 6.10 run_job_searchs (main orchestrator)

```python
async def run_job_searchs(trigger: str = "command", args: list = None) -> list[dict]:
    """
    Full pipeline:
      1. Load config
      2. Init DB
      3. Announce to Telegram (unless silent)
      4. Scrape all sources concurrently (asyncio.gather)
      5. Deduplicate vs seen_jobs
      6. Ensemble score + fuse in batches of 20
      7. Persist + log
      8. Format + send Telegram message

    Concurrency breakdown:
      - All 30 career pages: concurrent
      - All 16 BDJobs keywords: concurrent (with 0.5s internal sleep each)
      - BDTechJobs: concurrent
      - All 8 LinkedIn searches: concurrent (with 2-5s internal sleep each)
      - All 5 Indeed searches: concurrent (with 1-2s internal sleep each)
      - All 2 Glassdoor searches: concurrent (with 1.5-3s internal sleep each)
      - All 4 Facebook groups: concurrent (with 3-5s internal sleep each)
      - Twitter/X: sequential per query (nitter instance found first)

    Everything runs inside asyncio.gather — total scraping wall-clock ≈ 15-30s.
    """
    args       = args or []
    tier1_only = "tier1" in args
    fresh      = "fresh" in args
    silent     = "silent" in args

    token, chat_id, nim_key = load_openclaw_config()
    conn       = init_db()
    wall_start = time.time()

    if fresh:
        conn.execute("DELETE FROM seen_jobs")
        conn.commit()
        print("[job-searchs] Cache cleared (fresh mode)")

    connector = aiohttp.TCPConnector(limit=25, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:

        # ── Announce ─────────────────────────────────────────────────────────
        if not silent:
            n_companies = len(TIER1) + (0 if tier1_only else len(TIER2))
            mode        = " \\(Tier 1 only\\)" if tier1_only else ""
            await send_telegram(
                session, token, chat_id,
                f"🔍 Searching {n_companies} companies \\+ LinkedIn \\+ BDJobs \\+ "
                f"BDTechJobs \\+ Indeed \\+ Facebook groups \\+ Twitter/X{mode}\\.\n"
                f"⚙️ 6\\-model NIM ensemble ready\\.\n"
                f"⏱️ Results in \\~4 minutes\\."
            )

        # ── Build all scraper tasks ──────────────────────────────────────────
        print(f"\n[job-searchs] Launching all scrapers concurrently...")
        tasks = []

        companies = (
            [{**co, "tier": 1} for co in TIER1]
            + ([] if tier1_only else [{**co, "tier": 2} for co in TIER2])
        )
        for co in companies:
            tasks.append(scrape_career_page(session, co))

        if not tier1_only:
            for kw in BDJOBS_KEYWORDS:
                tasks.append(scrape_bdjobs(session, kw))
            tasks.append(scrape_bdtechjobs(session))
            for li_url in LINKEDIN_SEARCHES:
                tasks.append(scrape_linkedin(session, li_url))
            for ind_url in INDEED_SEARCHES:
                tasks.append(scrape_indeed(session, ind_url))
            for gd_url in GLASSDOOR_SEARCHES:
                tasks.append(scrape_glassdoor(session, gd_url))
            for group in FACEBOOK_GROUPS:
                tasks.append(scrape_facebook_group(session, group))
            tasks.append(scrape_twitter_jobs(session))

        raw = await asyncio.gather(*tasks, return_exceptions=True)

        # ── Flatten + deduplicate ────────────────────────────────────────────
        all_jobs: list[dict] = []
        platforms_hit: dict[str, int] = defaultdict(int)
        for r in raw:
            if isinstance(r, list):
                for j in r:
                    all_jobs.append(j)
                    platforms_hit[j.get("platform","?")] += 1

        new_jobs: list[dict] = []
        for j in all_jobs:
            uid  = job_uid(j["title"], j["company"], j["url"])
            j["id"] = uid
            if not is_seen(conn, uid):
                new_jobs.append(j)

        print(f"[job-searchs] Scraped: {len(all_jobs)} total | {len(new_jobs)} new")
        for plat, count in sorted(platforms_hit.items(), key=lambda x: -x[1]):
            print(f"             {plat}: {count}")

        if not new_jobs:
            run_id = log_run(conn, trigger, len(all_jobs), 0, 0, 0, time.time()-wall_start, dict(platforms_hit))
            conn.close()
            if not silent:
                await send_telegram(session, token, chat_id,
                    "✅ No new jobs since last check\\. I'll notify you tomorrow\\!")
            return []

        # ── Ensemble filter in batches of 20 ────────────────────────────────
        filtered: list[dict] = []
        batches = [new_jobs[i:i+20] for i in range(0, len(new_jobs), 20)]
        for i, batch in enumerate(batches):
            print(f"[job-searchs] Ensemble batch {i+1}/{len(batches)}: {len(batch)} jobs")
            result = await filter_with_ensemble(session, batch, nim_key)
            filtered.extend(result)
            if i < len(batches) - 1:
                await asyncio.sleep(2)

        # ── Persist + log ────────────────────────────────────────────────────
        for j in filtered:
            mark_seen(conn, j)
        duration = time.time() - wall_start
        log_run(conn, trigger, len(all_jobs), len(new_jobs), len(filtered),
                len(ENSEMBLE_MODELS), duration, dict(platforms_hit))
        conn.close()
        print(f"[job-searchs] Done: {len(filtered)} relevant jobs in {duration:.1f}s")

        # ── Send ─────────────────────────────────────────────────────────────
        if not silent:
            if filtered:
                msg = format_jobs(filtered, trigger)
                await send_telegram(session, token, chat_id, msg)
            else:
                await send_telegram(session, token, chat_id,
                    "✅ Jobs scraped but none passed ensemble filter\\.\n"
                    "Try `/job_searchs_fresh` to reset cache\\.")

    return filtered
```

### 6.11 Weekly summary, scheduler, entry point

```python
async def send_weekly_summary():
    """Send weekly digest of stats + top companies."""
    token, chat_id, _ = load_openclaw_config()
    conn  = init_db()
    stats = get_weekly_stats(conn)
    top_companies = conn.execute("""
        SELECT company, COUNT(*) as n
        FROM seen_jobs
        WHERE found_at >= datetime('now', '-7 days')
        GROUP BY company ORDER BY n DESC LIMIT 5
    """).fetchall()
    conn.close()

    co_lines = "\n".join(
        f"  {i+1}\\. {tg_escape(row[0])}: {row[1]} jobs"
        for i, row in enumerate(top_companies)
    )
    connector = aiohttp.TCPConnector()
    async with aiohttp.ClientSession(connector=connector) as session:
        await send_telegram(session, token, chat_id,
            f"📊 *Weekly Job Summary*\n"
            f"Jobs found: *{stats.get('total_jobs', 0)}* across "
            f"*{stats.get('companies', 0)}* companies, "
            f"*{stats.get('platforms', 0)}* platforms\n"
            f"Tier 1 jobs: *{stats.get('tier1_jobs', 0)}*  \\|  "
            f"Social posts: *{stats.get('social_jobs', 0)}*\n\n"
            f"*Top companies this week:*\n{co_lines}\n\n"
            f"Use `/job_searchs_fresh` to reset cache and see all current openings\\."
        )


async def start_scheduler():
    scheduler = AsyncIOScheduler(timezone=DHAKA_TZ)
    scheduler.add_job(
        lambda: asyncio.create_task(run_job_searchs(trigger="scheduler")),
        "cron", hour=9, minute=0, id="daily_digest", replace_existing=True,
    )
    scheduler.add_job(
        lambda: asyncio.create_task(send_weekly_summary()),
        "cron", day_of_week="sun", hour=9, minute=5, id="weekly_summary", replace_existing=True,
    )
    scheduler.start()
    next_run = scheduler.get_job("daily_digest").next_run_time
    print(f"[scheduler] Daily: 09:00 Asia/Dhaka (next: {next_run})")
    print(f"[scheduler] Weekly summary: Sunday 09:05 Asia/Dhaka")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--schedule" in argv:
        asyncio.run(start_scheduler())
    elif "--test" in argv:
        async def _test():
            connector = aiohttp.TCPConnector(limit=10)
            async with aiohttp.ClientSession(connector=connector) as session:
                print("=== Smoke test: 3 career pages + BDJobs + Facebook + Twitter ===")
                for co in TIER1[:3]:
                    jobs = await scrape_career_page(session, {**co, "tier": 1})
                    print(f"  {co['name']}: {len(jobs)} jobs")
                bdjobs = await scrape_bdjobs(session, "software engineer")
                print(f"  BDJobs 'software engineer': {len(bdjobs)}")
                fb = await scrape_facebook_group(session, FACEBOOK_GROUPS[0])
                print(f"  Facebook '{FACEBOOK_GROUPS[0]['name']}': {len(fb)} posts")
                tw = await scrape_twitter_jobs(session)
                print(f"  Twitter/X: {len(tw)} job tweets")
        asyncio.run(_test())
    elif "weekly" in argv:
        asyncio.run(send_weekly_summary())
    else:
        asyncio.run(run_job_searchs(trigger="command", args=argv))
```

---

## STEP 7 — REGISTER IN openclaw.json

After creating files, run this Python to add the skill to config:

```python
import json
from pathlib import Path

cfg_path = Path.home() / ".openclaw/openclaw.json"
with open(cfg_path) as f:
    cfg = json.load(f)

cfg.setdefault("skills", {})["job-searchs"] = {
    "description": (
        "Full BD CSE job search — 30 companies + LinkedIn + BDJobs + Indeed + "
        "Facebook groups + Twitter/X. 6-model NIM ensemble + Kimi-K2.6 fusion."
    ),
    "executor": "python3",
    "script":   "/workspaces/openclaw-lab/skills/job-searchs/job_searchs.py",
    "schedule": "0 9 * * *",
    "timezone": "Asia/Dhaka",
}

with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2)

print("Registered: skills.job-searchs")
```

---

## STEP 8 — REGISTER TELEGRAM SLASH COMMANDS

```bash
BOT_TOKEN=$(python3 -c "
import json
from pathlib import Path
print(json.load(open(Path.home() / '.openclaw/openclaw.json'))['channels']['telegram']['botToken'])
")

curl -s "https://api.telegram.org/bot${BOT_TOKEN}/setMyCommands" \
  -H "Content-Type: application/json" \
  -d '{
    "commands": [
      {"command": "job_searchs",       "description": "Full CSE job search BD — 30 companies + 8 platforms (~4min)"},
      {"command": "job_searchs_tier1", "description": "Top 12 companies only, no job boards (~60s)"},
      {"command": "job_searchs_fresh", "description": "Clear cache + full search (see all current jobs)"},
      {"command": "job_searchs_weekly","description": "Weekly summary — jobs found this week"}
    ]
  }'
```

---

## STEP 9 — INSTALL DEPENDENCIES

```bash
pip install aiohttp==3.9.5 beautifulsoup4==4.12.3 lxml==5.2.2 \
            apscheduler==3.10.4 fake-useragent==1.5.1

# Playwright (optional, for JS-heavy pages — install if needed)
pip install playwright==1.44.0
python -m playwright install chromium --with-deps
```

---

## STEP 10 — TEST & LAUNCH

```bash
# 1. Syntax check
python3 -c "import ast; ast.parse(open('skills/job-searchs/job_searchs.py').read()); print('Syntax OK')"

# 2. Smoke test (no AI, no Telegram)
python3 skills/job-searchs/job_searchs.py --test

# 3. Register Telegram slash commands (Step 8 above)

# 4. On-demand test (full run — sends to Telegram)
python3 skills/job-searchs/job_searchs.py tier1

# 5. Start scheduler in tmux window (runs alongside OpenClaw gateway)
tmux new-window -n job-searchs
cd /workspaces/openclaw-lab
python3 skills/job-searchs/job_searchs.py --schedule
```

---

## QUALITY CHECKLIST

Before finishing, verify each item:

- [ ] `SKILL.md` format exactly matches `skills/caveman/SKILL.md` (YAML frontmatter)
- [ ] All 12 Tier 1 + 18 Tier 2 companies present with correct URLs
- [ ] All 6 ENSEMBLE_MODELS present with correct NIM model IDs
- [ ] `FUSION_MODEL = "moonshotai/kimi-k2.6"`
- [ ] `load_openclaw_config()` reads from `~/.openclaw/openclaw.json` only
- [ ] `NVIDIA_API_KEY` from `os.environ` only — never hardcoded
- [ ] DB at `data/job_searchs.db` (separate from existing `job_search.db`)
- [ ] All scrapers use `asyncio.gather` — truly concurrent
- [ ] `scrape_facebook_group()` handles login wall gracefully (returns [])
- [ ] `scrape_twitter_jobs()` tries all nitter instances, skips if all down
- [ ] `_extract_job_title_from_text()` and `_extract_company_from_text()` implemented
- [ ] `local_fusion()` applies -0.5 penalty to social-source jobs with agreement < 3
- [ ] `format_jobs()` shows 📢 badge on social-source jobs
- [ ] `format_jobs()` includes Eyasir's LinkedIn/GitHub/Facebook links in footer
- [ ] Telegram messages split at 4000 chars
- [ ] `--test` mode works with zero API calls
- [ ] `--schedule` keeps running indefinitely (asyncio.sleep loop)
- [ ] `skills.job-searchs` registered in `~/.openclaw/openclaw.json`
- [ ] Telegram slash commands registered via curl
- [ ] `requirements.txt` lists all pip imports used

---

## PLATFORM COVERAGE SUMMARY

| Platform | Type | Count | Notes |
|----------|------|-------|-------|
| Career Pages | Direct | 52 companies | Tier 1 (12) + Tier 2 (40) |
| BDJobs | Job board | 16 keyword searches | IT/Telecom category |
| BDTechJobs | Job board | 1 page | All tech listings |
| LinkedIn | Job board | 8 searches | Last 7 days, Bangladesh |
| Indeed BD | Job board | 5 searches | Last 7 days |
| Glassdoor | Job board | 2 searches | BD tech focus |
| Facebook Groups | Social | 4 groups | mbasic.facebook.com |
| Twitter/X | Social | 10 queries | Via Nitter (no API) |

**Total sources: 8 platforms, 52 companies, 46 search queries — all concurrent**

---

## MODEL ENSEMBLE SUMMARY

| Tier | Model | Weight | Timeout | Role |
|------|-------|--------|---------|------|
| S | kimi-k2.6 (1T/32B active) | 2.0 | 180s | #1 open-weights + fusion model |
| S | qwen3.5-397b (397B/17B active) | 1.8 | 150s | SOTA reasoning, Bengali-aware |
| A | nemotron-super-120b | 1.5 | 120s | Best structured JSON on NIM |
| A | nemotron-super-49b-v1.5 | 1.4 | 90s | Reasoning + RAG specialist |
| B | llama4-maverick (1M ctx) | 1.0 | 30s | ~0.2s latency, never bottleneck |
| B | mistral-small-119b | 1.0 | 60s | Architecture diversity |

Fusion: Kimi-K2.6 reads all 6 outputs at `temperature=0.0` (fully deterministic).
Fallback: `local_fusion()` — pure Python, zero API dependency — system never crashes.
