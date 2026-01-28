# Discord 集成设计方案

## 概览

为 as-dispatch 添加 Discord Bot 支持，优先实现私信（DM）场景，使用户能够通过 Discord 直接与 Agent Studio 交互。

## 架构设计

### 消息流程

```
Discord DM
    ↓
Discord Bot (Gateway WebSocket)
    ↓
Discord Events API
    ↓
as-dispatch (/callback/discord)
    ↓
HTTP POST
    ↓
agentstudio (A2A API)
```

### 技术选型

- **Discord API 版本**: v10
- **Python 库**: `discord.py` (官方推荐库)
- **Gateway Intents**: 
  - `DIRECT_MESSAGES` (必需，接收私信)
  - `MESSAGE_CONTENT` (必需，读取消息内容)
  - `GUILDS` (可选，用于未来扩展频道功能)

## 数据库设计

### 利用现有表结构

```python
# Chatbot 表新增 Discord Bot 配置
Chatbot(
    bot_key="discord-bot-1",  # 使用 Bot Application ID
    name="AgentStudio Discord Bot",
    platform="discord",  # 新增平台类型
    platform_config=json.dumps({
        "bot_token": "YOUR_BOT_TOKEN",
        "application_id": "YOUR_APPLICATION_ID",
        "public_key": "YOUR_PUBLIC_KEY",  # 用于签名验证
        "default_agent_id": "general-chat"
    }),
    target_url="http://localhost:4936/api/a2a/agent-id/messages",
    api_key="your-agentstudio-api-key",
    timeout=120,
    access_mode="allow_all",
    enabled=True
)
```

### 会话标识

- **DM 场景**: `user_id` 作为 `chat_id`
- **频道场景** (未来): `channel_id:thread_id` 作为 `chat_id`

## 实现计划

### Phase 1: 基础架构（1-2天）

#### 1.1 依赖安装

```bash
# 添加 discord.py 依赖
cd as-dispatch
uv add discord.py[voice]  # voice 可选
```

#### 1.2 创建 Discord Client

文件: `forward_service/clients/discord.py`

```python
"""Discord Bot 客户端"""
import logging
from typing import Optional
import discord

logger = logging.getLogger(__name__)

class DiscordClient(discord.Client):
    """Discord Bot 客户端，处理 DM 消息"""
    
    def __init__(self, bot_token: str, on_message_callback):
        intents = discord.Intents.default()
        intents.messages = True
        intents.message_content = True
        intents.dm_messages = True
        
        super().__init__(intents=intents)
        self.bot_token = bot_token
        self.on_message_callback = on_message_callback
    
    async def on_ready(self):
        logger.info(f"✅ Discord Bot 已启动: {self.user}")
    
    async def on_message(self, message: discord.Message):
        # 忽略自己发的消息
        if message.author == self.user:
            return
        
        # 只处理私信
        if not isinstance(message.channel, discord.DMChannel):
            return
        
        # 调用回调处理消息
        await self.on_message_callback(message)
    
    async def send_message(
        self,
        channel_id: int,
        content: str,
        embed: Optional[discord.Embed] = None
    ) -> discord.Message:
        """发送消息到 Discord"""
        channel = self.get_channel(channel_id)
        if not channel:
            # 如果找不到频道，尝试通过用户 DM
            user = await self.fetch_user(channel_id)
            if user:
                channel = await user.create_dm()
        
        if not channel:
            raise Exception(f"无法找到频道: {channel_id}")
        
        return await channel.send(content=content, embed=embed)
    
    async def start_bot(self):
        """启动 Bot"""
        await self.start(self.bot_token)
```

#### 1.3 创建 Discord 路由

文件: `forward_service/routes/discord.py`

