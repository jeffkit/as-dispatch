"""
企业微信智能机器人路由

处理企微智能机器人消息:
- XML 消息接收和解析
- 会话管理命令 (/sess, /reset, /change)
- 流式消息支持
- 模板卡片支持（未来）
"""
import logging
from typing import Optional
import asyncio

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse

from ..clients.wecom_intelligent import WeComIntelligentClient
from ..config import config
from ..services.forwarder import forward_to_agent_with_user_project
from ..session_manager import get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["intelligent"])


async def handle_intelligent_message(
    bot_key: str,
    message_data: dict,
    client: WeComIntelligentClient
) -> str:
    """
    处理智能机器人消息
    
    Args:
        bot_key: Bot 标识
        message_data: 解析后的消息数据
        client: 智能机器人客户端
    
    Returns:
        XML 响应
    """
    from_user = message_data.get("FromUserName", "")
    to_user = message_data.get("ToUserName", "")
    content = message_data.get("Content", "")
    msg_type = message_data.get("MsgType", "")
    
    # 只处理文本消息
    if msg_type != "text":
        logger.debug(f"忽略非文本消息: {msg_type}")
        return ""
    
    # 查找对应的 Bot 配置
    bot = config.get_bot_or_default(bot_key)
    if not bot:
        logger.error(f"未找到智能机器人配置: {bot_key}")
        return client.build_text_xml(
            to_user=from_user,
            from_user=to_user,
            content="⚠️ 机器人配置错误，请联系管理员"
        )
    
    # 验证平台类型
    if bot.platform != "wecom-intelligent":
        logger.error(f"Bot 平台类型错误: {bot.platform}, 期望: wecom-intelligent")
        return client.build_text_xml(
            to_user=from_user,
            from_user=to_user,
            content="⚠️ 机器人类型错误，请使用正确的回调 URL"
        )
    
    # 获取会话管理器
    session_mgr = get_session_manager()
    
    # 获取或创建会话
    # 智能机器人使用 "intelligent:{user_id}" 作为 session_key
    session_key = f"intelligent:{from_user}"
    active_session = await session_mgr.get_active_session(from_user, session_key, bot.bot_key)
    current_session_id = active_session.session_id if active_session else None
    current_project_id = active_session.current_project_id if active_session else None
    
    # 检查是否为 Slash 命令
    if content:
        slash_cmd = session_mgr.parse_slash_command(content)
        if slash_cmd:
            reply = await handle_intelligent_command(
                session_mgr=session_mgr,
                from_user=from_user,
                bot=bot,
                cmd_type=slash_cmd[0],
                cmd_arg=slash_cmd[1],
                extra_msg=slash_cmd[2],
                session_key=session_key,
                current_session_id=current_session_id
            )
            return client.build_text_xml(
                to_user=from_user,
                from_user=to_user,
                content=reply
            )
    
    try:
        # 转发消息到 Agent
        result = await forward_to_agent_with_user_project(
            bot_key=bot.bot_key,
            chat_id=session_key,
            content=content,
            timeout=config.timeout,
            session_id=current_session_id,
            current_project_id=current_project_id
        )
        
        if not result:
            return client.build_text_xml(
                to_user=from_user,
                from_user=to_user,
                content="⚠️ 处理请求时发生错误，请稍后重试"
            )
        
        # 记录会话
        if result.session_id:
            await session_mgr.record_session(
                user_id=from_user,
                chat_id=session_key,
                bot_key=bot.bot_key,
                session_id=result.session_id,
                last_message=content,
                current_project_id=current_project_id
            )
            logger.info(f"会话已记录: session={result.session_id[:8]}...")
        
        # 生成流式消息 ID
        stream_id = client.generate_stream_id(from_user)
        feedback_id = client.generate_feedback_id(stream_id)
        
        # 返回流式消息 XML
        # TODO: 支持真正的流式响应
        return client.build_stream_xml(
            to_user=from_user,
            from_user=to_user,
            stream_id=stream_id,
            content=result.reply,
            finish=True,
            feedback_id=feedback_id
        )
    
    except Exception as e:
        logger.error(f"处理智能机器人消息失败: {e}", exc_info=True)
        return client.build_text_xml(
            to_user=from_user,
            from_user=to_user,
            content=f"❌ 错误: {str(e)}"
        )


async def handle_intelligent_command(
    session_mgr,
    from_user: str,
    bot,
    cmd_type: str,
    cmd_arg: Optional[str],
    extra_msg: Optional[str],
    session_key: str,
    current_session_id: Optional[str]
) -> str:
    """
    处理智能机器人 Slash 命令
    
    Args:
        session_mgr: 会话管理器
        from_user: 用户 ID
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
            sessions = await session_mgr.list_sessions(from_user, session_key, bot_key=bot.bot_key)
            return session_mgr.format_session_list(sessions)
        
        elif cmd_type == "reset":
            # /reset 或 /r - 重置会话
            success = await session_mgr.reset_session(from_user, session_key, bot.bot_key)
            if success:
                return "✅ 会话已重置，下次发送消息将开始新对话"
            else:
                return "✅ 已准备好开始新对话，请发送消息"
        
        elif cmd_type == "change":
            # /change <short_id> 或 /c <short_id> - 切换会话
            if not cmd_arg:
                return "❌ 请提供会话 ID，例如: `/c abc123`"
            
            target_session = await session_mgr.change_session(
                from_user, session_key, cmd_arg, bot_key=bot.bot_key
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
        logger.error(f"处理智能机器人命令失败: {e}", exc_info=True)
        return f"❌ 命令执行失败: {str(e)}"


@router.post("/callback/intelligent/{bot_key}")
async def intelligent_callback(bot_key: str, request: Request) -> Response:
    """
    企业微信智能机器人回调接口
    
    Args:
        bot_key: Bot 标识键
        request: FastAPI 请求对象
    
    Returns:
        XML 响应
    """
    try:
        # 读取 XML 数据
        xml_data = await request.body()
        
        logger.info(f"收到智能机器人回调: bot_key={bot_key[:10]}..., size={len(xml_data)} bytes")
        
        # 创建客户端
        client = WeComIntelligentClient(bot_key=bot_key)
        
        # 解析 XML
        message_data = client.parse_xml(xml_data)
        
        logger.info(f"解析消息: from={message_data.get('FromUserName')}, type={message_data.get('MsgType')}")
        
        # 处理消息
        response_xml = await handle_intelligent_message(
            bot_key=bot_key,
            message_data=message_data,
            client=client
        )
        
        # 返回 XML 响应
        return PlainTextResponse(
            content=response_xml,
            media_type="application/xml"
        )
    
    except Exception as e:
        logger.error(f"处理智能机器人回调失败: {e}", exc_info=True)
        
        # 返回错误 XML
        error_xml = """<xml>
    <MsgType><![CDATA[text]]></MsgType>
    <Content><![CDATA[❌ 服务器错误，请稍后重试]]></Content>
</xml>"""
        
        return PlainTextResponse(
            content=error_xml,
            media_type="application/xml",
            status_code=200  # 企微要求返回 200
        )
