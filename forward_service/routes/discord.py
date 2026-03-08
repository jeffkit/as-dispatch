"""
Discord 集成路由

处理 Discord Bot 消息:
- DM (Direct Message) 消息处理（通过统一管线）
- WebSocket Bot 生命周期管理
"""
import logging
from typing import Dict, Optional

import discord

from ..clients.discord import DiscordBotClient
from ..config import config
from ..channel import get_adapter
from ..pipeline import process_message

logger = logging.getLogger(__name__)

# 全局 Discord Bot 实例字典
discord_bots: Dict[str, DiscordBotClient] = {}


async def handle_discord_message(message: discord.Message, client: DiscordBotClient):
    """
    处理 Discord DM 消息（通过统一管线）

    将 discord.Message 序列化为 dict，经由 DiscordAdapter 解析，
    进入统一的 10 步 process_message 管线。

    WebSocket 生命周期（on_ready、on_message、start_bot）保持不变。

    Args:
        message: Discord 消息对象
        client: Discord Bot 客户端实例
    """
    bot_key = client.bot_key
    adapter = get_adapter("discord")
    if not adapter:
        logger.error("[discord] DiscordAdapter 未注册，无法处理消息")
        return

    # 序列化 discord.Message 为可序列化的 dict
    attachments = []
    for att in message.attachments:
        attachments.append({
            "url": att.url,
            "content_type": att.content_type or "",
            "filename": att.filename,
        })

    channel_type = "dm" if isinstance(message.channel, discord.DMChannel) else "text"

    raw_data = {
        "message_id": str(message.id),
        "content": message.content or "",
        "author_id": str(message.author.id),
        "author_name": str(message.author),
        "author_is_bot": message.author.bot,
        "channel_id": f"dm:{message.author.id}" if channel_type == "dm" else str(message.channel.id),
        "channel_type": channel_type,
        "attachments": attachments,
        "_bot_key": bot_key,
    }

    # 忽略检查
    if adapter.should_ignore(raw_data):
        logger.debug(f"[discord] 忽略消息: author={message.author}")
        return

    # 解析为 InboundMessage
    try:
        inbound = await adapter.parse_inbound(raw_data, bot_key=bot_key)
    except ValueError as e:
        logger.warning(f"[discord] 消息解析失败（跳过）: {e}")
        return

    # 进入统一处理管线
    try:
        await process_message(adapter, inbound)
    except Exception as e:
        logger.error(f"[discord] 处理消息失败: {e}", exc_info=True)
        try:
            await message.channel.send(f"❌ 错误: {str(e)}")
        except Exception:
            pass


async def start_discord_bot(bot_key: str):
    """
    启动 Discord Bot（WebSocket 连接）

    Args:
        bot_key: Bot 标识键
    """
    bot_config = config.get_bot_or_default(bot_key)
    if not bot_config:
        logger.error(f"未找到 Discord Bot 配置: {bot_key}")
        return

    # 通过 _bot（Chatbot 数据库模型）获取平台特定配置
    if not bot_config._bot:
        logger.error(f"Discord Bot 配置缺少底层数据库模型: {bot_key}")
        return

    platform_config = bot_config._bot.get_platform_config()
    bot_token = platform_config.get("bot_token")

    if not bot_token:
        logger.error(f"Discord Bot Token 未配置: {bot_key}")
        return

    # 创建并启动 Bot
    client = DiscordBotClient(
        bot_token=bot_token,
        on_message_callback=handle_discord_message,
        bot_key=bot_key,
    )
    discord_bots[bot_key] = client

    logger.info(f"🚀 启动 Discord Bot: {bot_key}")
    await client.start_bot()


def get_discord_bot(bot_key: str) -> Optional[DiscordBotClient]:
    """
    获取 Discord Bot 实例
    
    Args:
        bot_key: Bot 标识键
    
    Returns:
        Discord Bot 客户端实例，不存在返回 None
    """
    return discord_bots.get(bot_key)
