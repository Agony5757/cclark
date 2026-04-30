# Module: Card Renderers

> Feishu Interactive Card construction: `CardBuilder`, `OutputCard`, `ThinkingCard`, `PromptCard`, `StreamingCard`, and verbose mode control.

---

## 1. Purpose

The `cards/` package builds Feishu Interactive Card JSON payloads for all cclark UI elements. Cards are updated in-place as agent output streams in, providing near-real-time feedback without creating a new message per update.

The package separates two concerns:
- **Static card assembly** (`builder.py`, `output.py`, `prompt.py`) — given a payload, produce the card JSON string.
- **Streaming lifecycle management** (`thinking.py`, `streaming.py`) — given a stream of agent events, manage the creation, incremental patching, and finalization of cards over time.

Verbose mode (`#verbose on|off`) controls whether `ThinkingCard` shows real thinking content or just a placeholder, and whether `VerboseCardStreamer` is active at all.

---

## 2. Architecture

```
unified-icc gateway events (on_message, on_status, on_hook)
        │
        ├── on_status ──→ ThinkingCardStreamer.push_thinking(text, is_complete)
        │                         │
        │                         ├── get_verbose_state(channel_id)._verbose_enabled?
        │                         │   ├── True  → show real thinking + "Generating…" suffix
        │                         │   └── False → placeholder only (🤔 Thinking... / Thinking...OK!)
        │                         │
        │                         ├── card_id is None? → send_interactive_card()
        │                         └── card_id exists? → patch_message()
        │
        ├── on_message ──→ VerboseCardStreamer.push(text, turn_index)
        │                         │
        │                         ├── debounce 2.5 s
        │                         ├── card_id is None? → send_interactive_card()
        │                         └── card_id exists? → patch_message()
        │
        └── user turn ──→ advance_turn_index()
                               ├── finalize_active_thinking_card()
                               └── reset streaming_card_id

Feishu API
  ├── FeishuClient.send_interactive_card()  → POST /im/v1/messages (type=interactive)
  └── FeishuClient.patch_message()         → PATCH /im/v1/messages/{message_id}
```

---

## 3. Key Components

### 3.1 cards/builder.py — FeishuCardBuilder

`FeishuCardBuilder` is a pure static-method class that converts platform-agnostic types (`CardPayload`, `InteractivePrompt`) to Feishu card JSON strings.

#### Markdown-to-Feishu-lite converter (`_md`)

Feishu cards support a limited markdown-like syntax. `_md` performs a minimal round-trip conversion:
- Escapes `&`, `<`, `>` first (so inserted HTML is preserved)
- Converts the first `**...**` pair to `<strong>...</strong>` (handles nested pairs correctly)
- Converts backtick-delimited spans to `<code>...</code>`

Code blocks (triple backticks) are handled separately in `output.py` using raw JSON card elements rather than markdown.

#### Card size limits

`_MAX_CARD_SIZE = 30 * 1024` bytes. `build_card` does not enforce this itself — callers truncate content. `_MAX_CODE_BLOCK = 2000` chars is the enforced limit for code block content; anything longer is truncated with a `... (truncated N chars)` suffix.

#### `build_card(card: CardPayload) -> str`

Elements assembled in order:
1. Body markdown (truncated, converted via `_md`)
2. Fields (key-value pairs rendered as a single `<br>`-separated markdown line with `<strong>` keys)
3. Actions (buttons): each button becomes `{"tag": "button", "text": {...}, "action_type": "interactive"|"default", "value": {...}}`. Buttons that carry an `action` value use `action_type: interactive` so Feishu sends a card callback on click.
4. Header: `{"title": {"tag": "plain_text", ...}, "template": <color>}`

#### `build_prompt_card(prompt: InteractivePrompt) -> str`

Assembles a prompt card with a markdown title and button actions. Each option button's `value` is a JSON-serialized `{"type": prompt_type, "choice": option_value}` string. The cancel button carries `"action": "cancel"`.

