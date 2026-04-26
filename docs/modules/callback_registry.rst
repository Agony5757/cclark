callback_registry — 最长前缀回调分发
=========================================

源码：src/cclark/callback_registry.py

用于飞书卡片按钮点击的自我注册式基于装饰器的分发机制。
各处理器模块在导入时注册自己的前缀；注册表在运行时执行最长前缀匹配。

``@register`` 装饰器
-----------------------

处理器使用 ``@register`` 声明自己处理哪些 action-value 前缀：

.. code-block:: python

   from cclark.callback_registry import register, CallbackContext

   @register("db:sel:", "db:up", "db:home")
   async def handle_dir(ctx: CallbackContext) -> None:
       ...

一个处理器可注册多个前缀（所有导航操作共享处理器）。同一前缀不能重复注册。

CallbackContext
---------------

传给每个处理器的已解析负载：

.. code-block:: python

   @dataclass
   class CallbackContext:
       user_id: str       # 点击用户的 open_id
       chat_id: str       # 飞书 chat_id
       thread_id: str     # 飞书 thread_id（可能为 ""）
       value: str        # 原始 action 值，例如 "db:sel:/home/user"
       message_id: str    # 卡片消息 ID
       token: str         # 验证令牌
       channel_id: str    # "feishu:chat:thread" 或 "feishu:chat"

最长前缀匹配
-----------------------

调用 ``dispatch(ctx)`` 时，它找到注册前缀对 ``ctx.value`` 匹配最长的那个处理器：

::

   ctx.value = "db:sel:/home/user/project"
   已注册前缀："db:sel:"、"db:up"、"db:"
   "db:sel:" 匹配（8 字符）← 最长
   → handle_dir_callback(ctx)

前缀必须在模块导入时注册（在首次调用 ``dispatch`` 之前）。
处理器模块由 ``main.py`` 导入：

.. code-block:: python

   from cclark.handlers import callback, message, session_creation, toolbar
   # → session_creation.py 导入 callback_registry
   # → @register("db:sel:", ...) 装饰器执行
   # → _registry 字典被填充

这种延迟导入避免了循环依赖问题——注册表模块提前加载，
各处理器模块在导入时注册自己。

``load_handlers`` 函数
---------------------------

``callback_registry.load_handlers()`` 显式触发导入副作用。
由 ``main.py`` 调用以确保在服务请求前加载处理器。

已注册前缀
-------------------

=========================  ====================================================
前缀                       处理器
=========================  ====================================================
``db:sel:``                ``session_creation.handle_dir_callback``
``db:up``                  ``session_creation.handle_dir_callback``
``db:home``                ``session_creation.handle_dir_callback``
``db:confirm:``            ``session_creation.handle_dir_callback``
``db:star:``               ``session_creation.handle_dir_callback``
``db:pg:``                 ``session_creation.handle_dir_callback``
``prov:``                  ``session_creation.handle_provider_callback``
``mode:``                  ``session_creation.handle_mode_callback``
``tb:``                    ``toolbar.handle_toolbar_callback``
``sh:run:``                ``callback._shell_approve``
``sh:x:``                  ``callback._shell_deny``
``sess:kill:``             ``callback._session_kill``
``sess:show:``             ``callback._session_show``
``noop`` / ``cancel``      ``callback.dispatch``（全匹配）
=========================  ====================================================

调用栈
-----------

工具栏按钮点击 → tmux 发送按键
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   POST /webhook/callback
   → webhook._handle_callback()
   → parse_callback_event() → FeishuCallbackEvent(value="tb:win1:ctrlc")
   → CallbackContext(value="tb:win1:ctrlc", ...)
   → callback_registry.dispatch(ctx)
       → _find_handler("tb:")
           → 已注册前缀："tb:",
           → 最佳匹配："tb:"（3 字符）
           → return toolbar.handle_toolbar_callback
       → await handle_toolbar_callback(ctx)
           → ctx.value[len("tb:"):] = "win1:ctrlc"
           → parts = "win1:ctrlc".split(":", 1) → ["win1", "ctrlc"]
           → window_id = "win1", action_name = "ctrlc"
           → _get_toolbar_config().actions.get("ctrlc")
               → ToolbarAction(name="ctrlc", action_type="builtin", payload="ctrlc")
           → action_type == "builtin"? → _handle_builtin("ctrlc", ...)
               → "ctrlc" 在 ("ctrlc", "send", "enter")? → key_map["ctrlc"] = "\x03"
               → gateway.send_key("win1", "\x03")
                   → tmux_manager.send_keys("win1", "\x03")
                   → tmux send-keys -t win1 "\x03"

提供方选择器 → 模式选择器卡片
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   callback value = "prov:claude"
   → dispatch → _find_handler("prov:")
   → handle_provider_callback(ctx)
       → provider = ctx.value[len("prov:"):] = "claude"
       → state["provider"] = "claude"
       → provider == "shell"? → 跳过模式选择器
       → _build_mode_picker_card(path, "claude")
       → adapter.send_interactive_card(channel_id, card_json)
