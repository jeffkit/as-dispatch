"""
Discord 通道适配器

负责：
- 从 kwargs["bot_key"] 提取 bot_key（Discord 走 WebSocket，非 Webhook）
- 将 discord.Message 序列化的 dict → InboundMessage
- 过滤 Bot 自身的消息
- 将 OutboundMessage → Discord DM 并发送
- 消息分拆（Discord 2000 字符限制）

架构说明：
Discord 使用 WebSocket gateway（discord.py），不是 HTTP Webhook。
因此 Discord 消息不经过 unified_callback.py 的 POST /callback/{platform} 路由，
而是从 routes/discord.py::handle_discord_message 直接调用 process_message()。
"""
import logging
from typing import Any, Optional

from .base import ChannelAdapter, InboundMessage, OutboundMessage, SendResult

logger = logging.getLogger(__name__)

# Discord 消息最大字符数
DISCORD_MAX_MESSAGE_LENGTH = 2000


class DiscordAdapter(ChannelAdapter):
    """
    Discord 通道适配器

    通过 discord.py WebSocket 接收消息，解析后进入统一处理管线。
    """

    @property
    def platform(self) -> str:
        return "discord"

    @property
    def max_message_bytes(self) -> int:
        return DISCORD_MAX_MESSAGE_LENGTH

    def should_ignore(self, raw_data: dict) -> bool:
        """忽略 Bot 自身发出的消息"""
        is_bot = raw_data.get("author_is_bot", False)
        if is_bot:
            logger.debug("[discord] 忽略 Bot 消息")
            return True
        return False

    def extract_bot_key(self, raw_data: dict, **kwargs: Any) -> Optional[str]:
        """
        从 kwargs 中提取 bot_key

        Discord 消息通过 WebSocket 接收，bot_key 在调用 parse_inbound 时
        由 handle_discord_message 通过 kwargs 传入。
        """
        bot_key = kwargs.get("bot_key", "")
        if bot_key:
            return bot_key
        # 兼容：从 raw_data 中获取（如果序列化时包含了此字段）
        bot_key = raw_data.get("_bot_key", "")
        return bot_key or None

    async def parse_inbound(self, raw_data: dict, **kwargs: Any) -> InboundMessage:
        """
        将 Discord Message 序列化 dict 解析为 InboundMessage

        raw_data 是从 discord.Message 对象序列化的字典，格式为：
        {
            "message_id": str,
            "content": str,
            "author_id": str,
            "author_name": str,
            "author_is_bot": bool,
            "channel_id": str,
            "channel_type": str,  # "dm" or "text"
            "attachments": [{"url": str, "content_type": str}],
            "_bot_key": str,
        }
        """
        bot_key = self.extract_bot_key(raw_data, **kwargs) or ""

        content = raw_data.get("content", "").strip()
        author_id = str(raw_data.get("author_id", ""))
        author_name = raw_data.get("author_name", "unknown")
        channel_id = str(raw_data.get("channel_id", ""))
        channel_type = raw_data.get("channel_type", "dm")

        # 提取图片附件 URL
        images: list[str] = []
        for attachment in raw_data.get("attachments", []):
            content_type = attachment.get("content_type", "")
            url = attachment.get("url", "")
            if content_type.startswith("image/") and url:
                images.append(url)

        if not content and not images:
            raise ValueError("Discord 消息内容为空（无文本也无图片附件）")

        # 消息类型判断
        if images and not content:
            msg_type = "image"
        elif images and content:
            msg_type = "mixed"
        else:
            msg_type = "text"

        normalized_chat_type = "direct" if channel_type == "dm" else "group"

        return InboundMessage(
            platform=self.platform,
            bot_key=bot_key,
            user_id=author_id,
            user_name=author_name,
            chat_id=channel_id,
            chat_type=normalized_chat_type,
            text=content,
            images=images,
            msg_type=msg_type,
            message_id=str(raw_data.get("message_id", "")),
            raw_data=raw_data,
        )

    async def send_outbound(self, message: OutboundMessage) -> SendResult:
        """
        将 OutboundMessage 转换为 Discord DM 并发送

        处理：
        - 消息分拆（超过 2000 字符时）
        - 调用 DiscordBotClient.send_dm()
        """
        try:
            user_id_str = message.chat_id
            # chat_id 在 Discord DM 场景下为 "dm:{user_id}"
            if user_id_str.startswith("dm:"):
                user_id_str = user_id_str[3:]

            try:
                user_id = int(user_id_str)
            except (ValueError, TypeError):
                return SendResult(
                    success=False,
                    error=f"无法将 chat_id={message.chat_id} 转换为 Discord user_id",
                )

            client = self._get_bot_client(message.bot_key)
            if not client:
                return SendResult(
                    success=False,
                    error=f"未找到 bot_key={message.bot_key} 对应的 DiscordBotClient",
                )

            text = message.text
            parts_sent = 0

            if len(text) <= DISCORD_MAX_MESSAGE_LENGTH:
                result = await client.send_dm(user_id=user_id, content=text)
                if result is None:
                    return SendResult(success=False, error="Discord send_dm 返回 None")
                parts_sent = 1
            else:
                # 分拆消息
                chunks = [
                    text[i : i + DISCORD_MAX_MESSAGE_LENGTH]
                    for i in range(0, len(text), DISCORD_MAX_MESSAGE_LENGTH)
                ]
                total = len(chunks)
                logger.info(f"[discord] 消息过长，分拆为 {total} 条发送: user_id={user_id}")
                for idx, chunk in enumerate(chunks):
                    prefix = f"({idx + 1}/{total}) " if total > 1 else ""
                    result = await client.send_dm(user_id=user_id, content=prefix + chunk)
                    if result is None:
                        return SendResult(
                            success=False,
                            parts_sent=parts_sent,
                            error=f"Discord send_dm 第 {idx + 1}/{total} 条返回 None",
                        )
                    parts_sent += 1

            logger.info(f"[discord] 消息已发送: user_id={user_id}, parts={parts_sent}")
            return SendResult(success=True, parts_sent=parts_sent)

        except Exception as e:
            logger.error(f"[discord] 发送消息失败: {e}", exc_info=True)
            return SendResult(success=False, error=str(e))

    # ============== 内部辅助方法 ==============

    def _get_bot_client(self, bot_key: str):
        """
        获取对应 bot_key 的 DiscordBotClient 实例

        从 routes.discord 的 discord_bots 字典中查找已启动的 Bot。

        Returns:
            DiscordBotClient 实例，不存在返回 None
        """
        if not bot_key:
            return None

        try:
            from ..routes.discord import discord_bots
            return discord_bots.get(bot_key)
        except Exception as e:
            logger.error(f"[discord] 获取 DiscordBotClient 失败: {e}", exc_info=True)
            return None
