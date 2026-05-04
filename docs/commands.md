# 命令参考

## 飞书命令

所有命令以 `#` 开头，在飞书聊天中发送。

### #help

显示帮助文本。无会话时普通消息也会返回帮助。

### #new

创建新会话。会清理当前聊天的旧会话（如果有）。

### #status

显示当前会话状态：

```
当前窗口: @0
Session ID: abc123
工作目录: /home/user/project
Provider: claude
模式: standard
Verbose: off
```

### #mkdir \<name\>

在目录选择阶段创建新子目录。

```
发送: #mkdir test-project
Bot: 已创建并进入 test-project
```

### #select \<path\>

直接跳转到指定目录。

```
发送: #select /home/user
Bot: 📁 /home/user
     [..] [projects] [downloads]
```

### #verbose on|off

控制 thinking 卡片显示：

| 设置 | Thinking 输出 |
|------|--------------|
| `#verbose off` | `Thinking...` → `Thinking...OK!`（占位符） |
| `#verbose on` | 真实 Claude thinking 内容（流式更新） |

### #screenshot

截取当前 tmux 窗格并发送到飞书。

### #session list

列出 cclark 管理的所有 tmux 会话。

### #session close \<window_id\>

关闭指定的 cclark 管理会话。

```
发送: #session close @2
Bot: 已关闭窗口 @2
```

### #cancel

取消当前的会话创建向导，返回初始状态。

## 会话创建流程

`#new` 启动三步向导：

```
你: #new
Bot: 📁 选择目录
     [..] [project_a] [project_b]

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

## 目录导航

| 输入 | 行为 |
|------|------|
| `..` | 返回上级目录 |
| 目录名 | 进入该目录 |
| 数字 | 进入对应编号的目录 |
| `#mkdir <name>` | 创建并进入新目录 |
| `#select <path>` | 跳转到绝对路径 |

## 数字回复审批

当 Claude 需要权限/计划决策时，显示编号选项。直接回复数字即可。

### 权限审批

```
Bot: 🔐 Claude 需要权限
     1. Allow, don't ask again
     2. Allow once
     3. Deny
     4. Deny and don't ask again

你: 2
```

### Plan Mode 选项

```
Bot: 📋 Claude 提出了计划...
     1. Yes, proceed
     2. Exit plan mode
     3. Tell Claude what to change

你: 1
```

### Plan Mode Option 3

选项 3 是两步流程：

```
你: 3
     ── cclark 进入"等待反馈文本"状态 ──

你: 请改为使用 Python 的 async/await 语法
     ── 反馈文本被发送，不带 Enter ──

Bot: (Claude 应用反馈，继续执行)
```

实现原理：`send_to_window(text, enter=False)` 先发送反馈，再发送空行+Enter 提交。

## Claude Slash Commands

会话创建后，以下命令会转发给 Claude：

| 命令 | 说明 |
|------|------|
| `/status` | 显示 Claude 状态 |
| `/plan` | 进入 Plan Mode |
| `/permissions` | 查看/管理权限 |
| `/model` | 切换模型 |
| `/help` | Claude 帮助 |

## Provider 差异

| 特性 | Claude Code | Codex CLI |
|------|-------------|-----------|
| 会话发现 | hooks → session_map.json | 扫描 sessions/ |
| 思考内容 | thinking block | 无 |
| `#verbose` 效果 | 控制 thinking 显示 | 无效果 |
| Plan Mode | 支持 | 支持 |

## 下一步

- [架构介绍](architecture.md) — 了解组件和数据流
- [可扩展性](extending.md) — 自定义开发
