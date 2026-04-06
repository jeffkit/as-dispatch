"""
微信多媒体消息处理模块

类型定义、入站媒体解析、出站媒体构建。
所有 CDN 操作委托给 weixin_cdn.py，加解密委托给 weixin_crypto.py。

架构层级: weixin_crypto → weixin_cdn → weixin_media → WeixinAdapter
"""
import base64
import logging
import mimetypes
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

import httpx

from ..clients import weixin_cdn, weixin_crypto

logger = logging.getLogger(__name__)


# ============== 配置常量 ==============

DEFAULT_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
WEIXIN_MEDIA_MAX_BYTES = 100 * 1024 * 1024  # 100MB
WEIXIN_MEDIA_DOWNLOAD_TIMEOUT = 60.0
WEIXIN_MEDIA_UPLOAD_TIMEOUT = 60.0


# ============== 类型定义 ==============


class WeixinMediaType(IntEnum):
    """iLinkAI 上传媒体类型 (对应 UploadMediaType proto)"""
    IMAGE = 1
    VIDEO = 2
    FILE = 3
    VOICE = 4


@dataclass
class CDNMedia:
    """CDN 媒体引用信息"""
    encrypt_query_param: str
    aes_key: str  # base64 编码
    encrypt_type: int = 0


@dataclass
class MediaDownloadResult:
    """媒体下载解密结果"""
    data: bytes
    media_type: str  # MIME type
    file_name: str = ""
    success: bool = True
    error: str = ""


@dataclass
class MediaUploadResult:
    """媒体上传结果"""
    filekey: str
    download_encrypted_query_param: str
    aes_key_hex: str  # hex 编码的 AES key
    file_size: int  # 明文大小
    file_size_ciphertext: int  # 密文大小
    success: bool = True
    error: str = ""


# ============== 入站媒体处理 ==============


async def process_inbound_image(
    http_client: httpx.AsyncClient,
    cdn_base_url: str,
    image_item: dict[str, Any],
) -> MediaDownloadResult:
    """处理入站图片消息，下载解密图片。

    AES key 提取优先级:
    1. image_item.aeskey (hex 格式, 32 hex chars)
    2. image_item.media.aes_key (base64 格式)
    """
    media = image_item.get("media") or {}
    encrypt_query_param = media.get("encrypt_query_param", "")
    if not encrypt_query_param:
        return MediaDownloadResult(
            data=b"", media_type="", success=False, error="缺少 encrypt_query_param"
        )

    # 优先使用 image_item.aeskey (hex)，备选 media.aes_key (base64)
    raw_aeskey = image_item.get("aeskey", "")
    media_aes_key = media.get("aes_key", "")

    if raw_aeskey:
        aes_key_source = "image_item.aeskey"
        try:
            aes_key = weixin_crypto.parse_aes_key(raw_aeskey)
        except ValueError as e:
            return MediaDownloadResult(
                data=b"", media_type="", success=False,
                error=f"AES key 解析失败 ({aes_key_source}): {e}",
            )
    elif media_aes_key:
        aes_key_source = "media.aes_key"
        try:
            aes_key = weixin_crypto.parse_aes_key(media_aes_key)
        except ValueError as e:
            return MediaDownloadResult(
                data=b"", media_type="", success=False,
                error=f"AES key 解析失败 ({aes_key_source}): {e}",
            )
    else:
        return MediaDownloadResult(
            data=b"", media_type="", success=False, error="缺少 AES key"
        )

    logger.debug(
        f"[weixin] 图片下载: param={encrypt_query_param[:40]}... "
        f"key_source={aes_key_source}"
    )

    try:
        decrypted = await weixin_cdn.download_and_decrypt(
            http_client, cdn_base_url, encrypt_query_param, aes_key,
        )
    except Exception as e:
        logger.error(f"[weixin] 图片下载解密失败: {e}")
        return MediaDownloadResult(
            data=b"", media_type="", success=False, error=f"下载解密失败: {e}",
        )

    media_type = _detect_image_mime(decrypted)
    logger.info(f"[weixin] 图片下载成功: size={len(decrypted)}, mime={media_type}")
    return MediaDownloadResult(data=decrypted, media_type=media_type)


