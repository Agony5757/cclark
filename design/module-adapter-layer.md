# Module: Adapter Layer

> The frontend abstraction that decouples messaging platforms from the unifiedcc gateway.

---

## 1. Purpose

The adapter layer defines the contract between any messaging frontend (Feishu, Telegram, Discord, etc.) and the unifiedcc gateway. Each platform implements a `FrontendAdapter` that translates platform-specific concepts to gateway API calls and renders gateway events to platform-native UI.

## 2. Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Frontend Adapter                    │
│                                                      │
│  ┌─────────────────┐    ┌──────────────────────┐    │
│  │ Inbound Handler │    │ Outbound Renderer     │    │
│  │                 │    │                       │    │
│  │ platform msg    │    │ AgentMessageEvent     │    │
│  │     ↓           │    │     ↓                 │    │
│  │ parse & route   │    │ format for platform   │    │
│  │     ↓           │    │     ↓                 │    │
│  │ gateway API     │    │ platform send API     │    │
│  └─────────────────┘    └──────────────────────┘    │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │ UI Components                                 │    │
│  │ - Toolbar buttons                             │    │
│  │ - Interactive prompts (AskUser, Permission)   │    │
│  │ - Status indicators                           │    │
│  │ - Directory browser                           │    │
│  │ - File sender                                 │    │
│  └──────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
            ↕
┌─────────────────────────────────────────────────────┐
│              UnifiedCC Gateway API                    │
└─────────────────────────────────────────────────────┘
```

## 3. FrontendAdapter Protocol

```python
from typing import Protocol, Awaitable, Callable
from dataclasses import dataclass

@dataclass
class Button:
    """Platform-agnostic button definition."""
    id: str           # Callback identifier
    label: str        # Display text
    emoji: str = ""   # Optional emoji prefix
    style: str = "default"  # "default", "primary", "danger"

@dataclass
class CardPayload:
    """Platform-agnostic card definition."""
    title: str = ""
    content: str = ""
    buttons: list[list[Button]] = []  # Rows of buttons
    footer: str = ""
    color: str = ""  # Accent color

@dataclass
class InteractivePrompt:
    """A prompt requiring user interaction."""
    prompt_type: str   # "ask_user", "permission", "plan_mode", "approval"
    title: str
    description: str
    options: list[str] = []     # For ask_user
    detail: str = ""            # For permission (command/file details)
    plan_text: str = ""         # For plan_mode

class FrontendAdapter(Protocol):
    """Contract that each messaging platform must implement."""

    # ── Outbound: Gateway → Platform ──────────────

    async def send_text(self, channel_id: str, text: str) -> str:
        """Send plain text. Returns platform message_id for updates."""
        ...

    async def send_card(self, channel_id: str, card: CardPayload) -> str:
        """Send interactive card. Returns card_id for updates."""
        ...

    async def update_card(self, channel_id: str, card_id: str, card: CardPayload) -> None:
        """Update an existing card in-place."""
        ...

    async def send_image(self, channel_id: str, image_bytes: bytes, caption: str = "") -> str:
        """Send an image with optional caption."""
        ...

    async def send_file(self, channel_id: str, file_path: str, caption: str = "") -> str:
        """Upload and send a file."""
        ...

    async def show_prompt(self, channel_id: str, prompt: InteractivePrompt) -> str:
        """Render an interactive prompt requiring user action."""
        ...

    # ── Inbound: Platform → Gateway ───────────────
    # These are called by the platform SDK's event handlers

    def register_message_handler(
        self, handler: Callable[[str, str, str], Awaitable[None]]
    ) -> None:
        """Register handler for (channel_id, user_id, text) messages."""
        ...

    def register_callback_handler(
        self, handler: Callable[[str, str, str, dict], Awaitable[None]]
    ) -> None:
        """Register handler for (channel_id, user_id, action_id, data) callbacks."""
        ...
```

## 4. UI Component Adapters

### 4.1 Toolbar

Each platform renders the toolbar differently:

**Telegram**: Inline keyboard with emoji buttons
**Feishu**: Interactive card with button components

```python
class ToolbarAdapter(Protocol):
    async def show_toolbar(
        self, channel_id: str, window_id: str, provider: str
    ) -> str: ...

    async def update_toolbar_button(
        self, channel_id: str, card_id: str, button_id: str, label: str
    ) -> None: ...
```

### 4.2 Directory Browser

```python
class DirectoryBrowserAdapter(Protocol):
    async def show_directories(
        self, channel_id: str, path: str, entries: list[str], parent: str | None
    ) -> str: ...

    async def show_provider_picker(
        self, channel_id: str, providers: list[str], work_dir: str
    ) -> str: ...

    async def show_mode_picker(
        self, channel_id: str, provider: str, work_dir: str
    ) -> str: ...
```

### 4.3 Status Display

```python
class StatusAdapter(Protocol):
    async def show_status(
        self, channel_id: str, window_id: str, status: str, label: str
    ) -> str: ...

    async def update_status(
        self, channel_id: str, message_id: str, status: str, label: str
    ) -> None: ...

    async def clear_status(self, channel_id: str, message_id: str) -> None: ...
```

## 5. Message Formatting Pipeline

```
AgentMessage (from gateway)
    ↓
ContentFormatter.format(message, verbose=False)
    ↓
FormattedContent (platform-agnostic)
    ↓
FrontendAdapter.send_card() or send_text()
    ↓
Platform-native message
```

### 5.1 ContentFormatter

```python
@dataclass
class FormattedContent:
    text: str
    code_blocks: list[CodeBlock]
    thinking_blocks: list[str]
    tool_summaries: list[ToolSummary]

class ContentFormatter:
    """Formats agent output for display (platform-agnostic)."""

    def format(self, messages: list[AgentMessage], *, verbose: bool = False) -> FormattedContent:
        if verbose:
            return self._format_verbose(messages)
        return self._format_compact(messages)

    def _format_compact(self, messages: list[AgentMessage]) -> FormattedContent:
        """Show only status updates and final results."""
        ...

    def _format_verbose(self, messages: list[AgentMessage]) -> FormattedContent:
        """Show all output including tool calls, thinking, bash output."""
        ...
```

## 6. Platform Comparison

| Capability | Telegram | Feishu |
|---|---|---|
| Rich text | MessageEntity offsets | Rich text (lark format) |
| Cards/Buttons | InlineKeyboardMarkup | Interactive Card |
| Card updates | `edit_message_text` | Card update API |
| Images | `send_photo` | `send_image` |
| Files | `send_document` | `send_file` |
| Topics/Threads | Forum Topics | Message threads |
| Webhook | Long polling (PTB) | Event subscription webhook |
| Rate limits | 30 msg/sec group, 1 msg/sec user | 5 msg/sec app |
| Max message | 4096 chars | 10000 chars (card) |
| Max card buttons | No hard limit | 100 components |

## 7. Testing

Each adapter is tested with:

1. **Unit tests**: Mock platform SDK, verify correct API calls
2. **Integration tests**: Real gateway + adapter, mock platform HTTP
3. **Snapshot tests**: Verify card/message JSON payloads match expected format
