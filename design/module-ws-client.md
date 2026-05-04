# Module: WS Client (Feishu WebSocket Long-Connection)

> The Feishu proprietary WebSocket binary protocol client: connects, receives protobuf frames, and dispatches parsed events to registered handlers.

---

## 1. Purpose

`ws_client.py` implements the Feishu long-connection WebSocket protocol (v2). Rather than accepting HTTP webhooks (which require a public URL), cclark initiates an outbound WebSocket connection to Feishu. This removes the need for a publicly reachable server and allows cclark to run behind NAT — a critical advantage for local development and private deployments.

The module handles:
- Fetching a `wss://` URL from Feishu via a short-lived HTTP POST
- Connecting to the WebSocket and performing a handshake
- Sending periodic ping frames (Feishu expects application-level ping/pong, not the WebSocket wire-level kind)
- Decoding binary protobuf `Frame` messages from Feishu
- Auto-reconnecting on disconnect with jittered back-off
- Deduplicating replayed events (Feishu re-delivers after reconnect)
- Self-filtering (ignoring messages sent by the bot itself)
- Per-user authorization checks
- Routing parsed `FeishuMessageEvent` objects to the module-level message handler

The HTTP health endpoint (`/health`) lives in `webhook.py` — it is a separate FastAPI app that answers load-balancer probes and is not involved in event routing.

---

## 2. Architecture

```
Feishu Open Platform
        │
        │ 1. POST /callback/ws/endpoint  (HTTP, short-lived)
        │    ← { url: "wss://...", ClientConfig: {...} }
        ▼
┌──────────────────────────────────────────────────────────┐
│                    FeishuWSClient                         │
│                                                           │
│  _get_ws_url()   — fetch wss:// URL + timing config       │
│         │                                                 │
│  _connect_and_receive()                                   │
│    ├── _handshake()        — websocket handshake +        │
│    │                         optional first-frame read     │
│    ├── _ping_loop()        — send ping frames every N s    │
│    └── receive loop       — for raw in self._ws          │
│         │                                                 │
│  _handle_frame(raw)     — decode protobuf Frame           │
│    ├── method=0 (CONTROL) → handle PING → send PONG       │
│    └── method=1 (DATA)   → _dispatch_event(payload)       │
│         │                                                 │
│  _dispatch_event(payload)                                │
│    ├── parse JSON                                         │
│    ├── self-filter (skip own messages)                    │
│    ├── deduplicate (event_id + message_id)               │
│    ├── authorization check                               │
│    └── _message_handler(event)  ← module-level handler     │
│                                                           │
│  Auto-reconnect loop (start):                            │
│    try _connect_and_receive()                             │
│    except OSError/WebSocketException → sleep(jitter) → retry│
└──────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│  Module-level registry (set by main.py)                   │
│                                                           │
│  register_message_handler(fn)  → sets _message_handler    │
│                                                           │
│  _message_handler(event: FeishuMessageEvent)              │
│      → handlers/message.handle_message(event)            │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  webhook.py  — FastAPI health server (separate app)       │
│  GET /health → {"status": "ok"}                          │
│  (No event routes — all events arrive via WS above)      │
└──────────────────────────────────────────────────────────┘
```

---

## 3. Key Components

### 3.1 FeishuWSClient

```python
class FeishuWSClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        app_name: str = "default",
        ping_interval: float = 90.0,
        reconnect_interval: float = 5.0,
        reconnect_nonce: float = 3.0,
    ) -> None: ...

    async def start() -> None:  # blocks, reconnects automatically
    async def stop() -> None:   # graceful shutdown
```

**`start()`** enters a reconnect loop. Each iteration calls `_connect_and_receive()`, which establishes the WebSocket connection and enters the async receive loop. Any `OSError`, `WebSocketException`, `ConnectionError`, or `TimeoutError` causes the loop to sleep with jitter before reconnecting. `asyncio.CancelledError` exits cleanly.

**`_get_ws_url()`** POSTs to `https://open.feishu.cn/callback/ws/endpoint` with `AppID` and `AppSecret`. The response contains `data.url` (the `wss://` address) and `data.ClientConfig` (server-recommended ping/reconnect intervals). cclark adopts the server-suggested timing when provided.

