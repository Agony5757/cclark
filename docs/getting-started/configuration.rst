Configuration
=============

FeishuConfig singleton

All configuration is loaded from environment variables at import time into a
module-level ``config`` singleton (defined in ``config.py``):

.. code-block:: python

   from cclark.config import config

   config.feishu_app_id       # "cli_xxxx"
   config.feishu_app_secret   # "xxx"
   config.is_user_allowed(id) # True/False
   config.parse_channel_id(chat_id, thread_id)  # "feishu:chat:thread"
   config.split_channel_id("feishu:chat:thread") # ("chat", "thread")

Loading order
~~~~~~~~~~~~~

1. ``FeishuConfig.__init__`` runs at import time
2. ``~/.cclark/`` directory is created if absent
3. ``load_dotenv()`` is called for ``.env`` files (if present)
4. Required env vars (``FEISHU_APP_ID``, ``FEISHU_APP_SECRET``, ``ALLOWED_USERS``)
   are validated; missing ones raise ``ValueError``
5. Optional env vars fall back to defaults

Channel ID model
----------------

cclark uses the same platform-agnostic channel ID format as unified-icc:

.. code-block:: text

   "feishu:{chat_id}"              # non-threaded group chat
   "feishu:{chat_id}:{thread_id}"  # threaded session (1 thread = 1 session)

``parse_channel_id`` and ``split_channel_id`` convert between Feishu's
separate ``chat_id`` / ``thread_id`` fields and the unified channel ID string.

Toolbar TOML config
-------------------

The toolbar layout is loaded from TOML (defaults built in, overridable via file):

.. code-block:: toml

   # ~/.cclark/toolbar.toml
   [providers.claude]
   style = "emoji_text"
   buttons = [
     ["screen", "ctrlc", "live"],
     ["mode",   "think",  "esc" ],
     ["send",   "enter",  "close"],
   ]

See `Toolbar Configuration <../modules/toolbar_config.html>`_ for the full
schema and all available action types.
