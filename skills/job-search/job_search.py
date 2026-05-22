#!/usr/bin/env python3
"""
OpenClaw Skill: job-search

Full-stack BD CSE job search for Eyasir (eyasir329).

Sources (all concurrent):
  Career pages : 30 BD tech companies (12 Tier-1 + 18 Tier-2)
  BDJobs       : 16 keyword searches in IT/Telecom category
  BDTechJobs   : all tech listings
  LinkedIn     : 8 public search URLs (last 7 days, Bangladesh)
  Indeed BD    : 5 keyword searches
  Glassdoor    : 2 BD tech searches
  Facebook     : 4 groups via mbasic.facebook.com (no JS, public only)
  Twitter/X    : 10 queries via Nitter (open-source frontend, no API key)

Scoring  : 6-model NVIDIA NIM parallel ensemble (all models simultaneously)
Fusion   : Kimi-K2.6 at temperature=0 (deterministic)
Fallback : local_fusion() — pure Python, zero API dependency
DB       : data/job_search.db
Bot      : @oc_lab329_bot via Telegram MarkdownV2

CLI:
  python job_search.py               → on-demand full search
  python job_search.py tier1         → Tier 1 only (~60s)
  python job_search.py fresh         → clear cache + full search
  python job_search.py weekly        → send weekly summary only
  python job_search.py --schedule    → start daily scheduler (blocking)
  python job_search.py --test        → scraper smoke test, no AI/Telegram
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
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, quote_plus, urlparse, parse_qs, unquote
from zoneinfo import ZoneInfo

import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bs4 import BeautifulSoup

# ── Common Telegram utilities ──────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
from common.tg import (  # noqa: E402
    load_config as _load_config_from_common,
    tg_escape as _tg_escape_common,
    send_telegram as _send_telegram_common,
    conf_bar, Card,
)

# ── User-agent helpers ─────────────────────────────────────────────────────────
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


# ── Runtime paths ──────────────────────────────────────────────────────────────
OPENCLAW_CONFIG = Path.home() / ".openclaw/openclaw.json"
DB_PATH         = Path(__file__).parent / "../../data/job_search.db"
DHAKA_TZ        = ZoneInfo("Asia/Dhaka")
NIM_ENDPOINT    = "https://integrate.api.nvidia.com/v1/chat/completions"

# Anchor keywords for identifying job links on career pages
JOB_LINK_KEYWORDS = frozenset({
    "engineer", "developer", "intern", "trainee", "analyst", "scientist",
    "devops", "architect", "lead", "researcher", "qa", "tester", "programmer",
    "associate", "junior", "graduate", "backend", "frontend", "fullstack",
    "machine learning", "deep learning", "data engineer", "sre",
})

# Keywords for detecting job-related social posts
JOB_POST_KEYWORDS = frozenset({
    "hiring", "we are looking", "job opening", "job opportunity",
    "vacancy", "position available", "apply now", "join our team",
    "internship", "intern opening", "trainee", "fresh graduate",
    "recruitment", "career opportunity", "open position",
    "we're hiring", "software engineer", "developer wanted",
    "cse graduate", "looking for", "job circular", "career",
})


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

def load_openclaw_config() -> tuple[str, str, str]:
    return _load_config_from_common()


# ══════════════════════════════════════════════════════════════════════════════
# USER PROFILE
# ══════════════════════════════════════════════════════════════════════════════

USER = {
    "name":    "Eyasir",
    "degree":  "BSc Computer Science & Engineering",
    "linkedin": "https://www.linkedin.com/in/eyasir329/",
    "github":   "https://github.com/eyasir329",
    "facebook": "https://www.facebook.com/eyasir329",
    "target_roles": [
        "Software Engineer", "Junior Software Engineer",
        "Associate Software Engineer", "Software Developer",
        "Backend Developer", "Frontend Developer", "Full-Stack Developer",
        "AI Engineer", "ML Engineer", "Machine Learning Engineer",
        "Deep Learning Engineer", "Data Engineer", "Data Scientist",
        "Research Engineer", "DevOps Engineer", "Site Reliability Engineer",
        "QA Engineer", "Software Engineer Intern", "Software Developer Intern",
        "Trainee Software Engineer", "Graduate Trainee", "Junior Developer",
        "Management Trainee (Tech Track)",
    ],
    "exclude_roles": [
        "HR", "Human Resources", "Finance", "Accounts", "Sales",
        "Marketing", "Admin", "Administrative", "Procurement",
        "Legal", "Logistics", "Customer Service", "Business Development",
        "Receptionist", "Driver", "Cashier", "Operations Manager",
    ],
    "skills_summary": (
        "C++, Python, JavaScript/TypeScript, React, Node.js, SQL, "
        "competitive programming, algorithms & data structures, "
        "machine learning fundamentals, system design basics"
    ),
    "location":         "Bangladesh",
    "preferred_cities": ["Dhaka", "Chittagong"],
    "accept_remote":    True,
}


# ══════════════════════════════════════════════════════════════════════════════
# COMPANY & PLATFORM CONFIG
# ══════════════════════════════════════════════════════════════════════════════

TIER1 = [
    {
        "name": "Brain Station 23",
        "url":  "https://erp.bs-23.com/jobs",
        "extra_urls": [
            "https://brainstation-23.com/career/",
            "https://www.linkedin.com/company/brain-station-23-plc/jobs/",
        ],
    },
    {
        "name":   "Enosis Solutions",
        "url":    "https://enosisbd.pinpointhq.com/",
        "remote": True,
        "extra_urls": [
            "https://www.linkedin.com/company/enosis-solutions/jobs/",
        ],
    },
    {
        "name": "Samsung R&D Bangladesh",
        "url":  "https://research.samsung.com/srbd",
        "extra_urls": [
            "https://www.linkedin.com/company/samsung-bangladesh/jobs/",
        ],
    },
    {
        "name": "Cefalo Bangladesh",
        "url":  "https://cefalo.com/en/jobs/",
        "extra_urls": [
            "https://www.linkedin.com/company/cefalo-bangladesh-ltd-/jobs/",
        ],
    },
    {
        "name": "Therap BD",
        "url":  "https://therap.hire.trakstar.com/jobs/fk0hw8r",
        "extra_urls": [
            "https://www.linkedin.com/company/therap-services/jobs/",
        ],
    },
    {
        "name": "BJIT Group",
        "url":  "https://bjitgroup.com/career",
        "extra_urls": [
            "https://www.linkedin.com/company/bjit/jobs/",
        ],
    },
    {
        "name": "Pathao",
        "url":  "https://careers.pathao.com/jobs/",
        "extra_urls": [
            "https://www.linkedin.com/company/pathao/jobs/",
            "https://mbasic.facebook.com/PathaoCareers",
        ],
    },
    {
        "name": "Optimizely",
        "url":  "https://www.optimizely.com/company/career/",
        "extra_urls": [
            "https://www.linkedin.com/company/optimizely/jobs/",
        ],
    },
    {
        "name": "bKash",
        "url":  "https://www.bkash.com/bn/careers",
        "extra_urls": [
            "https://www.linkedin.com/company/bkash-limited/jobs/",
        ],
    },
    {
        "name": "Viva Soft",
        "url":  "https://www.vivasoftltd.com/career/",
        "extra_urls": [
            "https://vivasoft.com.bd/career",
            "https://www.linkedin.com/company/vivasoft-ltd/jobs/",
        ],
    },
    {
        "name": "Shikho",
        "url":  "https://shikho.com/careers",
        "extra_urls": [
            "https://www.linkedin.com/company/shikhobangladesh/jobs/",
        ],
    },
    {
        "name": "10 Minute School",
        "url":  "https://10minuteschool.com/careers",
        "extra_urls": [
            "https://www.linkedin.com/company/10-minute-school/jobs/",
        ],
    },
]

TIER2 = [
    {"name": "Augmedix Bangladesh",
     "url":  "https://www.augmedix.com/careers/",
     "extra_urls": ["https://www.linkedin.com/company/augmedix/jobs/"]},

    {"name": "TigerIT Bangladesh",
     "url":  "https://www.tigerit.com/",
     "extra_urls": ["https://www.linkedin.com/company/tiger-it-bangladesh-ltd-/jobs/"]},

    {"name": "SELISE Digital",
     "url":  "https://selisegroup.com/join-the-team/",
     "extra_urls": ["https://selise.ch/careers/",
                    "https://www.linkedin.com/company/selise-digital-platforms/jobs/"]},

    {"name": "DataSoft Systems",
     "url":  "http://datasoft-bd.com/career/",
     "extra_urls": ["https://www.linkedin.com/company/datasoft-systems/jobs/"]},

    {"name": "ReliSource Technologies",
     "url":  "https://www.relisource.com/careers/",
     "extra_urls": ["https://www.linkedin.com/company/relisource/jobs/"]},

    {"name": "Shohoz",
     "url":  "https://www.shohoz.com/career",
     "extra_urls": ["https://www.linkedin.com/company/shohoz/jobs/"]},

    {"name": "Grameenphone",
     "url":  "https://www.grameenphone.com/about/career",
     "extra_urls": ["https://www.linkedin.com/company/grameenphone/jobs/"]},

    {"name": "Robi Axiata",
     "url":  "https://www.robi.com.bd/en/corporate/career",
     "extra_urls": ["https://www.linkedin.com/company/robi-axiata-limited/jobs/"]},

    {"name": "Kaz Software",
     "url":  "https://kazsoftware.com/career/",
     "extra_urls": ["https://www.linkedin.com/company/kaz-software/jobs/"]},

    {"name": "Shajgoj",
     "url":  "https://shajgoj.com/careers",
     "extra_urls": ["https://www.linkedin.com/company/shajgoj/jobs/"]},

    {"name": "Field Nation",
     "url":  "https://careers.fieldnation.com/",
     "extra_urls": ["https://www.linkedin.com/company/fieldnation/jobs/"]},

    {"name": "Impulse BD",
     "url":  "https://www.impulsebdltd.com/career",
     "extra_urls": ["https://www.linkedin.com/company/impulse-ltd/jobs/"]},

    {"name": "Chaldal",
     "url":  "https://chaldal.com/careers",
     "extra_urls": ["https://www.linkedin.com/company/chaldal-com/jobs/"]},

    {"name": "Chaldal Engineering",
     "url":  "https://chaldal.tech/freshgrad.html"},

    {"name": "SSL Wireless",
     "url":  "https://www.sslwireless.com/career",
     "extra_urls": ["https://www.linkedin.com/company/ssl-wireless/jobs/"]},

    {"name": "Synesis IT",
     "url":  "https://synesisit.com.bd/career/",
     "extra_urls": ["https://www.linkedin.com/company/synesis-it/jobs/"]},

    {"name": "Nascenia",
     "url":  "https://www.nascenia.com/career/",
     "extra_urls": ["https://www.linkedin.com/company/nascenia/jobs/"]},

    {"name": "Dohatec",
     "url":  "https://www.dohatec-bd.com/career",
     "extra_urls": ["https://www.linkedin.com/company/dohatec-ca-limited/jobs/"]},

    {"name": "Backspace Tech",
     "url":  "https://backspace.com.bd/career",
     "extra_urls": ["https://www.linkedin.com/company/backspacetech/jobs/"]},

    # ── Added from community list ────────────────────────────────────────────
    {"name": "WellDev",
     "url":  "https://recruitment.welldev.io/public/jobs/db88764e-b85f-4f7f-b59f-61e5c77c3e77"},

    {"name": "Fifty-Two Digital",
     "url":  "https://fiftytwodigital.com/career/"},

    {"name": "Bit Mascot",
     "url":  "https://www.bitmascot.com/careers/"},

    {"name": "Inverse.AI",
     "url":  "https://inverseai.com/career"},

    {"name": "Kona Software Lab",
     "url":  "https://konasl.com/life-at-konasl/career-journey/"},

    {"name": "Shell Be Haken",
     "url":  "https://shellbeehaken.com/join-us"},

    {"name": "Kinetik",
     "url":  "https://boards.greenhouse.io/kinetik"},

    {"name": "BroTecs",
     "url":  "https://www.brotecs.com/job-openings/"},

    {"name": "Spring Rain",
     "url":  "https://springrain.io/careers/"},

    {"name": "BRAC IT",
     "url":  "https://www.bracits.com/career",
     "extra_urls": ["https://www.linkedin.com/company/brac-it-services-limited/jobs/"]},

    {"name": "IBOS",
     "url":  "https://ibos.io/career/"},

    {"name": "Dynamic Solutions Innovator",
     "url":  "https://apply.workable.com/dsinnovators/"},

    {"name": "ShopUp",
     "url":  "https://careers.smartrecruiters.com/ShopUp"},

    {"name": "Kite Games",
     "url":  "https://www.kitegamesstudio.com/#career"},

    {"name": "AppsCode",
     "url":  "https://appscode.com/"},

    {"name": "Streams Tech",
     "url":  "https://streamstech.com/"},

    {"name": "SouthTech Group",
     "url":  "https://career.southtechgroup.com/"},

    {"name": "LeadSoft",
     "url":  "https://leadsoft.com.bd/"},

    {"name": "ReveSoft",
     "url":  "https://www.revesoft.com/careers"},

    {"name": "Tekarsh",
     "url":  "https://tekarsh.com/"},

    {"name": "Muslim Pro",
     "url":  "https://career.muslimpro.com/careers/"},
]

BDJOBS_KEYWORDS = [
    "software engineer", "junior software engineer", "associate software engineer",
    "machine learning engineer", "ai engineer", "software developer intern",
    "trainee software engineer", "graduate trainee it", "backend developer",
    "full stack developer", "data engineer", "devops engineer",
    "junior developer", "react developer", "python developer", "node js developer",
]

BDTECHJOBS_URL = "https://www.bdtechjobs.com/jobs"

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

INDEED_SEARCHES = [
    "https://bd.indeed.com/jobs?q=software+engineer&l=Dhaka&fromage=7",
    "https://bd.indeed.com/jobs?q=machine+learning+engineer&l=Bangladesh&fromage=7",
    "https://bd.indeed.com/jobs?q=software+intern&l=Dhaka&fromage=7",
    "https://bd.indeed.com/jobs?q=junior+developer&l=Bangladesh&fromage=7",
    "https://bd.indeed.com/jobs?q=trainee+engineer&l=Bangladesh&fromage=7",
]

GLASSDOOR_SEARCHES = [
    "https://www.glassdoor.com/Job/bangladesh-software-engineer-jobs-SRCH_IL.0,10_IN17_KO11,28.htm",
    "https://www.glassdoor.com/Job/bangladesh-machine-learning-jobs-SRCH_IL.0,10_IN17_KO11,31.htm",
]

# Public Facebook groups that post BD tech jobs (scraped via mbasic)
FACEBOOK_GROUPS = [
    {
        "name":  "BD Software Jobs",
        "gid":   "781773098552968",
        "url":   "https://mbasic.facebook.com/groups/781773098552968/",
    },
    {
        "name":  "BD Contest Programmers",
        "gid":   "bd.contest.programmers",
        "url":   "https://mbasic.facebook.com/groups/bd.contest.programmers/",
    },
    {
        "name":  "Bangladesh Software Engineers",
        "gid":   "BangladeshSoftwareEngineers",
        "url":   "https://mbasic.facebook.com/groups/BangladeshSoftwareEngineers/",
    },
    {
        "name":  "CSE Jobs Bangladesh",
        "gid":   "csejobsbangladesh",
        "url":   "https://mbasic.facebook.com/groups/csejobsbangladesh/",
    },
]

# Nitter instances (open-source Twitter frontend — no API key)
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.cz",
]

TWITTER_QUERIES = [
    "#BDtechjobs",
    "#SWEjobsBD",
    "#CSEjobsBD",
    "hiring Bangladesh software engineer",
    "hiring Bangladesh intern developer",
    "internship Bangladesh CSE",
    "software engineer job Bangladesh",
    "#BrainStation23 hiring",
    "#bKash hiring",
    "#Pathao hiring",
]

# Known BD company names for heuristic extraction from social posts
KNOWN_BD_COMPANIES = [
    "Brain Station 23", "Enosis", "Samsung R&D", "Viva Soft", "Vivasoft", "Cefalo",
    "Therap", "BJIT", "Pathao", "bKash", "Optimizely", "Shikho",
    "10 Minute School", "Augmedix", "TigerIT", "SELISE", "DataSoft",
    "ReliSource", "Shohoz", "Grameenphone", "Robi", "Kaz Software",
    "Shajgoj", "Field Nation", "Impulse", "Chaldal", "SSL Wireless",
    "Synesis IT", "Nascenia", "Dohatec", "Backspace Tech",
    "WellDev", "Fifty-Two Digital", "Bit Mascot", "Inverse.AI", "InverseAI",
    "Kona Software", "Shell Be Haken", "Kinetik", "BroTecs", "Spring Rain",
    "BRAC IT", "BRACITS", "IBOS", "Dynamic Solutions Innovator", "DSI",
    "ShopUp", "Kite Games", "AppsCode", "Streams Tech", "SouthTech",
    "LeadSoft", "ReveSoft", "Tekarsh", "Muslim Pro",
    "Dream71", "WPXPO", "Orbitax", "Era Infotech",
]


# ══════════════════════════════════════════════════════════════════════════════
# ENSEMBLE CONFIG & PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

ENSEMBLE_MODELS = [
    # Tier S — maximum intelligence; kimi-k2.6 also serves as fusion model
    {"id": "moonshotai/kimi-k2.6",                     "label": "kimi-k2.6",          "tier": "S", "weight": 2.0, "timeout": 180},
    {"id": "qwen/qwen3.5-397b-a17b",                   "label": "qwen3.5-397b",        "tier": "S", "weight": 1.8, "timeout": 150},
    # Tier A — structured JSON specialists
    {"id": "nvidia/nemotron-3-super-120b-a12b",        "label": "nemotron-super-120b", "tier": "A", "weight": 1.5, "timeout": 120},
    {"id": "nvidia/llama-3.3-nemotron-super-49b-v1.5", "label": "nemotron-super-49b",  "tier": "A", "weight": 1.4, "timeout": 90},
    # Tier B — fast, architecturally diverse
    {"id": "meta/llama-4-maverick-17b-128e-instruct",  "label": "llama4-maverick",     "tier": "B", "weight": 1.0, "timeout": 30},
    {"id": "mistralai/mistral-small-4-119b-2603",      "label": "mistral-small-119b",  "tier": "B", "weight": 1.0, "timeout": 60},
]

FUSION_MODEL   = "moonshotai/kimi-k2.6"
FUSION_TIMEOUT = 180

_roles_str   = "\n".join(f"  - {r}" for r in USER["target_roles"])
_exclude_str = ", ".join(USER["exclude_roles"])

SCORER_SYSTEM_PROMPT = f"""You are a precise job relevance scorer for Eyasir, a CSE graduate in Bangladesh.

