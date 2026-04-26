toolbar_config — 工具栏 TOML 加载器
========================================

源码：src/cclark/toolbar_config.py

从 TOML 配置文件加载每个提供方的工具栏按钮布局，
并回退到内置默认值。纯数据 + 加载器——不含消息平台导入。

``ToolbarAction``
-----------------

.. code-block:: python

   @dataclass(frozen=True, slots=True)
   class ToolbarAction:
       name: str           # "screen"、"ctrlc"、"mode"、...
       emoji: str          # "📷"、"⏹"、"🔀"、...
       text: str           # "Screen"、"Ctrl-C"、"Mode"、...
       action_type: Literal["key", "text", "builtin"]
       payload: str       # tmux 按键字符串或文本或内置名称
       literal: bool = False   # 字面值按键 vs 命名按键
       read_state: bool = False # 发送后捕获窗格

三种操作类型：

``key``
    通过 ``send_keys()`` 发送 ``payload`` 为 tmux 按键。
    如果 ``literal=True``，字符串直接发送；否则作为命名按键处理
    （例如 ``"Enter"`` → tmux ``-n Enter``）。

``text``
    发送 ``payload`` 作为字面文本后跟回车。用于斜杠命令如 ``/clear``。

``builtin``
    分发到 ``handlers/toolbar.py`` 中的特殊处理器：
    ``screenshot``、``ctrlc``、``live``、``send``、``dismiss``。

``ToolbarLayout``
-----------------

.. code-block:: python

   @dataclass(frozen=True, slots=True)
   class ToolbarLayout:
       style: ButtonStyle  # "emoji" | "text" | "emoji_text"
       buttons: tuple[tuple[str, ...], ...]  # 行数 × 每行格数

``ToolbarConfig``
-----------------

解析后的配置，包含合并后的操作和每个提供方的布局。

.. code-block:: python

   cfg = load_toolbar_config("/path/to/toolbar.toml")
   layout = cfg.for_provider("claude")
   action = cfg.actions["mode"]

内置操作
-----------------

所有内置操作始终可用（加载到 ``BUILTIN_ACTIONS``）。
用户 TOML 可按名称覆盖它们。

``screen`` — 📷 Screen — ``builtin`` — payload: ``screenshot``

``ctrlc`` — ⏹ Ctrl-C — ``builtin`` — payload: ``ctrlc``

``live`` — 📺 Live — ``builtin`` — payload: ``live``

``send`` — 📤 Send — ``builtin`` — payload: ``send``

``close`` — ✖ Close — ``builtin`` — payload: ``dismiss``

``mode`` — 🔀 Mode — ``key`` — payload: ``\x1b[Z``（Shift-Tab）

``think`` — 💭 Think — ``key`` — payload: ``M-t``（Alt+T）

``yolo`` — 🏆 YOLO — ``key`` — payload: ``C-y``（Ctrl+Y）

``esc`` — ⎋ Esc — ``key`` — payload: ``Escape``

``enter`` — ⏎ Enter — ``key`` — payload: ``Enter``

``tab`` — ⇥ Tab — ``key`` — payload: ``Tab``

``eof`` — ^D EOF — ``key`` — payload: ``C-d``

``susp`` — ^Z Susp — ``key`` — payload: ``C-z``

TOML schema
-----------

.. code-block:: toml

   # 可选：覆盖内置操作
   [actions.mode]
   emoji = "🔄"
   text  = "Mode"
   type  = "key"
   payload = "\\x1b[Z"   # Shift-Tab
   read_state = true

   # 每个提供方的布局覆盖
   [providers.claude]
   style = "emoji_text"  # "emoji" | "text" | "emoji_text"
   buttons = [
     ["screen", "ctrlc", "live"],
     ["mode",   "think", "esc" ],
     ["send",   "enter", "close"],
   ]

默认布局
---------------

五个提供方（claude、codex、gemini、pi、shell）都有内置默认布局。
TOML 中的未知提供方被忽略；缺失的提供方回退到 ``claude`` 布局。

加载序列
~~~~~~~~~~~~~~~~

::

   load_toolbar_config("/path/to/toolbar.toml")
   → cfg = ToolbarConfig(layouts=DEFAULT_LAYOUTS, actions=BUILTIN_ACTIONS)
   → _read_toml(path) → raw dict | None
   → _apply_user_actions(cfg, raw)  # 合并到 cfg.actions
   → _apply_user_layouts(cfg, raw)  # 替换匹配的提供方布局
   → return cfg

调用栈
-----------

渲染工具栏卡片
~~~~~~~~~~~~~~~~~~~~~

::

   toolbar.show_toolbar(channel_id, window_id, adapter)
   → _get_toolbar_config()
       → 全局 _toolbar_config 为 None?
           → load_toolbar_config(config.toolbar_config_path)
               → 返回默认值（无 TOML 文件）
       → return cfg
   → cfg.for_provider("claude")
       → cfg.layouts.get("claude") → ToolbarLayout
   → build_toolbar_card(window_id, "claude", cfg)
       → 对 layout.buttons 中的每行：
           → 对行中每个 name：
               → action = cfg.actions[name]
               → label = action.render(style)  # "emoji_text" → "📷 Screen"
               → button = {"tag": "button", "text": ..., "value": {"action": f"tb:{window_id}:{name}"}}
       → json.dumps → card_json
   → adapter.send_interactive_card(channel_id, card_json)
