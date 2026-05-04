from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from cclark.icc_ws_gateway import ICCWebSocketGateway


@pytest.mark.asyncio
async def test_agent_message_event_is_adapted_for_cclark_handlers() -> None:
    gateway = ICCWebSocketGateway("ws://127.0.0.1:8900/api/v1/ws")
    callback = AsyncMock()
    gateway.on_message(callback)

    await gateway._dispatch_event(
        {
            "type": "agent.message",
            "window_id": "@1",
            "session_id": "sid-1",
            "channel_ids": ["feishu:oc_chat"],
            "messages": [
                {
                    "text": "hello",
                    "role": "assistant",
                    "content_type": "text",
                    "is_complete": True,
                }
            ],
        }
    )

    callback.assert_awaited_once()
    event = callback.await_args.args[0]
    assert event.window_id == "@1"
    assert event.channel_ids == ["feishu:oc_chat"]
    assert event.messages[0].text == "hello"
    assert gateway.resolve_window("feishu:oc_chat") == "@1"
    assert gateway.resolve_channels("@1") == ["feishu:oc_chat"]


@pytest.mark.asyncio
async def test_status_event_is_adapted_for_cclark_handlers() -> None:
    gateway = ICCWebSocketGateway("ws://127.0.0.1:8900/api/v1/ws")
    callback = AsyncMock()
    gateway.on_status(callback)

    await gateway._dispatch_event(
        {
            "type": "agent.status",
            "window_id": "@2",
            "session_id": "sid-2",
            "channel_ids": ["feishu:oc_chat"],
            "status": "interactive",
            "display_label": "Do you want to proceed?",
            "provider": "claude",
        }
    )

    callback.assert_awaited_once()
    event = callback.await_args.args[0]
    assert event.status == "interactive"
    assert event.display_label == "Do you want to proceed?"
    assert event.provider == "claude"
