安装
=========

环境要求
------------

- Python 3.12+
- tmux（必须已安装并运行）
- 已启用机器人功能的飞书自建应用

从源码安装
------------

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
   cclark

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

4. 启用事件订阅能力并允许应用通过长连接接收 ``im.message.receive_v1``。
5. 记录你的**应用 ID**（``cli_xxxx``）和**应用密钥**。

本项目当前主路径是 WebSocket 长连接，不需要公网 Webhook URL，也不需要 ngrok。

配置文件
------------

首选配置文件是 ``~/.cclark/config.yaml``：

.. code-block:: yaml

   apps:
     - name: "default"
       app_id: "cli_xxxxxxxxxxxxxxxx"
       app_secret: "xxxxxxxxxxxxxxxxxxxxxxxx"
       allowed_users: "all"
       provider: "claude"
       tmux_session: "cclark"
       health_port: 8080

环境变量 ``FEISHU_APP_ID`` / ``FEISHU_APP_SECRET`` 仍可作为单应用开发回退，但不推荐作为常规配置方式。
