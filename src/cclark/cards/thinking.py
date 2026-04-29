"""Thinking 卡片流 — 增量更新飞书交互卡片以显示 thinking 进度。

生命周期：
  is_complete=False + 无卡 → 创建新卡片
  is_complete=False + 有卡 → patch 更新内容
  is_complete=True         → patch 终态（去掉 spinner）
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
    """管理单个 channel 的 thinking 卡片生命周期。

    Args:
        adapter: FeishuAdapter 实例
        channel_id: 飞书 channel ID
        placeholder_only: 为 True 时卡片只显示占位符（thinking... / thinking...OK!），
                          丢弃实际 thinking 内容
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
        """构建 Feishu 交互卡片 JSON。

        - placeholder_only=True: 始终只显示占位符（🤔 Thinking... / 🤔 Thinking...OK!）
        - done=False: 追加 ⏳ Generating... 提示
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
        """推送一段 thinking 文本。"""
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
            self.reset()

    async def finalize(self) -> None:
        """Mark the current thinking card complete and stop updating it."""
        if self._card_id is None:
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
        self.reset()

    def reset(self) -> None:
        self._state.streaming_thinking_card_id = None
        self._state.streaming_thinking_text = ""
