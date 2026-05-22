"""
core.config — resolve runtime configuration from env + ~/.openclaw/openclaw.json.

Precedence (high → low):
    1. Function args / explicit override
    2. Environment variables
    3. ~/.openclaw/openclaw.json keys
    4. Hard-coded defaults

Never raises during import. Errors are raised lazily on `load_*` call so test
suites and CI can import this module without a populated environment.

NIM API key is *never* read from the config file — env only. The config file
is meant to be shared/synced; the key is per-machine.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


# ── Paths ─────────────────────────────────────────────────────────────────────

OPENCLAW_CONFIG_PATH = Path.home() / ".openclaw" / "openclaw.json"
NIM_ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
NIM_MODELS_ENDPOINT = "https://integrate.api.nvidia.com/v1/models"


# ── Public dataclasses ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RuntimeConfig:
    """Resolved configuration. Never persisted; built on demand."""

    nim_api_key: str
    bot_token: str
    chat_id: str
    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)
    audit_log_path: Path = Path("logs/audit.jsonl")
    nim_endpoint: str = NIM_ENDPOINT
    caveman_model: str = "nvidia/nemotron-3-super-120b-a12b"

    def redacted(self) -> dict[str, Any]:
        """Return a dict safe to log — keys/tokens are masked."""
        def mask(s: str) -> str:
            if not s:
                return ""
            return s[:6] + "…" + s[-2:] if len(s) > 10 else "…"

        return {
            "nim_api_key": mask(self.nim_api_key),
            "bot_token": mask(self.bot_token),
            "chat_id": self.chat_id,
            "allowed_user_ids": sorted(self.allowed_user_ids),
            "audit_log_path": str(self.audit_log_path),
            "nim_endpoint": self.nim_endpoint,
            "caveman_model": self.caveman_model,
        }


# ── Loaders ───────────────────────────────────────────────────────────────────

def _read_openclaw_json(path: Path | None = None) -> dict[str, Any]:
    # Look up the module attribute lazily so tests that monkeypatch
    # `core.config.OPENCLAW_CONFIG_PATH` are honored.
    target = path if path is not None else OPENCLAW_CONFIG_PATH
    if not target.exists():
        return {}
    try:
        with target.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _resolve_chat_id(cfg: dict[str, Any]) -> str:
    env_value = os.environ.get("TELEGRAM_CHAT_ID")
    if env_value:
        return str(env_value)
    tg = cfg.get("channels", {}).get("telegram", {})
    if tg.get("chatId"):
        return str(tg["chatId"])
    for entry in cfg.get("commands", {}).get("ownerAllowFrom", []) or []:
        if isinstance(entry, str) and entry.startswith("telegram:"):
            return entry.split(":", 1)[1]
    return ""


def _resolve_allowed_users(cfg: dict[str, Any]) -> frozenset[int]:
    raw = os.environ.get("ALLOWED_TG_USER_IDS", "")
    ids: set[int] = set()
    for token in raw.split(","):
        token = token.strip()
        if token.isdigit():
            ids.add(int(token))
    for entry in cfg.get("channels", {}).get("telegram", {}).get("allowedUsers", []) or []:
        try:
            ids.add(int(entry))
        except (TypeError, ValueError):
            continue
    return frozenset(ids)


def _resolve_audit_path() -> Path:
    raw = os.environ.get("OPENCLAW_AUDIT_LOG")
    if raw:
        return Path(raw).expanduser()
    here = Path(__file__).resolve().parent.parent
    return here / "logs" / "audit.jsonl"


def load_runtime_config(*, require_nim: bool = True) -> RuntimeConfig:
    """
    Resolve full runtime config. Raises EnvironmentError if `require_nim` and
    `NVIDIA_API_KEY` is missing (the common case for live API skills).
    """
    # Re-read the module attribute so test fixtures can swap the config path.
    import core.config as _self
    cfg = _read_openclaw_json(_self.OPENCLAW_CONFIG_PATH)

    nim_key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if require_nim and not nim_key:
        raise EnvironmentError(
            "NVIDIA_API_KEY is not set. Export it or add to Codespaces secrets:\n"
            "  export NVIDIA_API_KEY=nvapi-...\n"
            "Get a free key at: https://build.nvidia.com"
        )

    bot_token = (
        os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        or cfg.get("channels", {}).get("telegram", {}).get("botToken", "")
    )

    return RuntimeConfig(
        nim_api_key=nim_key,
        bot_token=bot_token,
        chat_id=_resolve_chat_id(cfg),
        allowed_user_ids=_resolve_allowed_users(cfg),
        audit_log_path=_resolve_audit_path(),
        caveman_model=os.environ.get(
            "CAVEMAN_MODEL", "nvidia/nemotron-3-super-120b-a12b"
        ),
    )


# ── Back-compat shim ──────────────────────────────────────────────────────────

def load_config() -> tuple[str, str, str]:
    """
    Legacy 3-tuple loader: (bot_token, chat_id, nim_api_key).

    Kept so existing skills that imported from `common.tg` continue to work
    after the refactor. New code should prefer `load_runtime_config()`.
    """
    rc = load_runtime_config(require_nim=True)
    return rc.bot_token, rc.chat_id, rc.nim_api_key


# ── Cached accessor for hot paths ─────────────────────────────────────────────

@lru_cache(maxsize=1)
def cached_runtime_config() -> RuntimeConfig:
    """Memoized runtime config. Clear with `cached_runtime_config.cache_clear()`."""
    return load_runtime_config()
