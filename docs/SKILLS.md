# Skills reference

Every skill is a self-contained directory under `skills/`. Each ships a
`SKILL.md` (trigger phrases + output spec) and, when applicable, a Python
CLI entry point.

| Skill | CLI | Backed by ensemble | Daily-work use |
| --- | --- | --- | --- |
| [caveman](../skills/caveman/SKILL.md) | n/a | no | ~75% token reduction communication mode |
| [caveman-commit](../skills/caveman-commit/SKILL.md) | n/a | no | Conventional Commits message generator |
| [caveman-compress](../skills/caveman-compress/SKILL.md) | `python -m skills.caveman_compress.scripts.cli <file>` | no | Compress markdown/text memory files |
| [caveman-review](../skills/caveman-review/SKILL.md) | n/a | no | Code review comment style |
| [caveman-stats](../skills/caveman-stats/SKILL.md) | n/a | no | Token usage stats |
| [cavecrew](../skills/cavecrew/SKILL.md) | n/a | no | Subagent delegation guide |
| [job-search](../skills/job-search/SKILL.md) | `python skills/job-search/job_search.py [tier1|fresh|...]` | **yes** | BD CSE job scraping (career pages + boards + social) |
| [search](../skills/search/SKILL.md) | `python skills/search/search.py "<query>" [--web|--news|--code|--academic|--all|--deep]` | **yes** | Multi-backend web search with fusion |
| [research](../skills/research/SKILL.md) | `python skills/research/research.py "<question>" [--academic|--json]` | **yes** | Deep-research briefing with citations |
| [review](../skills/review/SKILL.md) | `python skills/review/review.py [target|--pr|--json]` | **yes** | Ensemble code review for diff / branch / file |

## Daily-work matrix

| If you're doing… | Use this |
| --- | --- |
| Code review (own PR or someone else's) | `/review` or `python skills/review/review.py --pr` |
| Hunting for a job posting | `/job_search` or `/job_search_tier1` |
| Quick "what is X?" | `/search` |
| "Give me a briefing on X with citations" | `/research` |
| Need a commit message | `/caveman-commit` (let it look at the staged diff) |
| Reduce token usage in a long session | `/caveman ultra` |

## Ensemble skills — what changed in 1.0

`job-search` and `search` were the original ensemble-using skills. Their
ensemble code was duplicated. In 1.0 both share the implementation in
`core/ensemble.py`. New skills (`research`, `review`) build on the same
primitive — same six models, same Kimi-K2.6 fusion, same local fallback.

If you want to call the ensemble from a one-off script:

```python
import asyncio, aiohttp, sys
sys.path.insert(0, '.')
from core.config import load_runtime_config
from core.ensemble import run_ensemble, DEFAULT_ENSEMBLE

async def main():
    rc = load_runtime_config()
    async with aiohttp.ClientSession() as session:
        result = await run_ensemble(
            session, rc.nim_api_key,
            scorer_system="You are a JSON-emitting analyst...",
            scorer_user="Question: ...",
            fusion_system="Fuse the analyses...",
            models=DEFAULT_ENSEMBLE,
        )
    print(result.fusion_source, result.total_elapsed_secs, result.fused)

asyncio.run(main())
```

See `core/ensemble.py` for full parameter docs.
