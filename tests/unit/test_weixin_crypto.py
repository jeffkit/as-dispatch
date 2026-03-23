"""AES-128-ECB 加解密模块单元测试"""
import base64
import os

import pytest

from forward_service.clients.weixin_crypto import (
    aes_ecb_padded_size,
    decrypt_aes_ecb,
    encrypt_aes_ecb,
    parse_aes_key,
)


class TestEncryptDecryptRoundtrip:
    """加密-解密往返测试"""

    def test_roundtrip_short(self) -> None:
        key = os.urandom(16)
        plaintext = b"hello world"
        ciphertext = encrypt_aes_ecb(plaintext, key)
        assert decrypt_aes_ecb(ciphertext, key) == plaintext

    def test_roundtrip_block_aligned(self) -> None:
        key = os.urandom(16)
        plaintext = b"x" * 16
        ciphertext = encrypt_aes_ecb(plaintext, key)
        assert decrypt_aes_ecb(ciphertext, key) == plaintext

    def test_roundtrip_large(self) -> None:
        key = os.urandom(16)
        plaintext = os.urandom(10000)
        ciphertext = encrypt_aes_ecb(plaintext, key)
        assert decrypt_aes_ecb(ciphertext, key) == plaintext

    def test_roundtrip_empty(self) -> None:
        key = os.urandom(16)
        plaintext = b""
        ciphertext = encrypt_aes_ecb(plaintext, key)
        assert decrypt_aes_ecb(ciphertext, key) == plaintext


class TestPKCS7Padding:
    """PKCS7 padding 正确性"""

    def test_ciphertext_length_is_block_aligned(self) -> None:
        key = os.urandom(16)
        for size in [0, 1, 15, 16, 17, 31, 32, 100]:
            ct = encrypt_aes_ecb(b"a" * size, key)
            assert len(ct) % 16 == 0

    def test_ciphertext_size_matches_padded_size(self) -> None:
        key = os.urandom(16)
        for size in [0, 1, 15, 16, 17, 31, 32]:
            ct = encrypt_aes_ecb(b"a" * size, key)
            assert len(ct) == aes_ecb_padded_size(size)


class TestAesEcbPaddedSize:
    """密文大小计算"""

    def test_empty(self) -> None:
        assert aes_ecb_padded_size(0) == 16

    def test_one_byte(self) -> None:
        assert aes_ecb_padded_size(1) == 16

    def test_fifteen_bytes(self) -> None:
        assert aes_ecb_padded_size(15) == 16

    def test_block_aligned(self) -> None:
        assert aes_ecb_padded_size(16) == 32

    def test_seventeen_bytes(self) -> None:
        assert aes_ecb_padded_size(17) == 32


class TestParseAesKey:
    """AES key 解析"""

    def test_hex_format(self) -> None:
        raw_key = os.urandom(16)
        hex_str = raw_key.hex()
        assert parse_aes_key(hex_str) == raw_key

    def test_base64_raw_16_bytes(self) -> None:
        raw_key = os.urandom(16)
        b64_str = base64.b64encode(raw_key).decode()
        assert parse_aes_key(b64_str) == raw_key

    def test_base64_hex_in_base64(self) -> None:
        """base64(hex string of 16 bytes) — 语音/文件/视频常见格式"""
        raw_key = os.urandom(16)
        hex_str = raw_key.hex()  # 32 ASCII hex chars
        b64_str = base64.b64encode(hex_str.encode("ascii")).decode()
        assert parse_aes_key(b64_str) == raw_key

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            parse_aes_key("")

    def test_invalid_base64_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_aes_key("not-valid-base64!!!")

    def test_wrong_length_raises(self) -> None:
        bad = base64.b64encode(b"x" * 20).decode()
        with pytest.raises(ValueError, match="must decode to"):
            parse_aes_key(bad)


class TestErrorHandling:
    """异常处理"""

    def test_wrong_key_length_encrypt(self) -> None:
        with pytest.raises(ValueError, match="must be 16 bytes"):
            encrypt_aes_ecb(b"data", b"short")

    def test_wrong_key_length_decrypt(self) -> None:
        with pytest.raises(ValueError, match="must be 16 bytes"):
            decrypt_aes_ecb(b"x" * 16, b"short")

    def test_ciphertext_not_block_aligned(self) -> None:
        with pytest.raises(ValueError, match="multiple of 16"):
            decrypt_aes_ecb(b"x" * 15, os.urandom(16))

    def test_wrong_key_decrypt_raises(self) -> None:
        key1 = os.urandom(16)
        key2 = os.urandom(16)
        ct = encrypt_aes_ecb(b"hello", key1)
        with pytest.raises(ValueError):
            decrypt_aes_ecb(ct, key2)
