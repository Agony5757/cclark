# Module: Feishu Frontend (cclark)

> The Feishu bot implementation that serves as the user-facing frontend for unifiedcc.

---

## 1. Purpose

`cclark` is a Feishu bot that provides the same user experience as ccgram's Telegram bot, but using Feishu's native UI components (cards, buttons, rich text). It consumes the `unifiedcc` gateway API.

## 2. Architecture

```
┌────────────────────────────────────────────────────┐
│                    cclark                           │
│                                                    │
│  ┌──────────────┐    ┌──────────────────────────┐  │
│  │  FastAPI      │    │  FeishuAdapter            │  │
│  │  Webhook      │───▶│  (FrontendAdapter impl)   │  │
│  │  Server       │    │                          │  │
│  └──────────────┘    │  - send_text()            │  │
│                       │  - send_card()            │  │
│  ┌──────────────┐    │  - update_card()          │  │
│  │  Event        │◀───│  - send_image()           │  │
│  │  Handler     │    │  - show_prompt()           │  │
│  │              │    └──────────────────────────┘  │
│  │  on_message  │                                  │
│  │  on_status   │    ┌──────────────────────────┐  │
│  │  on_hook     │    │  CardBuilder               │  │
│  └──────┬───────┘    │  (Feishu card templates)   │  │
│         │            └──────────────────────────┘  │
│         │                                         │
│         ▼                                         │
│  ┌──────────────────────────────────────────────┐  │
│  │            UnifiedCC Gateway                  │  │
│  └──────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────┘
```

## 3. Feishu Bot Setup

### 3.1 Prerequisites

