"""
消息发送模块

使用 fly-pigeon 库发送消息到企业微信
"""
import logging

from pigeon import Bot

from .config import config

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
    bot_key: str | None = None
) -> dict:
    """
    发送回复消息给用户
    
    Args:
        chat_id: 群/私聊 ID
        message: 消息内容
        msg_type: 消息类型 (text / markdown)
        bot_key: 机器人 Key（指定使用哪个机器人发送消息）
    
    Returns:
        发送结果 {"success": bool, "error": str | None}
    """
    try:
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
        
        return {"success": True}
        
    except Exception as e:
        logger.error(f"发送回复失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
