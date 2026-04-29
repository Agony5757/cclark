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

- **会话创建** —— 通过 `#new` 文本向导选择目录、创建工作区、选择智能体提供方和权限模式
- **流式输出卡片** —— Claude regular output 始终进入输出卡片并在同一回合内原地更新
- **思维内容隔离** —— Claude thinking 内容只走 thinking card；`#verbose` 只决定显示真实 thinking 还是占位状态
- **权限/计划提示桥接** —— Claude terminal prompt 会显示为飞书提示卡；当前用回复 `1/2/3` 作出选择
- **多智能体支持** —— Claude Code、Codex CLI、Gemini CLI、Pi 及交互式 Shell 会话
- **一对一绑定** —— 每个飞书聊天（chat）绑定唯一的 tmux 窗口；`#new` 会清理同一聊天旧会话
- **动态生命周期** —— 所有 tmux 会话由 cclark 进程创建和管理；非 cclark 创建的会话不会被追踪

## 环境要求

- Python 3.12+
- 一个运行中的 [tmux](https://github.com/tmux/tmux) 会话（默认名为 `cclark`）
- 一个已启用机器人、消息权限和事件长连接的飞书应用

## 安装

```bash
# 从源码安装
git clone https://github.com/Agony5757/cclark.git
cd cclark
uv sync
uv run cclark
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
    provider: "claude"         # #new 的默认智能体
    tmux_session: "cclark"     # 管理的 tmux 会话名
    health_port: 8080          # 仅多应用模式需要不同端口
```

`cp config.yaml.example ~/.cclark/config.yaml` 然后填入你的 app_id 和 app_secret。

**环境变量回退**（仅单应用、仅开发用）：设置 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`，当 `config.yaml` 不存在时使用。

## 使用方法

### 启动服务

```bash
cclark
```

这会启动 WebSocket 长连接（连接飞书事件服务器）和 unified-icc 网关。无需公网 Webhook URL。

### 飞书内命令

| 命令 | 说明 |
|------|------|
| `#help` | 显示帮助文本；无会话时普通消息也会返回此帮助 |
| `#new` | 清理当前聊天的旧托管会话并打开目录 / provider / mode 向导 |
| `#mkdir <name>` | 在 `#new` 的目录选择阶段创建一个新子目录并进入它 |
| `#status` | 显示当前聊天绑定的窗口、session id、cwd、mode 和 verbose 状态 |
| `#session list` | 列出 cclark 管理的活跃 tmux 会话 |
| `#session close <window_id>` | 关闭指定 cclark 管理的 tmux 会话 |
| `#verbose on` / `#verbose off` | 控制 thinking card 显示真实内容还是占位状态；regular output 始终走输出卡片 |
| `#screenshot` | 截取当前 tmux 窗格并发送 |

会话启动后，普通文本和 Claude slash commands（例如 `/status`、`/plan`、`/permissions`）都会转发给 Claude。

当前 Claude prompt 的飞书按钮回调尚未接入；看到 `Claude needs input` 卡片时，请直接回复 `1`、`2` 或 `3`。如果 plan mode 中选择 `3. Tell Claude what to change`，先回复 `3`，再发送一条反馈文本；cclark 会把第二条文本提交给 Claude 的反馈输入框。

### 飞书输出卡片设计

为保证长流程调试时飞书消息干净、可追踪，cclark 固定使用三类卡片：

| 卡片 | 触发 | 行为 |
|------|------|------|
| Output card | Claude regular output | 每个用户回合一张卡片，增量 patch；回合结束后不再更新 |
| Thinking card | Claude thinking output | `#verbose on` 显示真实 thinking，`#verbose off` 显示 `Thinking...` / `Thinking...OK!` 占位；结束后关闭更新，下一阶段新建卡片 |
| Input card | Claude permission / plan / selection prompt | 显示当前 terminal prompt；普通选项回复 `1/2/3`，plan 选项 `3` 会进入“等待反馈文本”状态 |

设计约束：

- 用户 prompt 不由 bot 回显。
- thinking 不作为普通文本发送。
- interactive prompt 出现前会结束上一张 thinking card。
- prompt 被选择并继续执行后，后续 thinking 从新 thinking card 开始。

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
                   # 例如：WebSocket 事件处理链路、Feishu 客户端调用
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
- **文本交互** —— 所有核心操作通过文字命令；当前审批/计划卡片用数字回复驱动 Claude terminal UI，其中 plan 选项 3 使用“两步输入”：先选 `3`，再发送反馈文本
- **一对一绑定** —— `ChannelRouter` 确保每个飞书聊天（chat_id）始终绑定一个 tmux 窗口；channel rebind 时旧 tmux window 被 kill
- **cclark 创建的窗口才追踪** —— `WindowStateStore._created_windows` 集合记录所有由 cclark 创建的 tmux 窗口；session monitor 的 fallback scan 仅扫描这些窗口
- **orphan 警告** —— 如果 `#new` 发现未被 cclark 状态追踪的 Claude tmux 窗口，会向用户提示但不会自动删除

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
