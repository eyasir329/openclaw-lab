#!/usr/bin/env python3
"""
OpenClaw Skill: search

General-purpose multi-backend search with 6-model NIM ensemble + Kimi-K2.6 fusion.

Backends (selected by flags):
  DDG Web          — duckduckgo-search DDGS().text() / HTML fallback
  DDG News         — duckduckgo-search DDGS().news()
  Stack Overflow   — api.stackexchange.com v2.3 (no key)
  GitHub           — api.github.com search (unauthenticated)
  Semantic Scholar — api.semanticscholar.org/graph/v1 (no key)

CLI:
  python search.py <query>                        → web + news (default)
  python search.py <query> --web                  → DDG Web only
  python search.py <query> --news                 → DDG News only
  python search.py <query> --code                 → GitHub + SO + web
  python search.py <query> --academic             → Semantic Scholar + web
  python search.py <query> --all                  → all backends
  python search.py <query> --all --deep           → all backends, max results
  python search.py <query> --brief                → skip top-results section
"""

import asyncio
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, urlparse, parse_qs, unquote
from zoneinfo import ZoneInfo

import aiohttp
from bs4 import BeautifulSoup

# ── Common Telegram utilities ──────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
from common.tg import (  # noqa: E402
    load_config as load_openclaw_config,
    tg_escape, conf_bar as _conf_bar,
    send_telegram, send_message_with_id, edit_message, send_typing, Card,
)

# ── Constants ──────────────────────────────────────────────────────────────────
NIM_ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
DHAKA_TZ     = ZoneInfo("Asia/Dhaka")

_FALLBACK_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

ENSEMBLE_MODELS = [
    # Tier S
    {"id": "moonshotai/kimi-k2.6",                     "label": "kimi-k2.6",          "tier": "S", "weight": 2.0, "timeout": 120},
    {"id": "qwen/qwen3.5-397b-a17b",                   "label": "qwen3.5-397b",        "tier": "S", "weight": 1.8, "timeout": 100},
    # Tier A
    {"id": "nvidia/nemotron-3-super-120b-a12b",        "label": "nemotron-super-120b", "tier": "A", "weight": 1.5, "timeout": 90},
    {"id": "nvidia/llama-3.3-nemotron-super-49b-v1.5", "label": "nemotron-super-49b",  "tier": "A", "weight": 1.4, "timeout": 70},
    # Tier B
    {"id": "meta/llama-4-maverick-17b-128e-instruct",  "label": "llama4-maverick",     "tier": "B", "weight": 1.0, "timeout": 30},
    {"id": "mistralai/mistral-small-4-119b-2603",      "label": "mistral-small-119b",  "tier": "B", "weight": 1.0, "timeout": 50},
]

FUSION_MODEL = "moonshotai/kimi-k2.6"

SOURCE_EMOJI = {
    "web":           "🌐",
    "news":          "📰",
    "stackoverflow": "💬",
    "github":        "🐙",
    "academic":      "🎓",
}


# ══════════════════════════════════════════════════════════════════════════════
# INTENT DETECTION
# ══════════════════════════════════════════════════════════════════════════════

_CODE_KW = frozenset({
    "error", "exception", "traceback", "bug", "fix", "install", "pip", "npm",
    "import", "module", "library", "package", "function", "class", "method",
    "api", "sdk", "tutorial", "implement", "code", "script", "snippet",
    "python", "javascript", "typescript", "java", "golang", "rust", "c++",
    "react", "node", "django", "flask", "fastapi", "tensorflow", "pytorch",
    "numpy", "pandas", "sqlalchemy", "how to", "stackoverflow", "github",
    "syntax", "debug", "compile", "runtime", "algorithm", "data structure",
    "async", "await", "callback", "promise", "thread", "process", "memory",
    "dockerfile", "kubernetes", "docker", "git", "bash", "linux command",
})