Profile:
- Degree: {USER['degree']}
- Skills: {USER['skills_summary']}
- LinkedIn: {USER['linkedin']}  GitHub: {USER['github']}
- Location: Bangladesh (Dhaka preferred, remote from BD accepted)

Target roles (include any of these):
{_roles_str}

Exclude non-tech roles — drop if title/department matches:
{_exclude_str}

Instructions:
- Score each job 0-10 for relevance to Eyasir specifically
- Drop jobs with relevance_score < 5
- Social-source jobs (platform contains Facebook or Twitter) may have noisy titles.
  Use the raw_text field if present to understand the actual role before scoring.
- Remote jobs from BD-based companies score same as on-site Dhaka roles.
- Clean up noisy social titles in your output.

Return a JSON array. Each entry MUST have EXACTLY these fields:
{{
  "job_id":          "string — copy exactly from input",
  "title":           "string — cleaned up if from social source",
  "company":         "string",
  "url":             "string",
  "platform":        "string",
  "tier":            1,
  "source_type":     "career_page",
  "relevance_score": 8,
  "why_relevant":    "max 10 words — specific technical reason",
  "remote":          false,
  "apply_note":      "short note for applicant or empty string"
}}

Return ONLY the raw JSON array. No markdown fences. No preamble. No explanation."""

FUSION_SYSTEM_PROMPT = """You are an elite job search result fusion engine for a CSE graduate in Bangladesh.
You receive scored job lists from 6 AI models (each with label, tier, weight).
Produce ONE final ranked list using weighted consensus.

