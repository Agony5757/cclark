故障排查
============

启动失败
----------------

"FEISHU_APP_ID environment variable is required"
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

配置单例在导入时如果缺少必需的环境变量会抛出 ``ValueError``。

**修复**：启动前设置所有必需的环境变量：

.. code-block:: bash

   export FEISHU_APP_ID=cli_xxx
   export FEISHU_APP_SECRET=xxx
   export ALLOWED_USERS=ou_xxx
   export FEISHU_BOT_USER_ID=ou_bot
   cclark run

"Cannot find unified-icc"
~~~~~~~~~~~~~~~~~~~~~~~~~~

``pyproject.toml`` 中的依赖路径指向本地源码树。
请先在 ``cclark/`` 目录下运行 ``uv sync``。

"Address already in use" 启动 Webhook 时
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

端口 8080（或 ``$CCLARK_WEBHOOK_PORT``）已被占用。

**修复**：设置不同端口：

.. code-block:: bash

   export CCLARK_WEBHOOK_PORT=8081
   cclark run

飞书 Webhook
---------------

飞书未收到事件
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. **检查 Webhook URL** 是否可公开访问（非 localhost）
2. **本地开发使用 ngrok**：

   .. code-block:: bash

      ngrok http 8080
      # 复制 https:// URL → 飞书开放平台 → 事件订阅

3. 验证 URL 验证挑战是否通过：

   .. code-block:: bash

      curl -X POST https://your-host/webhook/event \
        -H "Content-Type: application/json" \
        -d '{"challenge": "test-challenge"}'
      # 应返回：{"challenge": "test-challenge"}

4. 检查 ``/health`` 是否可从公网访问：

   .. code-block:: bash

      curl https://your-host/health
      # 应返回：{"status": "ok"}

消息未被处理
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **机器人自身消息**：是否设置了 ``config.bot_user_id``？机器人会跳过自身消息。
- **非文本消息**：目前仅处理 ``msg_type=text``。图片、文件等会被确认但不会处理。
- **用户不在白名单**：``config.is_user_allowed(user_id)`` 返回 False → 静默跳过。

目录浏览器 / 会话创建
--------------------------------------

点击文件夹时提示"Directory no longer exists"
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

URL 编码的操作值中的路径已过期（会话重启或目录已删除）。
点击 **Home** 重置到有效目录。

确认目录后会话创建挂起
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

会话创建流程依赖：

1. ``gateway.create_window()`` → tmux new-window 必须成功
2. ``gateway.bind_channel()`` → 频道-窗口映射已保存
3. ``gateway.send_to_window()`` → 文本已管道输入 tmux 窗格

请检查：

- tmux 是否运行中（``tmux list-sessions``）
- 工作目录是否存在且可访问
- 提供方命令（``claude``、``codex`` 等）是否已安装且在 PATH 中

工具栏按钮无响应
~~~~~~~~~~~~~~~~~~~~~~~~~~

- ``tb:`` 回调需要有已绑定的窗口（``channel_router.resolve_window`` 必须返回 window_id）
- 检查网关是否在运行（``gateway.on_message`` 是否已注册）
- ``gateway.send_key()`` 需要 tmux 1.8+

流式卡片不更新
~~~~~~~~~~~~~~~~~~~~~~~~~~~

VerboseCardStreamer 需要已注册的 ``on_message`` 回调。
如果 ``main._register_callbacks`` 静默失败，流式功能不会启动。

检查：``/health`` 是否有响应？网关轮询循环是否在运行？
可用 ``/new`` 命令验证——首条智能体输出后 3 秒内应出现流式卡片。

VerboseCardStreamer 创建重复卡片
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

如果同一回合出现多个流式卡片，可能是 ``_state`` 注册表在两次刷新之间被清除了。
确保 ``reset()`` 仅在取消绑定或会话结束时调用，不在同一会话的回合之间调用。

卡片过大（飞书错误）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

飞书强制每张卡片最大约 30 KB。请减少 ``cards/streaming.py`` 中的 ``_MAX_CHARS_PER_FLUSH``
或在对智能体转录本推送到流式器前截断长输出。

回调注册冲突
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

如果看到 ``ValueError: Callback prefix 'prov:' already registered``，
说明两个模块注册了相同前缀。修复方法：仅在 ``handlers/callback.py`` 中注册通配前缀
（``DB``、``PROV``、``MODE``、``TB``）—— 具体前缀
（``db:sel:``、``prov:claude`` 等）由各子处理器直接注册。

tmux 连接
-------------

"Session 'default' not found"
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

unified-icc 网关要求 tmux 已安装且默认会话存在（或自动创建）。先启动 tmux：

.. code-block:: bash

   tmux new -d -s default
   # 或设置 CCLARK_TMUX_SESSION 为其他会话名

智能体相关
-----------------

"claude command not found"
~~~~~~~~~~~~~~~~~~~~~~~~~~

安装 Claude Code CLI：

.. code-block:: bash

   npm install -g @anthropic-ai/claude-code
   # 或：pip install claude-code

"codex command not found"
~~~~~~~~~~~~~~~~~~~~~~~~~

安装 OpenAI Codex CLI：

.. code-block:: bash

   npm install -g @openai/codex
   # 或：pip install codex

文件上传失败
~~~~~~~~~~~~~~~~~

飞书文件上传需要在应用权限中申请 ``im:file`` 作用域。
检查：飞书开放平台 → 权限管理 → ``im:file``。