_NEWS_KW = frozenset({
    "latest", "today", "yesterday", "this week", "breaking", "news",
    "announcement", "release", "launch", "update", "version", "changelog",
    "price", "stock", "market", "election", "event", "happening", "current",
    "2024", "2025", "2026", "recently", "just", "new", "just released",
})

_ACADEMIC_KW = frozenset({
    "paper", "research", "study", "published", "journal", "arxiv", "ieee",
    "acm", "citation", "abstract", "literature", "survey", "experiment",
    "theory", "dataset", "benchmark", "findings", "authors", "proceedings",
    "conference", "machine learning paper", "nlp paper", "cv paper",
})


def detect_intent(query: str) -> str:
    """
    Classify query into: 'code', 'news', 'academic', 'general'.
    Uses keyword overlap. Returns the highest-scoring intent.
    """
    q_lower = query.lower()
    words   = set(re.findall(r"[\w]+", q_lower))

    # multi-word phrase matching
    def phrase_hits(kw_set: frozenset) -> int:
        hits = 0
        for kw in kw_set:
            if " " in kw:
                if kw in q_lower:
                    hits += 2
            elif kw in words:
                hits += 1
        return hits

    scores = {
        "code":     phrase_hits(_CODE_KW),
        "news":     phrase_hits(_NEWS_KW),
        "academic": phrase_hits(_ACADEMIC_KW),
    }
    best_score = max(scores.values())
    if best_score == 0:
        return "general"
    return max(scores, key=scores.__getitem__)


_INTENT_BACKENDS: dict[str, dict] = {
    "code":     {"web": True, "news": False, "code": True, "academic": False},
    "news":     {"web": True, "news": True,  "code": False, "academic": False},
    "academic": {"web": True, "news": False, "code": False, "academic": True},
    "general":  {"web": True, "news": True,  "code": False, "academic": False},
}

_INTENT_EMOJI: dict[str, str] = {
    "code":     "💻",
    "news":     "📰",
    "academic": "🎓",
    "general":  "🌐",
}


# ══════════════════════════════════════════════════════════════════════════════
# ARG PARSING
# ══════════════════════════════════════════════════════════════════════════════

def parse_args(argv: list[str]) -> tuple[str, dict]:
    """
    Split argv into (query, flags).
    When no backend flag given, auto-detects intent and selects backends.
    """
    explicit = {
        "web":      "--web"      in argv,
        "news":     "--news"     in argv,
        "code":     "--code"     in argv,
        "academic": "--academic" in argv,
        "all":      "--all"      in argv,
    }
    flags = {
        **explicit,
        "brief": "--brief" in argv,
        "deep":  "--deep"  in argv,
        "intent": "",
    }
    query = " ".join(a for a in argv if not a.startswith("--")).strip()

    if flags["all"]:
        flags["web"] = flags["news"] = flags["code"] = flags["academic"] = True
        flags["intent"] = "all"
    elif flags["code"]:
        flags["web"] = True
        flags["intent"] = "code"
    elif flags["academic"]:
        flags["web"] = True
        flags["intent"] = "academic"
    elif flags["news"] and not flags["web"]:
        flags["intent"] = "news"
    elif any([flags["web"], flags["news"]]):
        flags["intent"] = "general"
    else:
        # auto-detect
        intent = detect_intent(query)
        flags.update(_INTENT_BACKENDS[intent])
        flags["intent"] = intent

    return query, flags


# ══════════════════════════════════════════════════════════════════════════════
# BACKENDS
# ══════════════════════════════════════════════════════════════════════════════

async def backend_ddg_web(query: str, max_results: int = 10) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            raw = await loop.run_in_executor(
                pool,
                lambda: list(DDGS().text(query, max_results=max_results))
            )
        return [
            {
                "title":   r.get("title", ""),
                "url":     r.get("href", ""),
                "snippet": r.get("body", ""),
                "source":  "web",
                "date":    "",
            }
            for r in raw if r.get("href")
        ]
    except Exception as e:
        print(f"[ddg_web] package failed ({e}), falling back to HTML")
        return await _ddg_web_html(query, max_results)


