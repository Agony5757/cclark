handlers — Event Handler Modules
================================

Source: src/cclark/handlers/

Five handler modules, each handling a distinct class of inbound event.

handlers/message.py — Inbound Text
------------------------------------

Routes every text message from Feishu. Acts as the traffic controller.

Message flow
~~~~~~~~~~~~

::

   webhook._handle_message → event_parsers.parse_message_event → FeishuMessageEvent
   → handlers/message.py:handle_message(event)
       → text.startswith("/")?
           → _handle_command()  [slash commands]
       → gateway.channel_router.resolve_window(channel_id) → window_id | None
           → window_id is None?
               → _handle_new_channel(event, channel_id)
                   → session_creation.start_session_creation()
           → window_id found?
               → gateway.send_to_window(window_id, text)
                   → tmux send-keys
               → error?
                   → adapter.send_text(channel_id, f"Failed: {err}")

Slash commands
~~~~~~~~~~~~~~~

``/new``, ``/start``
    Start directory browser for new session

``/sessions``
    List active windows via status card

``/help``
    Send help text

``/verbose``
    Toggle verbose streaming mode

``/screenshot``
    Capture and send screenshot

``/toolbar``
    Show toolbar card for active session

handlers/callback.py — Callback Dispatcher
--------------------------------------------

Handles shell approval/denial and session management. Registers catch-all
prefixes only (``noop``, ``cancel``, ``sh:*``, ``sess:*``). All other
prefixes are dispatched from here to sub-handlers via longest-prefix
match in ``callback_registry``.

.. code-block:: python

   @register(SH_RUN)
   async def _shell_approve(ctx: CallbackContext) -> None: ...

   @register(SESSION_KILL)
   async def _session_kill(ctx: CallbackContext) -> None:
       window_id = ctx.value[len(SESSION_KILL):]
       await _gateway.kill_window(window_id)

handlers/session_creation.py — New Session Flow
------------------------------------------------

Implements the multi-step session creation flow: directory browser →
provider picker → mode picker → window creation.

Per-user browse state (``_browse_state[user_id]``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   {
       "path": "/home/user/project",   # current directory
       "page": 0,                       # pagination index
       "channel_id": "feishu:chat:thread",
       "provider": "claude",             # selected provider
       "original_text": "/new",          # triggering message text
   }

Step 1 — Directory browser
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   message.handle_message [unbound channel]
   → session_creation.start_session_creation(event, channel_id)
       → _browse_state[user_id] = {path: home, page: 0, ...}
       → _build_dir_browser_card(home, 0, user_id) → card_json
       → adapter.send_interactive_card(channel_id, card_json)

Button: navigate into subdirectory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   callback value = "db:sel:/home/user/project/src"
   → callback_registry._find_handler("db:sel:") → handle_dir_callback
   → _dec("/home/user/project/src")
   → _browse_state[user_id]["path"] = "/home/user/project/src"
   → _build_dir_browser_card(new_path, 0, user_id)
   → adapter.send_interactive_card(channel_id, card_json)

Button: navigate up
~~~~~~~~~~~~~~~~~~~

::

   callback value = "db:up"
   → handle_dir_callback
   → parent = Path(state["path"]).resolve().parent
   → state["path"] = str(parent)
   → rebuild card

Button: confirm directory
~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   callback value = "db:confirm:/home/user/project"
   → handle_dir_callback
   → user_preferences.update_user_mru(user_id, "/home/user/project")
   → _build_provider_picker_card("/home/user/project") → card_json
   → adapter.send_interactive_card(channel_id, card_json)

Button: select provider
~~~~~~~~~~~~~~~~~~~~~~~

::

   callback value = "prov:claude"
   → callback_registry._find_handler("prov:") → handle_provider_callback
   → state["provider"] = "claude"
   → provider == "shell"? → _create_window(..., "shell", "standard")
   → _build_mode_picker_card(path, "claude") → card_json
   → adapter.send_interactive_card(channel_id, card_json)

Button: select mode → create window
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   callback value = "mode:yolo"
   → callback_registry._find_handler("mode:") → handle_mode_callback
   → mode = "yolo"
   → _create_window(ctx, path, "claude", "yolo")
       → gateway.create_window(path, provider="claude", approval_mode="yolo")
           → TmuxManager.create_window() → tmux new-window
           → return Window object
       → gateway.bind_channel(ctx.channel_id, window_id)
       → gateway.send_to_window(window_id, pending_text)  [if any]
       → adapter.send_text(channel_id, f"Session started: {window_name}")

handlers/toolbar.py — Toolbar Card and Actions
------------------------------------------------

Shows a toolbar card and handles all button clicks.

Toolbar card structure
~~~~~~~~~~~~~~~~~~~~~~

::

   build_toolbar_card(window_id, provider, cfg, status_label)
   → for each row in layout.buttons:
       → for each action_name in row:
           → action = cfg.actions[name]
           → label = action.render(style)  # "🔀 Mode"
           → button value = f"tb:{window_id}:{name}"
   → json.dumps → card_json

Toolbar button dispatch
~~~~~~~~~~~~~~~~~~~~~~~

::

   callback value = "tb:win1:ctrlc"
   → callback_registry → handle_toolbar_callback(ctx)
       → ctx.value[len("tb:"):] = "win1:ctrlc"
       → window_id = "win1", action_name = "ctrlc"
       → gateway.send_key(window_id, key_map["ctrlc"])
           → tmux send-keys -t win1 "\x03"

Built-in action dispatch (``_handle_builtin``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``screenshot``
    ``capture_screenshot`` → ``send_image``

``live``
    ``capture_pane`` → ``send_text``

``dismiss``
    Clear ``toolbar_card_id`` from state

``ctrlc`` / ``send`` / ``enter``
    ``send_key`` with mapped key

handlers/screenshot.py — Pane Capture
--------------------------------------

::

   message._handle_screenshot(channel_id)
   → screenshot.handle_screenshot_request(channel_id, gateway, adapter)
       → gateway.capture_screenshot(window_id)
           → TmuxManager.capture_screenshot(window_id)
               → tmux capture-pane -t {window_id}
               → pyte.Screen + Pillow rendering
       → adapter.send_image(channel_id, screenshot_bytes)
           → FeishuClient.upload_image() → image_key
           → FeishuClient.send_message("image", ...)