```python
"""Discord 集成路由"""
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks
import discord

from ..clients.discord import DiscordClient
from ..config import config
from ..services.forwarder import forward_to_agent_with_user_project
from ..session_manager import get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["discord"])

# 全局 Discord Bot 实例
discord_bots = {}

async def handle_discord_message(message: discord.Message):
    """处理 Discord DM 消息"""
    user_id = str(message.author.id)
    channel_id = message.channel.id
    content = message.content
    
    # 查找对应的 Bot 配置
    # TODO: 支持多 Bot，暂时使用默认 Bot
    bot = config.get_bot_by_platform("discord")
    if not bot:
        logger.error("未找到 Discord Bot 配置")
        return
    
    # 获取会话管理器
    session_mgr = get_session_manager()
    
    # 获取或创建会话
    session_key = f"dm:{user_id}"
    active_session = await session_mgr.get_active_session(user_id, session_key, bot.bot_key)
    current_session_id = active_session.session_id if active_session else None
    current_project_id = active_session.current_project_id if active_session else None
    
    # 检查是否为 Slash 命令
    if content:
        slash_cmd = session_mgr.parse_slash_command(content)
        if slash_cmd:
            await handle_discord_command(
                message=message,
                session_mgr=session_mgr,
                user_id=user_id,
                bot=bot,
                cmd_type=slash_cmd[0],
                cmd_arg=slash_cmd[1],
                extra_msg=slash_cmd[2],
                session_key=session_key,
                current_session_id=current_session_id
            )
            return
    
    try:
        # 发送 "正在思考..." 占位消息
        placeholder_msg = await message.channel.send("🤔 正在思考...")
        
        # 处理图片附件
        image_data = None
        if message.attachments:
            for attachment in message.attachments:
                if attachment.content_type and attachment.content_type.startswith("image/"):
                    import base64
                    import httpx
                    async with httpx.AsyncClient() as client:
                        response = await client.get(attachment.url)
                        image_data = {
                            "data": base64.b64encode(response.content).decode("utf-8"),
                            "mediaType": attachment.content_type,
                            "filename": attachment.filename
                        }
                    break
        
        # 转发消息到 Agent
        result = await forward_to_agent_with_user_project(
            bot_key=bot.bot_key,
            chat_id=session_key,
            content=content or "(图片消息)",
            timeout=config.timeout,
            session_id=current_session_id,
            current_project_id=current_project_id
        )
        
        if not result:
            await placeholder_msg.edit(content="⚠️ 处理请求时发生错误，请稍后重试")
            return
        
        # 更新占位消息为 Agent 响应
        # Discord 消息长度限制: 2000 字符
        reply = result.reply
        if len(reply) > 2000:
            # 分段发送
            await placeholder_msg.delete()
            for i in range(0, len(reply), 1900):
                chunk = reply[i:i+1900]
                await message.channel.send(chunk)
        else:
            await placeholder_msg.edit(content=reply)
        
        # 记录会话
        if result.session_id:
            await session_mgr.record_session(
                user_id=user_id,
                chat_id=session_key,
                bot_key=bot.bot_key,
                session_id=result.session_id,
                last_message=content,
                current_project_id=current_project_id
            )
            logger.info(f"会话已记录: session={result.session_id[:8]}...")
    
    except Exception as e:
        logger.error(f"处理 Discord 消息失败: {e}", exc_info=True)
        try:
            await placeholder_msg.edit(content=f"❌ 错误: {str(e)}")
        except:
            pass


async def handle_discord_command(
    message: discord.Message,
    session_mgr,
    user_id: str,
    bot,
    cmd_type: str,
    cmd_arg: Optional[str],
    extra_msg: Optional[str],
    session_key: str,
    current_session_id: Optional[str]
):
    """处理 Discord Slash 命令"""
    try:
        if cmd_type == "list":
            # /sess 或 /s
            sessions = await session_mgr.list_sessions(user_id, session_key, bot_key=bot.bot_key)
            reply_msg = session_mgr.format_session_list(sessions)
            await message.channel.send(reply_msg)
        
        elif cmd_type == "reset":
            # /reset 或 /r
            success = await session_mgr.reset_session(user_id, session_key, bot.bot_key)
            if success:
                reply_msg = "✅ 会话已重置，下次发送消息将开始新对话"
            else:
                reply_msg = "✅ 已准备好开始新对话，请发送消息"
            await message.channel.send(reply_msg)
        
        elif cmd_type == "change":
            # /change <short_id> 或 /c <short_id>
            if not cmd_arg:
                await message.channel.send("❌ 请提供会话 ID，例如: `/c abc123`")
                return
            
            target_session = await session_mgr.change_session(user_id, session_key, cmd_arg, bot_key=bot.bot_key)
            if not target_session:
                await message.channel.send(f"❌ 未找到会话 `{cmd_arg}`\n使用 `/s` 查看可用会话")
                return
            
            reply_msg = f"✅ 已切换到会话 `{target_session.short_id}`\n最后消息: {target_session.last_message or '(无)'}"
            await message.channel.send(reply_msg)
        
        else:
            await message.channel.send(f"❓ 未知命令: `/{cmd_type}`")
    
    except Exception as e:
        logger.error(f"处理 Discord 命令失败: {e}", exc_info=True)
        await message.channel.send(f"❌ 命令执行失败: {str(e)}")


async def start_discord_bot(bot_key: str):
    """启动 Discord Bot"""
    bot_config = config.get_bot_or_default(bot_key)
    if not bot_config or bot_config.platform != "discord":
        logger.error(f"未找到 Discord Bot 配置: {bot_key}")
        return
    
    platform_config = bot_config.get_platform_config()
    bot_token = platform_config.get("bot_token")
    
    if not bot_token:
        logger.error("Discord Bot Token 未配置")
        return
    
    # 创建并启动 Bot
    client = DiscordClient(bot_token, handle_discord_message)
    discord_bots[bot_key] = client
    
    logger.info(f"启动 Discord Bot: {bot_key}")
    await client.start_bot()
```

