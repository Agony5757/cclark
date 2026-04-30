handlers — 事件处理器模块
=================================

源码：src/cclark/handlers/

三个处理器模块，均为文本驱动（无卡片按钮回调）：

handlers/message.py — 入站文本路由
-------------------------------------

路由来自飞书的每条文本消息。充当交通指挥官。

消息流程
~~~~~~~~~~~~

::

   FeishuWSClient._dispatch_event()
   → event_parsers.parse_message_event()
   → FeishuMessageEvent
   → handlers/message.py:handle_message(event)
       → #new or #help?
           → _handle_hash_new() / _handle_help()
       → session_creation.handle_session_input() 返回 True?
           → wizard consumed the message
       → text.startswith("#")?
           → _handle_hash_command()
       → gateway.channel_router.resolve_window(channel_id) → window_id | None
           → window_id 为 None → _handle_new_channel()
               → send help text
           → 有绑定窗口
               → _handle_terminal_prompt_reply() 返回 True?
                   → prompt reply consumed the message
               → _advance_channel_turn()
               → gateway.send_to_window(window_id, text)
                   → tmux send-keys

# 命令
~~~~~~~~~~~~~~~

所有 ``#`` 前缀为 cclark 专用命令：

``#new``
    杀掉当前会话，进入目录/提供方/模式向导

``#help``
    发送帮助文本

``#status``
    显示当前会话的窗口、提供方、模式、verbose 状态

``#session list``
    列出所有活跃的 cclark 管理的 tmux 会话

``#session close <window_id>``
    关闭指定的 tmux 会话

``#verbose on|off``
    切换详细流式模式（显示/隐藏 thinking 内容）

``#screenshot``
    捕获并发送当前 tmux 窗格截图

终端提示分类
~~~~~~~~~~~~~~~~~~~~~

当 Claude 显示交互式 TUI 提示时，状态被捕获并分类：

* ``plan_decision`` — "Would you like to proceed?" + "Tell Claude what to change"
* ``permission`` — "Do you want to proceed?" / "Allow X to Y"
* ``selection`` — "Enter to select" + 复选框/箭头字符

用户直接回复编号即可。选项 3（plan mode "Tell Claude what to change"）为两步流程：
先发送 ``3``（不回车），再发送反馈文本。

handlers/session_creation.py — 会话创建流程
-------------------------------------------------

实现多步文本向导：目录浏览 → 提供方选择 → 模式选择 → 窗口创建。

状态机
~~~~~~~~~~~~~~~~~~~~~

::

   STATE_BROWSE ──(ok)─────► STATE_PROVIDER ──(provider)──► STATE_MODE ──(mode)──► [窗口创建]

每个用户的浏览状态（``_sessions[user_id]``）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   {
       "phase": "browse" | "provider" | "mode",
       "path": "/home/user/project",
       "channel_id": "feishu:chat:thread",
       "provider": "claude",
       "original_text": "#new",
   }

第 1 步 — 目录浏览（STATE_BROWSE）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   _format_dir_listing(path, user_id)
       → MRU 目录（#select 快捷命令）
       → 子目录列表（最多 20 项）
       → 导航命令提示
   → adapter.send_text(channel_id, listing)

接受输入：数字序号、目录名匹配、 ``..`` 、 ``ok`` 、 ``cancel`` 、
``#mkdir <name>`` 、 ``#select <path>``

第 2 步 — 提供方选择（STATE_PROVIDER）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   "Select provider:\n  1. claude  2. codex  3. gemini  4. pi  5. shell"

接受输入：数字（1-5）或不区分大小写的名称。 ``shell`` 跳过模式选择。

第 3 步 — 模式选择（STATE_MODE）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   "Select mode:\n  1. standard  2. yolo"

第 4 步 — 窗口创建（_create_window）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

   gateway.create_window(path, provider=provider, mode=approval_mode)
   → gateway.bind_channel(channel_id, window_id)
   → window_store record + mark_window_created()
   → monitor.detect_session_id(window_id)
   → forward pending original_text
   → _clear_state(user_id)

handlers/screenshot.py — 窗格截图
--------------------------------------

::

   message._handle_screenshot(channel_id)
   → screenshot.handle_screenshot_request(channel_id, gateway, adapter)
       → gateway.capture_screenshot(window_id)
           → FeishuClient.upload_image() → image_key
           → FeishuClient.send_image("image", ...)
