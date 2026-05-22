# Security Policy

OpenClaw Lab is a personal AI lab that — when deployed — talks to a remote
LLM provider, exposes a Telegram bot, runs shell commands on behalf of the
operator, and persists data to disk. Treating it as security-critical from
day one is the only sane default.

## Supported versions

Only the `main` branch is actively maintained. Tagged releases prior to 1.0
are not patched.

## Reporting a vulnerability

Open a **private security advisory** at
[github.com/eyasir329/openclaw-lab/security/advisories/new](https://github.com/eyasir329/openclaw-lab/security/advisories/new).

Please do **not** open a public issue for security problems. Expect
acknowledgement within 7 days and a fix or written rationale within 30 days
for high-severity issues.

In your report, include:

1. A minimal reproduction (commands, config, observed output).
2. The expected behaviour and the impact.
3. Whether you have shared the issue with anyone else.

## Threat model

| Asset | Threat | Mitigation in this repo |
| --- | --- | --- |
| `NVIDIA_API_KEY` | Stolen via committed file or log | `.gitignore`, `gitleaks` CI, `core.logging` redaction |
| Telegram bot token | Same | `.env.example` only, never committed |
| Operator filesystem | Arbitrary shell via unrestricted bot | `core.auth` allowlist enforcement |
| Claude Code session | Approved-once permissions creep into shared state | `.claude/settings.json` deny-list + `.claude/settings.local.json` gitignored |
| Audit log | Sensitive prompts/tokens leaked into logs | `core.logging._redact` strips known-sensitive keys |
| Git history | Secret pushed in commit n then "fixed" in n+1 | weekly scheduled `gitleaks` run over full history |

## Hardening checklist for new deployments

1. **Set `ALLOWED_TG_USER_IDS`.** Without it the bot rejects every message
   (fail-closed). Find your user id with `@userinfobot`.
2. **Audit committed permissions.** Open `.claude/settings.json` and confirm
   nothing in the `allow` list is broader than you intend.
3. **Run a gitleaks scan before pushing.**
   `gitleaks detect --config .gitleaks.toml --redact -v`.
4. **Rotate `NVIDIA_API_KEY` if it ever appears in any log, screenshot, or
   support ticket.** NVIDIA keys are individually scoped; rotation is cheap.
5. **Never copy `~/.openclaw/openclaw.json` out of the host.** It contains
   the bot token and chat ids.

## Secret patterns scanned

`.gitleaks.toml` extends the upstream default ruleset with two
project-specific patterns:

- `nvapi-[A-Za-z0-9_\-]{20,}` — NVIDIA NIM keys
- `\d{8,12}:[A-Za-z0-9_\-]{30,}` — Telegram bot tokens

Placeholders in `.env.example` and docs are explicitly allow-listed so they
never trip the scanner.

## Out of scope

- Issues in upstream dependencies (file those against the project directly).
- Misuse of the lab as a tool against third parties — that is operator
  responsibility, not a vulnerability in this repo.
- Bot bugs reachable only when `ALLOWED_TG_USER_IDS` is unset (the
  documented fail-closed default exists precisely so this cannot happen).
