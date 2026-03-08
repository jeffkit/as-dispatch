"""
飞书 (Lark) 通道适配器

负责：
- URL 验证（duck-type get_verification_response）
- 事件解密（AES-256-CBC，如果配置了 encrypt_key）
- 解析 p2.im.message.receive_v1 事件 → InboundMessage
- 过滤 Bot 消息和非消息事件
- 将 OutboundMessage → 飞书文本消息并发送
"""
import json
import logging
from typing import Any, Optional

from .base import ChannelAdapter, InboundMessage, OutboundMessage, SendResult

logger = logging.getLogger(__name__)


class LarkAdapter(ChannelAdapter):
    """
    飞书通道适配器

    通过 Webhook 接收飞书事件回调，支持加密事件和 URL 验证挑战。
    """

    @property
    def platform(self) -> str:
        return "lark"

    def should_ignore(self, raw_data: dict) -> bool:
        """
        判断是否忽略此消息

        忽略条件：
        - URL 验证请求（在 get_verification_response 中单独处理）
        - 非消息类事件
        - Bot 自身发出的消息
        """
        # URL 验证会在 get_verification_response 中处理，这里不忽略也不会进管线
        request_type = raw_data.get("type", "")
        if request_type == "url_verification":
            return True

        # 非事件回调类型，忽略
        if request_type and request_type != "event_callback":
            logger.debug(f"[lark] 忽略非事件回调: type={request_type}")
            return True

        # 解密后的事件结构
        event_data = raw_data.get("event", {})
        sender = event_data.get("sender", {})
        sender_type = sender.get("sender_type", "")
        if sender_type == "app":
            logger.debug("[lark] 忽略 Bot 自身消息")
            return True

        # 检查事件类型
        header = raw_data.get("header", {})
        event_type = header.get("event_type", "")
        if event_type and event_type != "im.message.receive_v1":
            logger.debug(f"[lark] 忽略非消息事件: {event_type}")
            return True

        return False

    def get_verification_response(self, raw_data: dict) -> Optional[dict]:
        """
        Duck-type 方法：处理飞书 URL 验证挑战

        飞书在配置 Webhook URL 时会发送 url_verification 类型请求，
        需要立即返回 {"challenge": "..."} 响应。

        Returns:
            包含 challenge 的字典（验证通过），或 None（非验证请求）
        """
        if raw_data.get("type") != "url_verification":
            return None

        challenge = raw_data.get("challenge", "")
        token = raw_data.get("token", "")

        if not challenge:
            logger.warning("[lark] url_verification 请求中无 challenge 字段")
            return None

        logger.info("[lark] 处理 URL 验证挑战")

        # 可选：验证 token（如果 bot 配置了 verification_token）
        # 这里统一返回 challenge，token 验证逻辑在调用方
        return {"challenge": challenge}

    def extract_bot_key(self, raw_data: dict, **kwargs: Any) -> Optional[str]:
        """
        从飞书事件中提取 bot_key

        飞书的 app_id 作为 bot_key，从事件头中提取。
        """
        # 尝试从 header 的 app_id 获取
        header = raw_data.get("header", {})
        app_id = header.get("app_id", "")
        if app_id:
            return app_id

        # 兼容旧版事件格式
        app_id = raw_data.get("app_id", "")
        if app_id:
            return app_id

        logger.warning("[lark] 无法从事件中提取 app_id（bot_key）")
        return None

    async def parse_inbound(self, raw_data: dict, **kwargs: Any) -> InboundMessage:
        """
        将飞书事件回调解析为 InboundMessage

        处理：
        1. 如果有加密字段，先解密
        2. 提取发送者、会话信息
        3. 解析 p2.im.message.receive_v1 消息内容
        4. 处理图片消息（存储 image_key）
        """
        # 解密（如果需要）
        event_data = self._decrypt_if_needed(raw_data)

        bot_key = self.extract_bot_key(event_data) or ""

        header = event_data.get("header", {})
        event = event_data.get("event", {})
        message = event.get("message", {})
        sender = event.get("sender", {})

        # 发送者信息
        sender_id = sender.get("sender_id", {})
        user_id = sender_id.get("open_id", "") or sender_id.get("user_id", "")
        if not user_id:
            raise ValueError("飞书事件缺少 sender open_id")

        # 会话信息
        chat_id = message.get("chat_id", "")
        chat_type_raw = message.get("chat_type", "group")
        normalized_chat_type = "direct" if chat_type_raw == "p2p" else "group"

        # 消息类型
        message_type = message.get("message_type", "text")
        message_id = message.get("message_id", "")

        # 提取文本和图片
        text = ""
        images: list[str] = []
        msg_type = "text"

        content_str = message.get("content", "")
        if content_str:
            try:
                content_obj = json.loads(content_str)
            except json.JSONDecodeError:
                content_obj = {}

            if message_type == "text":
                text = content_obj.get("text", "").strip()
            elif message_type == "image":
                image_key = content_obj.get("image_key", "")
                if image_key:
                    images.append(image_key)
                    msg_type = "image"
                    text = ""
            elif message_type in ("file", "audio", "media"):
                # 其他文件类型，仅记录
                logger.debug(f"[lark] 收到非文本/图片消息: type={message_type}")

        if images and text:
            msg_type = "mixed"
        elif not images and text:
            msg_type = "text"

        # 用户显示名（飞书事件中通常无直接字段，使用 open_id）
        user_name = sender_id.get("open_id", user_id)

        return InboundMessage(
            platform=self.platform,
            bot_key=bot_key,
            user_id=user_id,
            user_name=user_name,
            chat_id=chat_id,
            chat_type=normalized_chat_type,
            text=text,
            images=images,
            msg_type=msg_type,
            message_id=message_id,
            raw_data=raw_data,
        )

    async def send_outbound(self, message: OutboundMessage) -> SendResult:
        """
        将 OutboundMessage 转换为飞书文本消息并发送

        使用 LarkClient.send_text() 发送文本消息。
        """
        try:
            client = self._get_client(message.bot_key)
            if not client:
                return SendResult(
                    success=False,
                    error=f"未找到 bot_key={message.bot_key} 对应的 LarkClient",
                )

            await client.send_text(
                receive_id=message.chat_id,
                text=message.text,
                receive_id_type="chat_id",
            )

            logger.info(f"[lark] 消息已发送: chat_id={message.chat_id}")
            return SendResult(success=True, parts_sent=1)

        except Exception as e:
            logger.error(f"[lark] 发送消息失败: {e}", exc_info=True)
            return SendResult(success=False, error=str(e))

    # ============== 内部辅助方法 ==============

    def _decrypt_if_needed(self, raw_data: dict) -> dict:
        """
        如果事件数据被加密，解密后返回；否则直接返回原始数据。

        飞书加密数据格式：{"encrypt": "<base64_encrypted_string>"}
        解密后得到完整的事件对象。
        """
        encrypted = raw_data.get("encrypt")
        if not encrypted:
            return raw_data

        # 从配置中获取 bot_key，再获取 encrypt_key
        # 飞书加密事件中，header.app_id 用于确定哪个 bot
        # 但加密事件中 header 本身也是加密的，需要先用已知配置解密
        # 此处使用 raw_data 的 app_id（飞书会在外层 JSON 中附带）
        app_id = raw_data.get("app_id", "")
        client = self._get_client(app_id)

        if not client:
            # 尝试用默认配置
            from ..config import config
            default_key = config.default_bot_key
            if default_key:
                client = self._get_client(default_key)

        if not client:
            logger.warning("[lark] 无法创建 LarkClient 进行事件解密")
            return raw_data

        try:
            decrypted = client.decrypt_event(encrypted)
            logger.debug("[lark] 事件解密成功")
            return decrypted
        except Exception as e:
            logger.error(f"[lark] 事件解密失败: {e}", exc_info=True)
            raise ValueError(f"飞书事件解密失败: {e}") from e

    def _get_client(self, bot_key: str):
        """
        根据 bot_key 获取 LarkClient 实例

        从 Bot 配置中读取 app_id、app_secret、encrypt_key，
        创建并返回 LarkClient 实例。

        Returns:
            LarkClient 实例，如果配置不存在返回 None
        """
        if not bot_key:
            return None

        try:
            from ..config import config
            from ..clients.lark import LarkClient

            bot_config = config.get_bot(bot_key)
            if not bot_config or not bot_config._bot:
                logger.warning(f"[lark] 未找到 bot_key={bot_key[:10]}... 的配置")
                return None

            platform_cfg = bot_config._bot.get_platform_config()
            app_id = platform_cfg.get("app_id", "")
            app_secret = platform_cfg.get("app_secret", "")
            encrypt_key = platform_cfg.get("encrypt_key")
            verification_token = platform_cfg.get("verification_token")

            if not app_id or not app_secret:
                logger.warning(f"[lark] bot_key={bot_key[:10]}... 未配置 app_id/app_secret")
                return None

            return LarkClient(
                app_id=app_id,
                app_secret=app_secret,
                encrypt_key=encrypt_key,
                verification_token=verification_token,
            )

        except Exception as e:
            logger.error(f"[lark] 创建 LarkClient 失败: {e}", exc_info=True)
            return None