#### 1.4 集成到主应用

修改文件: `forward_service/app.py`

```python
# 在 app.py 中添加 Discord Bot 启动逻辑
from .routes import discord as discord_router

# 添加路由
app.include_router(discord_router.router)

# 启动时启动 Discord Bot
@app.on_event("startup")
async def startup_discord_bots():
    """启动所有 Discord Bot"""
    from .config import config
    
    # 查找所有启用的 Discord Bot
    for bot_key, bot in config.bots.items():
        if bot.platform == "discord" and bot.enabled:
            import asyncio
            asyncio.create_task(discord_router.start_discord_bot(bot_key))
```

### Phase 2: 配置和部署（0.5天）

#### 2.1 环境变量配置

文件: `as-dispatch/.env.example`

```bash
# Discord Bot 配置
DISCORD_BOT_TOKEN=YOUR_BOT_TOKEN_HERE
DISCORD_APPLICATION_ID=YOUR_APPLICATION_ID_HERE
DISCORD_PUBLIC_KEY=YOUR_PUBLIC_KEY_HERE
DISCORD_DEFAULT_AGENT_ID=general-chat
```

#### 2.2 数据库迁移

```bash
# 创建迁移（如果需要新增字段）
cd as-dispatch
alembic revision --autogenerate -m "Add Discord platform support"
alembic upgrade head
```

#### 2.3 配置示例

通过数据库添加 Discord Bot:

```python
from forward_service.models import Chatbot
import json

discord_bot = Chatbot(
    bot_key="discord-bot-main",
    name="AgentStudio Discord Bot",
    description="AgentStudio Discord DM 集成",
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
```

### Phase 3: 测试和优化（0.5-1天）

#### 3.1 单元测试

文件: `tests/test_discord.py`

```python
"""Discord 集成测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock
import discord

from forward_service.routes.discord import handle_discord_message


@pytest.mark.asyncio
async def test_discord_dm_message():
    """测试 Discord DM 消息处理"""
    # Mock Discord Message
    message = MagicMock(spec=discord.Message)
    message.author.id = 123456789
    message.content = "Hello, Agent!"
    message.channel = MagicMock(spec=discord.DMChannel)
    message.channel.send = AsyncMock()
    
    # 处理消息
    await handle_discord_message(message)
    
    # 验证发送了占位消息
    message.channel.send.assert_called()
```

#### 3.2 集成测试

- 创建测试 Discord Bot
- 测试 DM 消息发送和接收
- 测试会话管理命令 (/sess, /reset, /change)
- 测试错误处理

