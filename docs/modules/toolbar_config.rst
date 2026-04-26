toolbar_config — Toolbar TOML Loader
====================================

Source: src/cclark/toolbar_config.py

Loads per-provider toolbar button layouts from a TOML config file, falling
back to built-in defaults. Pure data + loader — no messaging platform imports.

``ToolbarAction``
-----------------

.. code-block:: python

   @dataclass(frozen=True, slots=True)
   class ToolbarAction:
       name: str           # "screen", "ctrlc", "mode", ...
       emoji: str          # "📷", "⏹", "🔀", ...
       text: str           # "Screen", "Ctrl-C", "Mode", ...
       action_type: Literal["key", "text", "builtin"]
       payload: str       # tmux key string or text or builtin name
       literal: bool = False   # literal key vs. named key
       read_state: bool = False # capture pane after send

Three action types:

``key``
    Sends ``payload`` as a tmux key via ``send_keys()``.
    If ``literal=True``, the string is sent literally; otherwise treated
    as a named key (e.g. ``"Enter"`` → tmux ``-n Enter``).

``text``
    Sends ``payload`` as literal text followed by Enter. Used for slash
    commands like ``/clear``.

``builtin``
    Dispatches to a special handler in ``handlers/toolbar.py``:
    ``screenshot``, ``ctrlc``, ``live``, ``send``, ``dismiss``.

``ToolbarLayout``
-----------------

.. code-block:: python

   @dataclass(frozen=True, slots=True)
   class ToolbarLayout:
       style: ButtonStyle  # "emoji" | "text" | "emoji_text"
       buttons: tuple[tuple[str, ...], ...]  # rows × cells

``ToolbarConfig``
-----------------

Resolved config holding merged actions + per-provider layouts.

.. code-block:: python

   cfg = load_toolbar_config("/path/to/toolbar.toml")
   layout = cfg.for_provider("claude")
   action = cfg.actions["mode"]

Built-in actions
-----------------

All built-in actions are always available (loaded into ``BUILTIN_ACTIONS``).
User TOML may shadow them by name.

``screen`` — 📷 Screen — ``builtin`` — payload: ``screenshot``

``ctrlc`` — ⏹ Ctrl-C — ``builtin`` — payload: ``ctrlc``

``live`` — 📺 Live — ``builtin`` — payload: ``live``

``send`` — 📤 Send — ``builtin`` — payload: ``send``

``close`` — ✖ Close — ``builtin`` — payload: ``dismiss``

``mode`` — 🔀 Mode — ``key`` — payload: ``\x1b[Z`` (Shift-Tab)

``think`` — 💭 Think — ``key`` — payload: ``M-t`` (Alt+T)

``yolo`` — 🏆 YOLO — ``key`` — payload: ``C-y`` (Ctrl+Y)

``esc`` — ⎋ Esc — ``key`` — payload: ``Escape``

``enter`` — ⏎ Enter — ``key`` — payload: ``Enter``

``tab`` — ⇥ Tab — ``key`` — payload: ``Tab``

``eof`` — ^D EOF — ``key`` — payload: ``C-d``

``susp`` — ^Z Susp — ``key`` — payload: ``C-z``

TOML schema
-----------

.. code-block:: toml

   # Optional: override a built-in action
   [actions.mode]
   emoji = "🔄"
   text  = "Mode"
   type  = "key"
   payload = "\\x1b[Z"   # Shift-Tab
   read_state = true

   # Per-provider layout override
   [providers.claude]
   style = "emoji_text"  # "emoji" | "text" | "emoji_text"
   buttons = [
     ["screen", "ctrlc", "live"],
     ["mode",   "think", "esc" ],
     ["send",   "enter", "close"],
   ]

Default layouts
---------------

All five providers (claude, codex, gemini, pi, shell) have built-in default
layouts. Unknown providers in TOML are ignored; missing providers fall back
to the ``claude`` layout.

Loading sequence
~~~~~~~~~~~~~~~~

::

   load_toolbar_config("/path/to/toolbar.toml")
   → cfg = ToolbarConfig(layouts=DEFAULT_LAYOUTS, actions=BUILTIN_ACTIONS)
   → _read_toml(path) → raw dict | None
   → _apply_user_actions(cfg, raw)  # merge into cfg.actions
   → _apply_user_layouts(cfg, raw)  # replace matching provider layouts
   → return cfg

Call stacks
-----------

Render a toolbar card
~~~~~~~~~~~~~~~~~~~~~~

::

   toolbar.show_toolbar(channel_id, window_id, adapter)
   → _get_toolbar_config()
       → global _toolbar_config is None?
           → load_toolbar_config(config.toolbar_config_path)
               → returns defaults (no TOML file)
       → return cfg
   → cfg.for_provider("claude")
       → cfg.layouts.get("claude") → ToolbarLayout
   → build_toolbar_card(window_id, "claude", cfg)
       → for each row_names in layout.buttons:
           → for each name in row_names:
               → action = cfg.actions[name]
               → label = action.render(style)  # "emoji_text" → "📷 Screen"
               → button = {"tag": "button", "text": ..., "value": {"action": f"tb:{window_id}:{name}"}}
       → json.dumps → card_json
   → adapter.send_interactive_card(channel_id, card_json)
