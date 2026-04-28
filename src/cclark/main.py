"""cclark CLI entry point — run the Feishu bot via WebSocket long connection.

Supports multi-app mode: one WS connection + adapter per app in config.yaml.
In single-app mode (backward compat): behaves exactly as before.
"""

from __future__ import annotations

import asyncio
import signal
import sys
import structlog
from contextlib import suppress
from typing import Any

import uvicorn
from unified_icc.adapter import CardPayload
from unified_icc import UnifiedICC

from cclark.adapter import FeishuAdapter
from cclark.config import AppConfig, config
from cclark.feishu_client import FeishuClient
from cclark.handlers.message import handle_message, set_handlers
from cclark.webhook import app as health_app
from cclark.ws_client import (
    FeishuWSClient,
    register_message_handler,
)

logger = structlog.get_logger()

# ── App registry ────────────────────────────────────────────────────────────────

# app_name → FeishuAdapter (for routing outbound messages to the right app)
_app_adapters: dict[str, FeishuAdapter] = {}
# app_name → FeishuWSClient (for graceful shutdown)
_ws_clients: dict[str, FeishuWSClient] = {}
# app_name → FeishuClient (for cleanup)
_feishu_clients: dict[str, FeishuClient] = {}


# ── App context for handlers ────────────────────────────────────────────────


def get_adapter_for_channel(channel_id: str) -> FeishuAdapter | None:
    """Look up the right FeishuAdapter for a channel_id (multi-app routing)."""
    if _app_adapters:
        # Multi-app: route by app name in channel_id
        app_name = config.app_name_for_channel(channel_id)
        return _app_adapters.get(app_name) or _app_adapters.get("default")
    # Single-app fallback
    return next(iter(_app_adapters.values()), None)


# ── Gateway callbacks ────────────────────────────────────────────────────────


STX = "\x02"
_EXP_START = "\x02EXPQUOTE_START\x02"
_EXP_END = "\x02EXPQUOTE_END\x02"


def _clean_text(raw: str) -> str:
    """Strip all STX chars and EXPQUOTE markers from raw text."""
    return raw.replace(_EXP_START, "").replace(_EXP_END, "").replace(STX, "")


def _looks_like_thinking(m: Any) -> bool:
    """Return True for messages that must be handled only by thinking cards."""
    ct = getattr(m, "content_type", "text") or "text"
    if ct == "thinking":
        return True
    text = getattr(m, "text", "") or ""
    return _EXP_START in text or _EXP_END in text


def _split_messages(messages: list[Any]) -> tuple[list[Any], list[Any]]:
    """Split messages into thinking vs non-thinking lists."""
    thinking, regular = [], []
    for m in messages:
        if getattr(m, "role", "") == "user":
            continue
        if _looks_like_thinking(m):
            thinking.append(m)
        else:
            regular.append(m)
    return thinking, regular


async def _send_regular_text(adapter, channel_id: str, regular_msgs: list[Any]) -> None:
    """Send non-thinking messages as plain text."""
    combined = "\n".join(
        _clean_text(getattr(m, "text", "") or "")
        for m in regular_msgs
        if getattr(m, "text", "") and not _looks_like_thinking(m)
    )
    if combined:
        try:
            await adapter.send_text(channel_id, combined)
        except Exception:
            logger.exception("send_text failed channel=%s", channel_id)


async def _send_regular_verbose_card(
    adapter,
    channel_id: str,
    regular_msgs: list[Any],
    *,
    provider: str = "",
) -> None:
    """Send non-thinking messages through the verbose streaming card."""
    combined = "\n".join(
        _clean_text(getattr(m, "text", "") or "")
        for m in regular_msgs
        if getattr(m, "text", "") and not _looks_like_thinking(m)
    )
    if not combined:
        return

    from cclark.cards.streaming import VerboseCardStreamer
    from cclark.state import get_current_turn_index

    streamer = VerboseCardStreamer(
        client=adapter._client,
        channel_id=channel_id,
        user_id="__channel__",
        provider=provider,
    )
    try:
        await streamer.push(combined, turn_index=get_current_turn_index(channel_id))
        await streamer.flush()
    except Exception:
        logger.exception("verbose card send failed channel=%s", channel_id)