### 3.2 cards/output.py

Two helper functions for agent output:

**`build_output_card(title, body, provider, color, actions)`** — thin wrapper around `CardPayload + FeishuCardBuilder.build_card`. Adds a `fields` dict with `{"provider": provider}` when a provider is supplied.

**`build_code_output_card(title, code, language, max_chars=4000)`** — directly builds a Feishu card dict (not using `CardPayload`) with a triple-backtick code block rendered as a raw `"tag": "markdown"` element. This bypasses the `_md` converter (which would mangle triple backticks) and gives clean code block rendering. The card header uses `"wathet"` template color.

### 3.3 cards/thinking.py — ThinkingCardStreamer

`ThinkingCardStreamer` manages the lifecycle of a single channel's thinking card.

#### State

```python
class ThinkingCardStreamer:
    _adapter: FeishuAdapter
    _channel_id: str
    _state: VerboseChannelState   # from cclark.state
    _placeholder_only: bool        # True → only show "🤔 Thinking..." placeholder
```

`_card_id` is a property backed by `self._state.streaming_thinking_card_id`, keeping the card ID synchronized with the shared channel state.

#### `_build_card(text, done)` behavior

| Mode | `done=False` | `done=True` |
|---|---|---|
| `placeholder_only=True` | `"🤔 Thinking..."` | `"🤔 Thinking...OK!"` |
| `placeholder_only=False` | `_truncate(_clean(text))` + `"\n\n⏳ Generating…"` | `_truncate(_clean(text))` |

`_clean` strips the STX (`\x02`) control characters and `EXPQUOTE_START` / `EXPQUOTE_END` markers that Claude Code emits around thinking blocks. `_truncate` caps at 8000 characters.

#### `push_thinking(text, *, is_complete)`

- If `card_id is None`: `send_interactive_card()` → store returned `message_id`
- If `card_id exists` and `is_complete=True`: patch the final content (removes "Generating…" spinner)
- If `card_id exists` and `is_complete=False`: patch with new content + spinner

On API error during patch (`FeishuAPIError`), the streamer falls back to sending a new card. This handles the edge case where Feishu has evicted the original card and the patch fails.

When `is_complete=True`, `streaming_thinking_active` is set to `False` and `streaming_thinking_text` is cleared.

#### `finalize()`

Called by `_advance_channel_turn` before each new user turn. If a thinking card is active, patches it one final time with `done=True` (replaces spinner with "OK!" or final text). This ensures the thinking card reflects the complete result before the output card for the next turn is created.

#### `finalize_active_thinking_card(adapter, channel_id)`

Module-level helper. Looks up `get_verbose_state(channel_id)`, constructs a `ThinkingCardStreamer` with the channel's `placeholder_only` setting, and calls `finalize()`. This is the canonical entry point from `handlers/message._advance_channel_turn`.

### 3.4 cards/prompt.py

#### `build_permission_card(title, body, options, cancel_text)`

Permission cards have an orange header. The body markdown is prepended before the action buttons. Options default to `Approve` / `Deny` if not provided.

#### `build_question_card(title, question, options, cancel_text)`

Multi-choice question cards with a wathet header. The question text is prepended before the button grid.

#### `_prompt_to_card(prompt: InteractivePrompt) -> dict`

Shared card structure builder. Each option button value is encoded as `f"prompt:{prompt_type}:{option_value}"` so the callback handler can reconstruct the prompt context from the button click alone.

### 3.5 cards/streaming.py — VerboseCardStreamer

`VerboseCardStreamer` debounces agent text output into Feishu card patches.

#### State

```python
class VerboseCardStreamer:
    _client: FeishuClient
    _channel_id: str
    _user_id: str
    _provider: str
    _state: VerboseChannelState
    _turn_index: int           # last turn index seen
    _pending: list[str]        # un-flushed text segments
    _pending_chars: int
```

#### Debounce strategy

