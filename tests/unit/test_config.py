"""Tests for core.config — env + file-based runtime config resolution."""

from __future__ import annotations

import pytest

from core.config import RuntimeConfig, load_runtime_config


def test_load_runtime_config_requires_nim_key_by_default():
    with pytest.raises(EnvironmentError, match="NVIDIA_API_KEY"):
        load_runtime_config()


def test_load_runtime_config_skipping_nim_returns_empty_key(monkeypatch):
    rc = load_runtime_config(require_nim=False)
    assert isinstance(rc, RuntimeConfig)
    assert rc.nim_api_key == ""


def test_env_overrides_chat_id(monkeypatch, temp_openclaw_json):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-fake")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456")
    temp_openclaw_json({"channels": {"telegram": {"chatId": "999999"}}})

    rc = load_runtime_config()
    assert rc.chat_id == "123456"  # env wins over file


def test_chat_id_falls_back_to_owner_allow_from(monkeypatch, temp_openclaw_json):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-fake")
    temp_openclaw_json(
        {"commands": {"ownerAllowFrom": ["telegram:777", "discord:nope"]}}
    )

    rc = load_runtime_config()
    assert rc.chat_id == "777"


def test_allowlist_merges_env_and_file(monkeypatch, temp_openclaw_json):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-fake")
    monkeypatch.setenv("ALLOWED_TG_USER_IDS", "111, 222 ,333")
    temp_openclaw_json(
        {"channels": {"telegram": {"allowedUsers": [222, 444, "555"]}}}
    )

    rc = load_runtime_config()
    assert rc.allowed_user_ids == frozenset({111, 222, 333, 444, 555})


def test_allowlist_drops_garbage(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-fake")
    monkeypatch.setenv("ALLOWED_TG_USER_IDS", "abc,,,,123,xx-99")

    rc = load_runtime_config()
    assert rc.allowed_user_ids == frozenset({123})


def test_redacted_masks_secrets(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-1234567890abcdef")
    rc = load_runtime_config()
    redacted = rc.redacted()
    assert "1234567890" not in redacted["nim_api_key"]
    assert redacted["nim_api_key"].startswith("nvapi-")
    assert "…" in redacted["nim_api_key"]


def test_caveman_model_uses_env(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-fake")
    monkeypatch.setenv("CAVEMAN_MODEL", "nvidia/openai/gpt-oss-120b")
    rc = load_runtime_config()
    assert rc.caveman_model == "nvidia/openai/gpt-oss-120b"
