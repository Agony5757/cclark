callback_registry — Longest-Prefix Callback Dispatch
callback_registry — Longest-Prefix Callback Dispatch

Source: src/cclark/callback_registry.py

Self-registering decorator-based dispatch for Feishu card button clicks.
Each handler module registers its own prefixes at import time; the registry
performs longest-prefix matching at runtime.

``@register`` decorator
-----------------------

Handlers use ``@register`` to declare which action-value prefixes they handle:

.. code-block:: python

   from cclark.callback_registry import register, CallbackContext

   @register("db:sel:", "db:up", "db:home")
   async def handle_dir(ctx: CallbackContext) -> None:
       ...

Multiple prefixes can be registered for a single handler (shared handler for
all navigation actions). The same prefix cannot be registered twice.

CallbackContext
---------------

Parsed payload passed to every handler:

.. code-block:: python

   @dataclass
   class CallbackContext:
       user_id: str       # open_id of clicking user
       chat_id: str       # Feishu chat_id
       thread_id: str     # Feishu thread_id (may be "")
       value: str        # raw action value, e.g. "db:sel:/home/user"
       message_id: str    # card message ID
       token: str         # verification token
       channel_id: str    # "feishu:chat:thread" or "feishu:chat"

Longest-prefix matching
-----------------------

When ``dispatch(ctx)`` is called, it finds the registered handler whose prefix
is the longest match for ``ctx.value``:

::

   ctx.value = "db:sel:/home/user/project"
   registered prefixes: "db:sel:", "db:up", "db:"
   "db:sel:" matches (8 chars) ← longest
   → handle_dir_callback(ctx)

Prefixes must be registered at module import time (before ``dispatch`` is first
called). Handler modules are imported by ``main.py``:

.. code-block:: python

   from cclark.handlers import callback, message, session_creation, toolbar
   # → session_creation.py imports callback_registry
   # → @register("db:sel:", ...) decorators fire
   # → _registry dict populated

This deferred import avoids circular dependency issues — the registry
module is loaded early, and individual handler modules register themselves
when imported.

``load_handlers`` function
---------------------------

``callback_registry.load_handlers()`` triggers the import side effects
explicitly. Called by ``main.py`` to ensure handlers are loaded before
serving requests.

Registered prefixes
-------------------

=========================  ====================================================
Prefix                     Handler
=========================  ====================================================
``db:sel:``                ``session_creation.handle_dir_callback``
``db:up``                  ``session_creation.handle_dir_callback``
``db:home``                ``session_creation.handle_dir_callback``
``db:confirm:``            ``session_creation.handle_dir_callback``
``db:star:``               ``session_creation.handle_dir_callback``
``db:pg:``                 ``session_creation.handle_dir_callback``
``prov:``                  ``session_creation.handle_provider_callback``
``mode:``                  ``session_creation.handle_mode_callback``
``tb:``                    ``toolbar.handle_toolbar_callback``
``sh:run:``                ``callback._shell_approve``
``sh:x:``                  ``callback._shell_deny``
``sess:kill:``             ``callback._session_kill``
``sess:show:``             ``callback._session_show``
``noop`` / ``cancel``      ``callback.dispatch`` (catch-all)
=========================  ====================================================

Call stacks
-----------

Toolbar button click → tmux key send
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   POST /webhook/callback
   → webhook._handle_callback()
   → parse_callback_event() → FeishuCallbackEvent(value="tb:win1:ctrlc")
   → CallbackContext(value="tb:win1:ctrlc", ...)
   → callback_registry.dispatch(ctx)
       → _find_handler("tb:")
           → registered prefixes: "tb:",
           → best match: "tb:" (3 chars)
           → return toolbar.handle_toolbar_callback
       → await handle_toolbar_callback(ctx)
           → ctx.value[len("tb:"):] = "win1:ctrlc"
           → parts = "win1:ctrlc".split(":", 1) → ["win1", "ctrlc"]
           → window_id = "win1", action_name = "ctrlc"
           → _get_toolbar_config().actions.get("ctrlc")
               → ToolbarAction(name="ctrlc", action_type="builtin", payload="ctrlc")
           → action_type == "builtin"? → _handle_builtin("ctrlc", ...)
               → "ctrlc" in ("ctrlc", "send", "enter")? → key_map["ctrlc"] = "\x03"
               → gateway.send_key("win1", "\x03")
                   → tmux_manager.send_keys("win1", "\x03")
                   → tmux send-keys -t win1 "\x03"

Provider picker → mode picker card
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   callback value = "prov:claude"
   → dispatch → _find_handler("prov:")
   → handle_provider_callback(ctx)
       → provider = ctx.value[len("prov:"):] = "claude"
       → state["provider"] = "claude"
       → provider == "shell"? → skip mode picker
       → _build_mode_picker_card(path, "claude")
       → adapter.send_interactive_card(channel_id, card_json)
