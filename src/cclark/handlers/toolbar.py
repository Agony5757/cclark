"""Toolbar handler — builds and updates toolbar cards, dispatches button clicks."""

from __future__ import annotations

import structlog

from cclark.adapter import FeishuAdapter
from cclark.callback_data import TB
from cclark.callback_registry import CallbackContext, register
from cclark.cards.toolbar import build_toolbar_card
from cclark.state import get_toolbar_state
from cclark.toolbar_config import load_toolbar_config

logger = structlog.get_logger()

# Lazily loaded toolbar config (path set by config)
_toolbar_config = None


def _get_toolbar_config() -> object:
    global _toolbar_config
    if _toolbar_config is None:
        path = None
        try:
            from cclark.config import config
            path = config.toolbar_config_path or None
        except (AttributeError, ImportError):
            pass
        _toolbar_config = load_toolbar_config(path)
    return _toolbar_config


async def show_toolbar(
    channel_id: str,
    window_id: str,
    adapter: FeishuAdapter,
    status_label: str = "",
    provider: str = "claude",
) -> None:
    """Send or update the toolbar card for a channel."""
    toolbar_state = get_toolbar_state(channel_id)
    cfg = _get_toolbar_config()

    card_json = build_toolbar_card(window_id, provider, cfg, status_label)
    toolbar_state.toolbar_window_id = window_id

    if toolbar_state.toolbar_card_id:
        try:
            await adapter._client.patch_message(toolbar_state.toolbar_card_id, card_json)
            return
        except Exception:  # noqa: BLE001
            pass

    msg_id = await adapter.send_interactive_card(channel_id, card_json)
    toolbar_state.toolbar_card_id = msg_id


@register(TB)
async def handle_toolbar_callback(ctx: CallbackContext) -> None:
    """Handle toolbar button clicks."""
    from cclark.handlers.message import _adapter, _gateway

    if _gateway is None or _adapter is None:
        return

    # Parse: tb:<window_id>:<action_name>
    value = ctx.value[len(TB):]
    parts = value.split(":", 1)
    window_id = parts[0]
    action_name = parts[1] if len(parts) > 1 else ""

    if not window_id:
        return

    # Resolve active window for this channel if needed
    active_window = _gateway.channel_router.resolve_window(ctx.channel_id)
    if active_window is None:
        await _adapter.send_text(ctx.channel_id, "No active session.")
        return

    # Use the window_id from the button (may differ from active)
    target_window = window_id or active_window

    action = _get_toolbar_config().actions.get(action_name)
    if action is None:
        logger.warning("Unknown toolbar action: %s", action_name)
        return

    if action.action_type == "builtin":
        await _handle_builtin(action_name, target_window, ctx.channel_id, _gateway, _adapter)
    elif action.action_type == "key":
        await _gateway.send_key(target_window, action.payload)
    elif action.action_type == "text":
        await _gateway.send_to_window(target_window, action.payload)


async def _handle_builtin(
    action_name: str,
    window_id: str,
    channel_id: str,
    gateway,
    adapter: FeishuAdapter,
) -> None:
    """Handle built-in toolbar actions."""
    if action_name == "screenshot":
        from cclark.handlers.screenshot import handle_screenshot_request
        await handle_screenshot_request(channel_id, gateway, adapter)
    elif action_name == "live":
        # Toggle live output mode — show latest pane capture
        try:
            pane = await gateway.capture_pane(window_id)
            await adapter.send_text(channel_id, f"<pre>{pane[-3000:]}</pre>")
        except Exception as e:  # noqa: BLE001
            await adapter.send_text(channel_id, f"Live capture failed: {e}")
    elif action_name == "dismiss":
        # Remove toolbar card
        state = get_toolbar_state(channel_id)
        state.toolbar_card_id = None
        state.toolbar_window_id = None
    elif action_name in ("ctrlc", "send", "enter"):
        key_map = {"ctrlc": "\x03", "send": "\x04", "enter": "\r"}
        await gateway.send_key(window_id, key_map.get(action_name, ""))
    else:
        logger.debug("Builtin action %s not yet implemented", action_name)
