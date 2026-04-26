callback_data — 回调前缀常量
===================================

源码：src/cclark/callback_data.py

定义飞书交互卡片按钮中使用的所有回调 action-value 前缀。
这些常量确保构建器（生成值）和注册表（消费值）之间的字符串匹配一致。

所有常量都是纯 ``str`` 值，同时用于：

1. **作为卡片按钮的 ``value["action"]``**（在 ``cards/`` 构建器中）
2. **作为处理器模块中 ``@register`` 的前缀参数**

前缀参考

目录浏览器（``db:``）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``DB``                    ``"db"``                  通配前缀
``DB_SEL``                ``"db:sel:"``             进入子目录
``DB_UP``                 ``"db:up"``               进入父目录
``DB_HOME``               ``"db:home"``            跳转到主目录
``DB_CONFIRM``            ``"db:confirm:"``        确认目录选择
``DB_TOGGLE_STAR``        ``"db:star:"``            切换目录星标状态

提供方 / 模式（``prov:``、``mode:``）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``PROV``                  ``"prov:"``               提供方通配前缀
``PROV_CLAUDE``           ``"prov:claude"``        提供方特定（字面值）
``PROV_CODEX``            ``"prov:codex"``         提供方特定（字面值）
``PROV_GEMINI``           ``"prov:gemini"``        提供方特定（字面值）
``PROV_PI``               ``"prov:pi"``            提供方特定（字面值）
``PROV_SHELL``            ``"prov:shell"``         提供方特定（字面值）
``MODE``                   ``"mode:"``               模式通配前缀
``MODE_STANDARD``          ``"mode:standard"``      字面值常量
``MODE_YOLO``              ``"mode:yolo"``         字面值常量

工具栏（``tb:``）
~~~~~~~~~~~~~~~~~

``TB``                    ``"tb:"``                 工具栏前缀（``tb:{window}:{action}``）

Shell 审批（``sh:``）
~~~~~~~~~~~~~~~~~~~~~~~~

``SH_RUN``                ``"sh:run:"``            批准 shell 命令
``SH_X``                  ``"sh:x:"``              拒绝 shell 命令

会话 / 可展开引用（``sess:``、``aq:``）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``SESSION_KILL``          ``"sess:kill:"``         关闭窗口
``SESSION_SHOW``          ``"sess:show:"``         显示会话状态卡片
``AQ``                    ``"aq:"``                可展开引用导航

通用
~~~~~~~

``NOOP``                  ``"noop"``                确认但不执行任何操作
``CANCEL``                ``"cancel"``             取消当前流程

示例卡片按钮 JSON（在 cards/ 中生成）
----------------------------------------------

.. code-block:: python

   # 目录确认按钮
   {"action": f"db:confirm:{_enc(selected_path)}"}
   # "db:confirm:/home/user/project"

   # 提供方选择按钮
   {"action": "prov:claude"}

   # 工具栏按钮
   {"action": f"tb:{window_id}:mode"}
   # "tb:emdash-claude-main-abc123:mode"

``db:sel:`` 中的 URL 编码
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``db:sel:{encoded_path}`` 中的子目录路径经过 URL 编码，
以避免与冒号分隔符冲突：

.. code-block:: python

   import urllib.parse
   path = "/home/user/my-project/src"
   action_value = f"db:sel:{urllib.parse.quote(path, safe='')}"
   # "db:sel:%2Fhome%2Fuser%2Fmy-project%2Fsrc"

   # 接收端：
   raw = ctx.value[len("db:sel:"):]
   path = urllib.parse.unquote(raw)
