# 快速上手

## 环境要求

- Python 3.12+
- tmux
- 运行中的 unified-icc server
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
    allowed_users: "all"       # "all" 或逗号分隔的 open_id 列表
    provider: "claude"         # 默认智能体
    tmux_session: "cclark"    # tmux 会话名
    health_port: 8080
```

### 获取飞书凭证

1. 登录 [飞书开放平台](https://open.feishu.cn/)
2. 创建企业自建应用
3. 获取 `app_id` 和 `app_secret`
4. 在应用配置中启用「消息权限」和「长连接」事件订阅

### 环境变量

| 变量 | 说明 |
|------|------|
| `FEISHU_APP_ID` | 飞书 app_id（仅单应用开发用） |
| `FEISHU_APP_SECRET` | 飞书 app_secret |
| `UNIFIED_ICC_DIR` | 状态目录（默认 ~/.unified-icc） |

## 启动

需要先启动 unified-icc server：

```bash
# 终端 1：启动 unified-icc server
unified-icc server start --port 8900

# 终端 2：启动 cclark
uv run cclark
```

## 飞书命令

发送消息到飞书机器人：

```bash
# 查看帮助
LARK_CLI_NO_PROXY=1 lark-cli im +messages-send \
  --as user \
  --chat-id oc_8c1e688f72705de85fba2716bb69c9ce \
  --text "#help"
```

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
- [可扩展性](extending.md) — 自定义开发
