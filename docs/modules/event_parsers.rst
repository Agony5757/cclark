event_parsers — 飞书 JSON → 类型化事件
==========================================

源码：src/cclark/event_parsers.py

将原始飞书 Webhook JSON 负载转换为类型化 Python 数据类。
三种事件类型：

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - 类型
     - 来源
   * - ``FeishuMessageEvent``
     - ``im.message.receive_v1`` 事件负载
   * - ``FeishuCallbackEvent``
     - 卡片按钮点击回调负载
   * - ``FeishuURLVerificationEvent``
     - Webhook URL 验证挑战

``FeishuMessageEvent``
-----------------------

.. code-block:: python

   @dataclass(frozen=True)
   class FeishuMessageEvent:
       chat_id: str       # "oc_xxxx"
       thread_id: str     # 非话题聊天时为 ""
       user_id: str       # 发送者的飞书 open_id
       text: str          # 去空格后的文本内容
       message_id: str     # 用于回复话题
       msg_type: str      # "text"、"image" 等

``parse_message_event`` 解析逻辑：

::

   payload = {"event": {"chat_id": "...", "thread_id": "...",
                        "sender": {"sender_id": {"open_id": "..."}},
                        "message": {"msg_type": "text", "message_id": "...",
                                   "content": "{\"text\": \"...\"}"}}}
   ↓ 提取 event、sender、message
   ↓ msg_type != "text"? → 返回 None  [仅处理文本]
   ↓ json.loads(content) → {"text": "..."}
   ↓ text = parsed["text"].strip()
   ↓ FeishuMessageEvent(...)
   ↓ 任何异常 → 返回 None

飞书文本消息的 JSON ``content`` 字段本身又是一个 JSON 字符串，
所以需要双重解析。

``FeishuCallbackEvent``
-----------------------

.. code-block:: python

   @dataclass(frozen=True)
   class FeishuCallbackEvent:
       chat_id: str
       user_id: str       # 点击用户的 open_id
       action_value: str  # "db:sel:/path"、"tb:window:mode" 等
       message_id: str     # 被点击的卡片消息 ID
       token: str         # 验证令牌
       thread_id: str = ""

解析逻辑：

::

   payload = {"action": {"value": "{\"action\": \"db:sel:/home/...\"}",
                          "message_id": "..."},
              "chat": {"chat_id": "...", "thread_id": "..."},
              "sender": {"sender_id": {"open_id": "..."}},
              "token": "..."}
   ↓ action["value"] 可能是 str 或 dict
   ↓ 如为 str → json.loads
   ↓ action_value = value["action"]
   ↓ FeishuCallbackEvent(...)

``is_card_callback``
--------------------

::

   def is_card_callback(payload: dict) -> bool:
       return "action" in payload and "value" in payload.get("action", {})

这用于区分卡片回调和消息事件——消息事件有 ``event.message``，
卡片回调有 ``action.value``。

调用栈
------------

解析文本消息事件
~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   webhook._handle_message(payload)
   → parse_message_event(payload)
       → payload["event"]["message"]["msg_type"] == "text"?
       → payload["event"]["message"]["content"] = '{"text": "hello"}'
       → json.loads → {"text": "hello"}
       → text = "hello".strip()
       → return FeishuMessageEvent(chat_id=..., user_id=..., text="hello", ...)
   → handle_message(event)  [handlers/message.py]

解析卡片按钮点击
~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   webhook._handle_callback(payload)
   → is_card_callback(payload) → True  [此调用前已检查]
   → parse_callback_event(payload)
       → payload["action"]["value"] = '{"action": "tb:win1:mode"}'
       → json.loads → {"action": "tb:win1:mode"}
       → action_value = "tb:win1:mode"
       → return FeishuCallbackEvent(value="tb:win1:mode", ...)
   → CallbackContext(...)
   → callback_registry.dispatch(ctx)
       → ctx.value.startswith("tb:")? → True
       → _find_handler("tb:") → toolbar.handle_toolbar_callback
       → await handle_toolbar_callback(ctx)
