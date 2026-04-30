"""httpx-based Feishu REST API client.

Thin wrapper around Feishu's IM API. All outbound communication
(send text, send card, patch card, upload file/image) flows through
FeishuClient.

Token management is lazy and automatic — the tenant_access_token is
fetched on first use and cached until it expires.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

BASE_URL = "https://open.feishu.cn/open-apis"


class FeishuClient:
    """Async Feishu REST API client with automatic token management."""

    def __init__(self, app_id: str, app_secret: str) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._tenant_access_token: str | None = None
        self._token_expires_at: float = 0
        self._http = httpx.AsyncClient(timeout=30.0, trust_env=False)

    async def close(self) -> None:
        await self._http.aclose()

    # ── Token management ──────────────────────────────────────────────────

    async def _get_token(self) -> str:
        """Fetch and cache tenant_access_token. Auto-refreshes before expiry."""
        now = time.monotonic()
        if self._tenant_access_token and now < self._token_expires_at - 60:
            return self._tenant_access_token

        resp = await self._http.post(
            f"{BASE_URL}/auth/v3/tenant_access_token/internal",
            json={"app_id": self._app_id, "app_secret": self._app_secret},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise FeishuAPIError(data.get("msg", "auth failed"), data)
        self._tenant_access_token = str(data["tenant_access_token"])
        self._token_expires_at = now + float(data.get("expire", 7200))
        logger.debug("Feishu token refreshed, expires in %ss", data.get("expire", 7200))
        return self._tenant_access_token

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self._get_token()}"}

    async def _post(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST helper that handles auth, JSON encoding, and error checking."""
        resp = await self._http.post(
            f"{BASE_URL}{path}",
            headers=await self._headers(),
            params=params,
            json=json_data,
            data=data,
            files=files,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != 0:
            raise FeishuAPIError(body.get("msg", "API error"), body)
        return body

    async def _patch(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """PATCH helper that handles auth, JSON encoding, and error checking."""
        resp = await self._http.patch(
            f"{BASE_URL}{path}",
            headers=await self._headers(),
            params=params,
            json=json_data,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != 0:
            raise FeishuAPIError(body.get("msg", "API error"), body)
        return body

    # ── Messaging ───────────────────────────────────────────────────────

    async def send_message(
        self,
        receive_id: str,
        msg_type: str,
        content: str | dict,
    ) -> str:
        """Send a message. Returns message_id.

        Args:
            receive_id: chat_id (uses receive_id_type=chat_id)
            msg_type: "text", "interactive", "image", "file"
            content: string or dict (will be JSON-encoded)
        """
        if isinstance(content, dict):
            content = json.dumps(content)
        body = await self._post(
            "/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            json_data={
                "receive_id": receive_id,
                "msg_type": msg_type,
                "content": content,
            },
        )
        return body["data"]["message_id"]

    async def send_text(self, receive_id: str, text: str) -> str:
        """Send a plain text message."""
        return await self.send_message(receive_id, "text", json.dumps({"text": text}))

    async def send_interactive_card(
        self, receive_id: str, card_json: str
    ) -> str:
        """Send an interactive card message. Returns message_id."""
        return await self.send_message(receive_id, "interactive", card_json)

    async def send_image(
        self, receive_id: str, image_key: str
    ) -> str:
        """Send an image message using an already-uploaded image_key.

        Args:
            receive_id: Feishu chat_id.
            image_key: Image key from a prior upload_image call.
        Returns:
            The sent message_id.
    """
        return await self.send_message(
            receive_id, "image", json.dumps({"image_key": image_key})
        )

    async def send_file(
        self, receive_id: str, file_key: str, file_name: str
    ) -> str:
        """Send a file message using an already-uploaded file_key.

        Args:
            receive_id: Feishu chat_id.
            file_key: File key from a prior upload_file call.
            file_name: Display name for the file.
        Returns:
            The sent message_id.
    """
        return await self.send_message(
            receive_id, "file", json.dumps({"file_key": file_key, "file_name": file_name})
        )

    async def patch_message(self, message_id: str, card_json: str) -> None:
        """Patch an existing interactive card message (in-place update).

        Args:
            message_id: The Feishu message_id of the card to patch.
            card_json: JSON string of the updated card payload.
        """
        if isinstance(card_json, dict):
            card_json = json.dumps(card_json)
        await self._patch(
            f"/im/v1/messages/{message_id}",
            json_data={"content": card_json},
        )

    # ── Media upload ────────────────────────────────────────────────────

    async def upload_image(self, image_bytes: bytes, image_name: str = "image.png") -> str:
        """Upload an image to Feishu.

        Args:
            image_bytes: Raw PNG/JPEG bytes.
            image_name: File name hint (default "image.png").
        Returns:
            Feishu image_key to use with send_image.
        """
        body = await self._post(
            "/im/v1/images",
            data={"image_type": "message"},
            files={
                "image": (image_name, image_bytes, "image/png"),
            },
        )
        return body["data"]["image_key"]

    async def upload_file(
        self,
        file_bytes: bytes,
        file_name: str,
        file_type: str = "stream_file",
    ) -> str:
        """Upload a file to Feishu.

        Args:
            file_bytes: Raw file bytes.
            file_name: File name for the upload.
            file_type: Feishu file type (default "stream_file").
        Returns:
            Feishu file_key to use with send_file.
        """
        body = await self._post(
            "/im/v1/files",
            data={"file_name": file_name, "file_type": file_type},
            files={
                "file": (file_name, file_bytes, "application/octet-stream"),
            },
        )
        return body["data"]["file_key"]

    # ── Convenience ──────────────────────────────────────────────────────

    async def reply_in_thread(
        self,
        receive_id: str,
        msg_type: str,
        content: str | dict,
        parent_id: str,
    ) -> str:
        """Reply to a specific message in a Feishu thread.

        Args:
            receive_id: Feishu chat_id.
            msg_type: Message type ("text", "interactive", etc.).
            content: Message content (string or dict, JSON-encoded).
            parent_id: message_id of the message to reply to.
        Returns:
            The sent message_id.
        """
        if isinstance(content, dict):
            content = json.dumps(content)
        body = await self._post(
            "/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            json_data={
                "receive_id": receive_id,
                "msg_type": msg_type,
                "content": content,
                "parent_id": parent_id,
            },
        )
        return body["data"]["message_id"]


class FeishuAPIError(Exception):
    """Raised when the Feishu API returns a non-zero code."""

    def __init__(self, msg: str, body: dict[str, Any]) -> None:
        super().__init__(f"Feishu API error: {msg}")
        self.msg = msg
        self.body = body
