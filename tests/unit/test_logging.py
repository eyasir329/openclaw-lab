"""Tests for core.logging — JSONL writer + redaction."""

from __future__ import annotations

import json
from pathlib import Path

from core.logging import audit_log, audit_log_path


def _read_log(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_audit_log_appends_jsonl(tmp_path, monkeypatch):
    log = tmp_path / "audit.jsonl"
    monkeypatch.setenv("OPENCLAW_AUDIT_LOG", str(log))

    audit_log("skill.invoke", skill="review", target="diff-HEAD")
    audit_log("skill.complete", skill="review", elapsed_secs=4.2)

    records = _read_log(log)
    assert len(records) == 2
    assert records[0]["event"] == "skill.invoke"
    assert records[0]["skill"] == "review"
    assert records[1]["event"] == "skill.complete"
    assert records[1]["elapsed_secs"] == 4.2
    for r in records:
        assert "ts" in r
        assert "pid" in r


def test_audit_log_redacts_sensitive_top_level(tmp_path, monkeypatch):
    log = tmp_path / "a.jsonl"
    monkeypatch.setenv("OPENCLAW_AUDIT_LOG", str(log))

    audit_log("nim.call", model="x", api_key="nvapi-secret", token="bot:xxx")
    rec = _read_log(log)[0]
    assert rec["api_key"] == "***REDACTED***"
    assert rec["token"] == "***REDACTED***"
    assert rec["model"] == "x"


def test_audit_log_redacts_sensitive_nested(tmp_path, monkeypatch):
    log = tmp_path / "a.jsonl"
    monkeypatch.setenv("OPENCLAW_AUDIT_LOG", str(log))

    audit_log("foo", payload={"prompt": "leaked", "ok": True, "nested": {"secret": "x"}})
    rec = _read_log(log)[0]
    assert rec["payload"]["prompt"] == "***REDACTED***"
    assert rec["payload"]["ok"] is True
    assert rec["payload"]["nested"]["secret"] == "***REDACTED***"


def test_audit_log_path_resolves_from_env(tmp_path, monkeypatch):
    log = tmp_path / "custom.jsonl"
    monkeypatch.setenv("OPENCLAW_AUDIT_LOG", str(log))
    assert audit_log_path() == log


def test_audit_log_never_raises_on_write_failure(monkeypatch):
    """Even if the log path is unwritable, audit_log must not throw."""
    monkeypatch.setenv("OPENCLAW_AUDIT_LOG", "/nope/this/will/never/exist/audit.jsonl")
    audit_log("event")  # must not raise
