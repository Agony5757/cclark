"""Inbound message handler — routes text messages to the gateway or starts new sessions."""

from __future__ import annotations

import re

import structlog

from cclark.config import config
from cclark.event_parsers import FeishuMessageEvent

logger = structlog.get_logger()

# Set by main.py at startup
_gateway = None
_adapter = None
_terminal_prompt_states: dict[str, dict[str, str]] = {}

_NUMBERED_OPTION_RE = re.compile(r"^\s*(?:[❯›]\s*)?(\d+)\.\s+(.+?)\s*$")
_SELECTED_NUMBERED_OPTION_RE = re.compile(r"^\s*[❯›]\s*(\d+)\.\s+")


def set_handlers(gateway, adapter) -> None:
    """Store the gateway and adapter references for use in message handlers."""
    global _gateway, _adapter
    _gateway = gateway
    _adapter = adapter


def classify_terminal_prompt(body: str) -> dict[str, str] | None:
    """Classify terminal UI text only when it expects a Feishu reply."""
    text = body or ""
    options = extract_numbered_prompt_options(text)
    selected = extract_selected_prompt_option(text)
    if (
        "Claude has written up a plan" in text
        or (
            "Would you like to proceed?" in text
            and "Tell Claude what to change" in text
        )
    ):
        return {
            "type": "plan_decision",
            "phase": "choice",
            "options": ",".join(options),
            "selected": selected,
        }

    permission_markers = (
        "Do you want to proceed?",
        "Do you want to make this edit",
        "Do you want to create ",
        "Do you want to update ",
        "Do you want to delete ",
        "Do you want to modify ",
        "Network request outside of sandbox",
        "This command requires approval",
    )
    if any(marker in text for marker in permission_markers) or (
        "Allow " in text and " to " in text
    ):
        return {
            "type": "permission",
            "phase": "choice",
            "options": ",".join(options),
            "selected": selected,
        }

    selection_markers = (
        "Enter to select",
        "Enter to confirm",
        "Press enter to select",
        "Press enter to confirm",
        "Type to filter",
    )
    if any(marker in text for marker in selection_markers) and any(
        marker in text for marker in ("☐", "✔", "☒", "❯", "›")
    ):
        return {
            "type": "selection",
            "phase": "choice",
            "options": ",".join(options),
            "selected": selected,
        }

    return None


def extract_numbered_prompt_options(body: str) -> list[str]:
    """Return every visible numbered choice from a Claude terminal prompt."""
    options: list[str] = []
    seen: set[str] = set()
    for line in (body or "").splitlines():
        match = _NUMBERED_OPTION_RE.match(line)
        if not match:
            continue
        value = match.group(1)
        if value in seen:
            continue
        seen.add(value)
        options.append(value)
    return options


def extract_selected_prompt_option(body: str) -> str:
    """Return the numbered option currently focused by Claude's cursor."""
    for line in (body or "").splitlines():
        match = _SELECTED_NUMBERED_OPTION_RE.match(line)
        if match:
            return match.group(1)
    return ""


def build_terminal_prompt_reply_guidance(body: str, state: dict[str, str]) -> str:
    """Build prompt-specific Feishu guidance for the current Claude terminal UI."""
    options = extract_numbered_prompt_options(body)
    if options:
        choices = ", ".join(f"`{option}`" for option in options)
        guidance = f"Reply with one of the listed numbers: {choices}."
    else:
        guidance = "Reply with the number shown in Claude."

    if state.get("type") == "plan_decision" and "3" in options:
        guidance += (
            "\nFor plan option `3`, reply `3` first, then send the feedback text."
        )

    return guidance


def set_terminal_prompt_state(channel_id: str, body: str) -> bool:
    """Classify and record the latest actionable terminal prompt for a channel.

    Returns:
        True if the prompt was classified as actionable and stored.
    """
    state = classify_terminal_prompt(body)
    if state is None:
        clear_terminal_prompt_state(channel_id)
        return False
    _terminal_prompt_states[channel_id] = state
    return True


def clear_terminal_prompt_state(channel_id: str) -> None:
    """Clear the stored terminal prompt state for a channel."""
    _terminal_prompt_states.pop(channel_id, None)


async def _advance_channel_turn(channel_id: str) -> int:
    """Finalize any open thinking card and advance the channel's turn index.

    Returns:
        The new turn index.
    """
    from cclark.state import advance_turn_index, get_verbose_state

    if _adapter is not None:
        state = get_verbose_state(channel_id)
        if state.streaming_thinking_active:
            from cclark.cards.thinking import finalize_active_thinking_card

            try:
                await finalize_active_thinking_card(_adapter, channel_id)
            except Exception:
                logger.exception(
                    "ThinkingCardStreamer finalize before turn advance failed channel=%s",
                    channel_id,
                )

    return advance_turn_index(channel_id)


async def handle_message(event: FeishuMessageEvent) -> None:
    """Top-level handler for an inbound Feishu text message.

    Routes to # command handling, session creation wizard, terminal prompt
    replies, or gateway forwarding as appropriate.
    """
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

    if await _handle_terminal_prompt_reply(channel_id, window_id, text):
        return

    # Forward text to the agent window
    try:
        await _advance_channel_turn(channel_id)
        await _gateway.send_to_window(window_id, text)
    except Exception:
        logger.exception("Failed to send to window %s", window_id)
        if _adapter:
            await _adapter.send_text(channel_id, "Failed to send message to session.")


