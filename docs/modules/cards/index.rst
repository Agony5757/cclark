cards — 飞书卡片构建器
===========================

.. toctree::
   :maxdepth: 1

   streaming

源码：src/cclark/cards/

所有卡片构建工具。每个模块生成一个飞书卡片 JSON 字符串
（``json.dumps`` 输出），可直接通过 ``FeishuClient`` 发送。

飞书卡片 schema
-------------------

所有卡片遵循飞书交互卡片 schema：

.. code-block:: json

   {
     "config": {"wide_screen_mode": true},
     "header": {
       "title": {"tag": "plain_text", "content": "Title"},
       "template": "blue"
     },
     "elements": [
       {"tag": "markdown", "content": "..."},
       {"tag": "action", "children": [
         {"tag": "button", "text": {...}, "action_type": "interactive", "value": {"action": "..."}}
       ]}
     ]
   }

支持的 header 模板：``blue``、``wathet``、``turquoise``、``green``、
``yellow``、``orange``、``red``、``purple``、``indigo``、``grey``。

cards/builder — FeishuCardBuilder
---------------------------------

``CardPayload`` 和 ``InteractivePrompt`` 的核心构建器：

.. code-block:: python

   FeishuCardBuilder.build_card(CardPayload(title="...", body="...", color="blue"))
   # → json.dumps(card_dict)

Markdown 转换（``_md``）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- ``**bold**`` → ``<strong>bold</strong>``
- 反引号代码段 → ``<code>code</code>``
- ``&``、``<``、``>`` 转义为 HTML 实体

cards/output — 智能体输出卡片
----------------------------------

.. code-block:: python

   build_output_card(title, body, provider, color, actions)
   # → FeishuCardBuilder.build_card(CardPayload(...))

   build_code_output_card(title, code, language, provider, max_chars)
   # → json.dumps({header, elements: [{tag: "markdown", content: "```lang\ncode\n```"}]})

cards/status — 会话状态卡片
-----------------------------------

.. code-block:: python

   build_status_card(
       title="Claude Session",
       window_id="emdash-claude-main-abc",
       provider="claude",
       status="running",
       working_dir="/home/user/project",
       actions=[{"label": "Kill", "action": "sess:kill:window_id"}],
   )
   # → json.dumps(card_dict)

cards/prompt — 权限/提问卡片
--------------------------------------------

.. code-block:: python

   build_permission_card(title, body, options, cancel_text)
   # → 带批准按钮的飞书交互卡片

   build_question_card(title, question, options, cancel_text)
   # → 带多选按钮的飞书交互卡片

cards/toolbar — 工具栏网格构建器
-------------------------------------

.. code-block:: python

   build_toolbar_card(window_id, provider, toolbar_config, status_label)
   # → 带操作按钮网格的飞书交互卡片
   # 每个按钮 value = f"tb:{window_id}:{action_name}"

飞书 markdown 限制
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

飞书 markdown 不支持 ``<pre>`` 或 ``<code>`` 标签中的 `` ```language`` 代码围栏。
``cards/output.py:build_code_output_card`` 通过在 ``<markdown>`` 元素标签内
使用 `` ``` `` markdown 语法（由飞书渲染为代码块）来绕过此限制，
但某些飞书版本对此支持不稳定。对于超过几行的代码输出，
建议改用文件消息发送。

cards/streaming — VerboseCardStreamer
--------------------------------------

详见 `cards/streaming.rst <streaming.html>`_ 的完整调用栈文档。

卡片大小限制
----------------

飞书强制每张卡片最大约 30 KB。``FeishuCardBuilder._truncate_code``
将代码块截断到 2000 字符。``VerboseCardStreamer._build_card``
在文本超过 28 KB 时添加截断警告。
