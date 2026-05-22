"""
OpenClaw Lab — shared core library.

Public modules:
    core.config     — env + ~/.openclaw/openclaw.json loader
    core.nim_client — single-call NIM API wrapper (retry, structured)
    core.ensemble   — N-model parallel scoring + Kimi-K2.6 fusion
    core.auth       — Telegram user allowlist verifier
    core.logging    — JSONL structured audit logger
    core.cost       — rough NIM cost / token accounting

All modules are import-time side-effect free. Configuration is resolved lazily
on first call so test fixtures can swap env vars before anything reads them.
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["config", "nim_client", "ensemble", "auth", "logging", "cost"]
