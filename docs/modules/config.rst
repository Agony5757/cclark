config — 配置单例
=================================

源码：src/cclark/config.py

cclark 首选从 ``~/.cclark/config.yaml`` 加载配置，并在该文件不存在时回退到环境变量。
导入时实例化为模块级 ``config`` 单例。

配置文件
------------

.. code-block:: yaml

   apps:
     - name: "default"
       app_id: "cli_xxxxxxxxxxxxxxxx"
       app_secret: "xxxxxxxxxxxxxxxxxxxxxxxx"
       allowed_users: "all"
       provider: "claude"
       tmux_session: "cclark"
       health_port: 8080

关键字段
------------

.. code-block:: python

   from cclark.config import config

   config.feishu_app_id
   config.feishu_app_secret
   config.allowed_users
   config.default_provider
   config.tmux_session
   config.health_port

关键方法
-----------

.. code-block:: python

   config.is_user_allowed("ou_abc123")
   config.parse_channel_id("chat_123", "thread_456")
   config.split_channel_id("feishu:chat_123:thread_456")

频道 ID 格式
-----------------

.. code-block:: text

   feishu:{chat_id}
   feishu:{chat_id}:{thread_id}

加载序列
------------

1. 创建 ``~/.cclark``。
2. 如果 ``~/.cclark/config.yaml`` 存在，加载 ``apps``。
3. 如果配置文件不存在，读取 ``FEISHU_APP_ID`` / ``FEISHU_APP_SECRET`` / ``ALLOWED_USERS``。
4. 根据 app 配置选择 provider、tmux session 和 health port。

环境变量回退仅用于单应用开发；常规部署应使用 ``config.yaml``。

