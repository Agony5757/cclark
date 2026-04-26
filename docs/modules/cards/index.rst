cards — Feishu Card Builders
=============================

.. toctree::
   :maxdepth: 1

   streaming

Source: src/cclark/cards/

All card-building utilities. Each module produces a Feishu card JSON string
(``json.dumps`` output) ready to be sent via ``FeishuClient``.

Feishu card schema
-------------------

All cards follow the Feishu interactive card schema:

.. code-block:: json

   {
     "config": {"wide_screen_mode": true},
     "header": {
       "title": {"tag": "plain_text", "content": "Title"},
       "template": "blue"
     },
     "elements": [
       {"tag": "markdown", "content": "..."},
       {"tag": "action", "children": [
         {"tag": "button", "text": {...}, "action_type": "interactive", "value": {"action": "..."}}
       ]}
     ]
   }

Supported header templates: ``blue``, ``wathet``, ``turquoise``, ``green``,
``yellow``, ``orange``, ``red``, ``purple``, ``indigo``, ``grey``.

cards/builder — FeishuCardBuilder
---------------------------------

Core builder for ``CardPayload`` and ``InteractivePrompt``:

.. code-block:: python

   FeishuCardBuilder.build_card(CardPayload(title="...", body="...", color="blue"))
   # → json.dumps(card_dict)

Markdown conversion (``_md``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- ``**bold**`` → ``<strong>bold</strong>``
- backtick code spans → ``<code>code</code>``
- ``&``, ``<``, ``>`` escaped to HTML entities

cards/output — Agent Output Cards
----------------------------------

.. code-block:: python

   build_output_card(title, body, provider, color, actions)
   # → FeishuCardBuilder.build_card(CardPayload(...))

   build_code_output_card(title, code, language, provider, max_chars)
   # → json.dumps({header, elements: [{tag: "markdown", content: "```lang\ncode\n```"}]})

cards/status — Session Status Cards
-----------------------------------

.. code-block:: python

   build_status_card(
       title="Claude Session",
       window_id="emdash-claude-main-abc",
       provider="claude",
       status="running",
       working_dir="/home/user/project",
       actions=[{"label": "Kill", "action": "sess:kill:window_id"}],
   )
   # → json.dumps(card_dict)

cards/prompt — Permission / Question Cards
--------------------------------------------

.. code-block:: python

   build_permission_card(title, body, options, cancel_text)
   # → Feishu interactive card with approval buttons

   build_question_card(title, question, options, cancel_text)
   # → Feishu interactive card with multi-choice buttons

cards/toolbar — Toolbar Grid Builder
-------------------------------------

.. code-block:: python

   build_toolbar_card(window_id, provider, toolbar_config, status_label)
   # → Feishu interactive card with action button grid
   # Each button value = f"tb:{window_id}:{action_name}"

Feishu markdown limitation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Feishu markdown does not support `````language`` code fences in ``<pre>`` or
``<code>`` tags. ``cards/output.py:build_code_output_card`` works around this
by using the ````` ```` markdown syntax inside a ``<markdown>`` element tag
(rendered as a code block by Feishu), but this is unreliable for some Feishu
versions. For code output longer than a few lines, prefer sending as a file
message instead.

cards/streaming — VerboseCardStreamer
--------------------------------------

See `cards/streaming.rst <streaming.html>`_ for the full call-stack documentation.

Card size limits
----------------

Feishu enforces a ~30 KB limit per card. ``FeishuCardBuilder._truncate_code``
cuts code blocks at 2000 characters. ``VerboseCardStreamer._build_card`` adds
a truncation warning if text exceeds 28 KB.
