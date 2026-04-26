webhook — FastAPI Webhook 服务器
====================================

源码：src/cclark/webhook.py

运行 FastAPI 服务器以接收飞书事件 Webhook。两个端点：

- ``GET /health`` — 存活探针
- ``POST /webhook/event`` — 飞书事件 Webhook
- ``POST /webhook/callback`` — 卡片按钮点击（与上一路径相同，通过负载形状区分）

模块级注册
-------------------------

处理器通过模块级变量设置，以便 ``main.py`` 在不产生循环导入的情况下接入：

.. code-block:: python

   from cclark.webhook import create_app, register_message_handler

   def my_handler(event_dict):
       asyncio.create_task(handle_message(event_dict))

   register_message_handler(my_handler)

   app = create_app(client)  # 接入 FastAPI 路由

路由流程
----------

::

   FastAPI 接收 POST 请求
   ↓ request.json()
   ↓ parse_url_verification(payload)
       → FeishuURLVerificationEvent? → 返回 {"challenge": x}（HTTP 200）
   ↓ is_card_callback(payload)
       → True? → _handle_callback()
       → False? → _handle_message()

``is_card_callback`` 检查飞书卡片回调形状：
``"action" in payload and "value" in payload.get("action", {})``。

``POST /webhook/event`` — 消息处理
-------------------------------------------

::

   webhook._handle_message(payload)
   → event_parsers.parse_message_event(payload)
       → FeishuMessageEvent | None
       → 非文本消息返回 None → 静默确认
   → event.user_id == config.bot_user_id?
       → True → 跳过，返回 {"status": "ok"}
   → config.is_user_allowed(event.user_id)?
       → False → 跳过、记录日志、返回 {"status": "ok"}
   → _message_handler(event)
       → asyncio.create_task(handle_message(event))
   → 立即返回 {"status": "ok"}

``await asyncio.create_task(...)`` 通过处理器函数本身的 async 特性隐式实现——
FastAPI 会 ``await`` 它。非文本消息（图片、文件等）
直接返回 ``{"status": "ok"}`` 而不处理。

``POST /webhook/callback`` — 卡片按钮点击
-------------------------------------------------

::

   webhook._handle_callback(payload)
   → event_parsers.parse_callback_event(payload)
       → FeishuCallbackEvent | None
       → 返回 None? → HTTP 400
   → config.feishu_verification_token 已设置且令牌不匹配?
       → True → HTTP 403
   → config.parse_channel_id(event.chat_id, event.thread_id)
       → "feishu:chat:thread" 或 "feishu:chat"
   → CallbackContext(user_id=..., channel_id=..., value=action_value, ...)
   → _callback_handler(ctx)
       → callback_registry.dispatch(ctx)
           → is_user_allowed 检查
           → _find_handler（最长前缀匹配）
           → handler(ctx)
   → 返回 {"status": "ok"}

URL 验证
----------------

飞书首次设置 Webhook URL 时，会发送带有 ``{"challenge": "xxx"}`` 的 GET/POST 请求。
``parse_url_verification`` 检测到此情况后，Webhook 返回 ``{"challenge": "xxx"}`` 以证明所有权。

``create_app`` 签名
------------------------

.. code-block:: python

   def create_app(client: FeishuClient) -> FastAPI:
       ...

``client`` 参数被接受（为了完整性），但当前未在 FastAPI 应用内部使用——
实际的 FeishuClient 存储在通过 ``register_message_handler`` /
``register_callback_handler`` 注册的处理器闭包中。