async def _handle_terminal_prompt_reply(
    channel_id: str,
    window_id: str,
    text: str,
) -> bool:
    """Handle numbered replies to permission/plan/selection prompts.

    Returns True if the message was consumed as a prompt reply.
    Special case: plan option 3 is two-step (select first, then feedback text).
    """
    state = _terminal_prompt_states.get(channel_id)
    if not state:
        return False

    stripped = text.strip()
    allowed_options = {
        option for option in (state.get("options") or "").split(",") if option
    }
    if state.get("type") == "plan_decision":
        if state.get("phase") == "choice" and stripped == "3":
            await _gateway.send_input_to_window(
                window_id,
                "3",
                enter=False,
                literal=True,
                raw=True,
            )
            state["phase"] = "awaiting_feedback"
            if _adapter is not None:
                await _adapter.send_text(
                    channel_id,
                    "Plan option 3 selected. Send the feedback text next; "
                    "cclark will submit it to Claude.",
                )
            return True

        if state.get("phase") == "awaiting_feedback":
            await _advance_channel_turn(channel_id)
            await _gateway.send_to_window(window_id, text)
            clear_terminal_prompt_state(channel_id)
            return True

    if state.get("type") == "selection" and stripped.isdigit():
        if allowed_options and stripped not in allowed_options:
            await _send_invalid_prompt_option(channel_id, stripped, allowed_options)
            return True

        if await _select_terminal_option_by_navigation(
            window_id,
            stripped,
            state,
        ):
            await _advance_channel_turn(channel_id)
            clear_terminal_prompt_state(channel_id)
            return True

    if stripped.isdigit() and allowed_options and stripped not in allowed_options:
        await _send_invalid_prompt_option(channel_id, stripped, allowed_options)
        return True

    if stripped.isdigit() and (not allowed_options or stripped in allowed_options):
        await _advance_channel_turn(channel_id)
        await _gateway.send_to_window(window_id, stripped)
        clear_terminal_prompt_state(channel_id)
        return True

    return False


async def _send_invalid_prompt_option(
    channel_id: str,
    stripped: str,
    allowed_options: set[str],
) -> None:
    """Send an error message when the user picks a number not shown by Claude."""
    if _adapter is None:
        return
    choices = ", ".join(f"`{option}`" for option in sorted(allowed_options, key=int))
    await _adapter.send_text(
        channel_id,
        f"`{stripped}` is not a visible Claude option. Reply with one of: {choices}.",
    )


async def _select_terminal_option_by_navigation(
    window_id: str,
    target: str,
    state: dict[str, str],
) -> bool:
    """Move the terminal cursor to the target option and press Enter.

    Uses captured cursor position as baseline, navigates with Up/Down keys.
    Returns True on success.
    """
    selected = state.get("selected") or ""
    options = [option for option in (state.get("options") or "").split(",") if option]
    if not selected or target not in options or selected not in options:
        return False

    current_idx = options.index(selected)
    target_idx = options.index(target)
    delta = target_idx - current_idx
    key = "Down" if delta > 0 else "Up"
    for _ in range(abs(delta)):
        await _gateway.send_key(window_id, key)
    await _gateway.send_key(window_id, "Enter")
    return True


# ── # command system ──────────────────────────────────────────────────────────


async def _handle_new_channel(event: FeishuMessageEvent, channel_id: str) -> None:
    """Send guidance when a message arrives on a chat with no bound session."""
    if _adapter is None:
        return
    await _adapter.send_text(
        channel_id,
        "No active session is bound to this chat.\n\n" + _build_help_text(),
    )


async def _handle_hash_command(
    event: FeishuMessageEvent, channel_id: str, text: str
) -> None:
    """Dispatch a #command (e.g. #new, #help, #status) to the appropriate handler."""
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
    """Handle #new — kill existing bound window(s) and start the session creation wizard."""
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
    clear_terminal_prompt_state(channel_id)
    await start_session_creation(event, channel_id)


async def _handle_session_command(
    _event: FeishuMessageEvent, channel_id: str, arg: str
) -> None:
    """Handle #session list and #session close <window_id>."""
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
    """Send a text listing of all active cclark-managed tmux sessions."""
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
    """Close a specific tmux window by its window_id and notify the channel."""
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
    """Send a text summary of the session bound to this channel (window, provider, mode, verbose)."""
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
        f"Thinking card: {vs.streaming_thinking_card_id if vs.streaming_thinking_active else 'none'}",
    ]
    await _adapter.send_text(channel_id, "\n".join(lines))


async def _handle_help(channel_id: str) -> None:
    """Send the cclark command reference to the channel."""
    if _adapter is None:
        return
    await _adapter.send_text(channel_id, _build_help_text())


def _build_help_text() -> str:
    """Return the formatted help text listing all cclark commands."""
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
    """Handle #screenshot — capture the active tmux pane and send it as a Feishu image."""
    from cclark.handlers.screenshot import handle_screenshot_request
    if _gateway and _adapter:
        await handle_screenshot_request(channel_id, _gateway, _adapter)


async def _handle_verbose_toggle(channel_id: str, arg: str) -> None:
    """Handle #verbose on|off — set or toggle per-channel verbose mode and notify the user."""
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
