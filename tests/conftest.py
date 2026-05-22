"""
Shared pytest fixtures + sys.path setup.

This file makes the repo root importable so tests can `from core.* import …`
regardless of where pytest is invoked from.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """
    Each test starts with a clean OpenClaw env. Tests that need vars set them
    explicitly via monkeypatch.setenv().
    """
    for var in (
        "NVIDIA_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "ALLOWED_TG_USER_IDS",
        "OPENCLAW_AUDIT_LOG",
        "CAVEMAN_MODEL",
        "CAVEMAN_DEFAULT_MODE",
    ):
        monkeypatch.delenv(var, raising=False)

    monkeypatch.setenv("OPENCLAW_AUDIT_LOG", str(tmp_path / "audit.jsonl"))

    from core.config import cached_runtime_config
    cached_runtime_config.cache_clear()
    yield
    cached_runtime_config.cache_clear()


@pytest.fixture
def temp_openclaw_json(tmp_path, monkeypatch):
    """
    Returns a writer fn — write({...}) drops a fake openclaw.json into a
    temp dir and points core.config at it. Useful when a test needs the
    file-loader path without touching $HOME.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_cfg_dir = fake_home / ".openclaw"
    fake_cfg_dir.mkdir()
    fake_cfg = fake_cfg_dir / "openclaw.json"

    import core.config as config_mod
    monkeypatch.setattr(config_mod, "OPENCLAW_CONFIG_PATH", fake_cfg)

    def writer(payload: dict) -> Path:
        import json
        fake_cfg.write_text(json.dumps(payload))
        config_mod.cached_runtime_config.cache_clear()
        return fake_cfg

    return writer
