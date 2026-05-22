"""
core.logging — JSONL structured audit log.

Append-only event stream. One JSON object per line. Designed for cheap
post-hoc analysis (jq, sqlite-utils, pandas) and for tailing during incidents.

Events to log:
    * `skill.invoke`     — a skill started
    * `skill.complete`   — a skill finished (success or error)
    * `nim.call`         — a single NIM API call (model, elapsed, tokens, ok)
    * `auth.deny`        — a denied Telegram user attempt
    * `auth.allow`       — an allowed Telegram user invocation
    * `gateway.error`    — gateway / framework error caught at boundary

Sensitive fields (api keys, bot tokens, full prompts) are NEVER logged. The
caller is responsible for shaping payloads — this module just appends.

Usage:
    from core.logging import audit_log
    audit_log("skill.invoke", skill="job-search", trigger="cli")

The log path is resolved lazily from `core.config.cached_runtime_config()`
so tests can redirect via the OPENCLAW_AUDIT_LOG env var.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .config import cached_runtime_config


# ── Path resolution ───────────────────────────────────────────────────────────

def _resolve_log_path() -> Path:
    raw = os.environ.get("OPENCLAW_AUDIT_LOG")
    if raw:
        return Path(raw).expanduser()
    try:
        return cached_runtime_config().audit_log_path
    except EnvironmentError:
        here = Path(__file__).resolve().parent.parent
        return here / "logs" / "audit.jsonl"


# ── Sensitive field redaction ─────────────────────────────────────────────────

_SENSITIVE_KEYS = frozenset({
    "api_key", "apikey", "nim_api_key", "nvidia_api_key",
    "bot_token", "telegram_bot_token", "token",
    "password", "secret", "authorization",
    "prompt", "user_message", "system_prompt",
})


def _redact(value: Any) -> Any:
    """
    Recursively strip sensitive keys. Top-level callers should still avoid
    passing raw prompts/keys — this is defense in depth, not the primary line.
    """
    if isinstance(value, dict):
        return {
            k: ("***REDACTED***" if k.lower() in _SENSITIVE_KEYS else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


# ── Public API ────────────────────────────────────────────────────────────────

def audit_log(event: str, **fields: Any) -> None:
    """
    Append one JSONL event. Never raises — logging failures are silent so a
    failed write can't take down a skill.

    Each line has:
        ts      — float seconds since epoch (UTC)
        event   — string event name (caller-defined)
        pid     — process id (correlates lines from same run)
        ...     — caller-supplied fields, recursively redacted
    """
    record = {
        "ts": round(time.time(), 3),
        "event": event,
        "pid": os.getpid(),
        **_redact(fields),
    }
    try:
        path = _resolve_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        # Last-resort: surface to stderr so it's visible in `openclaw status`
        # logs without breaking the calling skill.
        try:
            sys.stderr.write(f"[audit_log] write failed: {type(e).__name__}: {e}\n")
        except Exception:
            pass


def audit_log_path() -> Path:
    """Resolved audit log path (exposed for inspection / tailing)."""
    return _resolve_log_path()


__all__ = ["audit_log", "audit_log_path"]
