"""Thinking card streamer — incrementally updates a Feishu interactive card to show thinking progress.

Lifecycle:
  is_complete=False + no card  → create new card
  is_complete=False + card exists → patch update
  is_complete=True              → patch final state (remove spinner)

In verbose-off mode (placeholder_only=True) the card shows placeholder text
("Thinking..." / "Thinking...OK!") and discards actual thinking content.
In verbose-on mode it streams real thinking text until is_complete=True.
"""

from __future__ import annotations

import json
import structlog

from cclark.feishu_client import FeishuAPIError, FeishuClient
from cclark.state import get_verbose_state

logger = structlog.get_logger()

STX = "\x02"
EXP_START = "\x02EXPQUOTE_START\x02"
EXP_END = "\x02EXPQUOTE_END\x02"
_MAX_THINKING_CHARS = 8000


def _clean(text: str) -> str:
    return text.replace(EXP_START, "").replace(EXP_END, "").replace(STX, "")


def _truncate(text: str) -> str:
    if len(text) > _MAX_THINKING_CHARS:
        return text[:_MAX_THINKING_CHARS] + f"\n… (truncated, {len(text)} total)"
    return text


class ThinkingCardStreamer:
    """Manages the incremental thinking card lifecycle for one Feishu channel.

    When placeholder_only is True, the card shows placeholder text and discards
    actual thinking content. Otherwise it streams the real content, updating
    the card in-place until is_complete=True.

    Args:
        adapter: FeishuAdapter (must expose _client).
        channel_id: Feishu channel ID.
        placeholder_only: If True, render placeholders only (verbose=off mode).
    """

    def __init__(self, adapter, channel_id: str, *, placeholder_only: bool = False) -> None:
        self._adapter = adapter
        self._client: FeishuClient = adapter._client
        self._channel_id = channel_id
        self._state = get_verbose_state(channel_id)
        self._placeholder_only = placeholder_only

    @property
    def _card_id(self) -> str | None:
        return self._state.streaming_thinking_card_id

    @_card_id.setter
    def _card_id(self, value: str | None) -> None:
        self._state.streaming_thinking_card_id = value

    def _build_card(self, text: str, done: bool = False) -> dict:
        """Build the Feishu interactive card dict for the current thinking state.

        When placeholder_only=True, always renders placeholder text.
        When done=False, appends an in-progress indicator.
        """
        if self._placeholder_only:
            content = "🤔 Thinking...OK!" if done else "🤔 Thinking..."
            return {
                "config": {"wide_screen_mode": True, "update_multi": True},
                "header": {
                    "title": {"tag": "plain_text", "content": "🤔 Thinking..."},
                    "template": "grey",
                },
                "elements": [
                    {"tag": "markdown", "content": content},
                ],
            }

        clean = _truncate(_clean(text))
        content = clean
        if not done:
            content = clean + "\n\n⏳ Generating…"
        return {
            "config": {"wide_screen_mode": True, "update_multi": True},
            "header": {
                "title": {"tag": "plain_text", "content": "🤔 Thinking..."},
                "template": "grey",
            },
            "elements": [
                {"tag": "markdown", "content": content},
            ],
        }

    async def _send_card(self, card: dict) -> str:
        return await self._adapter.send_interactive_card(
            self._channel_id, json.dumps(card)
        )

    async def _patch_card(self, card: dict) -> None:
        if self._card_id is None:
            msg_id = await self._send_card(card)
            self._card_id = msg_id
            return
        try:
            await self._client.patch_message(self._card_id, json.dumps(card))
        except FeishuAPIError as exc:
            logger.warning(
                "update_multi failed card=%s, falling back to new card: %s",
                self._card_id, exc,
            )
            msg_id = await self._send_card(card)
            self._card_id = msg_id

    async def push_thinking(self, text: str, *, is_complete: bool) -> None:
        """Push a thinking text segment, creating or patching the card as needed.

        Args:
            text: Cleaned thinking text (markers already stripped).
            is_complete: If True, marks the thinking done and stops updating.
        """
        if not text:
            return
        self._state.streaming_thinking_text = text
        card = self._build_card(text, done=is_complete)

        if self._card_id is None:
            msg_id = await self._send_card(card)
            self._card_id = msg_id
            logger.info(
                "ThinkingCard: created card %s channel=%s",
                msg_id, self._channel_id,
            )
        elif is_complete:
            await self._patch_card(card)
            logger.info(
                "ThinkingCard: finalized card %s channel=%s",
                self._card_id, self._channel_id,
            )
        else:
            await self._patch_card(card)
            logger.debug(
                "ThinkingCard: patched card %s channel=%s",
                self._card_id, self._channel_id,
            )

        if is_complete:
            self._state.streaming_thinking_text = ""
            self._state.streaming_thinking_active = False
        else:
            self._state.streaming_thinking_active = True

    async def finalize(self) -> None:
        """Patch the card to its final done state and mark streaming inactive."""
        if self._card_id is None or not self._state.streaming_thinking_active:
            return
        card = self._build_card(
            self._state.streaming_thinking_text or "Done.",
            done=True,
        )
        await self._patch_card(card)
        logger.info(
            "ThinkingCard: finalized card %s channel=%s",
            self._card_id, self._channel_id,
        )
        self._state.streaming_thinking_text = ""
        self._state.streaming_thinking_active = False

    def reset(self) -> None:
        """Clear all thinking streaming state for this channel."""
        self._state.streaming_thinking_card_id = None
        self._state.streaming_thinking_text = ""
        self._state.streaming_thinking_active = False


async def finalize_active_thinking_card(adapter, channel_id: str) -> None:
    """Finalize the current thinking card using the channel's verbose mode."""
    state = get_verbose_state(channel_id)
    if state.streaming_thinking_card_id is None:
        return

    streamer = ThinkingCardStreamer(
        adapter,
        channel_id,
        placeholder_only=not getattr(state, "_verbose_enabled", False),
    )
    await streamer.finalize()
