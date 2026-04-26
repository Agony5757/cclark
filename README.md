# CCLark

[![CI](https://github.com/Agony5757/cclark/actions/workflows/ci.yml/badge.svg)](https://github.com/Agony5757/cclark/actions)
[![Docs](https://img.shields.io/badge/docs-github.io-blue)](https://agony5757.github.io/cclark/)

**在飞书群聊和话题中控制 AI 编程助手。**

CCLark 是 [unified-icc](https://github.com/Agony5757/unified-icc) 的飞书前端。它作为常驻服务运行，接收飞书消息、转发给 unified-icc 网关（驱动一个 tmux 会话），并将智能体输出以飞书交互卡片的形式流式推送回来。

```
┌──────────────┐         ┌─────────────┐         ┌──────────────┐
│  飞书         │  POST   │  CCLark     │         │  unified-icc │
│  群聊/话题     │ ──────► │  webhook    │ ──────► │  网关        │
│              │ ◄────── │  (卡片)     │ ◄────── │  (tmux)      │
└──────────────┘ 卡片更新  └─────────────┘  事件    └──────┬───────┘
                         推送                    tmux 会话
                                                  ┌───┐ ┌───┐
                                                  │@0 │ │@1 │ ...
                                                  └───┘ └───┘
```

## 功能特性

- **会话创建** —— 全部通过飞书卡片按钮导航目录、选择智能体提供方
- **流式输出** —— 智能体输出实时流式推送到交互卡片，在位更新
- **丰富工具栏** —— 每个会话专属工具栏卡片（截图、Ctrl-C、模式切换、实时窗格等）
- **Shell 审批** —— 危险命令需飞书按钮确认后才执行
- **多智能体支持** —— Claude Code、Codex CLI、Gemini CLI、Pi 及交互式 Shell 会话
- **话题路由** —— 每个飞书话题映射一个会话；未绑定话题触发会话创建流程

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

CCLark 完全通过环境变量配置：

```bash
# 飞书应用凭证
FEISHU_APP_ID=cli_xxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxx
FEISHU_VERIFICATION_TOKEN=xxxxxxxx
FEISHU_ENCRYPT_KEY=            # 可选，AES 加密密钥

# 访问控制
ALLOWED_USERS=ou_xxxxxxxx,ou_yyyyyyyy   # 飞书 open ID；留空表示允许所有人

# 目录和默认值
CCLARK_DIR=~/.cclark
CCLARK_PROVIDER=claude        # 使用 /new 时的默认智能体提供方
CCLARK_HOME=~                 # 目录浏览器的根目录

# tmux
TMUX_SESSION_NAME=cclark      # CCLark 管理的 tmux 会话名

# 工具栏
CCLARK_TOOLBAR_CONFIG=        # toolbar.toml 路径；省略则使用内置默认值

# 日志
LOG_LEVEL=INFO
RICH_OUTPUT=true
```

所有配置项详见[配置参考](https://agony5757.github.io/cclark/modules/config.html)。

## 使用方法

### 启动服务

```bash
cclark run
```

这会启动 Webhook 服务器（默认端口 8080）和 unified-icc 网关。将飞书应用的 Webhook URL 配置为 `http://your-host:8080/webhook/event` 即可。

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

**单元测试示例**（测试 `CallbackRegistry` 最长前缀匹配）：

```python
# tests/unit/test_callback_registry.py
import pytest
from cclark.callback_registry import CallbackRegistry

@pytest.fixture
def registry():
    return CallbackRegistry()

def test_longest_prefix_match(registry):
    registry.register("session:send", lambda: "send")
    registry.register("session:send:approve", lambda: "approve")

    handler, params = registry.resolve("session:send:approve:123")
    assert handler() == "approve"
    assert params == {"value": "session:send:approve:123"}

def test_no_match_returns_none(registry):
    registry.register("session:send", lambda: "send")
    handler, params = registry.resolve("unrelated:action")
    assert handler is None
```

**集成测试示例**（测试 Webhook 端点）：

```python
# tests/integration/test_webhook_event.py
import pytest
from httpx import AsyncClient, ASGITransport
from cclark.webhook import app

@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")

@pytest.mark.asyncio
async def test_message_event_routed(client, mock_feishu_client):
    event = {
        "schema": "2.0",
        "header": {"event_type": "im.message.receive_v1", ...},
        "event": {...}
    }
    response = await client.post("/webhook/event", json=event)
    assert response.status_code == 200
```

测试中使用 `pytest-asyncio`（已配置 `asyncio_mode = auto`），异步测试直接用 `async def` 无需额外标记。使用 `pytest-timeout` 将所有测试的超时限制设为 30 秒。

## 架构设计

CCLark 分四层：

| 层级 | 文件 | 职责 |
|------|------|------|
| 飞书 REST API | `feishu_client.py` | 发送消息、补丁卡片、上传文件 |
| Webhook 服务器 | `webhook.py` | FastAPI 应用；解析飞书事件 |
| 事件处理器 | `handlers/` | 将文本和按钮点击路由到具体操作 |
| 网关回调 | `main.py` | 接收 unified-icc 事件 → 转发到飞书 |

关键设计决策：

- **httpx 而非 SDK** —— 飞书官方 SDK 是同步的，直接使用 httpx 保持全链路异步
- **卡片作为主要 UI** —— 所有富输出使用飞书交互卡片；纯文本仅用于简短回复
- **每轮一个卡片** —— `VerboseCardStreamer` 每个通道每轮智能体只维护一个流式卡片，通过 `PATCH /im/v1/messages` 就地更新
- **最长前缀分发** —— 卡片按钮值使用 `前缀:值` 命名；`CallbackRegistry` 按最长匹配前缀路由

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
