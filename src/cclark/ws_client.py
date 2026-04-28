"""Feishu WebSocket long-connection client.

Implements the Feishu proprietary binary protocol:
  1. POST /callback/ws/endpoint → get wss:// URL
  2. Connect to WebSocket, receive protobuf Frames
  3. Decode Frames → dispatch message events to registered handlers
  4. Send pong frames for ping, auto-reconnect on disconnect
"""

from __future__ import annotations

import asyncio
import json
import random
import structlog
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import websockets

from cclark.config import config
from cclark.event_parsers import parse_message_event

logger = structlog.get_logger()

# ── Protocol constants ────────────────────────────────────────────────────────

_WS_ENDPOINT_URI = "/callback/ws/endpoint"
_BASE_URL = "https://open.feishu.cn"

# Frame method (protobuf field 4, wire varint)
_METHOD_CONTROL = 0
_METHOD_DATA = 1

# Header keys
_HDR_TYPE = "type"
_TYPE_EVENT = "event"
_TYPE_PING = "ping"
_TYPE_PONG = "pong"

# ── Protobuf encoding helpers ────────────────────────────────────────────────

# Wire types: 0=varint, 2=length-delimited, 5=32-bit
_WIRE_VARINT = 0
_WIRE_64BIT = 1
_WIRE_LENGTH_DELIMITED = 2
_WIRE_32BIT = 5

# Protobuf field numbers in Frame
_FIELD_SEQ_ID = 1
_FIELD_LOG_ID = 2
_FIELD_SERVICE = 3
_FIELD_METHOD = 4
_FIELD_HEADERS = 5
_FIELD_ENCODING = 6
_FIELD_TYPE = 7
_FIELD_PAYLOAD = 8

# Protobuf field numbers in Header (nested)
_HDR_FIELD_KEY = 1
_HDR_FIELD_VALUE = 2

_VARINT_7BIT_MASK = 0x7F
_VARINT_CONTINUATION_BIT = 0x80
_UINT64_MASK = 0xFFFFFFFFFFFFFFFF


def _encode_varint(value: int) -> bytes:
    if value < 0:
        # Python negative int → two's complement varint
        value &= _UINT64_MASK
    result = bytearray()
    while value > _VARINT_7BIT_MASK:
        result.append((value & _VARINT_7BIT_MASK) | _VARINT_CONTINUATION_BIT)
        value >>= 7
    result.append(value & _VARINT_7BIT_MASK)
    return bytes(result)


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        b = data[pos]
        pos += 1
        result |= (b & _VARINT_7BIT_MASK) << shift
        if not (b & _VARINT_CONTINUATION_BIT):
            break
        shift += 7
    return result, pos


def _encode_field(field_num: int, wire_type: int, encoded: bytes) -> bytes:
    return _encode_varint((field_num << 3) | wire_type) + encoded


def _encode_string(value: str | bytes) -> bytes:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return _encode_varint(len(value)) + value


def _encode_frame_headers(headers: list[tuple[str, str]]) -> bytes:
    out = b""
    for key, value in headers:
        key_bytes = key.encode("utf-8")
        value_bytes = value.encode("utf-8")
        # Header { key: string(2), value: string(2) }
        out += _encode_field(_HDR_FIELD_KEY, _WIRE_LENGTH_DELIMITED,
                             _encode_varint(len(key_bytes)) + key_bytes)
        out += _encode_field(_HDR_FIELD_VALUE, _WIRE_LENGTH_DELIMITED,
                             _encode_varint(len(value_bytes)) + value_bytes)
    return out


