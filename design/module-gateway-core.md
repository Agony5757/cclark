# Module: Gateway Core (unifiedcc)

> The platform-agnostic engine extracted from ccgram that manages AI coding agents via tmux.

---

## 1. Purpose

`unifiedcc` is a Python library that provides all the logic needed to manage AI coding agent sessions in tmux windows, monitor their output, and dispatch events — without any dependency on a specific messaging platform.

## 2. Source: CCGram Module Mapping

| unifiedcc module | ccgram source | Adaptation needed |
|---|---|---|
| `gateway.py` | New orchestration | Combines session_manager + monitor + hooks |
| `channel_router.py` | `thread_router.py` | Generalize `thread_id: int` → `channel_id: str` |
| `event_types.py` | `providers/base.py` (partial) | Extract `AgentMessageEvent`, `StatusEvent`, etc. |
| `config.py` | `config.py` | Split gateway config from frontend config |
| `providers/` | `providers/` (entire) | Direct import |
| `tmux_manager.py` | `tmux_manager.py` | Direct import |
| `session_monitor.py` | `session_monitor.py` | Decouple callback signatures |
| `transcript_reader.py` | `transcript_reader.py` | Direct import |
| `event_reader.py` | `event_reader.py` | Direct import |
| `session_lifecycle.py` | `session_lifecycle.py` | Direct import |
| `transcript_parser.py` | `transcript_parser.py` | Direct import |
| `hook.py` | `hook.py` | Direct import |
| `state_persistence.py` | `state_persistence.py` | Direct import |
| `window_state_store.py` | `window_state_store.py` | Direct import |
| `session_map.py` | `session_map.py` | Direct import |
| `window_resolver.py` | `window_resolver.py` | Direct import |
| `window_query.py` | `window_query.py` | Direct import |
| `session_query.py` | `session_query.py` | Direct import |
| `idle_tracker.py` | `idle_tracker.py` | Direct import |
| `monitor_state.py` | `monitor_state.py` | Direct import |
| `mailbox.py` | `mailbox.py` | Direct import |

## 3. Core API: `UnifiedCC`

```python
from unifiedcc import UnifiedCC

gateway = UnifiedCC(
    config=GatewayConfig(
        tmux_session="cclark",
        default_provider="claude",
        config_dir="~/.unified-icc",
        poll_interval=1.0,
    )
)

# Register event callbacks
@gateway.on_message
async def handle_message(event: AgentMessageEvent):
    """Called when agent produces output."""
    for msg in event.messages:
        print(f"[{event.window_id}] {msg.text}")

@gateway.on_status
async def handle_status(event: StatusEvent):
    """Called when agent status changes."""
    print(f"[{event.window_id}] {event.status}: {event.display_label}")

@gateway.on_hook_event
async def handle_hook(event: HookEvent):
    """Called on Claude Code hook events."""
    print(f"[{event.window_id}] hook: {event.event_type}")

# Start gateway
await gateway.start()

# Create a session
window = await gateway.create_window(
    work_dir="/home/user/project",
    provider="claude",
)
gateway.bind_channel("feishu:thread_123", window.window_id)

# Send user input
await gateway.send_to_window(window.window_id, "fix the login bug")

# Stop gateway
await gateway.stop()
```

## 4. Channel Router

Replaces ccgram's `ThreadRouter` with a platform-agnostic channel mapping:

```python
@dataclass
class ChannelBinding:
    channel_id: str        # Platform-specific: "feishu:thread_123", "telegram:topic_42"
    window_id: str         # tmux: "@0", "@12"
    display_name: str      # "api-project"
    provider_name: str     # "claude", "codex"
    user_id: str           # Platform-specific user identifier

class ChannelRouter:
    """Bidirectional channel↔window mapping."""

    def bind(self, channel_id: str, window_id: str, display_name: str = "",
             provider_name: str = "", user_id: str = "") -> None: ...
    def unbind(self, channel_id: str) -> None: ...
    def resolve_window(self, channel_id: str) -> str | None: ...
    def resolve_channels(self, window_id: str) -> list[str]: ...
    def get_display_name(self, window_id: str) -> str: ...
    def list_bindings(self) -> list[ChannelBinding]: ...
```

**Key difference from ccgram**: ccgram uses `dict[int, dict[int, str]]` (user_id → thread_id → window_id) keyed by Telegram integer IDs. The unified version uses string-based `channel_id` to support any platform's identifier scheme.

## 5. Event Dispatch

The gateway dispatches events through registered callbacks, matching ccgram's callback pattern but with frontend-agnostic event types:

```python
class UnifiedCC:
    def on_message(self, callback): ...
    def on_status(self, callback): ...
    def on_hook_event(self, callback): ...
    def on_window_change(self, callback): ...
```

The monitor loop (1s poll) reads:
1. `session_map.json` — window↔session bindings
2. `events.jsonl` — hook events (byte-offset incremental)
3. Agent transcripts — JSONL (mtime cache + byte-offset incremental)

Each event is dispatched to all registered callbacks concurrently.

## 6. State Persistence

Reuses ccgram's debounced atomic JSON persistence:

```
~/.unified-icc/
├── state.json           # Channel bindings + window states + display names
├── session_map.json     # Hook-generated window_id→session mapping
├── events.jsonl         # Append-only hook event log
├── monitor_state.json   # Byte offsets per session file
└── mailbox/             # Inter-agent messaging (future)
```

## 7. Import Strategy

**Option A: Fork and extract (Recommended for MVP)**
- Copy relevant ccgram modules into `unifiedcc/`
- Modify `thread_router` → `channel_router`
- Keep provider imports working
- Faster iteration, no coupling to ccgram release cycle

**Option B: Import ccgram as dependency**
- `pip install ccgram` as a dependency
- Import and wrap ccgram's internal modules
- Risk: ccgram's internals may change; tight coupling

**Option C: Adapter pattern (Ideal long-term)**
- Define `unifiedcc` interfaces
- Implement adapters that wrap ccgram modules
- Clean separation but more boilerplate

**Decision**: Start with Option A for speed, migrate to Option C as the API stabilizes.

## 8. Dependencies

```
# From ccgram (direct reuse)
libtmux>=0.50.0
pyte>=0.8.2
Pillow>=10.0.0
aiofiles>=24.0.0
structlog>=24.0.0
pathspec>=0.12
python-dotenv>=1.0.0
httpx>=0.27.0

# New for unifiedcc
# (none — gateway is deliberately dependency-light)
```

## 9. Testing Strategy

Same three-tier approach as ccgram:

| Tier | Pattern | Coverage |
|---|---|---|
| Unit | Mock tmux + filesystem | Channel routing, state persistence |
| Integration | Real tmux + filesystem | Window lifecycle, transcript reading |
| E2E | Real agent CLIs + real tmux | Full agent lifecycle |
