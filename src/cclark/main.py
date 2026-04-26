"""cclark CLI entry point — run the Feishu bot with unified-icc gateway."""

from __future__ import annotations

import asyncio
import signal
import sys
import structlog
from contextlib import suppress

import uvicorn
from unified_icc import UnifiedICC

from cclark.adapter import FeishuAdapter
from cclark.callback_registry import dispatch as dispatch_callback
from cclark.config import config as app_config
from cclark.feishu_client import FeishuClient
from cclark.handlers.message import handle_message, set_handlers
from cclark.webhook import create_app, register_callback_handler, register_message_handler

logger = structlog.get_logger()


async def _build_gateway() -> UnifiedICC:
    """Build and start the unified-icc gateway."""
    gateway = UnifiedICC()
    await gateway.start()
    logger.info("Gateway started")
    return gateway


def _build_adapter(client: FeishuClient) -> FeishuAdapter:
    return FeishuAdapter(client)


async def _register_callbacks(gateway: UnifiedICC, adapter: FeishuAdapter) -> None:  # noqa: C901
    """Register gateway event callbacks to forward agent output to Feishu."""
    # Message callbacks — forward agent output to the channel
    async def on_message(event) -> None:
        try:
            channel_ids = getattr(gateway, "channel_router").resolve_channels(event.window_id)
            for channel_id in channel_ids:
                if event.text:
                    await adapter.send_text(channel_id, event.text)
                elif event.screenshot_bytes:
                    await adapter.send_image(channel_id, event.screenshot_bytes)
        except Exception:  # noqa: BLE001
            logger.exception("on_message handler failed")

    async def on_status(event) -> None:
        try:
            channel_ids = getattr(gateway, "channel_router").resolve_channels(event.window_id)
            for channel_id in channel_ids:
                from cclark.cards.status import build_status_card
                card = build_status_card(
                    title=f"Session {event.status}",
                    window_id=event.window_id,
                    provider=event.provider or "unknown",
                    status=event.status,
                    working_dir=event.working_dir or "",
                )
                await adapter.send_interactive_card(channel_id, card)
        except Exception:  # noqa: BLE001
            logger.exception("on_status handler failed")

    async def on_hook(event) -> None:
        try:
            channel_ids = getattr(gateway, "channel_router").resolve_channels(event.window_id)
            for channel_id in channel_ids:
                await adapter.send_text(channel_id, f"[hook] {event.hook_name}: {event.message}")
        except Exception:  # noqa: BLE001
            logger.exception("on_hook handler failed")

    gateway.on_message(on_message)
    gateway.on_status(on_status)
    gateway.on_hook_event(on_hook)


async def _callback_handler(ctx) -> None:
    """Route a Feishu card callback to the handler system."""
    await dispatch_callback(ctx)


async def _message_handler(event) -> None:
    """Route a Feishu message event to the message handler."""
    await handle_message(event)


async def _main() -> None:
    """Start the cclark bot."""
    client = FeishuClient(app_config.feishu_app_id, app_config.feishu_app_secret)
    adapter = _build_adapter(client)

    gateway = await _build_gateway()
    await _register_callbacks(gateway, adapter)

    set_handlers(gateway, adapter)
    register_message_handler(_message_handler)
    register_callback_handler(_callback_handler)

    # Import handlers to trigger @register decorators
    from cclark.handlers import callback, message, screenshot, session_creation, toolbar  # noqa: F401

    app = create_app(client)

    uvicorn_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=app_config.webhook_port,
        log_level="info",
    )
    server = uvicorn.Server(uvicorn_config)

    async def shutdown() -> None:
        logger.info("Shutting down...")
        await gateway.stop()
        await client.close()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

    logger.info("cclark starting on port %d", app_config.webhook_port)
    await server.serve()


def main() -> None:
    """CLI entry point via pyproject.toml script."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main())


if __name__ == "__main__":
    main()
