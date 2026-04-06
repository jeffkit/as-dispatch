"""微信多媒体消息处理单元测试"""
import base64
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from forward_service.clients.weixin_crypto import encrypt_aes_ecb
from forward_service.channel.weixin_media import (
    DEFAULT_CDN_BASE_URL,
    WEIXIN_MEDIA_MAX_BYTES,
    MediaUploadResult,
    WeixinMediaType,
    build_file_item,
    build_image_item,
    build_video_item,
    process_inbound_file,
    process_inbound_image,
    process_inbound_media,
    process_inbound_video,
    process_inbound_voice,
    upload_media,
)


CDN_BASE = "https://test-cdn.example.com/c2c"


@pytest.fixture
def aes_key() -> bytes:
    return os.urandom(16)


@pytest.fixture
def mock_http() -> AsyncMock:
    return AsyncMock(spec=httpx.AsyncClient)


def _make_cdn_response(plaintext: bytes, aes_key: bytes) -> MagicMock:
    """Create a mock httpx response with encrypted content."""
    ciphertext = encrypt_aes_ecb(plaintext, aes_key)
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.content = ciphertext
    resp.raise_for_status = MagicMock()
    return resp


# ============== Phase 3: US1 — 入站图片 ==============


class TestProcessInboundImage:
    """process_inbound_image 测试"""

    @pytest.mark.asyncio
    async def test_success_with_hex_aeskey(
        self, mock_http: AsyncMock, aes_key: bytes,
    ) -> None:
        plaintext = b"\xff\xd8\xff\xe0" + b"jpeg data" * 100
        mock_http.get.return_value = _make_cdn_response(plaintext, aes_key)

        image_item = {
            "aeskey": aes_key.hex(),
            "media": {"encrypt_query_param": "test-param"},
        }
        result = await process_inbound_image(mock_http, CDN_BASE, image_item)

        assert result.success
        assert result.data == plaintext
        assert result.media_type == "image/jpeg"

    @pytest.mark.asyncio
    async def test_success_with_base64_media_key(
        self, mock_http: AsyncMock, aes_key: bytes,
    ) -> None:
        plaintext = b"\x89PNG\r\n\x1a\n" + b"png data" * 100
        mock_http.get.return_value = _make_cdn_response(plaintext, aes_key)

        image_item = {
            "media": {
                "encrypt_query_param": "test-param",
                "aes_key": base64.b64encode(aes_key).decode(),
            },
        }
        result = await process_inbound_image(mock_http, CDN_BASE, image_item)

        assert result.success
        assert result.data == plaintext
        assert result.media_type == "image/png"

    @pytest.mark.asyncio
    async def test_missing_encrypt_param(self, mock_http: AsyncMock) -> None:
        image_item = {"media": {}}
        result = await process_inbound_image(mock_http, CDN_BASE, image_item)
        assert not result.success
        assert "encrypt_query_param" in result.error

    @pytest.mark.asyncio
    async def test_missing_aes_key(self, mock_http: AsyncMock) -> None:
        image_item = {"media": {"encrypt_query_param": "p"}}
        result = await process_inbound_image(mock_http, CDN_BASE, image_item)
        assert not result.success
        assert "AES key" in result.error

    @pytest.mark.asyncio
    async def test_download_failure(
        self, mock_http: AsyncMock, aes_key: bytes,
    ) -> None:
        mock_http.get.side_effect = httpx.ReadTimeout("timeout")
        image_item = {
            "aeskey": aes_key.hex(),
            "media": {"encrypt_query_param": "p"},
        }
        result = await process_inbound_image(mock_http, CDN_BASE, image_item)
        assert not result.success
        assert "下载解密失败" in result.error


class TestProcessInboundMediaImages:
    """process_inbound_media 图片分支测试"""

    @pytest.mark.asyncio
    async def test_image_to_data_uri(
        self, mock_http: AsyncMock, aes_key: bytes,
    ) -> None:
        plaintext = b"\xff\xd8\xff\xe0" + b"jpeg data" * 50
        mock_http.get.return_value = _make_cdn_response(plaintext, aes_key)

        items = [{
            "type": 2,
            "image_item": {
                "aeskey": aes_key.hex(),
                "media": {"encrypt_query_param": "p"},
            },
        }]
        text, images, extra = await process_inbound_media(
            mock_http, CDN_BASE, items,
        )

        assert len(images) == 1
        assert images[0].startswith("data:image/jpeg;base64,")
        b64_data = images[0].split(",", 1)[1]
        assert base64.b64decode(b64_data) == plaintext

    @pytest.mark.asyncio
    async def test_image_download_fail_fallback(
        self, mock_http: AsyncMock, aes_key: bytes,
    ) -> None:
        mock_http.get.side_effect = httpx.ReadTimeout("timeout")
        items = [{
            "type": 2,
            "image_item": {
                "aeskey": aes_key.hex(),
                "media": {"encrypt_query_param": "p"},
            },
        }]
        text, images, extra = await process_inbound_media(
            mock_http, CDN_BASE, items,
        )

        assert len(images) == 0
        assert "图片下载失败" in text


