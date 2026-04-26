"""Integration tests for the FastAPI webhook server."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from cclark.webhook import create_app, register_callback_handler, register_message_handler


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    mock_client = MagicMock()
    app = create_app(mock_client)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_url_verification_returns_challenge(client: AsyncClient) -> None:
    response = await client.post(
        "/webhook/event",
        json={"challenge": "my_challenge_string"},
    )
    assert response.status_code == 200
    assert response.json() == {"challenge": "my_challenge_string"}


@pytest.mark.asyncio
async def test_card_callback_routed_to_handler(client: AsyncClient) -> None:
    handler = AsyncMock()
    register_callback_handler(handler)

    try:
        payload = {
            "action": {"value": '{"action": "noop"}', "message_id": "om_card1"},
            "chat": {"chat_id": "oc_chat1", "thread_id": ""},
            "sender": {"sender_id": {"open_id": "ou_testuser1"}},
            "token": "test_token",
        }
        response = await client.post("/webhook/event", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        handler.assert_awaited_once()
    finally:
        register_callback_handler(AsyncMock())


@pytest.mark.asyncio
async def test_message_event_routed_to_handler(client: AsyncClient) -> None:
    handler = AsyncMock()
    register_message_handler(handler)

    try:
        payload = {
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
        }
        response = await client.post("/webhook/event", json=payload)
        assert response.status_code == 200
        handler.assert_awaited_once()
    finally:
        register_message_handler(AsyncMock())


@pytest.mark.asyncio
async def test_invalid_json_returns_400(client: AsyncClient) -> None:
    response = await client.post(
        "/webhook/event",
        content=b"not json at all",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    assert "error" in response.json()


@pytest.mark.asyncio
async def test_non_text_message_acknowledged_without_handler_call(
    client: AsyncClient,
) -> None:
    handler = AsyncMock()
    register_message_handler(handler)

    try:
        payload = {
            "event": {
                "chat_id": "oc_chat1",
                "sender": {"sender_id": {"open_id": "ou_testuser1"}},
                "message": {
                    "message_id": "om_msg1",
                    "msg_type": "image",
                    "content": "{}",
                },
            }
        }
        response = await client.post("/webhook/event", json=payload)
        assert response.status_code == 200
        handler.assert_not_awaited()
    finally:
        register_message_handler(AsyncMock())


@pytest.mark.asyncio
async def test_bot_message_skipped(client: AsyncClient) -> None:
    handler = AsyncMock()
    register_message_handler(handler)

    try:
        payload = {
            "event": {
                "chat_id": "oc_chat1",
                "sender": {"sender_id": {"open_id": "ou_bot"}},
                "message": {
                    "message_id": "om_msg1",
                    "msg_type": "text",
                    "content": '{"text": "my own message"}',
                },
            }
        }
        response = await client.post("/webhook/event", json=payload)
        assert response.status_code == 200
        handler.assert_not_awaited()
    finally:
        register_message_handler(AsyncMock())


@pytest.mark.asyncio
async def test_callback_token_mismatch_returns_403(client: AsyncClient) -> None:
    payload = {
        "action": {"value": '{"action": "noop"}', "message_id": "om_card1"},
        "chat": {"chat_id": "oc_chat1", "thread_id": ""},
        "sender": {"sender_id": {"open_id": "ou_testuser1"}},
        "token": "wrong_token",
    }
    response = await client.post("/webhook/event", json=payload)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_callback_handler_exception_returns_500(client: AsyncClient) -> None:
    async def bad_handler(_: dict) -> None:
        msg: str = None  # type: ignore
        print(msg.upper())  # raises

    register_callback_handler(bad_handler)
    try:
        payload = {
            "action": {"value": '{"action": "noop"}', "message_id": "om_card1"},
            "chat": {"chat_id": "oc_chat1", "thread_id": ""},
            "sender": {"sender_id": {"open_id": "ou_testuser1"}},
            "token": "test_token",
        }
        response = await client.post("/webhook/event", json=payload)
        assert response.status_code == 500
    finally:
        register_callback_handler(AsyncMock())


@pytest.mark.asyncio
async def test_callback_no_handler_returns_error(client: AsyncClient) -> None:
    register_callback_handler(AsyncMock())  # reset to no-op
    with patch("cclark.webhook._callback_handler", None):
        payload = {
            "action": {"value": '{"action": "noop"}', "message_id": "om_card1"},
            "chat": {"chat_id": "oc_chat1", "thread_id": ""},
            "sender": {"sender_id": {"open_id": "ou_testuser1"}},
            "token": "test_token",
        }
        response = await client.post("/webhook/event", json=payload)
        # Returns 200 with error body when no handler registered
        assert response.json() == {"error": "no handler"}
