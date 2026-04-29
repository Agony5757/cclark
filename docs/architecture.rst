架构设计
============

cclark 是飞书与 unified-icc 之间的轻量桥接层。飞书事件入口使用 WebSocket 长连接；HTTP 服务只保留 health endpoint。

系统层级
------------

第 1 层 — 飞书 WebSocket 事件
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**输入**：飞书事件服务器推送的 ``im.message.receive_v1``。

**输出**：``FeishuMessageEvent``。

``ws_client.py`` 负责连接飞书事件服务器、过滤非文本消息、跳过机器人自身消息、检查用户白名单，并把消息交给 handler。

第 2 层 — 事件处理器
~~~~~~~~~~~~~~~~~~~~

**输入**：``FeishuMessageEvent``。

**输出**：调用 unified-icc 网关或 ``FeishuAdapter``。

关键 handler：

* ``message.py`` — 处理 ``#`` 命令、无会话帮助、普通文本转发。
* ``session_creation.py`` — ``#new`` 的目录 / provider / mode 向导，目录阶段支持 ``#mkdir <name>``。
* ``screenshot.py`` — 截图当前 tmux pane 并上传飞书。

第 3 层 — unified-icc 网关
~~~~~~~~~~~~~~~~~~~~~~~~~~

**输入**：``create_window``、``send_to_window``、``send_key`` 等调用。

**输出**：``AgentMessageEvent``、``StatusEvent``、hook event。

unified-icc 管理 tmux window、provider 启动命令、Claude transcript 监控、session id 探测、channel routing 和 startup cleanup。

第 4 层 — 飞书 REST API
~~~~~~~~~~~~~~~~~~~~~~~

**输入**：文本、交互卡片、图片上传请求。

**输出**：飞书消息。

``feishu_client.py`` 负责 tenant access token、消息发送、卡片 patch、文件上传和错误规范化。

关键数据流
--------------

普通消息
~~~~~~~~

::

   FeishuWSClient
   → event_parsers.parse_message_event()
   → handlers.message.handle_message()
   → gateway.channel_router.resolve_window(channel_id)
   → gateway.send_to_window(window_id, text)
   → tmux pane

无会话消息
~~~~~~~~~~

::

   handle_message()
   → no bound window
   → FeishuAdapter.send_text("#help guidance")

无会话时不会隐式创建 Claude；用户必须发送 ``#new``。

新会话
~~~~~~

::

   #new
   → kill_channel_windows(channel_id)
   → list_orphaned_agent_windows()
   → session_creation.start_session_creation()
   → directory selection
   → optional #mkdir <name>
   → provider selection
   → standard/yolo mode selection
   → gateway.create_window(path, provider, mode)
   → gateway.bind_channel(channel_id, window_id)
   → SessionMonitor.detect_session_id()
   → window_store persists session_id

智能体输出
~~~~~~~~~~

::

   SessionMonitor reads transcript / terminal status
   → gateway emits AgentMessageEvent or StatusEvent
   → main.py callback
   → thinking card / verbose card / plain text / prompt card
   → Feishu REST API

状态和持久化
--------------

- ``~/.cclark/config.yaml`` 是主配置文件。
- ``~/.cclark/state.json`` 保存窗口状态、channel bindings、verbose 状态等。
- unified-icc 的 ``window_store`` 记录 cclark 创建的 tmux windows，用于 startup cleanup 和 fallback transcript tracking。
- ``#new`` 只自动清理 cclark 能证明属于当前 Feishu chat 的 managed windows；发现 orphaned Claude windows 时只提示 Warning。

权限模式
------------

- ``standard`` 在 cclark 中映射到 unified-icc ``normal``。
- Claude normal launch 显式使用 ``claude --permission-mode default``。
- 只有 ``yolo`` 使用 Claude 的危险跳过权限模式。
- 当前 Feishu approval button callback 未接入；Claude permission prompt 通过 terminal status 桥接成卡片后，用户回复 ``1`` / ``2`` / ``3`` 完成选择。

启动顺序
------------

::

   main.main()
   → load ~/.cclark/config.yaml
   → FeishuClient(app_id, app_secret)
   → FeishuAdapter(client)
   → UnifiedICC().start()
   → register gateway callbacks
   → set_handlers(gateway, adapter)
   → start FeishuWSClient
   → serve local /health endpoint

