adapter — FeishuAdapter（FrontendAdapter 实现）
==================================================

源码：src/cclark/adapter.py

实现 ``unified_icc.adapter.FrontendAdapter`` — unified-icc 用于发送出站消息的契约。
这是唯一同时了解网关接口和飞书 API 的模块。

``FeishuAdapter``
-----------------

.. code-block:: python

   from cclark import FeishuClient, FeishuAdapter

   client = FeishuClient(app_id, app_secret)
   adapter = FeishuAdapter(client)

``FrontendAdapter`` 实现
-----------------------------------

``FrontendAdapter`` 的全部六个方法：

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - 方法
     - 行为
   * - ``send_text(channel_id, text)``
     - 按 4000 字符分块发送；如有 thread_id 则在话题中回复
   * - ``send_card(channel_id, card)``
     - 将 CardPayload 转换为飞书卡片 JSON；作为交互卡片发送
   * - ``update_card(channel_id, card_id, card)``
     - 通过 FeishuClient PATCH 已有卡片
   * - ``send_image(channel_id, image_bytes, caption)``
     - 上传 → 发送图片消息
   * - ``send_file(channel_id, file_path, caption)``
     - 读取文件 → 上传 → 发送文件消息
   * - ``show_prompt(channel_id, prompt)``
     - 将 InteractivePrompt 渲染为卡片

内部辅助函数
-----------------

* ``_send_text_chunked`` — 按 4000 字符分块发送文本，返回最后一条消息 ID
* ``_send_text_in_thread`` — 调用 ``reply_in_thread`` 实现飞书话题
* ``_send_card`` — 正常发送卡片或作为话题回复
* ``_send_message`` — 带可选话题路由的低级发送

飞书话题机制
-----------------

飞书话题使用 ``parent_id``（根话题消息的 message_id）来路由回复。当频道 ID 包含 thread_id 时：

::

   channel_id = "feishu:chat_123:thread_456"
   ↓ split_channel_id
   chat_id="chat_123", thread_id="thread_456"
   ↓ _send_text_in_thread / _send_card / _send_message
   FeishuClient.reply_in_thread(chat_id, msg_type, content, parent_id=thread_456)

非话题频道直接发送，不带 ``parent_id``。

CardPayload → 飞书 JSON
--------------------------

::

   adapter.send_card(channel_id, CardPayload(title="...", body="...", color="blue"))
   → FeishuCardBuilder.build_card(card)
       → _header_color("blue") → "blue"
       → _md(body)  [markdown → 飞书标签]
       → fields 渲染为键值对 markdown
       → actions 渲染为按钮，action.value["action"]
       → json.dumps → card_json 字符串
   → FeishuClient.send_interactive_card(chat_id, card_json)
   → message_id

调用栈
-----------

在话题中发送文本
~~~~~~~~~~~~~~~~~~~~~~~~

::

   adapter.send_text("feishu:chat:thread", "hello")
   → config.split_channel_id("feishu:chat:thread")
       → ("chat", "thread")
   → _send_text_in_thread("chat", "thread", "hello")
       → _send_text_chunked("chat", "hello")  [≤4000 字符，不分块]
           → client.send_text("chat", "hello")
               → send_message("chat", "text", json.dumps({"text":"hello"}))
                   → _post("/im/v1/messages", params={...})
   → return message_id

长文本（>4000 字符）在发送前分块：

::

   adapter.send_text("feishu:chat", long_text)
   → _send_text_chunked("chat", long_text)
       → client.send_text("chat", chunk1[:4000])  [返回 msg_id_1]
       → client.send_text("chat", chunk1[4000:])  [返回 msg_id_2]
       → ...
       → return last_msg_id

发送图片
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
