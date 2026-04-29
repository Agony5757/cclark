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

    # #new and #help must be global: #new cancels any in-progress wizard and
    # replaces the chat's tmux-Claude session, while #help should never be
    # interpreted as directory input during the wizard.
    global_cmd = text.split(maxsplit=1)[0].lower() if text.strip() else ""
    if global_cmd == "#new":
        await _handle_hash_new(event, channel_id)
        return
    if global_cmd == "#help":
        await _handle_help(channel_id)
        return

    # Check if user is in the middle of session creation
    from cclark.handlers.session_creation import handle_session_input
    if await handle_session_input(event, channel_id):
        return

    # # prefix — cclark command system
    if text.startswith("#"):
        await _handle_hash_command(event, channel_id, text)
        return

    # All other messages (including / commands) are forwarded to the agent
    if _gateway is None:
        logger.warning("Gateway not initialized")
        return

    window_id = _gateway.channel_router.resolve_window(channel_id)
    if window_id is None:
        # Unbound channel — show explicit guidance instead of guessing that the
        # user's first message was intended to start a new workspace.
        await _handle_new_channel(event, channel_id)
        return

    # Forward text to the agent window
    try:
        from cclark.state import advance_turn_index

        advance_turn_index(channel_id)
        await _gateway.send_to_window(window_id, text)
    except Exception:
        logger.exception("Failed to send to window %s", window_id)
        if _adapter:
            await _adapter.send_text(channel_id, "Failed to send message to session.")


# ── # command system ──────────────────────────────────────────────────────────


async def _handle_new_channel(event: FeishuMessageEvent, channel_id: str) -> None:
    """Show guidance for an unbound chat."""
    if _adapter is None:
        return
    await _adapter.send_text(
        channel_id,
        "No active session is bound to this chat.\n\n" + _build_help_text(),
    )


async def _handle_hash_command(
    event: FeishuMessageEvent, channel_id: str, text: str
) -> None:
    """Route # prefixed commands to their handlers."""
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "#new":
        await _handle_hash_new(event, channel_id)
    elif cmd == "#session":
        await _handle_session_command(event, channel_id, arg)
    elif cmd == "#status":
        await _handle_status(channel_id)
    elif cmd == "#help":
        await _handle_help(channel_id)
    elif cmd == "#mkdir":
        await _adapter.send_text(
            channel_id,
            "Use #new first, then send #mkdir <name> during directory selection.",
        )
    elif cmd == "#screenshot":
        await _handle_screenshot(channel_id)
    elif cmd == "#verbose":
        await _handle_verbose_toggle(channel_id, arg)
    else:
        if _adapter:
            await _adapter.send_text(
                channel_id,
                f"Unknown command: {cmd}\n"
                "Send #help for available commands.",
            )


async def _handle_hash_new(event: FeishuMessageEvent, channel_id: str) -> None:
    """Kill the current bound window and start the session creation wizard."""
    from cclark.state import reset_channel_state
    from cclark.handlers.session_creation import (
        clear_session_creation,
        start_session_creation,
    )

    clear_session_creation(event.user_id)

    if _gateway is not None:
        killed = await _gateway.kill_channel_windows(channel_id)
        if killed and _adapter is not None:
            await _adapter.send_text(
                channel_id,
                "Closed previous session window(s): " + ", ".join(killed),
            )

        orphans = await _gateway.list_orphaned_agent_windows()
        if orphans and _adapter is not None:
            lines = [
                "Warning: found tmux-Claude window(s) that are no longer tracked by cclark:",
            ]
            for w in orphans:
                lines.append(
                    f"  {w.window_id} | {w.display_name} | {w.cwd or 'unknown cwd'}"
                )
            lines.append("They were not killed because cclark cannot prove ownership.")
            await _adapter.send_text(channel_id, "\n".join(lines))

    reset_channel_state(channel_id)
    await start_session_creation(event, channel_id)


async def _handle_session_command(
    _event: FeishuMessageEvent, channel_id: str, arg: str
) -> None:
    """Route #session subcommands: list, close."""
    sub = arg.strip().lower()
    if sub == "list":
        await _handle_session_list(channel_id)
    elif sub.startswith("close "):
        target = sub[len("close "):].strip()
        await _handle_session_close(channel_id, target)
    elif sub == "close":
        await _adapter.send_text(channel_id, "Usage: #session close <window_id>")
    else:
        await _adapter.send_text(
            channel_id,
            "Usage: #session list | #session close <window_id>",
        )