async def _handle_thinking(adapter, channel_id: str, thinking_msgs: list[Any], verbose_on: bool) -> None:
    """Handle thinking messages for a channel.

    - verbose_on=True:  显示实际 thinking 内容（ThinkingCardStreamer，灰色卡片）
    - verbose_on=False: 显示占位符 🤔 Thinking... → 🤔 Thinking...OK!
                        （同样是灰色卡片，但丢弃实际内容）
    """
    if not thinking_msgs:
        return
    from cclark.cards.thinking import ThinkingCardStreamer

    streamer = ThinkingCardStreamer(adapter, channel_id, placeholder_only=not verbose_on)
    for m in thinking_msgs:
        text = _clean_text(getattr(m, "text", "") or "")
        is_complete = getattr(m, "is_complete", True)
        try:
            await streamer.push_thinking(text, is_complete=is_complete)
        except Exception:
            logger.exception("ThinkingCardStreamer failed channel=%s", channel_id)


async def _dispatch_channel_messages(
    channel_id: str,
    messages: list[Any],
    _session_id: str,
    _gateway: UnifiedICC,
) -> None:
    """Dispatch messages to one channel, respecting verbose mode and content types."""
    adapter = get_adapter_for_channel(channel_id)
    if adapter is None:
        logger.warning("No adapter for channel %s", channel_id)
        return

    from cclark.state import get_verbose_state
    from unified_icc.window_state_store import window_store

    verbose_on = getattr(get_verbose_state(channel_id), "_verbose_enabled", False)
    thinking_msgs, regular_msgs = _split_messages(messages)
    provider = ""
    window_id = _gateway.channel_router.resolve_window(channel_id)
    if window_id:
        ws = window_store.get_window_state(window_id)
        provider = ws.provider_name or ""

    if verbose_on:
        await _send_regular_verbose_card(
            adapter, channel_id, regular_msgs, provider=provider
        )
    else:
        await _send_regular_text(adapter, channel_id, regular_msgs)
    await _handle_thinking(adapter, channel_id, thinking_msgs, verbose_on)


async def _register_callbacks(gateway: UnifiedICC) -> None:  # noqa: C901,PLR0915
    """Register gateway event callbacks to forward agent output to Feishu."""

    async def on_message(event: Any) -> None:  # noqa: C901
        try:
            # Resolve channel_ids
            channel_ids: list[str] = list(getattr(event, "channel_ids", []) or [])
            if not channel_ids:
                from unified_icc.window_state_store import window_store

                session_id = getattr(event, "session_id", "")
                direct = window_store.find_channel_by_session(session_id)
                if direct:
                    channel_ids = [direct]

            if not channel_ids:
                channel_ids = gateway.channel_router.resolve_channels(event.window_id)

            if not channel_ids:
                channel_ids = [
                    cid for cid, _, _ in gateway.channel_router.iter_channel_bindings()
                ]

            if not channel_ids:
                return

            messages: list = getattr(event, "messages", [])
            session_id = getattr(event, "session_id", "")

            logger.info(
                "on_message: session=%s msg_count=%d channels=%s",
                session_id,
                len(messages),
                channel_ids,
            )

            for channel_id in channel_ids:
                await _dispatch_channel_messages(channel_id, messages, session_id, gateway)

        except Exception:  # noqa: BLE001
            logger.exception("on_message handler failed")

    async def on_status(event: Any) -> None:
        try:
            channel_ids = list(getattr(event, "channel_ids", []) or [])
            if not channel_ids:
                channel_ids = gateway.channel_router.resolve_channels(event.window_id)
            if not channel_ids:
                from unified_icc.window_state_store import window_store

                ws = window_store.get_window_state(event.window_id)
                if ws.channel_id:
                    channel_ids = [ws.channel_id]

            for channel_id in channel_ids:
                adapter = get_adapter_for_channel(channel_id)
                if adapter is None:
                    continue
                try:
                    if getattr(event, "status", "") == "interactive":
                        body = str(getattr(event, "display_label", "") or "").strip()
                        if body:
                            body = (
                                f"{body}\n\n"
                                "Reply with `1`, `2`, or `3` to choose in Claude."
                            )
                        await adapter.send_card(
                            channel_id,
                            CardPayload(
                                title="Claude needs input",
                                body=body,
                                color="orange",
                            ),
                        )
                    else:
                        text = (
                            f"[status] Session {event.status} — "
                            f"{getattr(event, 'provider', '') or 'unknown'} | "
                            f"{getattr(event, 'working_dir', '') or ''}"
                        )
                        await adapter.send_text(channel_id, text)
                except Exception:
                    logger.exception("on_status failed for channel %s", channel_id)
        except Exception:  # noqa: BLE001
            logger.exception("on_status handler failed")

    async def on_hook(event: Any) -> None:
        try:
            channel_ids = gateway.channel_router.resolve_channels(event.window_id)
            if not channel_ids:
                from unified_icc.window_state_store import window_store

                ws = window_store.get_window_state(event.window_id)
                if ws.channel_id:
                    channel_ids = [ws.channel_id]

            for channel_id in channel_ids:
                adapter = get_adapter_for_channel(channel_id)
                if adapter is None:
                    continue
                try:
                    await adapter.send_text(
                        channel_id,
                        f"[hook] {getattr(event, 'hook_name', '')}: {getattr(event, 'message', '')}",
                    )
                except Exception:
                    logger.exception("on_hook failed for channel %s", channel_id)
        except Exception:  # noqa: BLE001
            logger.exception("on_hook handler failed")

    gateway.on_message(on_message)
    gateway.on_status(on_status)
    gateway.on_hook_event(on_hook)


