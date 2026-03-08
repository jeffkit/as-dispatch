"""
Telegram 通道适配器

负责：
- 从 X-Telegram-Bot-Api-Secret-Token 请求头提取 bot_key
- 解析 Telegram Update 回调数据 → InboundMessage
- 过滤 Bot 发出的消息
- 将 OutboundMessage → Telegram 消息格式并发送
- 支持图片消息（通过 getFile API 获取下载 URL）
"""
import logging
from typing import Any, Optional

from .base import ChannelAdapter, InboundMessage, OutboundMessage, SendResult

logger = logging.getLogger(__name__)

# Telegram 消息最大字符数
TELEGRAM_MAX_MESSAGE_LENGTH = 4096


class TelegramAdapter(ChannelAdapter):
    """
    Telegram 通道适配器

    通过 Webhook 接收 Telegram Update，解析后进入统一处理管线。
    Bot 标识通过 X-Telegram-Bot-Api-Secret-Token 请求头传入（配置 Webhook 时设置）。
    """

    @property
    def platform(self) -> str:
        return "telegram"

    @property
    def max_message_bytes(self) -> int:
        return TELEGRAM_MAX_MESSAGE_LENGTH

    def should_ignore(self, raw_data: dict) -> bool:
        """忽略来自 Bot 自身的消息"""
        message = raw_data.get("message", {}) or raw_data.get("edited_message", {})
        if not message:
            return True
        sender = message.get("from", {})
        if sender.get("is_bot", False):
            logger.debug(f"[telegram] 忽略 Bot 消息: from={sender.get('username')}")
            return True
        return False

    def extract_bot_key(self, raw_data: dict, **kwargs: Any) -> Optional[str]:
        """
        从 X-Telegram-Bot-Api-Secret-Token 请求头提取 bot_key

        Webhook 配置时将 bot_key 作为 Secret Token 传入，
        Telegram 会在每个 Webhook 请求中附上该 Token。
        """
        headers = raw_data.get("_request_headers", {})
        secret_token = headers.get("x-telegram-bot-api-secret-token", "")
        if secret_token:
            return secret_token
        logger.warning("[telegram] 未找到 X-Telegram-Bot-Api-Secret-Token 请求头")
        return None

    async def parse_inbound(self, raw_data: dict, **kwargs: Any) -> InboundMessage:
        """
        将 Telegram Update 回调数据解析为 InboundMessage

        处理：
        1. 从 Update 中提取 message 对象
        2. 提取发送者、会话信息
        3. 提取文本内容
        4. 处理图片附件（取最大尺寸，通过 getFile API 获取 URL）
        """
        message = (
            raw_data.get("message")
            or raw_data.get("edited_message")
            or raw_data.get("channel_post")
        )
        if not message:
            raise ValueError("Telegram Update 中无 message 字段")

        sender = message.get("from", {})
        chat = message.get("chat", {})
        bot_key = self.extract_bot_key(raw_data) or ""

        # 提取文本内容（优先 text，其次 caption）
        text = (message.get("text") or message.get("caption") or "").strip()

        # 提取图片（Telegram 发送 photo 数组，取最大尺寸）
        images: list[str] = []
        photos = message.get("photo", [])
        if photos:
            largest_photo = max(photos, key=lambda p: p.get("file_size", 0))
            file_id = largest_photo.get("file_id", "")
            if file_id:
                client = self._get_client(bot_key)
                if client:
                    file_url = await client.get_file_url(file_id)
                    if file_url:
                        images.append(file_url)
                        logger.debug(f"[telegram] 获取图片 URL: {file_url[:60]}...")

        # 处理文档类型的图片（如 JPEG 文件通过 document 发送）
        document = message.get("document", {})
        if document and document.get("mime_type", "").startswith("image/"):
            file_id = document.get("file_id", "")
            if file_id:
                client = self._get_client(bot_key)
                if client:
                    file_url = await client.get_file_url(file_id)
                    if file_url:
                        images.append(file_url)

        # 消息类型判断
        if images and not text:
            msg_type = "image"
        elif images and text:
            msg_type = "mixed"
        else:
            msg_type = "text"

        # 用户名拼接
        first_name = sender.get("first_name", "")
        last_name = sender.get("last_name", "")
        user_name = f"{first_name} {last_name}".strip() or sender.get("username", "unknown")

        # chat_type 映射
        chat_type = chat.get("type", "private")
        normalized_chat_type = "direct" if chat_type == "private" else "group"

        return InboundMessage(
            platform=self.platform,
            bot_key=bot_key,
            user_id=str(sender.get("id", "")),
            user_name=user_name,
            chat_id=str(chat.get("id", "")),
            chat_type=normalized_chat_type,
            text=text,
            images=images,
            msg_type=msg_type,
            message_id=str(message.get("message_id", "")),
            raw_data=raw_data,
        )

    async def send_outbound(self, message: OutboundMessage) -> SendResult:
        """
        将 OutboundMessage 转换为 Telegram 消息并发送

        处理：
        - 消息分拆（超过 4096 字符时）
        - 调用 TelegramClient.send_message()
        """
        try:
            client = self._get_client(message.bot_key)
            if not client:
                return SendResult(
                    success=False,
                    error=f"未找到 bot_key={message.bot_key} 对应的 TelegramClient",
                )

            text = message.text
            chat_id = message.chat_id
            parts_sent = 0

            if len(text) <= TELEGRAM_MAX_MESSAGE_LENGTH:
                await client.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=None,
                )
                parts_sent = 1
            else:
                # 分拆消息
                chunks = [
                    text[i : i + TELEGRAM_MAX_MESSAGE_LENGTH]
                    for i in range(0, len(text), TELEGRAM_MAX_MESSAGE_LENGTH)
                ]
                total = len(chunks)
                logger.info(f"[telegram] 消息过长，分拆为 {total} 条发送: chat_id={chat_id}")
                for idx, chunk in enumerate(chunks):
                    prefix = f"({idx + 1}/{total}) " if total > 1 else ""
                    await client.send_message(
                        chat_id=chat_id,
                        text=prefix + chunk,
                        parse_mode=None,
                    )
                    parts_sent += 1

            logger.info(f"[telegram] 消息已发送: chat_id={chat_id}, parts={parts_sent}")
            return SendResult(success=True, parts_sent=parts_sent)

        except Exception as e:
            logger.error(f"[telegram] 发送消息失败: {e}", exc_info=True)
            return SendResult(success=False, error=str(e))

    # ============== 内部辅助方法 ==============

    def _get_client(self, bot_key: str):
        """
        根据 bot_key 获取 TelegramClient 实例

        从 Bot 配置中读取 bot_token 和 secret_token，
        创建并返回 TelegramClient 实例。

        Returns:
            TelegramClient 实例，如果配置不存在返回 None
        """
        if not bot_key:
            return None

        try:
            from ..config import config
            from ..clients.telegram import TelegramClient

            bot_config = config.get_bot(bot_key)
            if not bot_config or not bot_config._bot:
                logger.warning(f"[telegram] 未找到 bot_key={bot_key[:10]}... 的配置")
                return None

            platform_cfg = bot_config._bot.get_platform_config()
            bot_token = platform_cfg.get("bot_token", "")
            secret_token = platform_cfg.get("secret_token", "")

            if not bot_token:
                logger.warning(f"[telegram] bot_key={bot_key[:10]}... 未配置 bot_token")
                return None

            return TelegramClient(bot_token=bot_token, secret_token=secret_token or None)

        except Exception as e:
            logger.error(f"[telegram] 创建 TelegramClient 失败: {e}", exc_info=True)
            return None
