from __future__ import annotations

from types import SimpleNamespace

import pytest

from cclark.event_parsers import FeishuMessageEvent
from cclark.handlers import message, session_creation


class _FakeAdapter:
    def __init__(self) -> None:
        self.sent_text: list[tuple[str, str]] = []

    async def send_text(self, channel_id: str, text: str) -> str:
        self.sent_text.append((channel_id, text))
        return "om_test"


class _FakeGateway:
    def __init__(self) -> None:
        self.window_id: str | None = None
        self.sent_to_window: list[tuple[str, str]] = []
        self.sent_input: list[tuple[str, str, bool, bool, bool]] = []
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
