cclark Documentation
=====================

**cclark** is a Feishu bot frontend for the unified-icc gateway. It receives messages and card-button clicks from Feishu group chats and threads, forwards them to the tmux-backed AI agent session managed by unified-icc, and streams agent output back to Feishu.

Architecture at a glance::

   Feishu Group/Thread
          │
          ▼
   ┌─────────────────────┐
   │  FastAPI Webhook    │  webhook.py
   │  POST /webhook/event│  POST /webhook/callback
   └──────────┬──────────┘
              │ parse + dispatch
              ▼
   ┌─────────────────────┐
   │  Event Handlers     │  handlers/
   │  message.py         │  callback.py
   │  session_creation.py│  toolbar.py
   └──────────┬──────────┘
              │ send_to_window / create_window
              ▼
   ┌─────────────────────┐
   │  unified-icc        │  ← tmux
   │  Gateway            │  ← agent sessions
   └──────────┬──────────┘
              │ on_message / on_status / on_hook
              ▼
   ┌─────────────────────┐
   │  FeishuAdapter      │  adapter.py
   │  (FrontendAdapter)  │  send_text / send_card / send_image
   └──────────┬──────────┘
              │ httpx POST
              ▼
         Feishu REST API

Key capabilities
-----------------

- **Thread-per-session**: Each Feishu thread maps to one tmux window
- **Interactive cards**: Directory browser, provider picker, mode picker, toolbar
- **Longest-prefix dispatch**: Extensible button routing without hardcoded chains
- **Verbose streaming**: 2.5-second debounced card updates during agent turns
- **Multi-provider**: Claude Code, Codex, Gemini CLI, Pi, Shell

.. toctree::
   :maxdepth: 2
   :caption: Contents

   getting-started/index
   architecture
   modules/index
   troubleshooting

Quick start
------------

.. code-block:: bash

   # Set required env vars
   export FEISHU_APP_ID=cli_xxxx
   export FEISHU_APP_SECRET=xxx
   export ALLOWED_USERS=ou_xxxx
   export FEISHU_BOT_USER_ID=ou_yyyy

   # Run the bot
   cclark run

   # Or with Python
   python -m cclark.main

Related projects
----------------

=============  ===============================================
Project        Description
=============  ===============================================
unified-icc    Core gateway — tmux session + window management
ccgram         Original Telegram frontend (upstream reference)
=============  ===============================================

.. image:: https://img.shields.io/badge/python-3.12%2B-blue
   :target: https://www.python.org/
.. image:: https://img.shields.io/badge/Feishu-API-blue
   :target: https://open.feishu.cn/

Indices and tables
------------------

* {ref}`genindex`
* {ref}`modindex`
* {ref}`search`
