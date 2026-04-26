main — CLI 入口点
=======================

源码：src/cclark/main.py

``pyproject.toml`` 中定义的 ``cclark`` CLI 脚本：

.. code-block:: toml

   [project.scripts]
   cclark = "cclark.main:main"

也可以这样导入：

.. code-block:: bash

   python -m cclark.main

``main()`` — 同步封装
-------------------------

设置 Windows 事件循环策略并调用 ``asyncio.run(_main())``。

``_main()`` — 异步启动序列
-------------------------------------

第 1 步 — structlog 配置
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   structlog.configure(
       wrapper_class=structlog.make_filtering_bound_logger(
           {"WARNING": ..., "INFO": ...}
       ),
   )

配置 structlog 在生产环境仅记录 WARNING 和 INFO 级别日志。

第 2 步 — 构建核心对象
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   client = FeishuClient(app_config.feishu_app_id, app_config.feishu_app_secret)
   adapter = _build_adapter(client)  → FeishuAdapter(client)

第 3 步 — 启动 unified-icc 网关
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   gateway = UnifiedICC()
   await gateway.start()
   → TmuxManager 连接到 tmux socket
   → SessionMonitor 启动轮询循环
   → StatePersistence 加载 ~/.cclark/state.json

第 4 步 — 注册网关 → 飞书回调
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   _register_callbacks(gateway, adapter)
   → gateway.on_message(on_message)
       → 每次 AgentMessageEvent 到来时调用 on_message
           → channel_ids = channel_router.resolve_channels(event.window_id)
           → adapter.send_text(channel_id, event.text)
           → adapter.send_image(channel_id, event.screenshot_bytes)
   → gateway.on_status(on_status)
       → 状态变化时调用 on_status
           → 解析频道 → build_status_card → adapter.send_card
   → gateway.on_hook_event(on_hook)
       → 钩子事件到来时调用 on_hook（Stop、Input 等）
           → adapter.send_text(channel_id, f"[hook] {hook_name}: {msg}")

第 5 步 — 接入处理器全局变量
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   set_handlers(gateway, adapter)
   → handlers/message._gateway = gateway
   → handlers/message._adapter = adapter
   # → handlers/session_creation._gateway, _adapter（通过 import）
   # → handlers/callback._gateway, _adapter（通过 import）
   # → handlers/toolbar._gateway, _adapter（通过 import）

   register_message_handler(_message_handler)
   → webhook._message_handler = _message_handler

   register_callback_handler(_callback_handler)
   → webhook._callback_handler = _callback_handler

第 6 步 — 导入处理器（触发 @register 装饰器）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   from cclark.handlers import callback, message, screenshot, session_creation, toolbar
   # → 各模块导入 callback_registry
   # → @register(...) 装饰器执行 → _registry 被填充

第 7 步 — 构建 FastAPI 应用
~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   app = create_app(client)
   → FastAPI(title="cclark webhook")
   → 路由：GET /health、POST config.webhook_path

第 8 步 — 启动 uvicorn
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   uvicorn_config = uvicorn.Config(app, host="0.0.0.0", port=app_config.webhook_port)
   server = uvicorn.Server(uvicorn_config)
   await server.serve()
   → FastAPI 监听在 0.0.0.0:8080

信号处理
~~~~~~~~~~~~~

::

   for sig in (SIGTERM, SIGINT):
       loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

   async def shutdown():
       → await gateway.stop()
       → await client.close()

优雅关闭会先保存网关状态并关闭 httpx 客户端，然后退出进程。

环境变量要求
---------------------------------

调用 ``main()`` 前必须设置以下环境变量：

- ``FEISHU_APP_ID``
- ``FEISHU_APP_SECRET``
- ``ALLOWED_USERS``
- ``FEISHU_BOT_USER_ID``

以上全部由 ``cclark.config`` 在导入时加载。导入时的 ``ValueError``
可防止无凭证时机器人启动。

回调中的错误处理
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

每个网关回调（on_message、on_status、on_hook）都将其主体用
``try/except Exception`` 包裹，以防止回调异常导致网关轮询循环崩溃：

.. code-block:: python

   async def on_message(event):
       try:
           ...
       except Exception:
           logger.exception("on_message handler failed")
