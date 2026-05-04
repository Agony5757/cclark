# 可扩展性

## 自定义卡片

### 卡片结构

cclark 使用飞书交互卡片，通过 `FeishuCardBuilder` 构建：

```python
from cclark.cards.builder import FeishuCardBuilder

card = FeishuCardBuilder() \
    .title("My Card") \
    .content("Markdown **formatted** content") \
    .button("Action 1", "action_1", style="primary") \
    .button("Action 2", "action_2") \
    .build()
```

### 发送和更新卡片

```python
from cclark.adapter import FeishuAdapter

adapter = FeishuAdapter()

# 发送新卡片
card_id = await adapter.send_card(channel_id, card)

# 更新现有卡片
await adapter.update_card(channel_id, card_id, updated_card)
```

### 流式更新

对于长时间运行的命令，使用流式卡片：

```python
from cclark.cards.streaming import StreamingCard

streamer = StreamingCard(channel_id, adapter)

# 开始流式输出
await streamer.start()

# 更新内容
await streamer.update("Processing...")
await streamer.update("Processing... 50%")

# 完成
await streamer.finalize("Done!")
```

## 添加新命令

### 1. 实现 Handler

在 `handlers/` 目录添加新的 handler：

```python
# handlers/my_command.py
from cclark.state import get_channel_state

async def handle_my_command(event):
    """处理 #mycommand 命令"""
    channel_id = event.chat_id

    # 获取当前 channel 状态
    state = get_channel_state(channel_id)

    # 发送响应
    await event.reply("My command result")
```

### 2. 注册命令路由

在 `handlers/message.py` 中添加路由：

```python
# handlers/message.py

async def handle_text_message(event):
    text = event.text.strip()

    if text.startswith("#mycommand"):
        from handlers.my_command import handle_my_command
        await handle_my_command(event)
    elif text.startswith("#"):
        await handle_hash_command(event)
    else:
        await handle_regular_message(event)
```

## 添加卡片元素

### 图片卡片

```python
from cclark.adapter import FeishuAdapter

adapter = FeishuAdapter()

# 上传图片并发送
image_id = await adapter.send_image(
    channel_id,
    image_bytes=b"...",
    caption="Screenshot"
)
```

### 文件卡片

```python
await adapter.send_file(
    channel_id,
    file_path="/path/to/file.txt",
    caption="Log file"
)
```

## 自定义状态存储

### Channel State

每个 channel 维护独立状态：

```python
from cclark.state import ChannelState, get_channel_state

state = get_channel_state(channel_id)

# 状态字段
state.current_window  # tmux window_id
state.current_session_id
state.cwd
state.provider
state.mode
state.verbose
```

### 持久化

状态默认保存在内存中。如需持久化：

```python
# state.py
import json
from pathlib import Path

STATE_FILE = Path("~/.cclark/state.json")

def save_state():
    with open(STATE_FILE, "w") as f:
        json.dump(all_states, f)

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
```

## 与 unified-icc 集成

### 直接使用 Gateway

```python
from cclark.icc_ws_gateway import ICCWebSocketGateway

gateway = ICCWebSocketGateway()
await gateway.connect()

# 创建窗口
window = await gateway.create_window("/path", "claude", "standard")

# 发送消息
await gateway.send_to_window(window.window_id, "Hello")

# 接收事件
gateway.on_message(lambda event: print(event))
```

### 事件处理

```python
from unified_icc.event_types import AgentMessageEvent, StatusEvent

def on_agent_message(event: AgentMessageEvent):
    for msg in event.messages:
        print(f"[{msg.content_type}] {msg.text}")

def on_status(event: StatusEvent):
    print(f"Status: {event.status}")

gateway.on_message(on_agent_message)
gateway.on_status(on_status)
```

## 开发调试

### 本地测试

```bash
# 启动 unified-icc
unified-icc server start --port 8900

# 启动 cclark（开发模式）
uv run cclark
```

### 查看日志

cclark 日志输出到 stdout，包含：
- WebSocket 连接状态
- 消息路由
- 卡片发送/更新

### 模拟消息

```python
from cclark.handlers.message import handle_text_message
from cclark.event_parsers import FeishuMessageEvent

# 模拟消息事件
event = FeishuMessageEvent(
    chat_id="test_chat",
    user_id="test_user",
    text="#help",
    message_id="test_msg_1"
)

await handle_text_message(event)
```

## 下一步

- [故障排除](troubleshooting.md) — 常见问题与解决方案
