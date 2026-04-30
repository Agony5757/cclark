from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from cclark.cards.thinking import ThinkingCardStreamer, finalize_active_thinking_card
from cclark.feishu_client import FeishuClient
from cclark.state import get_verbose_state, reset_channel_state


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
async def test_completed_thinking_card_marks_card_inactive_for_same_turn_reuse() -> None:
    streamer = _make_streamer()

    await streamer.push_thinking("done", is_complete=True)

    assert streamer._state.streaming_thinking_card_id == "om_card"
    assert streamer._state.streaming_thinking_text == ""
    assert streamer._state.streaming_thinking_active is False


@pytest.mark.asyncio
async def test_finalize_patches_active_card_and_marks_state_inactive() -> None:
    streamer = _make_streamer()

    await streamer.push_thinking("working", is_complete=False)
    await streamer.finalize()

    streamer._client.patch_message.assert_awaited_once()
    assert streamer._state.streaming_thinking_card_id == "om_card"
    assert streamer._state.streaming_thinking_text == ""
    assert streamer._state.streaming_thinking_active is False


@pytest.mark.asyncio
async def test_same_turn_finalize_reuses_existing_thinking_card() -> None:
    streamer = _make_streamer()

    await streamer.push_thinking("first", is_complete=False)
    await streamer.finalize()
    await streamer.push_thinking("second", is_complete=False)

    streamer._adapter.send_interactive_card.assert_awaited_once()
    assert streamer._client.patch_message.await_count == 2
    assert streamer._state.streaming_thinking_card_id == "om_card"
    assert streamer._state.streaming_thinking_active is True


@pytest.mark.asyncio
async def test_finalize_active_thinking_card_respects_placeholder_mode() -> None:
    streamer = _make_streamer(placeholder_only=True)
    get_verbose_state("feishu:oc_test_chat")._verbose_enabled = False

    await streamer.push_thinking("secret reasoning", is_complete=False)
    await finalize_active_thinking_card(streamer._adapter, "feishu:oc_test_chat")

    _, card_json = streamer._client.patch_message.await_args.args
    card = json.loads(card_json)
    assert card["elements"][0]["content"] == "🤔 Thinking...OK!"
