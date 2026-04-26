config — Configuration Singleton
================================

Source: src/cclark/config.py

Loads Feishu credentials, authorization settings, and webhook parameters
from environment variables. Instantiated as the module-level ``config`` singleton
at import time.

``FeishuConfig``
``FeishuConfig``

.. code-block:: python

   from cclark.config import config

   # Required fields (raise ValueError if missing)
   config.feishu_app_id
   config.feishu_app_secret
   config.allowed_users        # set[str]

   # Optional fields
   config.feishu_verification_token
   config.feishu_encrypt_key
   config.webhook_port         # default 8080
   config.webhook_path          # default "/webhook/event"
   config.bot_user_id           # skip own messages
   config.default_provider      # default "claude"
   config.toolbar_config_path   # TOML toolbar config

Key methods
-----------

.. code-block:: python

   # Check if a user is on the allowlist
   config.is_user_allowed("ou_abc123")  # True/False

   # Convert Feishu IDs → unified channel ID
   config.parse_channel_id("chat_123", "thread_456")
   # → "feishu:chat_123:thread_456"

   # Parse channel ID back to Feishu IDs
   config.split_channel_id("feishu:chat_123:thread_456")
   # → ("chat_123", "thread_456")

Channel ID format
-----------------

cclark uses the same channel ID format as unified-icc so that channel
routing is consistent across both layers:

.. code-block:: text

   feishu:{chat_id}           # non-threaded chat
   feishu:{chat_id}:{thread_id}  # thread (1 thread = 1 session)

Loading sequence
~~~~~~~~~~~~~~~~

::

   import cclark.config
       → FeishuConfig.__init__()
           → config_dir = Path.home() / ".cclark"
           → config_dir.mkdir(parents=True, exist_ok=True)
           → load_dotenv(Path(".env"))
           → load_dotenv(config_dir / ".env")
           → os.getenv("FEISHU_APP_ID") → ValueError if empty
           → os.getenv("FEISHU_APP_SECRET") → ValueError if empty
           → os.getenv("ALLOWED_USERS") → ValueError if empty
           → parse as set of comma-separated open_ids
           → os.getenv for all optional vars with defaults

The ``ValueError`` at import time means the bot will fail fast if
credentials are missing rather than failing at runtime.

``.env`` locations tried
~~~~~~~~~~~~~~~~~~~~~~~~

1. ``./.env`` (current working directory at import time)
2. ``~/.cclark/.env``

The order means a repo-level ``.env`` is tried first, then the user's
persistent config directory — matching the standard Python pattern.