# ============== Phase 5: US3 — 入站语音 ==============


class TestProcessInboundVoice:
    """process_inbound_voice 测试"""

    @pytest.mark.asyncio
    async def test_transcribed_text(self, mock_http: AsyncMock) -> None:
        voice_item = {"text": "你好世界", "media": {}}
        text, extra = await process_inbound_voice(mock_http, CDN_BASE, voice_item)
        assert text == "你好世界"
        assert extra == {}

    @pytest.mark.asyncio
    async def test_voice_to_text_field(self, mock_http: AsyncMock) -> None:
        voice_item = {"voice_to_text": "语音转文字内容", "media": {}}
        text, extra = await process_inbound_voice(mock_http, CDN_BASE, voice_item)
        assert text == "语音转文字内容"

    @pytest.mark.asyncio
    async def test_download_voice_fallback(
        self, mock_http: AsyncMock, aes_key: bytes,
    ) -> None:
        voice_data = b"silk encoded audio data" * 10
        mock_http.get.return_value = _make_cdn_response(voice_data, aes_key)

        voice_item = {
            "media": {
                "encrypt_query_param": "p",
                "aes_key": base64.b64encode(aes_key).decode(),
            },
        }
        text, extra = await process_inbound_voice(mock_http, CDN_BASE, voice_item)
        assert text == "[语音消息]"
        assert "_voice_data" in extra

    @pytest.mark.asyncio
    async def test_download_failure_fallback(
        self, mock_http: AsyncMock, aes_key: bytes,
    ) -> None:
        mock_http.get.side_effect = httpx.ReadTimeout("timeout")
        voice_item = {
            "media": {
                "encrypt_query_param": "p",
                "aes_key": base64.b64encode(aes_key).decode(),
            },
        }
        text, extra = await process_inbound_voice(mock_http, CDN_BASE, voice_item)
        assert text == "[语音消息]"
        assert "_voice_data" not in extra


# ============== Phase 6: US4 — 文件收发 ==============


class TestProcessInboundFile:
    """process_inbound_file 测试"""

    @pytest.mark.asyncio
    async def test_success(
        self, mock_http: AsyncMock, aes_key: bytes,
    ) -> None:
        file_data = b"PDF file content" * 100
        mock_http.get.return_value = _make_cdn_response(file_data, aes_key)

        file_item = {
            "file_name": "report.pdf",
            "len": str(len(file_data)),
            "media": {
                "encrypt_query_param": "p",
                "aes_key": base64.b64encode(aes_key).decode(),
            },
        }
        text, extra = await process_inbound_file(mock_http, CDN_BASE, file_item)
        assert text == "[文件: report.pdf]"
        assert extra["_file_name"] == "report.pdf"
        assert "_file_data" in extra

    @pytest.mark.asyncio
    async def test_file_too_large(self, mock_http: AsyncMock) -> None:
        file_item = {
            "file_name": "huge.bin",
            "len": str(WEIXIN_MEDIA_MAX_BYTES + 1),
            "media": {"encrypt_query_param": "p", "aes_key": "abc"},
        }
        text, extra = await process_inbound_file(mock_http, CDN_BASE, file_item)
        assert "文件过大" in text
        assert extra == {}

    @pytest.mark.asyncio
    async def test_file_name_preserved(
        self, mock_http: AsyncMock, aes_key: bytes,
    ) -> None:
        mock_http.get.return_value = _make_cdn_response(b"data", aes_key)
        file_item = {
            "file_name": "合同 v2.docx",
            "len": "100",
            "media": {
                "encrypt_query_param": "p",
                "aes_key": base64.b64encode(aes_key).decode(),
            },
        }
        text, extra = await process_inbound_file(mock_http, CDN_BASE, file_item)
        assert "合同 v2.docx" in text
        assert extra["_file_name"] == "合同 v2.docx"


