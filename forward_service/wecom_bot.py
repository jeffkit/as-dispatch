"""
企业微信机器人客户端

直接使用 httpx 调用企业微信 Webhook API，替代 fly-pigeon 库
"""
import httpx
import logging

logger = logging.getLogger(__name__)

WECOM_WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"


class Bot:
    """企业微信机器人"""
    
    def __init__(self, bot_key: str):
        """
        初始化机器人
        
        Args:
            bot_key: 机器人 Webhook Key
        """
        self.bot_key = bot_key
        self.webhook_url = f"{WECOM_WEBHOOK_URL}?key={bot_key}"
    
    def _send(self, payload: dict) -> dict:
        """
        发送消息到企业微信
        
        Args:
            payload: 消息体
            
        Returns:
            API 响应 {"errcode": 0, "errmsg": "ok"} 或错误信息
        """
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(self.webhook_url, json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"WeCom API HTTP error: {e}")
            return {"errcode": -1, "errmsg": str(e)}
        except Exception as e:
            logger.error(f"WeCom API error: {e}")
            return {"errcode": -1, "errmsg": str(e)}
    
    def text(self, msg_content: str, chat_id: str = None, mentioned_list: list = None) -> dict:
        """
        发送文本消息
        
        Args:
            msg_content: 消息内容
            chat_id: 会话 ID（企业微信 Webhook 不使用此参数，保留用于兼容）
            mentioned_list: @成员列表
            
        Returns:
            API 响应
        """
        payload = {
            "msgtype": "text",
            "text": {
                "content": msg_content,
            }
        }
        
        if mentioned_list:
            payload["text"]["mentioned_list"] = mentioned_list
        
        return self._send(payload)
    
    def markdown(self, msg_content: str, chat_id: str = None) -> dict:
        """
        发送 Markdown 消息
        
        Args:
            msg_content: Markdown 内容
            chat_id: 会话 ID（企业微信 Webhook 不使用此参数，保留用于兼容）
            
        Returns:
            API 响应
        """
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": msg_content,
            }
        }
        
        return self._send(payload)