### Phase 4: 文档和部署（0.5天）

#### 4.1 用户文档

完善 `DISCORD_INTEGRATION.md`，包括:
- Discord Bot 创建步骤
- 权限配置
- 部署指南
- 故障排查

#### 4.2 部署清单

- [ ] 在 Discord Developer Portal 创建 Bot
- [ ] 配置 Bot Intents (MESSAGE_CONTENT, DIRECT_MESSAGES)
- [ ] 获取 Bot Token
- [ ] 在数据库中添加 Bot 配置
- [ ] 启动 as-dispatch 服务
- [ ] 测试 DM 消息
- [ ] 监控日志

## Discord Bot 创建指南

### 1. 创建 Discord Application

1. 访问 [Discord Developer Portal](https://discord.com/developers/applications)
2. 点击 "New Application"
3. 输入应用名称（如 "AgentStudio Bot"）
4. 进入 "Bot" 页面，点击 "Add Bot"

### 2. 配置 Bot 权限

在 "Bot" 页面:
- 启用 **MESSAGE CONTENT INTENT** (必需)
- 启用 **DIRECT MESSAGES** (必需)
- 复制 **Bot Token**

在 "General Information" 页面:
- 复制 **Application ID**
- 复制 **Public Key**

### 3. 邀请 Bot 到服务器（可选）

1. 在 "OAuth2" → "URL Generator" 页面
2. 选择 Scopes: `bot`
3. 选择 Bot Permissions:
   - Send Messages
   - Read Message History
   - Use Slash Commands (未来支持)
4. 复制生成的 URL，在浏览器中打开邀请 Bot

### 4. 测试 Bot

1. 在 Discord 中找到 Bot 用户
2. 发送 DM: "Hello, Bot!"
3. Bot 应该回复

## 技术细节

### Discord 消息长度限制

- 普通消息: 2000 字符
- Embed 描述: 4096 字符
- 建议分段策略: 每段 1900 字符，避免边界问题

### 会话管理

- **chat_id 格式**: `dm:{user_id}` (DM 场景)
- **session_key**: 同 chat_id
- **会话持久化**: 存储在 `user_sessions` 表

### 错误处理

- Discord API 限流: 使用指数退避重试
- 网络错误: 自动重连（discord.py 内置）
- Agent 超时: 返回友好错误消息

## 未来扩展

### Phase 5: 频道支持（可选）

- 支持 @mention Bot 在频道中触发
- 自动创建 private thread 回复
- 支持多服务器部署

### Phase 6: Slash Commands（可选）

- 注册 Discord Slash Commands
- 支持 `/ask <question>` 命令
- 支持 ephemeral 回复（只有用户可见）

### Phase 7: 高级功能（可选）

- 语音频道支持
- 文件上传/下载
- 富文本 Embed 回复
- 按钮/菜单交互

## 风险和注意事项

### 1. Discord API 限制

- **速率限制**: 全局限流 50 请求/秒，需要遵守
- **Gateway 连接**: 单个 Bot Token 只能建立一个 Gateway 连接
- **Intents 权限**: MESSAGE_CONTENT intent 需要 Discord 审核（Bot 达到 100 个服务器时）

### 2. 私密性保证

- DM 消息完全私密，只有用户和 Bot 可见
- Bot 无法主动发起 DM，用户需要先发消息
- 服务器管理员无法查看用户与 Bot 的 DM 内容

### 3. 部署建议

- 使用 systemd 管理 Discord Bot 进程
- 配置日志轮转
- 监控 Bot 在线状态

## 时间估算

| Phase | 任务 | 预计时间 |
|-------|------|---------|
| 1 | 基础架构实现 | 1-2 天 |
| 2 | 配置和部署 | 0.5 天 |
| 3 | 测试和优化 | 0.5-1 天 |
| 4 | 文档和部署 | 0.5 天 |
| **总计** | | **2.5-4 天** |

## 参考资料

- [Discord Developer Portal](https://discord.com/developers/docs)
- [discord.py 文档](https://discordpy.readthedocs.io/)
- [Discord Bot 最佳实践](https://discord.com/developers/docs/topics/community-resources)
