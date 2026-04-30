# Module: State, Config, User Preferences, and Event Parsers

> In-memory state per channel, application configuration from YAML, per-user preference storage, and Feishu event parsing.

---

## 1. Purpose

This group of four modules provides the context and persistence infrastructure that all other modules depend on:

- **`config.py`** — reads `~/.cclark/config.yaml` (or `.env` fallback), exposes per-app and global config values as a singleton `config` object.
- **`state.py`** — in-memory per-channel state: streaming card IDs, turn indices, thinking card state, and toolbar state.
- **`user_preferences.py`** — per-user MRU directories and window read offsets, backed by the unified-icc window state store.
- **`event_parsers.py`** — translates the raw JSON payload from the WebSocket client into a typed `FeishuMessageEvent` dataclass.

---

## 2. Architecture

```
FeishuWSClient._dispatch_event(raw_payload)
        │
        ▼
event_parsers.parse_message_event(raw_payload)
        │
        ├── Handles schema 1.0 and 2.0 differences
        ├── Extracts chat_id, thread_id, user_id, text, message_id, msg_type
        └── Returns FeishuMessageEvent | None
                │
                ▼
handlers/message.handle_message(event)
        │
        ├── config.parse_channel_id(chat_id, thread_id)
        │     → "feishu:{app}:{chat_id}[:{thread_id}]"  (multi-app)
        │     → "feishu:{chat_id}[:{thread_id}]"         (single-app)
        │
        ├── config.is_user_allowed(user_id)  [or is_user_allowed_in_app]
        │     → reject unauthorized users early
        │
        ├── state.get_verbose_state(channel_id)
        │     → VerboseChannelState (streaming card, thinking card, turn index)
        │
        ├── state.get_toolbar_state(channel_id)
        │     → ToolbarState (toolbar card ID, attached window)
        │
        ├── state.advance_turn_index(channel_id)
        │     → increments turn, resets streaming card IDs
        │
        ├── user_preferences.update_user_mru(user_id, path)
        │     → persists MRU directories per user
        │
        └── gateway.send_to_window(window_id, text)
              └── channel_router.resolve_window(channel_id) → window_id

gateway events (on_message, on_status)
        │
        ├── VerboseCardStreamer.push(text, turn_index)
        │     └── state.get_verbose_state(channel_id).streaming_card_id = msg_id
        │
        └── ThinkingCardStreamer.push_thinking(text, is_complete)
              └── state.get_verbose_state(channel_id).streaming_thinking_card_id = msg_id
```

---

## 3. Key Components

### 3.1 config.py — FeishuConfig

#### Loading order

1. `load_dotenv()` for `.env` and `~/.cclark/.env` (backward compat and local overrides)
2. If `~/.cclark/config.yaml` exists → `_load_yaml()` (multi-app)
3. Otherwise → `_load_from_env()` (single-app backward compat)
4. If no apps loaded → raise `ValueError`

#### YAML format

```yaml
apps:
  - name: "default"
    app_id: "cli_xxx"
    app_secret: "xxx"
    allowed_users: "all"          # or "open_id1,open_id2,..."
    provider: "claude"
    tmux_session: "cclark"
    health_port: 8080
  - name: "admin"
    app_id: "cli_yyy"
    app_secret: "yyy"
    allowed_users: "ou_admin1"     # restricted
    provider: "claude"
    tmux_session: "cclark-admin"
    health_port: 8081
```

#### Channel ID format

```
Single-app:   feishu:{chat_id}[:{thread_id}]
Multi-app:    feishu:{app_name}:{chat_id}[:{thread_id}]
```

`parse_channel_id(chat_id, thread_id)` builds the appropriate string. `split_channel_id(channel_id)` parses it back into `(chat_id, thread_id)`, with a heuristic: if the middle segment starts with `oc_` or `ou_` it is treated as a Feishu ID (single-app), otherwise as an app name (multi-app).

`app_name_for_channel(channel_id)` extracts the app name from a channel ID string.

#### Authorization

```python
def is_user_allowed(self, user_id: str) -> bool:
    allowed = self._default_app.allowed_users
    return allowed is None or user_id in allowed

def is_user_allowed_in_app(self, user_id: str, app_name: str) -> bool:
    app = self._by_name.get(app_name)
    if app is None:
        return False
    return app.allowed_users is None or user_id in app.allowed_users
```

`None` for `allowed_users` means allow all. Empty string or `"all"` in YAML is converted to `None`.

#### Convenience shortcuts

For single-app usage, the singleton `config` object exposes `@property` accessors that delegate to `self._default_app`: `feishu_app_id`, `feishu_app_secret`, `allowed_users`, `default_provider`, `health_port`.

### 3.2 state.py — VerboseChannelState and ToolbarState

#### VerboseChannelState

```python
@dataclass
class VerboseChannelState:
    streaming_card_id: str | None = None
    last_flush_ms: float = 0
    turn_states: dict[str, VerboseTurnState]  # user_id → turn state
    streaming_thinking_card_id: str | None = None
    streaming_thinking_text: str = ""
    streaming_thinking_active: bool = False
    _verbose_enabled: bool = False
```

`VerboseTurnState` tracks the highest turn index seen by a given user/window:
```python
@dataclass
class VerboseTurnState:
    last_turn_index: int = -1
    pending_text: str = ""
```

#### ToolbarState

```python
@dataclass
class ToolbarState:
    toolbar_card_id: str | None = None
    toolbar_window_id: str | None = None  # to detect stale toolbars
```

#### Global registries

```python
_verbose_states: dict[str, VerboseChannelState] = {}   # channel_id → state
_toolbar_states: dict[str, ToolbarState] = {}         # channel_id → state
_CHANNEL_TURN_KEY = "__channel_turn__"                # reserved key for channel-level turn
```

`get_verbose_state(channel_id)` returns an existing or new `VerboseChannelState`. `get_current_turn_index(channel_id)` returns the channel-level turn index using the reserved `__channel_turn__` key. `advance_turn_index(channel_id)` increments it and resets all streaming card state.

#### Serialization

`to_dict()` / `from_dict()` exist but are not currently used for persistence — `VerboseChannelState` is ephemeral per process. The serialization is present for future use (e.g., a restart-safe verbose mode preference).

#### reset_channel_state vs reset_channel_state_keep_verbose

- `reset_channel_state(channel_id)` — removes all entries from both registries. Used after a full session reset (`#new`).
- `reset_channel_state_keep_verbose(channel_id)` — clears streaming cards, toolbar, and turn state but preserves `_verbose_enabled`. Used when rebinding or recovering a session.

### 3.3 user_preferences.py — UserPreferences

```python
@dataclass
class UserPreferences:
    user_dir_favorites: dict[str, dict[str, list[str]]] = {}   # user_id → {starred: [...], mru: [...]}
    user_window_offsets: dict[str, dict[str, int]] = {}       # user_id → {window_id → offset}
```

The singleton `user_preferences` is loaded and saved by `unified_icc.window_state_store` (via the `WindowStateStore.to_dict()` / `from_dict()` persistence pipeline). It is **not** written directly — `window_store._schedule_save()` triggers a debounced atomic JSON write that includes both window state and user preferences.

#### MRU directories

`update_user_mru(user_id, path)` adds the resolved absolute path to the front of the MRU list, removes duplicates, and caps at 5 entries. MRU directories are shown in the session creation browse phase as `#select <path>` quick-jump commands.

#### Window read offsets

`get_user_window_offset(user_id, window_id)` / `update_user_window_offset(user_id, window_id, offset)` store per-user transcript read offsets. This allows different users sharing a window (e.g., multiple Feishu threads bound to the same tmux window) to track their own read progress. Currently stored but not actively used by the cclark event handlers — present for future multi-user support.

### 3.4 event_parsers.py — FeishuMessageEvent and parse_message_event

```python
@dataclass
class FeishuMessageEvent:
    chat_id: str
    thread_id: str
    user_id: str
    text: str
    message_id: str
    msg_type: str          # "text", "image", "file", "card", ...
    app_name: str = "default"  # set by FeishuWSClient
```

#### Schema compatibility

Feishu's event schema has evolved between versions. `parse_message_event` handles both:

| Field | Schema 1.0 | Schema 2.0 |
|---|---|---|
| Message type | `event.message.msg_type` | `event.message.message_type` |
| Chat ID | `event.chat_id` | `event.message.chat_id` |
| Thread ID | `event.thread_id` | `event.thread_id` |
| Sender open_id | `event.sender.sender_id.open_id` | same |
| Content | `message.content` (JSON string) | same |

The function uses `or` chaining (`message.get("message_type", "") or message.get("msg_type", "")`) to accept both. Non-text messages return `None` and are silently dropped by `_dispatch_event`.

#### Null returns

`parse_message_event` returns `None` for:
- Non-text messages (`msg_type != "text"`)
- Messages with empty or missing text after JSON parsing
- Messages that fail JSON deserialization or field extraction

The caller (`_dispatch_event`) checks `if event is None: return` — no error is surfaced to the user for malformed events.

---

## 4. Data Flow

### 4.1 Multi-app message routing

```
FeishuWSClient receives message for app "admin"
    ↓
_dispatch_event: is_user_allowed_in_app(open_id, "admin")?
    ├── Forbidden → drop silently
    └── Allowed → continue
    ↓
event._app_name = "admin"
    ↓
_message_handler(event)
    ↓
handle_message:
    channel_id = config.parse_channel_id(chat_id, thread_id)
    → "feishu:admin:oc_xxxxx"  (multi-app format)
    ↓
_gateway.send_to_window(window_id, text)
    (gateway uses channel_router to find window)
```

### 4.2 Verbose state across user turns

```
User turn 1:
    handle_message → _advance_channel_turn(channel_id)
        → state.streaming_card_id = None
        → state.streaming_thinking_card_id = None
        → turn_states["__channel_turn__"].last_turn_index = 1
    ↓
gateway.on_message events arrive
    ↓
VerboseCardStreamer.push(text, turn_index=1)
    (turn_index == self._turn_index → append to pending)
    ↓
Debounce fires → send_interactive_card() → state.streaming_card_id = msg_id
    ↓

User turn 2:
    handle_message → _advance_channel_turn(channel_id)
        → state.streaming_card_id = None    ← reset
        → turn_states["__channel_turn__"].last_turn_index = 2
    ↓
...new streaming card created for turn 2...
```

---

## 5. State / Persistence

### 5.1 What is persisted

| Data | Where | Written by |
|---|---|---|
| Channel ↔ window bindings | `~/.cclark/state.json` | `unified_icc.state_persistence` |
| Window metadata (cwd, provider, etc.) | `~/.cclark/window_state_store.json` | `window_store._schedule_save()` |
| Session map (window → session_id) | `~/.cclark/session_map.json` | Claude Code hooks |
| User preferences (MRU, offsets) | Bundled in `window_state_store.json` | `window_store._schedule_save()` |
| App config | `~/.cclark/config.yaml` or `~/.cclark/.env` | Manual (operator) |
| Seen events/messages (dedup) | `~/.cclark/seen_events.json` | `ws_client._save_seen_state()` |

### 5.2 What is ephemeral (in-memory only)

- All `VerboseChannelState` fields (`streaming_card_id`, thinking card, turn index, verbose flag)
- All `ToolbarState` fields
- Handler module globals (`_gateway`, `_adapter`, `_terminal_prompt_states`, `_sessions`)
- WebSocket client state (`_service_id`, `_running`, dedup in-memory sets)

---

## 6. Error Handling

| Situation | Handling |
|---|---|
| `~/.cclark/config.yaml` missing and env vars absent | `ValueError` at import time — process fails fast |
| YAML file has malformed `apps` list | Log warning, skip bad entries, require at least one valid app |
| `allowed_users` contains empty string | Treated as `"all"` (converted to `None`) |
| Invalid `channel_id` in `split_channel_id` | `ValueError` (should not occur in normal operation) |
| `parse_message_event` fails JSON parse | Returns `None`, caller drops the event silently |
| Non-text message received | Returns `None`, caller drops silently |
| `window_state_store` save fails | `logger.warning`, data lost for this cycle |

---

## 7. Design Decisions

### 7.1 Config as a singleton module-level instance

`config = FeishuConfig()` is instantiated at module import time. This avoids the need to pass a config object through every call chain — any module can `from cclark.config import config` and access settings immediately. The downside is that tests must mock `config` or use a test config file.

### 7.2 App-name embedded in channel IDs

In multi-app mode, the channel ID string includes the app name (`feishu:admin:oc_xxxxx`). This means the channel router and all downstream code see a fully-qualified channel ID that encodes the app context. The alternative — passing `(channel_id, app_name)` as a tuple throughout — was rejected because it would require changing the signatures of many gateway and adapter methods.

### 7.3 Heuristic for channel ID parsing

`split_channel_id` distinguishes `feishu:app_name:chat_id` from `feishu:chat_id:thread_id` using a heuristic: Feishu IDs always start with `oc_` or `ou_`. If the second segment starts with either prefix, it is treated as a chat ID. Otherwise it is treated as an app name. This works correctly for all known Feishu ID formats and avoids ambiguity without requiring a separate parsing flag.

### 7.4 Verbose state is not persisted

`_verbose_enabled` is stored in `VerboseChannelState` which is in-memory only. On restart, verbose mode resets to `False`. This is simpler than persisting per-channel preferences and matches the mental model that verbose mode is a temporary preference for the current session. If persistent verbose preference is desired in the future, `VerboseChannelState.to_dict()` / `from_dict()` can be wired to a config file.

### 7.5 User preferences co-located with window state

`UserPreferences` is persisted via `WindowStateStore` rather than as a separate file. Both structures share the same `~/.cclark/window_state_store.json` file, which reduces the number of files to manage and ensures atomic saves cover all per-user and per-window state together.

### 7.6 Event parsing returns None for non-text

Returning `None` from `parse_message_event` for non-text messages (images, files, cards) is intentional — cclark is text-only in the current implementation. Silently dropping non-text messages avoids surfacing errors for legitimate Feishu events. This keeps the error surface small and defers multi-media handling to a future iteration.
