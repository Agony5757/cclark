故障排查
============

启动失败
----------------

"FEISHU_APP_ID environment variable is required"
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

当 ``~/.cclark/config.yaml`` 不存在时，配置单例会回退读取环境变量；此时缺少必需环境变量会抛出 ``ValueError``。

**推荐修复**：创建 ``~/.cclark/config.yaml``：

.. code-block:: yaml

   apps:
     - name: "default"
       app_id: "cli_xxxxxxxxxxxxxxxx"
       app_secret: "xxxxxxxxxxxxxxxxxxxxxxxx"
       allowed_users: "all"
       provider: "claude"
       tmux_session: "cclark"
       health_port: 8080

"Cannot find unified-icc"
~~~~~~~~~~~~~~~~~~~~~~~~~~

``pyproject.toml`` 中的依赖路径指向本地源码树。
请先在 ``cclark/`` 目录下运行 ``uv sync``。

"Address already in use" 启动 health endpoint 时
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

端口 8080（或配置中的 ``health_port``）已被占用。

**修复**：设置不同端口：

.. code-block:: bash

   # 在 ~/.cclark/config.yaml 中设置 health_port: 8081
   cclark

飞书 WebSocket 事件
-------------------

飞书未收到事件
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. 确认飞书应用启用了事件订阅并允许通过长连接接收 ``im.message.receive_v1``。
2. 确认 cclark 进程正在运行，且日志显示 WebSocket 已连接。
3. 检查 ``/health`` 是否在本机可访问：

   .. code-block:: bash

      curl http://127.0.0.1:8080/health
      # 应返回：{"status": "ok"}

消息未被处理
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **机器人自身消息**：是否设置了 ``config.bot_user_id``？机器人会跳过自身消息。
- **非文本消息**：目前仅处理 ``msg_type=text``。图片、文件等会被确认但不会处理。
- **用户不在白名单**：``config.is_user_allowed(user_id)`` 返回 False → 静默跳过。

目录浏览器 / 会话创建
--------------------------------------

没有会话时普通消息只返回帮助
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

这是预期行为。发送 ``#new`` 进入目录 / provider / mode 向导；不要依赖首条普通消息自动创建会话。

``#mkdir <name>`` 失败
~~~~~~~~~~~~~~~~~~~~~~

``#mkdir`` 只允许在 ``#new`` 的目录选择阶段创建当前目录下的单个子目录。
绝对路径或 ``nested/path`` 这类嵌套路径会被拒绝；删除目录不由 cclark 提供。

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

权限提示卡片按钮无响应
~~~~~~~~~~~~~~~~~~~~~~~~~~

当前 Claude permission prompt 的飞书卡片按钮回调尚未接入。
看到 ``Claude needs input`` 卡片时，直接回复卡片中列出的编号；选项数量不固定，
cclark 会读取 Claude 当前终端 prompt 中的全部可见编号。

流式卡片不更新
~~~~~~~~~~~~~~~~~~~~~~~~~~~

VerboseCardStreamer 需要已注册的 ``on_message`` 回调。
如果 ``main._register_callbacks`` 静默失败，流式功能不会启动。

检查：``/health`` 是否有响应？网关轮询循环是否在运行？
可用 ``#new`` 命令验证——首条智能体输出后 3 秒内应出现流式卡片。

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
