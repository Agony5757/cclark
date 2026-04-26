cclark 文档
=====================

**cclark** 是 unified-icc 网关的飞书机器人前端。它接收飞书群聊和话题中的消息及卡片按钮点击，转发给由 unified-icc 管理的 tmux 后端 AI 智能体会话，并将智能体输出流式推送回飞书。

架构概览::

   飞书群/话题
          │
          ▼
   ┌─────────────────────┐
   │  FastAPI Webhook    │  webhook.py
   │  POST /webhook/event│  POST /webhook/callback
   └──────────┬──────────┘
              │ 解析 + 分发
              ▼
   ┌─────────────────────┐
   │  事件处理器          │  handlers/
   │  message.py         │  callback.py
   │  session_creation.py│  toolbar.py
   └──────────┬──────────┘
              │ send_to_window / create_window
              ▼
   ┌─────────────────────┐
   │  unified-icc         │  ← tmux
   │  网关                │  ← 智能体会话
   └──────────┬──────────┘
              │ on_message / on_status / on_hook
              ▼
   ┌─────────────────────┐
   │  FeishuAdapter      │  adapter.py
   │  (FrontendAdapter) │  send_text / send_card / send_image
   └──────────┬──────────┘
              │ httpx POST
              ▼
         飞书 REST API

核心能力
-----------------

- **每话题一会话**：每个飞书话题映射一个 tmux 窗口
- **交互卡片**：目录浏览器、提供方选择器、模式选择器、工具栏
- **最长前缀分发**：可扩展的按钮路由，无需硬编码链
- **详细流式输出**：智能体回合期间 2.5 秒防抖卡片更新
- **多智能体支持**：Claude Code、Codex、Gemini CLI、Pi、Shell

.. toctree::
   :maxdepth: 2
   :caption: 目录

   getting-started/index
   architecture
   modules/index
   troubleshooting

快速开始
------------

.. code-block:: bash

   # 设置必需的环境变量
   export FEISHU_APP_ID=cli_xxxx
   export FEISHU_APP_SECRET=xxx
   export ALLOWED_USERS=ou_xxxx
   export FEISHU_BOT_USER_ID=ou_yyyy

   # 运行机器人
   cclark run

   # 或使用 Python
   python -m cclark.main

相关项目
----------------

=============  ===============================================
项目           说明
=============  ===============================================
unified-icc   核心网关 — tmux 会话 + 窗口管理
ccgram        原始 Telegram 前端（上游参考）
=============  ===============================================

.. image:: https://img.shields.io/badge/python-3.12%2B-blue
   :target: https://www.python.org/
.. image:: https://img.shields.io/badge/Feishu-API-blue
   :target: https://open.feishu.cn/

索引和表格
------------------

* {ref}`genindex`
* {ref}`modindex`
* {ref}`search`
