adapter — FeishuAdapter (FrontendAdapter implementation)
adapter — FeishuAdapter (FrontendAdapter implementation)

Source: src/cclark/adapter.py

Implements ``unified_icc.adapter.FrontendAdapter`` — the contract that
unified-icc uses to send outbound messages. This is the only module that
knows about both the gateway interface and Feishu's API.

``FeishuAdapter``
-----------------

.. code-block:: python

   from cclark import FeishuClient, FeishuAdapter

   client = FeishuClient(app_id, app_secret)
   adapter = FeishuAdapter(client)

``FrontendAdapter`` implementation
-----------------------------------

All six methods from ``FrontendAdapter``:

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Method
     - Behaviour
   * - ``send_text(channel_id, text)``
     - Chunks text at 4000 chars; sends in thread if thread_id present
   * - ``send_card(channel_id, card)``
     - Converts CardPayload → Feishu card JSON; sends as interactive card
   * - ``update_card(channel_id, card_id, card)``
     - PATCH existing card via FeishuClient
   * - ``send_image(channel_id, image_bytes, caption)``
     - Uploads → sends image message
   * - ``send_file(channel_id, file_path, caption)``
     - Reads file → uploads → sends file message
   * - ``show_prompt(channel_id, prompt)``
     - Renders InteractivePrompt as card

Internal helpers
Internal helpers

Internal helpers:

* ``_send_text_chunked`` — Splits text at 4000 chars, sends each chunk, returns last ID
* ``_send_text_in_thread`` — Calls ``reply_in_thread`` for Feishu threading
* ``_send_card`` — Sends card normally or as thread reply
* ``_send_message`` — Low-level send with optional thread routing

Feishu threading
-----------------

Feishu threads use ``parent_id`` (message_id of the root thread message) to
route replies. When a channel ID contains a thread_id:

::

   channel_id = "feishu:chat_123:thread_456"
   ↓ split_channel_id
   chat_id="chat_123", thread_id="thread_456"
   ↓ _send_text_in_thread / _send_card / _send_message
   FeishuClient.reply_in_thread(chat_id, msg_type, content, parent_id=thread_456)

For non-threaded channels, the send is made directly without ``parent_id``.

CardPayload → Feishu JSON
--------------------------

::

   adapter.send_card(channel_id, CardPayload(title="...", body="...", color="blue"))
   → FeishuCardBuilder.build_card(card)
       → _header_color("blue") → "blue"
       → _md(body)  [markdown → Feishu tags]
       → fields rendered as key-value markdown
       → actions rendered as buttons with action.value["action"]
       → json.dumps → card_json string
   → FeishuClient.send_interactive_card(chat_id, card_json)
   → message_id

Call stacks
-----------

Send text in a thread
~~~~~~~~~~~~~~~~~~~~~~

::

   adapter.send_text("feishu:chat:thread", "hello")
   → config.split_channel_id("feishu:chat:thread")
       → ("chat", "thread")
   → _send_text_in_thread("chat", "thread", "hello")
       → _send_text_chunked("chat", "hello")  [≤4000 chars, no chunking]
           → client.send_text("chat", "hello")
               → send_message("chat", "text", json.dumps({"text":"hello"}))
                   → _post("/im/v1/messages", params={...})
   → return message_id

Long text (>4000 chars) is split before sending:

::

   adapter.send_text("feishu:chat", long_text)
   → _send_text_chunked("chat", long_text)
       → client.send_text("chat", chunk1[:4000])  [returns msg_id_1]
       → client.send_text("chat", chunk1[4000:])  [returns msg_id_2]
       → ...
       → return last_msg_id

Send image
~~~~~~~~~~

::

   adapter.send_image("feishu:chat:thread", image_bytes)
   → config.split_channel_id → ("chat", "thread")
   → client.upload_image(image_bytes)
       → _post("/im/v1/images", files={"image": ...})
       → return image_key
   → json.dumps({"image_key": image_key})
   → client.reply_in_thread("chat", "image", content, "thread")
       → _post(..., json_data={..., "parent_id": "thread"})
   → return message_id
