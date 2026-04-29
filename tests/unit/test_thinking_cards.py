from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from cclark.cards.thinking import ThinkingCardStreamer
from cclark.feishu_client import FeishuClient
from cclark.state import reset_channel_state


def _make_streamer(*, placeholder_only: bool = False) -> ThinkingCardStreamer:
    reset_channel_state("feishu:oc_test_chat")
    adapter = MagicMock()
    adapter._client = MagicMock(spec=FeishuClient)
    adapter._client.patch_message = AsyncMock()
    adapter.send_interactive_card = AsyncMock(return_value="om_card")
    return ThinkingCardStreamer(
        adapter,
        "feishu:oc_test_chat",
        placeholder_only=placeholder_only,
    )


def test_thinking_card_marks_shared_updates_enabled() -> None:
    streamer = _make_streamer()
    card = streamer._build_card("thinking...", done=False)
    assert card["config"]["wide_screen_mode"] is True
    assert card["config"]["update_multi"] is True


@pytest.mark.asyncio
async def test_patch_message_uses_http_patch() -> None:
    client = FeishuClient("cli_test", "secret")
    client._tenant_access_token = "token"
    client._token_expires_at = 10**12
    client._http.patch = AsyncMock()
    client._http.patch.return_value.raise_for_status = MagicMock()
    client._http.patch.return_value.json = MagicMock(return_value={"code": 0, "data": {}, "msg": "ok"})

    await client.patch_message("om_123", json.dumps({"config": {"update_multi": True}}))

    client._http.patch.assert_awaited_once()
    _, kwargs = client._http.patch.await_args
    assert kwargs["json"] == {"content": json.dumps({"config": {"update_multi": True}})}


@pytest.mark.asyncio
async def test_completed_thinking_card_resets_active_card() -> None:
    streamer = _make_streamer()

    await streamer.push_thinking("done", is_complete=True)

    assert streamer._state.streaming_thinking_card_id is None
    assert streamer._state.streaming_thinking_text == ""


@pytest.mark.asyncio
async def test_finalize_patches_active_card_and_resets_state() -> None:
    streamer = _make_streamer()

    await streamer.push_thinking("working", is_complete=False)
    await streamer.finalize()

    streamer._client.patch_message.assert_awaited_once()
    assert streamer._state.streaming_thinking_card_id is None
    assert streamer._state.streaming_thinking_text == ""
