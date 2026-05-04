# 快速上手

## 环境要求

- Python 3.12+
- tmux
- 已启用机器人、消息权限和事件长连接的飞书应用

## 安装

```bash
git clone https://github.com/Agony5757/cclark.git
cd cclark
uv sync
```

## 配置

创建 `~/.unified-icc/config.yaml`：

```yaml
unified_icc_ws_url: "ws://127.0.0.1:8900/api/v1/ws"
unified_icc_api_key: ""  # 如果 unified-icc 设置了 ICC_API_KEY

apps:
  - name: "default"
    app_id: "cli_xxxxxxxxxxxxxxxx"
    app_secret: "xxxxxxxxxxxxxxxxxxxxxxxx"
    allowed_users: "all"
    provider: "claude"
    tmux_session: "cclark"
    health_port: 8080
```

### 获取飞书凭证

1. 登录 [飞书开放平台](https://open.feishu.cn/)
2. 创建企业自建应用
3. 获取 `app_id` 和 `app_secret`
4. 在应用配置中启用「消息权限」和「长连接」事件订阅

## 启动

### 1. 启动 unified-icc server

详见 [unified-icc 快速上手](../unified-icc/docs/getting-started.md)：

```bash
unified-icc server start --port 8900
```

### 2. 启动 cclark

```bash
uv run cclark
```

## 飞书命令

| 命令 | 说明 |
|------|------|
| `#help` | 显示帮助 |
| `#new` | 创建新会话 |
| `#status` | 查看当前会话状态 |
| `#mkdir <name>` | 创建目录 |
| `#verbose on\|off` | 控制 thinking 显示 |
| `#screenshot` | 截图 |

## 创建会话

```
发送 #new
  ↓
选择目录
  ↓
选择智能体 (claude/codex/gemini/pi/shell)
  ↓
选择模式 (standard/yolo)
  ↓
等待 Session started
```

## 下一步

- [架构介绍](architecture.md) — 了解组件和数据流
- [命令参考](commands.md) — 完整的命令列表
- [故障排除](troubleshooting.md) — 常见问题
