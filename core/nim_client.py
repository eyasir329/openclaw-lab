"""
core.nim_client — single-call NIM (NVIDIA NIM / OpenAI-compatible) wrapper.

Design goals:
    * Pure-async (aiohttp). Skills are already async.
    * Structured result: success/failure plus elapsed/usage metadata.
    * No retry loop *inside* the call — caller decides. Most skills want
      `asyncio.gather` over N parallel calls, then accept partial failure.
    * Strips ```json fences on parsing; the calling skill chooses raw vs JSON.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .config import NIM_ENDPOINT


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class NIMResult:
    """Single NIM call outcome. `ok=False` ⇒ caller drops or retries."""

    ok: bool
    model: str
    elapsed_secs: float
    content: str = ""
    parsed: Any = None
    error: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    http_status: int = 0


# ── Helpers ───────────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*|\s*```\s*$", re.MULTILINE)


def strip_fences(s: str) -> str:
    """Remove ```json fences a model occasionally adds around JSON output."""
    return _FENCE_RE.sub("", s).strip()


def try_parse_json(content: str) -> Any:
    """
    Tolerant JSON parser. Strips fences, then parses. Returns None on failure.
    Use only when the prompt explicitly asked for JSON.
    """
    cleaned = strip_fences(content)
    if not cleaned:
        return None
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Sometimes models prepend prose. Find first '{' or '[' and try again.
        for opener, closer in (("[", "]"), ("{", "}")):
            i = cleaned.find(opener)
            j = cleaned.rfind(closer)
            if 0 <= i < j:
                try:
                    return json.loads(cleaned[i : j + 1])
                except json.JSONDecodeError:
                    continue
        return None


# ── Single-call API ───────────────────────────────────────────────────────────

async def call_nim(
    session: aiohttp.ClientSession,
    nim_key: str,
    model: str,
    *,
    system: str | None = None,
    user: str,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    timeout: float = 60.0,
    expect_json: bool = False,
    endpoint: str = NIM_ENDPOINT,
) -> NIMResult:
    """
    Call a single NIM chat completion. Returns a NIMResult; never raises.

    Args:
        session:      shared aiohttp session (callers usually batch N calls).
        nim_key:      NVIDIA NIM API key.
        model:        NIM model id, e.g. `moonshotai/kimi-k2.6`.
        system:       optional system prompt.
        user:         user prompt.
        temperature:  sampling temperature.
        max_tokens:   ceiling on response tokens.
        timeout:      per-request total timeout in seconds.
        expect_json:  if true, parse `content` as JSON into `parsed`.
        endpoint:     override the chat-completions URL (rare).
    """
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {nim_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    start = time.monotonic()
    try:
        async with session.post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            elapsed = round(time.monotonic() - start, 2)
            status = resp.status
            if status != 200:
                body = await resp.text()
                return NIMResult(
                    ok=False,
                    model=model,
                    elapsed_secs=elapsed,
                    error=f"HTTP {status}: {body[:200]}",
                    http_status=status,
                )
            data = await resp.json()
    except asyncio.TimeoutError:
        return NIMResult(
            ok=False,
            model=model,
            elapsed_secs=round(time.monotonic() - start, 2),
            error=f"timeout after {timeout}s",
        )
    except aiohttp.ClientError as e:
        return NIMResult(
            ok=False,
            model=model,
            elapsed_secs=round(time.monotonic() - start, 2),
            error=f"{type(e).__name__}: {e}",
        )
    except Exception as e:  # last-resort safety net for unknown failures
        return NIMResult(
            ok=False,
            model=model,
            elapsed_secs=round(time.monotonic() - start, 2),
            error=f"{type(e).__name__}: {e}",
        )

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return NIMResult(
            ok=False,
            model=model,
            elapsed_secs=elapsed,
            error="malformed response: missing choices[0].message.content",
            http_status=status,
        )

    usage = data.get("usage") or {}
    parsed = try_parse_json(content) if expect_json else None
    if expect_json and parsed is None:
        return NIMResult(
            ok=False,
            model=model,
            elapsed_secs=elapsed,
            content=content,
            error="response was not parseable as JSON",
            usage=usage,
            http_status=status,
        )

    return NIMResult(
        ok=True,
        model=model,
        elapsed_secs=elapsed,
        content=content,
        parsed=parsed,
        usage=usage,
        http_status=status,
    )
