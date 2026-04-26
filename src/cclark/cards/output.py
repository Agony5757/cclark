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
    """Build a Feishu card for an agent output message."""
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
    """Build a Feishu card with a syntax-highlighted code block."""
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
