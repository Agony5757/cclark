webhook — FastAPI Webhook Server
=================================

Source: src/cclark/webhook.py

Runs the FastAPI server that receives Feishu event webhooks. Two endpoints:

- ``GET /health`` — liveness probe
- ``POST /webhook/event`` — Feishu event webhook
- ``POST /webhook/callback`` — card button clicks (same path, distinguished by payload shape)

Module-level registration
-------------------------

Handlers are set via module-level variables so that ``main.py`` can wire them
without circular imports:

.. code-block:: python

   from cclark.webhook import create_app, register_message_handler

   def my_handler(event_dict):
       asyncio.create_task(handle_message(event_dict))

   register_message_handler(my_handler)

   app = create_app(client)  # wires the FastAPI routes

Route flow
----------

::

   FastAPI receives POST request
   ↓ request.json()
   ↓ parse_url_verification(payload)
       → FeishuURLVerificationEvent? → return {"challenge": x} (HTTP 200)
   ↓ is_card_callback(payload)
       → True? → _handle_callback()
       → False? → _handle_message()

``is_card_callback`` checks for the Feishu card callback shape:
``"action" in payload and "value" in payload.get("action", {})``.

``POST /webhook/event`` — message handling
-------------------------------------------

::

   webhook._handle_message(payload)
   → event_parsers.parse_message_event(payload)
       → FeishuMessageEvent | None
       → returns None for non-text messages → silently acknowledge
   → event.user_id == config.bot_user_id?
       → True → skip, return {"status": "ok"}
   → config.is_user_allowed(event.user_id)?
       → False → skip, log, return {"status": "ok"}
   → _message_handler(event)
       → asyncio.create_task(handle_message(event))
   → return {"status": "ok"} immediately

The ``await asyncio.create_task(...)`` is implicit via the handler function
being async — FastAPI ``await``s it. Non-text messages (images, files, etc.)
return ``{"status": "ok"}`` immediately without processing.

``POST /webhook/callback`` — card button clicks
-------------------------------------------------

::

   webhook._handle_callback(payload)
   → event_parsers.parse_callback_event(payload)
       → FeishuCallbackEvent | None
       → returns None? → HTTP 400
   → config.feishu_verification_token set + token mismatch?
       → True → HTTP 403
   → config.parse_channel_id(event.chat_id, event.thread_id)
       → "feishu:chat:thread" or "feishu:chat"
   → CallbackContext(user_id=..., channel_id=..., value=action_value, ...)
   → _callback_handler(ctx)
       → callback_registry.dispatch(ctx)
           → is_user_allowed check
           → _find_handler(longest-prefix match)
           → handler(ctx)
   → return {"status": "ok"}

URL verification
----------------

When Feishu first sets up a webhook URL, it sends a GET/POST with
``{"challenge": "xxx"}``. ``parse_url_verification`` detects this and the
webhook returns ``{"challenge": "xxx"}`` to prove ownership.

``create_app`` signature
------------------------

.. code-block:: python

   def create_app(client: FeishuClient) -> FastAPI:
       ...

The ``client`` parameter is accepted (for completeness) but is not currently
used inside the FastAPI app — the actual FeishuClient is stored in handler
closures registered via ``register_message_handler`` / ``register_callback_handler``.
