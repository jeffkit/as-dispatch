# Slack 集成指南

本文档介绍如何在 as-dispatch 中配置和使用 Slack 集成。

## 架构概览

```
Slack Workspace
      ↓
   Slack App
      ↓
  Events API Webhook
      ↓
as-dispatch (/callback/slack)
      ↓
  HTTP POST
      ↓
agentstudio (A2A API)
```

## 前置准备

### 1. 创建 Slack App

1. 访问 [https://api.slack.com/apps](https://api.slack.com/apps)
2. 点击 "Create New App" → "From scratch"
3. 输入 App 名称和选择 Workspace
4. 创建成功后，记录以下信息：
   - **App ID**: 应用标识
   - **Bot Token**: `xoxb-...` (在 "OAuth & Permissions" 页面)
   - **Signing Secret**: 签名密钥 (在 "Basic Information" 页面)

### 2. 配置 Slack App 权限

在 "OAuth & Permissions" 页面，添加以下 **Bot Token Scopes**:

- `chat:write` - 发送消息
- `chat:write.public` - 在公共频道发送消息
- `channels:history` - 读取公共频道消息
- `groups:history` - 读取私有频道消息
- `im:history` - 读取私信消息
- `mpim:history` - 读取群组私信消息
- `app_mentions:read` - 读取 @提及
- `files:read` - 读取文件 (可选，如果需要处理图片)

### 3. 启用 Events API

在 "Event Subscriptions" 页面:

1. 启用 "Enable Events"
2. 设置 **Request URL**: `https://your-domain.com/callback/slack`
   - as-dispatch 会自动处理 URL verification
3. 订阅以下 Bot Events:
   - `message.channels` - 公共频道消息
   - `message.groups` - 私有频道消息
   - `message.im` - 私信消息
   - `message.mpim` - 群组私信消息
   - `app_mention` - @提及事件

### 4. 安装 App 到 Workspace

在 "Install App" 页面，点击 "Install to Workspace"，授权后获得 Bot Token。

## as-dispatch 配置

### 方式 1: 数据库配置（推荐）

使用数据库管理 Slack Bot 配置:

```python
# 示例：通过 API 或直接数据库操作添加 Slack Bot
from forward_service.models import Chatbot
import json

slack_bot = Chatbot(
    bot_key="your-team-id",  # 使用 Slack Team ID
    name="Slack AgentStudio Bot",
    description="AgentStudio Slack 集成",
    platform="slack",
    platform_config=json.dumps({
        "bot_token": "xoxb-your-bot-token",
        "signing_secret": "your-signing-secret",
        "default_agent_id": "general-chat"
    }),
    target_url="http://localhost:4936/api/a2a/agent-id/messages",
    api_key="your-agentstudio-api-key",
    timeout=120,
    access_mode="allow_all",
    enabled=True
)

# 保存到数据库
# ...
```

### 方式 2: 环境变量配置（临时测试）

```bash
# .env 或环境变量
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret
SLACK_DEFAULT_AGENT_ID=general-chat
```

## 数据库迁移

运行迁移以添加 `platform` 和 `platform_config` 字段:

```bash
cd as-dispatch
uv run python -m alembic upgrade head
```

## 启动服务

```bash
cd as-dispatch
USE_DATABASE=true uv run python -m forward_service.app
```

服务将在 `http://0.0.0.0:8083` 启动。

## 测试集成

### 1. 验证 Webhook URL

Slack 会发送 `url_verification` 挑战，as-dispatch 会自动响应。

在 Slack "Event Subscriptions" 页面，你应该看到绿色的 "Verified" 标记。

### 2. 发送测试消息

1. 在 Slack Workspace 中邀请 Bot 到一个频道:
   ```
   /invite @AgentStudio
   ```

2. 发送消息:
   ```
   @AgentStudio 你好
   ```

3. Bot 应该回复消息。

## 支持的功能

### 基础对话

```
@AgentStudio 帮我写一个 Python 函数计算斐波那契数列
```

### 会话管理 (未来支持)

```
/sess - 列出所有会话
/reset - 重置会话
/change <short_id> - 切换会话
```

### 项目指定 (未来支持)

```
@AgentStudio proj:my-project 帮我修复这个 bug
```

## 故障排查

### 1. Webhook 验证失败

- 检查 `SLACK_SIGNING_SECRET` 配置是否正确
- 确保请求 URL 可以从公网访问
- 查看 as-dispatch 日志

### 2. Bot 不响应

- 检查 Bot Token 是否有效
- 确认 Bot 已被邀请到频道
- 检查 Events API 订阅是否正确
- 查看 as-dispatch 日志

### 3. 消息延迟

- Slack 要求 3 秒内响应 webhook
- as-dispatch 会立即返回 200，然后异步处理
- 检查 agentstudio 的响应速度

## 架构说明

### 签名验证

as-dispatch 使用 HMAC SHA-256 验证所有来自 Slack 的请求，防止伪造请求。

### 会话管理

- Slack 使用 `channel + thread_ts` 作为会话标识
- 会话信息存储在数据库中
- 支持会话持续性和历史记录

### 消息处理流程

1. Slack 发送事件 → as-dispatch
2. as-dispatch 验证签名
3. 发送占位消息 "🤔 正在思考..."
4. 转发到 agentstudio (A2A API)
5. 更新占位消息为 Agent 响应
6. 记录会话信息

## 高级配置

### 多 Bot 支持

可以配置多个 Slack Bot，每个 Bot 连接不同的 Workspace:

```python
# Bot 1: Team A
slack_bot_team_a = Chatbot(
    bot_key="team-a-id",
    platform="slack",
    platform_config=json.dumps({
        "bot_token": "xoxb-team-a-token",
        "signing_secret": "team-a-secret"
    }),
    ...
)

# Bot 2: Team B
slack_bot_team_b = Chatbot(
    bot_key="team-b-id",
    platform="slack",
    platform_config=json.dumps({
        "bot_token": "xoxb-team-b-token",
        "signing_secret": "team-b-secret"
    }),
    ...
)
```

### 访问控制

支持白名单/黑名单控制用户访问:

```python
bot.access_mode = "whitelist"  # 或 "blacklist", "allow_all"
```

在数据库中添加访问规则:

```python
from forward_service.models import ChatAccessRule

rule = ChatAccessRule(
    chatbot_id=bot.id,
    chat_id="U123456",  # Slack User ID
    rule_type="whitelist",
    remark="允许用户 A 访问"
)
```

## 参考资料

- [Slack API 文档](https://api.slack.com/)
- [Events API 指南](https://api.slack.com/apis/connections/events-api)
- [Bot Token 权限](https://api.slack.com/scopes)
