state — 流式状态和工具栏状态
=================================

源码：src/cclark/state.py

每个频道的流式状态和工具栏状态的模块级全局注册表。
不跨重启持久化（仅内存）。

``VerboseChannelState``
-----------------------

追踪一个飞书频道的活跃流式卡片和回合进度：

.. code-block:: python

   @dataclass
   class VerboseChannelState:
       streaming_card_id: str | None  # 实时卡片的 message_id
       last_flush_ms: float          # 上次刷新的单调时间戳
       turn_states: dict[str, VerboseTurnState]  # 按 user_id 为键

``VerboseTurnState``（嵌套）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   @dataclass
   class VerboseTurnState:
       last_turn_index: int  # 用户已看到的最大 turn_index
       pending_text: str      # 自上次刷新以来积累的文本

``ToolbarState``
----------------

.. code-block:: python

   @dataclass
   class ToolbarState:
       toolbar_card_id: str | None   # 显示中的工具栏的 message_id
       toolbar_window_id: str | None # 工具栏所附着的窗口

全局注册表访问器
-------------------------

::

   _verbose_states: dict[str, VerboseChannelState]  # 按 channel_id 为键
   _toolbar_states: dict[str, ToolbarState]        # 按 channel_id 为键

   get_verbose_state(channel_id) → VerboseChannelState
   get_toolbar_state(channel_id) → ToolbarState
   reset_channel_state(channel_id)  # 取消绑定时清除两者

持久化
-----------

此模块**不持久化**。流式状态和工具栏状态在重启后从网关事件重建。
``cards/streaming.py`` 中的 ``VerboseCardStreamer`` 是主要消费者。

VerboseCardStreamer 使用 ``get_verbose_state`` 来：

1. 检查流式卡片是否已存在（``streaming_card_id``）
2. 在后续刷新时 patch 它而非创建新卡片
3. 存储上次刷新时间戳用于防抖计算

调用栈
-----------

流式卡片 — 首次刷新（新卡片）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   VerboseCardStreamer.push("hello", turn_index=0)
   → turn_index 变化? → _flush()
       → _pending = ["hello"]
       → _pending_chars = 5
       → self._state.last_flush_ms = now
       → _build_card("hello") → card_json
       → client.send_interactive_card(channel_id, card_json)
           → POST /im/v1/messages → message_id = "om_xxx"
       → self._state.streaming_card_id = "om_xxx"

流式卡片 — 第二次刷新（patch）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   VerboseCardStreamer.push(" world", turn_index=0)
   → _pending = ["hello", " world"], _pending_chars += 6
   → 定时触发 _flush()
       → text = "hello world"
       → _state.streaming_card_id 已设置
       → client.patch_message("om_xxx", card_json)
           → PATCH /im/v1/messages/om_xxx → 更新卡片

新回合 — 新的流式卡片
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   VerboseCardStreamer.push("next turn", turn_index=1)
   → turn_index 变化（0 → 1）
   → _flush() → 发送回合 0 的卡片，设置 streaming_card_id = None
   → self._turn_index = 1
   → push 添加到新 _pending
   → 下次刷新 → 新卡片通过 send_interactive_card() 发送

