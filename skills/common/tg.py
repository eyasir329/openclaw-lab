"""
OpenClaw shared Telegram MarkdownV2 utilities.

Usage in any skill:
    import sys; sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from skills.common.tg import tg_escape, send_telegram, conf_bar, Card

Configuration loading delegates to `core.config` (added in the v1.0 pro
restructure). The legacy `load_config()` 3-tuple signature is preserved so
existing skills keep working unchanged.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import Any

import aiohttp

# ── Make repo root importable so `from core.config import …` works ────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.config import load_config as _core_load_config  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG LOADER (back-compat shim — delegates to core.config)
# ══════════════════════════════════════════════════════════════════════════════

def load_config() -> tuple[str, str, str]:
    """
    Returns (bot_token, chat_id, nim_key). Thin shim over `core.config.load_config()`.
    Kept for back-compat with existing skill scripts.
    """
    return _core_load_config()


# ══════════════════════════════════════════════════════════════════════════════
# ESCAPING
# ══════════════════════════════════════════════════════════════════════════════

def tg_escape(text: Any) -> str:
    """Escape all Telegram MarkdownV2 special characters."""
    return re.sub(r'([\\_*\[\]()~`>#+\-=|{}.!])', r'\\\1', str(text))


def tg_code(text: Any) -> str:
    """Wrap in inline code span (backtick). Escapes backticks inside."""
    return f"`{str(text).replace('`', '')}`"


def tg_bold(text: Any) -> str:
    return f"*{tg_escape(text)}*"


def tg_italic(text: Any) -> str:
    return f"_{tg_escape(text)}_"


def tg_link(title: str, url: str) -> str:
    """Markdown link. Title is escaped; URL is used verbatim."""
    return f"[{tg_escape(title)}]({url})"


# ══════════════════════════════════════════════════════════════════════════════
# VISUAL ELEMENTS
# ══════════════════════════════════════════════════════════════════════════════

def conf_bar(value: float, width: int = 10) -> str:
    """Block-bar representation of a 0-1 float. Returns plain text (safe in code span)."""
    value  = max(0.0, min(1.0, float(value)))
    filled = round(value * width)
    return "█" * filled + "░" * (width - filled)


def score_badge(score: float) -> str:
    """Emoji badge for a 0-1 confidence/score."""
    if score >= 0.80: return "🟢"
    if score >= 0.55: return "🟡"
    return "🟠"


def bullet(items: list[str], prefix: str = "•") -> list[str]:
    """Return list of escaped bullet lines."""
    return [f"{prefix} {tg_escape(item)}" for item in items]


# ══════════════════════════════════════════════════════════════════════════════
# CARD BUILDER
# ══════════════════════════════════════════════════════════════════════════════

class Card:
    """
    Fluent builder for a Telegram MarkdownV2 message card.

    Example:
        text = (
            Card("🔍", "My Query")
            .metric("Confidence", conf_bar(0.87), "87%")
            .section("📝 Summary", ["Detailed answer here."])
            .bullets("💡 Key Facts", facts[:6])
            .links("🔗 Best Sources", sources)
            .bullets("⚠️ Caveats", caveats)
            .footer("6-model NIM · Kimi-K2.6 · 42s")
            .build()
        )
    """

    def __init__(self, emoji: str, title: str) -> None:
        self._lines: list[str] = [f"{emoji} {tg_bold(title)}", ""]

    # ── primitives ─────────────────────────────────────────────────────────────

    def line(self, text: str) -> "Card":
        self._lines.append(text)
        return self

    def blank(self) -> "Card":
        self._lines.append("")
        return self

    # ── common blocks ──────────────────────────────────────────────────────────

    def metric(self, label: str, bar: str, suffix: str = "") -> "Card":
        """e.g. metric('Confidence', conf_bar(0.8), '80%')"""
        suf = f" {tg_escape(suffix)}" if suffix else ""
        self._lines.append(f"{tg_escape(label)}: {tg_code(bar)}{suf}")
        return self

    def badge_row(self, items: list[tuple[str, Any]]) -> "Card":
        """e.g. [('🟢', 5), ('🟡', 3), ('🟠', 1)]"""
        self._lines.append("  ".join(f"{e} {tg_escape(str(v))}" for e, v in items))
        return self

    def section(self, header: str, body_lines: list[str]) -> "Card":
        self._lines += ["", header]
        for ln in body_lines:
            self._lines.append(ln)
        return self

    def bullets(self, header: str, items: list[str], prefix: str = "•") -> "Card":
        if not items:
            return self
        self._lines += ["", header]
        for item in items:
            self._lines.append(f"{prefix} {tg_escape(item)}")
        return self

    def numbered_bullets(self, header: str, items: list[str]) -> "Card":
        if not items:
            return self
        self._lines += ["", header]
        for i, item in enumerate(items, 1):
            self._lines.append(f"{i}\\. {tg_escape(item)}")
        return self

    def links(
        self,
        header: str,
        sources: list[dict],
        title_key: str = "title",
        url_key: str   = "url",
        why_key: str   = "why",
    ) -> "Card":
        """
        Numbered link list.
        sources = [{"title": ..., "url": ..., "why": ...}, ...]
        """
        if not sources:
            return self
        self._lines += ["", header]
        for i, s in enumerate(sources[:10], 1):
            title = s.get(title_key, "")
            url   = s.get(url_key, "")
            why   = s.get(why_key, "")
            link  = tg_link(title, url) if url else tg_escape(title)
            self._lines.append(f"{i}\\. {link}")
            if why:
                self._lines.append(f"   {tg_italic(why)}")
        return self

    def result_rows(
        self,
        header: str,
        results: list[dict],
        source_emojis: dict[str, str] | None = None,
    ) -> "Card":
        """
        Scored result rows.
        result = {"title", "url", "snippet", "source", "score"}
        """
        if not results:
            return self
        _emojis = source_emojis or {}
        self._lines += ["", header]
        for r in results[:8]:
            src     = _emojis.get(r.get("source", ""), "🔗")
            title   = r.get("title", "")
            url     = r.get("url", "")
            score   = float(r.get("score") or 0)
            snippet = (r.get("snippet") or "")[:100]
            bar     = conf_bar(score, 5)
            if url:
                self._lines.append(f"{src} {tg_link(title, url)}")
            else:
                self._lines.append(f"{src} {tg_escape(title)}")
            self._lines.append(f"  {tg_code(bar)} {tg_italic(snippet)}")
        return self

    def code_queries(self, header: str, queries: list[str]) -> "Card":
        """List of queries rendered in code spans."""
        if not queries:
            return self
        self._lines += ["", header]
        for q in queries[:6]:
            self._lines.append(f"• {tg_code(q.replace('`', ''))}")
        return self

    def divider(self) -> "Card":
        """Thin visual separator line."""
        self._lines.append("▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬")
        return self

    def footer(self, text: str) -> "Card":
        self._lines += ["", tg_italic(text)]
        return self

    def build(self) -> str:
        return "\n".join(self._lines)


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM SEND
# ══════════════════════════════════════════════════════════════════════════════

async def send_telegram(
    session: aiohttp.ClientSession,
    token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "MarkdownV2",
) -> None:
    """Send message, splitting at 4000 chars. Retries 3x with exponential backoff."""
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks  = [text[i:i + 4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        for attempt in range(3):
            try:
                async with session.post(api_url, json={
                    "chat_id":                  chat_id,
                    "text":                     chunk,
                    "parse_mode":               parse_mode,
                    "disable_web_page_preview": True,
                }) as r:
                    if r.status == 200:
                        break
                    body = await r.text()
                    print(f"[telegram] HTTP {r.status} attempt {attempt+1}: {body[:120]}")
                    await asyncio.sleep(2 ** attempt)
            except Exception as e:
                print(f"[telegram] error attempt {attempt+1}: {e}")
                await asyncio.sleep(2 ** attempt)
        await asyncio.sleep(0.5)


async def send_message_with_id(
    token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "MarkdownV2",
) -> int | None:
    """
    Send a single message and return its message_id (for later editing).
    Returns None on failure.
    """
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with aiohttp.ClientSession() as sess:
        try:
            async with sess.post(api_url, json={
                "chat_id":                  chat_id,
                "text":                     text[:4000],
                "parse_mode":               parse_mode,
                "disable_web_page_preview": True,
            }) as r:
                data = await r.json()
                if r.status == 200 and data.get("ok"):
                    return data["result"]["message_id"]
                print(f"[telegram] send_message_with_id HTTP {r.status}: {data}")
        except Exception as e:
            print(f"[telegram] send_message_with_id error: {e}")
    return None


async def edit_message(
    token: str,
    chat_id: str,
    message_id: int,
    text: str,
    parse_mode: str = "MarkdownV2",
) -> bool:
    """
    Edit an existing message in-place. Returns True on success.
    Falls back silently on failure (e.g. message too old or unchanged text).
    """
    api_url = f"https://api.telegram.org/bot{token}/editMessageText"
    async with aiohttp.ClientSession() as sess:
        try:
            async with sess.post(api_url, json={
                "chat_id":                  chat_id,
                "message_id":               message_id,
                "text":                     text[:4000],
                "parse_mode":               parse_mode,
                "disable_web_page_preview": True,
            }) as r:
                data = await r.json()
                return r.status == 200 and data.get("ok", False)
        except Exception as e:
            print(f"[telegram] edit_message error: {e}")
    return False


async def send_typing(token: str, chat_id: str) -> None:
    """Send typing indicator (shows for ~5s in Telegram)."""
    api_url = f"https://api.telegram.org/bot{token}/sendChatAction"
    async with aiohttp.ClientSession() as sess:
        try:
            await sess.post(api_url, json={"chat_id": chat_id, "action": "typing"})
        except Exception:
            pass


async def send_text(token: str, chat_id: str, text: str, parse_mode: str = "MarkdownV2") -> None:
    """Convenience wrapper that creates its own session."""
    async with aiohttp.ClientSession() as sess:
        await send_telegram(sess, token, chat_id, text, parse_mode)


async def send_error(token: str, chat_id: str, title: str, detail: str = "") -> None:
    """Send a standardised error card."""
    lines = [f"❌ {tg_bold(title)}"]
    if detail:
        lines += ["", tg_escape(detail)]
    await send_text(token, chat_id, "\n".join(lines))


async def send_ok(token: str, chat_id: str, message: str) -> None:
    """Send a simple success message."""
    await send_text(token, chat_id, f"✅ {tg_escape(message)}")
