"""
QQ Bot 通道适配器

负责：
- 将 QQ Bot WebSocket 事件解析为 InboundMessage
- 将 OutboundMessage 通过 QQ Bot API 发送
- 消息分拆（QQ 单条消息约 2000 字符限制）

架构说明：
QQ Bot 使用 WebSocket Gateway 接收消息（类似 Discord），不是 HTTP Webhook。
因此 QQ Bot 消息不经过 unified_callback.py 的 POST /callback/{platform} 路由，
而是从 routes/qqbot.py::handle_qqbot_message 调用 pipeline.process_message()。
"""
import logging
from typing import Any, Optional

from .base import ChannelAdapter, InboundMessage, OutboundMessage, SendResult

logger = logging.getLogger(__name__)

QQBOT_MAX_MESSAGE_LENGTH = 2000


class QQBotAdapter(ChannelAdapter):
    """
    QQ Bot 通道适配器

    通过 QQ 开放平台 WebSocket Gateway 接收消息，解析后进入统一处理管线。
    """

    @property
    def platform(self) -> str:
        return "qqbot"

    @property
    def max_message_bytes(self) -> int:
        return QQBOT_MAX_MESSAGE_LENGTH

    def should_ignore(self, raw_data: dict) -> bool:
        """QQ Bot 消息默认不忽略（Bot 自身消息已在 client 层过滤）"""
        return False

    def extract_bot_key(self, raw_data: dict, **kwargs: Any) -> Optional[str]:
        """
        从 kwargs 中提取 bot_key

        QQ Bot 消息通过 WebSocket 接收，bot_key 在调用 parse_inbound 时
        由 handle_qqbot_message 通过 kwargs 传入。
        """
        bot_key = kwargs.get("bot_key", "")
        if bot_key:
            return bot_key
        return raw_data.get("_bot_key") or None

    async def parse_inbound(self, raw_data: dict, **kwargs: Any) -> InboundMessage:
        """
        将 QQ Bot 消息事件解析为 InboundMessage

        raw_data 格式（由 QQBotClient._parse_message_event 生成）：
        {
            "type": "c2c" | "group" | "channel" | "dm",
            "sender_id": str,
            "sender_name": str,
            "content": str,
            "message_id": str,
            "timestamp": str,
            "group_openid": str | None,
            "channel_id": str | None,
            "guild_id": str | None,
            "attachments": [{"content_type": str, "url": str}],
        }
        """
        bot_key = self.extract_bot_key(raw_data, **kwargs) or ""

        msg_type_raw = raw_data.get("type", "c2c")
        content = raw_data.get("content", "").strip()
        sender_id = raw_data.get("sender_id", "")
        sender_name = raw_data.get("sender_name", sender_id[:8] if sender_id else "unknown")

        # chat_id 映射
        if msg_type_raw == "c2c":
            chat_id = f"c2c:{sender_id}"
            chat_type = "direct"
        elif msg_type_raw == "group":
            chat_id = f"group:{raw_data.get('group_openid', '')}"
            chat_type = "group"
        elif msg_type_raw == "channel":
            chat_id = f"channel:{raw_data.get('channel_id', '')}"
            chat_type = "group"
        elif msg_type_raw == "dm":
            chat_id = f"dm:{sender_id}"
            chat_type = "direct"
        else:
            chat_id = sender_id
            chat_type = "direct"

        # 提取图片附件
        images: list[str] = []
        for att in raw_data.get("attachments", []):
            ct = att.get("content_type", "")
            url = att.get("url", "")
            if ct.startswith("image/") and url:
                images.append(url)

        if not content and not images:
            raise ValueError("QQ Bot 消息内容为空（无文本也无图片附件）")

        if images and not content:
            msg_type = "image"
        elif images and content:
            msg_type = "mixed"
        else:
            msg_type = "text"

        return InboundMessage(
            platform=self.platform,
            bot_key=bot_key,
            user_id=sender_id,
            user_name=sender_name,
            chat_id=chat_id,
            chat_type=chat_type,
            text=content,
            images=images,
            msg_type=msg_type,
            message_id=raw_data.get("message_id", ""),
            raw_data=raw_data,
        )

    async def send_outbound(self, message: OutboundMessage) -> SendResult:
        """
        将 OutboundMessage 通过 QQ Bot API 发送

        根据 chat_id 前缀判断发送目标：
        - c2c:{openid} → 私聊
        - group:{group_openid} → 群聊
        - channel:{channel_id} → 频道
        - dm:{user_id} → 频道私信
        """
        try:
            client = self._get_bot_client(message.bot_key)
            if not client:
                return SendResult(
                    success=False,
                    error=f"未找到 bot_key={message.bot_key} 对应的 QQBotClient",
                )

            target_type, target_id = self._parse_chat_id(message.chat_id)
            if not target_type or not target_id:
                return SendResult(
                    success=False,
                    error=f"无法解析 chat_id={message.chat_id}",
                )

            text = message.text
            parts_sent = 0

            # 从 extra 中获取原始 message_id（用于被动回复）
            reply_msg_id = message.extra.get("reply_msg_id")

            if len(text) <= QQBOT_MAX_MESSAGE_LENGTH:
                await client.send_text(target_type, target_id, text, msg_id=reply_msg_id)
                parts_sent = 1
            else:
                chunks = self._chunk_text(text, QQBOT_MAX_MESSAGE_LENGTH)
                total = len(chunks)
                logger.info(
                    f"[qqbot] 消息过长，分拆为 {total} 条发送: "
                    f"{target_type}:{target_id}"
                )
                for idx, chunk in enumerate(chunks):
                    prefix = f"({idx + 1}/{total}) " if total > 1 else ""
                    mid = reply_msg_id if idx == 0 else None
                    await client.send_text(target_type, target_id, prefix + chunk, msg_id=mid)
                    parts_sent += 1

            logger.info(
                f"[qqbot] 消息已发送: {target_type}:{target_id}, parts={parts_sent}"
            )
            return SendResult(success=True, parts_sent=parts_sent)

        except Exception as e:
            logger.error(f"[qqbot] 发送消息失败: {e}", exc_info=True)
            return SendResult(success=False, error=str(e))

    # ============== 内部辅助方法 ==============

    def _get_bot_client(self, bot_key: str):
        """获取对应 bot_key 的 QQBotClient 实例"""
        if not bot_key:
            return None
        try:
            from ..routes.qqbot import qqbot_clients
            return qqbot_clients.get(bot_key)
        except Exception as e:
            logger.error(f"[qqbot] 获取 QQBotClient 失败: {e}", exc_info=True)
            return None

    @staticmethod
    def _parse_chat_id(chat_id: str) -> tuple[Optional[str], Optional[str]]:
        """
        解析 chat_id 为 (target_type, target_id)

        格式：{type}:{id}
        """
        if ":" not in chat_id:
            return "c2c", chat_id

        parts = chat_id.split(":", 1)
        type_map = {
            "c2c": "c2c",
            "group": "group",
            "channel": "channel",
            "dm": "c2c",
        }
        target_type = type_map.get(parts[0])
        if target_type:
            return target_type, parts[1]
        return None, None

    @staticmethod
    def _chunk_text(text: str, limit: int) -> list[str]:
        """将文本按限制分块，优先在换行处分割"""
        if len(text) <= limit:
            return [text]

        chunks: list[str] = []
        remaining = text

        while remaining:
            if len(remaining) <= limit:
                chunks.append(remaining)
                break

            split_at = remaining.rfind("\n", 0, limit)
            if split_at <= 0 or split_at < limit * 0.5:
                split_at = remaining.rfind(" ", 0, limit)
            if split_at <= 0 or split_at < limit * 0.5:
                split_at = limit

            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip()

        return chunks
