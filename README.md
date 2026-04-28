# CCLark

[![CI](https://github.com/Agony5757/cclark/actions/workflows/ci.yml/badge.svg)](https://github.com/Agony5757/cclark/actions)
[![Docs](https://img.shields.io/badge/docs-github.io-blue)](https://agony5757.github.io/cclark/)

**在飞书群聊和话题中控制 AI 编程助手。**

CCLark 是 [unified-icc](https://github.com/Agony5757/unified-icc) 的飞书前端。它作为常驻服务运行，通过 WebSocket 长连接实时接收飞书消息、转发给 unified-icc 网关（驱动一个 tmux 会话），并将智能体输出流式推送回来。

```
┌──────────────┐         ┌─────────────┐         ┌──────────────┐
│  飞书         │  WS     │  CCLark     │         │  unified-icc │
│  群聊/话题     │◄══════►│  WS Client  │ ◄══════►│  网关        │
│              │  事件    │             │  事件    │  (tmux)      │
└──────────────┘         └─────────────┘         └──────┬───────┘
                                                       tmux 会话
                                                        ┌───┐
                                                        │@0 │  ← 1:1 映射
                                                        └───┘
```

## 功能特性

- **会话创建** —— 全部通过飞书卡片按钮导航目录、选择智能体提供方
- **流式输出** —— 智能体输出实时流式推送回飞书，在位更新
- **丰富工具栏** —— 每个会话专属工具栏卡片（截图、Ctrl-C、模式切换等）
- **Shell 审批** —— 危险命令需飞书按钮确认后才执行
- **多智能体支持** —— Claude Code、Codex CLI、Gemini CLI、Pi 及交互式 Shell 会话
- **一对一绑定** —— 每个飞书聊天（chat）绑定唯一的 tmux 窗口；重新绑定会 kill 旧会话
- **动态生命周期** —— 所有 tmux 会话由 cclark 进程创建和管理；非 cclark 创建的会话不会被追踪

## 环境要求

- Python 3.12+
- 一个运行中的 [tmux](https://github.com/tmux/tmux) 会话（默认名为 `cclark`）
- 一个已配置入站 Webhook 和卡片消息权限的飞书应用

## 安装

```bash
# 从源码安装
git clone https://github.com/Agony5757/cclark.git
cd cclark
uv sync
uv run python -m cclark run
```

或使用 `pip`：

```bash
pip install cclark
```

## 配置

CCLark 通过 `~/.cclark/config.yaml` 配置（首选）。对于单应用场景，只需一个 entry：

```yaml
apps:
  - name: "default"
    app_id: "cli_xxxxxxxxxxxxxxxx"
    app_secret: "xxxxxxxxxxxxxxxxxxxxxxxx"
    allowed_users: "all"       # "all" 或逗号分隔的 open_id 列表
    provider: "claude"         # /new 的默认智能体
    tmux_session: "cclark"     # 管理的 tmux 会话名
    health_port: 8080          # 仅多应用模式需要不同端口
```

`cp config.yaml.example ~/.cclark/config.yaml` 然后填入你的 app_id 和 app_secret。

**环境变量回退**（仅单应用、仅开发用）：设置 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`，当 `config.yaml` 不存在时使用。

## 使用方法

### 启动服务

```bash
cclark run
```

这会启动 WebSocket 长连接（连接飞书事件服务器）和 unified-icc 网关。无需公网 Webhook URL。

### 飞书内命令

| 命令 | 说明 |
|------|------|
| `/new` 或发送首条消息 | 打开目录浏览器 → 选择智能体提供方 → 创建会话 |
| `/sessions` | 通过状态卡片列出活跃会话 |
| `/verbose` | 开关流式卡片模式 |
| `/toolbar` | 显示会话工具栏卡片 |
| `/screenshot` | 截取当前 tmux 窗格并发送 |
| `/help` | 显示帮助文本 |

点击工具栏按钮可向智能体发送对应按键或操作。在 Shell 审批卡片上点击 **批准** 或 **拒绝**。

## 测试

### 运行测试

```bash
# 安装测试依赖
uv sync --extra dev

# 运行所有测试
uv run pytest

# 仅运行单元测试
uv run pytest tests/unit/

# 仅运行集成测试
uv run pytest tests/integration/

# 带覆盖率报告
uv run pytest --cov=cclark --cov-report=term-missing
```

### 测试结构

```
tests/
├── unit/          # 单元测试：测试单个模块的内部逻辑
│                  # 例如：CallbackRegistry、卡片构建器、事件解析器、配置加载
└── integration/   # 集成测试：测试模块间的交互，使用 mocked 的飞书 API
                   # 例如：webhook 端点、事件处理链路、Feishu 客户端调用
```

### 编写新测试

**单元测试示例**（测试 `parse_message_event` 事件解析）：

```python
# tests/unit/test_event_parsers.py
from cclark.event_parsers import FeishuMessageEvent, parse_message_event

def test_valid_text_message():
    payload = {
        "event": {
            "chat_id": "oc_chat1",
            "thread_id": "",
            "sender": {"sender_id": {"open_id": "ou_user1"}},
            "message": {
                "message_id": "om_msg1",
                "msg_type": "text",
                "content": '{"text": "hello"}',
            },
        }
    }
    result = parse_message_event(payload)
    assert result is not None
    assert result.text == "hello"
    assert result.user_id == "ou_user1"

def test_non_text_message_returns_none():
    payload = {
        "event": {
            "chat_id": "oc_chat1",
            "sender": {"sender_id": {"open_id": "ou_user1"}},
            "message": {
                "message_id": "om_msg1",
                "msg_type": "image",
                "content": "{}",
            },
        }
    }
    assert parse_message_event(payload) is None
```

**集成测试示例**（测试 WS 事件分发）：

```python
# tests/integration/test_ws_client.py
import json
from unittest.mock import AsyncMock
from cclark.ws_client import FeishuWSClient, register_message_handler

def test_ws_event_routes_to_registered_handler():
    handler = AsyncMock()
    register_message_handler(handler)
    try:
        client = FeishuWSClient(app_id="cli_test", app_secret="test")
        payload = json.dumps({
            "event": {
                "chat_id": "oc_chat1",
                "thread_id": "",
                "sender": {"sender_id": {"open_id": "ou_testuser1"}},
                "message": {
                    "message_id": "om_msg1",
                    "msg_type": "text",
                    "content": '{"text": "hello"}',
                },
            }
        }).encode()
        await client._dispatch_event(payload)
        handler.assert_awaited_once()
    finally:
        register_message_handler(AsyncMock())
```

测试中使用 `pytest-asyncio`（已配置 `asyncio_mode = auto`），异步测试直接用 `async def` 无需额外标记。使用 `pytest-timeout` 将所有测试的超时限制设为 30 秒。

## 架构设计

CCLark 分四层：

| 层级 | 文件 | 职责 |
|------|------|------|
| 飞书 REST API | `feishu_client.py` | 发送消息、补丁卡片、上传文件 |
| WS 长连接 | `ws_client.py` | 连接飞书事件服务器，接收事件 |
| 事件处理器 | `handlers/` | 将文本消息路由到具体操作（命令、会话创建） |
| 网关回调 | `main.py` | 接收 unified-icc 事件 → 转发到飞书 |

关键设计决策：

- **WebSocket 长连接** —— cclark 主动连接飞书，无需公网 URL
- **httpx 而非 SDK** —— 飞书官方 SDK 是同步的，直接使用 httpx 保持全链路异步
- **文本交互** —— 所有对话通过文字命令；飞书 WS 模式不支持卡片按钮回调
- **一对一绑定** —— `ChannelRouter` 确保每个飞书聊天（chat_id）始终绑定一个 tmux 窗口；channel rebind 时旧 tmux window 被 kill
- **cclark 创建的窗口才追踪** —— `WindowStateStore._created_windows` 集合记录所有由 cclark 创建的 tmux 窗口；session monitor 的 fallback scan 仅扫描这些窗口

完整数据流图见[架构文档](https://agony5757.github.io/cclark/architecture.html)。

## 文档

在线文档：https://agony5757.github.io/cclark/

| 章节 | 说明 |
|------|------|
| [快速上手](https://agony5757.github.io/cclark/getting-started/index.html) | 安装与首次运行 |
| [配置指南](https://agony5757.github.io/cclark/getting-started/configuration.html) | 所有环境变量说明 |
| [架构设计](https://agony5757.github.io/cclark/architecture.html) | 系统设计与数据流 |
| [模块参考](https://agony5757.github.io/cclark/modules/index.html) | 各模块调用栈与 API |
| [故障排查](https://agony5757.github.io/cclark/troubleshooting.html) | 常见问题与修复方法 |

## 与 unified-icc 的关系

CCLark 实现了 unified-icc 中的 [`FrontendAdapter`](https://unified-icc.readthedocs.io/api-reference/adapter.html#unified_icc.adapter.FrontendAdapter) 协议。它不包含任何 tmux、智能体提供方或会话管理逻辑——那些都在 unified-icc 中：

```
CCLark 实现 FrontendAdapter  ←→  unified-icc 在网关事件时调用它
```

网关（`UnifiedICC`）和 CCLark 运行在同一 Python 进程中，通过进程内异步回调通信，不走 HTTP。

## 相关项目

| 项目 | 仓库 | 角色 |
|------|------|------|
| **unified-icc** | [Agony5757/unified-icc](https://github.com/Agony5757/unified-icc) | 网关库 —— tmux 管理、智能体提供方、事件系统 |
| **ccgram** | [alexei-led/ccgram](https://github.com/alexei-led/ccgram) | 原始 Telegram 前端（CCLark 的上游参考） |
| **cclark** | [Agony5757/cclark](https://github.com/Agony5757/cclark) | 飞书前端 —— 本项目 |

## 许可证

MIT
