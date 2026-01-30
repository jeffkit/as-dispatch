# Telegram Bot 集成指南

## 概述

AS-Dispatch 现已支持 Telegram Bot 集成，可将用户消息转发到 AgentStudio 进行处理。

### 支持的功能

- ✅ 文本消息收发
- ✅ Markdown 格式支持
- ✅ 会话管理 (多会话切换)
- ✅ Slash 命令 (/sess, /reset, /change)
- ✅ Webhook 验证 (Secret Token)
- ✅ 群组和私聊支持
- 🚧 内联按钮 (框架已就绪)
- 🚧 图片/文件消息 (计划中)

### 限制

- 消息最大长度: 4096 字符
- Webhook 响应超时: 60 秒
- 需要 HTTPS (端口 443/80/88/8443)

---

## 前置条件

### 1. 创建 Telegram Bot

1. 在 Telegram 中搜索 **@BotFather**
2. 发送 `/newbot` 命令
3. 按提示设置 Bot 名称和用户名
4. 获取 **Bot Token** (格式: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. 配置 Webhook

使用 BotFather 或 API 设置 Webhook URL:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://hitl.woa.com/callback/telegram/<BOT_KEY>",
    "secret_token": "<YOUR_SECRET_TOKEN>"
  }'
```

**重要**: 
- 替换 `<YOUR_BOT_TOKEN>` 为你的 Bot Token
- 替换 `<BOT_KEY>` 为 AS-Dispatch 中的 Bot Key
- `secret_token` 用于验证请求来源（可选但推荐）

### 3. 允许 Telegram IP

如果有防火墙，需要允许 Telegram 的 IP 段:
- `149.154.160.0/20`
- `91.108.4.0/22`

---

## 配置步骤

### 方式 1: 通过数据库配置

```sql
INSERT INTO chatbots (
    bot_key,
    name,
    platform,
    platform_config,
    target_url,
    enabled
) VALUES (
    'my-telegram-bot',
    'My Telegram Bot',
    'telegram',
    '{"bot_token": "123456789:ABCdefGHI...", "secret_token": "your-secret-token"}',
    'http://localhost:4936/a2a/your-agent-id/messages',
    1
);
```

### 方式 2: 通过 Admin API 配置

```bash
curl -X POST "http://localhost:8083/admin/bots" \
  -H "Content-Type: application/json" \
  -d '{
    "bot_key": "my-telegram-bot",
    "name": "My Telegram Bot",
    "platform": "telegram",
    "platform_config": {
      "bot_token": "123456789:ABCdefGHI...",
      "secret_token": "your-secret-token"
    },
    "target_url": "http://localhost:4936/a2a/your-agent-id/messages",
    "enabled": true
  }'
```

### Platform Config 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `bot_token` | string | ✅ | Bot Token (从 @BotFather 获取) |
| `secret_token` | string | ❌ | Secret Token (用于 Webhook 验证) |
| `allowed_chat_ids` | array | ❌ | 允许的聊天 ID 列表 (白名单) |

---

## 使用指南

### 基本对话

1. 在 Telegram 中找到你的 Bot
2. 发送消息: `你好，帮我写一段代码`
3. Bot 会自动转发到 AgentStudio 处理
4. Agent 响应会自动回复到 Telegram

### Slash 命令

#### `/sess` 或 `/s` - 列出会话

查看当前用户的所有会话:

```
/sess
```

响应示例:
```
📋 会话列表 (共 3 个)

1. abc123 (当前) - 最后消息: 帮我写代码
   项目: my-project
   时间: 2026-01-29 20:30:15

2. def456 - 最后消息: 什么是 Python
   项目: default
   时间: 2026-01-29 18:15:30

3. ghi789 - 最后消息: 写个函数
   项目: my-project
   时间: 2026-01-28 14:20:00
```

#### `/reset` 或 `/r` - 重置会话

开始新的对话:

```
/reset
```

响应:
```
✅ 会话已重置，下次发送消息将开始新对话
```

#### `/change <id>` 或 `/c <id>` - 切换会话

切换到指定会话:

```
/c abc123
```

响应:
```
✅ 已切换到会话 `abc123`
最后消息: 帮我写代码
```

---

## API 参考

### 消息格式

#### 接收的 Update 对象

Telegram 发送的 Webhook 数据格式:

```json
{
  "update_id": 123456789,
  "message": {
    "message_id": 100,
    "from": {
      "id": 987654321,
      "is_bot": false,
      "first_name": "John",
      "username": "john_doe"
    },
    "chat": {
      "id": -1001234567890,
      "type": "group",
      "title": "My Group"
    },
    "date": 1738166400,
    "text": "Hello, bot!"
  }
}
```

#### 发送消息 API

```python
from forward_service.clients.telegram import TelegramClient

