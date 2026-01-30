"""
Telegram Bot 路由

处理 Telegram Bot 消息:
- Webhook 接收和验证
- 消息解析和转发
- 会话管理命令
- 内联按钮处理
"""
import logging
from typing import Optional

from fastapi import APIRouter, Request, Response, Header
from fastapi.responses import JSONResponse

from ..clients.telegram import TelegramClient
from ..config import config
from ..services.forwarder import forward_to_agent_with_user_project
from ..session_manager import get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["telegram"])


async def handle_telegram_message(
    bot_key: str,
    update: dict,
    client: TelegramClient
) -> None:
    """
    处理 Telegram 消息
    
    Args:
        bot_key: Bot 标识
        update: Telegram Update 对象
        client: Telegram 客户端
    """
    # 解析消息
    parsed = client.parse_update(update)
    
    if not parsed.get("text"):
        logger.debug(f"忽略非文本消息: {update}")
        return
    
    chat_id = parsed["chat_id"]
    user_id = parsed["user_id"]
    text = parsed["text"]
    message_id = parsed["message_id"]
    
    # 查找对应的 Bot 配置
    bot = config.get_bot_or_default(bot_key)
    if not bot:
        logger.error(f"未找到 Telegram Bot 配置: {bot_key}")
        await client.send_message(
            chat_id=chat_id,
            text="⚠️ 机器人配置错误，请联系管理员",
            reply_to_message_id=message_id
        )
        return
    
    # 验证平台类型
    if bot.platform != "telegram":
        logger.error(f"Bot 平台类型错误: {bot.platform}, 期望: telegram")
        await client.send_message(
            chat_id=chat_id,
            text="⚠️ 机器人类型错误，请使用正确的 Bot",
            reply_to_message_id=message_id
        )
        return
    
    # 获取会话管理器
    session_mgr = get_session_manager()
    
    # 获取或创建会话
    # Telegram 使用 "telegram:{chat_id}" 作为 session_key
    session_key = f"telegram:{chat_id}"
    active_session = await session_mgr.get_active_session(str(user_id), session_key, bot.bot_key)
    current_session_id = active_session.session_id if active_session else None
    current_project_id = active_session.current_project_id if active_session else None
    
    # 检查是否为 Slash 命令
    if text.startswith("/"):
        slash_cmd = session_mgr.parse_slash_command(text)
        if slash_cmd:
            reply = await handle_telegram_command(
                session_mgr=session_mgr,
                user_id=str(user_id),
                bot=bot,
                cmd_type=slash_cmd[0],
                cmd_arg=slash_cmd[1],
                extra_msg=slash_cmd[2],
                session_key=session_key,
                current_session_id=current_session_id
            )
            await client.send_message(
                chat_id=chat_id,
                text=reply,
                reply_to_message_id=message_id,
                parse_mode=None  # 使用纯文本，避免格式错误
            )
            return
    
    try:
        # 转发消息到 Agent
        result = await forward_to_agent_with_user_project(
            bot_key=bot.bot_key,
            chat_id=session_key,
            content=text,
            timeout=config.timeout,
            session_id=current_session_id,
            current_project_id=current_project_id
        )
        
        if not result:
            await client.send_message(
                chat_id=chat_id,
                text="⚠️ 处理请求时发生错误，请稍后重试",
                reply_to_message_id=message_id
            )
            return
        
        # 记录会话
        if result.session_id:
            await session_mgr.record_session(
                user_id=str(user_id),
                chat_id=session_key,
                bot_key=bot.bot_key,
                session_id=result.session_id,
                last_message=text,
                current_project_id=current_project_id
            )
            logger.info(f"会话已记录: session={result.session_id[:8]}...")
        
        # 格式化响应
        formatted_text, reply_markup = client.format_agent_response(result.reply, add_buttons=False)
        
        # 发送响应
        await client.send_message(
            chat_id=chat_id,
            text=formatted_text,
            reply_to_message_id=message_id,
            parse_mode=None,  # Agent 响应可能包含特殊字符，使用纯文本
            reply_markup=reply_markup
        )
    
    except Exception as e:
        logger.error(f"处理 Telegram 消息失败: {e}", exc_info=True)
        await client.send_message(
            chat_id=chat_id,
            text=f"❌ 错误: {str(e)}",
            reply_to_message_id=message_id
        )


