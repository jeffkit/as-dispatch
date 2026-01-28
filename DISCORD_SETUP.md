# Discord Bot 快速配置指南

## 1. 创建 Discord Bot

### 步骤 1: 访问 Discord Developer Portal

1. 访问 [Discord Developer Portal](https://discord.com/developers/applications)
2. 点击 "New Application"
3. 输入应用名称（例如: "AgentStudio Bot"）
4. 点击 "Create"

### 步骤 2: 创建 Bot 用户

1. 在左侧导航栏点击 "Bot"
2. 点击 "Add Bot"
3. 确认创建 Bot

### 步骤 3: 配置 Bot 权限

在 "Bot" 页面:

1. **启用 Privileged Gateway Intents** (必需):
   - ✅ **MESSAGE CONTENT INTENT** (必需，读取消息内容)
   - ✅ **SERVER MEMBERS INTENT** (可选，用于未来扩展)
   - ✅ **PRESENCE INTENT** (可选)

2. **复制 Bot Token**:
   - 点击 "Reset Token" 或 "Copy"
   - ⚠️ **请妥善保管 Token，不要泄露！**

### 步骤 4: 获取其他信息

1. 在左侧导航栏点击 "General Information"
2. 复制以下信息：
   - **Application ID**
   - **Public Key**

## 2. 配置 as-dispatch

### 方式 1: 数据库配置（推荐）

在数据库中添加 Discord Bot 配置：

```sql
INSERT INTO chatbots (
    bot_key,
    name,
    description,
    platform,
    platform_config,
    target_url,
    api_key,
    timeout,
    access_mode,
    enabled,
    created_at,
    updated_at
) VALUES (
    'YOUR_APPLICATION_ID',                 -- 使用 Application ID 作为 bot_key
    'AgentStudio Discord Bot',
    'Discord DM 集成',
    'discord',                              -- 平台类型
    '{"bot_token": "YOUR_BOT_TOKEN", "application_id": "YOUR_APPLICATION_ID", "public_key": "YOUR_PUBLIC_KEY"}',
    'http://localhost:4936/api/a2a/agent-id/messages',  -- 替换为实际的 Agent Studio API
    'your-agentstudio-api-key',            -- 替换为实际的 API Key
    120,
    'allow_all',
    1,
    NOW(),
    NOW()
);
```

### 方式 2: Python 脚本配置

创建配置脚本 `scripts/add_discord_bot.py`:

```python
import asyncio
import json
from forward_service.database import get_db_manager
from forward_service.models import Chatbot

async def add_discord_bot():
    """添加 Discord Bot 配置"""
    db_manager = get_db_manager()
    
    # 创建 Bot 配置
    bot = Chatbot(
        bot_key="YOUR_APPLICATION_ID",
        name="AgentStudio Discord Bot",
        description="Discord DM 集成",
        platform="discord",
        platform_config=json.dumps({
            "bot_token": "YOUR_BOT_TOKEN",
            "application_id": "YOUR_APPLICATION_ID",
            "public_key": "YOUR_PUBLIC_KEY",
            "default_agent_id": "general-chat"
        }),
        target_url="http://localhost:4936/api/a2a/agent-id/messages",
        api_key="your-agentstudio-api-key",
        timeout=120,
        access_mode="allow_all",
        enabled=True
    )
    
    # 保存到数据库
    async with db_manager.get_session() as session:
        session.add(bot)
        await session.commit()
        print(f"✅ Discord Bot 已添加: {bot.name}")

if __name__ == "__main__":
    asyncio.run(add_discord_bot())
```

运行脚本：

```bash
cd as-dispatch-discord
uv run python scripts/add_discord_bot.py
```

## 3. 启动服务

```bash
cd as-dispatch-discord

# 安装依赖
uv sync

# 启动服务
USE_DATABASE=true uv run python -m forward_service.app
```

## 4. 测试 Bot

### 邀请 Bot 到服务器（可选）

1. 在 Discord Developer Portal 中，进入 "OAuth2" → "URL Generator"
2. 选择 Scopes:
   - ✅ `bot`
3. 选择 Bot Permissions:
   - ✅ Send Messages
   - ✅ Read Message History
   - ✅ Use Slash Commands (未来支持)
4. 复制生成的 URL，在浏览器中打开
5. 选择要邀请的服务器，授权

### 发送 DM 测试

1. 在 Discord 中找到你的 Bot 用户
2. 右键点击 Bot → "Message"
3. 发送消息: "Hello, Bot!"
4. Bot 应该回复

## 5. 故障排查

### Bot 无法启动

1. **检查 Bot Token**: 确认 Token 正确且未过期
2. **检查 Intents**: 确保启用了 MESSAGE_CONTENT intent
3. **查看日志**: 检查 as-dispatch 日志输出

```bash
# 查看服务日志
tail -f /path/to/logs/forward_service.log
```

### Bot 不响应 DM

1. **确认 Bot 在线**: 在 Discord 中查看 Bot 状态
2. **检查配置**: 确认数据库中 Bot 配置正确
3. **查看日志**: 检查是否有错误信息

### 消息发送失败

1. **检查权限**: 确认 Bot 有发送消息的权限
2. **检查 API**: 确认 Agent Studio API 可访问
3. **查看日志**: 检查转发日志

## 6. 高级配置

### 访问控制

设置白名单模式，只允许特定用户访问：

```sql
-- 更新 Bot 访问模式为白名单
UPDATE chatbots 
SET access_mode = 'whitelist' 
WHERE platform = 'discord' AND bot_key = 'YOUR_APPLICATION_ID';

-- 添加白名单用户
INSERT INTO chat_access_rules (chatbot_id, chat_id, rule_type, remark)
SELECT id, '123456789012345678', 'whitelist', '允许的用户'
FROM chatbots 
WHERE platform = 'discord' AND bot_key = 'YOUR_APPLICATION_ID';
```

### 多 Bot 支持

可以配置多个 Discord Bot，每个 Bot 连接不同的服务：

```python
# Bot 1: 用于 Agent A
bot1 = Chatbot(
    bot_key="app_id_1",
    platform="discord",
    target_url="http://localhost:4936/api/a2a/agent-a/messages",
    ...
)

# Bot 2: 用于 Agent B
bot2 = Chatbot(
    bot_key="app_id_2",
    platform="discord",
    target_url="http://localhost:4936/api/a2a/agent-b/messages",
    ...
)
```

## 7. 会话管理命令

用户可以通过以下命令管理会话：

```
/sess 或 /s         - 列出所有会话
/reset 或 /r        - 重置当前会话
/change <id> 或 /c <id> - 切换到指定会话
```

## 参考资料

- [Discord Developer Portal](https://discord.com/developers/docs)
- [discord.py 文档](https://discordpy.readthedocs.io/)
- [Discord Bot 权限计算器](https://discordapi.com/permissions.html)