class TestBuildFileItem:
    """build_file_item 结构测试"""

    def test_structure(self) -> None:
        result = MediaUploadResult(
            filekey="fk1",
            download_encrypted_query_param="dl-param",
            aes_key_hex="aa" * 16,
            file_size=1024,
            file_size_ciphertext=1040,
        )
        item = build_file_item(result, "doc.pdf")
        assert item["type"] == 4
        assert item["file_item"]["file_name"] == "doc.pdf"
        assert item["file_item"]["len"] == "1024"
        assert item["file_item"]["media"]["encrypt_query_param"] == "dl-param"


# ============== Phase 7: US5 — 视频收发 ==============


class TestProcessInboundVideo:
    """process_inbound_video 测试"""

    @pytest.mark.asyncio
    async def test_success(
        self, mock_http: AsyncMock, aes_key: bytes,
    ) -> None:
        video_data = b"mp4 video content" * 100
        mock_http.get.return_value = _make_cdn_response(video_data, aes_key)

        video_item = {
            "media": {
                "encrypt_query_param": "p",
                "aes_key": base64.b64encode(aes_key).decode(),
            },
        }
        text, extra = await process_inbound_video(mock_http, CDN_BASE, video_item)
        assert text == "[视频消息]"
        assert "_video_data" in extra

    @pytest.mark.asyncio
    async def test_download_failure(
        self, mock_http: AsyncMock, aes_key: bytes,
    ) -> None:
        mock_http.get.side_effect = httpx.ReadTimeout("timeout")
        video_item = {
            "media": {
                "encrypt_query_param": "p",
                "aes_key": base64.b64encode(aes_key).decode(),
            },
        }
        text, extra = await process_inbound_video(mock_http, CDN_BASE, video_item)
        assert text == "[视频消息]"
        assert "_video_data" not in extra


class TestBuildVideoItem:
    """build_video_item 结构测试"""

    def test_structure(self) -> None:
        result = MediaUploadResult(
            filekey="fk1",
            download_encrypted_query_param="dl-param",
            aes_key_hex="bb" * 16,
            file_size=5000,
            file_size_ciphertext=5008,
        )
        item = build_video_item(result)
        assert item["type"] == 5
        assert item["video_item"]["video_size"] == 5008
        assert item["video_item"]["media"]["encrypt_query_param"] == "dl-param"


# ============== Phase 4: US2 — 出站图片 ==============


class TestUploadMedia:
    """upload_media 测试"""

    @pytest.mark.asyncio
    async def test_success(self, mock_http: AsyncMock) -> None:
        mock_client = AsyncMock()
        mock_client.get_upload_url.return_value = {"upload_param": "up-123"}

        upload_resp = MagicMock(spec=httpx.Response)
        upload_resp.status_code = 200
        upload_resp.headers = {"x-encrypted-param": "dl-param-456"}
        upload_resp.raise_for_status = MagicMock()
        mock_http.post.return_value = upload_resp

        result = await upload_media(
            mock_http, mock_client, CDN_BASE,
            "user1", b"image data" * 100, WeixinMediaType.IMAGE,
        )

        assert result.success
        assert result.download_encrypted_query_param == "dl-param-456"
        assert result.file_size == len(b"image data" * 100)
        mock_client.get_upload_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_upload_url_failure(self, mock_http: AsyncMock) -> None:
        mock_client = AsyncMock()
        mock_client.get_upload_url.side_effect = Exception("API error")

        result = await upload_media(
            mock_http, mock_client, CDN_BASE,
            "user1", b"data", WeixinMediaType.IMAGE,
        )

        assert not result.success
        assert "getUploadUrl" in result.error

    @pytest.mark.asyncio
    async def test_missing_upload_param(self, mock_http: AsyncMock) -> None:
        mock_client = AsyncMock()
        mock_client.get_upload_url.return_value = {}  # no upload_param

        result = await upload_media(
            mock_http, mock_client, CDN_BASE,
            "user1", b"data", WeixinMediaType.IMAGE,
        )

        assert not result.success
        assert "upload_param" in result.error


class TestBuildImageItem:
    """build_image_item 结构测试"""

    def test_structure(self) -> None:
        result = MediaUploadResult(
            filekey="fk1",
            download_encrypted_query_param="dl-param",
            aes_key_hex="cc" * 16,
            file_size=2048,
            file_size_ciphertext=2064,
        )
        item = build_image_item(result)
        assert item["type"] == 2
        assert item["image_item"]["mid_size"] == 2064
        assert item["image_item"]["hd_size"] == 2064
        assert item["image_item"]["media"]["encrypt_query_param"] == "dl-param"
        assert item["image_item"]["media"]["encrypt_type"] == 1