async def process_inbound_voice(
    http_client: httpx.AsyncClient,
    cdn_base_url: str,
    voice_item: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """处理入站语音消息。

    优先路径: 使用平台转写文本 (voice_item.text)
    降级路径: 下载解密语音文件

    Returns:
        (text, extra_data) — text 为转写文本或占位符, extra_data 可含 _voice_data
    """
    transcribed = voice_item.get("text", "") or voice_item.get("voice_to_text", "")
    if transcribed:
        logger.info(f"[weixin] 语音转写文本: {transcribed[:50]}")
        return transcribed, {}

    media = voice_item.get("media") or {}
    encrypt_query_param = media.get("encrypt_query_param", "")
    aes_key_str = media.get("aes_key", "")

    if not encrypt_query_param or not aes_key_str:
        return "[语音消息]", {}

    try:
        aes_key = weixin_crypto.parse_aes_key(aes_key_str)
        voice_data = await weixin_cdn.download_and_decrypt(
            http_client, cdn_base_url, encrypt_query_param, aes_key,
        )
        voice_b64 = base64.b64encode(voice_data).decode("ascii")
        logger.info(f"[weixin] 语音下载成功: size={len(voice_data)}")
        return "[语音消息]", {"_voice_data": voice_b64}
    except Exception as e:
        logger.error(f"[weixin] 语音下载失败: {e}")
        return "[语音消息]", {}


async def process_inbound_file(
    http_client: httpx.AsyncClient,
    cdn_base_url: str,
    file_item: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """处理入站文件消息，下载解密文件。

    Returns:
        (text, extra_data) — text 为文件描述, extra_data 含文件数据
    """
    file_name = file_item.get("file_name", "file.bin")
    file_len_str = file_item.get("len", "0")
    try:
        file_len = int(file_len_str)
    except (ValueError, TypeError):
        file_len = 0

    if file_len > WEIXIN_MEDIA_MAX_BYTES:
        msg = f"[文件过大: {file_name} ({file_len / 1024 / 1024:.1f}MB 超过限制)]"
        logger.warning(f"[weixin] {msg}")
        return msg, {}

    media = file_item.get("media") or {}
    encrypt_query_param = media.get("encrypt_query_param", "")
    aes_key_str = media.get("aes_key", "")

    if not encrypt_query_param or not aes_key_str:
        return f"[文件: {file_name}]", {}

    try:
        aes_key = weixin_crypto.parse_aes_key(aes_key_str)
        file_data = await weixin_cdn.download_and_decrypt(
            http_client, cdn_base_url, encrypt_query_param, aes_key,
        )
        file_b64 = base64.b64encode(file_data).decode("ascii")
        logger.info(f"[weixin] 文件下载成功: name={file_name}, size={len(file_data)}")
        return f"[文件: {file_name}]", {
            "_file_data": file_b64,
            "_file_name": file_name,
        }
    except Exception as e:
        logger.error(f"[weixin] 文件下载失败: {file_name}: {e}")
        return f"[文件: {file_name}]", {}


async def process_inbound_video(
    http_client: httpx.AsyncClient,
    cdn_base_url: str,
    video_item: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """处理入站视频消息，下载解密视频。

    Returns:
        (text, extra_data)
    """
    video_size = video_item.get("video_size", 0)
    try:
        video_size = int(video_size)
    except (ValueError, TypeError):
        video_size = 0
    if video_size > WEIXIN_MEDIA_MAX_BYTES:
        msg = f"[视频过大: {video_size / 1024 / 1024:.1f}MB 超过限制]"
        logger.warning(f"[weixin] {msg}")
        return msg, {}

    media = video_item.get("media") or {}
    encrypt_query_param = media.get("encrypt_query_param", "")
    aes_key_str = media.get("aes_key", "")

    if not encrypt_query_param or not aes_key_str:
        return "[视频消息]", {}

    try:
        aes_key = weixin_crypto.parse_aes_key(aes_key_str)
        video_data = await weixin_cdn.download_and_decrypt(
            http_client, cdn_base_url, encrypt_query_param, aes_key,
        )
        video_b64 = base64.b64encode(video_data).decode("ascii")
        logger.info(f"[weixin] 视频下载成功: size={len(video_data)}")
        return "[视频消息]", {"_video_data": video_b64}
    except Exception as e:
        logger.error(f"[weixin] 视频下载失败: {e}")
        return "[视频消息]", {}


async def process_inbound_media(
    http_client: httpx.AsyncClient,
    cdn_base_url: str,
    media_items: list[dict[str, Any]],
) -> tuple[str, list[str], dict[str, Any]]:
    """入站媒体调度函数，遍历 item_list 按类型分发处理。

    Returns:
        (text, images, extra_raw_data)
        - text: 文本内容 (合并文本项和语音转写)
        - images: base64 data URI 列表 (图片)
        - extra_raw_data: 额外数据 (语音/文件/视频原始数据)
    """
    texts: list[str] = []
    images: list[str] = []
    extra: dict[str, Any] = {}

    for item in media_items:
        item_type = item.get("type", 0)

        if item_type == 1:  # TEXT
            text_item = item.get("text_item") or {}
            t = text_item.get("text", "")
            if t:
                texts.append(t)

        elif item_type == 2:  # IMAGE
            image_item = item.get("image_item") or {}
            result = await process_inbound_image(http_client, cdn_base_url, image_item)
            if result.success and result.data:
                mime = result.media_type or "image/jpeg"
                b64 = base64.b64encode(result.data).decode("ascii")
                images.append(f"data:{mime};base64,{b64}")
            else:
                texts.append(f"[图片下载失败: {result.error}]")

        elif item_type == 3:  # VOICE
            voice_item = item.get("voice_item") or {}
            voice_text, voice_extra = await process_inbound_voice(
                http_client, cdn_base_url, voice_item,
            )
            if voice_text:
                texts.append(voice_text)
            extra.update(voice_extra)

        elif item_type == 4:  # FILE
            file_item = item.get("file_item") or {}
            file_text, file_extra = await process_inbound_file(
                http_client, cdn_base_url, file_item,
            )
            if file_text:
                texts.append(file_text)
            extra.update(file_extra)

        elif item_type == 5:  # VIDEO
            video_item = item.get("video_item") or {}
            video_text, video_extra = await process_inbound_video(
                http_client, cdn_base_url, video_item,
            )
            if video_text:
                texts.append(video_text)
            extra.update(video_extra)

    text = "\n".join(texts) if texts else ""
    return text, images, extra


# ============== 出站媒体处理 ==============


async def upload_media(
    http_client: httpx.AsyncClient,
    weixin_client: Any,
    cdn_base_url: str,
    to_user_id: str,
    data: bytes,
    media_type: WeixinMediaType,
    file_name: str = "",
) -> MediaUploadResult:
    """上传媒体文件到 CDN。

    流程: 生成 AES key → 计算 MD5 → getUploadUrl → encrypt+upload
    """
    import hashlib
    import os

    aes_key = os.urandom(16)
    aes_key_hex = aes_key.hex()
    raw_md5 = hashlib.md5(data).hexdigest()
    raw_size = len(data)
    cipher_size = weixin_crypto.aes_ecb_padded_size(raw_size)
    filekey = os.urandom(16).hex()

    logger.debug(
        f"[weixin] 媒体上传: type={media_type.name}, size={raw_size}, "
        f"cipher_size={cipher_size}, filekey={filekey}"
    )

    try:
        upload_resp = await weixin_client.get_upload_url(
            filekey=filekey,
            media_type=media_type.value,
            to_user_id=to_user_id,
            rawsize=raw_size,
            rawfilemd5=raw_md5,
            filesize=cipher_size,
            aeskey=aes_key_hex,
        )
    except Exception as e:
        logger.error(f"[weixin] getUploadUrl 失败: {e}")
        return MediaUploadResult(
            filekey="", download_encrypted_query_param="",
            aes_key_hex="", file_size=0, file_size_ciphertext=0,
            success=False, error=f"getUploadUrl 失败: {e}",
        )

    upload_param = upload_resp.get("upload_param", "")
    if not upload_param:
        err = "getUploadUrl 未返回 upload_param"
        logger.error(f"[weixin] {err}, resp={upload_resp}")
        return MediaUploadResult(
            filekey="", download_encrypted_query_param="",
            aes_key_hex="", file_size=0, file_size_ciphertext=0,
            success=False, error=err,
        )

    try:
        download_param = await weixin_cdn.encrypt_and_upload(
            http_client, cdn_base_url, upload_param, filekey, data, aes_key,
        )
    except Exception as e:
        logger.error(f"[weixin] CDN 上传失败: {e}")
        return MediaUploadResult(
            filekey="", download_encrypted_query_param="",
            aes_key_hex="", file_size=0, file_size_ciphertext=0,
            success=False, error=f"CDN 上传失败: {e}",
        )

    logger.info(f"[weixin] 媒体上传成功: filekey={filekey}, type={media_type.name}")
    return MediaUploadResult(
        filekey=filekey,
        download_encrypted_query_param=download_param,
        aes_key_hex=aes_key_hex,
        file_size=raw_size,
        file_size_ciphertext=cipher_size,
    )


def build_image_item(upload_result: MediaUploadResult) -> dict[str, Any]:
    """根据上传结果构建图片消息 item。"""
    return {
        "type": 2,
        "image_item": {
            "media": {
                "encrypt_query_param": upload_result.download_encrypted_query_param,
                "aes_key": base64.b64encode(
                    upload_result.aes_key_hex.encode("ascii")
                ).decode("ascii"),
                "encrypt_type": 1,
            },
            "mid_size": upload_result.file_size_ciphertext,
            "hd_size": upload_result.file_size_ciphertext,
        },
    }


def build_file_item(
    upload_result: MediaUploadResult, file_name: str,
) -> dict[str, Any]:
    """根据上传结果构建文件消息 item。"""
    return {
        "type": 4,
        "file_item": {
            "media": {
                "encrypt_query_param": upload_result.download_encrypted_query_param,
                "aes_key": base64.b64encode(
                    upload_result.aes_key_hex.encode("ascii")
                ).decode("ascii"),
                "encrypt_type": 1,
            },
            "file_name": file_name,
            "len": str(upload_result.file_size),
        },
    }


def build_video_item(upload_result: MediaUploadResult) -> dict[str, Any]:
    """根据上传结果构建视频消息 item。"""
    return {
        "type": 5,
        "video_item": {
            "media": {
                "encrypt_query_param": upload_result.download_encrypted_query_param,
                "aes_key": base64.b64encode(
                    upload_result.aes_key_hex.encode("ascii")
                ).decode("ascii"),
                "encrypt_type": 1,
            },
            "video_size": upload_result.file_size_ciphertext,
        },
    }


# ============== 内部工具 ==============


def _detect_image_mime(data: bytes) -> str:
    """通过文件头魔术字节检测图片 MIME 类型。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"\x00\x00\x00\x1c" or data[:4] == b"\x00\x00\x00\x18":
        return "image/heic"
    return "image/jpeg"  # default fallback
