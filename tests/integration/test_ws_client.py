"""Integration tests for the Feishu WebSocket client and health endpoint."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from cclark.webhook import app as health_app
from cclark.ws_client import (
    _save_seen_state,
    _seen_events,
    _seen_messages,
    decode_frame,
    encode_frame,
    register_message_handler,
)


# ── Health endpoint ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def http_client() -> AsyncClient:
    transport = ASGITransport(app=health_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _clear_dedup_state() -> None:
    """Reset in-memory dedup state so tests don't interfere with each other."""
    _seen_events.clear()
    _seen_messages.clear()
    _save_seen_state()


@pytest.mark.asyncio
async def test_health_endpoint(http_client: AsyncClient) -> None:
    response = await http_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ── Protobuf frame encoding/decoding ───────────────────────────────────────────


class TestProtobufRoundtrip:
    """Round-trip encode → decode preserves all fields."""

    def test_control_frame_empty(self) -> None:
        frame = encode_frame(method=0, payload=b"", headers=[("type", "ping")], service_id=123)
        headers, payload, service_id, method = decode_frame(frame)
        assert headers == {"type": "ping"}
        assert payload == b""
        assert service_id == 123
        assert method == 0

    def test_data_frame_with_event_payload(self) -> None:
        event_json = json.dumps({"schema": "2.0", "event": {"chat_id": "oc_1"}}).encode()
        frame = encode_frame(
            method=1,
            payload=event_json,
            headers=[("type", "event"), ("message_id", "om_1")],
            service_id=456,
            seq_id=1,
        )
        headers, payload, service_id, method = decode_frame(frame)
        assert headers["type"] == "event"
        assert headers["message_id"] == "om_1"
        assert json.loads(payload)["event"]["chat_id"] == "oc_1"
        assert service_id == 456
        assert method == 1

    def test_multiple_headers(self) -> None:
        frame = encode_frame(
            method=1,
            payload=b'{"key":"val"}',
            headers=[("type", "event"), ("trace_id", "t1"), ("biz_rt", "5")],
            service_id=111,
        )
        headers, _, _, method = decode_frame(frame)
        assert headers["type"] == "event"
        assert headers["trace_id"] == "t1"
        assert headers["biz_rt"] == "5"
        assert method == 1


# ── Event dispatch ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ws_event_routes_to_registered_handler() -> None:
    handler = AsyncMock()
    register_message_handler(handler)
    try:
        from cclark.ws_client import FeishuWSClient

        client = FeishuWSClient(app_id="cli_test", app_secret="test")
        event_payload = json.dumps({
            "event": {
                "chat_id": "oc_chat1",
                "thread_id": "",
                "sender": {"sender_id": {"open_id": "ou_testuser1"}},
                "message": {
                    "message_id": "om_msg1",
                    "msg_type": "text",
                    "content": '{"text": "hello"}',
                },
            }
        }).encode()
        # _dispatch_event expects raw JSON payload bytes (not the full encoded frame)
        await client._dispatch_event(event_payload)
        handler.assert_awaited_once()
    finally:
        register_message_handler(AsyncMock())