**`_connect_and_receive()`** performs the WebSocket handshake, starts `_ping_loop()`, then iterates `async for raw in self._ws`. Each raw frame is passed to `_handle_frame()`.

**`_handshake()`** calls `websockets.connect()`, waits up to 5 seconds for an optional initial frame from Feishu (which may contain session metadata), then returns. If no frame arrives within 5 s it proceeds anyway — the receive loop handles everything after the handshake.

**`_ping_loop()`** runs as a separate `asyncio.Task`. Every `ping_interval` seconds it sends a pre-encoded binary ping frame. Feishu's protocol requires application-level ping/pong, not the WebSocket wire-level kind, so `ping_interval=None` is passed to `websockets.connect()` to suppress the library's own pinger.

### 3.2 Protobuf Frame Encoding / Decoding

Feishu's WebSocket frames are raw protobuf-encoded binary messages, not JSON. The module ships a minimal hand-rolled implementation:

- `_encode_varint(value)` / `_decode_varint(data, pos)` — variable-length integer encoding (7-bit per byte, continuation bit)
- `encode_frame(method, payload, headers, service_id, seq_id)` — builds a `Frame` protobuf
- `decode_frame(data)` — parses a binary frame, returns `(headers_dict, payload_bytes, service_id, method)`

`Frame` fields used: `SeqID` (1), `LogID` (2), `Service` (3), `Method` (4), `Headers` (5), `PayloadEncoding` (6), `PayloadType` (7), `Payload` (8). `Headers` is itself a nested `Header{key, value}` proto.

`_get_ping_frame(service_id)` pre-builds the ping frame at module import time (stateless once built) so the ping loop only pays serialization cost once.

### 3.3 Frame Dispatch

`_handle_frame(raw)` decodes the binary frame, then:
- `method == _METHOD_CONTROL (0)`: inspect `headers["type"]`. `"ping"` → reply with a pong frame. `"pong"` → log and return.
- `method == _METHOD_DATA (1)`: call `_dispatch_by_type("event", payload)`.
- `payload` is a JSON byte string containing the Feishu event schema.

### 3.4 Event Parsing and Filtering

`_dispatch_event(payload)` is the main inbound event handler:

1. **JSON parse** the payload.
2. **Self-filter**: extract `sender.sender_type` and `id` (app_id). If `sender_type == "app"` or `id == self._app_id`, skip — this prevents the bot from processing its own output messages that Feishu re-delivers.
3. **Deduplicate by event_id**: events are persisted to `~/.unified-icc/seen_events.json`. A duplicate is silently dropped.
4. **Deduplicate by message_id**: messages persisted to `~/.unified-icc/seen_messages.json`.
5. **Authorization**: `config.is_user_allowed_in_app(user_id, app_name)` (multi-app) or `config.is_user_allowed(user_id)` (single-app). Unauthorized users are dropped silently (no error response to avoid information leakage).
6. **Annotate event**: `event._app_name = self._app_name` is set so downstream handlers can route to the correct app context.
7. **Dispatch**: call `_message_handler(event)` (registered by `handlers/message.py`).

### 3.5 Module-Level Handler Registry

The registry is intentionally module-level (two simple module variables, no class):

```python
_message_handler: Any | None = None

def register_message_handler(handler: Any) -> None:
    global _message_handler
    _message_handler = handler
```

`main.py` calls `register_message_handler(handlers.message.handle_message)` at startup. The handler signature is `async def handle_message(event: FeishuMessageEvent)`.

### 3.6 Token Management

Unlike the REST API (which uses `tenant_access_token`), the WebSocket protocol authenticates via the initial HTTP POST (`AppID` + `AppSecret`). No bearer token is needed in the WebSocket frames themselves. Token management for REST calls (used by `feishu_client.py` to send messages, upload images, patch cards) is handled separately in `feishu_client.py`.

---

## 4. Data Flow

### 4.1 Full inbound message flow

```
Feishu sends protobuf Frame (method=1, headers["type"]="event")
    ↓
FeishuWSClient._handle_frame(raw)
    ↓ decode_frame → (headers, payload_bytes, service_id, method=1)
    ↓
METHOD_DATA → _dispatch_by_type("event", payload_bytes)
    ↓
_dispatch_event(payload_bytes)
    ├── json.loads(payload_bytes)
    ├── self-filter (skip own messages)
    ├── deduplicate event_id + message_id
    ├── is_user_allowed check
    ├── event._app_name = self._app_name
    └── _message_handler(event)  ← → handlers/message.handle_message
```