| Trigger | Action |
|---|---|
| New text arrives | Append to `_pending`, increment `_pending_chars` |
| `_pending` ≥ 50 messages | Force flush |
| `_pending_chars` ≥ 8000 | Force flush |
| Time since last flush ≥ 2500 ms | Flush |
| Turn index changes | Flush before processing new turn |

`_state.last_flush_ms` is updated after every flush so successive messages accumulate correctly across the debounce window.

#### `_flush()`

Joins `_pending` into a single string, builds the card JSON, then:
- If `streaming_card_id` exists → `patch_message()`
- If not → `send_interactive_card()`, store returned `message_id` in `state.streaming_card_id`

On exception, logs and continues (the card update is lost but the process is not disrupted).

#### Turn index awareness

`VerboseCardStreamer.set_turn_index(index)` and the `push(text, turn_index)` parameter both check `turn_index != self._turn_index`. When the turn advances, any pending text is flushed before the new turn's text is accepted. This ensures one streaming card per user turn.

`advance_turn_index(channel_id)` (called from `handlers/message._advance_channel_turn`) clears `state.streaming_card_id` to reset the streamer for the next turn.

#### `reset()`

Clears all pending state. Called when a channel is unbound or the session ends.

---

## 4. Verbose Mode

### 4.1 Per-channel toggle

```python
_verbose_states: dict[str, VerboseChannelState]  # channel_id → state

class VerboseChannelState:
    _verbose_enabled: bool = False  # default off
```

`#verbose on` sets `_verbose_enabled = True`. `#verbose off` sets it to `False`. `#verbose` with no argument toggles.

### 4.2 Effect on card renderers

| Feature | Verbose OFF | Verbose ON |
|---|---|---|
| `ThinkingCardStreamer` | `placeholder_only=True` → "🤔 Thinking..." / "🤔 Thinking...OK!" | `placeholder_only=False` → real thinking text |
| `VerboseCardStreamer` | Inactive (never created) | Active, debounced card patches |
| `VerboseCardStreamer` card header | — | `"🤖 {provider}"` |

### 4.3 Verbose state persistence

`VerboseChannelState` is serializable (`to_dict` / `from_dict`) but the `_verbose_enabled` flag is currently **not** persisted — it resets to `False` on restart. This is a deliberate simplicity choice: verbose mode is a short-lived preference for the current session.

---

## 5. Data Flow

### 5.1 Thinking card full lifecycle

```
Gateway: on_status event with thinking block captured from tmux pane
    ↓
adapter.on_status(event) [or direct call from gateway callback]
    ↓
ThinkingCardStreamer.push_thinking(text, is_complete=False)
    ├── _state.streaming_thinking_text = text
    ├── _build_card(text, done=False)
    │     └── placeholder_only? → show spinner
    ├── card_id is None?
    │     ├── True → send_interactive_card() → _card_id = msg_id
    │     └── False → patch_message()
    └── _state.streaming_thinking_active = True

[more thinking blocks arrive]

Gateway: on_status with is_complete=True
    ↓
ThinkingCardStreamer.push_thinking(text, is_complete=True)
    ├── _build_card(text, done=True)  → removes spinner
    ├── patch_message()
    ├── _state.streaming_thinking_text = ""
    └── _state.streaming_thinking_active = False
```

### 5.2 Verbose streaming card full lifecycle (single turn)

```
User sends message → _advance_channel_turn(channel_id)
    ├── finalize_active_thinking_card(adapter, channel_id)
    └── advance_turn_index(channel_id)
          ├── state.streaming_card_id = None
          └── state.streaming_thinking_* = None/False

Gateway: on_message events stream in (every ~1s poll)
    ↓
VerboseCardStreamer.push(text, turn_index=N)
    ├── turn_index != self._turn_index? → False (N == current)
    ├── append to _pending
    └── debounce timer armed (2.5 s)

[more messages arrive, each resets debounce]

Debounce fires (or max messages/chars hit)
    ↓
VerboseCardStreamer._flush()
    ├── join _pending → text
    ├── _build_card(text)
    ├── streaming_card_id is None?
    │     ├── True → send_interactive_card() → state.streaming_card_id = msg_id
    │     └── False → patch_message()
    └── _pending.clear()

Gateway: Stop hook event (agent turn complete)
    ↓
finalize_streaming_card / advance_turn_index
    → _flush() immediately (no debounce)
    → state.streaming_card_id = None
```

