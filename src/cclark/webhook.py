"""FastAPI health-check server.

When running in WebSocket mode (the default) the webhook endpoints are
removed — all events arrive via the WebSocket connection in ws_client.py.
This module retains only the health endpoint so the deployment can still
answer load-balancer / uptime-monkey probes.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="cclark health")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
