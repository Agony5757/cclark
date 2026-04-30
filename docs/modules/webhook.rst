webhook — HTTP Health-Check Server
====================================

源码：src/cclark/webhook.py

当前实现仅有一个 FastAPI 端点：

::

   GET /health  →  {"status": "ok"}

所有飞书事件通过 WebSocket 长连接进入 ``FeishuWSClient``（ws_client.py）。
webhook.py 只负责回答负载均衡器 / 存活探针探测。

启动方式
------------

main._main() 为每个 app 配置创建一个 uvicorn 实例（不同端口）：
``uvicorn.run(health_app, host="0.0.0.0", port=health_port)``。