async def _handle_session_list(channel_id: str) -> None:
    """List all tmux windows created by cclark with their channel bindings."""
    if _gateway is None or _adapter is None:
        return

    windows = await _gateway.list_windows()
    if not windows:
        await _adapter.send_text(channel_id, "No active sessions.")
        return

    lines = ["Active sessions:"]
    for w in windows:
        wid = getattr(w, "window_id", str(w))
        provider = getattr(w, "provider", "unknown")
        cwd = getattr(w, "cwd", "")
        session_short = (getattr(w, "session_id", "") or "")[:8]
        bound = _gateway.resolve_channels(wid)
        ch_info = ""
        if bound:
            ch_parts = [c.rsplit(":", 1)[-1] for c in bound]
            ch_info = " → " + ", ".join(ch_parts)
        lines.append(f"  [{session_short}] {wid} | {provider} | {cwd}{ch_info}")

    await _adapter.send_text(channel_id, "\n".join(lines))


async def _handle_session_close(channel_id: str, target_wid: str) -> None:
    """Close a session by window id."""
    if _gateway is None or _adapter is None:
        return

    target_wid = target_wid.strip()
    if not target_wid:
        await _adapter.send_text(channel_id, "Usage: #session close <window_id>")
        return

    windows = await _gateway.list_windows()
    valid_ids = {getattr(w, "window_id", str(w)) for w in windows}
    if target_wid not in valid_ids:
        await _adapter.send_text(channel_id, f"Unknown window id: {target_wid}")
        return

    await _gateway.kill_window(target_wid)
    await _adapter.send_text(channel_id, f"Session {target_wid} closed.")


async def _handle_status(channel_id: str) -> None:
    """Show current window status for this channel."""
    if _gateway is None or _adapter is None:
        return

    window_id = _gateway.channel_router.resolve_window(channel_id)
    if window_id is None:
        await _adapter.send_text(channel_id, "No active session on this channel.")
        return

    from cclark.state import get_verbose_state
    from unified_icc.window_state_store import window_store

    ws = window_store.get_window_state(window_id)
    vs = get_verbose_state(channel_id)
    verbose = getattr(vs, "_verbose_enabled", False)
    session_short = (ws.session_id or "")[:8]

    lines = [
        f"Window: {window_id}",
        f"Session: {session_short}… ({ws.session_id})",
        f"Provider: {ws.provider_name or 'unknown'}",
        f"CWD: {ws.cwd or '—'}",
        f"Mode: {ws.approval_mode or '—'}",
        f"Verbose: {'on' if verbose else 'off'}",
        f"Thinking card: {vs.streaming_thinking_card_id or 'none'}",
    ]
    await _adapter.send_text(channel_id, "\n".join(lines))


async def _handle_help(channel_id: str) -> None:
    """Send help text."""
    if _adapter is None:
        return
    await _adapter.send_text(channel_id, _build_help_text())


def _build_help_text() -> str:
    return (
        "cclark commands:\n"
        "#new — Start a fresh Claude workspace for this chat. If this chat already has one, cclark closes it first.\n"
        "#mkdir <name> — During #new directory selection, create a new child directory and switch into it.\n"
        "#status — Show the session bound to this chat.\n"
        "#verbose on|off — Show or hide streaming/thinking details.\n"
        "#session list — List active tmux sessions managed by cclark.\n"
        "#session close <window_id> — Close a specific managed tmux session.\n"
        "#screenshot — Send a screenshot of the current tmux window.\n"
        "#help — Show this help.\n"
        "\n"
        "To begin: send #new, choose a directory, send ok, choose a provider, then choose standard or yolo mode.\n"
        "After a session starts, normal text and Claude slash commands such as /status are forwarded to Claude."
    )


async def _handle_screenshot(channel_id: str) -> None:
    """Capture and send a screenshot."""
    from cclark.handlers.screenshot import handle_screenshot_request
    if _gateway and _adapter:
        await handle_screenshot_request(channel_id, _gateway, _adapter)


async def _handle_verbose_toggle(channel_id: str, arg: str) -> None:
    """Set or toggle verbose mode for this channel."""
    if _adapter is None:
        return
    from cclark.state import get_verbose_state
    state = get_verbose_state(channel_id)
    if arg == "on":
        new = True
    elif arg == "off":
        new = False
    else:
        new = not getattr(state, "_verbose_enabled", False)
    setattr(state, "_verbose_enabled", new)
    verb = "enabled" if new else "disabled"
    await _adapter.send_text(
        channel_id,
        f"Verbose mode {verb}. Thinking will {'be' if new else 'not be'} shown.",
    )
