# Changelog

All notable changes will be recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Dates are
ISO-8601.

## [1.0.0] — 2026-05-22

First production-ready release. Restructure + harden pass.

### Added

- `core/` shared library: `config`, `nim_client`, `ensemble`, `auth`,
  `logging`, `cost`. Pure-Python, side-effect-free imports.
- `skills/review/` — ensemble code review CLI (`python skills/review/review.py`).
  Targets diff / branch / file / PR.
- `skills/research/` — ensemble deep-research CLI with long-form briefing
  output (summary, key findings, conflicting claims, follow-ups).
- 47 unit tests under `tests/unit/` covering all of `core/`.
- `.github/workflows/`:
  - `ci.yml` — pytest + ruff + node hook syntax check on every push.
  - `secret-scan.yml` — `gitleaks` on every push + weekly cron.
  - `codeql.yml` — Python + JavaScript static analysis.
- `.github/dependabot.yml`, PR / issue templates, `CODEOWNERS`.
- `.gitleaks.toml` with project-specific patterns (`nvapi-...`, Telegram
  bot tokens) and placeholder allowlist.
- `.claude/settings.json` — team-shared Claude Code policy with explicit
  `allow` and `deny` lists.
- `.env.example` documenting every env var the lab consumes.
- `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`, `docs/CONTRIBUTING.md`,
  this file, top-level `SECURITY.md`, `LICENSE` (MIT).
- `pyproject.toml` with pytest + ruff + mypy config and the dev extras.

### Changed

- `.gitignore` rewritten: now excludes `.env*`, `data/*.db`, `logs/*`,
  `workspace/*`, `auth-profiles.json`, gitleaks artefacts, Python /
  Node build outputs.
- `skills/common/tg.py` delegates `load_config()` to `core.config` —
  back-compat preserved.
- README updated to reference new skills, docs, and security posture.

### Security

- Telegram allowlist (`core.auth`) is **fail-closed**: empty allowlist
  rejects every user.
- Audit log redacts known-sensitive keys (`api_key`, `prompt`, `token`,
  `password`, …) recursively before writing.
- Claude Code permissions include explicit deny rules for `rm -rf /`,
  `git push --force`, secret-leaking `printenv` patterns, and reading
  `~/.openclaw/agents/main/agent/auth-profiles.json`.
