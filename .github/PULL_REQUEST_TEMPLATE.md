<!-- Thanks for the contribution. Fill in what's relevant; skip the rest. -->

## Summary

<!-- 1-3 sentences. What does this PR change and why? -->

## Type of change

- [ ] Bug fix
- [ ] New skill or agent
- [ ] Refactor (no functional change)
- [ ] Docs / CI / tooling
- [ ] Security hardening

## Test plan

- [ ] `pytest -q` passes locally
- [ ] `ruff check core tests` passes
- [ ] If touching a skill: ran the CLI smoke command listed in its SKILL.md
- [ ] If touching `core.config` or auth: added/updated unit tests
- [ ] If touching CI workflows: triggered with `workflow_dispatch` and confirmed green

## Security checklist

- [ ] No new secrets committed (verified with `gitleaks detect --redact -v`)
- [ ] No new permissions added to `.claude/settings.json` without justification
- [ ] No new external network sinks (telemetry, analytics) without explicit opt-in

## Linked issues

<!-- Closes #123, Fixes #456 -->
