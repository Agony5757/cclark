"""Feishu adapter — implements FrontendAdapter for the unified-icc gateway."""

from __future__ import annotations

import json
import structlog
from pathlib import Path


from cclark.cards.builder import FeishuCardBuilder
from cclark.config import config
from cclark.feishu_client import FeishuClient
from unified_icc.adapter import CardPayload, InteractivePrompt

logger = structlog.get_logger()

_MAX_TEXT_CHUNK = 4000


class FeishuAdapter:
    """Feishu implementation of FrontendAdapter — sends messages via FeishuClient."""

    def __init__(self, client: FeishuClient) -> None:
        self._client = client

    # ── FrontendAdapter implementation ───────────────────────────────────────

    async def send_text(self, channel_id: str, text: str) -> str:
        """Send plain text. Chunks at 4000 chars for Feishu limits."""
        chat_id, thread_id = config.split_channel_id(channel_id)
        # Send without thread_id for non-threaded, or reply in thread
        if thread_id:
            return await self._send_text_in_thread(chat_id, thread_id, text)
        return await self._send_text_chunked(chat_id, text)

    async def send_card(self, channel_id: str, card: CardPayload) -> str:
        """Send a rich card built from CardPayload."""
        chat_id, thread_id = config.split_channel_id(channel_id)
        card_json = FeishuCardBuilder.build_card(card)
        return await self._send_card(chat_id, thread_id, card_json)

    async def update_card(
        self, channel_id: str, card_id: str, card: CardPayload  # noqa: ARG002
    ) -> None:
        """Patch an existing card."""
        card_json = FeishuCardBuilder.build_card(card)
        await self._client.patch_message(card_id, card_json)

    async def send_image(
        self, channel_id: str, image_bytes: bytes, caption: str = ""  # noqa: ARG002
    ) -> str:
        """Upload image and send as Feishu image message."""
        chat_id, thread_id = config.split_channel_id(channel_id)
        image_key = await self._client.upload_image(image_bytes)
        content = json.dumps({"image_key": image_key})
        return await self._send_message(chat_id, thread_id, "image", content)

    async def send_file(
        self, channel_id: str, file_path: str, caption: str = ""  # noqa: ARG002
    ) -> str:
        """Read a file, upload it, and send as Feishu file message."""
        chat_id, thread_id = config.split_channel_id(channel_id)
        path = Path(file_path)
        file_bytes = path.read_bytes()
        file_key = await self._client.upload_file(
            file_bytes, path.name, file_type="stream_file"
        )
        content = json.dumps({"file_key": file_key, "file_name": path.name})
        return await self._send_message(chat_id, thread_id, "file", content)

    async def show_prompt(
        self, channel_id: str, prompt: InteractivePrompt
    ) -> str:
        """Show an interactive prompt (permission / question)."""
        chat_id, thread_id = config.split_channel_id(channel_id)
        card_json = FeishuCardBuilder.build_prompt_card(prompt)
        return await self._send_card(chat_id, thread_id, card_json)

    # ── Internal helpers ─────────────────────────────────────────────────────

    async def _send_text_chunked(self, chat_id: str, text: str) -> str:
        """Send text in chunks, returning the last message_id."""
        last_id = ""
        for i in range(0, len(text), _MAX_TEXT_CHUNK):
            chunk = text[i : i + _MAX_TEXT_CHUNK]
            last_id = await self._client.send_text(chat_id, chunk)
        return last_id

    async def _send_text_in_thread(
        self, chat_id: str, thread_id: str, text: str
    ) -> str:
        """Send text in a thread using reply_in_thread."""
        last_id = ""
        for i in range(0, len(text), _MAX_TEXT_CHUNK):
            chunk = text[i : i + _MAX_TEXT_CHUNK]
            content = json.dumps({"text": chunk})
            last_id = await self._client.reply_in_thread(
                chat_id, "text", content, thread_id
            )
        return last_id

    async def _send_card(
        self, chat_id: str, thread_id: str, card_json: str
    ) -> str:
        """Send an interactive card, optionally in a thread."""
        if thread_id:
            return await self._client.reply_in_thread(
                chat_id, "interactive", card_json, thread_id
            )
        return await self._client.send_interactive_card(chat_id, card_json)

    async def send_interactive_card(self, channel_id: str, card_json: str) -> str:
        """Send a pre-built interactive card JSON string to a channel.

        Args:
            channel_id: Unified channel ID (feishu:chat_id[:thread_id]).
            card_json: Serialized Feishu card JSON string.
        Returns:
            The sent message_id.
        """
        chat_id, thread_id = config.split_channel_id(channel_id)
        return await self._send_card(chat_id, thread_id, card_json)

    async def _send_message(
        self, chat_id: str, thread_id: str, msg_type: str, content: str
    ) -> str:
        """Low-level send with optional thread reply."""
        if thread_id:
            return await self._client.reply_in_thread(
                chat_id, msg_type, content, thread_id
            )
        return await self._client.send_message(chat_id, msg_type, content)
