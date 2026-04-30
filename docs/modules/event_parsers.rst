event_parsers — 飞书 JSON → FeishuMessageEvent
==================================================

源码：src/cclark/event_parsers.py

将原始飞书 WebSocket 事件 JSON 负载转换为类型化 Python 数据类。

``FeishuMessageEvent``
-----------------------

.. code-block:: python

   @dataclass
   class FeishuMessageEvent:
       chat_id: str       # "oc_xxxx"
       thread_id: str     # 非话题聊天时为 ""
       user_id: str       # 发送者的飞书 open_id
       text: str          # 去空格后的文本内容
       message_id: str     # 用于回复话题
       msg_type: str      # "text"（当前仅处理文本）
       app_name: str      # 多 app 模式下来源 app 名称

``parse_message_event`` 解析逻辑
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   payload = {"event": {
       "chat_id": "...",
       "thread_id": "...",
       "sender": {"sender_id": {"open_id": "..."}},
       "message": {"msg_type": "text", "message_id": "...",
                   "content": "{\"text\": \"...\"}"}
   }}
   ↓ 提取 event、sender、message
   ↓ msg_type != "text"? → 返回 None  [仅处理文本]
   ↓ json.loads(content) → {"text": "..."}
   ↓ text = parsed["text"].strip()
   ↓ FeishuMessageEvent(...)
   ↓ 任何异常 → 返回 None

飞书文本消息的 JSON ``content`` 字段本身又是一个 JSON 字符串，
所以需要双重解析。

支持的飞书事件 schema 版本
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Feishu 平台在 1.0 和 2.0 版本间演进：

===============  =============  ================
字段              Schema 1.0     Schema 2.0
===============  =============  ================
消息类型          msg_type       message_type
聊天 ID          event.chat_id  message.chat_id
===============  =============  =============

``parse_message_event`` 使用 ``or`` 链接受两者：
``message.get("message_type", "") or message.get("msg_type", "")``

调用栈
------------

::

   ws_client._dispatch_event(payload)
   → parse_message_event(payload)
       → payload["event"]["message"]["msg_type"] == "text"?
       → payload["event"]["message"]["content"] = '{"text": "hello"}'
       → json.loads → {"text": "hello"}
       → text = "hello".strip()
       → return FeishuMessageEvent(chat_id=..., user_id=..., text="hello", ...)
   → handle_message(event)  [handlers/message.py]