async def _ddg_web_html(query: str, max_results: int = 10) -> list[dict]:
    url     = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    headers = {"User-Agent": _FALLBACK_UA, "Accept-Language": "en-US,en;q=0.9"}
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as r:
                html = await r.text()
        soup    = BeautifulSoup(html, "lxml")
        results = []
        for a in soup.select(".result__a")[:max_results]:
            href   = a.get("href", "")
            parsed = urlparse(href)
            uddg   = parse_qs(parsed.query).get("uddg", [""])[0]
            real   = unquote(uddg) if uddg else href
            snip   = a.find_next(class_="result__snippet")
            results.append({
                "title":   a.get_text(strip=True),
                "url":     real,
                "snippet": snip.get_text(strip=True) if snip else "",
                "source":  "web",
                "date":    "",
            })
        return results
    except Exception as e:
        print(f"[ddg_web_html] {e}")
        return []


async def backend_ddg_news(query: str, max_results: int = 10) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            raw = await loop.run_in_executor(
                pool,
                lambda: list(DDGS().news(query, max_results=max_results))
            )
        return [
            {
                "title":   r.get("title", ""),
                "url":     r.get("url", ""),
                "snippet": r.get("body", ""),
                "source":  "news",
                "date":    r.get("date", ""),
            }
            for r in raw if r.get("url")
        ]
    except Exception as e:
        print(f"[ddg_news] {e}")
        return []


async def backend_stackoverflow(query: str, max_results: int = 8) -> list[dict]:
    url = (
        "https://api.stackexchange.com/2.3/search/advanced"
        f"?site=stackoverflow&q={quote_plus(query)}"
        f"&pagesize={max_results}&sort=relevance&order=desc&filter=default"
    )
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                data = await r.json()
        items = data.get("items", [])
        return [
            {
                "title":   item.get("title", ""),
                "url":     item.get("link", ""),
                "snippet": (
                    f"Score: {item.get('score', 0)}, "
                    f"Answers: {item.get('answer_count', 0)}. "
                    f"Tags: {', '.join((item.get('tags') or [])[:5])}"
                ),
                "source":  "stackoverflow",
                "date":    (
                    datetime.utcfromtimestamp(item["creation_date"]).strftime("%Y-%m-%d")
                    if item.get("creation_date") else ""
                ),
            }
            for item in items if item.get("link")
        ]
    except Exception as e:
        print(f"[stackoverflow] {e}")
        return []


async def backend_github(query: str, max_results: int = 8) -> list[dict]:
    url = (
        "https://api.github.com/search/repositories"
        f"?q={quote_plus(query)}&sort=stars&order=desc&per_page={max_results}"
    )
    headers = {
        "Accept":     "application/vnd.github.v3+json",
        "User-Agent": "OpenClaw-SearchBot/1.0",
    }
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as r:
                data = await r.json()
        items = data.get("items", [])
        return [
            {
                "title":   item.get("full_name", ""),
                "url":     item.get("html_url", ""),
                "snippet": (
                    f"{item.get('description') or ''}. "
                    f"⭐ {item.get('stargazers_count', 0)}, "
                    f"Lang: {item.get('language') or 'N/A'}"
                ),
                "source":  "github",
                "date":    (item.get("updated_at") or "")[:10],
            }
            for item in items if item.get("html_url")
        ]
    except Exception as e:
        print(f"[github] {e}")
        return []