Rules (apply ALL strictly):
1. final_score = weighted average of relevance_score across models that included this job
2. BOOST x1.15 — job in 5 or 6 models
3. BOOST x1.05 — job in 3 or 4 models
4. DROP — only 1 model AND score < 7
5. VETO — kimi-k2.6 OR qwen3.5-397b scored job < 5, drop it regardless
6. Sort: model_agreement DESC, final_score DESC
7. Deduplicate by url — keep highest-scored
8. why_relevant — sharpest explanation across all models
9. apply_note — most useful applicant tip across all models
10. Social-source penalty: if platform contains "Facebook" or "Twitter" AND
    model_agreement < 3, subtract 0.5 from final_score (noisy source, low confidence)

Return ONLY a raw JSON array. Each entry must have exactly:
title, company, url, platform, tier, source_type, final_score (float 0-10),
why_relevant, apply_note, remote, model_agreement (int 1-6),
confidence ("high"/"medium"/"low")

confidence: >=5 = "high", 3-4 = "medium", 1-2 = "low"
No markdown. Raw JSON array only."""


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════════════════

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
            source_type     TEXT    DEFAULT 'unknown',
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
            platforms_hit   TEXT    DEFAULT '{}'
        );
    """)
    conn.commit()
    return conn


def job_uid(title: str, company: str, url: str) -> str:
    """Stable 16-char SHA-256 hash for deduplication."""
    key = f"{title.strip().lower()}{company.strip().lower()}{url.strip()}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def is_seen(conn: sqlite3.Connection, uid: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM seen_jobs WHERE id=?", (uid,)).fetchone())


def mark_seen(conn: sqlite3.Connection, job: dict):
    conn.execute(
        "INSERT OR IGNORE INTO seen_jobs VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
        (
            job["id"], job["title"], job["company"], job["url"],
            job.get("platform"), job.get("tier", 3),
            job.get("final_score", job.get("relevance_score", 5.0)),
            job.get("source_type", "unknown"),
        ),
    )
    conn.commit()


def log_run(
    conn: sqlite3.Connection,
    trigger: str, total: int, new: int, filtered: int,
    models: int, duration: float, platforms: dict,
):
    conn.execute(
        "INSERT INTO search_log "
        "(trigger,total_scraped,new_jobs,filtered_jobs,ensemble_models,duration_secs,platforms_hit) "
        "VALUES (?,?,?,?,?,?,?)",
        (trigger, total, new, filtered, models, round(duration, 1), json.dumps(platforms)),
    )
    conn.commit()


def get_weekly_stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute("""
        SELECT COUNT(*), COUNT(DISTINCT company), COUNT(DISTINCT platform),
               SUM(CASE WHEN tier=1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN source_type='social' THEN 1 ELSE 0 END)
        FROM seen_jobs WHERE found_at >= datetime('now', '-7 days')
    """).fetchone()
    if not row:
        return {}
    return {
        "total_jobs": row[0], "companies": row[1], "platforms": row[2],
        "tier1_jobs": row[3] or 0, "social_jobs": row[4] or 0,
    }


def get_top_companies(conn: sqlite3.Connection, n: int = 5) -> list[tuple]:
    return conn.execute("""
        SELECT company, COUNT(*) FROM seen_jobs
        WHERE found_at >= datetime('now', '-7 days')
        GROUP BY company ORDER BY COUNT(*) DESC LIMIT ?
    """, (n,)).fetchall()


# ══════════════════════════════════════════════════════════════════════════════
# HTTP HELPERS
# ══════════════════════════════════════════════════════════════════════════════

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
    }


async def fetch_html(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict = None,
    timeout: int = 25,
    retries: int = 2,
) -> str | None:
    """
    GET request with retry. Returns HTML string or None.
    Handles 429 with exponential backoff. Never raises.
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
                    print(f"[fetch] 429 on {url[:60]} — waiting {wait}s")
                    await asyncio.sleep(wait)
                    continue
                print(f"[fetch] HTTP {r.status}: {url[:70]}")
                return None
        except asyncio.TimeoutError:
            print(f"[fetch] Timeout ({timeout}s): {url[:60]}")
            return None
        except aiohttp.ClientConnectorError:
            if attempt < retries - 1:
                await asyncio.sleep(1)
                continue
            print(f"[fetch] Connect error: {url[:60]}")
            return None
        except Exception as e:
            print(f"[fetch] {type(e).__name__}: {url[:60]} — {e}")
            return None
    return None


# ══════════════════════════════════════════════════════════════════════════════
# TEXT EXTRACTION HELPERS (for social posts)
# ══════════════════════════════════════════════════════════════════════════════

def extract_job_title(text: str) -> str:
    """Heuristic extraction of job title from social post text."""
    patterns = [
        r"(?:looking for|hiring|position|role|job|vacancy)[:\s]+([A-Za-z\s/&\-]+?)(?:\.|,|\n|at\s)",
        r"((?:software|junior|senior|associate|backend|frontend|full.?stack|ml|ai|data|devops)\s+"
        r"(?:engineer|developer|intern|trainee))[^\n]{0,20}",
        r"(?:intern|trainee)[:\s]+([A-Za-z\s]+?)(?:\.|,|\n|in\s)",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            result = (m.group(1) if m.lastindex else m.group(0)).strip()[:80]
            if result:
                return result
    return text[:80].strip()


def extract_company(text: str) -> str:
    """Heuristic extraction of company name from social post text."""
    text_lower = text.lower()
    for co in KNOWN_BD_COMPANIES:
        if co.lower() in text_lower:
            return co
    patterns = [
        r"(?:at|@|join|company:)\s+([A-Z][A-Za-z0-9\s&\-\.]{2,35}?)(?:\s+is|\s+are|\.|,|\n)",
        r"([A-Z][A-Za-z0-9\s&\-]{2,30}?)\s+(?:is hiring|is looking for|has opening)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            name = m.group(1).strip()
            if 3 <= len(name) <= 50:
                return name
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# SCRAPERS
# ══════════════════════════════════════════════════════════════════════════════

async def _scrape_one_url(
    session: aiohttp.ClientSession,
    base_url: str,
    name: str,
    tier: int,
    remote: bool,
    seen_urls: set,
    cap: int = 15,
) -> list[dict]:
    """Scrape a single career page URL. Shares seen_urls set with caller for cross-URL dedup."""
    html = await fetch_html(session, base_url)
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "lxml")
        jobs: list[dict] = []
        for a in soup.find_all("a", href=True):
            text = a.get_text(" ", strip=True)
            if not any(kw in text.lower() for kw in JOB_LINK_KEYWORDS):
                continue
            href    = a["href"].strip()
            abs_url = urljoin(base_url, href)
            if abs_url in seen_urls or abs_url.rstrip("/") == base_url.rstrip("/"):
                continue
            seen_urls.add(abs_url)
            jobs.append({
                "title":       text[:120],
                "company":     name,
                "url":         abs_url,
                "platform":    "Career Page",
                "tier":        tier,
                "remote":      remote,
                "source_type": "career_page",
            })
            if len(jobs) >= cap:
                break
        return jobs
    except Exception as e:
        print(f"[career] {name} ({base_url[:50]}) parse error: {e}")
        return []


async def scrape_career_page(
    session: aiohttp.ClientSession,
    company: dict,
) -> list[dict]:
    """
    Scrape all career URLs for a company (company["url"] + company["extra_urls"]).
    All URLs scraped concurrently. Results merged and deduplicated. Cap 25 total.
    Returns [] on full failure without blocking other scrapers.
    """
    name   = company["name"]
    tier   = company.get("tier", 2)
    remote = company.get("remote", False)

    all_urls = [company["url"]] + company.get("extra_urls", [])
    seen_urls: set[str] = set()

    results = await asyncio.gather(
        *[_scrape_one_url(session, u, name, tier, remote, seen_urls) for u in all_urls],
        return_exceptions=True,
    )

    jobs: list[dict] = []
    for r in results:
        if isinstance(r, list):
            jobs.extend(r)
            if len(jobs) >= 25:
                jobs = jobs[:25]
                break

    if not jobs:
        print(f"[career] ❓ Unreachable: {name}")
    else:
        src_count = len(all_urls)
        label = f"{src_count} URLs" if src_count > 1 else "1 URL"
        print(f"[career] {name}: {len(jobs)} jobs ({label})")
    return jobs


async def scrape_bdjobs(
    session: aiohttp.ClientSession,
    keyword: str,
) -> list[dict]:
    """BDJobs IT/Telecom (fcat=14) keyword search. 0.5s sleep per request. Cap 20."""
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
                "platform": "BDJobs", "tier": 3,
                "remote": False, "source_type": "job_board",
            })
            if len(jobs) >= 20:
                break
        print(f"[bdjobs] '{keyword}': {len(jobs)}")
        await asyncio.sleep(0.5)
        return jobs
    except Exception as e:
        print(f"[bdjobs] '{keyword}' error: {e}")
        return []


async def scrape_bdtechjobs(session: aiohttp.ClientSession) -> list[dict]:
    """Scrape BDTechJobs all tech listings. Cap 30."""
    html = await fetch_html(session, BDTECHJOBS_URL)
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
            href = urljoin(BDTECHJOBS_URL, a["href"])
            if href in seen or href == BDTECHJOBS_URL:
                continue
            seen.add(href)
            parent = a.find_parent(["div", "li", "article"])
            co_el  = parent.select_one(".company, .org, [class*='company']") if parent else None
            comp   = co_el.get_text(strip=True)[:80] if co_el else "BD Tech Company"
            jobs.append({
                "title": text[:120], "company": comp, "url": href,
                "platform": "BDTechJobs", "tier": 3,
                "remote": False, "source_type": "job_board",
            })
            if len(jobs) >= 30:
                break
        print(f"[bdtechjobs] {len(jobs)}")
        return jobs
    except Exception as e:
        print(f"[bdtechjobs] error: {e}")
        return []


async def scrape_linkedin(
    session: aiohttp.ClientSession,
    search_url: str,
) -> list[dict]:
    """
    LinkedIn public job search. Randomized 2-5s pre-request sleep.
    Returns [] gracefully on any block (expected in cloud environments).
    Strips tracking params from URLs.
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
            print("[linkedin] ⚠️ No cards (rate-limited or CAPTCHA)")
            return []
        kw   = search_url.split("keywords=")[1].split("&")[0] if "keywords=" in search_url else "?"
        jobs = []
        seen: set[str] = set()
        for card in cards[:20]:
            ta = card.select_one(".base-search-card__title, h3, .job-result-card__title")
            ca = card.select_one(".base-search-card__subtitle, h4, .job-result-card__subtitle")
            la = card.select_one("a[href*='linkedin.com/jobs']")
            if not (ta and la):
                continue
            title = ta.get_text(strip=True)[:120]
            comp  = ca.get_text(strip=True)[:80] if ca else "Unknown"
            href  = la["href"].split("?")[0]
            if href in seen:
                continue
            seen.add(href)
            jobs.append({
                "title": title, "company": comp, "url": href,
                "platform": "LinkedIn", "tier": 3,
                "remote": False, "source_type": "job_board",
            })
        print(f"[linkedin] '{kw}': {len(jobs)}")
        return jobs
    except Exception as e:
        print(f"[linkedin] parse error: {e}")
        return []


