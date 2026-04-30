"""Session creation flow — text-based directory browser + provider/mode picker.

States: browse → provider → mode → create
- browse: list dirs, navigate with text input
- provider: pick an AI provider
- mode: pick standard or yolo
"""

from __future__ import annotations

import os
import structlog
from pathlib import Path
from typing import Any

from cclark.config import config
from cclark.event_parsers import FeishuMessageEvent
from cclark.user_preferences import user_preferences

logger = structlog.get_logger()

# ── State constants ──────────────────────────────────────────────────────────

STATE_BROWSE = "browse"
STATE_PROVIDER = "provider"
STATE_MODE = "mode"

_PROVIDERS = ["claude", "codex", "gemini", "pi", "shell"]
_MODES = ["standard", "yolo"]
_PAGE_SIZE = 20


# ── Per-user session creation state ──────────────────────────────────────────

_sessions: dict[str, dict[str, Any]] = {}


def get_session_state(user_id: str) -> dict[str, Any] | None:
    """Return the active session-creation state dict for a user, or None if not in a flow."""
    return _sessions.get(user_id)


def clear_session_creation(user_id: str) -> None:
    """Cancel and discard any in-progress session-creation flow for a user."""
    _clear_state(user_id)


def _get_or_create_state(user_id: str, channel_id: str) -> dict[str, Any]:
    """Return the existing or new per-user session-creation state dict."""
    state = _sessions.setdefault(user_id, {})
    if "phase" not in state:
        state["phase"] = STATE_BROWSE
        state["path"] = str(Path.home())
        state["channel_id"] = channel_id
        state["original_text"] = ""
        state["provider"] = ""
    return state


def _clear_state(user_id: str) -> None:
    """Remove the per-user session-creation state (on cancel or window creation)."""
    _sessions.pop(user_id, None)


# ── Directory listing helper ─────────────────────────────────────────────────


def _list_dirs(path: str) -> list[str]:
    """Return sorted list of non-hidden subdirectory names in path."""
    try:
        entries = []
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if os.path.isdir(full) and not name.startswith("."):
                entries.append(name)
        return entries
    except OSError:
        return []


def _format_dir_listing(path: str, user_id: str) -> str:
    """Format a text directory listing for the browse phase of the wizard."""
    lines = [
        "New session setup: choose the workspace directory.",
        f"Current directory: {path}",
        "",
        "Reply with a number or folder name to enter it, .. to go up, or ok to use the current directory.",
        "To create a new workspace here, reply with #mkdir <name>.",
    ]
    lines.append("")

    dirs = _list_dirs(path)
    mru = user_preferences.get_user_mru(user_id)

    if mru:
        lines.append("Recent directories:")
        for d in mru[:5]:
            lines.append(f"  #select {d}")
        lines.append("")

    if dirs:
        lines.append("Subdirectories:")
        for i, name in enumerate(dirs[:_PAGE_SIZE], 1):
            lines.append(f"  {i}. {name}")
        if len(dirs) > _PAGE_SIZE:
            lines.append(f"  ... ({len(dirs) - _PAGE_SIZE} more)")
    else:
        lines.append("Subdirectories: none")

    lines.append("")
    lines.append("Other commands: #select <path> | #mkdir <name> | #cancel")
    return "\n".join(lines)


def _validate_mkdir_name(name: str) -> str | None:
    """Return an error string if name is not a safe single-directory name, else None."""
    if not name:
        return "Usage: #mkdir <name>"
    if name in (".", ".."):
        return "Directory name cannot be . or .."
    candidate = Path(name)
    if candidate.is_absolute() or len(candidate.parts) != 1:
        return "Use a single directory name, not a path."
    return None


# ── Public API ───────────────────────────────────────────────────────────────


async def start_session_creation(
    event: FeishuMessageEvent, channel_id: str
) -> None:
    """Start the directory-browser session creation wizard, sending the initial listing."""
    from cclark.handlers.message import _adapter, _gateway

    if _adapter is None:
        return

    # Deduplication: refuse to create a new session if one is already bound to this channel.
    if _gateway is not None:
        existing = _gateway.channel_router.resolve_window(channel_id)
        if existing is not None:
            await _adapter.send_text(
                channel_id,
                f"A session is already running for this chat (window {existing}).\n"
                "Use #new to kill it first.",
            )
            return

    state = _get_or_create_state(event.user_id, channel_id)
    state["original_text"] = event.text

    # Handle #select <path> — jump directly to the specified directory
    text = event.text.strip()
    if text.startswith("#select "):
        target = text[len("#select "):].strip()
        target = os.path.expanduser(target)
        if os.path.isdir(target):
            state["path"] = os.path.abspath(target)

    await _adapter.send_text(
        channel_id,
        _format_dir_listing(state["path"], event.user_id),
    )


