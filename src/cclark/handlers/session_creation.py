"""Session creation flow — directory browser + provider picker + window creation."""

from __future__ import annotations

import json
import structlog
import urllib.parse
from pathlib import Path
from typing import Any

from cclark.callback_data import (
    DB_CONFIRM,
    DB_HOME,
    DB_SEL,
    DB_TOGGLE_STAR,
    DB_UP,
    MODE,
    MODE_YOLO,
    PROV,
    PROV_CLAUDE,
    PROV_CODEX,
    PROV_GEMINI,
    PROV_PI,
    PROV_SHELL,
)
from cclark.callback_registry import CallbackContext, register
from cclark.config import config
from cclark.event_parsers import FeishuMessageEvent
from cclark.handlers.message import _adapter, _gateway
from cclark.user_preferences import user_preferences

logger = structlog.get_logger()

_PAGE_SIZE = 15


# ── Card building helpers ────────────────────────────────────────────────────


def _enc(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def _dec(s: str) -> str:
    return urllib.parse.unquote(s)


def _build_dir_browser_card(  # noqa: C901
    path: str,
    page: int,
    user_id: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Build directory browser card JSON and action list.

    Returns (card_json, actions).
    """
    import os

    p = Path(path)
    entries = []
    try:
        for name in sorted(os.listdir(p)):
            full = p / name
            if full.is_dir() and not name.startswith("."):
                entries.append({"name": name, "type": "dir"})
    except OSError:
        pass

    # MRU + starred favorites at top
    mru = user_preferences.get_user_mru(user_id)
    starred = user_preferences.get_user_starred(user_id)
    favorites = mru + [d for d in starred if d not in mru]
    fav_entries = [
        {"name": Path(d).name, "path": d, "type": "fav"}
        for d in favorites[:5]
    ]

    start = page * _PAGE_SIZE
    page_entries = entries[start : start + _PAGE_SIZE]
    has_next = len(entries) > start + _PAGE_SIZE

    # Build elements
    header_md = f"**Directory:** `{_esc(path)}`"
    elements: list[dict[str, Any]] = [{"tag": "markdown", "content": header_md}]

    if fav_entries:
        fav_lines = [
            f"[⭐ {e['name']}](action:db:fav:{_enc(e['path'])})"
            for e in fav_entries
        ]
        elements.append({
            "tag": "markdown",
            "content": "<strong>Favorites</strong><br>" + " &nbsp; ".join(fav_lines),
        })
        elements.append({"tag": "hr"})

    # Navigation buttons
    nav_buttons = []
    if Path(path).parent != Path(path).resolve().parent:
        nav_buttons.append(_mkbtn("⬆ Up", f"db:up:{_enc(path)}"))
    nav_buttons.append(_mkbtn("🏠 Home", "db:home"))
    elements.append({"tag": "action", "children": nav_buttons})

    actions: list[dict[str, Any]] = []
    if page_entries:
        dir_lines = []
        for i, entry in enumerate(page_entries):
            full_path = str(p / entry["name"])
            line = f"[📁 {entry['name']}](action:db:sel:{_enc(full_path)})"
            dir_lines.append(line)
            actions.append({"idx": i, "path": full_path})
        elements.append({
            "tag": "markdown",
            "content": "<br>".join(dir_lines),
        })

    if page > 0 or has_next:
        paging_buttons = []
        if page > 0:
            paging_buttons.append(_mkbtn("◀ Prev", f"db:pg:{(page - 1)}"))
        if has_next:
            paging_buttons.append(_mkbtn("Next ▶", f"db:pg:{(page + 1)}"))
        elements.append({"tag": "action", "children": paging_buttons})

    # Confirm button
    confirm_btn = _mkbtn("✅ Confirm", f"db:confirm:{_enc(path)}")
    elements.append({"tag": "action", "children": [confirm_btn]})

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Select Directory"},
            "template": "blue",
        },
        "elements": elements,
    }
    return json.dumps(card), actions


def _build_provider_picker_card(selected_path: str) -> str:
    elements = [
        {
            "tag": "markdown",
            "content": f"**Working directory:** `{_esc(selected_path)}`\n\n"
                       "**Select a provider:**",
        }
    ]

    providers = [
        (PROV_CLAUDE, "🤖 Claude Code", "claude"),
        (PROV_CODEX, "🔮 Codex", "codex"),
        (PROV_GEMINI, "✨ Gemini CLI", "gemini"),
        (PROV_PI, "🧪 Pi", "pi"),
        (PROV_SHELL, "💻 Shell", "shell"),
    ]

    buttons = [
        _mkbtn(label, f"prov:{provider_id}")
        for label, _desc, provider_id in providers
    ]
    elements.append({"tag": "action", "children": buttons})  # type: ignore[arg-type]

    return json.dumps({
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Select Provider"},
            "template": "turquoise",
        },
        "elements": elements,
    })


def _build_mode_picker_card(selected_path: str, provider: str) -> str:
    elements = [
        {
            "tag": "markdown",
            "content": f"**Provider:** {provider}\n"
                       f"**Directory:** `{_esc(selected_path)}`\n\n"
                       "**Select mode:**",
        }
    ]

    buttons = [
        _mkbtn("📝 Standard (approval)", "mode:standard"),
        _mkbtn("🚀 YOLO (no approval)", "mode:yolo"),
    ]
    elements.append({"tag": "action", "children": buttons})  # type: ignore[arg-type]

    return json.dumps({
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{provider.title()} — Select Mode"},
            "template": "orange",
        },
        "elements": elements,
    })


def _mkbtn(label: str, action: str) -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "action_type": "interactive",
        "value": {"action": action},
    }


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── Per-user browse state (simple in-memory) ────────────────────────────────

_browse_state: dict[str, dict[str, Any]] = {}


def _get_state(user_id: str) -> dict[str, Any]:
    return _browse_state.setdefault(user_id, {})


# ── Entry point ─────────────────────────────────────────────────────────────


async def start_session_creation(event: FeishuMessageEvent, channel_id: str) -> None:
    """Show the directory browser card for a new session."""
    from cclark.handlers.message import _adapter

    if _adapter is None:
        return

    default_path = str(Path.home())
    state = _get_state(event.user_id)
    state["path"] = default_path
    state["page"] = 0
    state["channel_id"] = channel_id
    state["original_text"] = event.text

    card_json, _ = _build_dir_browser_card(default_path, 0, event.user_id)
    await _adapter.send_interactive_card(channel_id, card_json)


# ── Callback handlers ──────────────────────────────────────────────────────


@register(DB_SEL, DB_UP, DB_HOME, DB_CONFIRM, DB_TOGGLE_STAR, "db:pg:")
async def handle_dir_callback(ctx: CallbackContext) -> None:
    from cclark.handlers.message import _adapter

    if _adapter is None:
        return

    value = ctx.value
    state = _get_state(ctx.user_id)

    if value == DB_HOME:
        path = str(Path.home())
        state["path"] = path
        state["page"] = 0
    elif value.startswith("db:pg:"):
        try:
            page = int(value[len("db:pg:"):])
        except ValueError:
            page = 0
        state["page"] = page
        path: str = state.get("path") or str(Path.home())
    elif value == DB_UP:
        parent = Path(state.get("path") or str(Path.home())).resolve().parent
        path = str(parent)
        state["path"] = path
        state["page"] = 0
    elif value.startswith(DB_SEL):
        subdir = _dec(value[len(DB_SEL):])
        path = subdir
        state["path"] = path
        state["page"] = 0
    elif value.startswith(DB_TOGGLE_STAR):
        dir_path = _dec(value[len(DB_TOGGLE_STAR):])
        user_preferences.toggle_user_star(ctx.user_id, dir_path)
        return  # Just update the star, don't rebuild card
    elif value == DB_CONFIRM:
        selected_path: str = state.get("path") or str(Path.home())
        user_preferences.update_user_mru(ctx.user_id, selected_path)
        card_json = _build_provider_picker_card(selected_path)
        await _adapter.send_interactive_card(ctx.channel_id, card_json)
        return
    else:
        path = state.get("path") or str(Path.home())

    card_json, _ = _build_dir_browser_card(path, int(state["page"]), ctx.user_id)
    await _adapter.send_interactive_card(ctx.channel_id, card_json)


@register(PROV)
async def handle_provider_callback(ctx: CallbackContext) -> None:
    from cclark.handlers.message import _adapter

    if _adapter is None:
        return

    provider = ctx.value[len(PROV):]
    state = _get_state(ctx.user_id)
    state["provider"] = provider
    selected_path: str = state.get("path") or str(Path.home())

    # Shell has no mode picker
    if provider == "shell":
        await _create_window(ctx, selected_path, provider, "standard")
        return

    card_json = _build_mode_picker_card(selected_path, provider)
    await _adapter.send_interactive_card(ctx.channel_id, card_json)


@register(MODE)
async def handle_mode_callback(ctx: CallbackContext) -> None:
    if _adapter is None:
        return

    value = ctx.value
    state = _get_state(ctx.user_id)
    provider: str = state.get("provider") or config.default_provider
    selected_path: str = state.get("path") or str(Path.home())

    mode = "yolo" if value == MODE_YOLO else "standard"

    await _create_window(ctx, selected_path, provider, mode)


async def _create_window(
    ctx: CallbackContext,
    path: str,
    provider: str,
    approval_mode: str,
) -> None:
    """Create a tmux window, bind it to the channel, and forward pending text."""
    from cclark.handlers.message import _adapter

    if _gateway is None or _adapter is None:
        return

    state = _get_state(ctx.user_id)
    original_text = state.pop("original_text", "")
    pending_text = state.pop("pending_text", original_text)

    try:
        win = await _gateway.create_window(
            path,
            provider=provider,
            approval_mode=approval_mode,
        )
        window_id = win.window_id if hasattr(win, "window_id") else str(win)
        window_name = getattr(win, "window_name", window_id)
    except Exception as e:
        logger.exception("Failed to create window")
        await _adapter.send_text(ctx.channel_id, f"Failed to create window: {e}")
        return

    # Bind channel to window
    _gateway.bind_channel(ctx.channel_id, window_id)
    logger.info(
        "Window created: id=%s provider=%s mode=%s path=%s",
        window_id, provider, approval_mode, path,
    )

    await _adapter.send_text(
        ctx.channel_id,
        f"Session started: {window_name} ({provider}) at {path}",
    )

    # Forward the message that triggered session creation
    if pending_text and str(pending_text).strip():
        # Strip the /new command
        text = str(pending_text).strip()
        for prefix in ("/new", "/start"):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        if text:
            ok, err = await _gateway.send_to_window(window_id, text)
            if not ok:
                logger.warning("Failed to forward pending text: %s", err)
