from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from cclark.cards.thinking import ThinkingCardStreamer
from cclark.event_parsers import FeishuMessageEvent
from cclark.handlers import message, session_creation
from cclark.state import get_verbose_state, reset_channel_state


class _FakeClient:
    def __init__(self) -> None:
        self.sent_cards: list[tuple[str, str]] = []
        self.patched_cards: list[tuple[str, str]] = []

    async def send_interactive_card(self, chat_id: str, card_json: str) -> str:
        self.sent_cards.append((chat_id, card_json))
        return f"om_card_{len(self.sent_cards)}"

    async def patch_message(self, message_id: str, card_json: str) -> None:
        self.patched_cards.append((message_id, card_json))


class _FakeAdapter:
    def __init__(self) -> None:
        self._client = _FakeClient()
        self.sent_text: list[tuple[str, str]] = []

    async def send_interactive_card(self, channel_id: str, card_json: str) -> str:
        return await self._client.send_interactive_card(channel_id, card_json)

    async def send_text(self, channel_id: str, text: str) -> str:
        self.sent_text.append((channel_id, text))
        return "om_test"


class _FakeGateway:
    def __init__(self) -> None:
        self.window_id: str | None = None
        self.sent_to_window: list[tuple[str, str]] = []
        self.sent_input: list[tuple[str, str, bool, bool, bool]] = []
        self.keys: list[tuple[str, str]] = []
        self.channel_router = SimpleNamespace(resolve_window=lambda _channel_id: self.window_id)

    async def kill_channel_windows(self, _channel_id: str) -> list[str]:
        return []

    async def list_orphaned_agent_windows(self) -> list[object]:
        return []

    async def send_to_window(self, window_id: str, text: str) -> None:
        self.sent_to_window.append((window_id, text))

    async def send_input_to_window(
        self,
        window_id: str,
        text: str,
        *,
        enter: bool = True,
        literal: bool = True,
        raw: bool = False,
    ) -> None:
        self.sent_input.append((window_id, text, enter, literal, raw))

    async def send_key(self, window_id: str, key: str) -> None:
        self.keys.append((window_id, key))


def _event(text: str) -> FeishuMessageEvent:
    return FeishuMessageEvent(
        chat_id="oc_test",
        thread_id="",
        user_id="ou_testuser1",
        text=text,
        message_id="om_test",
        msg_type="text",
    )


@pytest.fixture
def fake_runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[_FakeAdapter, _FakeGateway]:
    adapter = _FakeAdapter()
    gateway = _FakeGateway()
    message.set_handlers(gateway, adapter)
    session_creation.clear_session_creation("ou_testuser1")
    yield adapter, gateway
    session_creation.clear_session_creation("ou_testuser1")
    message.set_handlers(None, None)


@pytest.mark.asyncio
async def test_unbound_plain_message_shows_help_without_starting_wizard(
    fake_runtime: tuple[_FakeAdapter, _FakeGateway],
) -> None:
    adapter, _gateway = fake_runtime
    await message.handle_message(_event("hello"))

    assert len(adapter.sent_text) == 1
    assert "No active session is bound to this chat." in adapter.sent_text[0][1]
    assert "#new" in adapter.sent_text[0][1]
    assert session_creation.get_session_state("ou_testuser1") is None


@pytest.mark.asyncio
async def test_help_is_global_during_session_creation(
    fake_runtime: tuple[_FakeAdapter, _FakeGateway],
) -> None:
    adapter, _gateway = fake_runtime
    await message.handle_message(_event("#new"))
    assert session_creation.get_session_state("ou_testuser1") is not None

    await message.handle_message(_event("#help"))

    assert "cclark commands:" in adapter.sent_text[-1][1]
    assert "#mkdir <name>" in adapter.sent_text[-1][1]
    assert session_creation.get_session_state("ou_testuser1") is not None


@pytest.mark.asyncio
async def test_mkdir_during_browse_creates_and_enters_directory(
    tmp_path, fake_runtime: tuple[_FakeAdapter, _FakeGateway]
) -> None:
    adapter, _gateway = fake_runtime
    await message.handle_message(_event("#new"))
    await message.handle_message(_event(f"#select {tmp_path}"))

    await message.handle_message(_event("#mkdir work"))

    created = tmp_path / "work"
    state = session_creation.get_session_state("ou_testuser1")
    assert created.is_dir()
    assert state is not None
    assert state["path"] == str(created.resolve())
    assert "Created directory:" in adapter.sent_text[-2][1]
    assert f"Current directory: {created.resolve()}" in adapter.sent_text[-1][1]


