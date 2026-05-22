"""
core.auth — Telegram user-id allowlist enforcement.

The OpenClaw gateway exposes a Telegram bot endpoint. Without an allowlist any
user who finds the bot handle can chat with the gateway. Since the gateway
spawns shell commands, runs the NIM API on the operator's key, and writes to
the operator's filesystem, an *un-allowlisted* bot is effectively a public
shell. **Always set ALLOWED_TG_USER_IDS in any environment that exposes the
bot.**

This module provides:
    * `is_allowed(user_id)` — boolean check against the resolved allowlist.
    * `ensure_allowed(user_id)` — raise PermissionError if not allowed.
    * `format_denial(user_id)` — message to return to denied senders (avoid
      leaking the allowlist or making the bot look broken).

Wire-up patterns:
    * OpenClaw config: set `channels.telegram.allowedUsers` to a list of ids.
    * Env var:        `ALLOWED_TG_USER_IDS=111,222,333` (comma separated).
    * Both merge.    If both are empty the bot is OPEN — a warning is logged.
"""

from __future__ import annotations

from .config import cached_runtime_config


class TelegramAuthError(PermissionError):
    """Raised when a non-allowlisted Telegram user attempts to invoke the bot."""


def _resolve_allowlist() -> frozenset[int]:
    try:
        return cached_runtime_config().allowed_user_ids
    except EnvironmentError:
        return frozenset()


def allowlist_is_empty() -> bool:
    """True if no allowlist is configured anywhere. Bot is effectively public."""
    return len(_resolve_allowlist()) == 0


def is_allowed(user_id: int | str | None) -> bool:
    """
    True iff `user_id` is on the allowlist.

    Empty allowlist returns False — fail-closed. Operators must explicitly
    populate ALLOWED_TG_USER_IDS or `channels.telegram.allowedUsers` before
    the bot accepts any messages. This is the secure default for a public
    repo deployment.
    """
    if user_id is None:
        return False
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    allow = _resolve_allowlist()
    if not allow:
        return False
    return uid in allow


def ensure_allowed(user_id: int | str | None) -> None:
    """Raise TelegramAuthError if `user_id` is not on the allowlist."""
    if not is_allowed(user_id):
        raise TelegramAuthError(f"telegram user {user_id!r} is not allow-listed")


def format_denial(user_id: int | str | None = None) -> str:
    """Generic message to return to a denied sender. Does not leak the allowlist."""
    return (
        "This bot is restricted to specific users.\n"
        "If you reached it by mistake, you can safely ignore it."
    )


__all__ = [
    "TelegramAuthError",
    "allowlist_is_empty",
    "is_allowed",
    "ensure_allowed",
    "format_denial",
]
