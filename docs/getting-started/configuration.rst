配置参考
=============

配置来源
-------------

cclark 首选从 ``~/.cclark/config.yaml`` 加载配置；只有当该文件不存在时，才使用环境变量作为单应用开发回退。

.. code-block:: yaml

   apps:
     - name: "default"
       app_id: "cli_xxxxxxxxxxxxxxxx"
       app_secret: "xxxxxxxxxxxxxxxxxxxxxxxx"
       allowed_users: "all"
       provider: "claude"
       tmux_session: "cclark"
       health_port: 8080

字段含义：

- ``name``：应用名称，用于多应用路由。
- ``app_id``：飞书应用 ID。
- ``app_secret``：飞书应用密钥。
- ``allowed_users``：``"all"`` 或逗号分隔的 open_id 列表。
- ``provider``：默认 provider，例如 ``claude``。
- ``tmux_session``：cclark 管理的 tmux session 名。
- ``health_port``：本地 health endpoint 端口。

FeishuConfig 单例
------------------

模块级 ``config`` 单例定义于 ``config.py``：

.. code-block:: python

   from cclark.config import config

   config.feishu_app_id       # "cli_xxxx"
   config.feishu_app_secret   # "xxx"
   config.is_user_allowed(id) # True/False
   config.parse_channel_id(chat_id, thread_id)  # "feishu:chat:thread"
   config.split_channel_id("feishu:chat:thread") # ("chat", "thread")

加载顺序
~~~~~~~~~~~~

1. ``FeishuConfig.__init__`` 在导入时运行
2. 创建 ``~/.cclark/`` 目录（如不存在）
3. 如果 ``~/.cclark/config.yaml`` 存在，则加载其中的 ``apps`` 列表
4. 如果配置文件不存在，则读取环境变量 ``FEISHU_APP_ID`` / ``FEISHU_APP_SECRET`` / ``ALLOWED_USERS``
5. 可选字段使用默认值

频道 ID 模型
----------------

cclark 使用与 unified-icc 相同的平台无关频道 ID 格式：

.. code-block:: text

   "feishu:{chat_id}"              # 非话题群聊
   "feishu:{chat_id}:{thread_id}"  # 话题会话（1 话题 = 1 会话）

``parse_channel_id`` 和 ``split_channel_id`` 在飞书的
分离 ``chat_id`` / ``thread_id`` 字段与统一频道 ID 字符串之间相互转换。

工具栏 TOML 配置
-------------------

工具栏布局从 TOML 加载（内置默认值，可通过文件覆盖）：

.. code-block:: toml

   # ~/.cclark/toolbar.toml
   [providers.claude]
   style = "emoji_text"
   buttons = [
     ["screen", "ctrlc", "live"],
     ["mode",   "think",  "esc" ],
     ["send",   "enter",  "close"],
   ]

完整的 schema 和所有可用的操作类型见 `工具栏配置 <../modules/toolbar_config.html>`_。
