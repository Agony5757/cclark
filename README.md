# CCLark

**在飞书群聊和话题中控制 AI 编程助手。**

CCLark 通过 WebSocket 长连接接收飞书消息，通过 unified-icc 网关与 tmux 上的 Claude Code、Codex CLI 等交互，将输出以交互卡片的形式推送回飞书。

```
飞书群聊/话题
     │
     ▼
┌──────────────┐
│  cclark     │  ← 飞书 WebSocket 长连接
│              │
│  ws_client  │  ← 事件接收
│  handlers/  │  ← 消息路由、命令处理
│  adapter/   │  ← unified-icc 集成
│  cards/     │  ← 飞书交互卡片渲染
└──────────────┘
     │
     │ ICCWebSocketGateway
     ▼
┌──────────────┐
│ unified-icc  │  ← tmux 管理、Agent 会话
│    server   │
└──────────────┘
     │
     ▼
┌──────────────┐
│    tmux      │  ← Claude Code / Codex
└──────────────┘
```

[![CI](https://github.com/Agony5757/cclark/actions/workflows/ci.yml/badge.svg)](https://github.com/Agony5757/cclark/actions)

## 核心特性

- **WebSocket 长连接** — 无需公网 Webhook URL
- **交互卡片** — 输出、思考、权限提示均通过飞书卡片展示，支持原地更新
- **多 Agent 支持** — Claude Code、Codex CLI、Gemini CLI、Pi、Shell
- **会话管理** — 每个飞书聊天绑定唯一 tmux 窗口，`#new` 自动清理旧会话
- **权限审批** — 通过回复数字编号审批 Claude 权限提示

## 快速导航

| 文档 | 说明 |
|------|------|
| [快速上手](docs/getting-started.md) | 安装、配置、启动 |
| [架构介绍](docs/architecture.md) | 组件、数据流、卡片系统 |
| [命令参考](docs/commands.md) | 飞书内命令详解 |
| [可扩展性](docs/extending.md) | 自定义卡片、添加命令 |
| [故障排除](docs/troubleshooting.md) | 常见问题与解决方案 |

## 快速开始

```bash
# 安装
git clone https://github.com/Agony5757/cclark.git
cd cclark
uv sync

# 配置
mkdir -p ~/.unified-icc
cp config.yaml.example ~/.unified-icc/config.yaml
# 编辑填入 app_id 和 app_secret

# 启动 unified-icc server
unified-icc server start --port 8900

# 启动 cclark
uv run cclark
```

飞书发送 `#help` 查看可用命令。

## 相关项目

| 项目 | 说明 |
|------|------|
| [unified-icc](https://github.com/Agony5757/unified-icc) | 平台无关网关 |
| [ccgram](https://github.com/alexei-led/ccgram) | Telegram 前端（上游参考） |

## License

MIT