async def handle_telegram_command(
    session_mgr,
    user_id: str,
    bot,
    cmd_type: str,
    cmd_arg: Optional[str],
    extra_msg: Optional[str],
    session_key: str,
    current_session_id: Optional[str]
) -> str:
    """
    处理 Telegram Slash 命令
    
    Args:
        session_mgr: 会话管理器
        user_id: 用户 ID
        bot: Bot 配置对象
        cmd_type: 命令类型 (list/reset/change)
        cmd_arg: 命令参数
        extra_msg: 附加消息
        session_key: 会话键
        current_session_id: 当前会话 ID
    
    Returns:
        回复消息
    """
    try:
        if cmd_type == "list":
            # /sess 或 /s - 列出会话
            sessions = await session_mgr.list_sessions(user_id, session_key, bot_key=bot.bot_key)
            return session_mgr.format_session_list(sessions)
        
        elif cmd_type == "reset":
            # /reset 或 /r - 重置会话
            success = await session_mgr.reset_session(user_id, session_key, bot.bot_key)
            if success:
                return "✅ 会话已重置，下次发送消息将开始新对话"
            else:
                return "✅ 已准备好开始新对话，请发送消息"
        
        elif cmd_type == "change":
            # /change <short_id> 或 /c <short_id> - 切换会话
            if not cmd_arg:
                return "❌ 请提供会话 ID，例如: `/c abc123`"
            
            target_session = await session_mgr.change_session(
                user_id, session_key, cmd_arg, bot_key=bot.bot_key
            )
            if not target_session:
                return f"❌ 未找到会话 `{cmd_arg}`\n使用 `/s` 查看可用会话"
            
            return (
                f"✅ 已切换到会话 `{target_session.short_id}`\n"
                f"最后消息: {target_session.last_message or '(无)'}"
            )
        
        else:
            return f"❓ 未知命令: `/{cmd_type}`"
    
    except Exception as e:
        logger.error(f"处理 Telegram 命令失败: {e}", exc_info=True)
        return f"❌ 命令执行失败: {str(e)}"


@router.post("/callback/telegram/{bot_key}")
async def telegram_callback(
    bot_key: str,
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None)
) -> Response:
    """
    Telegram Bot Webhook 回调接口
    
    Args:
        bot_key: Bot 标识键
        request: FastAPI 请求对象
        x_telegram_bot_api_secret_token: Secret Token 头部 (可选)
    
    Returns:
        JSON 响应
    """
    try:
        # 读取请求数据
        update = await request.json()
        
        logger.info(f"收到 Telegram 回调: bot_key={bot_key[:10]}..., update_id={update.get('update_id')}")
        
        # 获取 Bot 配置
        bot = config.get_bot_or_default(bot_key)
        if not bot:
            return JSONResponse(
                status_code=404,
                content={"error": "Bot not found"}
            )
        
        # 解析平台配置
        platform_config = bot.get_platform_config()
        bot_token = platform_config.get("bot_token")
        secret_token = platform_config.get("secret_token")
        
        if not bot_token:
            return JSONResponse(
                status_code=500,
                content={"error": "Bot token not configured"}
            )
        
        # 创建客户端
        client = TelegramClient(bot_token=bot_token, secret_token=secret_token)
        
        # 验证 Secret Token (如果配置了)
        if not client.verify_webhook(x_telegram_bot_api_secret_token):
            logger.warning(f"Secret token 验证失败: bot_key={bot_key[:10]}...")
            return JSONResponse(
                status_code=403,
                content={"error": "Invalid secret token"}
            )
        
        # 处理消息 (异步，不阻塞响应)
        import asyncio
        asyncio.create_task(handle_telegram_message(bot_key, update, client))
        
        # 立即返回 200 OK (Telegram 要求快速响应)
        return JSONResponse(
            status_code=200,
            content={"ok": True}
        )
    
    except Exception as e:
        logger.error(f"处理 Telegram 回调失败: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )
