# Module: Event Handlers

> `handlers/` — inbound event processing: message routing, session creation wizard, and screenshot capture.

---

## 1. Purpose

The `handlers/` package contains the three primary inbound processing modules:

- **`message.py`** — classifies every inbound Feishu text message: `#` command vs. agent forward vs. terminal prompt reply, and routes to the appropriate handler.
- **`session_creation.py`** — implements the `#new` wizard: text-based directory browser → provider picker → mode picker → `gateway.create_window`.
- **`screenshot.py`** — captures the tmux pane and sends it as a Feishu image.

These handlers are invoked by the WebSocket client via the module-level `register_message_handler` registry. They are stateless aside from the module-level globals set by `main.py` at startup (`_gateway`, `_adapter`).

---

## 2. Architecture

```
FeishuMessageEvent (from ws_client._dispatch_event)
        │
        ▼
handlers/message.handle_message(event)
        │
        ├── #new  ──────────────────────→ _handle_hash_new()
        │                                       │
        ├── #help ──────────────────────→ _handle_help()
        │                                       │
        ├── #screenshot ─────────────────→ _handle_screenshot()
        │                                       │
        ├── #verbose ────────────────────→ _handle_verbose_toggle()
        │                                       │
        ├── #session list|close ────────→ _handle_session_list/_close()
        │                                       │
        ├── #<any> ────────────────────────→ _handle_hash_command()
        │                                       │
        ├── session creation in-progress? ────→ session_creation.handle_session_input()
        │                                       │
        ├── unbound channel ─────────────────→ _handle_new_channel() (help text)
        │                                       │
        ├── terminal prompt reply? ───────────→ _handle_terminal_prompt_reply()
        │     │                                  │
        │     ├── plan option 3 → send "3" (no Enter), await feedback
        │     ├── selection nav  → arrow keys + Enter
        │     └── plain number  → send number + Enter
        │                                       │
        └── agent forward ─────────────────────→ _gateway.send_to_window()
                                                      │
                                                      ▼
                                              unified-icc gateway
```

---

## 3. Key Components

### 3.1 handlers/message.py

#### Global state

```python
_gateway = None   # unified-icc UnifiedCC instance, set by main.py
_adapter = None  # FeishuAdapter instance, set by main.py
_terminal_prompt_states: dict[str, dict[str, str]] = {}
# ^ channel_id → {"type": "plan_decision"|"permission"|"selection",
#                 "phase": "choice"|"awaiting_feedback",
#                 "options": "1,2,3",
#                 "selected": "2"}
```

#### The command routing table

Every `#`-prefixed message is dispatched inside `_handle_hash_command`:

| Command | Handler |
|---|---|
| `#new` | `_handle_hash_new()` — kill session, start wizard |
| `#help` | `_handle_help()` — send help text |
| `#screenshot` | `_handle_screenshot()` — capture and send |
| `#verbose on\|off` | `_handle_verbose_toggle()` — toggle thinking display |
| `#session list` | `_handle_session_list()` — list tmux windows |
| `#session close <id>` | `_handle_session_close()` — kill a tmux window |
| `#mkdir <name>` | inline — "use #new first" error |
| `#new` (global check) | `_handle_hash_new()` (also caught before session_creation) |
| `#help` (global check) | `_handle_help()` (also caught before session_creation) |
| `#<unknown>` | inline error response |

Note: `#new` and `#help` are checked at the top of `handle_message` (before session creation) so they always take precedence over the wizard. A user who sends `#new` while mid-wizard has their existing wizard cancelled and a new one started.

#### Terminal prompt classification