async def scrape_indeed(
    session: aiohttp.ClientSession,
    search_url: str,
) -> list[dict]:
    """Indeed BD job search. Randomized 1-2s sleep. Cap 20."""
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
        kw   = search_url.split("q=")[1].split("&")[0] if "q=" in search_url else "?"
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
                "platform": "Indeed BD", "tier": 3,
                "remote": False, "source_type": "job_board",
            })
        print(f"[indeed] '{kw}': {len(jobs)}")
        return jobs
    except Exception as e:
        print(f"[indeed] parse error: {e}")
        return []


async def scrape_glassdoor(
    session: aiohttp.ClientSession,
    search_url: str,
) -> list[dict]:
    """Glassdoor BD tech job search. Returns [] gracefully on any block. Cap 15."""
    await asyncio.sleep(random.uniform(1.5, 3.0))
    html = await fetch_html(session, search_url, timeout=30)
    if not html:
        print("[glassdoor] ⚠️ Fetch failed (likely blocked)")
        return []
    try:
        soup  = BeautifulSoup(html, "lxml")
        cards = soup.select("[data-test='jobListing'], .react-job-listing, li[data-id]")
        if not cards:
            print("[glassdoor] ⚠️ No listings (blocked or no results)")
            return []
        jobs = []
        seen: set[str] = set()
        for card in cards[:15]:
            ta = card.select_one("a[data-test='job-link'], a.jobLink, h2 a")
            ca = card.select_one(".employer-name, [class*='EmployerName']")
            if not ta:
                continue
            title = ta.get_text(strip=True)[:120]
            comp  = ca.get_text(strip=True)[:80] if ca else "Unknown"
            href  = ta.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.glassdoor.com" + href
            if href in seen or not href:
                continue
            seen.add(href)
            jobs.append({
                "title": title, "company": comp, "url": href,
                "platform": "Glassdoor", "tier": 3,
                "remote": False, "source_type": "job_board",
            })
        print(f"[glassdoor] {len(jobs)}")
        return jobs
    except Exception as e:
        print(f"[glassdoor] parse error: {e}")
        return []


async def scrape_facebook_group(
    session: aiohttp.ClientSession,
    group: dict,
) -> list[dict]:
    """
    Scrape a Facebook group via mbasic.facebook.com — lightweight interface
    that renders without JavaScript and works for public groups without auth.

    Strategy:
    - Fetch mbasic group page
    - Detect login wall (returns [] if hit)
    - Find post containers, filter for JOB_POST_KEYWORDS
    - Heuristic extraction of company + title from post text
    - Unwrap /l.php?u= encoded external links
    - Cap at 10 posts per group; sleep 3-5s before request
    """
    await asyncio.sleep(random.uniform(3.0, 5.0))
    name = group["name"]
    url  = group["url"]

    html = await fetch_html(session, url, headers=mobile_headers(), timeout=30)
    if not html:
        print(f"[facebook] ⚠️ {name}: fetch failed")
        return []

    soup = BeautifulSoup(html, "lxml")

    # Detect Facebook login wall
    if soup.select_one("#login_form, #loginbutton, input[name='pass']"):
        print(f"[facebook] 🔒 {name}: login required (private group or mbasic blocked)")
        return []

    try:
        jobs = []
        seen: set[str] = set()

        # mbasic renders posts in various container patterns depending on FB version
        containers = (
            soup.select("div[data-ft]") or
            soup.select("div.story_body_container") or
            soup.select("article") or
            []
        )

        # Fallback: scan all divs for job keyword text
        if not containers:
            candidates = [
                tag.find_parent("div")
                for tag in soup.find_all(string=lambda t: t and any(
                    kw in t.lower() for kw in JOB_POST_KEYWORDS
                ))
            ]
            containers = [c for c in candidates if c is not None][:20]

        for container in containers[:30]:
            text = container.get_text(" ", strip=True)
            if not any(kw in text.lower() for kw in JOB_POST_KEYWORDS):
                continue
            if len(text) < 30 or len(text) > 4000:
                continue

            title   = extract_job_title(text)
            company = extract_company(text) or name

            # Unwrap Facebook's /l.php?u= external link encoding
            href = ""
            link = container.find("a", href=True)
            if link:
                raw_href = link["href"]
                if "/l.php?u=" in raw_href:
                    try:
                        qs   = parse_qs(urlparse(raw_href).query)
                        href = unquote(qs.get("u", [""])[0])
                    except Exception:
                        href = raw_href
                elif raw_href.startswith("http"):
                    href = raw_href
                else:
                    href = f"https://www.facebook.com{raw_href}"

            # Fallback URL: synthetic group + hash of post text
            if not href:
                uid  = hashlib.sha256(text[:100].encode()).hexdigest()[:8]
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
                "remote":      "remote" in text.lower(),
                "source_type": "social",
                "raw_text":    text[:500],
            })
            if len(jobs) >= 10:
                break

        print(f"[facebook] {name}: {len(jobs)} job posts")
        return jobs
    except Exception as e:
        print(f"[facebook] {name} parse error: {e}")
        return []


async def _scrape_nitter_query(
    session: aiohttp.ClientSession,
    query: str,
    nitter_base: str,
) -> list[dict]:
    """Single Nitter search query. Returns list of job dicts."""
    url  = f"{nitter_base}/search?q={quote_plus(query)}&f=tweets"
    await asyncio.sleep(random.uniform(0.3, 0.8))
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
        for tw in tweets[:25]:
            ce = tw.select_one(".tweet-content, .tweet-body")
            ae = tw.select_one(".username")
            le = tw.select_one("a.tweet-link, a[href*='/status/']")
            if not ce:
                continue
            text = ce.get_text(" ", strip=True)
            if not any(kw in text.lower() for kw in JOB_POST_KEYWORDS):
                continue
            author = ae.get_text(strip=True) if ae else "@unknown"
            href   = le.get("href", "") if le else ""
            if href and not href.startswith("http"):
                href = f"https://twitter.com{href}"
            if href in seen or not href:
                continue
            seen.add(href)
            title   = extract_job_title(text) or text[:80]
            company = extract_company(text) or f"Twitter/{author}"
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
        return jobs
    except Exception as e:
        print(f"[twitter] parse error for '{query}': {e}")
        return []


async def scrape_twitter_jobs(session: aiohttp.ClientSession) -> list[dict]:
    """
    Search Twitter/X job posts via Nitter (open-source Twitter frontend).
    No API key required. Tries multiple Nitter instances; uses first that responds.
    Returns [] if all instances are down.
    """
    # Find first working Nitter instance
    working = None
    for inst in NITTER_INSTANCES:
        html = await fetch_html(session, inst, timeout=10)
        if html:
            working = inst
            print(f"[twitter] Using Nitter: {inst}")
            break

    if not working:
        print("[twitter] ⚠️ All Nitter instances unreachable — skipping Twitter search")
        return []

    all_jobs: list[dict] = []
    seen_urls: set[str] = set()

    for query in TWITTER_QUERIES:
        jobs = await _scrape_nitter_query(session, query, working)
        for j in jobs:
            if j["url"] not in seen_urls:
                seen_urls.add(j["url"])
                all_jobs.append(j)

    print(f"[twitter] Total: {len(all_jobs)} unique job tweets")
    return all_jobs


# ══════════════════════════════════════════════════════════════════════════════
# WEB SEARCH SCRAPERS  (DuckDuckGo HTML + Bing HTML — no API key needed)
# ══════════════════════════════════════════════════════════════════════════════

# Keywords for general BD tech news (funding, layoffs, new offices, events)
NEWS_KEYWORDS = frozenset({
    "funding", "raises", "series", "expansion", "new office", "layoff",
    "laid off", "acquired", "acquisition", "merger", "launch", "partnership",
    "joins", "appoints", "cto", "ceo", "opens", "headquarter", "tech park",
    "bangladesh startup", "bd tech", "fintech", "edtech", "healthtech",
})

# Per-company search query templates  (use {name} and {year})
_COMPANY_JOB_QUERIES = [
    '"{name}" software engineer jobs Bangladesh {year}',
    '"{name}" hiring developer Bangladesh {year}',
]
_COMPANY_NEWS_QUERIES = [
    '"{name}" Bangladesh news {year}',
]

# General BD tech news — run once per search cycle
BD_TECH_NEWS_QUERIES = [
    "Bangladesh software company hiring 2025",
    "Bangladesh tech startup hiring developer 2025",
    "BD tech company job circular 2025",
    "Bangladesh fintech edtech hiring software engineer",
    "Bangladesh software engineer salary hiring news 2025",
]


def _ddg_extract_url(href: str) -> str:
    """Extract real URL from DuckDuckGo redirect href (/l/?uddg=...)."""
    if "uddg=" in href:
        try:
            qs = parse_qs(urlparse(href).query)
            return unquote(qs.get("uddg", [""])[0])
        except Exception:
            pass
    if href.startswith("http"):
        return href
    return ""