client = TelegramClient(bot_token="YOUR_BOT_TOKEN")

# 发送文本消息
await client.send_message(
    chat_id=123456789,
    text="Hello from AS-Dispatch!",
    parse_mode="Markdown"
)

# 发送图片
await client.send_photo(
    chat_id=123456789,
    photo="https://example.com/image.jpg",
    caption="Check out this image!"
)
```

---

## 测试

### 测试 Webhook 配置

```bash
# 检查 Webhook 状态
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

响应示例:
```json
{
  "ok": true,
  "result": {
    "url": "https://hitl.woa.com/callback/telegram/my-telegram-bot",
    "has_custom_certificate": false,
    "pending_update_count": 0,
    "last_error_date": 0,
    "max_connections": 40
  }
}
```

### 测试消息发送

```bash
# 手动发送测试消息
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/sendMessage" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": YOUR_CHAT_ID,
    "text": "Test message from API"
  }'
```

---

## 常见问题

### 1. Bot 没有收到消息

**可能原因**:
- Webhook URL 不正确
- 服务器无法访问
- Secret Token 不匹配
- Telegram IP 被防火墙阻止

**解决方法**:
```bash
# 检查 Webhook 状态
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"

# 查看最近的错误
# 检查 last_error_date 和 last_error_message 字段

# 重新设置 Webhook
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://your-server.com/callback/telegram/bot-key"
```

### 2. 消息发送失败

**可能原因**:
- Bot Token 无效
- 聊天 ID 错误
- Bot 被用户屏蔽
- 消息格式错误

**解决方法**:
- 检查日志中的错误信息
- 验证 Bot Token 是否正确
- 确认 Bot 有权限向该聊天发送消息

### 3. Markdown 格式错误

Telegram 对 Markdown 格式要求严格，特殊字符需要转义:

```python
# 使用客户端的转义方法
text = client.escape_markdown("Text with special_characters")
```

或者使用纯文本模式:
```python
await client.send_message(
    chat_id=chat_id,
    text=message,
    parse_mode=None  # 禁用 Markdown
)
```

### 4. Webhook 响应超时

Telegram 要求在 60 秒内响应，建议:
- 使用异步处理: `asyncio.create_task()`
- 立即返回 200 OK
- 后台处理消息

我们的实现已经采用了这种方式:
```python
# 立即返回响应
asyncio.create_task(handle_telegram_message(...))
return JSONResponse(status_code=200, content={"ok": True})
```

---

## 安全建议

1. **使用 Secret Token**: 在 Webhook 配置中启用 secret_token
2. **IP 白名单**: 仅允许 Telegram 官方 IP 访问
3. **HTTPS**: 必须使用 HTTPS (Telegram 要求)
4. **聊天白名单**: 通过 `allowed_chat_ids` 限制访问
5. **速率限制**: Telegram API 有每秒 30 条消息的限制

---

## 高级功能

### 内联按钮

```python
# 构建内联键盘
buttons = client.build_inline_keyboard([
    [
        {"text": "选项 1", "callback_data": "option_1"},
        {"text": "选项 2", "callback_data": "option_2"}
    ],
    [
        {"text": "访问网站", "url": "https://example.com"}
    ]
])

# 发送带按钮的消息
await client.send_message(
    chat_id=chat_id,
    text="请选择一个选项:",
    reply_markup=buttons
)
```

### 群组权限

如果在群组中使用，需要:
1. 将 Bot 添加到群组
2. 给予 Bot 发送消息权限
3. 可选: 设置为群组管理员 (获取更多权限)

---

## 相关资源

- [Telegram Bot API 官方文档](https://core.telegram.org/bots/api)
- [Webhook 指南](https://core.telegram.org/bots/webhooks)
- [Bot FAQ](https://core.telegram.org/bots/faq)
- [AS-Dispatch 主文档](./README.md)

---

**最后更新**: 2026-01-29
**版本**: 1.0