@pytest.mark.asyncio
async def test_mkdir_rejects_paths(
    tmp_path, fake_runtime: tuple[_FakeAdapter, _FakeGateway]
) -> None:
    adapter, _gateway = fake_runtime
    await message.handle_message(_event("#new"))
    await message.handle_message(_event(f"#select {tmp_path}"))

    await message.handle_message(_event("#mkdir nested/path"))

    assert not (tmp_path / "nested").exists()
    assert "Use a single directory name" in adapter.sent_text[-1][1]


@pytest.mark.asyncio
async def test_plan_option_three_waits_for_feedback(
    fake_runtime: tuple[_FakeAdapter, _FakeGateway],
) -> None:
    adapter, gateway = fake_runtime
    gateway.window_id = "@42"
    message.set_terminal_prompt_state(
        "feishu:oc_test",
        "Claude has written up a plan and is ready to execute. Would you like to proceed?\n"
        "1. Yes, and use auto mode\n"
        "2. Yes, manually approve edits\n"
        "3. Tell Claude what to change",
    )

    await message.handle_message(_event("3"))

    assert gateway.sent_input == [("@42", "3", False, True, True)]
    assert gateway.sent_to_window == []
    assert "feedback text next" in adapter.sent_text[-1][1]

    await message.handle_message(_event("一个 README 里面包括测试的结论"))

    assert gateway.sent_to_window == [("@42", "一个 README 里面包括测试的结论")]


@pytest.mark.asyncio
async def test_new_turn_clears_thinking_card(
    fake_runtime: tuple[_FakeAdapter, _FakeGateway],
) -> None:
    adapter, gateway = fake_runtime
    gateway.window_id = "@42"
    channel_id = "feishu:oc_test"
    reset_channel_state(channel_id)
    get_verbose_state(channel_id)._verbose_enabled = False

    streamer = ThinkingCardStreamer(adapter, channel_id, placeholder_only=True)
    await streamer.push_thinking("private reasoning", is_complete=False)

    assert len(adapter._client.sent_cards) == 1
    old_card_id = get_verbose_state(channel_id).streaming_thinking_card_id
    assert old_card_id == "om_card_1"

    await message.handle_message(_event("继续"))

    assert gateway.sent_to_window == [("@42", "继续")]
    assert get_verbose_state(channel_id).streaming_thinking_card_id is None
    assert adapter._client.patched_cards[0][0] == old_card_id
    finalized_old_card = json.loads(adapter._client.patched_cards[0][1])
    assert finalized_old_card["elements"][0]["content"] == "🤔 Thinking...OK!"

    next_streamer = ThinkingCardStreamer(adapter, channel_id, placeholder_only=True)
    await next_streamer.push_thinking("next turn", is_complete=False)

    assert len(adapter._client.sent_cards) == 2
    assert get_verbose_state(channel_id).streaming_thinking_card_id == "om_card_2"


@pytest.mark.asyncio
async def test_multiple_turns_one_thinking_card_visible(
    fake_runtime: tuple[_FakeAdapter, _FakeGateway],
) -> None:
    adapter, gateway = fake_runtime
    gateway.window_id = "@42"
    channel_id = "feishu:oc_test"
    reset_channel_state(channel_id)
    get_verbose_state(channel_id)._verbose_enabled = False

    streamer = ThinkingCardStreamer(adapter, channel_id, placeholder_only=True)
    await streamer.push_thinking("turn 0", is_complete=False)
    await message.handle_message(_event("turn 1"))

    await streamer.push_thinking("turn 1", is_complete=False)
    await message.handle_message(_event("turn 2"))

    await streamer.push_thinking("turn 2", is_complete=False)

    state = get_verbose_state(channel_id)
    assert len(adapter._client.sent_cards) == 3
    assert [card_id for card_id, _ in adapter._client.patched_cards] == [
        "om_card_1",
        "om_card_2",
    ]
    assert state.streaming_thinking_card_id == "om_card_3"


def test_status_panel_is_not_terminal_prompt() -> None:
    panel = """
❯ /status

────────────────────────────────────────────────────────────────────────────────
   Status   Config   Usage   Stats

  Version:             2.1.122
  Session ID:          68a7436c-be89-4b5c-8b4e-2b9b2ea6cfe3
  cwd:                 /home/agony/projects/larkcc-test/test-20260429-0954
  Model:               Default (claude-sonnet-4-6)
  Setting sources:     User settings
  Esc to cancel
"""

    assert message.classify_terminal_prompt(panel) is None


def test_permission_panel_is_terminal_prompt() -> None:
    panel = """
 Do you want to create README.md?
 ❯ 1. Yes
   2. Yes, allow all edits in this session
   3. No

 Esc to cancel · Tab to amend
"""

    assert message.classify_terminal_prompt(panel) == {
        "type": "permission",
        "phase": "choice",
        "options": "1,2,3",
        "selected": "1",
    }


