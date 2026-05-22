---
name: search
description: >
  General-purpose multi-backend search for any query.
  Backends: DDG Web, DDG News, Stack Overflow, GitHub, Semantic Scholar.
  6-model NVIDIA NIM parallel ensemble + Kimi-K2.6 fusion.
  Telegram MarkdownV2 cards with confidence bar, key facts, best sources, caveats, follow-up queries.
---

Unified search skill for any topic — tech, news, code, academic papers.
Runs selected backends concurrently, scores all results with a 6-model NIM ensemble,
fuses with Kimi-K2.6 at temperature=0, then sends a structured card to Telegram.

## Trigger
/search <query> [flags]

## Flags
| Flag         | Backends activated                         |
|--------------|--------------------------------------------|
| (none)       | DDG Web + DDG News (default)               |
| `--web`      | DDG Web                                    |
| `--news`     | DDG News                                   |
| `--code`     | GitHub + Stack Overflow + DDG Web          |
| `--academic` | Semantic Scholar + DDG Web                 |
| `--all`      | All 5 backends                             |
| `--brief`    | Skip top-results section (shorter card)    |
| `--deep`     | Fetch more results per backend (max 15)    |

## Telegram slash commands
/search <query>             — web + news (default)
/search_news <query>        — DDG News only
/search_code <query>        — GitHub + Stack Overflow + web
/search_deep <query>        — all backends, deep mode

## Executor
skills/search/search.py

## Sources
| Backend           | Type     | API / Method                            |
|-------------------|----------|-----------------------------------------|
| DDG Web           | Web      | duckduckgo-search DDGS().text()         |
| DDG News          | News     | duckduckgo-search DDGS().news()         |
| Stack Overflow    | Code Q&A | api.stackexchange.com/2.3/search        |
| GitHub            | Code     | api.github.com/search/repositories      |
| Semantic Scholar  | Academic | api.semanticscholar.org/graph/v1/paper  |

## Output Card Format
🔍 *Query*
📊 Confidence: ████████░░ 85%
📝 Summary (3-5 sentences)
💡 Key Facts (up to 6)
🔗 Best Sources (up to 5, with why)
📋 Top Results (scored, with snippet)
⚠️ Caveats
🔎 Follow-up Queries
🤖 Footer (models used, elapsed)

## Notes
- NIM ensemble: 6 models in parallel (see search.py ENSEMBLE_MODELS)
- Fusion: moonshotai/kimi-k2.6 at temperature=0.0
- Fallback: local_fusion() if Kimi API fails
- DDG fallback: HTML scraping if duckduckgo-search package unavailable
- GitHub/SO: unauthenticated (rate-limited to ~60 req/hr)
