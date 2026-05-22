"""Tests for core.auth — Telegram allowlist enforcement."""

from __future__ import annotations

import pytest

from core.auth import (
    TelegramAuthError,
    allowlist_is_empty,
    ensure_allowed,
    format_denial,
    is_allowed,
)


def test_is_allowed_rejects_none(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-x")
    monkeypatch.setenv("ALLOWED_TG_USER_IDS", "111,222")
    assert is_allowed(None) is False


def test_is_allowed_accepts_member(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-x")
    monkeypatch.setenv("ALLOWED_TG_USER_IDS", "111,222")
    assert is_allowed(111) is True
    assert is_allowed("222") is True


def test_is_allowed_rejects_non_member(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-x")
    monkeypatch.setenv("ALLOWED_TG_USER_IDS", "111")
    assert is_allowed(999) is False


def test_is_allowed_fails_closed_when_allowlist_empty(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-x")
    # No ALLOWED_TG_USER_IDS set
    assert is_allowed(111) is False
    assert allowlist_is_empty() is True


def test_ensure_allowed_raises_on_denial(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-x")
    monkeypatch.setenv("ALLOWED_TG_USER_IDS", "111")
    with pytest.raises(TelegramAuthError):
        ensure_allowed(222)


def test_ensure_allowed_silent_on_match(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-x")
    monkeypatch.setenv("ALLOWED_TG_USER_IDS", "111")
    ensure_allowed(111)  # must not raise


def test_is_allowed_handles_non_numeric(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-x")
    monkeypatch.setenv("ALLOWED_TG_USER_IDS", "111")
    assert is_allowed("not_a_number") is False
    assert is_allowed([1, 2]) is False  # type: ignore[arg-type]


def test_format_denial_does_not_leak_allowlist(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-x")
    monkeypatch.setenv("ALLOWED_TG_USER_IDS", "111,222")
    msg = format_denial(999)
    assert "111" not in msg
    assert "222" not in msg
    assert "999" not in msg