async def backend_semantic_scholar(query: str, max_results: int = 8) -> list[dict]:
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={quote_plus(query)}&limit={max_results}"
        "&fields=title,abstract,url,year,authors,citationCount,openAccessPdf"
    )
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                data = await r.json()
        items = data.get("data", [])
        results = []
        for item in items:
            pdf  = item.get("openAccessPdf") or {}
            link = pdf.get("url") or item.get("url") or ""
            if not link:
                pid  = item.get("paperId", "")
                link = f"https://www.semanticscholar.org/paper/{pid}" if pid else ""
            authors = ", ".join(
                a.get("name", "") for a in (item.get("authors") or [])[:3]
            )
            abstract = (item.get("abstract") or "")[:200]
            results.append({
                "title":   item.get("title", ""),
                "url":     link,
                "snippet": (
                    f"({item.get('year', '')}) {authors}. "
                    f"Cited: {item.get('citationCount', 0)}. {abstract}"
                ),
                "source":  "academic",
                "date":    str(item.get("year", "")),
            })
        return results
    except Exception as e:
        print(f"[semantic_scholar] {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
# RESULT GATHERER
# ══════════════════════════════════════════════════════════════════════════════

async def gather_results(query: str, flags: dict) -> list[dict]:
    max_r  = 15 if flags.get("deep") else 8
    tasks  = []

    if flags.get("web"):      tasks.append(backend_ddg_web(query, max_r))
    if flags.get("news"):     tasks.append(backend_ddg_news(query, max_r))
    if flags.get("code"):
        tasks.append(backend_stackoverflow(query, max_r))
        tasks.append(backend_github(query, max_r))
    if flags.get("academic"): tasks.append(backend_semantic_scholar(query, max_r))

    all_lists = await asyncio.gather(*tasks, return_exceptions=True)

    seen, unique = set(), []
    for lst in all_lists:
        if not isinstance(lst, list):
            continue
        for r in lst:
            url = r.get("url", "")
            if url and url not in seen:
                seen.add(url)
                unique.append(r)

    return unique


# ══════════════════════════════════════════════════════════════════════════════
# NIM ENSEMBLE
# ══════════════════════════════════════════════════════════════════════════════

_SCORER_SYS = """\
You are a search result analyst. Given a query and a list of search results, evaluate \
each result for relevance, quality, and trustworthiness. Output JSON only — no markdown fences, \
no explanation — exactly matching this schema:
{
  "summary": "<2-3 sentence direct answer to the query based on the results>",
  "confidence": <float 0.0-1.0>,
  "top_result_indices": [<0-based indices of 5 best results ordered by relevance>],
  "scores": {"<index>": <float 0-10>, ...},
  "key_facts": ["<fact1>", "<fact2>", "<fact3>"],
  "caveats": ["<caveat>"],
  "follow_up_queries": ["<query1>", "<query2>"]
}
"""

def _scorer_user(query: str, results: list[dict]) -> str:
    lines = [f"QUERY: {query}\n\nRESULTS ({len(results)} total):"]
    for i, r in enumerate(results):
        src     = r.get("source", "web").upper()
        title   = r.get("title", "")
        url     = r.get("url", "")
        snippet = (r.get("snippet") or "")[:300]
        date    = f" [{r['date']}]" if r.get("date") else ""
        lines.append(f"[{i}] [{src}]{date} {title}\n    {url}\n    {snippet}")
    return "\n".join(lines)


async def _call_one_model(
    session: aiohttp.ClientSession,
    nim_key: str,
    model_cfg: dict,
    query: str,
    results: list[dict],
) -> dict | None:
    payload = {
        "model": model_cfg["id"],
        "messages": [
            {"role": "system", "content": _SCORER_SYS},
            {"role": "user",   "content": _scorer_user(query, results)},
        ],
        "temperature": 0.2,
        "max_tokens":  1024,
    }
    headers = {
        "Authorization": f"Bearer {nim_key}",
        "Content-Type":  "application/json",
    }
    t0 = time.monotonic()
    try:
        async with session.post(
            NIM_ENDPOINT, json=payload, headers=headers,
            timeout=aiohttp.ClientTimeout(total=model_cfg["timeout"]),
        ) as resp:
            data = await resp.json()
        elapsed = time.monotonic() - t0
        raw = data["choices"][0]["message"]["content"].strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        parsed               = json.loads(raw)
        parsed["_model"]     = model_cfg["label"]
        parsed["_weight"]    = model_cfg["weight"]
        parsed["_elapsed"]   = round(elapsed, 1)
        print(f"[ensemble] {model_cfg['label']} OK ({elapsed:.1f}s)")
        return parsed
    except Exception as e:
        print(f"[ensemble] {model_cfg['label']} failed: {e}")
        return None


async def run_ensemble(nim_key: str, query: str, results: list[dict]) -> list[dict]:
    print(f"[ensemble] firing {len(ENSEMBLE_MODELS)} models in parallel …")
    async with aiohttp.ClientSession() as session:
        outputs = await asyncio.gather(
            *[_call_one_model(session, nim_key, m, query, results) for m in ENSEMBLE_MODELS],
            return_exceptions=True,
        )
    valid = [o for o in outputs if isinstance(o, dict)]
    print(f"[ensemble] {len(valid)}/{len(ENSEMBLE_MODELS)} models responded")
    return valid


# ══════════════════════════════════════════════════════════════════════════════
# LOCAL FUSION FALLBACK
# ══════════════════════════════════════════════════════════════════════════════

def local_fusion(query: str, results: list[dict], model_outputs: list[dict]) -> dict:
    if not model_outputs:
        return {
            "summary":      f"Found {len(results)} results for: {query}",
            "confidence":   0.5,
            "key_facts":    [],
            "best_sources": [
                {"title": r["title"], "url": r["url"], "why": r.get("source", "")}
                for r in results[:5]
            ],
            "caveats":      ["No AI analysis available — NIM ensemble returned no output."],
            "follow_ups":   [],
            "top_results":  results[:5],
        }

    total_weight = sum(m["_weight"] for m in model_outputs)
    agg_scores: dict[int, float] = {}
    key_facts, follow_ups, caveats_all = [], [], []

    for m in model_outputs:
        w = m["_weight"]
        for idx_s, score in (m.get("scores") or {}).items():
            idx = int(idx_s)
            agg_scores[idx] = agg_scores.get(idx, 0) + float(score) * w
        key_facts.extend(m.get("key_facts") or [])
        follow_ups.extend(m.get("follow_up_queries") or [])
        caveats_all.extend(m.get("caveats") or [])

    if agg_scores:
        for k in agg_scores:
            agg_scores[k] /= total_weight

    best_model = max(model_outputs, key=lambda m: m["_weight"])
    summary    = best_model.get("summary", "")
    confidence = sum(
        (m.get("confidence") or 0.5) * m["_weight"] for m in model_outputs
    ) / total_weight

    ranked      = sorted(agg_scores.items(), key=lambda x: x[1], reverse=True)[:5]
    top_results = []
    for idx, score in ranked:
        if idx < len(results):
            r         = dict(results[idx])
            r["score"] = round(score / 10, 2)
            top_results.append(r)

    def dedup(lst: list[str]) -> list[str]:
        seen_d, out = set(), []
        for x in lst:
            k = x.lower()[:60]
            if k not in seen_d:
                seen_d.add(k); out.append(x)
        return out

    return {
        "summary":      summary,
        "confidence":   round(confidence, 2),
        "key_facts":    dedup(key_facts)[:6],
        "best_sources": [
            {"title": r["title"], "url": r["url"], "why": r.get("source", "")}
            for r in top_results
        ],
        "caveats":      dedup(caveats_all)[:3],
        "follow_ups":   dedup(follow_ups)[:4],
        "top_results":  top_results,
    }


# ══════════════════════════════════════════════════════════════════════════════
# KIMI-K2.6 FUSION
# ══════════════════════════════════════════════════════════════════════════════

_FUSION_SYS = """\
You are the final synthesis layer of a 6-model search intelligence ensemble.
Combine the analyses below into one authoritative, concise answer.
Output JSON only — no markdown fences, no explanation — exactly matching this schema:
{
  "summary": "<3-5 sentence comprehensive answer to the query>",
  "confidence": <float 0.0-1.0>,
  "key_facts": ["<fact>", ...(up to 6)],
  "best_sources": [{"title": "...", "url": "...", "why": "..."}, ...(up to 5)],
  "caveats": ["<caveat>", ...(up to 3)],
  "follow_ups": ["<query>", ...(up to 4)],
  "top_results": [
    {"title": "...", "url": "...", "snippet": "...", "source": "...", "score": <float 0.0-1.0>},
    ...(up to 5)
  ]
}
"""


async def fuse_with_kimi(
    nim_key: str,
    query: str,
    results: list[dict],
    model_outputs: list[dict],
) -> dict:
    analyses = "\n\n".join(
        f"=== {m['_model']} (weight={m['_weight']}, conf={m.get('confidence', 0):.2f}, {m['_elapsed']}s) ===\n"
        f"Summary: {m.get('summary', '')}\n"
        f"Key facts: {m.get('key_facts', [])}\n"
        f"Top indices: {m.get('top_result_indices', [])}\n"
        f"Caveats: {m.get('caveats', [])}\n"
        f"Follow-ups: {m.get('follow_up_queries', [])}"
        for m in model_outputs
    )
    # collect top-voted results for context
    top_idx: set[int] = set()
    for m in model_outputs:
        for i in (m.get("top_result_indices") or [])[:3]:
            if i < len(results):
                top_idx.add(i)
    top_ctx = "\n".join(
        f"[{results[i]['source'].upper()}] {results[i]['title']}\n"
        f"  {results[i]['url']}\n"
        f"  {(results[i].get('snippet') or '')[:200]}"
        for i in sorted(top_idx)
    )
    user_msg = (
        f"QUERY: {query}\n\n"
        f"ENSEMBLE ANALYSES:\n{analyses}\n\n"
        f"TOP RESULT CONTEXT:\n{top_ctx}"
    )
    payload = {
        "model": FUSION_MODEL,
        "messages": [
            {"role": "system", "content": _FUSION_SYS},
            {"role": "user",   "content": user_msg},
        ],
        "temperature": 0.0,
        "max_tokens":  2048,
    }
    headers = {
        "Authorization": f"Bearer {nim_key}",
        "Content-Type":  "application/json",
    }
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(
                NIM_ENDPOINT, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                data = await resp.json()
        raw = data["choices"][0]["message"]["content"].strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        fused = json.loads(raw)
        print("[kimi_fusion] OK")
        return fused
    except Exception as e:
        print(f"[kimi_fusion] failed ({e}), using local_fusion")
        return local_fusion(query, results, model_outputs)


# ══════════════════════════════════════════════════════════════════════════════
# FORMATTER
# ══════════════════════════════════════════════════════════════════════════════

def _status_card(query: str, intent: str, backends_used: list[str]) -> str:
    intent_emoji = _INTENT_EMOJI.get(intent, "🌐")
    backends_str = tg_escape(" · ".join(backends_used))
    return (
        f"🔍 {tg_escape(query)}\n"
        f"\n"
        f"{intent_emoji} Intent: `{intent}` · Backends: `{backends_str}`\n"
        f"⏳ _Running 6\\-model NIM ensemble\\.\\.\\._"
    )


def format_result(
    query: str,
    fused: dict,
    total_found: int,
    elapsed: float,
    flags: dict,
) -> str:
    conf   = float(fused.get("confidence") or 0.5)
    intent = flags.get("intent", "general")
    intent_emoji = _INTENT_EMOJI.get(intent, "🌐")

    backends_used = []
    if flags.get("web"):      backends_used.append("DDG Web")
    if flags.get("news"):     backends_used.append("DDG News")
    if flags.get("code"):     backends_used.append("SO\\+GitHub")
    if flags.get("academic"): backends_used.append("Semantic Scholar")

    card = (
        Card("🔍", query)
        .line(f"{intent_emoji} `{intent}` · {tg_escape(', '.join(b.replace('\\', '') for b in backends_used))} · {total_found} results · {round(elapsed)}s")
        .blank()
        .metric("📊 Confidence", _conf_bar(conf), f"{round(conf * 100)}%")
        .divider()
        .section("📝 *Summary*", [tg_escape((fused.get("summary") or "").strip())])
    )

    facts = fused.get("key_facts") or []
    if facts:
        card.bullets("💡 *Key Facts*", facts)

    sources = fused.get("best_sources") or []
    if sources:
        card.divider().links("🔗 *Best Sources*", sources)

    if not flags.get("brief"):
        top = fused.get("top_results") or []
        if top:
            card.result_rows("📋 *Top Results*", top, SOURCE_EMOJI)

    caveats = fused.get("caveats") or []
    if caveats:
        card.divider().bullets("⚠️ *Caveats*", caveats)

    follow_ups = fused.get("follow_ups") or []
    if follow_ups:
        card.code_queries("🔎 *Follow\\-up Queries*", follow_ups)

    card.footer(f"6\\-model NIM ensemble · Kimi\\-K2\\.6 fusion")

    return card.build()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def run_search(argv: list[str]) -> None:
    query, flags = parse_args(argv)

    if not query:
        print(
            "Usage: search.py <query> [--web] [--news] [--code] [--academic] "
            "[--all] [--brief] [--deep]"
        )
        return

    bot_token, chat_id, nim_key = load_openclaw_config()
    intent = flags.get("intent", "general")

    backends_preview = []
    if flags.get("web"):      backends_preview.append("DDG Web")
    if flags.get("news"):     backends_preview.append("DDG News")
    if flags.get("code"):     backends_preview.append("SO+GitHub")
    if flags.get("academic"): backends_preview.append("Semantic Scholar")

    print(f"[search] query={query!r} intent={intent} backends={backends_preview}")

    # ── Send immediate status card + typing indicator ─────────────────────────
    await send_typing(bot_token, chat_id)
    status_text  = _status_card(query, intent, backends_preview)
    status_msg_id = await send_message_with_id(bot_token, chat_id, status_text)

    t0 = time.monotonic()

    # ── Gather results ────────────────────────────────────────────────────────
    results = await gather_results(query, flags)
    print(f"[search] gathered {len(results)} results")

    if not results:
        no_results = f"🔍 *{tg_escape(query)}*\n\n❌ No results found\\."
        if status_msg_id:
            await edit_message(bot_token, chat_id, status_msg_id, no_results)
        else:
            async with aiohttp.ClientSession() as sess:
                await send_telegram(sess, bot_token, chat_id, no_results)
        return

    cap     = 30 if flags.get("deep") else 20
    results = results[:cap]

    # ── NIM ensemble ──────────────────────────────────────────────────────────
    model_outputs = await run_ensemble(nim_key, query, results)

    if model_outputs:
        fused = await fuse_with_kimi(nim_key, query, results, model_outputs)
    else:
        fused = local_fusion(query, results, [])

    elapsed = time.monotonic() - t0
    text    = format_result(query, fused, len(results), elapsed, flags)

    # ── Edit status card in-place, fall back to new message ──────────────────
    if status_msg_id:
        ok = await edit_message(bot_token, chat_id, status_msg_id, text)
        if not ok:
            async with aiohttp.ClientSession() as sess:
                await send_telegram(sess, bot_token, chat_id, text)
    else:
        async with aiohttp.ClientSession() as sess:
            await send_telegram(sess, bot_token, chat_id, text)

    print(f"[search] done in {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(run_search(sys.argv[1:]))
