"""Feishu card builder — converts CardPayload to Feishu card JSON.

Feishu card schema: https://open.feishu.cn/document/server-docs/im-v1/message-content-description/create_json
"""

from __future__ import annotations

import json
import re
from typing import Any

from unified_icc.adapter import CardPayload, InteractivePrompt


# Feishu card header color mapping
_COLOR_MAP: dict[str, str] = {
    "blue": "blue",
    "wathet": "wathet",
    "turquoise": "turquoise",
    "green": "green",
    "yellow": "yellow",
    "orange": "orange",
    "carmine": "carmine",
    "red": "red",
    "violet": "violet",
    "purple": "purple",
    "indigo": "indigo",
    "gray": "gray",
    "grey": "grey",
}

_MAX_CARD_SIZE = 30 * 1024  # Feishu card limit ~30 KB
_MAX_CODE_BLOCK = 2000  # Truncate code blocks above this


class FeishuCardBuilder:
    """Static utilities for building Feishu interactive card JSON from gateway payload types."""

    @staticmethod
    def _header_color(color: str) -> str:
        return _COLOR_MAP.get(color.lower(), "blue")

    @staticmethod
    def _md(text: str) -> str:
        """Basic markdown-to-Feishu markdown-lite converter.

        Preserves fenced code blocks (```...```) and converts inline formatting
        (bold, inline code) in the remaining text.
        """
        # 1. Extract fenced code blocks before any escaping.
        code_blocks: list[str] = []
        code_pat = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)

        def _stash_code(m: re.Match[str]) -> str:
            lang = m.group(1)
            body = m.group(2).rstrip("\n")
            # Escape HTML inside code blocks
            body = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            idx = len(code_blocks)
            if lang:
                code_blocks.append(f'<pre lang="{lang}">{body}</pre>')
            else:
                code_blocks.append(f"<pre>{body}</pre>")
            return f"\x00CODEBLOCK_{idx}\x00"

        text = code_pat.sub(_stash_code, text)

        # 2. Escape HTML in non-code text.
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # 3. Bold (**text**)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)

        # 4. Inline code (`text`) — skip escaped NUL placeholders.
        parts = text.split("`")
        out: list[str] = []
        for i, part in enumerate(parts):
            if i % 2 == 1:
                out.append(f"<code>{part}</code>")
            else:
                out.append(part)
        text = "".join(out)

        # 5. Restore code blocks.
        for idx, block in enumerate(code_blocks):
            text = text.replace(f"\x00CODEBLOCK_{idx}\x00", block)

        return text

    @staticmethod
    def _truncate_code(text: str) -> str:
        """Truncate code blocks exceeding MAX_CODE_BLOCK characters."""
        if len(text) <= _MAX_CODE_BLOCK:
            return text
        return text[:_MAX_CODE_BLOCK] + f"\n... (truncated {len(text) - _MAX_CODE_BLOCK} chars)"

    @staticmethod
    def build_card(card: CardPayload) -> str:
        """Build a Feishu card JSON string from a CardPayload."""
        elements: list[dict[str, Any]] = []

        # Body markdown
        if card.body:
            body_md = FeishuCardBuilder._truncate_code(card.body)
            elements.append({
                "tag": "markdown",
                "content": FeishuCardBuilder._md(body_md),
            })

        # Fields (key-value pairs as a table)
        if card.fields:
            field_lines = []
            for key, val in card.fields.items():
                field_lines.append(
                    f"<strong>{FeishuCardBuilder._md(key)}</strong>: "
                    f"{FeishuCardBuilder._md(val)}"
                )
            elements.append({
                "tag": "markdown",
                "content": "<br>".join(field_lines),
            })

        # Actions (buttons)
        if card.actions:
            buttons: list[dict[str, Any]] = []
            for action in card.actions:
                btn: dict[str, Any] = {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": action.get("label", "Button")},
                }
                if action.get("action"):
                    btn["action_type"] = "interactive"
                    btn["value"] = {"action": action["action"]}
                else:
                    btn["action_type"] = "default"
                buttons.append(btn)

            if buttons:
                elements.append({"tag": "action", "children": buttons})

        # Assemble card
        header: dict[str, Any] = {
            "title": {"tag": "plain_text", "content": card.title or "Message"},
            "template": FeishuCardBuilder._header_color(card.color),
        }

        card_json: dict[str, Any] = {
            "config": {"wide_screen_mode": True},
            "header": header,
            "elements": elements,
        }
        return json.dumps(card_json)

    @staticmethod
    def build_prompt_card(prompt: InteractivePrompt) -> str:
        """Build a prompt/permission card."""
        elements: list[dict[str, Any]] = [
            {
                "tag": "markdown",
                "content": FeishuCardBuilder._md(prompt.title),
            }
        ]

        buttons: list[dict[str, Any]] = []
        for option in prompt.options:
            value = json.dumps({"type": prompt.prompt_type, "choice": option.get("value", "")})
            buttons.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": option.get("label", "Option")},
                "action_type": "interactive",
                "value": {"action": value},
            })

        if prompt.cancel_text:
            buttons.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": prompt.cancel_text},
                "action_type": "interactive",
                "value": {"action": "cancel"},
            })

        if buttons:
            elements.append({"tag": "action", "children": buttons})

        return json.dumps({
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "Prompt"},
                "template": "wathet",
            },
            "elements": elements,
        })
