config — 配置单例
=================================

源码：src/cclark/config.py

从环境变量加载飞书凭证、授权设置和 Webhook 参数。在导入时实例化为模块级 ``config`` 单例。

``FeishuConfig``

.. code-block:: python

   from cclark.config import config

   # 必需字段（缺失则抛出 ValueError）
   config.feishu_app_id
   config.feishu_app_secret
   config.allowed_users        # set[str]

   # 可选字段
   config.feishu_verification_token
   config.feishu_encrypt_key
   config.webhook_port         # 默认 8080
   config.webhook_path          # 默认 "/webhook/event"
   config.bot_user_id           # 跳过自身消息
   config.default_provider      # 默认 "claude"
   config.toolbar_config_path   # TOML 工具栏配置

关键方法
-----------

.. code-block:: python

   # 检查用户是否在白名单中
   config.is_user_allowed("ou_abc123")  # True/False

   # 飞书 ID → 统一频道 ID
   config.parse_channel_id("chat_123", "thread_456")
   # → "feishu:chat_123:thread_456"

   # 解析频道 ID 为飞书 ID
   config.split_channel_id("feishu:chat_123:thread_456")
   # → ("chat_123", "thread_456")

频道 ID 格式
-----------------

cclark 使用与 unified-icc 相同的频道 ID 格式，以保证两层间频道路由一致：

.. code-block:: text

   feishu:{chat_id}           # 非话题聊天
   feishu:{chat_id}:{thread_id}  # 话题（1 话题 = 1 会话）

加载序列
~~~~~~~~~~~~~~~~

::

   import cclark.config
       → FeishuConfig.__init__()
           → config_dir = Path.home() / ".cclark"
           → config_dir.mkdir(parents=True, exist_ok=True)
           → load_dotenv(Path(".env"))
           → load_dotenv(config_dir / ".env")
           → os.getenv("FEISHU_APP_ID") → 如为空则 ValueError
           → os.getenv("FEISHU_APP_SECRET") → 如为空则 ValueError
           → os.getenv("ALLOWED_USERS") → 如为空则 ValueError
           → 解析为逗号分隔的 open_id 集合
           → 用默认值获取所有可选环境变量

导入时抛出 ``ValueError`` 意味着机器人在凭证缺失时会快速失败，
而不是在运行时才失败。

``.env`` 查找顺序
~~~~~~~~~~~~~~~~~~~~~~~~

1. ``./.env``（导入时的当前工作目录）
2. ``~/.cclark/.env``

顺序意味着先尝试仓库级 ``.env``，再尝试用户持久化配置目录——
符合标准 Python 模式。
