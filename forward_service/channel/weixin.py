"""
微信个人号通道适配器

负责：
- 将 iLinkAI 长轮询消息解析为 InboundMessage
- 将 OutboundMessage 通过 iLinkAI API 发送
- 非文本消息的占位符处理

架构说明：
微信个人号使用 HTTP 长轮询（getupdates）接收消息，类似 QQ Bot 的 WebSocket Gateway。
消息不经过 unified_callback.py 的 POST /callback/{platform} 路由，
而是从 routes/weixin.py::handle_weixin_message 调用 pipeline.process_message()。

所有 HTTP 调用委托给 forward_service/clients/weixin.py::WeixinClient。
"""
import hashlib
import logging
import time
from enum import Enum
from typing import Any, Optional

from .base import ChannelAdapter, InboundMessage, OutboundMessage, SendResult

logger = logging.getLogger(__name__)

# ============== 消息类型常量 ==============

WEIXIN_MSG_TYPE_TEXT = 1
WEIXIN_MSG_TYPE_IMAGE = 2
WEIXIN_MSG_TYPE_VOICE = 3
WEIXIN_MSG_TYPE_FILE = 4
WEIXIN_MSG_TYPE_VIDEO = 5

WEIXIN_MSG_TYPE_NAMES: dict[int, str] = {
    1: "text",
    2: "image",
    3: "voice",
    4: "file",
    5: "video",
}

WEIXIN_NON_TEXT_PLACEHOLDERS: dict[int, str] = {
    2: "[收到了图片，暂不支持处理图片消息]",
    3: "[收到了语音，暂不支持处理语音消息]",
    4: "[收到了文件，暂不支持处理文件消息]",
    5: "[收到了视频，暂不支持处理视频消息]",
}

# iLinkAI 消息类型
WEIXIN_MESSAGE_TYPE_USER = 1
WEIXIN_MESSAGE_TYPE_BOT = 2


class WeixinPollerStatus(str, Enum):
    """微信长轮询器状态"""
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    EXPIRED = "expired"
    LOGIN_PENDING = "login_pending"


class WeixinAdapter(ChannelAdapter):
    """
    微信个人号通道适配器

    通过 iLinkAI 协议长轮询接收消息，解析后进入统一处理管线。
    """

    @property
    def platform(self) -> str:
        return "weixin"

    def should_ignore(self, raw_data: dict) -> bool:
        """
        判断是否忽略此消息。

        忽略条件：
        - 群聊消息（group_id 非空）— 仅处理私聊

        非用户消息（Bot 自身回复等）已在 _parse_weixin_message() 中通过
        原始 iLinkAI 整数类型码过滤（返回 None）。parsed dict 中的
        message_type 是字符串（如 "text"），不能与整数常量比较。
        """
        if raw_data.get("group_id"):
            logger.debug(
                f"[weixin] 忽略群聊消息: group_id={raw_data.get('group_id')}"
            )
            return True

        return False

    def extract_bot_key(self, raw_data: dict, **kwargs: Any) -> Optional[str]:
        """
        从 raw_data 中提取 bot_key。

        bot_key 由 WeixinPoller 在注入消息时通过 _bot_key 字段传入。
        """
        return raw_data.get("_bot_key") or kwargs.get("bot_key") or None

    async def parse_inbound(self, raw_data: dict, **kwargs: Any) -> InboundMessage:
        """
        将 iLinkAI 消息解析为 InboundMessage。

        raw_data 格式（由 WeixinPoller._parse_message 生成）：
        {
            "type": "direct",
            "sender_id": str,
            "sender_name": str,
            "content": str,
            "message_type": str,  # "text" / "image" / "voice" / etc.
            "context_token": str,
            "_bot_key": str,
        }
        """
        bot_key = self.extract_bot_key(raw_data, **kwargs) or ""
        sender_id = raw_data.get("sender_id", "")
        sender_name = raw_data.get("sender_name", sender_id[:8] if sender_id else "unknown")
        content = raw_data.get("content", "")
        msg_type = raw_data.get("message_type", "text")
        context_token = raw_data.get("context_token", "")

        chat_id = f"direct:{sender_id}"

        if not content:
            raise ValueError("微信消息内容为空")

        message_id = raw_data.get("message_id", "")
        if not message_id:
            raw_key = f"{bot_key}|{sender_id}|{content}|{time.time()}"
            message_id = f"wx_{hashlib.sha256(raw_key.encode()).hexdigest()[:16]}"

        return InboundMessage(
            platform=self.platform,
            bot_key=bot_key,
            user_id=sender_id,
            user_name=sender_name,
            user_alias="",
            chat_id=chat_id,
            chat_type="direct",
            text=content,
            images=[],
            msg_type=msg_type,
            message_id=message_id,
            raw_data=raw_data,
        )

    async def send_outbound(self, message: OutboundMessage) -> SendResult:
        """
        将 OutboundMessage 通过 iLinkAI API 发送。

        从活跃的 WeixinPoller 中获取 WeixinClient 和 context_token。
        错误不抛出，返回 SendResult(success=False, error=...) per constitution P3。
        """
        try:
            poller = self._get_poller(message.bot_key)
            if not poller:
                return SendResult(
                    success=False,
                    error=f"未找到 bot_key={message.bot_key} 对应的微信 Poller",
                )

            chat_id = message.chat_id
            if not chat_id.startswith("direct:"):
                return SendResult(
                    success=False,
                    error=f"不支持的 chat_id 格式: {chat_id}",
                )

            user_id = chat_id.split(":", 1)[1]
            context_token = poller.context_tokens.get(user_id, "")

            if not context_token:
                logger.warning(
                    f"[weixin] 缺少 context_token: user={user_id}, "
                    f"仍尝试发送（可能缺少会话关联）"
                )

            await poller.client.send_message(
                to_user_id=user_id,
                context_token=context_token,
                text=message.text,
            )

            logger.info(
                f"[weixin] 消息已发送: chat_id={chat_id}, "
                f"text={message.text[:50]}..."
                if len(message.text) > 50
                else f"[weixin] 消息已发送: chat_id={chat_id}, text={message.text}"
            )
            return SendResult(success=True, parts_sent=1)

        except Exception as e:
            logger.error(f"[weixin] 发送消息失败: {e}", exc_info=True)
            return SendResult(success=False, error=str(e))

    # ============== 内部方法 ==============

    def _get_poller(self, bot_key: str) -> Any:
        """获取对应 bot_key 的 WeixinPoller 实例"""
        if not bot_key:
            return None
        try:
            from ..routes.weixin import weixin_pollers
            return weixin_pollers.get(bot_key)
        except Exception as e:
            logger.error(f"[weixin] 获取 WeixinPoller 失败: {e}", exc_info=True)
            return None