1. Create a Feishu app at [Feishu Open Platform](https://open.feishu.cn/)
2. Enable bot capabilities
3. Configure event subscription URL
4. Set permissions: `im:message`, `im:message:send_as_bot`, `im:chat`, `im:resource`

### 3.2 Configuration

```ini
# ~/.cclark/.env
FEISHU_APP_ID=cli_xxxxxxx
FEISHU_APP_SECRET=xxxxxxx
FEISHU_VERIFICATION_TOKEN=xxxxxxx
FEISHU_ENCRYPT_KEY=xxxxxxx
CCLARK_DIR=~/.cclark
CCLARK_PROVIDER=claude
ALLOWED_USERS=ou_xxxxxxx
```

### 3.3 WebSocket Event Flow (not Webhook)

The webhook-based event flow is **not used**. All events arrive via the WebSocket
long-connection in `ws_client.py`:

```
Feishu Platform
    │
    │  wss://... (outbound WS connection)
    ▼
FeishuWSClient
    │
    ├── Protobuf frame decode
    ├── Self-filter (skip own messages)
    ├── Deduplicate event_id / message_id
    ├── Authorization check
    │
    ├── "im.message.receive_v1"  → parse_message_event → handle_message
    │
    ▼
Gateway API call or card update
```

See `design/module-ws-client.md` for the full protocol details.

## 4. Message Handler

### 4.1 Inbound Flow

```python
async def handle_feishu_message(event: FeishuMessageEvent):
    channel_id = f"feishu:{event.chat_id}:{event.message_id}"
    user_id = event.user_id
    text = extract_text(event.message)

    # Check if channel is bound to a window
    window_id = gateway.resolve_window(channel_id)

    if window_id is None:
        # Unbound channel — show directory browser
        await show_directory_browser(channel_id)
        return

    # Forward to agent
    await gateway.send_to_window(window_id, text)
```

### 4.2 Outbound Flow

```python
@gateway.on_message
async def on_agent_message(event: AgentMessageEvent):
    for channel_id in event.channel_ids:
        formatted = formatter.format(event.messages, verbose=is_verbose(channel_id))

        if formatted.tool_summaries or formatted.code_blocks:
            # Rich content → Feishu card
            card = card_builder.build_output_card(formatted)
            await adapter.send_card(channel_id, card)
        else:
            # Simple text
            await adapter.send_text(channel_id, formatted.text)
```

## 5. FeishuAdapter Implementation

### 5.1 SDK Choice

Use `lark-oapi` (official Feishu Python SDK):

```python
import lark_oapi as lark
from lark_oapi.api.im.v1 import *

class FeishuAdapter:
    def __init__(self, app_id: str, app_secret: str):
        self.client = lark.Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .build()

    async def send_text(self, channel_id: str, text: str) -> str:
        request = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(channel_id)
                .msg_type("text")
                .content(json.dumps({"text": text}))
                .build()
            ).build()
        response = await asyncio.to_thread(
            self.client.im.v1.message.create, request
        )
        return response.data.message_id

    async def send_card(self, channel_id: str, card: CardPayload) -> str:
        card_json = self._build_card_json(card)
        request = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(channel_id)
                .msg_type("interactive")
                .content(card_json)
                .build()
            ).build()
        response = await asyncio.to_thread(
            self.client.im.v1.message.create, request
        )
        return response.data.message_id

    async def update_card(self, channel_id: str, card_id: str, card: CardPayload) -> None:
        card_json = self._build_card_json(card)
        request = PatchMessageRequest.builder() \
            .message_id(card_id) \
            .request_body(
                PatchMessageRequestBody.builder()
                .content(card_json)
                .build()
            ).build()
        await asyncio.to_thread(
            self.client.im.v1.message.patch, request
        )

    async def send_image(self, channel_id: str, image_bytes: bytes, caption: str = "") -> str:
        # Upload image first, then send image message
        image_key = await self._upload_image(image_bytes)
        request = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(channel_id)
                .msg_type("image")
                .content(json.dumps({"image_key": image_key}))
                .build()
            ).build()
        response = await asyncio.to_thread(
            self.client.im.v1.message.create, request
        )
        return response.data.message_id
```

### 5.2 Async Bridge

The `lark-oapi` SDK is synchronous. Bridge to async:

```python
async def _call_sdk(self, func, *args):
    """Run synchronous SDK call in thread pool."""
    return await asyncio.to_thread(func, *args)
```

Alternatively, for better performance, use `httpx` directly with Feishu's REST API (bypassing the SDK).

## 6. Channel Binding Model

### 6.1 Single Group + Threads (Default)

```
Feishu Group (群组)
├── Thread: "api-project"  → tmux @0 (claude)
├── Thread: "ui-project"   → tmux @1 (claude)
└── Thread: "ops"          → tmux @2 (shell)
```

Channel ID format: `feishu:{chat_id}:{thread_id}`

When a user sends a message in a thread:
1. Look up `channel_id` in channel_router
2. If unbound → show directory browser (first message in new thread)
3. If bound → forward to tmux window

### 6.2 Multi-Group (Alternative)

Each session is a separate group chat. The bot joins multiple groups.

Channel ID format: `feishu:{chat_id}`

This requires creating group chats programmatically (possible via Feishu API).

## 7. Interactive Prompts in Feishu

### 7.1 AskUserQuestion

```json
{
  "config": {"wide_screen_mode": true},
  "header": {
    "title": {"tag": "plain_text", "content": "🤔 Claude asks"},
    "template": "blue"
  },
  "elements": [
    {
      "tag": "markdown",
      "content": "Which authentication method should I use?"
    },
    {
      "tag": "action",
      "actions": [
        {"tag": "button", "text": {"tag": "plain_text", "content": "JWT"}, "value": {"choice": "jwt"}, "type": "primary"},
        {"tag": "button", "text": {"tag": "plain_text", "content": "OAuth2"}, "value": {"choice": "oauth2"}, "type": "default"},
        {"tag": "button", "text": {"tag": "plain_text", "content": "Session"}, "value": {"choice": "session"}, "type": "default"}
      ]
    }
  ]
}
```

### 7.2 Permission Prompt

```json
{
  "config": {"wide_screen_mode": true},
  "header": {
    "title": {"tag": "plain_text", "content": "🔐 Permission Request"},
    "template": "orange"
  },
  "elements": [
    {
      "tag": "markdown",
      "content": "**Command:** `rm -rf node_modules`\n**Risk:** Destructive file deletion"
    },
    {
      "tag": "action",
      "actions": [
        {"tag": "button", "text": {"tag": "plain_text", "content": "✅ Allow"}, "value": {"action": "allow"}, "type": "primary"},
        {"tag": "button", "text": {"tag": "plain_text", "content": "❌ Deny"}, "value": {"action": "deny"}, "type": "danger"}
      ]
    }
  ]
}
```

## 8. Callback Handling

Card button callbacks are **not wired** in the current implementation.
Permission and plan prompts show numbered options; the user replies with the
digit directly. See `design/module-cards.md` §8.5 for rationale.

The Feishu card button infrastructure (`build_prompt_card`, `build_permission_card`,
etc.) is still built so it can be wired in a future iteration.

## 9. Session Creation Flow

When a user sends the first message in an unbound thread:

The wizard is entirely text-based (no Feishu card buttons):

```
1. User: "fix the login bug"
    ↓
2. cclark: Text listing of home directory + subdirectories
    "New session setup: choose the workspace directory.
     Current directory: /home/user/
     Reply with a number or folder name..."
    ↓
3. User sends "1" (enter first subdirectory)
    → _handle_browse: navigate, re-list new directory
    ↓
   (User navigates with numbers, names, "..", #select <path>)
    ↓
4. User sends "ok"
    → update_user_mru() → advance to provider phase
    → send text: "Select provider:\n  1. claude  2. codex  3. gemini  4. pi  5. shell"
    ↓
5. User sends "1" (claude)
    → advance to mode phase
    → send text: "Select mode:\n  1. standard  2. yolo"
    ↓
6. User sends "1" (standard)
    → _create_window(channel_id, user_id, path, "claude", "standard")
    → gateway.create_window(path, provider="claude", mode="standard")
    → gateway.bind_channel(channel_id, window_id)
    → window_store record + detect_session_id()
    → forward original message "fix the login bug"
```

## 10. Webhook Server (Not Used)

The webhook server (FastAPI) is **not used** in the current implementation.
All Feishu events arrive via the WebSocket long connection in `ws_client.py`.
The `webhook.py` FastAPI app retains only the `GET /health` endpoint for
load-balancer probes. See `design/module-ws-client.md` for the full WebSocket
event path.

## 11. Dependencies

```
# Feishu SDK
lark-oapi>=1.4.0

# Webhook server
fastapi>=0.110.0
uvicorn>=0.29.0

# Async HTTP (alternative to SDK)
httpx>=0.27.0

# Core
unifiedcc  # Local package
```

## 12. Key Differences from ccgram

| Aspect | ccgram (Telegram) | cclark (Feishu) |
|---|---|---|
| Message transport | Long polling (PTB) | WebSocket long-connection |
| Rich UI | Inline keyboards | Interactive cards |
| Message updates | `edit_message_text` | Card patch API |
| Session creation | Card buttons | Text-based wizard |
| Approval mechanism | Card button callbacks | Numbered text replies |
| Max message size | 4096 chars | ~10000 chars (card) |
| Thread model | Forum topics (built-in) | Message threads or groups |
| Rate limits | 30/sec group | 5/sec app |
| SDK style | Async-native (PTB) | httpx async client |
| File uploads | `send_document` | Upload API → `send_file` |
| Voice | `send_voice` | Audio message handling |
