"""WebSocket-backed gateway proxy for unified-icc.

CCLark handlers historically talked directly to ``UnifiedICC``. This proxy
keeps that small gateway surface but forwards all session operations to the
standalone unified-icc WebSocket API server.
"""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

import structlog
import websockets

from unified_icc.gateway import WindowInfo
from unified_icc.window_state_store import window_store

logger = structlog.get_logger()


@dataclass
class _LocalBinding:
    channel_id: str
    window_id: str
    display_name: str = ""
    provider: str = "claude"
    cwd: str = ""
    session_id: str = ""


class _LocalChannelRouter:
    """Small in-process mirror of unified-icc channel bindings."""

    def __init__(self) -> None:
        self._channel_to_window: dict[str, str] = {}
        self._window_to_channels: dict[str, set[str]] = {}

    def bind(self, channel_id: str, window_id: str) -> None:
        old_window = self._channel_to_window.get(channel_id)
        if old_window:
            self._window_to_channels.get(old_window, set()).discard(channel_id)
        self._channel_to_window[channel_id] = window_id
        self._window_to_channels.setdefault(window_id, set()).add(channel_id)

    def unbind(self, channel_id: str) -> None:
        window_id = self._channel_to_window.pop(channel_id, "")
        if window_id:
            channels = self._window_to_channels.get(window_id)
            if channels is not None:
                channels.discard(channel_id)
                if not channels:
                    self._window_to_channels.pop(window_id, None)

    def unbind_window(self, window_id: str) -> None:
        for channel_id in list(self._window_to_channels.get(window_id, set())):
            self.unbind(channel_id)

    def resolve_window(self, channel_id: str) -> str | None:
        return self._channel_to_window.get(channel_id)

    def resolve_channels(self, window_id: str) -> list[str]:
        return sorted(self._window_to_channels.get(window_id, set()))

    def iter_channel_bindings(self) -> list[tuple[str, str, str]]:
        return [(cid, wid, "") for cid, wid in sorted(self._channel_to_window.items())]


