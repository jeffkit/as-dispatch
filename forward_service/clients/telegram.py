"""
Telegram Bot API 客户端

封装 Telegram Bot API 的常用操作:
- 发送消息 (文本、Markdown)
- Webhook 处理
- 消息解析
- 内联按钮支持
"""
import logging
import json
import hashlib
import hmac
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)


class TelegramClient:
    """Telegram Bot API 客户端"""
    
    def __init__(self, bot_token: str, secret_token: Optional[str] = None):
        """
        初始化客户端
        
        Args:
            bot_token: Bot Token (从 @BotFather 获取)
            secret_token: Secret Token (用于 Webhook 验证，可选)
        """
        self.bot_token = bot_token
        self.secret_token = secret_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
    
    # ============== 消息发送 ==============
    
    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: Optional[str] = "Markdown",
        reply_to_message_id: Optional[int] = None,
        reply_markup: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        发送文本消息
        
        Args:
            chat_id: 聊天 ID
            text: 消息文本
            parse_mode: 解析模式 (Markdown, HTML, 或 None)
            reply_to_message_id: 回复的消息 ID
            reply_markup: 键盘标记 (InlineKeyboardMarkup 等)
        
        Returns:
            发送结果
        """
        import httpx
        
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
        }
        
        if parse_mode:
            payload["parse_mode"] = parse_mode
        
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        
        if reply_markup:
            payload["reply_markup"] = reply_markup
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"发送 Telegram 消息失败: {e}", exc_info=True)
            raise
    
    async def send_photo(
        self,
        chat_id: int | str,
        photo: str,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = "Markdown"
    ) -> Dict[str, Any]:
        """
        发送图片
        
        Args:
            chat_id: 聊天 ID
            photo: 图片 URL 或 file_id
            caption: 图片说明
            parse_mode: 解析模式
        
        Returns:
            发送结果
        """
        import httpx
        
        url = f"{self.base_url}/sendPhoto"
        payload = {
            "chat_id": chat_id,
            "photo": photo,
        }
        
        if caption:
            payload["caption"] = caption
            if parse_mode:
                payload["parse_mode"] = parse_mode
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
    
    # ============== Webhook 处理 ==============
    
    def verify_webhook(self, secret_token_header: Optional[str]) -> bool:
        """
        验证 Webhook 请求
        
        Args:
            secret_token_header: X-Telegram-Bot-Api-Secret-Token 头部值
        
        Returns:
            验证结果
        """
        if not self.secret_token:
            # 如果没有配置 secret_token，跳过验证
            return True
        
        return secret_token_header == self.secret_token
    
    def parse_update(self, update: Dict[str, Any]) -> Dict[str, Any]:
        """
        解析 Telegram Update 对象
        
        Args:
            update: Update 对象
        
        Returns:
            解析后的统一格式:
            {
                "update_id": int,
                "message_id": int,
                "chat_id": int,
                "user_id": int,
                "username": str,
                "text": str,
                "reply_to_message_id": int | None,
                "timestamp": int,
                "raw": dict
            }
        """
        # Telegram Update 可能包含 message, edited_message, channel_post 等
        message = update.get("message") or update.get("edited_message") or update.get("channel_post")
        
        if not message:
            logger.warning(f"Update 中没有消息: {update}")
            return {
                "update_id": update.get("update_id"),
                "raw": update
            }
        
        chat = message.get("chat", {})
        from_user = message.get("from", {})
        
        return {
            "update_id": update.get("update_id"),
            "message_id": message.get("message_id"),
            "chat_id": chat.get("id"),
            "chat_type": chat.get("type"),  # private, group, supergroup, channel
            "user_id": from_user.get("id"),
            "username": from_user.get("username"),
            "first_name": from_user.get("first_name"),
            "last_name": from_user.get("last_name"),
            "text": message.get("text"),
            "reply_to_message_id": message.get("reply_to_message", {}).get("message_id"),
            "timestamp": message.get("date"),
            "raw": update
        }
    
    # ============== 文件下载 ==============

    async def get_file_url(self, file_id: str) -> Optional[str]:
        """
        获取文件的完整下载 URL

        调用 Telegram getFile API 获取文件路径，然后组装完整 URL。

        Args:
            file_id: 文件 ID

        Returns:
            完整文件 URL，失败时返回 None
        """
        import httpx

        url = f"{self.base_url}/getFile"
        payload = {"file_id": file_id}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()

                if not data.get("ok"):
                    logger.warning(f"getFile 返回错误: {data.get('description')}")
                    return None

                file_path = data.get("result", {}).get("file_path")
                if not file_path:
                    logger.warning(f"getFile 结果中无 file_path: file_id={file_id}")
                    return None

                return f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"

        except Exception as e:
            logger.error(f"获取 Telegram 文件 URL 失败: file_id={file_id}, error={e}")
            return None

    # ============== 内联按钮 ==============
    
    def build_inline_keyboard(self, buttons: List[List[Dict[str, str]]]) -> Dict:
        """
        构建内联键盘
        
        Args:
            buttons: 按钮数组，格式:
                [
                    [{"text": "按钮1", "callback_data": "data1"}],
                    [{"text": "按钮2", "url": "https://..."}]
                ]
        
        Returns:
            InlineKeyboardMarkup 对象
        """
        return {
            "inline_keyboard": buttons
        }
    
    # ============== 辅助方法 ==============
    
    def escape_markdown(self, text: str) -> str:
        """
        转义 Markdown 特殊字符
        
        Args:
            text: 原始文本
        
        Returns:
            转义后的文本
        """
        # Telegram MarkdownV2 需要转义的字符
        escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in escape_chars:
            text = text.replace(char, f'\\{char}')
        return text
    
    def format_agent_response(self, response: str, add_buttons: bool = False) -> tuple[str, Optional[Dict]]:
        """
        格式化 Agent 响应为 Telegram 消息
        
        Args:
            response: Agent 响应文本
            add_buttons: 是否添加操作按钮
        
        Returns:
            (formatted_text, reply_markup)
        """
        # 简单格式化：保持原样，但可以根据需要添加特殊格式
        text = response
        
        # 如果响应太长，截断并添加提示
        max_length = 4096  # Telegram 消息最大长度
        if len(text) > max_length:
            text = text[:max_length - 50] + "\n\n... (消息过长，已截断)"
        
        # 可选：添加操作按钮
        reply_markup = None
        if add_buttons:
            reply_markup = self.build_inline_keyboard([
                [
                    {"text": "🔄 重新生成", "callback_data": "regenerate"},
                    {"text": "✅ 满意", "callback_data": "satisfied"}
                ]
            ])
        
        return text, reply_markup
