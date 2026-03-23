"""
微信 CDN 媒体操作模块

负责 CDN 文件的下载解密和加密上传。
所有加解密操作委托给 weixin_crypto.py。

CDN URL 格式:
- 下载: {cdnBaseUrl}/download?encrypted_query_param={param}
- 上传: {cdnBaseUrl}/upload?encrypted_query_param={uploadParam}&filekey={filekey}

参考: TypeScript SDK cdn/pic-decrypt.ts, cdn/cdn-upload.ts, cdn/cdn-url.ts
"""
import logging
from urllib.parse import quote

import httpx

from . import weixin_crypto

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = 60.0
UPLOAD_TIMEOUT = 60.0
UPLOAD_MAX_RETRIES = 3


def _build_download_url(cdn_base_url: str, encrypt_query_param: str) -> str:
    return f"{cdn_base_url}/download?encrypted_query_param={quote(encrypt_query_param)}"


def _build_upload_url(
    cdn_base_url: str, upload_param: str, filekey: str,
) -> str:
    return (
        f"{cdn_base_url}/upload?"
        f"encrypted_query_param={quote(upload_param)}&filekey={quote(filekey)}"
    )


async def download_and_decrypt(
    http_client: httpx.AsyncClient,
    cdn_base_url: str,
    encrypt_query_param: str,
    aes_key: bytes,
) -> bytes:
    """从 CDN 下载并 AES-128-ECB 解密媒体文件。

    Args:
        http_client: httpx AsyncClient 实例
        cdn_base_url: CDN 基础 URL
        encrypt_query_param: 加密查询参数
        aes_key: 16 字节 AES key (已解析)

    Returns:
        解密后的明文字节

    Raises:
        httpx.HTTPStatusError: HTTP 请求失败
        ValueError: 解密失败
    """
    url = _build_download_url(cdn_base_url, encrypt_query_param)
    logger.debug(f"[weixin-cdn] 下载: url={url[:80]}...")

    resp = await http_client.get(url, timeout=DOWNLOAD_TIMEOUT)
    resp.raise_for_status()

    encrypted = resp.content
    logger.debug(f"[weixin-cdn] 下载完成: {len(encrypted)} bytes, 开始解密")

    decrypted = weixin_crypto.decrypt_aes_ecb(encrypted, aes_key)
    logger.debug(f"[weixin-cdn] 解密完成: {len(decrypted)} bytes")
    return decrypted


async def encrypt_and_upload(
    http_client: httpx.AsyncClient,
    cdn_base_url: str,
    upload_param: str,
    filekey: str,
    plaintext: bytes,
    aes_key: bytes,
) -> str:
    """加密并上传文件到 CDN。

    Args:
        http_client: httpx AsyncClient 实例
        cdn_base_url: CDN 基础 URL
        upload_param: getUploadUrl 返回的 upload_param
        filekey: 文件标识
        plaintext: 明文数据
        aes_key: 16 字节 AES key

    Returns:
        download_encrypted_query_param (用于后续下载)

    Raises:
        httpx.HTTPStatusError: HTTP 请求失败
        RuntimeError: 上传后未获取到 download param
    """
    ciphertext = weixin_crypto.encrypt_aes_ecb(plaintext, aes_key)
    url = _build_upload_url(cdn_base_url, upload_param, filekey)
    logger.debug(
        f"[weixin-cdn] 上传: url={url[:80]}... ciphertext={len(ciphertext)} bytes"
    )

    download_param: str | None = None
    last_error: Exception | None = None

    for attempt in range(1, UPLOAD_MAX_RETRIES + 1):
        try:
            resp = await http_client.post(
                url,
                content=ciphertext,
                headers={"Content-Type": "application/octet-stream"},
                timeout=UPLOAD_TIMEOUT,
            )

            if 400 <= resp.status_code < 500:
                err_msg = resp.headers.get("x-error-message", resp.text)
                raise httpx.HTTPStatusError(
                    f"CDN upload client error {resp.status_code}: {err_msg}",
                    request=resp.request,
                    response=resp,
                )

            resp.raise_for_status()

            download_param = resp.headers.get("x-encrypted-param")
            if not download_param:
                raise RuntimeError(
                    "CDN upload response missing x-encrypted-param header"
                )

            logger.debug(f"[weixin-cdn] 上传成功: attempt={attempt}")
            break

        except httpx.HTTPStatusError as e:
            if 400 <= e.response.status_code < 500:
                raise
            last_error = e
            if attempt < UPLOAD_MAX_RETRIES:
                logger.warning(
                    f"[weixin-cdn] 上传失败 attempt={attempt}, 重试: {e}"
                )
            else:
                logger.error(
                    f"[weixin-cdn] 上传失败 {UPLOAD_MAX_RETRIES} 次: {e}"
                )
        except Exception as e:
            last_error = e  # type: ignore[assignment]
            if attempt < UPLOAD_MAX_RETRIES:
                logger.warning(
                    f"[weixin-cdn] 上传异常 attempt={attempt}, 重试: {e}"
                )
            else:
                logger.error(
                    f"[weixin-cdn] 上传异常 {UPLOAD_MAX_RETRIES} 次: {e}"
                )

    if not download_param:
        raise last_error or RuntimeError(
            f"CDN upload failed after {UPLOAD_MAX_RETRIES} attempts"
        )

    return download_param
