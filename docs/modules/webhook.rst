webhook — Legacy FastAPI App
============================

源码：src/cclark/webhook.py

当前主入口是 ``ws_client.py`` 的飞书 WebSocket 长连接；``webhook.py`` 不再是主要消息入口。
该模块保留为 FastAPI 兼容层和 health endpoint 相关代码的历史实现参考。

当前运行模型
------------

- 飞书消息事件：通过 WebSocket 长连接进入 ``FeishuWSClient``。
- 本地 HTTP：仅用于 health-check，不要求公网 Webhook URL。
- 卡片 action callback：当前 Claude approval flow 未使用飞书按钮回调，用户通过普通文本回复 ``1`` / ``2`` / ``3``。

历史 webhook 模型
-----------------

旧模型曾通过以下路由接收飞书 POST：

- ``GET /health`` — 存活探针
- ``POST /webhook/event`` — 飞书事件 Webhook
- ``POST /webhook/callback`` — 卡片按钮点击

如果未来重新启用公网 webhook，需要重新验证事件鉴权、URL challenge、卡片 callback 和当前 WebSocket 路径之间的状态一致性。

