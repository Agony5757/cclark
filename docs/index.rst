cclark 文档
=====================

**cclark** 是 unified-icc 网关的飞书前端。它通过飞书事件长连接接收群聊或话题消息，把文本转发给 unified-icc 管理的 tmux 后端 AI 编程助手，并将输出以文本或交互卡片形式发回飞书。

架构概览::

   飞书群/话题
          │  WebSocket 事件
          ▼
   ┌─────────────────────┐
   │  FeishuWSClient     │  ws_client.py
   └──────────┬──────────┘
              │ FeishuMessageEvent
              ▼
   ┌─────────────────────┐
   │  handlers/message.py│  #help / #new / #status / #verbose
   │  session_creation.py│  #mkdir / provider / mode
   └──────────┬──────────┘
              │ create_window / send_to_window
              ▼
   ┌─────────────────────┐
   │  unified-icc         │  tmux + provider + monitor
   └──────────┬──────────┘
              │ on_message / on_status
              ▼
   ┌─────────────────────┐
   │  FeishuAdapter      │  text / card / screenshot
   └──────────┬──────────┘
              │ REST API
              ▼
         飞书消息

核心能力
-----------------

- **每聊天一会话**：每个飞书聊天绑定一个 cclark 管理的 tmux 窗口，``#new`` 会清理同聊天旧窗口。
- **文本向导**：``#new`` 进入目录 / provider / mode 向导，目录阶段支持 ``#mkdir <name>``。
- **显式帮助**：``#help`` 随时可用；无会话时普通消息返回帮助而不是隐式启动 Claude。
- **详细流式输出**：``#verbose on`` 使用交互卡片展示 regular output 和 thinking output。
- **权限提示桥接**：Claude terminal permission prompt 会显示为飞书卡片，当前通过回复卡片中列出的编号操作。
- **多智能体支持**：Claude Code、Codex、Gemini CLI、Pi、Shell。

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

   mkdir -p ~/.unified-icc
   cp config.yaml.example ~/.unified-icc/config.yaml
   # 填入 app_id / app_secret
   cclark

飞书内发送：

.. code-block:: text

   #help
   #new

相关项目
----------------

.. list-table::
   :header-rows: 1

   * - 项目
     - 说明
   * - unified-icc
     - 核心网关 — tmux 会话、provider、窗口和 transcript 管理
   * - ccgram
     - 原始 Telegram 前端（上游参考）

.. image:: https://img.shields.io/badge/python-3.12%2B-blue
   :target: https://www.python.org/
.. image:: https://img.shields.io/badge/Feishu-API-blue
   :target: https://open.feishu.cn/

索引和表格
------------------

* {ref}`genindex`
* {ref}`modindex`
* {ref}`search`