async def handle_session_input(
    event: FeishuMessageEvent, channel_id: str
) -> bool:
    """Process a message while in the session-creation wizard.

    Returns True if the message was consumed by the wizard (browse/provider/mode phase).
    """
    from cclark.handlers.message import _adapter

    if _adapter is None:
        return False

    state = _sessions.get(event.user_id)
    if state is None:
        return False

    text = event.text.strip()
    phase = state.get("phase", STATE_BROWSE)

    if phase == STATE_BROWSE:
        return await _handle_browse(event, channel_id, text, state)
    elif phase == STATE_PROVIDER:
        return await _handle_provider(event, channel_id, text, state)
    elif phase == STATE_MODE:
        return await _handle_mode(event, channel_id, text, state)

    return False


# ── Phase handlers ───────────────────────────────────────────────────────────


async def _handle_browse(  # noqa: C901,PLR0911,PLR0912,PLR0915
    event: FeishuMessageEvent,
    channel_id: str,
    text: str,
    state: dict[str, Any],
) -> bool:
    from cclark.handlers.message import _adapter

    if _adapter is None:
        return False

    current_path = state["path"]
    new_path: str | None = None

    # #select <path> — direct navigation
    if text.startswith("#select "):
        target = text[len("#select "):].strip()
        target = os.path.expanduser(target)
        if os.path.isdir(target):
            new_path = os.path.abspath(target)
        else:
            await _adapter.send_text(channel_id, f"Not a directory: {target}")
            return True

    # #mkdir <name> — create a child directory and switch into it
    elif text.startswith("#mkdir"):
        raw_name = text[len("#mkdir"):].strip()
        error = _validate_mkdir_name(raw_name)
        if error is not None:
            await _adapter.send_text(channel_id, error)
            return True

        target_path = Path(current_path) / raw_name
        try:
            target_path.mkdir()
        except FileExistsError:
            await _adapter.send_text(
                channel_id,
                f"Directory already exists: {target_path}\n\n"
                + _format_dir_listing(current_path, event.user_id),
            )
            return True
        except OSError as exc:
            await _adapter.send_text(channel_id, f"Failed to create directory: {exc}")
            return True

        new_path = str(target_path.resolve())
        await _adapter.send_text(channel_id, f"Created directory: {new_path}")

    # ok / confirm — accept current dir
    elif text.lower() in ("ok", "confirm", "yes"):
        user_preferences.update_user_mru(event.user_id, current_path)
        state["phase"] = STATE_PROVIDER
        await _adapter.send_text(
            channel_id,
            f"✅ Directory: {current_path}\n\n"
            f"Select provider:\n"
            + "\n".join(f"  {i}. {p}" for i, p in enumerate(_PROVIDERS, 1)),
        )
        return True

    # .. — go up
    elif text == "..":
        parent = str(Path(current_path).resolve().parent)
        if parent != current_path:
            new_path = parent
        else:
            await _adapter.send_text(channel_id, "Already at root.")
            return True

    # cancel
    elif text.lower() in ("cancel", "quit", "exit", "#cancel"):
        _clear_state(event.user_id)
        await _adapter.send_text(channel_id, "Session creation cancelled.")
        return True

    # Number or directory name
    else:
        dirs = _list_dirs(current_path)
        # Try as number
        try:
            idx = int(text) - 1
            if 0 <= idx < len(dirs):
                new_path = os.path.join(current_path, dirs[idx])
        except ValueError:
            pass

        # Try as name match
        if new_path is None:
            for d in dirs:
                if d.lower() == text.lower():
                    new_path = os.path.join(current_path, d)
                    break

        # Try as relative/absolute path
        if new_path is None:
            candidate = os.path.join(current_path, text)
            candidate = os.path.expanduser(candidate)
            if os.path.isdir(candidate):
                new_path = os.path.abspath(candidate)

        if new_path is None:
            await _adapter.send_text(
                channel_id, f"Not found: {text}\n\n" + _format_dir_listing(current_path, event.user_id)
            )
            return True

    if new_path:
        state["path"] = new_path
        await _adapter.send_text(
            channel_id,
            _format_dir_listing(new_path, event.user_id),
        )
    return True


