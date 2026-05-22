# Contributing

This is a personal lab, but PRs that harden it, add useful skills, or improve
docs are welcome.

## Quick start

```bash
git clone https://github.com/eyasir329/openclaw-lab.git
cd openclaw-lab
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ruff check core tests
```

If you only intend to touch markdown / workflows, you can skip the venv.

## Before opening a PR

1. **Tests pass.** `pytest -q`
2. **Lint passes.** `ruff check core tests skills/review skills/research`
3. **No secrets.** `gitleaks detect --config .gitleaks.toml --redact -v`
4. **One concern per PR.** Refactor + feature in the same PR is hard to
   review. Split it.
5. **Update docs.** If you add a CLI flag, edit the relevant `SKILL.md`. If
   you change architecture, edit `docs/ARCHITECTURE.md`.

## What lives where

- **New runtime primitive** (config loader, NIM helper, ensemble tweak) →
  `core/`. Must come with tests.
- **New skill** → `skills/<name>/SKILL.md` + `<name>.py`. Must use `core/`
  for ensemble and audit logging. Add a CLI smoke command to the SKILL.md.
- **Claude Code hook** → `src/hooks/`. Must syntax-check (`node --check`)
  in CI.
- **Long-form docs** → `docs/`. Short reference docs → top of the relevant
  source file as a module docstring.

## Code style

### Python

- 3.11+. Type hints encouraged, not enforced.
- `from __future__ import annotations` at the top of every module.
- Dataclasses for value types; not for stateful machines.
- Side-effect-free imports — load config and open files inside `run_*` or
  fixtures, not at module top level.
- Tolerant of partial failure: every external call returns a Result-like
  object, never a raise that crashes the run.

### JavaScript (hooks)

- CommonJS. Node 24 target.
- Silent-on-failure for `optional` work (statusline, statistics).
- No new external runtime dependencies in hooks — they must keep working
  in offline Codespaces.

## Commit messages

Follow Conventional Commits (the `/caveman-commit` skill writes them too):

```
<type>(<scope>): <imperative summary, ≤50 chars>

<optional body — explain why, not what>
```

Types: `feat` `fix` `refactor` `perf` `docs` `test` `chore` `build` `ci`
`style` `revert`.

Examples:

- `feat(skills): add /research deep-research skill`
- `fix(ensemble): handle empty model outputs without div/0`
- `docs(deploy): clarify ALLOWED_TG_USER_IDS fail-closed behaviour`

## Adding tests

- New module ⇒ new `tests/unit/test_<module>.py`.
- Live API calls go behind `@pytest.mark.integration` and are not run in
  CI. Real keys are *never* in the test environment.
- Use the `temp_openclaw_json` fixture if you need a fake config file.

## Reviewing

The lab uses the `cavecrew-reviewer` agent locally and full
`/ultrareview` for serious PRs. Reviewers should:

- Focus on correctness and security. Style nits go to ruff, not human
  reviewers.
- Verify any new permission entry in `.claude/settings.json` is minimal.
- Verify any new external HTTP endpoint is documented in
  `docs/ARCHITECTURE.md`.

## Release / version bump

Single-author lab; no formal release cycle. When the user-visible API
changes, bump `__version__` in `core/__init__.py` and add a `CHANGELOG.md`
entry.
