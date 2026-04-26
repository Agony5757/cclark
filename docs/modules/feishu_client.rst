feishu_client — Feishu REST API Client
=======================================

Source: src/cclark/feishu_client.py

Thin async wrapper around Feishu's IM API using ``httpx.AsyncClient``.
All outbound Feishu communication flows through this module — no other module
makes raw HTTP calls.

``FeishuClient``
----------------

.. code-block:: python

   from cclark.feishu_client import FeishuClient, FeishuAPIError

   client = FeishuClient(app_id="cli_xxx", app_secret="xxx")
   # use await client.send_text(chat_id, "hello")
   await client.close()

Token management
----------------

``_get_token()`` is called lazily before every outbound request. It:

1. Checks if the cached token is still valid (expires_at - 60s margin)
2. If expired/missing, POSTs to ``/auth/v3/tenant_access_token``
3. Stores token + expiry in instance attributes
4. Returns the token

Token is **never** shared across ``FeishuClient`` instances. Each instance
manages its own token lifecycle.

API methods
-----------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Method
     - Feishu API endpoint
   * - ``send_message(receive_id, msg_type, content)``
     - ``POST /im/v1/messages`` (returns message_id)
   * - ``send_text(receive_id, text)``
     - Wraps ``send_message`` with ``msg_type="text"``
   * - ``send_interactive_card(receive_id, card_json)``
     - Wraps ``send_message`` with ``msg_type="interactive"``
   * - ``send_image(receive_id, image_key)``
     - Wraps ``send_message`` with ``msg_type="image"``
   * - ``send_file(receive_id, file_key, file_name)``
     - Wraps ``send_message`` with ``msg_type="file"``
   * - ``patch_message(message_id, card_json)``
     - ``PATCH /im/v1/messages/{message_id}``
   * - ``reply_in_thread(receive_id, msg_type, content, parent_id)``
     - ``POST /im/v1/messages`` with ``parent_id`` for threading
   * - ``upload_image(image_bytes, image_name)``
     - ``POST /im/v1/images`` (returns image_key)
   * - ``upload_file(file_bytes, file_name, file_type)``
     - ``POST /im/v1/files`` (returns file_key)

Error handling
--------------

Any non-zero Feishu ``code`` in the response body raises ``FeishuAPIError``:

.. code-block:: python

   try:
       await client.send_text(chat_id, "hello")
   except FeishuAPIError as e:
       logger.error("Feishu API error: %s body=%s", e.msg, e.body)

HTTP-level errors (4xx/5xx) raise ``httpx.HTTPStatusError``, which is
**not** caught — callers should handle it.

Call stacks
-----------

Send a text message in a thread
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   adapter._send_text_in_thread(chat_id, thread_id, text)
   └─ client.reply_in_thread(chat_id, "text", json.dumps({"text": text}), thread_id)
       └─ client._post("/im/v1/messages",
           json_data={..., "parent_id": thread_id},
           params={"receive_id_type": "chat_id"})
           └─ _headers() → _get_token()
               └─ POST /auth/v3/tenant_access_token  [if expired]
           └─ POST /im/v1/messages
           └─ raise FeishuAPIError if body["code"] != 0
           └─ return body["data"]["message_id"]

Upload an image and send it
~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   adapter.send_image(channel_id, image_bytes)
   └─ client.upload_image(image_bytes)
       └─ client._post("/im/v1/images",
           data={"image_type": "message"},
           files={"image": (name, bytes, "image/png")})
           └─ _headers() → _get_token()
           └─ POST /im/v1/images
           └─ return body["data"]["image_key"]
   └─ client.send_message(chat_id, "image", json.dumps({"image_key": key}))
       └─ _post(...)  [same as above]
       └─ return message_id

Patch a streaming card (update)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   VerboseCardStreamer._flush()
   └─ client.patch_message(streaming_card_id, card_json)
       └─ client._post(f"/im/v1/messages/{message_id}",
           json_data={"content": card_json})
           └─ _headers() → _get_token()
           └─ PATCH /im/v1/messages/{message_id}
           └─ Feishu returns empty data {} on success
