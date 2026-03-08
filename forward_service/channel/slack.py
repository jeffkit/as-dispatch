"""
Slack 通道适配器

负责：
- URL 验证（duck-type get_verification_response）
- 重试请求检测（X-Slack-Retry-Num 请求头）
- 过滤 Bot 消息
- 从 api_app_id 提取 bot_key
- 解析 Slack Event Callback → InboundMessage
- 提取图片附件（url_private_download）
- 将 OutboundMessage → Slack 消息并发送
"""
import logging
from typing import Any, Optional

from .base import ChannelAdapter, InboundMessage, OutboundMessage, SendResult

logger = logging.getLogger(__name__)


class SlackAdapter(ChannelAdapter):
    """
    Slack 通道适配器

    通过 Slack Events API Webhook 接收事件，支持 URL 验证和重试检测。
    """

    @property
    def platform(self) -> str:
        return "slack"

    def should_ignore(self, raw_data: dict) -> bool:
        """
        判断是否忽略此消息

        忽略条件（按优先级）：
        1. X-Slack-Retry-Num 请求头存在（Slack 重试）→ 立即返回 200
        2. url_verification 类型（由 get_verification_response 处理）
        3. Bot 消息（bot_id 存在或 subtype == "bot_message"）
        """
        headers = raw_data.get("_request_headers", {})

        # 1. 重试检测：忽略 Slack 自动重试
        retry_num = headers.get("x-slack-retry-num", "")
        if retry_num:
            logger.info(f"[slack] 检测到 Slack 重试请求 (Retry-Num={retry_num})，忽略")
            return True

        # 2. URL 验证由 get_verification_response 处理
        if raw_data.get("type") == "url_verification":
            return True

        # 3. Bot 消息过滤
        event = raw_data.get("event", {})
        if event.get("bot_id"):
            logger.debug("[slack] 忽略 Bot 消息 (bot_id 存在)")
            return True
        if event.get("subtype") == "bot_message":
            logger.debug("[slack] 忽略 Bot 消息 (subtype=bot_message)")
            return True

        return False

    def get_verification_response(self, raw_data: dict) -> Optional[dict]:
        """
        Duck-type 方法：处理 Slack URL 验证挑战

        Slack 在配置 Events API 端点时会发送 url_verification 类型请求，
        需要立即返回 {"challenge": "..."} 响应。

        Returns:
            包含 challenge 的字典（验证通过），或 None（非验证请求）
        """
        if raw_data.get("type") != "url_verification":
            return None

        challenge = raw_data.get("challenge", "")
        if not challenge:
            logger.warning("[slack] url_verification 请求中无 challenge 字段")
            return None

        logger.info("[slack] 处理 URL 验证挑战")
        return {"challenge": challenge}

    def extract_bot_key(self, raw_data: dict, **kwargs: Any) -> Optional[str]:
        """
        从 Slack 事件中提取 bot_key

        使用 api_app_id（Slack App ID）作为 bot_key。
        """
        api_app_id = raw_data.get("api_app_id", "")
        if api_app_id:
            return api_app_id

        # 兼容：从 authorizations 字段获取
        auths = raw_data.get("authorizations", [])
        if auths:
            app_id = auths[0].get("app_id", "")
            if app_id:
                return app_id

        logger.warning("[slack] 无法从事件中提取 api_app_id（bot_key）")
        return None

    async def parse_inbound(self, raw_data: dict, **kwargs: Any) -> InboundMessage:
        """
        将 Slack Event Callback 解析为 InboundMessage

        处理：
        1. 提取 event 对象中的消息内容
        2. 提取发送者信息
        3. 提取图片附件（url_private_download）
        """
        bot_key = self.extract_bot_key(raw_data) or ""
        event = raw_data.get("event", {})

        if not event:
            raise ValueError("Slack 事件回调中无 event 字段")

        event_type = event.get("type", "")
        if event_type != "message" and event_type != "app_mention":
            raise ValueError(f"不支持的 Slack 事件类型: {event_type}")

        user_id = event.get("user", "")
        if not user_id:
            raise ValueError("Slack 事件中缺少 user 字段")

        channel = event.get("channel", "")
        channel_type = event.get("channel_type", "channel")
        text = (event.get("text") or "").strip()
        ts = event.get("ts", "")

        # 提取图片附件（Slack 文件）
        images: list[str] = []
        files = event.get("files", [])
        for f in files:
            mimetype = f.get("mimetype", "")
            if mimetype.startswith("image/"):
                url = f.get("url_private_download", "") or f.get("url_private", "")
                if url:
                    images.append(url)

        if not text and not images:
            raise ValueError("Slack 消息内容为空（无文本也无图片）")

        # 消息类型判断
        if images and not text:
            msg_type = "image"
        elif images and text:
            msg_type = "mixed"
        else:
            msg_type = "text"

        # channel_type 映射
        normalized_chat_type = "direct" if channel_type == "im" else "group"

        return InboundMessage(
            platform=self.platform,
            bot_key=bot_key,
            user_id=user_id,
            user_name=user_id,  # Slack 事件中通常只有 user_id，不包含显示名
            chat_id=channel,
            chat_type=normalized_chat_type,
            text=text,
            images=images,
            msg_type=msg_type,
            message_id=ts,  # Slack 使用 timestamp 作为消息 ID
            raw_data=raw_data,
        )

    async def send_outbound(self, message: OutboundMessage) -> SendResult:
        """
        将 OutboundMessage 转换为 Slack 消息并发送

        使用 SlackClient.post_message() 发送到频道或私信。
        """
        try:
            client = self._get_client(message.bot_key)
            if not client:
                return SendResult(
                    success=False,
                    error=f"未找到 bot_key={message.bot_key} 对应的 SlackClient",
                )

            await client.post_message(
                channel=message.chat_id,
                text=message.text,
            )

            logger.info(f"[slack] 消息已发送: channel={message.chat_id}")
            return SendResult(success=True, parts_sent=1)

        except Exception as e:
            logger.error(f"[slack] 发送消息失败: {e}", exc_info=True)
            return SendResult(success=False, error=str(e))

    # ============== 内部辅助方法 ==============

    def _get_client(self, bot_key: str):
        """
        根据 bot_key 获取 SlackClient 实例

        从 Bot 配置中读取 bot_token，创建并返回 SlackClient 实例。

        Returns:
            SlackClient 实例，如果配置不存在返回 None
        """
        if not bot_key:
            return None

        try:
            from ..config import config
            from ..clients.slack import SlackClient

            bot_config = config.get_bot(bot_key)
            if not bot_config or not bot_config._bot:
                logger.warning(f"[slack] 未找到 bot_key={bot_key[:10]}... 的配置")
                return None

            platform_cfg = bot_config._bot.get_platform_config()
            bot_token = platform_cfg.get("bot_token", "")

            if not bot_token:
                logger.warning(f"[slack] bot_key={bot_key[:10]}... 未配置 bot_token")
                return None

            return SlackClient(bot_token=bot_token)

        except Exception as e:
            logger.error(f"[slack] 创建 SlackClient 失败: {e}", exc_info=True)
            return None
