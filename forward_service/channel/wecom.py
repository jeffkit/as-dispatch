"""
企业微信通道适配器

负责：
- 解析企微 webhook 回调数据 → InboundMessage
- 将 OutboundMessage → 企微消息格式并发送
- 消息分拆（企微 2KB 限制）
- @ 提醒（群聊场景）
- 引用消息解析（企微特有的中文引号 + 分割线格式）
"""
import logging
import re
from typing import Any, Optional

from .base import ChannelAdapter, InboundMessage, OutboundMessage, SendResult

logger = logging.getLogger(__name__)


# ============== 企微特定常量 ==============

# 企微消息最大字节数
WECOM_MAX_MESSAGE_BYTES = 2048

# 企微引用消息格式：
#   \u201c被引用的消息内容\u201d
#   ------
#   @机器人 用户实际回复
QUOTE_SEPARATOR = "\n------\n"
SHORT_ID_PATTERN = re.compile(r'\[#([a-f0-9]{6,8})(?:\s+\S+)?\]')

# 纯图片消息占位文本
IMAGE_ONLY_PLACEHOLDER = "[图片]"


class WeComAdapter(ChannelAdapter):
    """
    企业微信通道适配器

    处理企微 webhook 回调的消息解析和消息发送。
    """

    @property
    def platform(self) -> str:
        return "wecom"

    @property
    def max_message_bytes(self) -> int:
        return WECOM_MAX_MESSAGE_BYTES

    def should_ignore(self, raw_data: dict) -> bool:
        """忽略企微的事件类型消息"""
        msg_type = raw_data.get("msgtype", "")
        return msg_type in ("event", "enter_chat")

    def extract_bot_key(self, raw_data: dict, **kwargs: Any) -> Optional[str]:
        """
        从企微 webhook_url 中提取 bot_key

        企微回调数据中的 webhook_url 格式：
        https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
        """
        webhook_url = raw_data.get("webhook_url", "")
        match = re.search(r'[?&]key=([^&]+)', webhook_url)
        if match:
            return match.group(1)
        return None

    async def parse_inbound(self, raw_data: dict, **kwargs: Any) -> InboundMessage:
        """
        将企微回调数据解析为 InboundMessage

        处理：
        1. 提取 chat_id, chat_type, from_user 等基本信息
        2. 根据 msgtype 提取文本/图片内容
        3. 剥离引用消息（企微特有的中文引号 + 分割线格式）
        4. 去除 @bot 前缀
        5. 提取引用中的 short_id
        """
        chat_id = raw_data.get("chatid", "")
        chat_type = raw_data.get("chattype", "group")
        msg_type = raw_data.get("msgtype", "")
        from_user = raw_data.get("from", {})

        # 提取 bot_key
        bot_key = self.extract_bot_key(raw_data) or ""

        # 提取消息内容
        text, images, quoted_short_id = self._extract_content(raw_data)

        return InboundMessage(
            platform="wecom",
            bot_key=bot_key,
            user_id=from_user.get("userid", "unknown"),
            user_name=from_user.get("name", "unknown"),
            user_alias=from_user.get("alias", ""),
            chat_id=chat_id,
            chat_type="direct" if chat_type == "single" else "group",
            text=text or "",
            images=images,
            msg_type=msg_type,
            quoted_short_id=quoted_short_id,
            message_id=raw_data.get("msgid", ""),
            raw_data=raw_data,
        )

    async def send_outbound(self, message: OutboundMessage) -> SendResult:
        """
        将 OutboundMessage 转换为企微消息格式并发送

        处理：
        1. 消息头部标识（[#short_id project_name]）
        2. 消息分拆（> 2KB）
        3. @ 提醒（群聊）
        4. 调用 fly-pigeon 发送
        """
        try:
            from ..message_splitter import (
                split_and_format_message,
                needs_split,
            )

            text = message.text
            short_id = message.short_id
            project_name = message.project_name
            mentioned_list = message.mentioned_user_ids

            # 检查是否需要分拆
            if short_id and needs_split(text, short_id, project_name):
                logger.info(f"消息过长，分拆发送: chat_id={message.chat_id}")
                return await self._send_split(message)

            # 不需要分拆，直接发送
            result = self._send_raw(
                text=text,
                chat_id=message.chat_id,
                msg_type=message.msg_type,
                bot_key=message.bot_key,
                mentioned_list=mentioned_list,
            )

            if isinstance(result, dict) and result.get("errcode", 0) != 0:
                return SendResult(
                    success=False,
                    error=f"发送失败: {result.get('errmsg', '未知错误')}",
                )

            return SendResult(success=True, parts_sent=1)

        except Exception as e:
            logger.error(f"发送回复失败: {e}", exc_info=True)
            return SendResult(success=False, error=str(e))

    # ============== 内部方法 ==============

    def _extract_content(
        self, data: dict
    ) -> tuple[Optional[str], list[str], Optional[str]]:
        """
        从企微回调数据提取内容

        Returns:
            (text, image_urls, quoted_short_id)
        """
        msg_type = data.get("msgtype", "")

        if msg_type == "text":
            text_data = data.get("text", {})
            content = text_data.get("content", "")
            content, quoted_short_id = self._strip_quote(content)
            content = self._strip_at_prefix(content)
            return content, [], quoted_short_id

        elif msg_type == "image":
            image_data = data.get("image", {})
            image_url = image_data.get("image_url", "")
            image_urls = [image_url] if image_url else []
            text = IMAGE_ONLY_PLACEHOLDER if image_urls else None
            return text, image_urls, None

        elif msg_type == "mixed":
            mixed = data.get("mixed_message", {})
            msg_items = mixed.get("msg_item", [])

            contents: list[str] = []
            images: list[str] = []
            quoted_short_id = None

            for item in msg_items:
                item_type = item.get("msg_type", "")
                if item_type == "text":
                    text = item.get("text", {}).get("content", "")
                    if not contents and not quoted_short_id:
                        text, quoted_short_id = self._strip_quote(text)
                    text = self._strip_at_prefix(text)
                    if text:
                        contents.append(text)
                elif item_type == "image":
                    img_url = item.get("image", {}).get("image_url", "")
                    if img_url:
                        images.append(img_url)

            content = "\n".join(contents) if contents else None
            if not content and images:
                content = IMAGE_ONLY_PLACEHOLDER
            return content, images, quoted_short_id

        return None, [], None

    def _strip_quote(self, text: str) -> tuple[str, Optional[str]]:
        """
        剥离企微引用消息内容

        企微引用格式:
            \u201c被引用的消息...\u201d
            ------
            @机器人 用户实际回复

        Returns:
            (clean_text, quoted_short_id)
        """
        if not text or QUOTE_SEPARATOR not in text:
            return text, None

        sep_index = text.find(QUOTE_SEPARATOR)
        if sep_index < 0:
            return text, None

        quoted_part = text[:sep_index]
        user_reply = text[sep_index + len(QUOTE_SEPARATOR) :]

        if not quoted_part.startswith("\u201c"):
            return text, None

        # 从引用内容中提取 short_id
        quoted_short_id = None
        match = SHORT_ID_PATTERN.search(quoted_part)
        if match:
            quoted_short_id = match.group(1)
            logger.info(f"从引用消息中提取到 short_id: {quoted_short_id}")

        user_reply = user_reply.strip()

        if not user_reply:
            logger.warning("引用回复中用户实际内容为空")
            return "", quoted_short_id

        logger.info(f"剥离引用消息，用户实际回复: {user_reply[:50]}...")
        return user_reply, quoted_short_id

    def _strip_at_prefix(self, text: str) -> str:
        """去除文本开头的 @机器人 前缀"""
        if text and text.startswith("@"):
            parts = text.split(" ", 1)
            if len(parts) > 1:
                return parts[1].strip()
        return text

    def _send_raw(
        self,
        text: str,
        chat_id: str,
        msg_type: str = "text",
        bot_key: str | None = None,
        mentioned_list: list[str] | None = None,
    ) -> dict:
        """
        使用 fly-pigeon 发送原始消息到企微

        Returns:
            企微 API 返回结果
        """
        from ..config import config

        bot_key = bot_key or config.bot_key if hasattr(config, "bot_key") else bot_key
        if not bot_key:
            raise ValueError("未配置 bot_key")

        try:
            from pigeon import Bot
        except ImportError:
            raise ImportError(
                "fly-pigeon 包未安装。企微功能需要安装: pip install fly-pigeon\n"
                "或安装完整依赖: pip install 'as-dispatch[wecom]'"
            )

        bot = Bot(bot_key=bot_key)

        logger.info(
            f"发送消息到企微: chat_id={chat_id}, msg_type={msg_type}, "
            f"mentioned={mentioned_list}, message={text[:50]}..."
        )

        try:
            if msg_type == "markdown":
                result = bot.markdown(chat_id=chat_id, msg_content=text)
            else:
                kwargs = {"chat_id": chat_id, "msg_content": text}
                if mentioned_list:
                    kwargs["mentioned_list"] = mentioned_list
                result = bot.text(**kwargs)

            response_data = None
            if hasattr(result, "json"):
                try:
                    response_data = result.json()
                except Exception:
                    pass
            elif isinstance(result, dict):
                response_data = result

            logger.info(f"fly-pigeon 响应: status={result}, data={response_data}")

            if response_data:
                errcode = response_data.get("errcode", 0)
                if errcode != 0:
                    logger.error(
                        f"企微发送失败: errcode={errcode}, errmsg={response_data.get('errmsg')}"
                    )
                    return response_data

            return response_data or {"errcode": 0, "errmsg": "ok"}

        except Exception as e:
            logger.error(f"fly-pigeon 发送失败: {e}", exc_info=True)
            raise

    async def _send_split(self, message: OutboundMessage) -> SendResult:
        """分拆消息并逐条发送"""
        from ..message_splitter import split_and_format_message

        try:
            split_messages = split_and_format_message(
                message=message.text,
                short_id=message.short_id or "",
                project_name=message.project_name,
            )

            logger.info(
                f"消息分拆为 {len(split_messages)} 条: chat_id={message.chat_id}"
            )

            for split_msg in split_messages:
                result = self._send_raw(
                    text=split_msg.content,
                    chat_id=message.chat_id,
                    msg_type=message.msg_type,
                    bot_key=message.bot_key,
                    mentioned_list=message.mentioned_user_ids,
                )

                if isinstance(result, dict) and result.get("errcode", 0) != 0:
                    return SendResult(
                        success=False,
                        parts_sent=split_msg.part_number - 1,
                        error=f"第 {split_msg.part_number}/{split_msg.total_parts} 条消息发送失败: {result.get('errmsg', '未知错误')}",
                    )

            return SendResult(success=True, parts_sent=len(split_messages))

        except Exception as e:
            logger.error(f"分拆消息发送失败: {e}", exc_info=True)
            return SendResult(success=False, error=str(e))
