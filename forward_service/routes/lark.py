"""
飞书 (Lark) Bot 路由

处理飞书 Bot 消息:
- Webhook URL 验证
- 事件接收和解密
- 消息解析和转发
- 会话管理命令
- 卡片消息支持
"""
import logging
from typing import Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from ..clients.lark import LarkClient
from ..config import config
from ..services.forwarder import forward_to_agent_with_user_project
from ..session_manager import get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["lark"])


async def handle_lark_message(
    bot_key: str,
    event: dict,
    client: LarkClient
) -> None:
    """
    处理飞书消息
    
    Args:
        bot_key: Bot 标识
        event: 飞书事件对象
        client: 飞书客户端
    """
    # 解析消息
    parsed = client.parse_event(event)
    
    # 只处理文本消息
    event_type = parsed.get("event_type")
    if event_type != "im.message.receive_v1":
        logger.debug(f"忽略非消息事件: {event_type}")
        return
    
    message_type = parsed.get("message_type")
    if message_type != "text":
        logger.debug(f"忽略非文本消息: {message_type}")
        return
    
    chat_id = parsed["chat_id"]
    user_id = parsed["user_id"] or parsed["open_id"]
    text = parsed["text"]
    message_id = parsed["message_id"]
    
    if not text or not user_id:
        logger.debug(f"消息缺少必要字段: {parsed}")
        return
    
    # 查找对应的 Bot 配置
    bot = config.get_bot_or_default(bot_key)
    if not bot:
        logger.error(f"未找到飞书 Bot 配置: {bot_key}")
        await client.send_text(
            receive_id=chat_id,
            text="⚠️ 机器人配置错误，请联系管理员"
        )
        return
    
    # 验证平台类型
    if bot.platform != "lark":
        logger.error(f"Bot 平台类型错误: {bot.platform}, 期望: lark")
        await client.send_text(
            receive_id=chat_id,
            text="⚠️ 机器人类型错误，请使用正确的 Bot"
        )
        return
    
    # 获取会话管理器
    session_mgr = get_session_manager()
    
    # 获取或创建会话
    # 飞书使用 "lark:{chat_id}" 作为 session_key
    session_key = f"lark:{chat_id}"
    active_session = await session_mgr.get_active_session(user_id, session_key, bot.bot_key)
    current_session_id = active_session.session_id if active_session else None
    current_project_id = active_session.current_project_id if active_session else None
    
    # 检查是否为 Slash 命令
    if text.startswith("/"):
        slash_cmd = session_mgr.parse_slash_command(text)
        if slash_cmd:
            reply = await handle_lark_command(
                session_mgr=session_mgr,
                user_id=user_id,
                bot=bot,
                cmd_type=slash_cmd[0],
                cmd_arg=slash_cmd[1],
                extra_msg=slash_cmd[2],
                session_key=session_key,
                current_session_id=current_session_id
            )
            await client.send_text(
                receive_id=chat_id,
                text=reply
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
            await client.send_text(
                receive_id=chat_id,
                text="⚠️ 处理请求时发生错误，请稍后重试"
            )
            return
        
        # 记录会话
        if result.session_id:
            await session_mgr.record_session(
                user_id=user_id,
                chat_id=session_key,
                bot_key=bot.bot_key,
                session_id=result.session_id,
                last_message=text,
                current_project_id=current_project_id
            )
            logger.info(f"会话已记录: session={result.session_id[:8]}...")
        
        # 格式化响应
        msg_type, content = client.format_agent_response(result.reply, use_card=False)
        
        # 发送响应
        await client.send_message(
            receive_id=chat_id,
            msg_type=msg_type,
            content=content
        )
    
    except Exception as e:
        logger.error(f"处理飞书消息失败: {e}", exc_info=True)
        await client.send_text(
            receive_id=chat_id,
            text=f"❌ 错误: {str(e)}"
        )


async def handle_lark_command(
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
    处理飞书 Slash 命令
    
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
        logger.error(f"处理飞书命令失败: {e}", exc_info=True)
        return f"❌ 命令执行失败: {str(e)}"


@router.post("/callback/lark/{bot_key}")
async def lark_callback(bot_key: str, request: Request) -> Response:
    """
    飞书 Bot Webhook 回调接口
    
    Args:
        bot_key: Bot 标识键
        request: FastAPI 请求对象
    
    Returns:
        JSON 响应
    """
    try:
        # 读取请求数据
        data = await request.json()
        
        logger.info(f"收到飞书回调: bot_key={bot_key[:10]}..., type={data.get('type')}")
        
        # 获取 Bot 配置
        bot = config.get_bot_or_default(bot_key)
        if not bot:
            return JSONResponse(
                status_code=404,
                content={"error": "Bot not found"}
            )
        
        # 解析平台配置
        platform_config = bot.get_platform_config()
        app_id = platform_config.get("app_id")
        app_secret = platform_config.get("app_secret")
        encrypt_key = platform_config.get("encrypt_key")
        verification_token = platform_config.get("verification_token")
        
        if not app_id or not app_secret:
            return JSONResponse(
                status_code=500,
                content={"error": "App credentials not configured"}
            )
        
        # 创建客户端
        client = LarkClient(
            app_id=app_id,
            app_secret=app_secret,
            encrypt_key=encrypt_key,
            verification_token=verification_token
        )
        
        # 处理不同类型的请求
        request_type = data.get("type")
        
        # URL 验证
        if request_type == "url_verification":
            challenge = data.get("challenge")
            token = data.get("token")
            
            result = client.verify_url(challenge, token)
            if result:
                return JSONResponse(content=result)
            else:
                return JSONResponse(
                    status_code=403,
                    content={"error": "Invalid verification token"}
                )
        
        # 事件回调
        elif request_type == "event_callback":
            # 解密事件 (如果配置了加密)
            if data.get("encrypt"):
                encrypted = data.get("encrypt")
                event = client.decrypt_event(encrypted)
            else:
                event = data
            
            # 处理消息 (异步，不阻塞响应)
            import asyncio
            asyncio.create_task(handle_lark_message(bot_key, event, client))
            
            # 立即返回 200 OK (飞书要求快速响应)
            return JSONResponse(
                status_code=200,
                content={"ok": True}
            )
        
        else:
            logger.warning(f"未知的请求类型: {request_type}")
            return JSONResponse(
                status_code=400,
                content={"error": f"Unknown request type: {request_type}"}
            )
    
    except Exception as e:
        logger.error(f"处理飞书回调失败: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )
