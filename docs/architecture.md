# 架构介绍

## 整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                         飞书聊天                                 │
└──────────────────────────────────────────────────────────────────┘
                              │ WebSocket 长连接
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                         cclark                                   │
│                                                                  │
│  ws_client.py ──► handlers/ ──► adapter ──► icc_ws_gateway.py  │
│  (事件接收)       (消息路由)    (回调)      (unified-icc WS)     │
│                                                                  │
│  cards/ ──► feishu_client.py                                   │
│  (卡片渲染)      (飞书 API)                                      │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ WebSocket
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                      unified-icc server                          │
│                                                                  │
│  gateway.py ──► ChannelRouter ──► SessionMonitor                 │
│  tmux_manager.py ──► ProviderRegistry                           │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                         tmux session                             │
│                                                                  │
│  @0 (claude)    @1 (codex)    @2 (gemini)                      │
└──────────────────────────────────────────────────────────────────┘
```

## 组件职责

### ws_client.py — 飞书 WebSocket 客户端

连接飞书事件服务器：
1. `POST /callback/ws/endpoint` 获取 WebSocket URL
2. 连接 WebSocket，接收 protobuf Frame
3. 解码 Frame → JSON → 分发事件
4. 收到 ping 自动回复 pong

### handlers/ — 消息处理

| 文件 | 职责 |
|------|------|
| `message.py` | 消息分类：#command vs 普通消息 |
| `session_creation.py` | 会话创建向导（三步状态机） |
| `screenshot.py` | tmux 窗格截图 |

### adapter.py — 统一网关适配器

实现 `FrontendAdapter` 协议：

```python
class FeishuAdapter:
    async def send_text(channel_id, text) -> str
    async def send_card(channel_id, card) -> str
    async def update_card(channel_id, card_id, card) -> None
    async def send_image(channel_id, image_bytes, caption) -> str
    async def send_file(channel_id, file_path, caption) -> str
    async def show_prompt(channel_id, prompt) -> str

    def register_message_handler(handler)
    def register_callback_handler(handler)
```

### icc_ws_gateway.py — unified-icc WebSocket 网关

连接 unified-icc server 的 WebSocket API，将 cclark 的 handler 方法转换为 unified-icc API 调用。

### cards/ — 卡片渲染

| 文件 | 说明 |
|------|------|
| `output.py` | 输出卡片：流式更新，每个用户回合一张 |
| `thinking.py` | 思考卡片：占位符或真实内容 |
| `prompt.py` | 权限/计划提示卡片 |
| `streaming.py` | 合并 thinking + output 的流式卡片 |
| `builder.py` | 底层卡片 JSON 构建 |

## 数据流

### 入站（飞书 → Agent）

```
飞书消息
    │
    ▼
ws_client._dispatch_event()
    │
    ▼
handlers/message.handle_text_message()
    │
    ├─► #command → session_creation / screenshot
    │
    └─► 普通消息 → icc_ws_gateway.send_to_window()
              │
              ▼
         unified-icc → tmux send-keys
              │
              ▼
         Agent 接收输入
```

### 出站（Agent → 飞书）

```
tmux transcript / events.jsonl
    │
    ▼
unified-icc SessionMonitor
    │
    ▼
AgentMessageEvent / StatusEvent
    │
    ▼
adapter.on_message()
    │
    ├─► text → cards/output.py OutputCard.patch()
    ├─► thinking → cards/thinking.py ThinkingCard
    └─► prompt → cards/prompt.py PromptCard
    │
    ▼
feishu_client → 飞书卡片
```

## 卡片系统

### Output Card

每个用户回合一张输出卡片，增量 patch 直到回合结束。

### Thinking Card

思考内容隔离显示：

| 设置 | 显示 |
|------|------|
| `#verbose off` | `Thinking...` → `Thinking...OK!` |
| `#verbose on` | 真实 Claude thinking 内容 |

### Prompt Card

权限/计划/选择提示：

```python
@dataclass
class InteractivePrompt:
    prompt_type: str   # "ask_user" | "permission" | "plan_mode" | "approval"
    title: str
    description: str
    options: list[str] = []
    detail: str = ""
    plan_text: str = ""
```

## 会话创建流程

```
用户 #new
    │
    ▼
STATE_BROWSE ──► 用户选择目录 ──► STATE_PROVIDER
                                    │
                              用户选择智能体 ──► STATE_MODE
                                                  │
                                            用户选择模式 ──► create_window()
```

## 状态持久化

- `~/.unified-icc/state.json` — channel↔window 绑定
- `~/.unified-icc/session_map.json` — Claude session 映射
- `~/.unified-icc/events.jsonl` — Hook 事件日志

## 下一步

- [命令参考](commands.md) — 完整的命令列表
- [可扩展性](extending.md) — 自定义开发
