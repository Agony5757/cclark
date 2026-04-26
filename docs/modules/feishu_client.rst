feishu_client — 飞书 REST API 客户端
=========================================

源码：src/cclark/feishu_client.py

使用 ``httpx.AsyncClient`` 对飞书 IM API 的轻量异步封装。
所有出站飞书通信都经过此模块——其他模块不发送原始 HTTP 请求。

``FeishuClient``
----------------

.. code-block:: python

   from cclark.feishu_client import FeishuClient, FeishuAPIError

   client = FeishuClient(app_id="cli_xxx", app_secret="xxx")
   # 使用 await client.send_text(chat_id, "hello")
   await client.close()

令牌管理
----------------

``_get_token()`` 在每次出站请求前惰性调用。它：

1. 检查缓存令牌是否仍有效（expires_at 预留 60 秒余量）
2. 如已过期/缺失，向 ``/auth/v3/tenant_access_token`` 发送 POST
3. 将令牌 + 过期时间存入实例属性
4. 返回令牌

令牌**不会**在多个 ``FeishuClient`` 实例间共享。每个实例
管理自己的令牌生命周期。

API 方法
-----------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - 方法
     - 飞书 API 端点
   * - ``send_message(receive_id, msg_type, content)``
     - ``POST /im/v1/messages``（返回 message_id）
   * - ``send_text(receive_id, text)``
     - 用 ``msg_type="text"`` 封装 ``send_message``
   * - ``send_interactive_card(receive_id, card_json)``
     - 用 ``msg_type="interactive"`` 封装 ``send_message``
   * - ``send_image(receive_id, image_key)``
     - 用 ``msg_type="image"`` 封装 ``send_message``
   * - ``send_file(receive_id, file_key, file_name)``
     - 用 ``msg_type="file"`` 封装 ``send_message``
   * - ``patch_message(message_id, card_json)``
     - ``PATCH /im/v1/messages/{message_id}``
   * - ``reply_in_thread(receive_id, msg_type, content, parent_id)``
     - ``POST /im/v1/messages`` 并带 ``parent_id`` 以实现话题
   * - ``upload_image(image_bytes, image_name)``
     - ``POST /im/v1/images``（返回 image_key）
   * - ``upload_file(file_bytes, file_name, file_type)``
     - ``POST /im/v1/files``（返回 file_key）

错误处理
--------------

响应体中任何非零的飞书 ``code`` 都会抛出 ``FeishuAPIError``：

.. code-block:: python

   try:
       await client.send_text(chat_id, "hello")
   except FeishuAPIError as e:
       logger.error("Feishu API error: %s body=%s", e.msg, e.body)

HTTP 层错误（4xx/5xx）抛出 ``httpx.HTTPStatusError``，
**不会**被捕获——调用方应自行处理。

调用栈
-----------

在话题中发送文本消息
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   adapter._send_text_in_thread(chat_id, thread_id, text)
   └─ client.reply_in_thread(chat_id, "text", json.dumps({"text": text}), thread_id)
       └─ client._post("/im/v1/messages",
           json_data={..., "parent_id": thread_id},
           params={"receive_id_type": "chat_id"})
           └─ _headers() → _get_token()
               └─ POST /auth/v3/tenant_access_token  [如已过期]
           └─ POST /im/v1/messages
           └─ 如 body["code"] != 0 则抛出 FeishuAPIError
           └─ return body["data"]["message_id"]

上传图片并发送
~~~~~~~~~~~~~~~~~~~~~~~~~

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
       └─ _post(...)  [同上]
       └─ return message_id

Patch 流式卡片（更新）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   VerboseCardStreamer._flush()
   └─ client.patch_message(streaming_card_id, card_json)
       └─ client._post(f"/im/v1/messages/{message_id}",
           json_data={"content": card_json})
           └─ _headers() → _get_token()
           └─ PATCH /im/v1/messages/{message_id}
           └─ 成功时飞书返回空数据 {}
