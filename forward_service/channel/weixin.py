"""
微信个人号通道适配器

负责：
- 将 iLinkAI 长轮询消息解析为 InboundMessage
- 将 OutboundMessage 通过 iLinkAI API 发送
- 多媒体消息的收发（图片/语音/文件/视频）

架构说明：
微信个人号使用 HTTP 长轮询（getupdates）接收消息，类似 QQ Bot 的 WebSocket Gateway。
消息不经过 unified_callback.py 的 POST /callback/{platform} 路由，
而是从 routes/weixin.py::handle_weixin_message 调用 pipeline.process_message()。

所有 HTTP 调用委托给 forward_service/clients/weixin.py::WeixinClient。

多媒体消息处理架构：
- 入站: routes/weixin.py 传递原始 item_list → WeixinAdapter.parse_inbound() →
  weixin_media.process_inbound_media() → 按类型分发下载解密
  - 图片 → InboundMessage.images (base64 data URI)
  - 语音 → 优先使用平台转写文本，降级下载原始音频
  - 文件/视频 → raw_data 扩展字段
- 出站: OutboundMessage.extra 字典传递媒体 URL →
  WeixinAdapter.send_outbound() → 下载 → 加密上传 CDN → 发送媒体消息
  - image_urls → 图片消息
  - file_url/file_path → 文件消息
  - video_url/video_path → 视频消息

CDN 操作链路: weixin_crypto (AES) → weixin_cdn (HTTP) → weixin_media (业务) → weixin (适配器)
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
            "_media_items": list[dict],  # 非文本消息时包含完整 item_list
        }

        多媒体处理:
        当 _media_items 存在时，调用 weixin_media.process_inbound_media()
        下载解密媒体内容。图片走 images 字段，语音/文件/视频走 raw_data 扩展。
        """
        bot_key = self.extract_bot_key(raw_data, **kwargs) or ""
        sender_id = raw_data.get("sender_id", "")
        sender_name = raw_data.get("sender_name", sender_id[:8] if sender_id else "unknown")
        content = raw_data.get("content", "")
        msg_type = raw_data.get("message_type", "text")

        chat_id = f"direct:{sender_id}"

        images: list[str] = []
        media_items = raw_data.get("_media_items")

        if media_items:
            try:
                http_client, cdn_base_url = self._get_media_deps(bot_key)
                from .weixin_media import process_inbound_media
                media_text, media_images, media_extra = await process_inbound_media(
                    http_client, cdn_base_url, media_items,
                )
                if media_images:
                    images = media_images
                if media_text:
                    content = media_text
                if media_extra:
                    raw_data.update(media_extra)
            except Exception as e:
                logger.error(f"[weixin] 媒体处理失败，回退占位文本: {e}", exc_info=True)

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
            images=images,
            msg_type=msg_type,
            message_id=message_id,
            raw_data=raw_data,
        )

    async def send_outbound(self, message: OutboundMessage) -> SendResult:
        """
        将 OutboundMessage 通过 iLinkAI API 发送。

        支持:
        - 纯文本消息: 使用已有 send_message
        - 图片消息: extra["image_urls"] → 下载 → 加密上传 CDN → 发送图片消息
        - 文件消息: extra["file_url"] / extra["file_path"] → 加密上传 → 发送文件消息
        - 视频消息: extra["video_url"] / extra["video_path"] → 加密上传 → 发送视频消息

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

            parts_sent = 0
            extra = message.extra or {}

            # 发送文本消息
            if message.text:
                await poller.client.send_message(
                    to_user_id=user_id,
                    context_token=context_token,
                    text=message.text,
                )
                parts_sent += 1

            # 发送图片消息
            image_urls = extra.get("image_urls") or []
            if image_urls:
                parts_sent += await self._send_media_items(
                    poller, user_id, context_token, image_urls, "image",
                )

            # 发送文件消息
            file_url = extra.get("file_url") or extra.get("file_path")
            file_name = extra.get("file_name", "file.bin")
            if file_url:
                parts_sent += await self._send_media_items(
                    poller, user_id, context_token, [file_url], "file",
                    file_name=file_name,
                )

            # 发送视频消息
            video_url = extra.get("video_url") or extra.get("video_path")
            if video_url:
                parts_sent += await self._send_media_items(
                    poller, user_id, context_token, [video_url], "video",
                )

            if parts_sent == 0 and not message.text:
                return SendResult(success=False, error="消息内容为空")

            log_text = message.text[:50] + "..." if len(message.text) > 50 else message.text
            logger.info(
                f"[weixin] 消息已发送: chat_id={chat_id}, "
                f"parts={parts_sent}, text={log_text}"
            )
            return SendResult(success=True, parts_sent=parts_sent)

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

    async def _send_media_items(
        self,
        poller: Any,
        user_id: str,
        context_token: str,
        urls: list[str],
        media_kind: str,
        file_name: str = "",
    ) -> int:
        """下载、加密上传、发送媒体消息。返回成功发送的条数。"""
        from .weixin_media import (
            WeixinMediaType,
            build_file_item,
            build_image_item,
            build_video_item,
            upload_media,
        )

        media_type_map = {
            "image": WeixinMediaType.IMAGE,
            "file": WeixinMediaType.FILE,
            "video": WeixinMediaType.VIDEO,
        }
        build_fn_map = {
            "image": lambda r: build_image_item(r),
            "file": lambda r: build_file_item(r, file_name),
            "video": lambda r: build_video_item(r),
        }

        http_client = poller.client._http
        _, cdn_base_url = self._get_media_deps(poller.bot_key)
        wx_media_type = media_type_map[media_kind]
        build_fn = build_fn_map[media_kind]

        sent = 0
        for url in urls:
            try:
                data = await self._download_media_data(http_client, url)
                if not data:
                    logger.warning(f"[weixin] 媒体数据为空，跳过: {url[:60]}")
                    continue

                result = await upload_media(
                    http_client, poller.client, cdn_base_url,
                    user_id, data, wx_media_type, file_name,
                )
                if not result.success:
                    logger.error(
                        f"[weixin] 媒体上传失败: {result.error}, "
                        f"回退为文本"
                    )
                    await poller.client.send_message(
                        to_user_id=user_id,
                        context_token=context_token,
                        text=f"[{media_kind}发送失败: {result.error}]",
                    )
                    sent += 1
                    continue

                item = build_fn(result)
                await poller.client.send_media_message(
                    to_user_id=user_id,
                    context_token=context_token,
                    item_list=[item],
                )
                sent += 1
            except Exception as e:
                logger.error(
                    f"[weixin] 发送{media_kind}失败: {e}", exc_info=True,
                )
                try:
                    await poller.client.send_message(
                        to_user_id=user_id,
                        context_token=context_token,
                        text=f"[{media_kind}发送失败]",
                    )
                    sent += 1
                except Exception:
                    pass

        return sent

    async def _download_media_data(
        self, http_client: Any, url: str,
    ) -> bytes | None:
        """从 URL 或 data URI 获取媒体数据。"""
        import base64 as b64mod

        if url.startswith("data:"):
            try:
                _, encoded = url.split(",", 1)
                return b64mod.b64decode(encoded)
            except Exception as e:
                logger.error(f"[weixin] data URI 解析失败: {e}")
                return None

        try:
            resp = await http_client.get(url, timeout=30.0)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            logger.error(f"[weixin] 下载媒体失败: {url[:60]}: {e}")
            return None

    def _get_media_deps(self, bot_key: str) -> tuple[Any, str]:
        """获取媒体处理所需的 http_client 和 cdn_base_url。

        Returns:
            (http_client, cdn_base_url)

        Raises:
            RuntimeError: 无法获取依赖
        """
        from .weixin_media import DEFAULT_CDN_BASE_URL

        poller = self._get_poller(bot_key)
        if not poller:
            raise RuntimeError(f"未找到 bot_key={bot_key} 对应的 WeixinPoller")

        http_client = poller.client._http

        cdn_base_url = DEFAULT_CDN_BASE_URL
        try:
            from ..config import config
            bot_config = config.get_bot_or_default(bot_key)
            if bot_config and bot_config._bot:
                pc = bot_config._bot.get_platform_config()
                cdn_base_url = pc.get("cdn_base_url", DEFAULT_CDN_BASE_URL)
        except Exception:
            pass

        return http_client, cdn_base_url