class ICCWebSocketGateway:
    """Compatibility gateway that talks to unified-icc over WebSocket."""

    def __init__(
        self,
        ws_url: str,
        *,
        api_key: str = "",
        reconnect_interval: float = 3.0,
    ) -> None:
        self.ws_url = ws_url
        self.api_key = api_key
        self.reconnect_interval = reconnect_interval
        self.channel_router = _LocalChannelRouter()
        self._bindings: dict[str, _LocalBinding] = {}
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._message_callbacks: list[Callable[[Any], Any]] = []
        self._status_callbacks: list[Callable[[Any], Any]] = []
        self._hook_callbacks: list[Callable[[Any], Any]] = []
        self._window_change_callbacks: list[Callable[[Any], Any]] = []
        self._running = False
        self._connected = asyncio.Event()
        self._ws: Any = None
        self._task: asyncio.Task[None] | None = None
        self._send_lock = asyncio.Lock()

    async def start(self) -> None:
        """Connect to unified-icc and start receiving events."""
        self._running = True
        self._task = asyncio.create_task(self._connect_loop())
        await asyncio.wait_for(self._connected.wait(), timeout=30)
        await self._hydrate_sessions()
        logger.info("Connected to unified-icc WebSocket: %s", self.ws_url)

    async def stop(self) -> None:
        """Close the WebSocket connection and fail outstanding requests."""
        self._running = False
        if self._ws is not None:
            await self._ws.close()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._fail_pending(RuntimeError("ICC WebSocket stopped"))

    async def _connect_loop(self) -> None:
        while self._running:
            try:
                async with websockets.connect(
                    self._url_with_token(),
                    ping_interval=30,
                    open_timeout=30,
                ) as ws:
                    self._ws = ws
                    self._connected.set()
                    async for raw in ws:
                        await self._handle_raw(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                if self._running:
                    logger.warning("ICC WebSocket disconnected: %s", exc)
            finally:
                self._connected.clear()
                self._ws = None
                self._fail_pending(RuntimeError("ICC WebSocket disconnected"))
            if self._running:
                await asyncio.sleep(self.reconnect_interval)

    def _url_with_token(self) -> str:
        if not self.api_key:
            return self.ws_url
        sep = "&" if "?" in self.ws_url else "?"
        return f"{self.ws_url}{sep}{urlencode({'token': self.api_key})}"

    async def _handle_raw(self, raw: str | bytes) -> None:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid ICC WS JSON: %r", raw[:120])
            return

        request_id = msg.get("request_id", "")
        if request_id and request_id in self._pending:
            fut = self._pending.pop(request_id)
            if not fut.done():
                fut.set_result(msg)
            return

        await self._dispatch_event(msg)

    async def _dispatch_event(self, msg: dict[str, Any]) -> None:
        msg_type = msg.get("type", "")
        if msg_type == "agent.message":
            self._update_bindings_from_event(msg)
            messages = [SimpleNamespace(**m) for m in msg.get("messages", [])]
            event = SimpleNamespace(
                window_id=msg.get("window_id", ""),
                session_id=msg.get("session_id", ""),
                messages=messages,
                channel_ids=list(msg.get("channel_ids", []) or []),
            )
            await self._run_callbacks(self._message_callbacks, event)
        elif msg_type == "agent.status":
            self._update_bindings_from_event(msg)
            event = SimpleNamespace(
                window_id=msg.get("window_id", ""),
                session_id=msg.get("session_id", ""),
                status=msg.get("status", ""),
                display_label=msg.get("display_label", ""),
                channel_ids=list(msg.get("channel_ids", []) or []),
                provider=msg.get("provider", ""),
                working_dir="",
            )
            await self._run_callbacks(self._status_callbacks, event)
        elif msg_type == "hook.event":
            event = SimpleNamespace(
                window_id=msg.get("window_id", ""),
                event_type=msg.get("event_type", ""),
                hook_name=msg.get("event_type", ""),
                session_id=msg.get("session_id", ""),
                data=msg.get("data", {}),
                message=str(msg.get("data", {}).get("message", "")),
            )
            await self._run_callbacks(self._hook_callbacks, event)
        elif msg_type == "window.change":
            self._remember_window_change(msg)
            event = SimpleNamespace(
                window_id=msg.get("window_id", ""),
                change_type=msg.get("change_type", ""),
                provider=msg.get("provider", ""),
                cwd=msg.get("cwd", ""),
                display_name=msg.get("display_name", ""),
            )
            await self._run_callbacks(self._window_change_callbacks, event)

    async def _run_callbacks(self, callbacks: list[Callable[[Any], Any]], event: Any) -> None:
        for callback in callbacks:
            result = callback(event)
            if asyncio.iscoroutine(result):
                await result

    def _update_bindings_from_event(self, msg: dict[str, Any]) -> None:
        window_id = msg.get("window_id", "")
        if not window_id:
            return
        for channel_id in msg.get("channel_ids", []) or []:
            self.bind_channel(channel_id, window_id)
            binding = self._bindings.setdefault(
                window_id,
                _LocalBinding(channel_id=channel_id, window_id=window_id),
            )
            binding.channel_id = channel_id
            binding.session_id = msg.get("session_id", binding.session_id)
            binding.provider = msg.get("provider", binding.provider)
            self._mirror_window_store(binding)

    def _remember_window_change(self, msg: dict[str, Any]) -> None:
        window_id = msg.get("window_id", "")
        if not window_id:
            return
        binding = self._bindings.setdefault(
            window_id,
            _LocalBinding(channel_id="", window_id=window_id),
        )
        binding.provider = msg.get("provider", binding.provider)
        binding.cwd = msg.get("cwd", binding.cwd)
        binding.display_name = msg.get("display_name", binding.display_name)
        self._mirror_window_store(binding)

    def _mirror_window_store(self, binding: _LocalBinding) -> None:
        state = window_store.get_window_state(binding.window_id)
        state.channel_id = binding.channel_id or state.channel_id
        state.provider_name = binding.provider or state.provider_name
        state.cwd = binding.cwd or state.cwd
        state.session_id = binding.session_id or state.session_id
        state.window_name = binding.display_name or state.window_name
        window_store.mark_window_created(binding.window_id)

    def _fail_pending(self, exc: Exception) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()

    async def _request(
        self,
        msg_type: str,
        *,
        wait: bool = True,
        timeout: float = 30.0,
        **payload: Any,
    ) -> dict[str, Any]:
        await self._connected.wait()
        request_id = payload.pop("request_id", "") or uuid.uuid4().hex
        msg = {"type": msg_type, "request_id": request_id, **payload}
        fut: asyncio.Future[dict[str, Any]] | None = None
        if wait:
            fut = asyncio.get_running_loop().create_future()
            self._pending[request_id] = fut
        async with self._send_lock:
            if self._ws is None:
                raise RuntimeError("ICC WebSocket is not connected")
            await self._ws.send(json.dumps(msg))
        if not wait:
            return {}
        assert fut is not None
        reply = await asyncio.wait_for(fut, timeout=timeout)
        if reply.get("type") == "error":
            raise RuntimeError(reply.get("message", "unified-icc request failed"))
        return reply

    async def _hydrate_sessions(self) -> None:
        try:
            reply = await self._request("session.list")
        except Exception:
            logger.exception("Failed to hydrate unified-icc sessions")
            return
        for item in reply.get("sessions", []):
            channel_id = item.get("channel_id", "")
            window_id = item.get("window_id", "")
            if not channel_id or not window_id:
                continue
            self.bind_channel(channel_id, window_id)
            binding = _LocalBinding(
                channel_id=channel_id,
                window_id=window_id,
                display_name=item.get("display_name", ""),
                provider=item.get("provider", "claude"),
                cwd=item.get("cwd", ""),
                session_id=item.get("session_id", ""),
            )
            self._bindings[window_id] = binding
            self._mirror_window_store(binding)

    async def create_channel_window(
        self,
        channel_id: str,
        work_dir: str,
        *,
        provider: str = "claude",
        mode: str = "normal",
    ) -> WindowInfo:
        """Create and bind a unified-icc session to an external channel id."""
        reply = await self._request(
            "session.create",
            channel_id=channel_id,
            work_dir=work_dir,
            provider=provider,
            mode=mode,
        )
        window_id = reply["window_id"]
        self.bind_channel(channel_id, window_id)
        binding = _LocalBinding(
            channel_id=channel_id,
            window_id=window_id,
            display_name=reply.get("display_name", ""),
            provider=reply.get("provider", provider),
            cwd=reply.get("cwd", work_dir),
            session_id=reply.get("session_id", ""),
        )
        self._bindings[window_id] = binding
        self._mirror_window_store(binding)
        return WindowInfo(
            window_id=window_id,
            display_name=binding.display_name,
            provider=binding.provider,
            cwd=binding.cwd,
            session_id=binding.session_id,
        )

    async def create_window(
        self,
        work_dir: str,
        provider: str = "claude",
        mode: str = "normal",
    ) -> WindowInfo:
        channel_id = f"cclark:unbound:{uuid.uuid4().hex}"
        return await self.create_channel_window(
            channel_id,
            work_dir,
            provider=provider,
            mode=mode,
        )

    async def kill_channel_windows(self, channel_id: str) -> list[str]:
        window_id = self.resolve_window(channel_id)
        await self._request("session.close", channel_id=channel_id)
        if window_id:
            self.channel_router.unbind(channel_id)
            self._bindings.pop(window_id, None)
            window_store.remove_window(window_id)
            window_store.remove_created_window(window_id)
            return [window_id]
        return []

    async def kill_window(self, window_id: str) -> None:
        channels = self.resolve_channels(window_id)
        for channel_id in channels:
            await self.kill_channel_windows(channel_id)

    async def list_windows(self) -> list[WindowInfo]:
        reply = await self._request("session.list")
        result: list[WindowInfo] = []
        for item in reply.get("sessions", []):
            channel_id = item.get("channel_id", "")
            window_id = item.get("window_id", "")
            if channel_id and window_id:
                self.bind_channel(channel_id, window_id)
            result.append(
                WindowInfo(
                    window_id=window_id,
                    display_name=item.get("display_name", ""),
                    provider=item.get("provider", "claude"),
                    cwd=item.get("cwd", ""),
                    session_id=item.get("session_id", ""),
                )
            )
        return result

    async def list_orphaned_agent_windows(self) -> list[WindowInfo]:
        return []

    async def send_to_window(self, window_id: str, text: str) -> None:
        channel_id = self._channel_for_window(window_id)
        await self._request("input", wait=False, channel_id=channel_id, text=text)

    async def send_input_to_window(
        self,
        window_id: str,
        text: str,
        *,
        enter: bool = True,
        literal: bool = True,
        raw: bool = False,
    ) -> None:
        channel_id = self._channel_for_window(window_id)
        await self._request(
            "input",
            wait=False,
            channel_id=channel_id,
            text=text,
            enter=enter,
            literal=literal,
            raw=raw,
        )

    async def send_key(self, window_id: str, key: str) -> None:
        channel_id = self._channel_for_window(window_id)
        await self._request("key", wait=False, channel_id=channel_id, key=key)

    async def capture_pane(self, window_id: str) -> str:
        channel_id = self._channel_for_window(window_id)
        reply = await self._request("capture.pane", channel_id=channel_id)
        return reply.get("content", "")

    async def capture_screenshot(self, window_id: str) -> bytes:
        channel_id = self._channel_for_window(window_id)
        reply = await self._request("capture.screenshot", channel_id=channel_id)
        image = reply.get("image_base64", "")
        return base64.b64decode(image) if image else b""

    def _channel_for_window(self, window_id: str) -> str:
        channels = self.resolve_channels(window_id)
        if not channels:
            raise RuntimeError(f"No channel bound to window {window_id}")
        return channels[0]

    def bind_channel(self, channel_id: str, window_id: str) -> None:
        self.channel_router.bind(channel_id, window_id)
        binding = self._bindings.setdefault(
            window_id,
            _LocalBinding(channel_id=channel_id, window_id=window_id),
        )
        binding.channel_id = channel_id
        self._mirror_window_store(binding)

    def unbind_channel(self, channel_id: str) -> None:
        self.channel_router.unbind(channel_id)

    def resolve_window(self, channel_id: str) -> str | None:
        return self.channel_router.resolve_window(channel_id)

    def resolve_channels(self, window_id: str) -> list[str]:
        return self.channel_router.resolve_channels(window_id)

    def on_message(self, callback: Callable[[Any], Any]) -> None:
        self._message_callbacks.append(callback)

    def on_status(self, callback: Callable[[Any], Any]) -> None:
        self._status_callbacks.append(callback)

    def on_hook_event(self, callback: Callable[[Any], Any]) -> None:
        self._hook_callbacks.append(callback)

    def on_window_change(self, callback: Callable[[Any], Any]) -> None:
        self._window_change_callbacks.append(callback)