`classify_terminal_prompt(body: str)` inspects text captured from the tmux pane (fed to handlers by the gateway's `on_status` callback) and detects when Claude's TUI is showing an interactive prompt. It returns a state dict for three known prompt types:

- **`plan_decision`**: "Would you like to proceed?" + "Tell Claude what to change". Options include numbered choices; option `3` is the special two-step case.
- **`permission`**: "Do you want to proceed?" / "Allow X to Y". Permission requests from Claude's approval system.
- **`selection`**: "Enter to select" + checkbox/arrow characters. Terminal list selection.

`extract_numbered_prompt_options(body)` uses a regex `^\s*(?:[❯›]\s*)?(\d+)\.\s+(.+?)\s*$` to extract visible numbered choices from the captured pane text. `extract_selected_prompt_option` uses `^\s*[❯›]\s*(\d+)\.\s+` to find the currently cursor-focused option (prefixed with a terminal cursor symbol).

#### Terminal prompt reply handling (`_handle_terminal_prompt_reply`)

When a `text` message arrives on a channel that has an active `_terminal_prompt_states` entry:

1. **plan_decision + phase=choice + text="3"**: sends `"3"` with `enter=False, literal=True, raw=True` (keeps the input field open), transitions phase to `awaiting_feedback`, and sends user guidance. The next message is then treated as feedback text (step 2).
2. **plan_decision + phase=awaiting_feedback**: calls `_advance_channel_turn`, forwards the feedback text as a normal message, clears the state.
3. **selection + digit**: uses `_select_terminal_option_by_navigation` — calculates delta between current cursor position and target option, sends `Up`/`Down` arrow keys then `Enter`.
4. **plain digit** (valid option): sends the digit + `Enter` normally.
5. **plain digit** (invalid option): replies with an error listing valid choices.

#### Turn advancement

`_advance_channel_turn(channel_id)` is called before forwarding any user text to the gateway. It:
1. Finalizes any active `ThinkingCard` (via `finalize_active_thinking_card`) so the thinking placeholder is replaced with the final content before the next turn begins.
2. Calls `state.advance_turn_index(channel_id)`, which resets `streaming_card_id`, `streaming_thinking_card_id`, and increments the turn index. The next gateway event will start a fresh streaming card.

#### `set_handlers(gateway, adapter)`

Called by `main.py` at startup. Sets the module-level `_gateway` and `_adapter` singletons. Importable by other handler modules so they can call the gateway and adapter without circular import problems.

### 3.2 handlers/session_creation.py

#### State machine

```
STATE_BROWSE ──(ok/confirm)──► STATE_PROVIDER ──(provider)──► STATE_MODE ──(mode)──► [window created]
     ▲                                                                      │
     └─────────────────────────(cancel / back)────────────────────────────────┘
```

Each phase is driven entirely by text replies. There are no Feishu card buttons — the wizard uses numbered directory listings and text replies.

#### Per-user state

```python
_sessions: dict[str, dict[str, Any]] = {}
# user_id → {"phase": "browse"|"provider"|"mode",
#             "path": str,
#             "channel_id": str,
#             "original_text": str,
#             "provider": str}
```

#### Directory listing

`_format_dir_listing(path, user_id)` builds the browse card text:
- Header + current path
- MRU directories from `user_preferences.get_user_mru(user_id)` (shown as `#select <path>` commands)
- Subdirectories enumerated 1–20 with numbers
- Available commands: `#select <path>`, `#mkdir <name>`, `..`, `ok`, `cancel`

Input resolution order in `_handle_browse`:
1. `#select <path>` — resolve relative/absolute, navigate directly
2. `#mkdir <name>` — create child directory, switch into it, re-list
3. `ok` / `confirm` / `yes` — accept current dir, advance to provider phase
4. `..` — go to parent (blocked at filesystem root)
5. `cancel` / `quit` / `exit` / `#cancel` — abort wizard
6. Number `N` — enter the N-th subdirectory
7. Name match — case-insensitive directory name match
8. Relative/absolute path — resolve against current dir
9. Not found — error + re-list

`_validate_mkdir_name(name)` enforces single-component, non-absolute names (prevents `mkdir /etc/passwd`).

#### Provider and mode pickers

Provider picker: accepts a number (1–5) or a case-insensitive name match. "shell" skips the mode picker entirely (mode is always "standard").

Mode picker: accepts `1` = standard, `2` = yolo.

#### Window creation (`_create_window`)

```python
async def _create_window(channel_id, user_id, path, provider, approval_mode):
    win = await _gateway.create_window(path, provider=provider, mode=approval_mode)
    _gateway.bind_channel(channel_id, window_id)

    # Record in window_store
    ws = window_store.get_window_state(window_id)
    ws.cwd = path
    ws.provider_name = provider
    ws.approval_mode = "normal" if approval_mode == "standard" else approval_mode
    ws.channel_id = channel_id
    window_store.mark_window_created(window_id)
    window_store._schedule_save()

    # Actively probe session_id immediately
    monitor = get_active_monitor()
    if monitor:
        session_id = await monitor.detect_session_id(window_id)
        if session_id:
            ws.session_id = session_id
            window_store._schedule_save()

    _clear_state(user_id)

    # Forward the original message that triggered #new
    if pending_text:
        await _gateway.send_to_window(window_id, pending_text.strip())
```

`mark_window_created` sets a flag in `window_store` so that the fallback orphan session scanner (which periodically looks for unattached tmux-Claude sessions) does not incorrectly associate an unrelated existing session with this new window.

`detect_session_id` is called immediately after window creation so the `session_id` is available for the first gateway event callback without waiting for the next poll cycle.

#### `start_session_creation(event, channel_id)`

Called by `_handle_hash_new`. Kills any existing bound windows via `_gateway.kill_channel_windows(channel_id)`, warns about orphaned tmux windows that were not killed, resets channel state, then begins the browse phase.

### 3.3 handlers/screenshot.py

```python
async def handle_screenshot_request(channel_id, gateway, adapter):
    window_id = gateway.channel_router.resolve_window(channel_id)
    if window_id is None:
        await adapter.send_text(channel_id, "No active session in this channel.")
        return

    screenshot_bytes = await gateway.capture_screenshot(window_id)
    msg_id = await adapter.send_image(channel_id, screenshot_bytes)
```

The screenshot pipeline is: `gateway.capture_screenshot` → raw PNG bytes → `adapter.send_image` → Feishu `upload_image` → Feishu `send message (type=image)`. No intermediate file is written to disk.

---

## 4. Data Flow

### 4.1 Full `#new` session creation flow

```
User sends "fix the login bug" in a chat with no bound window
    ↓
handle_message → window_id = None → _handle_new_channel
    → "No active session... use #new to start"
    ↓

User sends #new
    ↓
handle_message → global_cmd == "#new" → _handle_hash_new()
    ├── kill_channel_windows(channel_id)
    ├── reset_channel_state(channel_id)
    ├── clear_terminal_prompt_state(channel_id)
    └── start_session_creation(event, channel_id)
        → _get_or_create_state(user_id, channel_id)
        → _adapter.send_text(channel_id, _format_dir_listing(home, user_id))
    ↓

User replies "1" (enter first subdirectory)
    ↓
handle_session_input() returns True (consumed)
    → _handle_browse: number → new_path → state["path"] = new_path
    → _adapter.send_text(channel_id, _format_dir_listing(new_path, user_id))
    ↓

User replies "ok"
    ↓
handle_session_input() returns True
    → state["phase"] = STATE_PROVIDER
    → _adapter.send_text(channel_id, "Select provider: 1. claude 2. codex ...")
    ↓

User replies "1" (claude)
    ↓
handle_session_input() returns True
    → state["provider"] = "claude"
    → state["phase"] = STATE_MODE
    → _adapter.send_text(channel_id, "Select mode: 1. standard 2. yolo")
    ↓

User replies "1" (standard)
    ↓
handle_session_input() returns True
    → _create_window(channel_id, user_id, path, "claude", "standard")
        ├── _gateway.create_window(path, provider="claude", mode="standard")
        ├── _gateway.bind_channel(channel_id, window_id)
        ├── window_store record
        ├── monitor.detect_session_id(window_id)
        ├── _clear_state(user_id)
        └── _adapter.send_text(channel_id, "Session started: ...")
    ↓

_pending_text ("fix the login bug") forwarded to gateway
    ↓
gateway.send_to_window(window_id, "fix the login bug")
    ↓
unified-icc: tmux send-keys
```

### 4.2 Terminal prompt reply — plan option 3

```
Gateway on_status: captured pane contains "Would you like to proceed?"
    ↓
adapter.on_status() calls set_terminal_prompt_state(channel_id, pane_text)
    → state = {"type": "plan_decision", "phase": "choice", "options": "1,2,3"}
    ↓

User sends "3"
    ↓
handle_message → _handle_terminal_prompt_reply
    → state["phase"] == "choice" and text == "3"
    → _gateway.send_input_to_window(window_id, "3", enter=False, literal=True, raw=True)
    → state["phase"] = "awaiting_feedback"
    → _adapter.send_text(channel_id, "Plan option 3 selected. Send the feedback text...")
    ↓

User sends "use pathlib instead of os.path"
    ↓
handle_message → _handle_terminal_prompt_reply
    → state["phase"] == "awaiting_feedback"
    → _advance_channel_turn(channel_id)
    → _gateway.send_to_window(window_id, "use pathlib instead of os.path")
    → clear_terminal_prompt_state(channel_id)
```

---

## 5. State / Persistence

### 5.1 In-memory state

| Variable | Scope | Purpose |
|---|---|---|
| `_gateway` | `handlers/message.py` module | Singleton gateway reference |
| `_adapter` | `handlers/message.py` module | Singleton adapter reference |
| `_terminal_prompt_states` | `handlers/message.py` module | channel_id → prompt classification |
| `_sessions` | `handlers/session_creation.py` module | user_id → wizard state |
| `window_store` | `unified_icc.window_state_store` | Persistent window metadata |

`_sessions` and `_terminal_prompt_states` are intentionally in-memory only — they are lost on restart. A restarted cclark abandons any in-progress wizard or active terminal prompt classification. This is acceptable because the gateway's tmux session is independent of cclark's process.

### 5.2 Persistent state (via unified-icc)

| File | Written by | Purpose |
|---|---|---|
| `~/.cclark/state.json` | `unified_icc.state_persistence` | channel ↔ window bindings |
| `~/.cclark/session_map.json` | Claude Code hooks | window_id → session_id |
| `~/.cclark/window_state_store.json` | `window_store` | per-window metadata (cwd, provider, etc.) |

---

## 6. Error Handling

| Error | Handling |
|---|---|
| `_gateway` is None at message time | Log warning, reply "Gateway not initialized" |
| `gateway.send_to_window` raises | Log exception, reply "Failed to send message to session" |
| `_create_window` raises | Log exception, reply "Failed to create window: {e}" |
| `os.listdir` fails during browse | Return empty list, show "Subdirectories: none" |
| `#mkdir` fails | Reply with error message, stay in browse phase |
| Invalid prompt option digit | Reply listing valid options, do not forward |
| Screenshot capture fails | Reply "Screenshot failed: {e}" |
| Unauthorized user message | Silently drop (no response) |

---

## 7. Design Decisions

### 7.1 Text-based wizard over card buttons

The session creation wizard uses plain text replies rather than Feishu interactive card buttons. This keeps the implementation simple, avoids callback routing complexity, and matches the feel of a CLI. Directory navigation via text is familiar to developers who use CLIs.

### 7.2 `#new` / `#help` take precedence over wizard

A user mid-wizard who sends `#new` or `#help` expects those commands to work immediately. The global command check is placed before the session creation check in `handle_message`.

### 7.3 Plan option 3 two-step flow

Claude Code's plan mode option 3 ("Tell Claude what to change") requires the user to first select option 3 and then type feedback text. If sent as a single Enter keystroke, Claude immediately proceeds with an empty change request. The two-step state machine in `_handle_terminal_prompt_reply` handles this by sending `"3"` without Enter, then waiting for the next message as the feedback text.

### 7.4 Terminal prompt state tracked in-memory

`set_terminal_prompt_state` is called from the adapter's `on_status` callback (driven by the gateway's poll loop reading the tmux pane). The state is kept in a module dict rather than persisted to disk because:
- It is inherently ephemeral (the pane content changes every poll cycle)
- Persisting it would require mapping pane content hashes to state, which is fragile
- On restart, cclark simply re-classifies the next pane snapshot

### 7.5 MRU directory tracking

`user_preferences.update_user_mru` is called when the user confirms a directory with `ok`. The MRU list is stored in `user_preferences` (persisted by `window_state_store`). When the browse phase starts, MRU paths are shown as `#select <path>` quick-jump commands.
