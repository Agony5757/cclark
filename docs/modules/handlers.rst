handlers — 事件处理器模块
=================================

源码：src/cclark/handlers/

五个处理器模块，每个处理一类入站事件。

handlers/message.py — 入站文本
-------------------------------------

路由来自飞书的每条文本消息。充当交通指挥官。

消息流程
~~~~~~~~~~~~

::

   webhook._handle_message → event_parsers.parse_message_event → FeishuMessageEvent
   → handlers/message.py:handle_message(event)
       → text.startswith("/")?
           → _handle_command()  [斜杠命令]
       → gateway.channel_router.resolve_window(channel_id) → window_id | None
           → window_id 为 None?
               → _handle_new_channel(event, channel_id)
                   → session_creation.start_session_creation()
           → 找到 window_id?
               → gateway.send_to_window(window_id, text)
                   → tmux send-keys
               → 错误?
                   → adapter.send_text(channel_id, f"Failed: {err}")

斜杠命令
~~~~~~~~~~~~~~~

``/new``、``/start``
    为新会话启动目录浏览器

``/sessions``
    通过状态卡片列出活跃窗口

``/help``
    发送帮助文本

``/verbose``
    切换详细流式模式

``/screenshot``
    捕获并发送截图

``/toolbar``
    为活跃会话显示工具栏卡片

handlers/callback.py — 回调分发器
-----------------------------------------

处理 Shell 批准/拒绝和会话管理。仅注册通配前缀
（``noop``、``cancel``、``sh:*``、``sess:*``）。其他
前缀由此通过 ``callback_registry`` 中的最长前缀匹配分发给子处理器。

.. code-block:: python

   @register(SH_RUN)
   async def _shell_approve(ctx: CallbackContext) -> None: ...

   @register(SESSION_KILL)
   async def _session_kill(ctx: CallbackContext) -> None:
       window_id = ctx.value[len(SESSION_KILL):]
       await _gateway.kill_window(window_id)

handlers/session_creation.py — 新建会话流程
-------------------------------------------------

实现多步会话创建流程：目录浏览器 → 提供方选择器 → 模式选择器 → 窗口创建。

每个用户的浏览状态（``_browse_state[user_id]``）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   {
       "path": "/home/user/project",   # 当前目录
       "page": 0,                     # 分页索引
       "channel_id": "feishu:chat:thread",
       "provider": "claude",           # 选中的提供方
       "original_text": "/new",        # 触发消息文本
   }

第 1 步 — 目录浏览器
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   message.handle_message [未绑定频道]
   → session_creation.start_session_creation(event, channel_id)
       → _browse_state[user_id] = {path: home, page: 0, ...}
       → _build_dir_browser_card(home, 0, user_id) → card_json
       → adapter.send_interactive_card(channel_id, card_json)

按钮：进入子目录
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   callback value = "db:sel:/home/user/project/src"
   → callback_registry._find_handler("db:sel:") → handle_dir_callback
   → _dec("/home/user/project/src")
   → _browse_state[user_id]["path"] = "/home/user/project/src"
   → _build_dir_browser_card(new_path, 0, user_id)
   → adapter.send_interactive_card(channel_id, card_json)

按钮：进入上级目录
~~~~~~~~~~~~~~~~~~~~~~~~~

::

   callback value = "db:up"
   → handle_dir_callback
   → parent = Path(state["path"]).resolve().parent
   → state["path"] = str(parent)
   → 重建卡片

按钮：确认目录
~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   callback value = "db:confirm:/home/user/project"
   → handle_dir_callback
   → user_preferences.update_user_mru(user_id, "/home/user/project")
   → _build_provider_picker_card("/home/user/project") → card_json
   → adapter.send_interactive_card(channel_id, card_json)

按钮：选择提供方
~~~~~~~~~~~~~~~~~~~~~

::

   callback value = "prov:claude"
   → callback_registry._find_handler("prov:") → handle_provider_callback
   → state["provider"] = "claude"
   → provider == "shell"? → _create_window(..., "shell", "standard")
   → _build_mode_picker_card(path, "claude") → card_json
   → adapter.send_interactive_card(channel_id, card_json)

按钮：选择模式 → 创建窗口
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   callback value = "mode:yolo"
   → callback_registry._find_handler("mode:") → handle_mode_callback
   → mode = "yolo"
   → _create_window(ctx, path, "claude", "yolo")
       → gateway.create_window(path, provider="claude", approval_mode="yolo")
           → TmuxManager.create_window() → tmux new-window
           → 返回 Window 对象
       → gateway.bind_channel(ctx.channel_id, window_id)
       → gateway.send_to_window(window_id, pending_text)  [如有]
       → adapter.send_text(channel_id, f"Session started: {window_name}")

handlers/toolbar.py — 工具栏卡片和操作
---------------------------------------------

显示工具栏卡片并处理所有按钮点击。

工具栏卡片结构
~~~~~~~~~~~~~~~~~~~~~

::

   build_toolbar_card(window_id, provider, cfg, status_label)
   → 对 layout.buttons 中的每行：
       → 对每行中每个 action_name：
           → action = cfg.actions[name]
           → label = action.render(style)  # "🔀 Mode"
           → button value = f"tb:{window_id}:{name}"
   → json.dumps → card_json

工具栏按钮分发
~~~~~~~~~~~~~~~~~~~~~

::

   callback value = "tb:win1:ctrlc"
   → callback_registry → handle_toolbar_callback(ctx)
       → ctx.value[len("tb:"):] = "win1:ctrlc"
       → window_id = "win1", action_name = "ctrlc"
       → gateway.send_key(window_id, key_map["ctrlc"])
           → tmux send-keys -t win1 "\x03"

内置操作分发（``_handle_builtin``）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``screenshot``
    ``capture_screenshot`` → ``send_image``

``live``
    ``capture_pane`` → ``send_text``

``dismiss``
    清除状态中的 ``toolbar_card_id``

``ctrlc`` / ``send`` / ``enter``
    用映射的按键调用 ``send_key``

handlers/screenshot.py — 窗格捕获
--------------------------------------

::

   message._handle_screenshot(channel_id)
   → screenshot.handle_screenshot_request(channel_id, gateway, adapter)
       → gateway.capture_screenshot(window_id)
           → TmuxManager.capture_screenshot(window_id)
               → tmux capture-pane -t {window_id}
               → pyte.Screen + Pillow 渲染
       → adapter.send_image(channel_id, screenshot_bytes)
           → FeishuClient.upload_image() → image_key
           → FeishuClient.send_message("image", ...)
