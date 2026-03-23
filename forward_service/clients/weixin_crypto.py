"""
AES-128-ECB 加解密工具

用于微信 CDN 媒体文件的加密上传和解密下载。
算法: AES-128-ECB + PKCS7 padding

密钥格式说明:
- 入站图片: image_item.aeskey 为 hex 字符串 (32 hex chars → 16 bytes)
- 入站语音/文件/视频: media.aes_key 为 base64 编码
  - base64 decode 后 16 字节 → 直接使用
  - base64 decode 后 32 字节且全为 hex 字符 → hex decode 得到 16 字节
- 出站: 随机生成 16 字节 key，hex 编码传给 getuploadurl API

参考: TypeScript SDK cdn/aes-ecb.ts, cdn/pic-decrypt.ts::parseAesKey
"""
import base64
import logging
import re

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

logger = logging.getLogger(__name__)

AES_BLOCK_SIZE = 16
_HEX_32_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def encrypt_aes_ecb(plaintext: bytes, key: bytes) -> bytes:
    """AES-128-ECB 加密 (PKCS7 padding)。"""
    if len(key) != AES_BLOCK_SIZE:
        raise ValueError(f"AES key must be {AES_BLOCK_SIZE} bytes, got {len(key)}")
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(pad(plaintext, AES_BLOCK_SIZE))


def decrypt_aes_ecb(ciphertext: bytes, key: bytes) -> bytes:
    """AES-128-ECB 解密 (PKCS7 unpadding)。"""
    if len(key) != AES_BLOCK_SIZE:
        raise ValueError(f"AES key must be {AES_BLOCK_SIZE} bytes, got {len(key)}")
    if len(ciphertext) % AES_BLOCK_SIZE != 0:
        raise ValueError(
            f"Ciphertext length must be a multiple of {AES_BLOCK_SIZE}, "
            f"got {len(ciphertext)}"
        )
    cipher = AES.new(key, AES.MODE_ECB)
    return unpad(cipher.decrypt(ciphertext), AES_BLOCK_SIZE)


def aes_ecb_padded_size(plaintext_size: int) -> int:
    """计算 AES-128-ECB PKCS7 padding 后的密文大小。

    PKCS7 padding 总是添加至少 1 字节，因此:
    plaintext_size=0  → 16
    plaintext_size=15 → 16
    plaintext_size=16 → 32
    """
    return ((plaintext_size + 1 + AES_BLOCK_SIZE - 1) // AES_BLOCK_SIZE) * AES_BLOCK_SIZE


def parse_aes_key(raw_key_str: str) -> bytes:
    """解析 CDN 媒体的 AES key，支持多种编码格式自动检测。

    支持的格式:
    1. 32 字符 hex 字符串 (image_item.aeskey) → hex decode → 16 bytes
    2. base64(raw 16 bytes) → base64 decode → 16 bytes
    3. base64(hex string of 16 bytes) → base64 decode → 32 ASCII hex → hex decode → 16 bytes

    Args:
        raw_key_str: 原始 key 字符串

    Returns:
        16 字节 AES key

    Raises:
        ValueError: 无法解析为有效的 16 字节 key
    """
    if not raw_key_str:
        raise ValueError("AES key string is empty")

    # Format 1: 32-char hex string (image_item.aeskey)
    if len(raw_key_str) == 32 and _HEX_32_RE.match(raw_key_str):
        return bytes.fromhex(raw_key_str)

    # Format 2 & 3: base64-encoded
    try:
        decoded = base64.b64decode(raw_key_str)
    except Exception as e:
        raise ValueError(f"Cannot base64-decode AES key: {e}") from e

    if len(decoded) == AES_BLOCK_SIZE:
        return decoded

    # Format 3: base64(hex string) — decoded is 32 bytes of ASCII hex chars
    if len(decoded) == 32:
        try:
            ascii_str = decoded.decode("ascii")
        except UnicodeDecodeError:
            pass
        else:
            if _HEX_32_RE.match(ascii_str):
                return bytes.fromhex(ascii_str)

    raise ValueError(
        f"AES key must decode to {AES_BLOCK_SIZE} raw bytes or 32-char hex string, "
        f"got {len(decoded)} bytes (input='{raw_key_str[:20]}...')"
    )
