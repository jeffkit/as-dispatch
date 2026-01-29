"""
Discord 集成路由

处理 Discord Bot 消息:
- DM (Direct Message) 消息处理
- 会话管理命令 (/sess, /reset, /change)
- 图片附件支持
"""
import logging
from typing import Optional, Dict
import base64

import discord
import httpx

from ..clients.discord import DiscordBotClient
from ..config import config
from ..services.forwarder import forward_to_agent_with_user_project
from ..session_manager import get_session_manager

logger = logging.getLogger(__name__)

# 全局 Discord Bot 实例字典
discord_bots: Dict[str, DiscordBotClient] = {}


async def handle_discord_message(message: discord.Message, client: DiscordBotClient):
    """
    处理 Discord DM 消息
    
    Args:
        message: Discord 消息对象
        client: Discord Bot 客户端实例
    """
    user_id = str(message.author.id)
    content = message.content
    
    # 查找对应的 Bot 配置
    bot = config.get_bot_or_default(client.bot_key)
    if not bot:
        logger.error(f"未找到 Discord Bot 配置: {client.bot_key}")
        return
    
    # 获取会话管理器
    session_mgr = get_session_manager()
    
    # 获取或创建会话
    # DM 场景使用 "dm:{user_id}" 作为 session_key
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
                client=client,
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
            logger.info(f"检测到 {len(message.attachments)} 个附件")
            for attachment in message.attachments:
                # 只处理图片类型
                if attachment.content_type and attachment.content_type.startswith("image/"):
                    try:
                        # 下载图片
                        async with httpx.AsyncClient() as http_client:
                            response = await http_client.get(attachment.url)
                            response.raise_for_status()
                            image_bytes = response.content
                        
                        # 转换为 base64
                        image_data = {
                            "data": base64.b64encode(image_bytes).decode("utf-8"),
                            "mediaType": attachment.content_type,
                            "filename": attachment.filename
                        }
                        logger.info(f"成功处理图片: {attachment.filename}")
                        break  # 只处理第一张图片
                    except Exception as e:
                        logger.error(f"下载图片失败: {e}")
        
        # 转发消息到 Agent
        # TODO: 支持图片参数（需要扩展 forward_to_agent_with_user_project）
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
            chunks = []
            for i in range(0, len(reply), 1900):
                chunk = reply[i:i+1900]
                chunks.append(chunk)
            
            for idx, chunk in enumerate(chunks):
                prefix = f"({idx+1}/{len(chunks)}) " if len(chunks) > 1 else ""
                await message.channel.send(prefix + chunk)
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
        except Exception:
            pass


async def handle_discord_command(
    message: discord.Message,
    client: DiscordBotClient,
    session_mgr,
    user_id: str,
    bot,
    cmd_type: str,
    cmd_arg: Optional[str],
    extra_msg: Optional[str],
    session_key: str,
    current_session_id: Optional[str]
):
    """
    处理 Discord Slash 命令
    
    Args:
        message: Discord 消息对象
        client: Discord Bot 客户端
        session_mgr: 会话管理器
        user_id: 用户 ID
        bot: Bot 配置对象
        cmd_type: 命令类型 (list/reset/change)
        cmd_arg: 命令参数
        extra_msg: 附加消息
        session_key: 会话键
        current_session_id: 当前会话 ID
    """
    try:
        if cmd_type == "list":
            # /sess 或 /s - 列出会话
            sessions = await session_mgr.list_sessions(user_id, session_key, bot_key=bot.bot_key)
            reply_msg = session_mgr.format_session_list(sessions)
            await message.channel.send(reply_msg)
        
        elif cmd_type == "reset":
            # /reset 或 /r - 重置会话
            success = await session_mgr.reset_session(user_id, session_key, bot.bot_key)
            if success:
                reply_msg = "✅ 会话已重置，下次发送消息将开始新对话"
            else:
                reply_msg = "✅ 已准备好开始新对话，请发送消息"
            await message.channel.send(reply_msg)
        
        elif cmd_type == "change":
            # /change <short_id> 或 /c <short_id> - 切换会话
            if not cmd_arg:
                await message.channel.send("❌ 请提供会话 ID，例如: `/c abc123`")
                return
            
            target_session = await session_mgr.change_session(
                user_id, session_key, cmd_arg, bot_key=bot.bot_key
            )
            if not target_session:
                await message.channel.send(
                    f"❌ 未找到会话 `{cmd_arg}`\n使用 `/s` 查看可用会话"
                )
                return
            
            reply_msg = (
                f"✅ 已切换到会话 `{target_session.short_id}`\n"
                f"最后消息: {target_session.last_message or '(无)'}"
            )
            await message.channel.send(reply_msg)
        
        else:
            await message.channel.send(f"❓ 未知命令: `/{cmd_type}`")
    
    except Exception as e:
        logger.error(f"处理 Discord 命令失败: {e}", exc_info=True)
        await message.channel.send(f"❌ 命令执行失败: {str(e)}")


async def start_discord_bot(bot_key: str):
    """
    启动 Discord Bot
    
    Args:
        bot_key: Bot 标识键
    """
    # 查找 Bot 配置
    bot_config = config.get_bot_or_default(bot_key)
    if not bot_config or bot_config.platform != "discord":
        logger.error(f"未找到 Discord Bot 配置: {bot_key}")
        return
    
    # 获取平台配置
    platform_config = bot_config.get_platform_config()
    bot_token = platform_config.get("bot_token")
    
    if not bot_token:
        logger.error(f"Discord Bot Token 未配置: {bot_key}")
        return
    
    # 创建并启动 Bot
    client = DiscordBotClient(
        bot_token=bot_token,
        on_message_callback=handle_discord_message,
        bot_key=bot_key
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
