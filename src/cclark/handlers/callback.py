"""Main callback dispatcher — routes card button clicks to sub-handlers.

This module registers ONLY catch-all prefixes (NOOP, CANCEL). All specific
prefixes (db:, prov:, mode:, tb:, etc.) are registered by their respective
handler modules to avoid conflicts. Longest-prefix dispatch in
callback_registry.dispatch() routes to the most specific handler.
"""

from __future__ import annotations

import structlog

from cclark.callback_data import CANCEL, NOOP, SH_RUN, SH_X, SESSION_KILL, SESSION_SHOW
from cclark.callback_registry import CallbackContext, register

logger = structlog.get_logger()


@register(NOOP, CANCEL)
async def dispatch(ctx: CallbackContext) -> None:
    """Catch-all dispatcher for NOOP and CANCEL callbacks."""
    # NOOP and CANCEL are handled here — other prefixes are handled by
    # sub-handlers that registered their own (more specific) prefixes.
    pass


@register(SH_RUN)
async def _shell_approve(ctx: CallbackContext) -> None:
    """Approve a pending shell command."""
    logger.info("Shell approve from %s: %s", ctx.user_id, ctx.value)


@register(SH_X)
async def _shell_deny(ctx: CallbackContext) -> None:
    """Deny a pending shell command."""
    logger.info("Shell deny from %s: %s", ctx.user_id, ctx.value)


@register(SESSION_KILL)
async def _session_kill(ctx: CallbackContext) -> None:
    """Kill a session window."""
    from cclark.handlers.message import _adapter, _gateway

    window_id = ctx.value[len(SESSION_KILL):]
    if _gateway:
        await _gateway.kill_window(window_id)
        if _adapter:
            await _adapter.send_text(ctx.channel_id, f"Window {window_id} killed.")


@register(SESSION_SHOW)
async def _session_show(ctx: CallbackContext) -> None:
    """Show status for a specific session."""
    from cclark.handlers.message import _adapter, _gateway

    window_id = ctx.value[len(SESSION_SHOW):]
    if _gateway and _adapter:
        await _adapter.send_text(ctx.channel_id, f"Session: {window_id}")
