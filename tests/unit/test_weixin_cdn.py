"""CDN 媒体操作模块单元测试"""
import os
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from forward_service.clients.weixin_cdn import (
    download_and_decrypt,
    encrypt_and_upload,
)
from forward_service.clients.weixin_crypto import encrypt_aes_ecb


CDN_BASE = "https://test-cdn.example.com/c2c"


@pytest.fixture
def aes_key() -> bytes:
    return os.urandom(16)


@pytest.fixture
def mock_http() -> AsyncMock:
    return AsyncMock(spec=httpx.AsyncClient)


class TestDownloadAndDecrypt:
    """CDN 下载+解密"""

    @pytest.mark.asyncio
    async def test_success(self, mock_http: AsyncMock, aes_key: bytes) -> None:
        plaintext = b"hello image data" * 100
        ciphertext = encrypt_aes_ecb(plaintext, aes_key)

        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.content = ciphertext
        resp.raise_for_status = MagicMock()
        mock_http.get.return_value = resp

        result = await download_and_decrypt(
            mock_http, CDN_BASE, "test-param", aes_key,
        )

        assert result == plaintext
        mock_http.get.assert_called_once()
        call_url = mock_http.get.call_args[0][0]
        assert "test-param" in call_url

    @pytest.mark.asyncio
    async def test_timeout(self, mock_http: AsyncMock, aes_key: bytes) -> None:
        mock_http.get.side_effect = httpx.ReadTimeout("timeout")
        with pytest.raises(httpx.ReadTimeout):
            await download_and_decrypt(mock_http, CDN_BASE, "p", aes_key)

    @pytest.mark.asyncio
    async def test_404(self, mock_http: AsyncMock, aes_key: bytes) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 404
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=resp,
        )
        mock_http.get.return_value = resp
        with pytest.raises(httpx.HTTPStatusError):
            await download_and_decrypt(mock_http, CDN_BASE, "p", aes_key)


class TestEncryptAndUpload:
    """CDN 加密+上传"""

    @pytest.mark.asyncio
    async def test_success(self, mock_http: AsyncMock, aes_key: bytes) -> None:
        plaintext = b"file data to upload"
        download_param = "dl-param-123"

        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {"x-encrypted-param": download_param}
        resp.raise_for_status = MagicMock()
        mock_http.post.return_value = resp

        result = await encrypt_and_upload(
            mock_http, CDN_BASE, "upload-param", "filekey1",
            plaintext, aes_key,
        )

        assert result == download_param
        mock_http.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout_retries(
        self, mock_http: AsyncMock, aes_key: bytes,
    ) -> None:
        mock_http.post.side_effect = httpx.ReadTimeout("timeout")
        with pytest.raises(httpx.ReadTimeout):
            await encrypt_and_upload(
                mock_http, CDN_BASE, "up", "fk", b"data", aes_key,
            )
        assert mock_http.post.call_count == 3  # UPLOAD_MAX_RETRIES

    @pytest.mark.asyncio
    async def test_client_error_no_retry(
        self, mock_http: AsyncMock, aes_key: bytes,
    ) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 400
        resp.headers = {"x-error-message": "bad request"}
        resp.text = "bad request"
        resp.request = MagicMock()
        resp.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
            "400", request=resp.request, response=resp,
        ))
        mock_http.post.return_value = resp

        with pytest.raises(httpx.HTTPStatusError):
            await encrypt_and_upload(
                mock_http, CDN_BASE, "up", "fk", b"data", aes_key,
            )
        assert mock_http.post.call_count == 1

    @pytest.mark.asyncio
    async def test_missing_header_retries(
        self, mock_http: AsyncMock, aes_key: bytes,
    ) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {}  # missing x-encrypted-param
        resp.raise_for_status = MagicMock()
        mock_http.post.return_value = resp

        with pytest.raises(RuntimeError, match="x-encrypted-param"):
            await encrypt_and_upload(
                mock_http, CDN_BASE, "up", "fk", b"data", aes_key,
            )
        assert mock_http.post.call_count == 3
