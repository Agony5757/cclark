# Module: Card Renderer + Verbose Mode

> Feishu Interactive Card construction and real-time verbose output rendering.

---

## 1. Purpose

The card renderer converts agent output (from `AgentMessage` events) into Feishu Interactive Card JSON payloads. It handles both compact (status-only) and verbose (full output) modes, with efficient in-place card updates for real-time streaming.

## 2. Card Types

### 2.1 Output Card (Agent Messages)

Displays agent text output, tool calls, and code blocks:

```json
{
  "config": {"wide_screen_mode": true},
  "header": {
    "title": {"tag": "plain_text", "content": "🟠 claude-api"},
    "template": "blue"
  },
  "elements": [
    {
      "tag": "markdown",
      "content": "I'll fix the login bug by updating the authentication module."
    },
    {
      "tag": "hr"
    },
    {
      "tag": "markdown",
      "content": "**🔧 Edit** `src/auth/login.py`\n```\n+ def authenticate(user, pwd):\n+     token = generate_jwt(user)\n- def authenticate(token):\n```"
    },
    {
      "tag": "hr"
    },
    {
      "tag": "markdown",
      "content": "**▶ Bash** `pytest tests/auth/`\n```\n4 passed, 0 failed\n```"
    }
  ]
}
```

### 2.2 Status Card

Compact status indicator that updates in-place:

```json
{
  "config": {"wide_screen_mode": true},
  "header": {
    "title": {"tag": "plain_text", "content": "🟠 claude-api"},
    "template": "green"
  },
  "elements": [
    {
      "tag": "markdown",
      "content": "**📝 Working…** Writing tests for auth module"
    }
  ]
}
```

### 2.3 Toolbar Card

Action buttons for window control:

```json
{
  "config": {"wide_screen_mode": true},
  "header": {
    "title": {"tag": "plain_text", "content": "🎛 Toolbar"},
    "template": "purple"
  },
  "elements": [
    {
      "tag": "action",
      "actions": [
        {"tag": "button", "text": {"tag": "plain_text", "content": "📷 Screen"}, "value": {"action": "screenshot"}},
        {"tag": "button", "text": {"tag": "plain_text", "content": "⏹ Ctrl-C"}, "value": {"action": "ctrlc"}},
        {"tag": "button", "text": {"tag": "plain_text", "content": "📺 Live"}, "value": {"action": "live"}}
      ]
    },
    {
      "tag": "action",
      "actions": [
        {"tag": "button", "text": {"tag": "plain_text", "content": "🔀 Mode"}, "value": {"action": "mode"}},
        {"tag": "button", "text": {"tag": "plain_text", "content": "💭 Think"}, "value": {"action": "think"}},
        {"tag": "button", "text": {"tag": "plain_text", "content": "⎋ Esc"}, "value": {"action": "esc"}}
      ]
    }
  ]
}
```

### 2.4 Verbose Streaming Card

Real-time output with in-place updates:

```json
{
  "config": {"wide_screen_mode": true, "update_card": true},
  "header": {
    "title": {"tag": "plain_text", "content": "📡 Verbose Output"},
    "template": "indigo"
  },
  "elements": [
    {
      "tag": "markdown",
      "content": "**Thinking…**\n> The user wants me to fix the login bug. Let me check the auth module first..."
    },
    {
      "tag": "markdown",
      "content": "**🔧 Edit** `src/auth/login.py` (streaming…)\n```\n+ def authenticate(user, pwd):\n+     return generate_jwt(user)\n```"
    },
    {
      "tag": "markdown",
      "content": "**▶ Bash** `pytest tests/auth/ -v`\n```\ntests/auth/test_login.py::test_authenticate PASSED\ntests/auth/test_login.py::test_invalid_password PASSED\n2/2 passed\n```"
    }
  ]
}
```

## 3. Verbose Mode Design

### 3.1 Mode Toggle

The `/verbose` command toggles verbose mode per-channel:

```python
class VerboseState:
    """Track verbose mode per channel."""
    _channels: dict[str, bool] = {}  # channel_id → is_verbose

    def toggle(self, channel_id: str) -> bool:
        current = self._channels.get(channel_id, False)
        self._channels[channel_id] = not current
        return not current

    def is_verbose(self, channel_id: str) -> bool:
        return self._channels.get(channel_id, False)
```

### 3.2 Output Behavior

| Mode | What's shown | Update strategy |
|---|---|---|
| **Compact** (default) | Status line + completion summary | Status card updates + final message |
| **Verbose** | Everything: thinking, tool calls, bash output, code diffs | Streaming card updates every 2-3 seconds |

### 3.3 Streaming Algorithm

```python
class VerboseCardStreamer:
    """Manages real-time verbose output to Feishu cards."""

    def __init__(self, adapter: FeishuAdapter, debounce_ms: int = 2500):
        self._adapter = adapter
        self._debounce_ms = debounce_ms
        self._buffers: dict[str, list[AgentMessage]] = {}    # channel → messages
        self._card_ids: dict[str, str] = {}                   # channel → card_id
        self._timers: dict[str, asyncio.Task] = {}            # channel → debounce timer

    async def on_message(self, event: AgentMessageEvent):
        for channel_id in event.channel_ids:
            if not verbose_state.is_verbose(channel_id):
                continue

            # Buffer new messages
            self._buffers.setdefault(channel_id, []).extend(event.messages)

            # Reset debounce timer
            if channel_id in self._timers:
                self._timers[channel_id].cancel()

            self._timers[channel_id] = asyncio.create_task(
                self._flush_after_delay(channel_id)
            )

    async def _flush_after_delay(self, channel_id: str):
        await asyncio.sleep(self._debounce_ms / 1000)
        await self._flush(channel_id)

    async def _flush(self, channel_id: str):
        messages = self._buffers.pop(channel_id, [])
        if not messages:
            return

        card = card_builder.build_verbose_card(messages)

        if channel_id in self._card_ids:
            # Update existing card
            await self._adapter.update_card(
                channel_id, self._card_ids[channel_id], card
            )
        else:
            # Create new card
            card_id = await self._adapter.send_card(channel_id, card)
            self._card_ids[channel_id] = card_id

    async def finalize(self, channel_id: str):
        """Flush remaining buffer and reset card tracking."""
        if channel_id in self._timers:
            self._timers[channel_id].cancel()
        await self._flush(channel_id)
        self._card_ids.pop(channel_id, None)
```

