# CCLark

**在飞书群聊和话题中控制 AI 编程助手。**

CCLark 是 [unified-icc](https://github.com/Agony5757/unified-icc) 的飞书前端。它作为常驻服务运行，通过 WebSocket 长连接实时接收飞书消息、转发给 unified-icc 网关（驱动一个 tmux 会话），并将智能体输出以交互卡片的形式推送回来。

```
飞书群聊/话题
     │  WebSocket 长连接
     ▼
┌──────────────┐         ┌─────────────────┐         ┌──────────────┐
│  ws_client   │────────►│  handlers/      │────────►│  adapter.py  │
│  (事件接收)   │  事件    │  message.py     │  调用    │  FeishuAdapter│
└──────────────┘         └─────────────────┘         └──────┬───────┘
                            session_creation.py               │
                            screenshot.py                     │ FrontendAdapter
                             │                               ▼
                             │                    ┌─────────────────┐
                             │                    │  UnifiedICC      │
                             │                    │  (unified-icc)  │
                             │                    └────────┬────────┘
                             │                             │ tmux
                             │                             ▼
                             │                    ┌──────────────┐
                             │                    │ tmux 会话     │
                             │                    │ @0 (claude)  │
                             │                    └──────────────┘
                             │
                    ┌─────────┴──────────┐
                    │  cards/           │  (飞书交互卡片渲染)
                    │  output.py        │
                    │  thinking.py      │
                    │  prompt.py        │
                    │  streaming.py     │
                    └────────────────────┘
```

[![CI](https://github.com/Agony5757/cclark/actions/workflows/ci.yml/badge.svg)](https://github.com/Agony5757/cclark/actions)
[![Docs](https://img.shields.io/badge/docs-github.io-blue)](https://agony5757.github.io/cclark/)

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Installation & Configuration](#installation--configuration)
- [Usage](#usage)
- [Commands Reference](#commands-reference)
- [Card System](#card-system)
- [Plan Mode Two-Step Flow](#plan-mode-two-step-flow)
- [Event Flow Diagram](#event-flow-diagram)
- [Module Reference](#module-reference)
- [Design Documents](#design-documents)
- [Troubleshooting](#troubleshooting)
- [Related Projects](#related-projects)

---

## Overview

CCLark implements the [`FrontendAdapter`](https://github.com/Agony5757/unified-icc/blob/main/src/unified_icc/adapter.py) protocol from unified-icc, bridging Feishu WebSocket events to the gateway and gateway events back to Feishu cards.

**Key design decisions:**
- **WebSocket 长连接** — cclark 主动连接飞书事件服务器，无需公网 Webhook URL
- **交互卡片** — 输出、思考内容、权限提示均通过飞书交互卡片展示，并支持原地更新
- **一对一绑定** — 每个飞书聊天（chat_id）绑定唯一的 tmux 窗口；`#new` 会清理旧会话
- **文字命令驱动** — 核心操作通过 `#` 前缀命令；当前审批/计划卡片通过回复数字编号驱动 Claude terminal UI
- **由 cclark 创建的窗口才追踪** — `WindowStateStore._created_windows` 记录所有由 cclark 创建的 tmux 窗口

---

## Architecture

CCLark 分四层：

| 层级 | 文件 | 职责 |
|------|------|------|
| **飞书 WS** | `ws_client.py` | 连接飞书事件服务器，接收事件，发送 pong |
| **事件处理** | `handlers/` | 消息分类（命令 vs 转发）、会话创建、截图 |
| **网关回调** | `adapter.py` | 实现 `FrontendAdapter`；网关事件 → 飞书卡片 |
| **网关集成** | `main.py` | 启动 UnifiedICC，注入 adapter，注册回调 |

### 数据流（从用户输入到智能体响应）

```
用户发送消息
    │
    ▼
ws_client._dispatch_event(payload)
    │
    ▼
handlers/message.handle_text_message(event)
    │
    ├─► 是 #command？ → session_creation / screenshot 等
    │
    └─► 普通消息 → gateway.send_to_window(window_id, text)
              │
              ▼
         tmux 窗口 (Claude Code)
              │
              │  1s poll (SessionMonitor)
              ▼
         AgentMessageEvent / StatusEvent
              │
              ▼
         adapter.on_message(event)
              │
              ├─► text 消息 ──► cards/output.py OutputCard.patch()
              ├─► thinking ──► cards/thinking.py ThinkingCard
              └─► status ────► 状态更新
```

---

## Installation & Configuration

### 环境要求

- Python 3.12+
- 运行中的 tmux 会话（默认名为 `cclark`）
- 一个已启用机器人、消息权限和事件长连接的飞书应用

### 安装

```bash
git clone https://github.com/Agony5757/cclark.git
cd cclark
uv sync
```

### 配置

CCLark 通过 `~/.cclark/config.yaml` 配置（首选）：

```yaml
apps:
  - name: "default"
    app_id: "cli_xxxxxxxxxxxxxxxx"
    app_secret: "xxxxxxxxxxxxxxxxxxxxxxxx"
    allowed_users: "all"       # "all" 或逗号分隔的 open_id 列表
    provider: "claude"         # #new 的默认智能体
    tmux_session: "cclark"    # 管理的 tmux 会话名
    health_port: 8080          # 多应用模式需要不同端口
```

```bash
cp config.yaml.example ~/.cclark/config.yaml
# 编辑填入 app_id 和 app_secret
```

**环境变量回退**（仅单应用、仅开发用）：设置 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`，当 `config.yaml` 不存在时使用。

### 启动

```bash
uv run cclark
```

这会启动 WebSocket 长连接和 unified-icc 网关。无需公网 Webhook URL。

---

## Usage

### 飞书内命令

| 命令 | 说明 |
|------|------|
| `#help` | 显示帮助文本；无会话时普通消息也会返回帮助 |
| `#new` | 清理当前聊天的旧会话，打开目录/provider/mode 向导 |
| `#mkdir <name>` | 在 `#new` 的目录选择阶段创建一个新子目录 |
| `#status` | 显示当前聊天绑定的窗口、session id、cwd、mode、verbose 状态 |
| `#session list` | 列出 cclark 管理的活跃 tmux 会话 |
| `#session close <window_id>` | 关闭指定的 cclark 管理会话 |
| `#verbose on` / `#verbose off` | 控制 thinking card 显示真实内容还是占位状态 |
| `#screenshot` | 截取当前 tmux 窗格并发送到飞书 |

会话启动后，普通文本和 Claude slash commands（如 `/status`、`/plan`、`/permissions`）都会转发给 Claude。

---

## Commands Reference

### #new 会话创建流程

`#new` 启动一个三步文字向导：

```
你: #new
Bot: 📁 选择目录
     [..] [project_a] [project_b]
     (输入目录名或数字导航)

你: project_a
Bot: 🤖 选择智能体
     1. claude  2. codex  3. gemini  4. pi  5. shell

你: 1
Bot: ⚙️ 选择模式
     1. standard (默认权限审批)
     2. yolo (跳过所有权限)

你: 1
Bot: ✅ 会话已创建: @0
     (开始与 Claude Code 交互)
```

`#mkdir <name>` 可在任何时候创建新子目录。

### 数字回复审批

当 Claude 需要权限/计划决策时，Bot 显示编号选项。直接回复编号即可：

```
Bot: 🔐 Claude 需要权限
     1. Allow, don't ask again
     2. Allow once
     3. Deny
     4. Deny and don't ask again

你: 2
```

---

## Card System

CCLark 使用三类卡片实现干净的飞书输出：

| 卡片 | 触发 | 行为 |
|------|------|------|
| **Output Card** | Claude regular output | 每个用户回合一张卡片，增量 patch；回合结束后不再更新 |
| **Thinking Card** | Claude thinking output | `#verbose on` 显示真实 thinking，`#verbose off` 显示占位状态；每轮思考结束后新建卡片 |
| **Prompt Card** | Claude permission / plan / selection prompt | 显示终端 prompt；回复编号继续；plan option 3 为两步流程 |

### Verbose 模式

`#verbose on` 和 `#verbose off` 只控制 thinking card 的显示内容：

| 设置 | Thinking 输出 |
|------|--------------|
| `#verbose off`（默认） | `Thinking...` → `Thinking...OK!`（占位符） |
| `#verbose on` | 真实 Claude thinking 内容（流式更新） |

Regular output 始终走 Output Card，不受 verbose 影响。

---

## Plan Mode Two-Step Flow

Claude plan mode 的 **"Tell Claude what to change"（选项 3）** 是一个两步流程：

```
Bot: 📋 Claude 提出了计划...
     1. Yes, proceed
     2. Exit plan mode
     3. Tell Claude what to change

你: 3
     ── cclark 进入"等待反馈文本"状态 ──

你: 请改为使用 Python 的 async/await 语法
     ── 反馈文本被发送，不带 Enter ──
     ── 然后发送 Enter ──

Bot: (Claude 应用反馈，继续执行)
```

**实现原理：** `send_to_window(text, enter=False)` 先发送反馈文本，然后第二次调用 `send_to_window("", enter=True)` 提交 Enter。普通选项 1/2 则直接 `send_to_window(number, enter=True)`。

---

## Event Flow Diagram

### 入站事件（飞书 → Agent）

```
Feishu WS Server
       │  protobuf WebSocket frame
       ▼
ws_client.py  FeishuWSClient
       │  _dispatch_event()
       ▼
event_parsers.py  parse_message_event()
       │  → FeishuMessageEvent(chat_id, user_id, text, message_id, ...)
       ▼
handlers/message.py  handle_text_message()
       │
       ├─► #command? → handlers/session_creation.py / screenshot.py
       │
       └─► 普通消息
              │
              ▼
         gateway.send_to_window(window_id, text)
              │
              ▼
         tmux send-keys
              │
              ▼
         Claude Code 接收输入
```

### 出站事件（Agent → 飞书）

```
tmux 窗口 (transcript.json / events.jsonl)
       │  1s poll
       ▼
unified-icc  SessionMonitor
       │  AgentMessageEvent / StatusEvent / HookEvent
       ▼
cclark adapter.py  FeishuAdapter.on_message()
       │
       ├─► messages (text) → cards/output.py → feishu_client.send_card()
       ├─► messages (thinking) → cards/thinking.py → FeishuAdapter.update_card()
       ├─► messages (tool_use/result) → cards/output.py 合并显示
       └─► StatusEvent → 卡片 footer 更新
```

---

## Module Reference

### `ws_client.py` — FeishuWSClient

飞书专有二进制 WebSocket 协议客户端：

1. `POST /callback/ws/endpoint` 获取 `wss://` URL
2. 连接 WebSocket，接收 protobuf Frame
3. 解码 Frame → JSON payload → 分发到注册处理器
4. 收到 ping → 回复 pong，自动重连

模块级别的 handler 注册（`register_message_handler`, `register_callback_handler`），由 `handlers/message.py` 使用。

```python
from cclark.ws_client import FeishuWSClient, register_message_handler

def my_handler(event: FeishuMessageEvent):
    ...

register_message_handler(my_handler)
client = FeishuWSClient(app_id=..., app_secret=...)
```

### `feishu_client.py` — FeishuClient

httpx 异步 REST 客户端，封装飞书消息 API：

| 方法 | 说明 |
|------|------|
| `send_message(chat_id, msg_type, content, thread_id)` | 发送消息 |
| `patch_message(message_id, card_json)` | 补丁更新卡片 |
| `upload_image(image_bytes)` | 上传图片 → image_key |
| `upload_file(file_bytes, filename, file_type)` | 上传文件 → file_key |
| `get_message(message_id)` | 获取消息详情 |

所有方法自动管理 tenant_access_token 缓存和刷新。

### `handlers/message.py` — 消息路由

入站消息分类：

```python
def classify_terminal_prompt(body: str) -> dict | None:
    """分类终端 UI 文本，识别 permission / plan 交互状态"""

def handle_text_message(event: FeishuMessageEvent) -> None:
    """主消息处理：#command vs 转发给 agent"""
```

关键状态 `_terminal_prompt_states`：跟踪每个 channel 的 plan mode `enter=False` 等待反馈文本状态。

### `handlers/session_creation.py` — 会话创建向导

三态状态机：

```
STATE_BROWSE ──► 用户选择目录 ──► STATE_PROVIDER
                                    │
                              用户选择智能体 ──► STATE_MODE
                                                  │
                                            用户选择模式 ──► create_window()
```

### `handlers/screenshot.py` — 截图

```python
async def handle_screenshot(channel_id: str, window_id: str) -> None:
    """截取 tmux 窗格 → 上传 Feishu → 发送图片消息"""
```

使用 `gateway.capture_pane(window_id)` 获取原始文本，然后渲染为图片。

### `adapter.py` — FeishuAdapter

实现 `unified_icc.adapter.FrontendAdapter` 协议：

```python
class FeishuAdapter:
    async def send_text(channel_id, text) -> str
    async def send_card(channel_id, card) -> str
    async def update_card(channel_id, card_id, card) -> None
    async def send_image(channel_id, image_bytes, caption) -> str
    async def send_file(channel_id, file_path, caption) -> str
    async def show_prompt(channel_id, prompt) -> str

    # 注册入站处理器
    def register_message_handler(handler)
    def register_callback_handler(handler)
```

### `cards/` — 卡片构建器

| 文件 | 类 | 说明 |
|------|-----|------|
| `builder.py` | `FeishuCardBuilder` | 底层卡片 JSON 构建；所有元素的公共渲染逻辑 |
| `output.py` | `OutputCard` | 流式输出卡片；每个用户回合一张，增量 patch |
| `thinking.py` | `ThinkingCard` | 思考内容隔离；placeholder vs verbose 模式 |
| `prompt.py` | `PromptCard` | 交互提示卡片；权限/计划/问题 |
| `streaming.py` | `StreamingCard` | 合并 thinking + output 的流式卡片 |

### `state.py` — 运行时状态

每个 channel 的内存状态：

```python
@dataclass
class ChannelState:
    channel_id: str
    current_window: str | None       # tmux window_id (e.g. "@0")
    current_session_id: str = ""
    cwd: str = ""
    provider: str = ""
    mode: str = ""
    tool_call_state: ToolCallState | None = None
    pending_plan_feedback: bool = False
```

### `config.py` — 配置

支持多应用配置（`apps` 列表），每个 app 有独立 `app_id`/`app_secret`。`get_app_config(name)` 按名称查找，`default_app` 即第一个条目。

### `event_parsers.py` — 事件解析

`FeishuMessageEvent` dataclass 和 `parse_message_event(payload) -> FeishuMessageEvent | None` 函数。解析飞书 WS 事件 payload，提取 `chat_id`、`user_id`、`text`、`message_id`、`thread_id`。

### `user_preferences.py` — 用户偏好

每个用户独立的偏好设置（按 `user_id` 存储）：

| 偏好 | 说明 |
|------|------|
| `verbose` | thinking card 详细模式 |
| `preferred_provider` | 默认智能体选择 |
| `preferred_mode` | 默认模式（standard/yolo） |

---

## Design Documents

| 文档 | 覆盖内容 |
|------|----------|
| [dev-design.md](dev-design.md) | 项目背景、ccgram 分析、设计决策 |
| [design/module-gateway-core.md](design/module-gateway-core.md) | cclark 如何委托 unified-icc |
| [design/module-adapter-layer.md](design/module-adapter-layer.md) | FrontendAdapter 实现 |
| [design/module-card-renderer.md](design/module-card-renderer.md) | 已弃用，内容合并至 module-cards.md |
| [design/module-feishu-frontend.md](design/module-feishu-frontend.md) | 整体飞书集成 |
| [design/module-mvp.md](design/module-mvp.md) | MVP 范围与实现计划 |
| [design/module-ws-client.md](design/module-ws-client.md) | WebSocket 客户端与事件分发 |
| [design/module-handlers.md](design/module-handlers.md) | 消息路由与会话创建 |
| [design/module-cards.md](design/module-cards.md) | 卡片构建器详解 |
| [design/module-state-and-config.md](design/module-state-and-config.md) | 状态管理与配置 |

---

## Troubleshooting

### Bot 无响应

1. 检查 cclark 进程是否运行：`ps aux | grep cclark`
2. 检查 WebSocket 连接状态（日志中应有 `Connected to wss://...`）
3. 确认飞书应用已启用"长连接"事件订阅

### 消息发送失败

- 错误 `code: 99991663`： tenant_access_token 过期或无效 → 重启 cclark 刷新 token
- 错误 `code: 230013`：应用没有该群的消息权限 → 在飞书管理后台添加权限

### 会话绑定异常

- `#new` 后 Bot 说已有活跃会话：这是预期行为，`#new` 会先清理旧会话
- 显示 `Orphaned window` 警告：未被状态追踪的 live Claude tmux 窗口，不会自动删除

### 卡片不更新

- Output card 在回合结束后停止更新是正常行为
- Thinking card 在 `#verbose off` 时显示占位符是设计行为，不是 bug

### Claude 卡住无响应

- 发送 `#status` 查看当前会话状态
- 发送 `#session close @N` 关闭后重新 `#new`

---

## Related Projects

| 项目 | 仓库 | 说明 |
|------|------|------|
| **unified-icc** | [Agony5757/unified-icc](https://github.com/Agony5757/unified-icc) | 平台无关网关 — tmux 管理、智能体提供方、事件系统 |
| **ccgram** | [alexei-led/ccgram](https://github.com/alexei-led/ccgram) | 原始 Telegram 前端（上游参考） |
| **cclark** | [Agony5757/cclark](https://github.com/Agony5757/cclark) | 本项目 — 飞书前端 |

---

## License

MIT
