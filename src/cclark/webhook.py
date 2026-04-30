"""FastAPI health-check HTTP server.

When running in WebSocket mode (the default) all events arrive via the
WebSocket connection in ws_client.py. This module retains only the health
endpoint so the deployment can still answer load-balancer / uptime-monitor
probes. One uvicorn server is started per app (different ports in
multi-app mode) from main._main().
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="cclark health")


@app.get("/health")
async def health() -> dict[str, str]:
    """Load-balancer / uptime-monitor probe endpoint. Always returns {"status": "ok"}."""
    return {"status": "ok"}
