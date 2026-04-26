Troubleshooting
===============

Startup failures
----------------

"FEISHU_APP_ID environment variable is required"
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The config singleton raises ``ValueError`` at import time if required env
vars are missing.

**Fix**: Set all required env vars before starting:

.. code-block:: bash

   export FEISHU_APP_ID=cli_xxx
   export FEISHU_APP_SECRET=xxx
   export ALLOWED_USERS=ou_xxx
   export FEISHU_BOT_USER_ID=ou_bot
   cclark run

"Cannot find unified-icc"
~~~~~~~~~~~~~~~~~~~~~~~~~~

The dependency path in ``pyproject.toml`` points to the local source tree.
Run ``uv sync`` in the ``cclark/`` directory first.

"Address already in use" when starting the webhook
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Port 8080 (or ``$CCLARK_WEBHOOK_PORT``) is already in use.

**Fix**: Set a different port:

.. code-block:: bash

   export CCLARK_WEBHOOK_PORT=8081
   cclark run

Feishu webhook
---------------

Feishu is not receiving events
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. **Check the webhook URL** is publicly accessible (not localhost)
2. **Use ngrok** for local development:

   .. code-block:: bash

      ngrok http 8080
      # Copy https:// URL → Feishu Open Platform → Event Subscription

3. Verify the URL verification challenge passes:

   .. code-block:: bash

      curl -X POST https://your-host/webhook/event \
        -H "Content-Type: application/json" \
        -d '{"challenge": "test-challenge"}'
      # Should return: {"challenge": "test-challenge"}

4. Check ``/health`` is reachable from the internet:

   .. code-block:: bash

      curl https://your-host/health
      # Should return: {"status": "ok"}

Messages not being processed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **Bot's own messages**: ``config.bot_user_id`` is set? The bot skips its own messages.
- **Non-text messages**: Only ``msg_type=text`` is handled. Images, files, etc. are acknowledged but not processed.
- **User not in allowlist**: ``config.is_user_allowed(user_id)`` returns False → silent skip.

Directory browser / session creation
--------------------------------------

"Directory no longer exists" when clicking a folder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The path in the URL-encoded action value is stale (session restart or directory
deleted). Click **Home** to reset to a valid directory.

Session creation hangs after confirming directory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The session creation flow requires:

1. ``gateway.create_window()`` → tmux new-window must succeed
2. ``gateway.bind_channel()`` → channel-window mapping saved
3. ``gateway.send_to_window()`` → text piped to tmux pane

Check that:

- tmux is running (``tmux list-sessions``)
- the working directory exists and is accessible
- the provider command (``claude``, ``codex``, etc.) is installed and on PATH

Toolbar buttons do nothing
~~~~~~~~~~~~~~~~~~~~~~~~~~

- ``tb:`` callbacks require a bound window (``channel_router.resolve_window`` must return a window_id)
- Check the gateway is running (``gateway.on_message`` is registered)
- ``gateway.send_key()`` requires tmux 1.8+

Streaming card not updating
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The VerboseCardStreamer requires a registered ``on_message`` callback.
If ``main._register_callbacks`` fails silently, streaming never starts.

Check: does ``/health`` respond? Is the gateway poll loop running?
Verify with a ``/new`` command — a streaming card should appear within 3s
of the first agent output.

VerboseCardStreamer creates duplicate cards
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If multiple streaming cards appear for the same turn, the ``_state`` registry
may have been cleared between flushes. Ensure ``reset()`` is only called
on unbind or session end, not between turns of the same session.

Card too large (Feishu error)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Feishu enforces a ~30 KB limit per card. Reduce ``_MAX_CHARS_PER_FLUSH``
in ``cards/streaming.py`` or truncate long outputs in the agent transcript
before pushing to the streamer.

Callback registration conflicts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you see ``ValueError: Callback prefix 'prov:' already registered``, two
modules registered the same prefix. The fix: only register catch-all prefixes
(``DB``, ``PROV``, ``MODE``, ``TB``) in ``handlers/callback.py`` — individual
sub-handlers register their own specific prefixes (``db:sel:``, ``prov:claude``,
etc.) directly.

tmux connection
---------------

"Session 'default' not found"
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The unified-icc gateway requires tmux to be installed and the default session
to exist (or be auto-created). Start tmux first:

.. code-block:: bash

   tmux new -d -s default
   # or set CCLARK_TMUX_SESSION to a different session name

Provider-specific
-----------------

"claude command not found"
~~~~~~~~~~~~~~~~~~~~~~~~~~

Install Claude Code CLI:

.. code-block:: bash

   npm install -g @anthropic-ai/claude-code
   # or: pip install claude-code

"codex command not found"
~~~~~~~~~~~~~~~~~~~~~~~~~

Install OpenAI Codex CLI:

.. code-block:: bash

   npm install -g @openai/codex
   # or: pip install codex

File upload fails
~~~~~~~~~~~~~~~~~

Feishu file uploads require the ``im:file`` scope in the app permissions.
Check Feishu Open Platform → Permissions → ``im:file``.
