---
name: job-search
description: >
  Unified BD CSE job search for Eyasir across 52 tech companies, LinkedIn,
  BDJobs (16 keywords), BDTechJobs, Indeed BD, Glassdoor, Facebook groups (mbasic),
  Twitter/X (Nitter), and DuckDuckGo/Bing web search per company.
  6-model NVIDIA NIM parallel ensemble + Kimi-K2.6 fusion.
  SQLite deduplication. Daily digest at 09:00 Asia/Dhaka. Telegram MarkdownV2 cards.
---

Comprehensive BD CSE job search targeting Software Engineering, AI/ML, Intern, and
Trainee roles. Searches 52 company career pages (with extra_urls per company) and
9 job/social platforms concurrently. Also runs DDG + Bing web search for every company
to surface jobs and news not on their career page. 6-model AI ensemble scores all results;
Kimi-K2.6 fuses all outputs deterministically. Social posts flagged with 📢, web search
results with 🔎, news items with 📰.

## Trigger
/job-search

## Optional args
- `tier1`   — Tier 1 companies only, no job boards (~60s)
- `fresh`   — Clear seen-jobs cache, re-show all current jobs
- `weekly`  — Send this week's summary only (no new search)
- `silent`  — No Telegram output (scheduler internal use)

## Telegram slash commands
/job_search              — full search all sources (~4 min)
/job_search_tier1        — top 12 companies only (~60s)
/job_search_fresh        — clear cache + full search
/job_search_weekly       — weekly stats summary

## Executor
skills/job-search/job_search.py

## Schedule
daily @ 09:00 Asia/Dhaka

## Sources
| Platform          | Type       | Count                             |
|-------------------|------------|-----------------------------------|
| Career Pages      | Direct     | 52 companies (Tier1=12, Tier2=40) |
| BDJobs            | Job board  | 16 keyword searches               |
| BDTechJobs        | Job board  | all tech listings                 |
| LinkedIn          | Job board  | 8 searches (last 7 days)          |
| Indeed BD         | Job board  | 5 searches                        |
| Glassdoor         | Job board  | 2 searches                        |
| Facebook Groups   | Social     | 4 groups via mbasic               |
| Twitter/X         | Social     | 10 queries via Nitter             |
| DuckDuckGo + Bing | Web search | 3 queries x 52 companies          |

## Notes
- DB: data/job_search.db
- LinkedIn/Glassdoor frequently block cloud IPs — handled gracefully (returns [])
- Nitter instances tried in order; skips Twitter if all down
- local_fusion() is pure-Python fallback if Kimi API fails
- Web search (DDG/Bing) uses semaphore=6 to avoid rate-limiting
