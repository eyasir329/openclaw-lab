"""Tests for core.nim_client — JSON parsing + fence stripping (no live API)."""

from __future__ import annotations

from core.nim_client import NIMResult, strip_fences, try_parse_json


def test_strip_fences_removes_json_fence():
    raw = "```json\n[1, 2, 3]\n```"
    assert strip_fences(raw) == "[1, 2, 3]"


def test_strip_fences_removes_bare_fence():
    raw = "```\n{\"k\": 1}\n```"
    assert strip_fences(raw) == '{"k": 1}'


def test_strip_fences_passthrough_unfenced():
    assert strip_fences('{"k": 1}') == '{"k": 1}'


def test_try_parse_json_clean_object():
    assert try_parse_json('{"k": 1}') == {"k": 1}


def test_try_parse_json_with_fences():
    assert try_parse_json("```json\n[\"a\"]\n```") == ["a"]


def test_try_parse_json_recovers_from_prose_prefix():
    raw = "Sure! Here is the answer:\n\n[{\"x\": 1}, {\"x\": 2}]"
    parsed = try_parse_json(raw)
    assert parsed == [{"x": 1}, {"x": 2}]


def test_try_parse_json_returns_none_on_garbage():
    assert try_parse_json("totally not json — sorry") is None


def test_try_parse_json_empty_returns_none():
    assert try_parse_json("") is None
    assert try_parse_json("   \n  ") is None


def test_nim_result_default_state():
    r = NIMResult(ok=False, model="m", elapsed_secs=1.0)
    assert r.content == ""
    assert r.parsed is None
    assert r.usage == {}
    assert r.http_status == 0
