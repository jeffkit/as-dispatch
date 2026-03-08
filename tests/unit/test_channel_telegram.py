"""
TelegramAdapter 单元测试

测试覆盖：
- parse_inbound: 正常路径（文本/图片）+ ValueError on missing message
- send_outbound: 成功 + 失败（mocked TelegramClient）
- should_ignore: Bot 作者消息
- extract_bot_key: 从请求头提取
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 确保 pigeon 不会导入失败
if 'pigeon' not in sys.modules:
    sys.modules['pigeon'] = MagicMock()

# 添加包路径
pkg_root = Path(__file__).parent.parent.parent
if str(pkg_root) not in sys.path:
    sys.path.insert(0, str(pkg_root))

from forward_service.channel.telegram import TelegramAdapter
from forward_service.channel.base import OutboundMessage


# ============== Fixtures ==============

@pytest.fixture
def adapter():
    return TelegramAdapter()


def make_update(
    message_id: int = 1,
    user_id: int = 12345,
    first_name: str = "Test",
    last_name: str = "User",
    is_bot: bool = False,
    chat_id: int = -100,
    chat_type: str = "group",
    text: str = "hello",
    photos: list = None,
    secret_token: str = "test-bot-key",
) -> dict:
    """构建 Telegram Update dict"""
    raw = {
        "update_id": 100,
        "message": {
            "message_id": message_id,
            "from": {
                "id": user_id,
                "first_name": first_name,
                "last_name": last_name,
                "is_bot": is_bot,
            },
            "chat": {
                "id": chat_id,
                "type": chat_type,
            },
            "text": text,
        },
        "_request_headers": {
            "x-telegram-bot-api-secret-token": secret_token,
        },
    }
    if photos:
        raw["message"]["photo"] = photos
        del raw["message"]["text"]
    return raw


# ============== extract_bot_key 测试 ==============

def test_extract_bot_key_from_headers(adapter):
    raw = {"_request_headers": {"x-telegram-bot-api-secret-token": "my-secret-key"}}
    assert adapter.extract_bot_key(raw) == "my-secret-key"


def test_extract_bot_key_missing_header(adapter):
    raw = {"_request_headers": {}}
    assert adapter.extract_bot_key(raw) is None


def test_extract_bot_key_no_headers(adapter):
    raw = {}
    assert adapter.extract_bot_key(raw) is None


# ============== should_ignore 测试 ==============

def test_should_ignore_bot_author(adapter):
    raw = make_update(is_bot=True)
    assert adapter.should_ignore(raw) is True


def test_should_not_ignore_human_author(adapter):
    raw = make_update(is_bot=False)
    assert adapter.should_ignore(raw) is False


def test_should_ignore_no_message(adapter):
    raw = {"_request_headers": {}}
    assert adapter.should_ignore(raw) is True


# ============== parse_inbound 测试 ==============

@pytest.mark.asyncio
async def test_parse_inbound_text_message(adapter):
    raw = make_update(text="Hello World", secret_token="mykey")
    inbound = await adapter.parse_inbound(raw)

    assert inbound.platform == "telegram"
    assert inbound.bot_key == "mykey"
    assert inbound.text == "Hello World"
    assert inbound.user_id == "12345"
    assert inbound.chat_id == "-100"
    assert inbound.msg_type == "text"
    assert inbound.images == []


@pytest.mark.asyncio
async def test_parse_inbound_private_chat_type(adapter):
    raw = make_update(chat_type="private", chat_id=99999)
    inbound = await adapter.parse_inbound(raw)
    assert inbound.chat_type == "direct"


@pytest.mark.asyncio
async def test_parse_inbound_group_chat_type(adapter):
    raw = make_update(chat_type="group")
    inbound = await adapter.parse_inbound(raw)
    assert inbound.chat_type == "group"


@pytest.mark.asyncio
async def test_parse_inbound_with_photo(adapter):
    photos = [
        {"file_id": "small_id", "file_size": 100, "width": 50, "height": 50},
        {"file_id": "large_id", "file_size": 5000, "width": 800, "height": 600},
    ]
    raw = make_update(photos=photos, secret_token="key123")
    raw["message"]["caption"] = "Nice photo"

    mock_client = AsyncMock()
    mock_client.get_file_url = AsyncMock(return_value="https://api.telegram.org/file/botTOKEN/photos/large.jpg")

    with patch.object(adapter, "_get_client", return_value=mock_client):
        inbound = await adapter.parse_inbound(raw)

    assert inbound.msg_type == "mixed"
    assert len(inbound.images) == 1
    assert "large.jpg" in inbound.images[0]
    assert inbound.text == "Nice photo"
    mock_client.get_file_url.assert_called_once_with("large_id")


@pytest.mark.asyncio
async def test_parse_inbound_raises_on_missing_message(adapter):
    raw = {"_request_headers": {"x-telegram-bot-api-secret-token": "key"}}
    with pytest.raises(ValueError, match="无 message 字段"):
        await adapter.parse_inbound(raw)


# ============== send_outbound 测试 ==============

@pytest.mark.asyncio
async def test_send_outbound_success(adapter):
    mock_client = AsyncMock()
    mock_client.send_message = AsyncMock(return_value={"ok": True})

    outbound = OutboundMessage(chat_id="12345", text="Hello!", bot_key="test-key")

    with patch.object(adapter, "_get_client", return_value=mock_client):
        result = await adapter.send_outbound(outbound)

    assert result.success is True
    assert result.parts_sent == 1
    mock_client.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_outbound_no_client(adapter):
    outbound = OutboundMessage(chat_id="12345", text="Hello!", bot_key="nonexistent")

    with patch.object(adapter, "_get_client", return_value=None):
        result = await adapter.send_outbound(outbound)

    assert result.success is False
    assert "TelegramClient" in result.error


@pytest.mark.asyncio
async def test_send_outbound_api_error(adapter):
    mock_client = AsyncMock()
    mock_client.send_message = AsyncMock(side_effect=Exception("Network error"))

    outbound = OutboundMessage(chat_id="12345", text="Hello!", bot_key="test-key")

    with patch.object(adapter, "_get_client", return_value=mock_client):
        result = await adapter.send_outbound(outbound)

    assert result.success is False
    assert "Network error" in result.error


@pytest.mark.asyncio
async def test_send_outbound_long_message_splits(adapter):
    mock_client = AsyncMock()
    mock_client.send_message = AsyncMock(return_value={"ok": True})

    long_text = "A" * 9000  # 超过 4096 字符
    outbound = OutboundMessage(chat_id="12345", text=long_text, bot_key="test-key")

    with patch.object(adapter, "_get_client", return_value=mock_client):
        result = await adapter.send_outbound(outbound)

    assert result.success is True
    assert result.parts_sent >= 2
    assert mock_client.send_message.call_count >= 2


# ============== platform 属性测试 ==============

def test_platform_name(adapter):
    assert adapter.platform == "telegram"
