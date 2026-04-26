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

### 3.3 Webhook Event Flow

```
Feishu Platform
    │
    │  HTTP POST (event JSON)
    ▼
FastAPI /webhook/event
    │
    ├── Verify signature + decrypt
    ├── Parse event type
    │
    ├── "im.message.receive_v1"  → message_handler
    ├── "card.action.callback"   → callback_handler
    │
    ▼
Gateway API call or card update
```

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

When a user clicks a card button, Feishu sends a callback to the webhook:

```python
async def handle_card_callback(event: FeishuCardCallback):
    action = event.action.value  # {"choice": "jwt"} or {"action": "allow"}
    channel_id = f"feishu:{event.event_context.chat_id}"

    if "choice" in action:
        # AskUserQuestion response
        await gateway.send_to_window(window_id, action["choice"])
    elif action.get("action") == "allow":
        # Permission granted
        await gateway.send_key(window_id, "y")
    elif action.get("action") == "deny":
        # Permission denied
        await gateway.send_key(window_id, "n")
```

## 9. Session Creation Flow

When a user sends the first message in an unbound thread:

```
1. User: "fix the login bug"
    ↓
2. cclark: Show directory browser card
    ├── 📁 /home/user/
    │   ├── projects/
    │   ├── code/
    │   └── ...
    ↓
3. User clicks "projects/"
    ↓
4. cclark: Update card with subdirectories
    ├── 📁 /home/user/projects/
    │   ├── api/
    │   ├── frontend/
    │   └── ...
    ↓
5. User clicks "api/"
    ↓
6. cclark: Show provider picker card
    ├── 🟠 Claude Code
    ├── 🧩 Codex CLI
    ├── 🐚 Shell
    └── ...
    ↓
7. User clicks "Claude Code"
    ↓
8. cclark: Show mode picker card
    ├── ✅ Standard
    └── 🚀 YOLO
    ↓
9. User clicks "Standard"
    ↓
10. cclark:
    - Create tmux window via gateway
    - Bind channel → window
    - Forward original message "fix the login bug"
```

## 10. Webhook Server

```python
from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/webhook/event")
async def event_handler(request: Request):
    body = await request.json()
    # Verify + decrypt
    event = parse_event(body)

    if event.type == "im.message.receive_v1":
        await handle_feishu_message(event)
    elif event.type == "url_verification":
        return {"challenge": event.challenge}

    return {"code": 0}

@app.post("/webhook/card")
async def card_callback_handler(request: Request):
    body = await request.json()
    event = parse_card_callback(body)
    await handle_card_callback(event)
    return {"code": 0}
```

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
| Message transport | Long polling (PTB) | Webhook (FastAPI) |
| Rich UI | Inline keyboards | Interactive cards |
| Message updates | `edit_message_text` | Card patch API |
| Max message size | 4096 chars | ~10000 chars (card) |
| Thread model | Forum topics (built-in) | Message threads or groups |
| Rate limits | 30/sec group | 5/sec app |
| SDK style | Async-native (PTB) | Sync (lark-oapi) → wrap async |
| File uploads | `send_document` | Upload API → `send_file` |
| Voice | `send_voice` | Audio message handling |
