"""Inbound message handler — routes text messages to the gateway or starts new sessions."""

from __future__ import annotations

import structlog

from cclark.config import config
from cclark.event_parsers import FeishuMessageEvent

logger = structlog.get_logger()

# Set by main.py at startup
_gateway = None
_adapter = None


def set_handlers(gateway, adapter) -> None:
    global _gateway, _adapter
    _gateway = gateway
    _adapter = adapter


async def handle_message(event: FeishuMessageEvent) -> None:
    """Handle an inbound Feishu text message."""
    channel_id = config.parse_channel_id(event.chat_id, event.thread_id)
    text = event.text

    # Check if user is in the middle of session creation
    from cclark.handlers.session_creation import handle_session_input
    if await handle_session_input(event, channel_id):
        return

    # /-prefixed commands (except /select which is handled above in session creation)
    if text.startswith("/"):
        await _handle_command(event, channel_id, text)
        return

    # Check if channel is bound to a window
    if _gateway is None:
        logger.warning("Gateway not initialized")
        return

    window_id = _gateway.channel_router.resolve_window(channel_id)
    if window_id is None:
        # Unbound channel — start new session creation flow
        await _handle_new_channel(event, channel_id)
        return

    # Forward text to the agent window
    try:
        await _gateway.send_to_window(window_id, text)
    except Exception:
        logger.exception("Failed to send to window %s", window_id)
        if _adapter:
            await _adapter.send_text(channel_id, "Failed to send message to session.")


async def _handle_command(
    event: FeishuMessageEvent, channel_id: str, text: str
) -> None:
    """Route slash commands to their handlers."""
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in ("/new", "/start", "/select"):
        await _handle_new_channel(event, channel_id)
    elif cmd == "/sessions":
        await _handle_sessions(channel_id)
    elif cmd == "/help":
        await _handle_help(channel_id)
    elif cmd == "/verbose":
        await _handle_verbose(channel_id, arg)
    elif cmd == "/screenshot":
        await _handle_screenshot(channel_id)
    else:
        if _adapter:
            await _adapter.send_text(channel_id, f"Unknown command: {cmd}\nUse /help for available commands.")


async def _handle_new_channel(event: FeishuMessageEvent, channel_id: str) -> None:
    """Start the directory browser / session creation flow."""
    from cclark.handlers.session_creation import start_session_creation
    await start_session_creation(event, channel_id)


async def _handle_sessions(channel_id: str) -> None:
    """List cclark-created sessions (only tmux windows created by this bot)."""
    if _gateway is None or _adapter is None:
        return

    windows = await _gateway.list_windows()
    if not windows:
        await _adapter.send_text(channel_id, "No active sessions.")
        return

    lines = ["Sessions created by this bot:"]
    for w in windows:
        provider = getattr(w, "provider", "unknown")
        wid = getattr(w, "window_id", str(w))
        cwd = getattr(w, "cwd", "")
        # Show which Feishu chat is bound to this window
        bound_channels = _gateway.resolve_channels(wid)
        channel_info = ""
        if bound_channels:
            # Show first channel (primary)
            ch = bound_channels[0]
            if ch.startswith("feishu:"):
                channel_info = f" → {ch[len('feishu:'):]}"
        lines.append(f"  {wid} — {provider} at {cwd}{channel_info}")

    await _adapter.send_text(channel_id, "\n".join(lines))


async def _handle_help(channel_id: str) -> None:
    """Send help text."""
    if _adapter is None:
        return
    help_text = (
        "Available commands:\n"
        "/new — Start a new session\n"
        "/sessions — List active sessions\n"
        "/verbose — Toggle verbose mode\n"
        "/screenshot — Capture screen\n"
        "/help — Show this help"
    )
    await _adapter.send_text(channel_id, help_text)


async def _handle_verbose(channel_id: str, arg: str) -> None:  # noqa: ARG001
    """Toggle verbose streaming mode."""
    from cclark.state import get_verbose_state
    state = get_verbose_state(channel_id)
    current = getattr(state, "_verbose_enabled", False)
    setattr(state, "_verbose_enabled", not current)
    mode = "disabled" if current else "enabled"
    if _adapter:
        await _adapter.send_text(channel_id, f"Verbose mode {mode}.")


async def _handle_screenshot(channel_id: str) -> None:
    """Capture and send a screenshot."""
    from cclark.handlers.screenshot import handle_screenshot_request
    if _gateway and _adapter:
        await handle_screenshot_request(channel_id, _gateway, _adapter)