def encode_frame(
    method: int,
    payload: bytes,
    headers: list[tuple[str, str]],
    service_id: int,
    seq_id: int = 0,
) -> bytes:
    """Encode a binary protobuf Frame."""
    out = b""
    # field 1: SeqID (varint)
    out += _encode_field(_FIELD_SEQ_ID, _WIRE_VARINT, _encode_varint(seq_id))
    # field 2: LogID (varint, always 0)
    out += _encode_field(_FIELD_LOG_ID, _WIRE_VARINT, _encode_varint(0))
    # field 3: Service (varint)
    out += _encode_field(_FIELD_SERVICE, _WIRE_VARINT, _encode_varint(service_id))
    # field 4: Method (varint)
    out += _encode_field(_FIELD_METHOD, _WIRE_VARINT, _encode_varint(method))
    # field 5: Headers (length-delimited)
    hdrs_bytes = _encode_frame_headers(headers)
    out += _encode_field(_FIELD_HEADERS, _WIRE_LENGTH_DELIMITED,
                          _encode_varint(len(hdrs_bytes)) + hdrs_bytes)
    # field 6: PayloadEncoding (length-delimited, empty)
    out += _encode_field(_FIELD_ENCODING, _WIRE_LENGTH_DELIMITED, _encode_varint(0))
    # field 7: PayloadType (length-delimited, empty)
    out += _encode_field(_FIELD_TYPE, _WIRE_LENGTH_DELIMITED, _encode_varint(0))
    # field 8: Payload (length-delimited)
    out += _encode_field(_FIELD_PAYLOAD, _WIRE_LENGTH_DELIMITED,
                          _encode_varint(len(payload)) + payload)
    return out


def decode_frame(data: bytes) -> tuple[dict[str, str], bytes, int]:
    """Decode a binary protobuf Frame.

    Returns (headers_dict, payload_bytes, service_id).
    """
    pos = 0
    end = len(data)
    headers: dict[str, str] = {}
    payload = b""
    service_id = 0

    while pos < end:
        b = data[pos]
        pos += 1
        field_and_wire = b >> 3
        wire = b & 7

        if wire == _WIRE_VARINT:
            val, pos = _decode_varint(data, pos)
        elif wire == _WIRE_LENGTH_DELIMITED:
            length, p2 = _decode_varint(data, pos)
            pos = p2
            val = data[pos : pos + length]
            pos += length
        else:
            val = None

        if field_and_wire == _FIELD_SERVICE:
            service_id = int(val) if isinstance(val, int) else 0
        elif field_and_wire == _FIELD_HEADERS:  # nested Header{key,value}
            hp = 0
            hdr_list: list[tuple[str, str]] = []
            assert isinstance(val, bytes), "Headers field must be length-delimited bytes"
            headers_bytes: bytes = val
            while hp < len(headers_bytes):
                b2 = headers_bytes[hp]
                hp += 1
                if (b2 >> 3) == _HDR_FIELD_KEY and (b2 & 7) == _WIRE_LENGTH_DELIMITED:
                    l2, hp2 = _decode_varint(headers_bytes, hp)
                    hp = hp2
                    key = headers_bytes[hp : hp + l2].decode("utf-8")
                    hp += l2
                    b3 = headers_bytes[hp]
                    hp += 1
                    if (b3 >> 3) == _HDR_FIELD_VALUE and (b3 & 7) == _WIRE_LENGTH_DELIMITED:
                        l3, hp3 = _decode_varint(headers_bytes, hp)
                        hp = hp3
                        value = headers_bytes[hp : hp + l3].decode("utf-8")
                        hp += l3
                        hdr_list.append((key, value))
                    else:
                        break
                else:
                    break
            headers = dict(hdr_list)
        elif field_and_wire == _FIELD_PAYLOAD:
            payload = val if isinstance(val, bytes) else b""

    return headers, payload, service_id


# ── Ping frame (pre-built, stateless) ───────────────────────────────────────

_ping_frame: bytes | None = None


def _get_ping_frame(service_id: int) -> bytes:
    global _ping_frame
    if _ping_frame is None:
        _ping_frame = encode_frame(_METHOD_CONTROL, b"", [(_HDR_TYPE, _TYPE_PING)], service_id)
    return _ping_frame


# ── Event types from the protocol ────────────────────────────────────────────


@dataclass
class WSClientConfig:
    """Config values needed by the WebSocket client."""

    app_id: str
    app_secret: str
    ping_interval: float
    reconnect_interval: float
    reconnect_nonce: float
    service_id: int


# ── Module-level state ───────────────────────────────────────────────────────

_message_handler: Any | None = None
_seen_events: set[str] = set()
_seen_messages: set[str] = set()