### 3.4 Debounce Strategy

- **Accumulation window**: 2.5 seconds (configurable)
- Each new message resets the timer
- When agent is done (Stop hook): flush immediately, no debounce
- Maximum buffer size: 50 messages or 8000 chars (force flush)

### 3.5 Card Update Constraints

Feishu card updates have constraints:
- Card cannot change `msg_type` after creation
- Header template (color) can be updated
- Elements can be added/removed
- Buttons can be updated

Strategy: Create a single "verbose output" card per agent turn, update it in-place as output accumulates. When the turn completes (Stop event), finalize the card and start fresh for the next turn.

## 4. Card Builder

```python
class FeishuCardBuilder:
    """Constructs Feishu Interactive Card JSON payloads."""

    def build_output_card(self, content: FormattedContent) -> CardPayload:
        elements = []

        # Main text
        if content.text:
            elements.append({"tag": "markdown", "content": content.text})

        # Code blocks
        for block in content.code_blocks:
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "markdown",
                "content": f"**{block.language}**\n```\n{block.code}\n```"
            })

        # Tool summaries (compact mode)
        for tool in content.tool_summaries:
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "markdown",
                "content": f"**{tool.icon} {tool.name}** `{tool.target}`\n{tool.summary}"
            })

        return CardPayload(
            title=f"🟠 claude-output",
            content="",
            buttons=[],
        )

    def build_verbose_card(self, messages: list[AgentMessage]) -> CardPayload:
        elements = []

        for msg in messages:
            if msg.content_type == "thinking":
                elements.append({
                    "tag": "markdown",
                    "content": f"**💭 Thinking…**\n> {msg.text[:500]}"
                })
            elif msg.content_type == "text":
                elements.append({"tag": "markdown", "content": msg.text})
            elif msg.content_type == "tool_use":
                elements.append({
                    "tag": "markdown",
                    "content": f"**🔧 {msg.tool_name}** (running…)"
                })
            elif msg.content_type == "tool_result":
                elements.append({
                    "tag": "markdown",
                    "content": f"**✅ Result**\n```\n{msg.text[:2000]}\n```"
                })

        return CardPayload(
            title="📡 Verbose Output",
            content="",
            buttons=[],
            color="indigo",
        )

    def build_status_card(self, status: str, label: str, provider: str) -> CardPayload:
        icon = {"working": "📝", "idle": "💤", "done": "✅", "dead": "💀"}.get(status, "❓")
        color = {"working": "blue", "idle": "grey", "done": "green", "dead": "red"}.get(status, "grey")

        return CardPayload(
            title=f"{icon} {provider}",
            content=f"**{icon} {status.title()}** {label}",
            color=color,
        )

    def build_toolbar_card(self, window_id: str, provider: str) -> CardPayload:
        # Build button grid based on provider capabilities
        ...

    def build_prompt_card(self, prompt: InteractivePrompt) -> CardPayload:
        elements = [{"tag": "markdown", "content": prompt.description}]

        actions = []
        if prompt.prompt_type == "ask_user":
            for opt in prompt.options:
                actions.append({
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": opt},
                    "value": {"action": "choice", "choice": opt},
                    "type": "default",
                })
        elif prompt.prompt_type == "permission":
            actions = [
                {"tag": "button", "text": {"tag": "plain_text", "content": "✅ Allow"},
                 "value": {"action": "allow"}, "type": "primary"},
                {"tag": "button", "text": {"tag": "plain_text", "content": "❌ Deny"},
                 "value": {"action": "deny"}, "type": "danger"},
            ]

        return CardPayload(
            title=f"🤔 {prompt.title}",
            content=prompt.description,
            buttons=[actions],
            color="orange",
        )
```

## 5. Content Formatting Rules

### 5.1 Compact Mode

| Content Type | Display |
|---|---|
| Agent text | Full text (up to 8000 chars) |
| Thinking | Hidden |
| Tool use | Icon + tool name + target file |
| Tool result | Hidden (unless error) |
| Bash output | Hidden (unless error) |
| Status change | Status card (updated in-place) |

### 5.2 Verbose Mode

| Content Type | Display |
|---|---|
| Agent text | Full text |
| Thinking | Collapsed block (max 500 chars) |
| Tool use | Full tool name + arguments |
| Tool result | Full output (up to 2000 chars per block) |
| Bash output | Full output with exit code |
| Status change | Inline in verbose card |

## 6. Performance Considerations

| Metric | Target | Strategy |
|---|---|---|
| Card update latency | < 500ms | Debounce 2.5s, async updates |
| Max cards per minute | < 40 (Feishu limit 5/sec) | Buffer + batch |
| Card content size | < 30KB JSON | Truncate code blocks at 2000 chars |
| Concurrent cards | < 10 per channel | One streaming card per agent turn |
