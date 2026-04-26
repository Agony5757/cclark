cards/streaming — VerboseCardStreamer

Source: src/cclark/cards/streaming.py

Buffers incoming agent output messages and flushes them as Feishu card
updates in 2.5-second debounce windows. One streaming card per channel per
agent turn.

Design goals
------------

1. **One card per turn**: A new turn starts a new card; old cards are not
   edited after the turn advances.
2. **Never gaps**: The card is updated (PATCH) rather than replaced between
   flushes within the same turn, preserving continuity.
3. **Bounded buffering**: Forces a flush after 50 messages or 8000 chars.

``VerboseCardStreamer``
-----------------------

.. code-block:: python

   streamer = VerboseCardStreamer(
       client=feishu_client,
       channel_id="feishu:chat:thread",
       user_id="ou_abc",
       provider="claude",
   )

Key methods
~~~~~~~~~~~

``push(text, turn_index)``
    Add text to buffer; trigger flush on thresholds

``flush()``
    Force immediate flush

``set_turn_index(idx)``
    Signal turn advance → new card on next push

``reset()``
    Clear state (called on unbind)

Flush triggers
~~~~~~~~~~~~~~

A flush is triggered when **any** of these conditions become true:

1. ``len(_pending) >= 50`` — max messages per flush
2. ``_pending_chars >= 8000`` — max characters per flush
3. ``now_ms - _state.last_flush_ms >= 2500`` — time-based debounce

The time-based debounce fires even if the flush is empty (no-op).

State lifecycle
---------------

::

   Streamer created
   → _state = get_verbose_state(channel_id)
   → _turn_index = -1, _pending = []

   First push(segment, turn_index=0)
   → turn_index changed (-1 → 0)
   → _flush() → _pending empty, nothing sent
   → _pending.append(segment)
   → time-based check → _flush()
       → text = "".join(_pending)
       → _build_card(text) → card_json
       → client.send_interactive_card() → msg_id
       → _state.streaming_card_id = msg_id
       → _pending.clear(), _pending_chars = 0

   Subsequent push within same turn
   → turn_index unchanged
   → _pending.append(segment)
   → time check → _flush() → client.patch_message(msg_id, ...)
       → Feishu updates the card in-place

   Turn advances: push(segment, turn_index=1)
   → turn_index changed (0 → 1)
   → _flush() → sends card for turn 0, sets streaming_card_id = None
   → _turn_index = 1, _pending = [segment]
   → next time flush → new card sent via send_interactive_card()

Call stacks
-----------

First message from a new turn
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   gateway emits AgentMessageEvent
   → main.py:on_message(event)
   → streamer.push(event.text, turn_index=event.turn_index)
       → turn_index changed? → _flush()  [clears pending, sends nothing]
       → _pending.append(text)
       → _pending_chars += len(text)
       → len >= 50 or chars >= 8000? → flush
       → now - last_flush >= 2500? → flush
           → _flush()
               → text = "".join(_pending)
               → _build_card(text) → card_json
               → streaming_card_id is None
                   → client.send_interactive_card(channel_id, card_json)
                       → POST /im/v1/messages → msg_id
                   → _state.streaming_card_id = msg_id

Update existing card (same turn)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   gateway emits next AgentMessageEvent
   → streamer.push(next_text, turn_index=0)
       → _pending.append(next_text)
       → time-based → _flush()
           → _state.streaming_card_id is set → patch
           → client.patch_message(msg_id, card_json)
               → PATCH /im/v1/messages/{msg_id}
               → Feishu replaces card content in-place

Streamer reset on session unbind
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   handlers/callback or handlers/message → unbind flow
   → state.reset_channel_state(channel_id)
       → _verbose_states.pop(channel_id)
       → _toolbar_states.pop(channel_id)

Or directly:

::

   VerboseCardStreamer.reset()
   → _pending.clear(), _pending_chars = 0
   → _state.streaming_card_id = None
   → _turn_index = -1
