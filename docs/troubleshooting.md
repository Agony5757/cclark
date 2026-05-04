# 故障排除

## Bot 无响应

### 检查 cclark 进程

```bash
ps aux | grep cclark
```

### 检查 WebSocket 连接

日志中应有 `Connected to wss://...`。如果没有：
1. 检查飞书应用凭证是否正确
2. 确认飞书应用已启用「长连接」事件订阅
3. 查看 cclark 日志中的错误信息

### 检查 unified-icc 连接

日志中应有 `Connected to ws://127.0.0.1:8900`。如果没有：
1. 确认 unified-icc server 已启动
2. 检查 `~/.unified-icc/config.yaml` 中的 `unified_icc_ws_url`

## 消息发送失败

### 错误 `code: 99991663`

tenant_access_token 过期或无效。

**解决**：重启 cclark 刷新 token。

### 错误 `code: 230013`

应用没有该群的消息权限。

**解决**：
1. 在飞书管理后台添加权限
2. 确认应用已添加到群聊

### 错误 `code: 230014`

没有消息权限。

**解决**：在飞书开放平台为应用开通「发消息」权限。

## 会话绑定异常

### 显示「已有活跃会话」

这是预期行为。`#new` 会先清理旧会话再创建新的。

### 显示「Orphaned window」警告

未被状态追踪的 live Claude tmux 窗口。不会自动删除，需要手动清理：

```bash
tmux kill-window -t cclark:N
```

## 卡片不更新

### Output card 停止更新

回合结束后停止更新是正常行为。下一条消息会创建新卡片。

### Thinking card 显示占位符

`#verbose off` 时显示占位符是设计行为，不是 bug。

**解决**：发送 `#verbose on` 查看真实 thinking 内容。

### 卡片卡住

```bash
# 查看当前状态
发送 #status

# 关闭会话
发送 #session close @N

# 重新创建
发送 #new
```

## Claude 无响应

### 检查 session 状态

```bash
# 查看 unified-icc 状态
curl http://localhost:8900/api/v1/sessions

# 查看 tmux 窗口
tmux list-windows -t cclark
tmux capture-pane -t cclark:@N -p
```

### 常见原因

1. Claude 正在等待权限审批 → 回复数字审批
2. Claude 等待 Plan Mode 反馈 → 输入反馈或选择选项
3. 会话已断开 → `#new` 重新创建

## 权限审批问题

### 权限提示无响应

确认数字回复发送到正确的 thread/channel。权限提示属于交互状态，只有在提示可见时回复才有效。

### Option 3 反馈未生效

Plan mode option 3 是两步流程：
1. 先发送 `3`（不带 Enter）
2. 再发送反馈文本

确认两次消息间隔足够让 cclark 处理。

## 状态问题

### 状态不同步

```bash
# 查看状态文件
cat ~/.unified-icc/state.json

# 手动清理
rm ~/.unified-icc/state.json
# 重启 cclark
```

### 窗口泄露

多次 `#new` 后有孤儿窗口：

```bash
# 列出所有窗口
tmux list-windows -t cclark

# 杀死孤儿窗口
tmux kill-window -t cclark:3
```

## 日志调试

### 启用详细日志

```bash
# 设置日志级别
export RUST_LOG=debug
uv run cclark
```

### 查看 unified-icc 日志

```bash
# 实时查看
tail -f ~/.unified-icc/logs/*.log
```

## 寻求帮助

- 查看 [GitHub Issues](https://github.com/Agony5757/cclark/issues)
- 查看 [unified-icc 故障排除](../unified-icc/docs/troubleshooting.md)