### 4.2 Ping/pong flow

```
Feishu sends CONTROL frame (method=0, headers["type"]="ping")
    ↓
_handle_frame → method==0
    ↓
headers["type"] == "ping"
    ↓
ws.send(_get_ping_frame(self._service_id))
    ↓
Feishu receives pong
```

### 4.3 Reconnect flow

```
WS disconnects (e.g. network glitch)
    ↓
websockets.ConnectionClosed raised in receive loop
    ↓
_connect_and_receive() raises
    ↓
start() catches exception, increments reconnect_count
    ↓
sleep(reconnect_interval + random(0, reconnect_nonce))
    ↓
retry _connect_and_receive()
```

---

## 5. State / Persistence

### 5.1 In-memory state

| Variable | Type | Purpose |
|---|---|---|
| `_message_handler` | `Any \| None` | Registered async callback |
| `_seen_events` | `set[str]` | Event IDs already processed (in-process dedup) |
| `_seen_messages` | `set[str]` | Message IDs already processed (in-process dedup) |
| `FeishuWSClient._service_id` | `int` | Feishu-assigned service ID, embedded in every frame |
| `FeishuWSClient._running` | `bool` | Controls the reconnect loop |

### 5.2 Persisted state

`~/.unified-icc/seen_events.json` — JSON file mapping `{"events": [...], "messages": [...]}` used to survive process restarts. Loaded at module import time (`_load_seen_state()`). Updated on every new event/message ID (`_save_seen_state()`).

---

## 6. Error Handling

| Error | Behaviour |
|---|---|
| WS disconnect | Reconnect with jitter (no maximum retry limit — keeps trying indefinitely) |
| Frame decode failure | Log warning, skip frame, continue |
| JSON parse failure in payload | Log warning, skip event |
| Handler exception | Log exception, continue (do not crash the receive loop) |
| Authorization failure | Silently drop event |
| `_get_ws_url` HTTP error | Raise `FeishuWSError`, trigger reconnect |
| `asyncio.CancelledError` in `start()` | Exit cleanly (normal shutdown) |

The ping loop catches its own send errors and breaks out — the outer reconnect loop then handles reconnecting.

---

## 7. Design Decisions

### 7.1 WebSocket over HTTP webhooks

Feishu offers two event delivery modes:
- **HTTP webhook**: Feishu POSTs to a public URL. Requires ngrok/Cloudflare Tunnel in development.
- **WebSocket long-connection**: cclark POSTs to Feishu to get a `wss://` URL, then connects outbound. No public URL needed.

cclark uses WebSocket exclusively. This allows it to run on a laptop behind WiFi without port forwarding.

### 7.2 Hand-rolled protobuf

Rather than depending on `protobuf` (which requires a `.proto` schema file and a code generation step), the module implements the two needed proto structures (`Frame`, `Header`) as plain byte manipulation. This keeps the dependency footprint small and avoids build-tool complexity.

### 7.3 Application-level ping/pong

Feishu's protocol expects the application to respond to `type: ping` control frames with a pong. The `websockets` library's built-in ping/pong is disabled (`ping_interval=None`) to avoid conflicts.

### 7.4 Self-filter by sender_type and app_id

When cclark sends a message via `FeishuAdapter`, Feishu delivers that message back as a new `im.message.receive_v1` event. Without filtering, cclark would process its own output and create a feedback loop. The self-filter checks both `sender_type == "app"` (standard bot messages) and `id == self._app_id` (card/edge cases) to be robust across Feishu schema variants.

### 7.5 Deduplication files

Feishu guarantees "at-least-once" delivery: after a WS reconnect it may replay recent events. The `seen_events.json` / `seen_messages.json` files allow cclark to survive process restarts without re-processing the same event. Files are small (two JSON arrays), so writes are cheap.

### 7.6 Per-app WSClient instances

In multi-app mode, `main.py` creates one `FeishuWSClient` per app. Each instance carries its own `_app_id`, `_app_name`, `_service_id`, and reconnect loop. They share no state — only the global `_seen_*` dedup sets (which intentionally cross-app deduplicate across all apps using the same filesystem path).
