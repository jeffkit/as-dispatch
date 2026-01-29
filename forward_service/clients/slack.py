"""
Slack Web API 客户端

封装 Slack Web API 的常用操作:
- 发送消息
- 更新消息
- 下载文件
"""
import logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)


class SlackClient:
    """Slack Web API 客户端"""
    
    def __init__(self, bot_token: str):
        """
        初始化 Slack 客户端
        
        Args:
            bot_token: Slack Bot Token (xoxb-...)
        """
        self.bot_token = bot_token
        self.base_url = "https://slack.com/api"
    
    async def post_message(
        self,
        channel: str,
        text: str,
        thread_ts: Optional[str] = None,
        blocks: Optional[list] = None
    ) -> dict:
        """
        发送消息到 Slack 频道
        
        Args:
            channel: 频道 ID
            text: 消息文本
            thread_ts: 线程时间戳 (可选，用于回复线程)
            blocks: Block Kit 块 (可选)
        
        Returns:
            Slack API 响应
        """
        url = f"{self.base_url}/chat.postMessage"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.bot_token}"
        }
        
        payload = {
            "channel": channel,
            "text": text
        }
        
        if thread_ts:
            payload["thread_ts"] = thread_ts
        
        if blocks:
            payload["blocks"] = blocks
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
                
                if not result.get("ok"):
                    logger.error(f"Slack API 错误: {result.get('error')}")
                    raise Exception(f"Slack API 错误: {result.get('error')}")
                
                return result
        except Exception as e:
            logger.error(f"发送 Slack 消息失败: {e}")
            raise
    
    async def update_message(
        self,
        channel: str,
        ts: str,
        text: str,
        blocks: Optional[list] = None
    ) -> dict:
        """
        更新已发送的消息
        
        Args:
            channel: 频道 ID
            ts: 消息时间戳
            text: 新的消息文本
            blocks: 新的 Block Kit 块 (可选)
        
        Returns:
            Slack API 响应
        """
        url = f"{self.base_url}/chat.update"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.bot_token}"
        }
        
        payload = {
            "channel": channel,
            "ts": ts,
            "text": text
        }
        
        if blocks:
            payload["blocks"] = blocks
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
                
                if not result.get("ok"):
                    logger.error(f"Slack API 错误: {result.get('error')}")
                    raise Exception(f"Slack API 错误: {result.get('error')}")
                
                return result
        except Exception as e:
            logger.error(f"更新 Slack 消息失败: {e}")
            raise
    
    async def download_file(self, url: str) -> bytes:
        """
        从 Slack 下载文件
        
        Args:
            url: 文件下载 URL (url_private_download)
        
        Returns:
            文件二进制数据
        """
        headers = {
            "Authorization": f"Bearer {self.bot_token}"
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.content
        except Exception as e:
            logger.error(f"下载 Slack 文件失败: {e}")
            raise
