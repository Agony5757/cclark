Installation

Requirements
------------

- Python 3.12+
- tmux (must be installed and running)
- A Feishu custom app with bot capability enabled

Install from source

.. code-block:: bash

   git clone https://github.com/Agony5757/cclark.git
   cd cclark
   uv sync

The ``unified-icc`` dependency is pulled directly from its source tree
(``file:///home/agony/projects/unified-icc``) so the two projects can be
developed in tandem without releasing new versions.

Install cclark as a CLI
-----------------------

.. code-block:: bash

   uv pip install -e .
   # Now available as:
   cclark run

Install dev dependencies

.. code-block:: bash

   uv sync --extra dev
   # Provides: ruff, pytest, pytest-asyncio, pytest-cov

Verify the installation
-----------------------

.. code-block:: bash

   FEISHU_APP_ID=x FEISHU_APP_SECRET=x ALLOWED_USERS=x FEISHU_BOT_USER_ID=x \
     uv run python -c "from cclark import FeishuClient; print('OK')"

Set up Feishu bot
-----------------

1. Go to `Feishu Open Platform <https://open.feishu.cn/>`_ and create a custom app.
2. Enable **Bot** capability.
3. Under **Permissions**, add:

   - ``im:message:send_as_bot`` — send messages
   - ``im:message:receive_v1`` — receive events
   - ``im:message`` — read messages

4. Create a **Message Event** subscription for ``im.message.receive_v1``.
5. Set the webhook URL to your running server, e.g. ``https://your-host/webhook/event``.
6. Note your **App ID** (``cli_xxxx``) and **App Secret**.

For local development, use `ngrok <https://ngrok.com/>`_ to expose your
local webhook port:

.. code-block:: bash

   ngrok http 8080
   # Copy the https:// URL and set it in Feishu Open Platform

Environment variables

Required
~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Variable
     - Description
   * - ``FEISHU_APP_ID``
     - Feishu app ID (e.g. ``cli_xxxx``)
   * - ``FEISHU_APP_SECRET``
     - Feishu app secret
   * - ``ALLOWED_USERS``
     - Comma-separated Feishu open_ids or user_ids who may use the bot

Optional
~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Variable
     - Description
   * - ``FEISHU_BOT_USER_ID``
     - Bot's own open_id (to skip own messages)
   * - ``FEISHU_VERIFICATION_TOKEN``
     - Webhook verification token from Feishu
   * - ``FEISHU_ENCRYPT_KEY``
     - AES encryption key for event payloads
   * - ``CCLARK_WEBHOOK_PORT``
     - Webhook server port (default: 8080)
   * - ``CCLARK_WEBHOOK_PATH``
     - Webhook URL path (default: ``/webhook/event``)
   * - ``CCLARK_PROVIDER``
     - Default provider (default: ``claude``)
   * - ``CCLARK_TOOLBAR_CONFIG``
     - Path to toolbar TOML config file

``.env`` file
-------------

cclark loads environment variables from ``.env`` files:

1. ``./.env`` (repo root)
2. ``~/.cclark/.env``

.. code-block:: text

   FEISHU_APP_ID=cli_xxxx
   FEISHU_APP_SECRET=xxxx
   ALLOWED_USERS=ou_abc123
   FEISHU_BOT_USER_ID=ou_bot
   CCLARK_WEBHOOK_PORT=8080
   CCLARK_PROVIDER=claude