---

## 6. State / Persistence

Cards themselves are persisted by Feishu (message IDs are stable). Client-side card state is ephemeral:

| Field | Stored in | Lost on restart? |
|---|---|---|
| `streaming_card_id` | `VerboseChannelState` (in-memory) | Yes |
| `streaming_thinking_card_id` | `VerboseChannelState` (in-memory) | Yes |
| `streaming_thinking_text` | `VerboseChannelState` (in-memory) | Yes |
| `streaming_thinking_active` | `VerboseChannelState` (in-memory) | Yes |
| `_verbose_enabled` | `VerboseChannelState` (in-memory) | Yes |
| `last_flush_ms` | `VerboseChannelState` (in-memory) | Yes |

On restart, in-flight streaming cards are abandoned. The next user message starts a fresh turn and fresh cards. This is acceptable — Feishu cards are not the source of truth; the tmux transcript is.

---

## 7. Error Handling

| Error | Handling |
|---|---|
| `patch_message` fails on thinking card | Fall back to sending a new card with the current content |
| `patch_message` fails on streaming card | Log exception, drop the update (do not crash the poll loop) |
| `send_interactive_card` fails (new card) | Log exception, the channel has no streaming card for this turn |
| Card content exceeds Feishu size limit | Truncate with `... (truncated N chars)` before building |
| Code block exceeds `_MAX_CODE_BLOCK` | Truncate at 2000 chars in `builder._truncate_code` |

---

## 8. Design Decisions

### 8.1 In-place card updates over new messages per update

Feishu's card update API (`PATCH /im/v1/messages/{message_id}`) allows replacing the card content without sending a new message. cclark uses this to accumulate agent output in a single card per turn. Alternatives considered:
- **New message per update**: creates a long thread of messages, harder to follow.
- **Single message, replace on new turn**: this is what cclark does — the card persists across the turn's output, is patched in-place, and is abandoned when the turn advances.

### 8.2 Separate thinking and output cards

`ThinkingCard` and `VerboseCardStreamer` are separate entities:
- `ThinkingCard` is created when the first thinking block arrives, updated as thinking continues, and finalized (spinner removed) when thinking ends.
- `VerboseCardStreamer` card is created on the first non-thinking output, not on thinking arrival.

This separation allows the thinking card to remain visible and finalized while the output card takes over. When verbose is off, the thinking card is just a placeholder that does not distract.

### 8.3 STX / EXPQUOTE marker stripping

Claude Code emits `\x02` (STX) control characters and `\x02EXPQUOTE_START\x02` / `\x02EXPQUOTE_END\x02` markers around expanded thinking quotes. These are raw terminal control sequences and must not appear in Feishu card content. `_clean()` strips all of them.

### 8.4 FeishuCardBuilder is a static-method class, not a module

`FeishuCardBuilder` holds only static methods and the `_COLOR_MAP` constant. It is instantiated nowhere. Making it a class (rather than a module) groups the related methods under a clear name and allows subclassing or composition if a future frontend needs a variant builder.

### 8.5 No callback wiring for approval buttons

Card button callbacks are not wired in the current implementation. Prompts that require approval use numbered option replies (the user sends a digit) rather than clicking a card button. This avoids the complexity of handling Feishu's card callback webhook and works identically for the user. The prompt card button infrastructure is still built (`build_prompt_card`, `build_permission_card`, etc.) so it can be wired in a future iteration.
