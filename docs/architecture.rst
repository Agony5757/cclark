Architecture
============

cclark is a thin bridge between Feishu and unified-icc. It has four independent
layers, each with a clear input/output contract.

System layers

Layer 1 — Feishu REST API
~~~~~~~~~~~~~~~~~~~~~~~~~~

**In**: Feishu outbound webhook POST requests (JSON)

**Out**: ``FeishuClient`` HTTP calls → Feishu API

``feishu_client.py`` wraps every outbound Feishu API call. It handles
tenant_access_token auto-refresh, JSON encoding, and error normalisation.
It knows nothing about unified-icc or the event system.

Layer 2 — FastAPI Webhook Server
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**In**: ``POST /webhook/event`` and ``POST /webhook/callback``

**Out**: Typed event objects (``FeishuMessageEvent``, ``FeishuCallbackEvent``)

``webhook.py`` runs a FastAPI app. It:

- Handles URL verification challenges
- Parses raw JSON into typed events (``event_parsers.py``)
- Silently acknowledges non-text messages
- Checks user allowlist
- Skips the bot's own messages

Layer 3 — Event Handlers
~~~~~~~~~~~~~~~~~~~~~~~~~

**In**: ``FeishuMessageEvent`` / ``CallbackContext``

**Out**: Calls to unified-icc gateway + FeishuAdapter

Handlers live in ``handlers/``:

Handlers live in ``handlers/``:

* ``message.py`` — Routes inbound text; command dispatch or gateway forward
* ``callback.py`` — Longest-prefix dispatch to sub-handlers
* ``session_creation.py`` — Directory browser, provider picker, window creation
* ``toolbar.py`` — Toolbar card rendering and button click handling
* ``screenshot.py`` — Pane capture → Feishu image upload

Layer 4 — Gateway Callbacks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**In**: ``gateway.on_message()``, ``gateway.on_status()``, ``gateway.on_hook_event()``

**Out**: ``FeishuAdapter`` calls → Feishu messages/cards/images

The gateway polls tmux for transcript changes and emits events. cclark
registers three async callbacks that forward the event to the appropriate
Feishu channel via ``FeishuAdapter``.

Key data flows
--------------

Inbound text (user → agent)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   POST /webhook/event
   → webhook.py:_handle_message()
   → event_parsers.parse_message_event()
   → handlers/message.py:handle_message()
   → gateway.send_to_window(window_id, text)
   → tmux_manager.send_keys()

New session (first message, unbound channel)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   handle_message() [window_id is None]
   → session_creation.start_session_creation()
   → FeishuAdapter.send_interactive_card() [directory browser]
   → user clicks folder buttons
   → callback → handle_dir_callback() [navigate]
   → user clicks Confirm
   → callback → handle_provider_callback() [provider picker]
   → user clicks provider
   → callback → handle_mode_callback() [mode picker]
   → _create_window()
   → gateway.create_window(path, provider, approval_mode)
   → gateway.bind_channel(channel_id, window_id)
   → gateway.send_to_window(window_id, pending_text)

Agent output (agent → user)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   SessionMonitor detects new transcript lines
   → gateway emits AgentMessageEvent
   → main.py:on_message() callback
   → FeishuAdapter.send_text(channel_id, text)

Toolbar button click
~~~~~~~~~~~~~~~~~~~~

::

   POST /webhook/callback
   → webhook.py:_handle_callback()
   → callback_registry.dispatch(ctx)  [longest-prefix match]
   → handlers/toolbar.py:handle_toolbar_callback()
   → gateway.send_key(window_id, payload)  [key type]
   → gateway.send_to_window(window_id, payload)  [text type]
   → _handle_builtin()  [screenshot, live, dismiss, etc.]

State management
-----------------

Per-channel streaming state is kept in ``state.py`` as module-level globals:

.. code-block:: python

   _verbose_states[channel_id]   # VerboseChannelState
   _toolbar_states[channel_id]   # ToolbarState

Per-user browse state during session creation is kept in
``session_creation.py`` as a module-level dict:

.. code-block:: python

   _browse_state[user_id] = {"path": "...", "page": 0, "provider": "claude"}

All state is in-memory only. State is not persisted across restarts (this
behaviour matches ccgram's approach).

Startup sequence
----------------

.. code-block:: text

   main.main() [CLI entry]
   → _main() async
   → FeishuClient(app_id, app_secret)
   → UnifiedICC().start()
   → _register_callbacks()  [gateway event → Feishu]
   → set_handlers(gateway, adapter)
   → register_message_handler / register_callback_handler
   → import handlers.*  [triggers @register decorators]
   → create_app(client)  [FastAPI app]
   → uvicorn.Server.serve()  [webhook listening]
