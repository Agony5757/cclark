"""Output card builder — renders agent output messages as Feishu cards."""

from __future__ import annotations

import json
from typing import Any

from cclark.cards.builder import FeishuCardBuilder


def build_output_card(
    title: str,
    body: str,
    provider: str = "",
    color: str = "blue",
    actions: list[dict[str, str]] | None = None,
) -> str:
    """Build a Feishu card JSON string for a general agent output message.

    Args:
        title: Card header title.
        body: Markdown body text.
        provider: Optional provider name shown as a field.
        color: Header color template string.
        actions: Optional list of button actions.
    Returns:
        Serialized JSON string for send_interactive_card / patch_message.
    """
    from unified_icc.adapter import CardPayload
    card = CardPayload(
        title=title,
        body=body,
        color=color,
        actions=actions or [],
    )
    if provider:
        card.fields = {"provider": provider}
    return FeishuCardBuilder.build_card(card)


def build_code_output_card(
    title: str,
    code: str,
    language: str = "",
    provider: str = "",  # noqa: ARG001
    max_chars: int = 4000,
) -> str:
    """Build a Feishu card JSON string with a fenced code block.

    Args:
        title: Card header title.
        code: Raw code text (wrapped in triple backticks).
        language: Language hint for the fence (e.g. "python").
        provider: Unused, kept for API compatibility.
        max_chars: Truncation threshold (default 4000).
    Returns:
        Serialized JSON string.
    """
    if len(code) > max_chars:
        code = code[:max_chars] + f"\n... (output truncated, {len(code) - max_chars} chars hidden)"

    body_lines = []
    if language:
        body_lines.append(f"```{language}")
    else:
        body_lines.append("```")
    body_lines.append(code)
    body_lines.append("```")

    card: dict[str, Any] = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "wathet",
        },
        "elements": [
            {"tag": "markdown", "content": "\n".join(body_lines)},
        ],
    }
    return json.dumps(card)
