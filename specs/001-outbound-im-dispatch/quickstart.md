# Quickstart: Outbound IM Dispatch

**Feature**: 001-outbound-im-dispatch
**Date**: 2026-03-22

---

## Prerequisites

1. **as-dispatch** 运行中（`outbound-im-dispatch` worktree）
2. **AgentStudio** 运行中（main branch）
3. 企微群已配置 Bot Key 和 Chat ID
4. `JWT_SECRET_KEY` 环境变量在两个服务间共享

## Setup

### 1. 启动 as-dispatch

```bash
cd /Users/kongjie/projects/agent-studio/platform/as-dispatch/.worktrees/outbound-im-dispatch

# 安装依赖（如尚未安装）
uv sync

# 启动服务
USE_DATABASE=true uv run python -m forward_service.app
```

### 2. 启动 AgentStudio

```bash
cd /Users/kongjie/projects/agent-studio/agentstudio

# 设置 as-dispatch URL（确保两个服务用同一个 JWT_SECRET_KEY）
export AS_DISPATCH_URL="http://localhost:8083"
export JWT_SECRET_KEY="your-shared-secret"

pnpm run dev
```

## Testing Scenarios

### Scenario 1: Web-to-IM 消息转发

**Steps**:

1. 在 AgentStudio Web UI 中与 Agent 对话，获得一条 AI 回复
2. 点击 AI 消息气泡上的"转发到企微"按钮
3. 确认弹窗中的目标群信息，点击确认
4. 观察：
   - Web UI 上消息气泡显示"已转发"标识
   - 企微群收到消息，头部有 `[#ob_xxxxxx MyProject]` 标识

**Verify**:
```bash
# 查看 as-dispatch 日志，应看到:
# - POST /api/im/send 请求
# - 生成 outbound_short_id
# - fly-pigeon 发送成功
# - OutboundMessageContext 已保存

# 查询 outbound context:
curl -H "Authorization: Bearer <jwt>" \
  http://localhost:8083/api/outbound-context/ob_xxxxxx
```

### Scenario 2: 企微回复路由回 Agent 会话

**Steps**:

1. 在企微群中找到带 `[#ob_xxxxxx MyProject]` 标识的消息
2. 引用（Quote）该消息并回复
3. 观察：
   - as-dispatch 回调收到消息
   - 从引用文本中解析出 `ob_xxxxxx`
   - 查找到对应的 OutboundMessageContext
   - 调用 AgentStudio inject 端点注入回复
   - Agent 继续在原会话中处理回复

**Verify**:
```bash
# 查看 as-dispatch 日志，应看到:
# - 从引用消息中提取到 short_id: ob_xxxxxx
# - 匹配到出站消息上下文
# - 调用 AgentStudio inject 端点
```

### Scenario 3: 边界情况

1. **重复转发**: 同一消息多次点击转发，每次生成不同的 `ob_xxxxxx`
2. **过期上下文**: 7 天后回复已转发的消息，系统 fallback 到 HITL 路由
3. **非引用回复**: 在企微群直接回复（非引用），不触发 outbound routing
4. **Bot Key 无效**: 转发时使用无效 Bot Key，前端显示错误信息

## API Quick Test

### 直接测试 as-dispatch /api/im/send

```bash
# 生成 JWT token（或使用已有 token）
JWT_TOKEN="your-jwt-token"

# 发送消息
curl -X POST http://localhost:8083/api/im/send \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -d '{
    "message_content": "测试从 API 发送的消息",
    "bot_key": "your-bot-key",
    "chat_id": "your-chat-id",
    "session_id": "test-session-001",
    "project_name": "TestProject"
  }'

# 期望返回:
# {"success": true, "short_id": "ob_xxxxxx", "message_with_header": "[#ob_xxxxxx TestProject]\n\n测试从 API 发送的消息"}
```

### 测试 AgentStudio dispatch-im 代理

```bash
curl -X POST http://localhost:4936/api/agui/dispatch-im \
  -H "Content-Type: application/json" \
  -d '{
    "sessionId": "test-session-001",
    "messageContent": "测试消息内容",
    "botKey": "your-bot-key",
    "chatId": "your-chat-id",
    "projectName": "TestProject"
  }'

# 期望返回:
# {"success": true, "shortId": "ob_xxxxxx"}
```
