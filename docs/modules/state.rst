state — Streaming and Toolbar State
===================================

Source: src/cclark/state.py

Module-level global registries for per-channel streaming state and toolbar
state. Not persisted across restarts (in-memory only).

``VerboseChannelState``
-----------------------

Tracks the active streaming card and turn progress for one Feishu channel:

.. code-block:: python

   @dataclass
   class VerboseChannelState:
       streaming_card_id: str | None  # message_id of the live card
       last_flush_ms: float          # monotonic timestamp of last flush
       turn_states: dict[str, VerboseTurnState]  # keyed by user_id

``VerboseTurnState`` (nested)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   @dataclass
   class VerboseTurnState:
       last_turn_index: int  # highest turn_index user has seen
       pending_text: str      # text accumulated since last flush

``ToolbarState``
----------------

.. code-block:: python

   @dataclass
   class ToolbarState:
       toolbar_card_id: str | None   # message_id of displayed toolbar
       toolbar_window_id: str | None # window the toolbar is attached to

Global registry accessors
-------------------------

::

   _verbose_states: dict[str, VerboseChannelState]  # keyed by channel_id
   _toolbar_states: dict[str, ToolbarState]        # keyed by channel_id

   get_verbose_state(channel_id) → VerboseChannelState
   get_toolbar_state(channel_id) → ToolbarState
   reset_channel_state(channel_id)  # clears both on unbind

Persistence
-----------

This module is **not persisted**. Streaming and toolbar state are rebuilt
from the gateway events after a restart. The ``VerboseCardStreamer`` in
``cards/streaming.py`` is the primary consumer.

The VerboseCardStreamer uses ``get_verbose_state`` to:

1. Check if a streaming card already exists (``streaming_card_id``)
2. Patch it on subsequent flushes rather than creating new cards
3. Store the last flush timestamp for debounce calculations

Call stacks
-----------

Streaming card — first flush (new card)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   VerboseCardStreamer.push("hello", turn_index=0)
   → turn_index changed? → _flush()
       → _pending = ["hello"]
       → _pending_chars = 5
       → self._state.last_flush_ms = now
       → _build_card("hello") → card_json
       → client.send_interactive_card(channel_id, card_json)
           → POST /im/v1/messages → message_id = "om_xxx"
       → self._state.streaming_card_id = "om_xxx"

Streaming card — second flush (patch)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   VerboseCardStreamer.push(" world", turn_index=0)
   → _pending = ["hello", " world"], _pending_chars += 6
   → _flush() called by interval
       → text = "hello world"
       → _state.streaming_card_id already set
       → client.patch_message("om_xxx", card_json)
           → PATCH /im/v1/messages/om_xxx → updates card

New turn — new streaming card
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   VerboseCardStreamer.push("next turn", turn_index=1)
   → turn_index changed (0 → 1)
   → _flush() → sends "hello world" in one card
   → self._state.streaming_card_id = None  [_flush() resets it]
   → self._turn_index = 1
   → push appends to new _pending
   → _flush() → client.send_interactive_card() → new message_id

Toolbar update (patch existing toolbar)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   toolbar.show_toolbar(channel_id, window_id, adapter)
   → get_toolbar_state(channel_id) → ToolbarState(...)
   → toolbar_state.toolbar_card_id already set?
       → client.patch_message(card_id, card_json)
           → toolbar card updated in-place
   → else: adapter.send_interactive_card(...) → toolbar_card_id stored