# ── WS client ────────────────────────────────────────────────────────────────


def _build_adapter(app: AppConfig) -> FeishuAdapter:
    client = FeishuClient(app.app_id, app.app_secret)
    _feishu_clients[app.name] = client
    adapter = FeishuAdapter(client)
    _app_adapters[app.name] = adapter
    # Also register as 'default' so single-app routing works
    if app.name == config.get_default_app().name:
        _app_adapters["default"] = adapter
    return adapter


async def _main() -> None:
    """Start the cclark bot (WebSocket mode, supports multi-app)."""
    global _ws_clients

    gateway = UnifiedICC()
    await gateway.start()
    logger.info("Gateway started")

    await _register_callbacks(gateway)

    # Build one FeishuClient + Adapter per app
    for app in config.apps:
        _build_adapter(app)

    # Use the default app's adapter for the message/handler subsystem
    default_adapter = _app_adapters.get(config.get_default_app().name)
    if default_adapter is None:
        raise RuntimeError("No adapter for default app")
    set_handlers(gateway, default_adapter)

    # Wire WS client → handler system
    register_message_handler(handle_message)

    # Import handlers to trigger @register decorators
    from cclark.handlers import message, screenshot, session_creation  # noqa: F401

    # Start one WS client per app
    ws_tasks: list[asyncio.Task[None]] = []
    for app in config.apps:
        ws_client = FeishuWSClient(
            app_id=app.app_id,
            app_secret=app.app_secret,
            app_name=app.name,
        )
        _ws_clients[app.name] = ws_client
        ws_tasks.append(asyncio.create_task(ws_client.start()))

    # Start one uvicorn per app (different ports in multi-app mode)
    server_tasks: list[asyncio.Task[None]] = []
    for app in config.apps:
        port = app.health_port if config.is_multi_app else config.health_port
        uvicorn_config = uvicorn.Config(
            health_app,
            host="0.0.0.0",
            port=port,
            log_level="info",
        )
        server = uvicorn.Server(uvicorn_config)
        server_tasks.append(asyncio.create_task(server.serve()))

    shutdown_started = False

    async def shutdown() -> None:
        nonlocal shutdown_started
        if shutdown_started:
            return
        shutdown_started = True
        logger.info("Shutting down...")
        for ws_client in _ws_clients.values():
            await ws_client.stop()
        for task in ws_tasks:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await gateway.stop()
        for client in _feishu_clients.values():
            await client.close()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

    app_names = ", ".join(a.name for a in config.apps)
    logger.info("cclark starting: %d app(s) [%s]", len(config.apps), app_names)

    await asyncio.gather(*server_tasks, *ws_tasks)


def main() -> None:
    """CLI entry point via pyproject.toml script."""
    if sys.platform == "win32":
        asyncio.set_event_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main())


if __name__ == "__main__":
    main()
