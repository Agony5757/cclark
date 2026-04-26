cards/streaming — VerboseCardStreamer
=======================================

源码：src/cclark/cards/streaming.py

将传入的智能体输出消息缓冲起来，以 2.5 秒防抖窗口刷新为飞书卡片更新。
每个智能体回合每频道一个流式卡片。

设计目标
------------

1. **每回合一卡**：新回合开始一张新卡；回合推进后不再编辑旧卡片。
2. **无间隙**：同一回合内通过 PATCH 更新卡片（而非替换），保持连续性。
3. **有界缓冲**：积累 50 条消息或 8000 字符后强制刷新。

``VerboseCardStreamer``
-----------------------

.. code-block:: python

   streamer = VerboseCardStreamer(
       client=feishu_client,
       channel_id="feishu:chat:thread",
       user_id="ou_abc",
       provider="claude",
   )

关键方法
~~~~~~~~~~~

``push(text, turn_index)``
    添加文本到缓冲区；触发阈值刷新

``flush()``
    强制立即刷新

``set_turn_index(idx)``
    信号回合推进 → 下次 push 时开始新卡片

``reset()``
    清除状态（在取消绑定时调用）

刷新触发条件
~~~~~~~~~~~~~~

满足**任一**条件时触发刷新：

1. ``len(_pending) >= 50`` — 每刷新最多消息数
2. ``_pending_chars >= 8000`` — 每刷新最多字符数
3. ``now_ms - _state.last_flush_ms >= 2500`` — 时间防抖

即使刷新为空（no-op），基于时间的防抖也会触发。

状态生命周期
---------------

::

   创建 Streamer
   → _state = get_verbose_state(channel_id)
   → _turn_index = -1, _pending = []

   首次 push(segment, turn_index=0)
   → turn_index 变化（-1 → 0）
   → _flush() → _pending 为空，不发送任何内容
   → _pending.append(segment)
   → 时间检查 → _flush()
       → text = "".join(_pending)
       → _build_card(text) → card_json
       → client.send_interactive_card() → msg_id
       → _state.streaming_card_id = msg_id
       → _pending.clear(), _pending_chars = 0

   同一回合内的后续 push
   → turn_index 未变化
   → _pending.append(segment)
   → 时间检查 → _flush() → client.patch_message(msg_id, ...)
       → 飞书就地更新卡片

   回合推进：push(segment, turn_index=1)
   → turn_index 变化（0 → 1）
   → _flush() → 发送回合 0 的卡片，设置 streaming_card_id = None
   → _turn_index = 1, _pending = [segment]
   → 下次刷新 → 新卡片通过 send_interactive_card() 发送

调用栈
-----------

新回合的首条消息
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   网关发出 AgentMessageEvent
   → main.py:on_message(event)
   → streamer.push(event.text, turn_index=event.turn_index)
       → turn_index 变化? → _flush()  [清空 pending，不发送]
       → _pending.append(text)
       → _pending_chars += len(text)
       → len >= 50 or chars >= 8000? → 刷新
       → now - last_flush >= 2500? → 刷新
           → _flush()
               → text = "".join(_pending)
               → _build_card(text) → card_json
               → streaming_card_id 为 None
                   → client.send_interactive_card(channel_id, card_json)
                       → POST /im/v1/messages → msg_id
                   → _state.streaming_card_id = msg_id

更新已有卡片（同一回合）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   网关发出下一条 AgentMessageEvent
   → streamer.push(next_text, turn_index=0)
       → _pending.append(next_text)
       → 时间触发 → _flush()
           → _state.streaming_card_id 已设置 → patch
           → client.patch_message(msg_id, card_json)
               → PATCH /im/v1/messages/{msg_id}
               → 飞书就地替换卡片内容

会话取消绑定时 Streamer 重置
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   handlers/callback 或 handlers/message → 取消绑定流程
   → state.reset_channel_state(channel_id)
       → _verbose_states.pop(channel_id)
       → _toolbar_states.pop(channel_id)

或直接：

::

   VerboseCardStreamer.reset()
   → _pending.clear(), _pending_chars = 0
   → _state.streaming_card_id = None
   → _turn_index = -1