def register_message_handler(handler: Any) -> None:
    global _message_handler
    _message_handler = handler


# ── WebSocket client ─────────────────────────────────────────────────────────


class FeishuWSClient:
    """Feishu WebSocket long-connection client with auto-reconnect."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        app_name: str = "default",
        ping_interval: float = 90.0,
        reconnect_interval: float = 5.0,
        reconnect_nonce: float = 3.0,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._app_name = app_name
        self._ping_interval = ping_interval
        self._reconnect_interval = reconnect_interval
        self._reconnect_nonce = reconnect_nonce
        self._service_id = 0
        self._running = False
        self._ws: Any = None
        self._ping_task: asyncio.Task[None] | None = None
        self._receive_task: asyncio.Task[None] | None = None

    # ── Public API ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the WebSocket client. Blocks until stopped."""
        self._running = True
        reconnect_count = 0
        while self._running:
            try:
                await self._connect_and_receive()
            except asyncio.CancelledError:
                logger.info("WS client cancelled")
                break
            except (OSError, websockets.WebSocketException, ConnectionError) as e:
                if not self._running:
                    break
                reconnect_count += 1
                delay = self._reconnect_interval + random.uniform(0, self._reconnect_nonce)
                logger.warning(
                    "WS disconnected: %s, reconnecting in %.1fs (attempt %d)",
                    e, delay, reconnect_count
                )
                await asyncio.sleep(delay)

    async def stop(self) -> None:
        """Stop the client gracefully."""
        self._running = False
        if self._ws is not None:
            await self._ws.close()
        if self._ping_task:
            self._ping_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._ping_task
        if self._receive_task:
            self._receive_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._receive_task
        logger.info("WS client stopped")

    # ── Internal ────────────────────────────────────────────────────────────

    async def _get_ws_url(self) -> str:
        """Fetch the WebSocket connection URL from Feishu."""
        import httpx
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            resp = await client.post(
                f"{_BASE_URL}{_WS_ENDPOINT_URI}",
                json={"AppID": self._app_id, "AppSecret": self._app_secret},
                headers={"locale": "zh"},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise FeishuWSError(f"endpoint error: {data.get('msg')}")
            url = data["data"]["URL"]
            client_config = data["data"].get("ClientConfig", {})
            # Update timing from server config if provided
            self._ping_interval = client_config.get("PingInterval", self._ping_interval)
            self._reconnect_interval = client_config.get("ReconnectInterval", self._reconnect_interval)
            logger.debug(
                "WS endpoint received: ping_interval=%ds reconnect_interval=%ds",
                self._ping_interval, self._reconnect_interval
            )
            return url

    async def _connect_and_receive(self) -> None:
        """Connect to the WebSocket and run the receive loop."""
        ws_url = await self._get_ws_url()
        _headers, _payload, service_id = await self._handshake(ws_url)
        self._service_id = service_id
        logger.info("WS connected: service_id=%d", service_id)

        # Start ping loop
        self._ping_task = asyncio.create_task(self._ping_loop())

        # Receive loop
        try:
            async for raw in self._ws:
                raw_type = type(raw).__name__
                raw_len = len(raw) if raw else 0
                raw_repr = repr(raw[:32]) if raw else "empty"
                logger.warning("WS recv: type=%s len=%d repr=%s", raw_type, raw_len, raw_repr)
                await self._handle_frame(raw)
        except websockets.ConnectionClosed as e:
            logger.warning("WS connection closed: code=%s reason=%s", e.code, e.reason)
            raise

    async def _handshake(self, ws_url: str) -> tuple[dict[str, str], bytes, int]:
        """Perform WebSocket handshake and return initial frame info."""
        self._ws = await websockets.connect(
            ws_url,
            ping_interval=None,  # We handle ping/pong ourselves at app level
            open_timeout=15,
        )
        # Receive the first frame (usually a handshake/ping)
        raw = await self._ws.recv()
        headers, payload, service_id = decode_frame(raw)
        logger.debug("WS handshake frame: headers=%s payload=%s", headers, payload[:100])
        return headers, payload, service_id

    async def _ping_loop(self) -> None:
        """Send periodic ping frames."""
        while self._running and self._ws is not None and self._ws.open:
            await asyncio.sleep(self._ping_interval)
            if not self._running or self._ws is None or not self._ws.open:
                break
            try:
                await self._ws.send(_get_ping_frame(self._service_id))
                logger.debug("WS ping sent")
            except (OSError, websockets.WebSocketException, ConnectionError) as e:
                logger.warning("WS ping failed, connection may be dead: %s", e)
                break

    async def _handle_frame(self, raw: bytes | str) -> None:
        """Decode a raw frame and dispatch to the appropriate handler."""
        if isinstance(raw, str):
            raw = raw.encode("latin1")
        try:
            headers, payload, _service_id = decode_frame(raw)
        except Exception:
            logger.exception("WS frame decode failed: %r", raw[:50])
            return

        msg_type = headers.get(_HDR_TYPE, "")

        logger.debug(
            "WS frame: type=%r payload_len=%d headers=%s app=%s",
            msg_type, len(payload), headers, self._app_name,
        )

        if msg_type == _TYPE_PING:
            if self._ws and self._ws.open:
                try:
                    await self._ws.send(_get_ping_frame(self._service_id))
                except (OSError, websockets.WebSocketException, ConnectionError) as e:
                    logger.warning("WS pong failed: %s", e)
            return

        if msg_type == _TYPE_PONG:
            logger.debug("WS pong received")
            return

        await self._dispatch_by_type(msg_type, payload)

    async def _handle_decoded_frame(
        self, headers: dict[str, str], payload: bytes
    ) -> None:
        """Dispatch an already-decoded frame (e.g. from the handshake)."""
        msg_type = headers.get(_HDR_TYPE, "")
        await self._dispatch_by_type(msg_type, payload)

    async def _dispatch_by_type(self, msg_type: str, payload: bytes) -> None:
        """Route a frame to the event handler based on type."""
        # Schema 2.0: event type lives in the JSON payload, not binary headers
        if not msg_type and payload:
            msg_type = self._classify_payload(payload)

        if msg_type == _TYPE_EVENT:
            await self._dispatch_event(payload)

    @staticmethod
    def _classify_payload(payload: bytes) -> str:
        """Determine frame type from JSON payload (schema 2.0)."""
        try:
            data: dict[str, Any] = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            return ""
        event_type: str = data.get("header", {}).get("event_type", "")
        if event_type.startswith("im.message."):
            return _TYPE_EVENT
        return ""

    async def _dispatch_event(self, payload: bytes) -> None:
        """Parse and dispatch an inbound message event."""
        if _message_handler is None:
            return
        try:
            data: dict[str, Any] = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning("WS event payload not JSON: %r", payload[:100])
            return

        # Deduplicate by event_id (Feishu may re-deliver)
        event_id = data.get("header", {}).get("event_id", "")
        if event_id:
            if event_id in _seen_events:
                logger.debug("WS duplicate event skipped: %s", event_id)
                return
            _seen_events.add(event_id)
            if len(_seen_events) > 1000:
                _seen_events.clear()

        event = parse_message_event(data)
        if event is None:
            return

        # Also deduplicate by message_id
        if event.message_id and event.message_id in _seen_messages:
            logger.debug("WS duplicate message skipped: %s", event.message_id)
            return
        if event.message_id:
            _seen_messages.add(event.message_id)
            if len(_seen_messages) > 1000:
                _seen_messages.clear()

        if event.user_id == config.bot_user_id:
            return

        # Multi-app auth check
        if config.is_multi_app:
            if not config.is_user_allowed_in_app(event.user_id, self._app_name):
                logger.info(
                    "WS message from unauthorized user %s for app %s",
                    event.user_id, self._app_name,
                )
                return
        elif not config.is_user_allowed(event.user_id):
            logger.info("WS message from unauthorized user %s", event.user_id)
            return

        # Annotate event with app context so handlers know which app this came from
        event._app_name = self._app_name  # type: ignore[attr-defined]

        try:
            await _message_handler(event)
        except Exception:
            logger.exception("WS message handler failed")



class FeishuWSError(Exception):
    """Raised when the Feishu WebSocket endpoint returns an error."""
