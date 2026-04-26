event_parsers — Feishu JSON → Typed Events
==========================================

Source: src/cclark/event_parsers.py

Converts raw Feishu webhook JSON payloads into typed Python dataclasses.
Three event types:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Type
     - Source
   * - ``FeishuMessageEvent``
     - ``im.message.receive_v1`` event payload
   * - ``FeishuCallbackEvent``
     - Card button click callback payload
   * - ``FeishuURLVerificationEvent``
     - Webhook URL verification challenge

``FeishuMessageEvent``
-----------------------

.. code-block:: python

   @dataclass(frozen=True)
   class FeishuMessageEvent:
       chat_id: str       # "oc_xxxx"
       thread_id: str     # "" for non-threaded chats
       user_id: str       # Feishu open_id of sender
       text: str          # stripped text content
       message_id: str    # for reply threading
       msg_type: str      # "text", "image", etc.

Parsing logic for ``parse_message_event``:

::

   payload = {"event": {"chat_id": "...", "thread_id": "...",
                        "sender": {"sender_id": {"open_id": "..."}},
                        "message": {"msg_type": "text", "message_id": "...",
                                   "content": "{\"text\": \"...\"}"}}}
   ↓ extract event, sender, message
   ↓ msg_type != "text"? → return None  [only handle text]
   ↓ json.loads(content) → {"text": "..."}
   ↓ text = parsed["text"].strip()
   ↓ FeishuMessageEvent(...)
   ↓ any exception → return None

The JSON ``content`` field from Feishu for text messages is itself a JSON
string, hence the double parse.

``FeishuCallbackEvent``
-----------------------

.. code-block:: python

   @dataclass(frozen=True)
   class FeishuCallbackEvent:
       chat_id: str
       user_id: str       # open_id of clicking user
       action_value: str  # "db:sel:/path", "tb:window:mode", etc.
       message_id: str     # card message that was clicked
       token: str         # verification token
       thread_id: str = ""

Parsing logic for ``parse_callback_event``:

::

   payload = {"action": {"value": "{\"action\": \"db:sel:/home/...\"}",
                          "message_id": "..."},
              "chat": {"chat_id": "...", "thread_id": "..."},
              "sender": {"sender_id": {"open_id": "..."}},
              "token": "..."}
   ↓ action["value"] may be str or dict
   ↓ if str → json.loads
   ↓ action_value = value["action"]
   ↓ FeishuCallbackEvent(...)

``is_card_callback``
--------------------

::

   def is_card_callback(payload: dict) -> bool:
       return "action" in payload and "value" in payload.get("action", {})

This distinguishes card callbacks from message events — message events have
``event.message`` but card callbacks have ``action.value``.

Call stacks
------------

Parse a text message event
~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   webhook._handle_message(payload)
   → parse_message_event(payload)
       → payload["event"]["message"]["msg_type"] == "text"?
       → payload["event"]["message"]["content"] = '{"text": "hello"}'
       → json.loads → {"text": "hello"}
       → text = "hello".strip()
       → return FeishuMessageEvent(chat_id=..., user_id=..., text="hello", ...)
   → handle_message(event)  [handlers/message.py]

Parse a card button click
~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   webhook._handle_callback(payload)
   → is_card_callback(payload) → True  [checked before this call]
   → parse_callback_event(payload)
       → payload["action"]["value"] = '{"action": "tb:win1:mode"}'
       → json.loads → {"action": "tb:win1:mode"}
       → action_value = "tb:win1:mode"
       → return FeishuCallbackEvent(value="tb:win1:mode", ...)
   → CallbackContext(...)
   → callback_registry.dispatch(ctx)
       → ctx.value.startswith("tb:")? → True
       → _find_handler("tb:") → toolbar.handle_toolbar_callback
       → await handle_toolbar_callback(ctx)