async def scrape_ddg(
    session: aiohttp.ClientSession,
    query: str,
    max_results: int = 10,
) -> list[dict]:
    """
    DuckDuckGo HTML search — no API key, no JS required.
    Returns list of {title, url, snippet} dicts.
    Sleep 1–2s before each request to avoid rate-limiting.
    """
    await asyncio.sleep(random.uniform(1.0, 2.0))
    url  = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    html = await fetch_html(session, url, timeout=20)
    if not html:
        return []
    try:
        soup    = BeautifulSoup(html, "lxml")
        results = []
        for r in soup.select(".result"):
            ta = r.select_one(".result__a")
            sa = r.select_one(".result__snippet")
            if not ta:
                continue
            href    = _ddg_extract_url(ta.get("href", ""))
            if not href:
                continue
            results.append({
                "title":   ta.get_text(strip=True)[:150],
                "url":     href,
                "snippet": sa.get_text(strip=True)[:300] if sa else "",
            })
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        print(f"[ddg] parse error for '{query[:50]}': {e}")
        return []


async def scrape_bing(
    session: aiohttp.ClientSession,
    query: str,
    max_results: int = 10,
) -> list[dict]:
    """
    Bing HTML search — no API key required.
    Returns list of {title, url, snippet} dicts.
    Sleep 1–2s before each request.
    """
    await asyncio.sleep(random.uniform(1.0, 2.0))
    url  = f"https://www.bing.com/search?q={quote_plus(query)}&count=10&setlang=en"
    html = await fetch_html(session, url, timeout=20)
    if not html:
        return []
    try:
        soup    = BeautifulSoup(html, "lxml")
        results = []
        for r in soup.select("#b_results .b_algo"):
            ta = r.select_one("h2 a")
            sa = r.select_one(".b_caption p, .b_algoSlug")
            if not ta:
                continue
            href = ta.get("href", "")
            if not href.startswith("http"):
                continue
            results.append({
                "title":   ta.get_text(strip=True)[:150],
                "url":     href,
                "snippet": sa.get_text(strip=True)[:300] if sa else "",
            })
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        print(f"[bing] parse error for '{query[:50]}': {e}")
        return []


def _search_result_to_job(
    result: dict,
    company_name: str,
    source_engine: str,
    is_news: bool = False,
) -> dict | None:
    """
    Convert a raw search result to a job/news dict.
    Returns None if it doesn't look like a job posting or relevant news.
    """
    title   = result["title"]
    snippet = result["snippet"]
    combined = (title + " " + snippet).lower()

    if is_news:
        if not any(kw in combined for kw in NEWS_KEYWORDS | JOB_POST_KEYWORDS):
            return None
        source_type = "web_news"
        platform    = f"{source_engine}/News"
    else:
        if not any(kw in combined for kw in JOB_POST_KEYWORDS):
            return None
        source_type = "web_search"
        platform    = source_engine

    return {
        "title":       title[:120],
        "company":     company_name,
        "url":         result["url"],
        "platform":    platform,
        "tier":        3,
        "remote":      "remote" in combined,
        "source_type": source_type,
        "raw_text":    f"{title}. {snippet}"[:500],
    }


async def _search_one_query(
    session: aiohttp.ClientSession,
    query: str,
    company_name: str,
    is_news: bool,
    sem: asyncio.Semaphore,
) -> list[dict]:
    """Run a query on DDG + Bing (under semaphore), merge, dedup by URL."""
    async with sem:
        ddg_res, bing_res = await asyncio.gather(
            scrape_ddg(session, query),
            scrape_bing(session, query),
            return_exceptions=True,
        )

    seen: set[str] = set()
    jobs: list[dict] = []

    for engine, results in [("DuckDuckGo", ddg_res), ("Bing", bing_res)]:
        if not isinstance(results, list):
            continue
        for r in results:
            if r["url"] in seen:
                continue
            seen.add(r["url"])
            job = _search_result_to_job(r, company_name, engine, is_news)
            if job:
                jobs.append(job)

    return jobs


async def scrape_company_web_searches(
    session: aiohttp.ClientSession,
    companies: list[dict],
    include_news: bool = True,
) -> list[dict]:
    """
    For every company: run job-search queries + (optionally) news queries on
    DuckDuckGo and Bing concurrently, capped by a semaphore of 6 simultaneous
    searches to avoid rate-limiting.

    Also runs BD_TECH_NEWS_QUERIES once for general industry news.
    Returns merged, URL-deduplicated list of job/news dicts.
    """
    year = datetime.now(DHAKA_TZ).year
    sem  = asyncio.Semaphore(6)
    tasks: list[asyncio.Task] = []

    for co in companies:
        name = co["name"]
        for tmpl in _COMPANY_JOB_QUERIES:
            tasks.append(_search_one_query(session, tmpl.format(name=name, year=year),
                                           name, False, sem))
        if include_news:
            for tmpl in _COMPANY_NEWS_QUERIES:
                tasks.append(_search_one_query(session, tmpl.format(name=name, year=year),
                                               name, True, sem))

    # General BD tech news queries (company = "BD Tech News")
    if include_news:
        for q in BD_TECH_NEWS_QUERIES:
            tasks.append(_search_one_query(session, q, "BD Tech News", True, sem))

    print(f"[websearch] Running {len(tasks)} search queries (DDG + Bing, semaphore=6)...")
    raw = await asyncio.gather(*tasks, return_exceptions=True)

    seen_urls: set[str] = set()
    all_results: list[dict] = []
    for r in raw:
        if not isinstance(r, list):
            continue
        for item in r:
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                all_results.append(item)

    job_count  = sum(1 for j in all_results if j["source_type"] == "web_search")
    news_count = sum(1 for j in all_results if j["source_type"] == "web_news")
    print(f"[websearch] Done: {job_count} job results + {news_count} news items")
    return all_results


# ══════════════════════════════════════════════════════════════════════════════
# ENSEMBLE: SINGLE MODEL CALLER
# ══════════════════════════════════════════════════════════════════════════════

