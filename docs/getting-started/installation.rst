安装
=========

环境要求
------------

- Python 3.12+
- tmux（必须已安装并运行）
- 已启用机器人功能的飞书自建应用

从源码安装

.. code-block:: bash

   git clone https://github.com/Agony5757/cclark.git
   cd cclark
   uv sync

``unified-icc`` 依赖直接从其源码树拉取
（``file:///home/agony/projects/unified-icc``），以便两个项目
可以并行开发而无需发布新版本。

将 cclark 安装为 CLI
-----------------------

.. code-block:: bash

   uv pip install -e .
   # 现在可以这样使用：
   cclark run

安装开发依赖

.. code-block:: bash

   uv sync --extra dev
   # 提供：ruff、pytest、pytest-asyncio、pytest-cov

验证安装
-----------------------

.. code-block:: bash

   FEISHU_APP_ID=x FEISHU_APP_SECRET=x ALLOWED_USERS=x FEISHU_BOT_USER_ID=x \
     uv run python -c "from cclark import FeishuClient; print('OK')"

配置飞书机器人
-----------------

1. 前往 `飞书开放平台 <https://open.feishu.cn/>`_ 创建自建应用。
2. 启用**机器人**能力。
3. 在**权限管理**中添加：

   - ``im:message:send_as_bot`` — 发送消息
   - ``im:message:receive_v1`` — 接收事件
   - ``im:message`` — 读取消息

4. 创建**消息事件**订阅，订阅 ``im.message.receive_v1``。
5. 将 Webhook URL 设置为你的服务器，例如 ``https://your-host/webhook/event``。
6. 记录你的**应用 ID**（``cli_xxxx``）和**应用密钥**。

本地开发可使用 `ngrok <https://ngrok.com/>`_ 将本地 Webhook 端口暴露到公网：

.. code-block:: bash

   ngrok http 8080
   # 复制 https:// URL 并填入飞书开放平台

环境变量

必需
~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - 变量
     - 说明
   * - ``FEISHU_APP_ID``
     - 飞书应用 ID（例如 ``cli_xxxx``）
   * - ``FEISHU_APP_SECRET``
     - 飞书应用密钥
   * - ``ALLOWED_USERS``
     - 有权使用机器人的飞书 open_id 或 user_id 列表（逗号分隔）

可选
~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - 变量
     - 说明
   * - ``FEISHU_BOT_USER_ID``
     - 机器人自身的 open_id（用于跳过自身消息）
   * - ``FEISHU_VERIFICATION_TOKEN``
     - 飞书提供的 Webhook 验证令牌
   * - ``FEISHU_ENCRYPT_KEY``
     - 用于事件负载加密的 AES 密钥
   * - ``CCLARK_WEBHOOK_PORT``
     - Webhook 服务器端口（默认：8080）
   * - ``CCLARK_WEBHOOK_PATH``
     - Webhook URL 路径（默认：``/webhook/event``）
   * - ``CCLARK_PROVIDER``
     - 默认智能体提供方（默认：``claude``）
   * - ``CCLARK_TOOLBAR_CONFIG``
     - 工具栏 TOML 配置文件路径

``.env`` 文件
-------------

cclark 从以下 ``.env`` 文件加载环境变量：

1. ``./.env``（仓库根目录）
2. ``~/.cclark/.env``

.. code-block:: text

   FEISHU_APP_ID=cli_xxxx
   FEISHU_APP_SECRET=xxxx
   ALLOWED_USERS=ou_abc123
   FEISHU_BOT_USER_ID=ou_bot
   CCLARK_WEBHOOK_PORT=8080
   CCLARK_PROVIDER=claude
