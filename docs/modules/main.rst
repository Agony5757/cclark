main — CLI 入口点
=======================

源码：src/cclark/main.py

``pyproject.toml`` 中定义的 CLI 脚本：

.. code-block:: toml

   [project.scripts]
   cclark = "cclark.main:main"

启动命令：

.. code-block:: bash

   cclark

启动序列
------------

1. 加载 ``~/.cclark/config.yaml`` 或环境变量回退配置。
2. 为默认 app 创建 ``FeishuClient`` 和 ``FeishuAdapter``。
3. 启动 ``UnifiedICC``，连接 tmux、启动 session monitor、加载持久化状态。
4. 注册 gateway 回调，把 ``AgentMessageEvent`` / ``StatusEvent`` 转换为飞书文本或卡片。
5. 调用 ``set_handlers(gateway, adapter)``，让 message handler 能创建窗口、转发文本、发送回复。
6. 启动 ``FeishuWSClient`` 长连接以接收飞书消息事件。
7. 启动本地 health endpoint。

网关回调
------------

``on_message`` 处理智能体输出：

- thinking 消息进入 ``ThinkingCardStreamer``。
- verbose on 时 regular output 进入 ``VerboseCardStreamer``。
- verbose off 时 regular output 发送为普通文本。
- marker-wrapped thinking 内容会被防御性拦截，避免作为普通文本泄漏。

``on_status`` 处理终端交互状态：

- Claude permission prompt 渲染为 ``Claude needs input`` 飞书卡片。
- 当前 card action callback 尚未接入；用户通过普通回复 ``1`` / ``2`` / ``3`` 选择。

关闭行为
------------

关闭时会停止 Feishu WebSocket、停止 unified-icc gateway、flush state，并关闭 httpx client。
shutdown 过程是幂等的，避免信号和 server stop 同时触发重复 flush。

