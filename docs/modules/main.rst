main — CLI Entry Point
=======================

Source: src/cclark/main.py

The ``cclark`` CLI script defined in ``pyproject.toml``:

.. code-block:: toml

   [project.scripts]
   cclark = "cclark.main:main"

Also importable as:

.. code-block:: bash

   python -m cclark.main

``main()`` — sync wrapper
-------------------------

Sets the Windows event loop policy and calls ``asyncio.run(_main())``.

``_main()`` — async startup sequence
-------------------------------------

Step 1 — structlog configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   structlog.configure(
       wrapper_class=structlog.make_filtering_bound_logger(
           {"WARNING": ..., "INFO": ...}
       ),
   )

Configures structlog to log WARNING and INFO level only in production.

Step 2 — Build core objects
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   client = FeishuClient(app_config.feishu_app_id, app_config.feishu_app_secret)
   adapter = _build_adapter(client)  → FeishuAdapter(client)

Step 3 — Start unified-icc gateway
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   gateway = UnifiedICC()
   await gateway.start()
   → TmuxManager connects to tmux socket
   → SessionMonitor starts polling loop
   → StatePersistence loads ~/.cclark/state.json

Step 4 — Register gateway → Feishu callbacks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   _register_callbacks(gateway, adapter)
   → gateway.on_message(on_message)
       → on_message called on every AgentMessageEvent
           → channel_ids = channel_router.resolve_channels(event.window_id)
           → adapter.send_text(channel_id, event.text)
           → adapter.send_image(channel_id, event.screenshot_bytes)
   → gateway.on_status(on_status)
       → on_status called on status change
           → resolve channels → build_status_card → adapter.send_card
   → gateway.on_hook_event(on_hook)
       → on_hook called on hook events (Stop, Input, etc.)
           → adapter.send_text(channel_id, f"[hook] {hook_name}: {msg}")

Step 5 — Wire up handler globals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   set_handlers(gateway, adapter)
   → handlers/message._gateway = gateway
   → handlers/message._adapter = adapter
   # → handlers/session_creation._gateway, _adapter (via import)
   # → handlers/callback._gateway, _adapter (via import)
   # → handlers/toolbar._gateway, _adapter (via import)

   register_message_handler(_message_handler)
   → webhook._message_handler = _message_handler

   register_callback_handler(_callback_handler)
   → webhook._callback_handler = _callback_handler

Step 6 — Import handlers (trigger @register decorators)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   from cclark.handlers import callback, message, screenshot, session_creation, toolbar
   # → each module imports callback_registry
   # → @register(...) decorators fire → _registry populated

Step 7 — Build FastAPI app
~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   app = create_app(client)
   → FastAPI(title="cclark webhook")
   → routes: GET /health, POST config.webhook_path

Step 8 — Start uvicorn
~~~~~~~~~~~~~~~~~~~~~~~

::

   uvicorn_config = uvicorn.Config(app, host="0.0.0.0", port=app_config.webhook_port)
   server = uvicorn.Server(uvicorn_config)
   await server.serve()
   → FastAPI listening on 0.0.0.0:8080

Signal handling
~~~~~~~~~~~~~~~

::

   for sig in (SIGTERM, SIGINT):
       loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

   async def shutdown():
       → await gateway.stop()
       → await client.close()

Graceful shutdown stops the gateway (saves state) and closes the httpx client
before the process exits.

Environment variable requirements
---------------------------------

The following env vars must be set before calling ``main()``:

- ``FEISHU_APP_ID``
- ``FEISHU_APP_SECRET``
- ``ALLOWED_USERS``
- ``FEISHU_BOT_USER_ID``

All are loaded by ``cclark.config`` at import time. A ``ValueError`` at import
prevents the bot from starting without credentials.

Error handling in callbacks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every gateway callback (on_message, on_status, on_hook) wraps its body in
``try/except Exception`` to prevent a callback exception from crashing
the gateway's poll loop:

.. code-block:: python

   async def on_message(event):
       try:
           ...
       except Exception:
           logger.exception("on_message handler failed")