async def _handle_provider(
    event: FeishuMessageEvent,
    channel_id: str,
    text: str,
    state: dict[str, Any],
) -> bool:
    from cclark.handlers.message import _adapter

    if _adapter is None:
        return False

    # cancel
    if text.lower() in ("cancel", "quit", "exit", "#cancel", "back"):
        state["phase"] = STATE_BROWSE
        await _adapter.send_text(
            channel_id,
            _format_dir_listing(state["path"], event.user_id),
        )
        return True

    provider: str | None = None

    # Number
    try:
        idx = int(text) - 1
        if 0 <= idx < len(_PROVIDERS):
            provider = _PROVIDERS[idx]
    except ValueError:
        pass

    # Name match
    if provider is None:
        for p in _PROVIDERS:
            if p.lower() == text.lower():
                provider = p
                break

    if provider is None:
        await _adapter.send_text(channel_id, f"Unknown provider: {text}")
        return True

    state["provider"] = provider

    # Shell skips mode picker
    if provider == "shell":
        await _create_window(channel_id, event.user_id, state["path"], provider, "standard")
        return True

    state["phase"] = STATE_MODE
    await _adapter.send_text(
        channel_id,
        f"Provider: {provider}\n"
        f"Directory: {state['path']}\n\n"
        f"Select mode:\n  1. standard (approval required)\n  2. yolo (no approval)",
    )
    return True


async def _handle_mode(
    event: FeishuMessageEvent,
    channel_id: str,
    text: str,
    state: dict[str, Any],
) -> bool:
    from cclark.handlers.message import _adapter

    if _adapter is None:
        return False

    # cancel / back
    if text.lower() in ("cancel", "quit", "exit", "#cancel"):
        _clear_state(event.user_id)
        await _adapter.send_text(channel_id, "Session creation cancelled.")
        return True
    if text.lower() == "back":
        state["phase"] = STATE_PROVIDER
        await _adapter.send_text(
            channel_id,
            "Select provider:\n"
            + "\n".join(f"  {i}. {p}" for i, p in enumerate(_PROVIDERS, 1)),
        )
        return True

    mode: str | None = None
    try:
        idx = int(text) - 1
        if 0 <= idx < len(_MODES):
            mode = _MODES[idx]
    except ValueError:
        pass

    if mode is None:
        for m in _MODES:
            if m.lower() == text.lower():
                mode = m
                break

    if mode is None:
        await _adapter.send_text(channel_id, f"Unknown mode: {text}")
        return True

    provider = state.get("provider") or config.default_provider
    await _create_window(channel_id, event.user_id, state["path"], provider, mode)
    return True


# ── Window creation ──────────────────────────────────────────────────────────


async def _create_window(
    channel_id: str,
    user_id: str,
    path: str,
    provider: str,
    approval_mode: str,
) -> None:
    """Create a tmux window, bind it to the channel, and forward pending text."""
    from cclark.handlers.message import _adapter, _gateway

    if _gateway is None or _adapter is None:
        return

    state = _get_or_create_state(user_id, channel_id)
    original_text = state.pop("original_text", "")
    pending_text = state.pop("pending_text", original_text)

    try:
        win = await _gateway.create_window(
            path,
            provider=provider,
            mode=approval_mode,
        )
        window_id = win.window_id if hasattr(win, "window_id") else str(win)
        window_name = getattr(win, "window_name", window_id)
    except Exception as e:
        logger.exception("Failed to create window")
        await _adapter.send_text(channel_id, f"Failed to create window: {e}")
        return

    # Bind channel to window
    _gateway.bind_channel(channel_id, window_id)

    # Record window + channel in window_store so on_message can route replies
    from unified_icc.window_state_store import window_store
    ws = window_store.get_window_state(window_id)
    ws.cwd = path
    ws.provider_name = provider
    ws.approval_mode = "normal" if approval_mode == "standard" else approval_mode
    ws.channel_id = channel_id
    window_store._schedule_save()

    # Mark as created so the fallback scan won't link unrelated sessions to this window
    window_store.mark_window_created(window_id)

    # Actively query session_id via /status — this runs right after the window is
    # created so the session_id is available immediately for routing and tracking.
    from unified_icc.session_monitor import get_active_monitor
    monitor = get_active_monitor()
    if monitor is not None:
        session_id = await monitor.detect_session_id(window_id)
        if session_id:
            ws.session_id = session_id
            window_store._schedule_save()

    logger.info(
        "Window created: id=%s provider=%s mode=%s path=%s",
        window_id, provider, approval_mode, path,
    )

    await _adapter.send_text(
        channel_id,
        f"Session started: {window_name} ({provider}, {approval_mode}) at {path}",
    )

    # Clean up session creation state
    _clear_state(user_id)

    # Forward the message that triggered session creation
    if pending_text and str(pending_text).strip():
        text = str(pending_text).strip()
        for prefix in ("#new", "#start", "/new", "/start"):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        if text:
            try:
                await _gateway.send_to_window(window_id, text)
            except Exception:
                logger.exception("Failed to forward pending text")