def test_selection_prompt_extracts_all_numbered_options() -> None:
    panel = """
Select model
  Switch between Claude models.

  ❯ 1. Default (recommended) ✔  Use the default model
    2. claude-sonnet-4-6        Custom Sonnet model
    3. claude-opus-4-7          Custom Opus model
    4. claude-haiku-4-5         Custom Haiku model

  Enter to confirm · Esc to exit
"""

    state = message.classify_terminal_prompt(panel)

    assert state == {
        "type": "selection",
        "phase": "choice",
        "options": "1,2,3,4",
        "selected": "1",
    }
    assert message.extract_numbered_prompt_options(panel) == ["1", "2", "3", "4"]
    assert message.extract_selected_prompt_option(panel) == "1"
    assert message.build_terminal_prompt_reply_guidance(panel, state) == (
        "Reply with one of the listed numbers: `1`, `2`, `3`, `4`."
    )


@pytest.mark.asyncio
async def test_selection_prompt_accepts_any_visible_number(
    fake_runtime: tuple[_FakeAdapter, _FakeGateway],
) -> None:
    _adapter, gateway = fake_runtime
    gateway.window_id = "@42"
    message.set_terminal_prompt_state(
        "feishu:oc_test",
        "Select model\n"
        "  ❯ 1. Default\n"
        "    2. Sonnet\n"
        "    3. Opus\n"
        "    4. Haiku\n"
        "Enter to confirm · Esc to exit",
    )

    await message.handle_message(_event("4"))

    assert gateway.sent_to_window == []
    assert gateway.keys == [
        ("@42", "Down"),
        ("@42", "Down"),
        ("@42", "Down"),
        ("@42", "Enter"),
    ]


@pytest.mark.asyncio
async def test_selection_prompt_rejects_number_not_visible(
    fake_runtime: tuple[_FakeAdapter, _FakeGateway],
) -> None:
    adapter, gateway = fake_runtime
    gateway.window_id = "@42"
    message.set_terminal_prompt_state(
        "feishu:oc_test",
        "Select model\n"
        "  ❯ 1. Default\n"
        "    2. Sonnet\n"
        "Enter to confirm · Esc to exit",
    )

    await message.handle_message(_event("4"))

    assert gateway.sent_to_window == []
    assert "`4` is not a visible option" in adapter.sent_text[-1][1]


@pytest.mark.asyncio
async def test_footer_selection_prompt_uses_navigation(
    fake_runtime: tuple[_FakeAdapter, _FakeGateway],
) -> None:
    _adapter, gateway = fake_runtime
    gateway.window_id = "@42"
    message.set_terminal_prompt_state(
        "feishu:oc_test",
        "☐ 项目方向\n\n"
        "❯ 1. 命令行计算器\n"
        "  2. 前端测试套件\n"
        "  3. Type something.\n"
        "─────\n"
        "  4. Chat about this\n"
        "  5. Skip interview and plan immediately\n\n"
        "Enter to select · ↑/↓ to navigate · Esc to cancel",
    )

    await message.handle_message(_event("5"))

    assert gateway.sent_to_window == []
    assert gateway.keys == [
        ("@42", "Down"),
        ("@42", "Down"),
        ("@42", "Down"),
        ("@42", "Down"),
        ("@42", "Enter"),
    ]


def test_classify_terminal_prompt_generic_plan_markers() -> None:
    """Plan detection should work with generic markers (no 'Claude' prefix)."""
    panel = """
The agent has written up a plan:

1. Create README.md
2. Add tests

Would you like to proceed?
  1. Yes
  2. No
  3. Tell the agent what to change
"""
    state = message.classify_terminal_prompt(panel)
    assert state is not None
    assert state["type"] == "plan_decision"


def test_classify_terminal_prompt_codex_permission() -> None:
    """Codex edit confirmation prompts should be classified as permission."""
    panel = """
Do you want to make this edit to src/main.py?
  - old line
  + new line
  1. Yes
  2. No

Esc to cancel
"""
    state = message.classify_terminal_prompt(panel)
    assert state is not None
    assert state["type"] == "permission"


def test_build_terminal_prompt_reply_guidance_uses_provider_name() -> None:
    """Reply guidance should include the provider name."""
    from cclark.handlers.message import build_terminal_prompt_reply_guidance

    state = {"type": "permission", "phase": "choice"}
    guidance = build_terminal_prompt_reply_guidance("no options here", state, provider_name="codex")
    assert "Codex" in guidance
    assert "Claude" not in guidance
