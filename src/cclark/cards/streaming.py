"""Verbose card streamer — debounced, turn-aware card updates.

Buffers incoming messages in 2.5-second windows and flushes them as a single
Feishu card update. One streaming card per channel per agent turn.
"""

from __future__ import annotations

import json
import time

import structlog

from cclark.config import config
from cclark.state import get_verbose_state
from cclark.feishu_client import FeishuClient

logger = structlog.get_logger()

_FLUSH_INTERVAL_MS = 2500  # flush every 2.5 seconds
_MAX_MESSAGES_PER_FLUSH = 50
_MAX_CHARS_PER_FLUSH = 8000
_MAX_CARD_SIZE = 30 * 1024


class VerboseCardStreamer:
    """Debounced card streamer for agent output in a Feishu channel."""

    def __init__(
        self,
        client: FeishuClient,
        channel_id: str,
        user_id: str,
        provider: str = "",
    ) -> None:
        self._client = client
        self._channel_id = channel_id
        self._user_id = user_id
        self._provider = provider
        self._state = get_verbose_state(channel_id)
        self._turn_index = -1
        self._pending: list[str] = []
        self._pending_chars = 0

    @property
    def channel_id(self) -> str:
        return self._channel_id

    @property
    def turn_index(self) -> int:
        return self._turn_index

    async def set_turn_index(self, index: int) -> None:
        """Signal that the agent turn has advanced."""
        if index != self._turn_index:
            await self._flush()
            self._turn_index = index

    async def push(self, text: str, turn_index: int) -> None:
        """Add a text segment to the pending buffer."""
        if turn_index != self._turn_index:
            await self._flush()
            self._turn_index = turn_index

        self._pending.append(text)
        self._pending_chars += len(text)

        if len(self._pending) >= _MAX_MESSAGES_PER_FLUSH or self._pending_chars >= _MAX_CHARS_PER_FLUSH:
            await self._flush()

        now_ms = time.monotonic() * 1000
        if self._pending and (now_ms - self._state.last_flush_ms) >= _FLUSH_INTERVAL_MS:
            await self._flush()

    async def _flush(self) -> None:
        """Send or patch the card with accumulated text."""
        if not self._pending:
            return

        text = "".join(self._pending)
        self._pending.clear()
        self._pending_chars = 0
        self._state.last_flush_ms = time.monotonic() * 1000

        card = self._build_card(text)

        try:
            if self._state.streaming_card_id:
                await self._client.patch_message(
                    self._state.streaming_card_id,
                    card,
                )
            else:
                chat_id, _thread_id = config.split_channel_id(self._channel_id)
                msg_id = await self._client.send_interactive_card(
                    chat_id,
                    card,
                )
                self._state.streaming_card_id = msg_id
        except Exception:
            logger.exception("Failed to flush streaming card channel=%s", self._channel_id)

    async def flush(self) -> None:
        await self._flush()

    def reset(self) -> None:
        """Clear streaming state (on unbind or session end)."""
        self._pending.clear()
        self._pending_chars = 0
        self._state.streaming_card_id = None
        self._turn_index = -1

    def _build_card(self, text: str) -> str:
        if len(text) > _MAX_CARD_SIZE - 2000:
            text = text[: _MAX_CARD_SIZE - 2000] + "\n... (output truncated)"
        # Basic markdown-lite rendering
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return json.dumps({
            "config": {"wide_screen_mode": True, "update_multi": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"🤖 {self._provider}" if self._provider else "🤖 Agent",
                },
                "template": "blue",
            },
            "elements": [
                {"tag": "markdown", "content": f"<pre>{escaped}</pre>"},
            ],
        })
