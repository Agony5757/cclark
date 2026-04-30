"""Screenshot capture handler — captures the tmux pane and sends it as a Feishu image.

The pipeline is: gateway.capture_screenshot -> raw PNG bytes ->
FeishuAdapter.send_image -> FeishuClient.upload_image -> Feishu send message (type=image).
No intermediate file is written to disk.
"""

from __future__ import annotations

import structlog

from cclark.adapter import FeishuAdapter

logger = structlog.get_logger()


async def handle_screenshot_request(
    channel_id: str,
    gateway,
    adapter: FeishuAdapter,
) -> None:
    """Capture a screenshot from the active window and send it as an image."""
    window_id = gateway.channel_router.resolve_window(channel_id)
    if window_id is None:
        await adapter.send_text(channel_id, "No active session in this channel.")
        return

    try:
        screenshot_bytes = await gateway.capture_screenshot(window_id)
    except Exception as e:
        logger.exception("Screenshot capture failed")
        await adapter.send_text(channel_id, f"Screenshot failed: {e}")
        return

    try:
        msg_id = await adapter.send_image(channel_id, screenshot_bytes)
        logger.debug("Screenshot sent: message_id=%s", msg_id)
    except Exception as e:
        logger.exception("Failed to send screenshot")
        await adapter.send_text(channel_id, f"Failed to send screenshot: {e}")
