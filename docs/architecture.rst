架构设计
============

cclark 是飞书与 unified-icc 之间的轻量桥接层。它有四个独立层级，
每个层级都有清晰的输入/输出契约。

系统层级

第 1 层 — 飞书 REST API
~~~~~~~~~~~~~~~~~~~~~~~~~~

**输入**：飞书出站 Webhook POST 请求（JSON）

**输出**：``FeishuClient`` HTTP 调用 → 飞书 API

``feishu_client.py`` 封装了所有出站飞书 API 调用。它处理
tenant_access_token 自动刷新、JSON 编码和错误规范化。
它不了解 unified-icc 或事件系统。

第 2 层 — FastAPI Webhook 服务器
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**输入**：``POST /webhook/event`` 和 ``POST /webhook/callback``

**输出**：类型化事件对象（``FeishuMessageEvent``、``FeishuCallbackEvent``）

``webhook.py`` 运行一个 FastAPI 应用。它：

- 处理 URL 验证挑战
- 将原始 JSON 解析为类型化事件（``event_parsers.py``）
- 对非文本消息静默确认
- 检查用户白名单
- 跳过机器人自身消息

第 3 层 — 事件处理器
~~~~~~~~~~~~~~~~~~~~~~~~~

**输入**：``FeishuMessageEvent`` / ``CallbackContext``

**输出**：调用 unified-icc 网关 + FeishuAdapter

处理器位于 ``handlers/``：

* ``message.py`` — 路由入站文本；命令分发或网关转发
* ``callback.py`` — 最长前缀分发到子处理器
* ``session_creation.py`` — 目录浏览器、提供方选择器、窗口创建
* ``toolbar.py`` — 工具栏卡片渲染和按钮点击处理
* ``screenshot.py`` — 窗格截图 → 飞书图片上传

第 4 层 — 网关回调
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**输入**：``gateway.on_message()``、``gateway.on_status()``、``gateway.on_hook_event()``

**输出**：``FeishuAdapter`` 调用 → 飞书消息/卡片/图片

网关轮询 tmux 的转录本变化并发出事件。cclark
注册三个异步回调，将事件通过 ``FeishuAdapter`` 转发到对应的飞书频道。

关键数据流
--------------

入站文本（用户 → 智能体）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   POST /webhook/event
   → webhook.py:_handle_message()
   → event_parsers.parse_message_event()
   → handlers/message.py:handle_message()
   → gateway.send_to_window(window_id, text)
   → tmux_manager.send_keys()

新会话（首条消息，未绑定频道）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   handle_message() [window_id is None]
   → session_creation.start_session_creation()
   → FeishuAdapter.send_interactive_card() [目录浏览器]
   → 用户点击文件夹按钮
   → callback → handle_dir_callback() [导航]
   → 用户点击确认
   → callback → handle_provider_callback() [提供方选择器]
   → 用户点击提供方
   → callback → handle_mode_callback() [模式选择器]
   → _create_window()
   → gateway.create_window(path, provider, approval_mode)
   → gateway.bind_channel(channel_id, window_id)
   → gateway.send_to_window(window_id, pending_text)

智能体输出（智能体 → 用户）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   SessionMonitor 检测到新转录行
   → 网关发出 AgentMessageEvent
   → main.py:on_message() 回调
   → FeishuAdapter.send_text(channel_id, text)

工具栏按钮点击
~~~~~~~~~~~~~~~~~~~~

::

   POST /webhook/callback
   → webhook.py:_handle_callback()
   → callback_registry.dispatch(ctx)  [最长前缀匹配]
   → handlers/toolbar.py:handle_toolbar_callback()
   → gateway.send_key(window_id, payload)  [key 类型]
   → gateway.send_to_window(window_id, payload)  [text 类型]
   → _handle_builtin()  [截图、live、dismiss 等]

状态管理
-----------------

每个频道的流式状态保存在 ``state.py`` 的模块级全局变量中：

.. code-block:: python

   _verbose_states[channel_id]   # VerboseChannelState
   _toolbar_states[channel_id]   # ToolbarState

会话创建期间每个用户的浏览状态保存在
``session_creation.py`` 的模块级字典中：

.. code-block:: python

   _browse_state[user_id] = {"path": "...", "page": 0, "provider": "claude"}

所有状态仅存于内存。重启后状态不持久化（此行为与 ccgram 一致）。

启动顺序
----------------

.. code-block:: text

   main.main() [CLI 入口]
   → _main() 异步
   → FeishuClient(app_id, app_secret)
   → UnifiedICC().start()
   → _register_callbacks()  [网关事件 → 飞书]
   → set_handlers(gateway, adapter)
   → register_message_handler / register_callback_handler
   → import handlers.*  [触发 @register 装饰器]
   → create_app(client)  [FastAPI 应用]
   → uvicorn.Server.serve()  [webhook 监听]