async def call_model(
    session: aiohttp.ClientSession,
    nim_key: str,
    model_cfg: dict,
    jobs: list[dict],
) -> tuple | None:
    """
    Score a batch with one NIM model.
    Attaches stable job_id; passes raw_text for social posts.
    Returns (label, weight, tier, results) or None on any failure.
    Catches JSONDecodeError, TimeoutError, and all other exceptions independently.
    """
    label, tier, model, timeout = (
        model_cfg["label"], model_cfg["tier"],
        model_cfg["id"], model_cfg["timeout"],
    )
    payload = [
        {
            **{k: v for k, v in j.items() if k != "raw_text"},
            "job_id":   j.get("id") or job_uid(j["title"], j["company"], j["url"]),
            "raw_text": j.get("raw_text", ""),  # social context for AI scorer
        }
        for j in jobs
    ]
    start = time.time()
    try:
        async with session.post(
            NIM_ENDPOINT,
            headers={
                "Authorization": f"Bearer {nim_key}",
                "Content-Type":  "application/json",
            },
            json={
                "model":       model,
                "messages": [
                    {"role": "system", "content": SCORER_SYSTEM_PROMPT},
                    {"role": "user",   "content": json.dumps(payload, ensure_ascii=False)},
                ],
                "max_tokens":  4000,
                "temperature": 0.1,
                "stream":      False,
            },
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as r:
            elapsed = round(time.time() - start, 1)
            if r.status != 200:
                body = await r.text()
                print(f"[ensemble] [{tier}] {label} -> HTTP {r.status} ({elapsed}s): {body[:80]}")
                return None
            data    = await r.json()
            raw     = data["choices"][0]["message"]["content"].strip()
            cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
            result  = json.loads(cleaned)
            if not isinstance(result, list):
                print(f"[ensemble] [{tier}] {label} -> non-list response")
                return None
            print(f"[ensemble] [{tier}] {label} -> {len(result)} jobs ({elapsed}s) ✓")
            return (label, model_cfg["weight"], tier, result)
    except json.JSONDecodeError as e:
        print(f"[ensemble] [{tier}] {label} -> bad JSON: {e}")
    except asyncio.TimeoutError:
        print(f"[ensemble] [{tier}] {label} -> timeout after {timeout}s")
    except Exception as e:
        print(f"[ensemble] [{tier}] {label} -> {type(e).__name__}: {e}")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# ENSEMBLE: LOCAL FUSION FALLBACK
# ══════════════════════════════════════════════════════════════════════════════

def local_fusion(model_outputs: list[tuple]) -> list[dict]:
    """
    Pure-Python weighted-average fusion. Zero API dependency.
    Mirrors FUSION_SYSTEM_PROMPT rules exactly:
    - Weighted avg score (Tier S gets x1.2 effective weight)
    - Boosts: x1.15 for 5-6 models, x1.05 for 3-4 models
    - Drop: 1 model AND score < 7
    - Tier S veto: max Tier S score < 5
    - Social penalty: source_type=social AND agreement < 3 -> -0.5
    - Sort: model_agreement DESC, final_score DESC
    """
    by_url: dict[str, list] = defaultdict(list)
    best:   dict[str, dict] = {}

    for label, weight, tier, scored_jobs in model_outputs:
        eff_w = weight * (1.2 if tier == "S" else 1.0)
        for job in scored_jobs:
            url = job.get("url", "").strip()
            if not url:
                continue
            score = float(job.get("relevance_score", 5))
            by_url[url].append((score, eff_w, tier, label))
            if url not in best:
                best[url] = dict(job)
            if len(job.get("why_relevant","")) > len(best[url].get("why_relevant","")):
                best[url]["why_relevant"] = job["why_relevant"]
            if job.get("apply_note") and not best[url].get("apply_note"):
                best[url]["apply_note"] = job["apply_note"]

    fused = []
    for url, entries in by_url.items():
        agreement = len(entries)

        if agreement == 1 and entries[0][0] < 7:
            continue

        tier_s = [s for s, _, t, _ in entries if t == "S"]
        if tier_s and max(tier_s) < 5:
            continue

        total_w   = sum(w for _, w, _, _ in entries)
        raw_score = sum(s * w for s, w, _, _ in entries) / total_w

        if   agreement >= 5: raw_score = min(raw_score * 1.15, 10.0)
        elif agreement >= 3: raw_score = min(raw_score * 1.05, 10.0)

        # Social penalty for low-agreement social posts
        job_data = best[url]
        if job_data.get("source_type") == "social" and agreement < 3:
            raw_score = max(raw_score - 0.5, 0.0)

        final_score = round(raw_score, 1)
        confidence  = "high" if agreement >= 5 else "medium" if agreement >= 3 else "low"

        job = dict(job_data)
        job.update({
            "final_score":     final_score,
            "model_agreement": agreement,
            "confidence":      confidence,
        })
        fused.append(job)

    fused.sort(key=lambda x: (-x["model_agreement"], -x["final_score"]))
    print(f"[ensemble] Local fallback fusion -> {len(fused)} jobs")
    return fused


# ══════════════════════════════════════════════════════════════════════════════
# ENSEMBLE: KIMI-K2.6 FUSION
# ══════════════════════════════════════════════════════════════════════════════

async def fuse_with_kimi(
    session: aiohttp.ClientSession,
    nim_key: str,
    model_outputs: list[tuple],
) -> list[dict]:
    """
    Send all model scored lists to Kimi-K2.6 for weighted consensus fusion.
    temperature=0.0 — deterministic output. Falls back to local_fusion() on failure.
    """
    fusion_input = {
        "models": [
            {"label": lbl, "tier": t, "weight": wgt, "scored_jobs": scored}
            for lbl, wgt, t, scored in model_outputs
        ],
        "task": "Fuse the scored job lists into one final ranked list following the rules.",
    }
    start = time.time()
    try:
        async with session.post(
            NIM_ENDPOINT,
            headers={
                "Authorization": f"Bearer {nim_key}",
                "Content-Type":  "application/json",
            },
            json={
                "model":       FUSION_MODEL,
                "messages": [
                    {"role": "system", "content": FUSION_SYSTEM_PROMPT},
                    {"role": "user",   "content": json.dumps(fusion_input, ensure_ascii=False)},
                ],
                "max_tokens":  6000,
                "temperature": 0.0,
                "stream":      False,
            },
            timeout=aiohttp.ClientTimeout(total=FUSION_TIMEOUT),
        ) as r:
            elapsed = round(time.time() - start, 1)
            if r.status == 200:
                data    = await r.json()
                raw     = data["choices"][0]["message"]["content"].strip()
                cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
                fused   = json.loads(cleaned)
                print(f"[ensemble] Kimi-K2.6 fusion -> {len(fused)} jobs ({elapsed}s)")
                return fused
            body = await r.text()
            print(f"[ensemble] Fusion HTTP {r.status} ({elapsed}s): {body[:80]} -> local fallback")
    except Exception as e:
        print(f"[ensemble] Fusion failed ({type(e).__name__}: {e}) -> local fallback")
    return local_fusion(model_outputs)


# ══════════════════════════════════════════════════════════════════════════════
# ENSEMBLE: MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

async def filter_with_ensemble(
    session: aiohttp.ClientSession,
    jobs: list[dict],
    nim_key: str,
) -> list[dict]:
    """
    Fire all 6 scorer models simultaneously, then fuse via Kimi-K2.6.

    Timeline (all parallel):
      t=0    All 6 start
      t=30s  llama4-maverick
      t=60s  mistral-small
      t=90s  nemotron-super-49b
      t=120s nemotron-super-120b
      t=150s qwen3.5-397b
      t=180s kimi-k2.6 scorer -> fusion starts
      t=240s fusion done

    Failure handling:
      0 models -> return unscored with warning flag
      1 model  -> return directly, skip fusion
      2+       -> run Kimi-K2.6 fusion
    """
    if not jobs:
        return []

    div = "=" * 65
    print(f"\n{div}")
    print(f"[ensemble] Scoring {len(jobs)} jobs — 6 models parallel")
    print(f"[ensemble] " + " | ".join(f"[{m['tier']}]{m['label']}" for m in ENSEMBLE_MODELS))
    print(div)
    wall_start = time.time()

    raw = await asyncio.gather(
        *[call_model(session, nim_key, cfg, jobs) for cfg in ENSEMBLE_MODELS],
        return_exceptions=True,
    )

    model_outputs = [r for r in raw if isinstance(r, tuple)]
    failed        = len(ENSEMBLE_MODELS) - len(model_outputs)
    elapsed       = round(time.time() - wall_start, 1)

    print(f"\n[ensemble] Scoring done: {elapsed}s | {len(model_outputs)} ok / {failed} failed")
    for lbl, _, tier, scored in model_outputs:
        print(f"           [{tier}] {lbl}: {len(scored)} kept")

    if not model_outputs:
        print("[ERROR] All 6 models failed — returning unscored with warning")
        for j in jobs:
            j.update({"final_score": 5.0, "model_agreement": 0,
                       "confidence": "none", "why_relevant": "Ensemble unavailable"})
        return jobs

    if len(model_outputs) == 1:
        lbl, _, tier, scored = model_outputs[0]
        print(f"[ensemble] Single model ({lbl}) — no fusion")
        for j in scored:
            j.update({"final_score": float(j.get("relevance_score", 5)),
                       "model_agreement": 1, "confidence": "low"})
        return scored

    print(f"\n[ensemble] Kimi-K2.6 fusion ({len(model_outputs)} model outputs)...")
    fused = await fuse_with_kimi(session, nim_key, model_outputs)
    total = round(time.time() - wall_start, 1)
    print(f"\n[ensemble] Complete: {total}s | {len(fused)} relevant jobs")
    print(f"{div}\n")
    return fused


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════════════════

def tg_escape(text: str) -> str:
    return _tg_escape_common(text)


async def send_telegram(
    session: aiohttp.ClientSession,
    token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "MarkdownV2",
):
    await _send_telegram_common(session, token, chat_id, text, parse_mode)


# ══════════════════════════════════════════════════════════════════════════════
# MESSAGE FORMATTER
# ══════════════════════════════════════════════════════════════════════════════

def format_jobs(jobs: list[dict], trigger: str = "command") -> str:
    """
    Format job list as Telegram MarkdownV2.
    Groups by tier. Social posts get 📢 badge.
    Footer includes Eyasir's profile links.
    """
    if not jobs:
        return "✅ No new jobs since last check\\. I'll notify you tomorrow\\!"

    now = datetime.now(DHAKA_TZ).strftime("%a, %d %b %Y  %I:%M %p")

    header = (
        "🌅 *Good morning Eyasir\\!* Daily job digest\n"
        if trigger == "scheduler"
        else "🔍 *CSE Job Search — Bangladesh*\n"
    )

    high_c   = sum(1 for j in jobs if j.get("confidence") == "high")
    medium_c = sum(1 for j in jobs if j.get("confidence") == "medium")
    low_c    = sum(1 for j in jobs if j.get("confidence") == "low")
    social_c  = sum(1 for j in jobs if j.get("source_type") == "social")
    search_c  = sum(1 for j in jobs if j.get("source_type") == "web_search")
    news_c    = sum(1 for j in jobs if j.get("source_type") == "web_news")

    # Unique platforms that contributed results
    platforms = sorted(set(j.get("platform", "?").split("/")[0] for j in jobs))

    lines = [
        header,
        f"📅 {tg_escape(now)}",
        f"🆕 *{len(jobs)} new relevant jobs found*",
        f"🤖 6\\-model ensemble  \\|  🔀 Kimi\\-K2\\.6 fusion",
        f"🟢 {high_c} high  🟡 {medium_c} medium  🟠 {low_c} low",
    ]
    if social_c:
        lines.append(f"📢 {social_c} community posts \\(verify details\\)")
    if search_c:
        lines.append(f"🔎 {search_c} web search results \\(DDG \\+ Bing\\)")
    if news_c:
        lines.append(f"📰 {news_c} company news items")
    if platforms:
        lines.append(f"📡 Sources: {tg_escape(' · '.join(platforms[:7]))}")
    lines.append("")

    TIER_LABELS = {
        1: "🏆 *Tier 1 — Top BD Tech*",
        2: "⭐ *Tier 2 — BD Tech*",
        3: "📋 *Job Boards & Community*",
    }
    CONF_BADGES = {"high": "🟢", "medium": "🟡", "low": "🟠", "none": "⚪"}

    sorted_jobs = sorted(
        jobs,
        key=lambda x: (x.get("tier", 3), -x.get("model_agreement", 0), -x.get("final_score", 0)),
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

        conf_badge  = CONF_BADGES.get(confidence, "⚪")
        agree_bar   = "●" * min(agreement, 6) + "○" * max(0, 6 - agreement)
        location    = "🌐 Remote" if remote else "📍 Bangladesh"
        src_prefix  = {"social": "📢 ", "web_search": "🔎 ", "web_news": "📰 "}.get(source, "")

        card = (
            f"\n━━━━━━━━━━━━━━\n"
            f"🏢 *{tg_escape(j.get('company', 'Unknown'))}*\n"
            f"💼 {src_prefix}{tg_escape(j.get('title', 'Unknown'))}\n"
            f"⭐ {tg_escape(str(final_score))}/10  "
            f"{conf_badge} {tg_escape(confidence)}  "
            f"\\[{agree_bar}\\] {agreement}/6\n"
            f"{tg_escape(location)}  \\|  {tg_escape(j.get('platform', ''))}\n"
        )
        if why:
            card += f"💡 _{tg_escape(why)}_\n"
        if note:
            card += f"📌 _{tg_escape(note)}_\n"
        card += f"🔗 [Apply Here]({j.get('url', '')})"
        lines.append(card)

    lines.append(
        f"\n\n👤 [LinkedIn](https://www.linkedin.com/in/eyasir329/)  "
        f"\\|  [GitHub](https://github.com/eyasir329)  "
        f"\\|  [Facebook](https://www.facebook.com/eyasir329)\n"
        f"_Powered by: Kimi\\-K2\\.6 \\+ Qwen3\\.5\\-397B \\+ "
        f"Nemotron\\-120B \\+ Nemotron\\-49B \\+ Llama\\-4 \\+ Mistral\\-119B_"
    )
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

async def run_job_search(trigger: str = "command", args: list = None) -> list[dict]:
    """
    Full pipeline:
      1. Load config + init DB
      2. Announce to Telegram (unless silent)
      3. Launch all scrapers concurrently
      4. Deduplicate vs seen_jobs table
      5. 6-model ensemble score + Kimi-K2.6 fusion (batches of 20)
      6. Persist + log
      7. Format + send Telegram

    Flags:
      tier1    — Tier 1 companies only, skip job boards
      fresh    — wipe seen_jobs before search
      silent   — no Telegram output
      intern   — post-filter: intern/trainee titles only
      ml       — post-filter: ML/AI/Data titles only
      backend  — post-filter: backend titles only
      frontend — post-filter: frontend titles only
      devops   — post-filter: DevOps/SRE/Cloud titles only
      remote   — post-filter: remote jobs only
      boards   — source-filter: job boards only (no career pages / social)
      social   — source-filter: Facebook + Twitter only
    """
    args       = args or []
    tier1_only = "tier1"    in args
    fresh      = "fresh"    in args
    silent     = "silent"   in args
    only_boards= "boards"   in args
    only_social= "social"   in args
    role_intern = "intern"  in args
    role_ml     = "ml"      in args
    role_backend= "backend" in args
    role_front  = "frontend"in args
    role_devops = "devops"  in args
    only_remote = "remote"  in args

    token, chat_id, nim_key = load_openclaw_config()
    conn       = init_db()
    wall_start = time.time()

    if fresh:
        conn.execute("DELETE FROM seen_jobs")
        conn.commit()
        print("[job-search] Cache cleared")

    connector = aiohttp.TCPConnector(limit=25, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:

        # ── Announce ──────────────────────────────────────────────────────────
        if not silent:
            n_companies = len(TIER1) + (0 if tier1_only else len(TIER2))
            mode_note   = " \\(Tier 1 only\\)" if tier1_only else ""
            extras      = "" if tier1_only else " \\+ BDJobs \\+ Indeed \\+ Facebook \\+ Twitter \\+ DDG/Bing"
            await send_telegram(
                session, token, chat_id,
                f"🔍 Searching {n_companies} companies{extras}{mode_note}\\.\n"
                f"⚙️ 6\\-model NIM ensemble ready\\. ⏱️ Results in \\~4 minutes\\."
            )

        # ── Build all scraper tasks ───────────────────────────────────────────
        print(f"\n[job-search] Launching scrapers (boards={only_boards} social={only_social})...")
        tasks = []

        companies = (
            [{**co, "tier": 1} for co in TIER1]
            + ([] if tier1_only else [{**co, "tier": 2} for co in TIER2])
        )

        if not only_boards and not only_social:
            for co in companies:
                tasks.append(scrape_career_page(session, co))

        if not only_social:
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

        if not only_boards:
            if not tier1_only:
                for group in FACEBOOK_GROUPS:
                    tasks.append(scrape_facebook_group(session, group))
                tasks.append(scrape_twitter_jobs(session))

        # Web search: skip when only_social or tier1_only; run for boards mode
        run_web = not only_social and not tier1_only
        if run_web:
            web_search_task = asyncio.create_task(
                scrape_company_web_searches(session, companies, include_news=True)
            )
        else:
            web_search_task = None

        raw = await asyncio.gather(*tasks, return_exceptions=True)
        web_search_results = (await web_search_task) if web_search_task else []

        # ── Flatten + count per platform ──────────────────────────────────────
        all_jobs: list[dict] = []
        platforms_hit: dict[str, int] = defaultdict(int)
        for r in raw:
            if isinstance(r, list):
                for j in r:
                    all_jobs.append(j)
                    platforms_hit[j.get("platform", "?")] += 1

        # Merge web search results (job + news)
        for j in web_search_results:
            all_jobs.append(j)
            platforms_hit[j.get("platform", "?")] += 1

        # ── Deduplicate vs DB ─────────────────────────────────────────────────
        new_jobs: list[dict] = []
        for j in all_jobs:
            uid  = job_uid(j["title"], j["company"], j["url"])
            j["id"] = uid
            if not is_seen(conn, uid):
                new_jobs.append(j)

        # ── Role / source post-filters ────────────────────────────────────────
        if role_intern:
            new_jobs = [j for j in new_jobs if _matches_role_filter(j, _INTERN_KW)]
            print(f"[job-search] intern filter: {len(new_jobs)} remaining")
        if role_ml:
            new_jobs = [j for j in new_jobs if _matches_role_filter(j, _ML_KW)]
            print(f"[job-search] ml filter: {len(new_jobs)} remaining")
        if role_backend:
            new_jobs = [j for j in new_jobs if _matches_role_filter(j, _BACKEND_KW)]
            print(f"[job-search] backend filter: {len(new_jobs)} remaining")
        if role_front:
            new_jobs = [j for j in new_jobs if _matches_role_filter(j, _FRONTEND_KW)]
            print(f"[job-search] frontend filter: {len(new_jobs)} remaining")
        if role_devops:
            new_jobs = [j for j in new_jobs if _matches_role_filter(j, _DEVOPS_KW)]
            print(f"[job-search] devops filter: {len(new_jobs)} remaining")
        if only_remote:
            new_jobs = [j for j in new_jobs if j.get("remote")]
            print(f"[job-search] remote filter: {len(new_jobs)} remaining")

        print(f"\n[job-search] Scraped: {len(all_jobs)} total | {len(new_jobs)} new")
        for plat, count in sorted(platforms_hit.items(), key=lambda x: -x[1])[:10]:
            print(f"             {plat}: {count}")

        if not new_jobs:
            log_run(conn, trigger, len(all_jobs), 0, 0, 0,
                    time.time() - wall_start, dict(platforms_hit))
            conn.close()
            if not silent:
                await send_telegram(session, token, chat_id,
                    "✅ No new jobs since last check\\. I'll notify you tomorrow\\!")
            return []

        # ── 6-model ensemble in batches of 20 ────────────────────────────────
        filtered: list[dict] = []
        batches = [new_jobs[i:i + 20] for i in range(0, len(new_jobs), 20)]
        for i, batch in enumerate(batches):
            print(f"[job-search] Ensemble batch {i+1}/{len(batches)}: {len(batch)} jobs")
            result = await filter_with_ensemble(session, batch, nim_key)
            filtered.extend(result)
            if i < len(batches) - 1:
                await asyncio.sleep(2)

        # ── Persist + log ─────────────────────────────────────────────────────
        for j in filtered:
            mark_seen(conn, j)
        duration = time.time() - wall_start
        log_run(conn, trigger, len(all_jobs), len(new_jobs), len(filtered),
                len(ENSEMBLE_MODELS), duration, dict(platforms_hit))
        conn.close()
        print(f"\n[job-search] Done: {len(filtered)} relevant jobs in {duration:.1f}s")

        # ── Send results ──────────────────────────────────────────────────────
        if not silent:
            if filtered:
                msg = format_jobs(filtered, trigger)
                await send_telegram(session, token, chat_id, msg)
            else:
                await send_telegram(session, token, chat_id,
                    "✅ Jobs scraped but none passed ensemble filter\\.\n"
                    "Try `/job_search_fresh` to reset the cache\\.")

    return filtered


# ══════════════════════════════════════════════════════════════════════════════
# WEEKLY SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

# ── Role/source filter keyword sets ───────────────────────────────────────────
_INTERN_KW  = frozenset({"intern", "internship", "trainee", "graduate trainee", "fresh grad"})
_ML_KW      = frozenset({"machine learning", "ml ", "ai ", "deep learning", "data scientist",
                          "data engineer", "nlp", "computer vision", "llm", "research engineer"})
_BACKEND_KW = frozenset({"backend", "back-end", "back end", "api developer", "node.js",
                          "django", "spring boot", "golang", "rust", "microservice"})
_FRONTEND_KW= frozenset({"frontend", "front-end", "front end", "react", "vue", "angular",
                          "next.js", "ui developer", "web developer"})
_DEVOPS_KW  = frozenset({"devops", "sre", "site reliability", "infrastructure", "cloud engineer",
                          "kubernetes", "docker", "aws", "gcp", "azure", "platform engineer"})


def _matches_role_filter(job: dict, kw_set: frozenset) -> bool:
    text = (job.get("title","") + " " + job.get("raw_text","")).lower()
    return any(kw in text for kw in kw_set)


# ══════════════════════════════════════════════════════════════════════════════
# STATUS + STATS COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

async def send_status():
    """Quick status: DB size, last run, next run, total seen jobs."""
    token, chat_id, _ = load_openclaw_config()
    conn = init_db()

    total_seen = conn.execute("SELECT COUNT(*) FROM seen_jobs").fetchone()[0]
    week_seen  = conn.execute(
        "SELECT COUNT(*) FROM seen_jobs WHERE found_at >= datetime('now','-7 days')"
    ).fetchone()[0]
    today_seen = conn.execute(
        "SELECT COUNT(*) FROM seen_jobs WHERE found_at >= date('now')"
    ).fetchone()[0]

    last_run_row = conn.execute(
        "SELECT searched_at, trigger, total_scraped, filtered_jobs, duration_secs "
        "FROM search_log ORDER BY id DESC LIMIT 1"
    ).fetchone()

    companies_tracked = len(TIER1) + len(TIER2)
    db_size = DB_PATH.stat().st_size / 1024 if DB_PATH.exists() else 0

    conn.close()

    now   = datetime.now(DHAKA_TZ).strftime("%a %d %b %Y %I:%M %p")
    lines = [
        "📊 *Job Search Status*",
        f"📅 {tg_escape(now)}",
        "",
        f"🏢 Companies tracked: *{companies_tracked}* \\(Tier1\\: {len(TIER1)}, Tier2\\: {len(TIER2)}\\)",
        f"🗃️ Total seen jobs: *{total_seen}*",
        f"📆 This week: *{week_seen}* new  \\|  Today: *{today_seen}* new",
        f"💾 DB size: *{tg_escape(f'{db_size:.1f}')} KB*",
    ]

    if last_run_row:
        at, trig, scraped, filtered, dur = last_run_row
        lines += [
            "",
            f"⏱️ Last run: *{tg_escape(str(at)[:16])}* \\({tg_escape(trig)}\\)",
            f"   Scraped {scraped} → kept {filtered} \\({tg_escape(f'{dur:.0f}')}s\\)",
        ]

    connector = aiohttp.TCPConnector()
    async with aiohttp.ClientSession(connector=connector) as session:
        await send_telegram(session, token, chat_id, "\n".join(lines))


async def send_stats():
    """Detailed platform + company breakdown for last 7 days."""
    token, chat_id, _ = load_openclaw_config()
    conn = init_db()

    platform_rows = conn.execute("""
        SELECT platform, COUNT(*) AS n
        FROM seen_jobs
        WHERE found_at >= datetime('now','-7 days') AND platform IS NOT NULL
        GROUP BY platform ORDER BY n DESC LIMIT 12
    """).fetchall()

    company_rows = conn.execute("""
        SELECT company, COUNT(*) AS n
        FROM seen_jobs
        WHERE found_at >= datetime('now','-7 days')
        GROUP BY company ORDER BY n DESC LIMIT 10
    """).fetchall()

    source_rows = conn.execute("""
        SELECT source_type, COUNT(*) AS n
        FROM seen_jobs
        WHERE found_at >= datetime('now','-7 days')
        GROUP BY source_type ORDER BY n DESC
    """).fetchall()

    run_rows = conn.execute("""
        SELECT searched_at, total_scraped, filtered_jobs, duration_secs
        FROM search_log ORDER BY id DESC LIMIT 5
    """).fetchall()

    conn.close()

    def _tbl(rows):
        return "\n".join(f"  • {tg_escape(str(r[0]))}: *{r[1]}*" for r in rows) or "  _no data_"

    run_lines = "\n".join(
        f"  {tg_escape(str(r[0])[:16])} — {r[1]} scraped → {r[2]} kept \\({tg_escape(f'{r[3]:.0f}')}s\\)"
        for r in run_rows
    ) or "  _no runs yet_"

    msg = (
        "📈 *Job Search Stats \\(last 7 days\\)*\n\n"
        f"*By platform:*\n{_tbl(platform_rows)}\n\n"
        f"*By source type:*\n{_tbl(source_rows)}\n\n"
        f"*Top companies:*\n{_tbl(company_rows)}\n\n"
        f"*Recent runs:*\n{run_lines}"
    )

    connector = aiohttp.TCPConnector()
    async with aiohttp.ClientSession(connector=connector) as session:
        await send_telegram(session, token, chat_id, msg)


async def send_company_search(company_query: str):
    """Search a single company by name (case-insensitive partial match)."""
    token, chat_id, nim_key = load_openclaw_config()

    q   = company_query.strip().lower()
    all_cos = [{**co, "tier": 1} for co in TIER1] + [{**co, "tier": 2} for co in TIER2]
    matches = [co for co in all_cos if q in co["name"].lower()]

    if not matches:
        connector = aiohttp.TCPConnector()
        async with aiohttp.ClientSession(connector=connector) as session:
            known = tg_escape(", ".join(co["name"] for co in all_cos[:10]) + "...")
            await send_telegram(session, token, chat_id,
                f"❓ No company matching *{tg_escape(company_query)}*\\.\n"
                f"Known: {known}")
        return

    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        await send_telegram(session, token, chat_id,
            f"🔍 Searching *{tg_escape(matches[0]['name'])}*\\.\\.\\.")

        conn = init_db()
        raw  = await asyncio.gather(
            *[scrape_career_page(session, co) for co in matches],
            return_exceptions=True,
        )
        jobs: list[dict] = []
        for r in raw:
            if isinstance(r, list):
                for j in r:
                    uid = job_uid(j["title"], j["company"], j["url"])
                    j["id"] = uid
                    jobs.append(j)

        if not jobs:
            await send_telegram(session, token, chat_id,
                f"📭 No jobs found on career page for *{tg_escape(matches[0]['name'])}*\\.")
            conn.close()
            return

        filtered = await filter_with_ensemble(session, jobs[:20], nim_key)
        for j in filtered:
            mark_seen(conn, j)
        conn.close()

        if filtered:
            await send_telegram(session, token, chat_id,
                format_jobs(filtered, trigger="command"))
        else:
            await send_telegram(session, token, chat_id,
                f"✅ Jobs scraped for *{tg_escape(matches[0]['name'])}* but none passed relevance filter\\.")


async def send_history(n: int = 10):
    """Show the last N jobs found (from DB, no new scraping)."""
    token, chat_id, _ = load_openclaw_config()
    conn  = init_db()
    rows  = conn.execute(
        "SELECT title, company, url, platform, tier, relevance_score, found_at "
        "FROM seen_jobs ORDER BY found_at DESC LIMIT ?", (n,)
    ).fetchall()
    conn.close()

    if not rows:
        connector = aiohttp.TCPConnector()
        async with aiohttp.ClientSession(connector=connector) as session:
            await send_telegram(session, token, chat_id, "📭 No jobs in history yet\\.")
        return

    lines = [f"🕐 *Last {n} jobs found*\n"]
    for title, company, url, platform, tier, score, found_at in rows:
        when = str(found_at)[:16]
        lines.append(
            f"\n━━━━━━━\n"
            f"🏢 *{tg_escape(company)}*\n"
            f"💼 {tg_escape(title[:80])}\n"
            f"📅 {tg_escape(when)}  \\|  {tg_escape(platform or '?')}\n"
            f"🔗 [Open]({url})"
        )

    connector = aiohttp.TCPConnector()
    async with aiohttp.ClientSession(connector=connector) as session:
        await send_telegram(session, token, chat_id, "\n".join(lines))


async def send_clear_cache():
    """Wipe seen_jobs so all current openings appear fresh next search."""
    token, chat_id, _ = load_openclaw_config()
    conn = init_db()
    n = conn.execute("SELECT COUNT(*) FROM seen_jobs").fetchone()[0]
    conn.execute("DELETE FROM seen_jobs")
    conn.commit()
    conn.close()
    connector = aiohttp.TCPConnector()
    async with aiohttp.ClientSession(connector=connector) as session:
        await send_telegram(session, token, chat_id,
            f"🗑️ Cache cleared\\. *{n}* seen\\-job records removed\\.\n"
            f"Next `/job_search` will show all current openings\\.")


async def send_weekly_summary():
    """Send weekly digest: count, top companies, platform breakdown."""
    token, chat_id, _ = load_openclaw_config()
    conn  = init_db()
    stats = get_weekly_stats(conn)
    top   = get_top_companies(conn, 5)
    conn.close()

    co_lines = "\n".join(
        f"  {i+1}\\. {tg_escape(row[0])}: {row[1]} job{'s' if row[1]!=1 else ''}"
        for i, row in enumerate(top)
    ) or "  _No data this week_"

    connector = aiohttp.TCPConnector()
    async with aiohttp.ClientSession(connector=connector) as session:
        await send_telegram(session, token, chat_id,
            f"📊 *Weekly Job Summary*\n"
            f"Jobs found: *{stats.get('total_jobs',0)}* across "
            f"*{stats.get('companies',0)}* companies, "
            f"*{stats.get('platforms',0)}* platforms\n"
            f"Tier 1 roles: *{stats.get('tier1_jobs',0)}*  "
            f"\\|  Community posts: *{stats.get('social_jobs',0)}*\n\n"
            f"*Top companies this week:*\n{co_lines}\n\n"
            f"Use `/job_search_fresh` to see all current openings\\."
        )


# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULER
# ══════════════════════════════════════════════════════════════════════════════

async def start_scheduler():
    """
    APScheduler inside asyncio. Blocking — run in dedicated tmux window.
    Daily at 09:00 Asia/Dhaka + weekly summary Sunday 09:05.
    """
    scheduler = AsyncIOScheduler(timezone=DHAKA_TZ)
    scheduler.add_job(
        lambda: asyncio.create_task(run_job_search(trigger="scheduler")),
        "cron", hour=9, minute=0, id="daily_digest", replace_existing=True,
    )
    scheduler.add_job(
        lambda: asyncio.create_task(send_weekly_summary()),
        "cron", day_of_week="sun", hour=9, minute=5, id="weekly_summary", replace_existing=True,
    )
    scheduler.start()
    next_run = scheduler.get_job("daily_digest").next_run_time
    print(f"[scheduler] Daily digest: 09:00 Asia/Dhaka (next: {next_run})")
    print(f"[scheduler] Weekly summary: Sunday 09:05 Asia/Dhaka")
    print(f"[scheduler] Running. Ctrl+C to stop.\n")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("[scheduler] Stopped.")


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    argv = sys.argv[1:]
    cmd  = argv[0] if argv else ""

    if "--schedule" in argv:
        asyncio.run(start_scheduler())

    elif "--test" in argv:
        async def _smoke_test():
            print("=== Smoke test: career pages + BDJobs + Facebook + Twitter ===\n")
            c = aiohttp.TCPConnector(limit=10)
            async with aiohttp.ClientSession(connector=c) as s:
                for co in TIER1[:3]:
                    jobs = await scrape_career_page(s, {**co, "tier": 1})
                    print(f"  {co['name']}: {len(jobs)} jobs")
                bd = await scrape_bdjobs(s, "software engineer")
                print(f"  BDJobs 'software engineer': {len(bd)}")
                bt = await scrape_bdtechjobs(s)
                print(f"  BDTechJobs: {len(bt)}")
                fb = await scrape_facebook_group(s, FACEBOOK_GROUPS[0])
                print(f"  Facebook '{FACEBOOK_GROUPS[0]['name']}': {len(fb)}")
                tw = await scrape_twitter_jobs(s)
                print(f"  Twitter/X: {len(tw)}")
            print("\n[test] Done")
        asyncio.run(_smoke_test())

    # ── Info / utility commands (no scraping) ─────────────────────────────────
    elif cmd == "status":
        asyncio.run(send_status())

    elif cmd == "stats":
        asyncio.run(send_stats())

    elif cmd == "weekly":
        asyncio.run(send_weekly_summary())

    elif cmd == "history":
        n = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 10
        asyncio.run(send_history(n))

    elif cmd == "clear":
        asyncio.run(send_clear_cache())

    # ── Company-specific search ───────────────────────────────────────────────
    elif cmd == "company" and len(argv) > 1:
        asyncio.run(send_company_search(" ".join(argv[1:])))

    # ── All other args pass through to run_job_search as filter flags ─────────
    # Supports: tier1 | fresh | silent | intern | ml | backend | frontend |
    #           devops | remote | boards | social
    else:
        asyncio.run(run_job_search(trigger="command", args=argv))

