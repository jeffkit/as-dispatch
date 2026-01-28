"""
消息发送模块

使用 fly-pigeon 库发送消息到企业微信

功能：
- 消息格式化：添加会话标识头
- 消息分拆：当消息超过 2K 时自动分拆
- 每条分拆的消息都保留会话标识，方便用户回复

注意: pigeon 模块为可选依赖，只在企微平台时需要
"""
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pigeon import Bot

from .config import config
from .message_splitter import (
    split_and_format_message,
    needs_split,
)

logger = logging.getLogger(__name__)


def send_to_wecom(
    message: str,
    chat_id: str,
    msg_type: str = "text",
    bot_key: str | None = None,
) -> dict:
    """
    发送消息到企业微信
    
    Args:
        message: 消息内容
        chat_id: 群/私聊 ID
        msg_type: 消息类型 (text / markdown)
        bot_key: 机器人 Key（不传则使用配置）
    
    Returns:
        发送结果
    """
    bot_key = bot_key or config.bot_key
    
    if not bot_key:
        raise ValueError("未配置 bot_key")
    
    # 懒加载 pigeon 模块（只在企微平台时需要）
    try:
        from pigeon import Bot
    except ImportError:
        raise ImportError(
            "fly-pigeon 包未安装。企微功能需要安装: pip install fly-pigeon\n"
            "或安装完整依赖: pip install 'as-dispatch[wecom]'"
        )
    
    bot = Bot(bot_key=bot_key)
    
    logger.info(f"发送消息到企微: chat_id={chat_id}, msg_type={msg_type}, message={message[:50]}...")
    
    try:
        if msg_type == "markdown":
            result = bot.markdown(
                chat_id=chat_id,
                msg_content=message,
            )
        else:
            result = bot.text(
                chat_id=chat_id,
                msg_content=message,
            )
        
        # 记录响应内容
        response_data = None
        if hasattr(result, 'json'):
            try:
                response_data = result.json()
            except Exception:
                pass
        elif isinstance(result, dict):
            response_data = result
        
        logger.info(f"fly-pigeon 响应: status={result}, data={response_data}")
        
        # 检查是否真的发送成功
        if response_data:
            errcode = response_data.get("errcode", 0)
            if errcode != 0:
                logger.error(f"企微发送失败: errcode={errcode}, errmsg={response_data.get('errmsg')}")
                return response_data
        
        return response_data or {"errcode": 0, "errmsg": "ok"}
        
    except Exception as e:
        logger.error(f"fly-pigeon 发送失败: {e}", exc_info=True)
        raise


async def send_reply(
    chat_id: str,
    message: str,
    msg_type: str = "text",
    bot_key: str | None = None,
    short_id: str | None = None,
    project_name: str | None = None
) -> dict:
    """
    发送回复消息给用户
    
    支持消息自动分拆：当消息超过 2K 时会自动分拆成多条消息。
    
    Args:
        chat_id: 群/私聊 ID
        message: 消息内容
        msg_type: 消息类型 (text / markdown)
        bot_key: 机器人 Key（指定使用哪个机器人发送消息）
        short_id: 会话短 ID（用于消息头部标识）
        project_name: 项目名称（显示在消息头部）
    
    Returns:
        发送结果 {"success": bool, "error": str | None, "parts_sent": int | None}
    """
    try:
        # 如果提供了 short_id，检查是否需要分拆
        if short_id and needs_split(message, short_id, project_name):
            logger.info(f"消息过长，分拆发送: chat_id={chat_id}, short_id={short_id}")
            return await _send_message_split(
                message=message,
                chat_id=chat_id,
                msg_type=msg_type,
                bot_key=bot_key,
                short_id=short_id,
                project_name=project_name
            )
        
        # 不需要分拆，使用原有逻辑
        result = send_to_wecom(
            message=message,
            chat_id=chat_id,
            msg_type=msg_type,
            bot_key=bot_key
        )
        
        if isinstance(result, dict) and result.get("errcode", 0) != 0:
            return {
                "success": False,
                "error": f"发送失败: {result.get('errmsg', '未知错误')}"
            }
        
        return {"success": True, "parts_sent": 1}
        
    except Exception as e:
        logger.error(f"发送回复失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def _send_message_split(
    message: str,
    chat_id: str,
    msg_type: str,
    bot_key: str | None,
    short_id: str,
    project_name: str | None
) -> dict:
    """
    分拆消息并发送
    
    Args:
        message: 消息内容
        chat_id: 目标会话 ID
        msg_type: 消息类型
        bot_key: 机器人 Key
        short_id: 会话短 ID
        project_name: 项目名称
    
    Returns:
        {"success": bool, "parts_sent": int, "error": str | None}
    """
    try:
        # 分拆消息
        split_messages = split_and_format_message(
            message=message,
            short_id=short_id,
            project_name=project_name
        )
        
        logger.info(f"消息分拆为 {len(split_messages)} 条: chat_id={chat_id}")
        
        # 逐条发送
        for split_msg in split_messages:
            result = send_to_wecom(
                message=split_msg.content,
                chat_id=chat_id,
                msg_type=msg_type,
                bot_key=bot_key
            )
            
            # 检查发送结果
            if isinstance(result, dict) and result.get("errcode", 0) != 0:
                logger.error(f"分拆消息发送失败: part={split_msg.part_number}/{split_msg.total_parts}, error={result.get('errmsg')}")
                return {
                    "success": False,
                    "error": f"第 {split_msg.part_number}/{split_msg.total_parts} 条消息发送失败: {result.get('errmsg', '未知错误')}",
                    "parts_sent": split_msg.part_number - 1
                }
        
        return {"success": True, "parts_sent": len(split_messages)}
        
    except Exception as e:
        logger.error(f"分拆消息发送失败: {e}", exc_info=True)
        return {"success": False, "error": str(e), "parts_sent": 0}
