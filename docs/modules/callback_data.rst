callback_data — Callback Prefix Constants
=========================================

Source: src/cclark/callback_data.py

Defines all callback action-value prefixes used in Feishu interactive card
buttons. These constants ensure consistent string matching across the
builder (producing the values) and the registry (consuming them).

All constants are plain ``str`` values. They are used both:

1. **As card button ``value["action"]``** in ``cards/`` builders
2. **As prefix arguments to ``@register``** in handler modules

Prefix reference

Directory browser (``db:``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``DB``                    ``"db"``                  catch-all prefix
``DB_SEL``                ``"db:sel:"``             navigate into a subdirectory
``DB_UP``                 ``"db:up"``               navigate to parent
``DB_HOME``               ``"db:home"``            jump to home directory
``DB_CONFIRM``            ``"db:confirm:"``        confirm selection
``DB_TOGGLE_STAR``        ``"db:star:"``            toggle star on directory

Provider / mode (``prov:``, ``mode:``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``PROV``                  ``"prov:"``               catch-all provider prefix
``PROV_CLAUDE``           ``"prov:claude"``        provider-specific (literal)
``PROV_CODEX``            ``"prov:codex"``         provider-specific (literal)
``PROV_GEMINI``           ``"prov:gemini"``        provider-specific (literal)
``PROV_PI``               ``"prov:pi"``            provider-specific (literal)
``PROV_SHELL``            ``"prov:shell"``        provider-specific (literal)
``MODE``                   ``"mode:"``              catch-all mode prefix
``MODE_STANDARD``          ``"mode:standard"``    literal constant
``MODE_YOLO``              ``"mode:yolo"``        literal constant

Toolbar (``tb:``)
~~~~~~~~~~~~~~~~~

``TB``                    ``"tb:"``                 toolbar prefix (``tb:{window}:{action}``)

Shell approval (``sh:``)
~~~~~~~~~~~~~~~~~~~~~~~~

``SH_RUN``                ``"sh:run:"``            approve shell command
``SH_X``                  ``"sh:x:"``              deny shell command

Session / expandable (``sess:``, ``aq:``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``SESSION_KILL``          ``"sess:kill:"``         kill a window
``SESSION_SHOW``          ``"sess:show:"``         show session status card
``AQ``                    ``"aq:"``                expandable quote navigation

Generic
~~~~~~~

``NOOP``                  ``"noop"``                acknowledge, do nothing
``CANCEL``                ``"cancel"``             cancel current flow

Example card button JSON (produced in cards/)
----------------------------------------------

.. code-block:: python

   # Directory confirm button
   {"action": f"db:confirm:{_enc(selected_path)}"}
   # "db:confirm:/home/user/project"

   # Provider selection button
   {"action": "prov:claude"}

   # Toolbar button
   {"action": f"tb:{window_id}:mode"}
   # "tb:emdash-claude-main-abc123:mode"

URL encoding in ``db:sel:``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Subdirectory paths in ``db:sel:{encoded_path}`` are URL-encoded to avoid
collisions with the colon separator:

.. code-block:: python

   import urllib.parse
   path = "/home/user/my-project/src"
   action_value = f"db:sel:{urllib.parse.quote(path, safe='')}"
   # "db:sel:%2Fhome%2Fuser%2Fmy-project%2Fsrc"

   # On the receiving side:
   raw = ctx.value[len("db:sel:"):]
   path = urllib.parse.unquote(raw)
