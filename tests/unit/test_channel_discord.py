"""
DiscordAdapter 单元测试

测试覆盖：
- parse_inbound: 正常路径（文本/图片附件）
- send_outbound: 成功 + 分拆 + 失败（mocked DiscordBotClient）
- should_ignore: Bot 消息
- extract_bot_key: 从 kwargs / raw_data
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if 'pigeon' not in sys.modules:
    sys.modules['pigeon'] = MagicMock()

pkg_root = Path(__file__).parent.parent.parent
if str(pkg_root) not in sys.path:
    sys.path.insert(0, str(pkg_root))

from forward_service.channel.discord import DiscordAdapter
from forward_service.channel.base import OutboundMessage


# ============== Fixtures ==============

@pytest.fixture
def adapter():
    return DiscordAdapter()


def make_discord_raw(
    message_id: str = "111",
    content: str = "Hello Discord",
    author_id: str = "999",
    author_name: str = "TestUser#1234",
    author_is_bot: bool = False,
    channel_id: str = "dm:999",
    channel_type: str = "dm",
    attachments: list = None,
    bot_key: str = "discord-bot-key",
) -> dict:
    return {
        "message_id": message_id,
        "content": content,
        "author_id": author_id,
        "author_name": author_name,
        "author_is_bot": author_is_bot,
        "channel_id": channel_id,
        "channel_type": channel_type,
        "attachments": attachments or [],
        "_bot_key": bot_key,
    }


# ============== extract_bot_key 测试 ==============

def test_extract_bot_key_from_kwargs(adapter):
    raw = {}
    assert adapter.extract_bot_key(raw, bot_key="mykey") == "mykey"


def test_extract_bot_key_from_raw_data(adapter):
    raw = {"_bot_key": "raw-key"}
    assert adapter.extract_bot_key(raw) == "raw-key"


def test_extract_bot_key_missing(adapter):
    raw = {}
    assert adapter.extract_bot_key(raw) is None


# ============== should_ignore 测试 ==============

def test_should_ignore_bot_author(adapter):
    raw = make_discord_raw(author_is_bot=True)
    assert adapter.should_ignore(raw) is True


def test_should_not_ignore_human_author(adapter):
    raw = make_discord_raw(author_is_bot=False)
    assert adapter.should_ignore(raw) is False


# ============== parse_inbound 测试 ==============

@pytest.mark.asyncio
async def test_parse_inbound_text_message(adapter):
    raw = make_discord_raw(content="Hello!", author_id="123", channel_id="dm:123")
    inbound = await adapter.parse_inbound(raw, bot_key="bot-key")

    assert inbound.platform == "discord"
    assert inbound.text == "Hello!"
    assert inbound.user_id == "123"
    assert inbound.chat_id == "dm:123"
    assert inbound.msg_type == "text"
    assert inbound.images == []
    # kwargs["bot_key"] 优先于 raw_data["_bot_key"]
    assert inbound.bot_key == "bot-key"


@pytest.mark.asyncio
async def test_parse_inbound_with_image_attachment(adapter):
    attachments = [
        {"url": "https://cdn.discord.com/img.png", "content_type": "image/png", "filename": "img.png"},
    ]
    raw = make_discord_raw(content="Check this", attachments=attachments)
    inbound = await adapter.parse_inbound(raw)

    assert inbound.msg_type == "mixed"
    assert len(inbound.images) == 1
    assert "img.png" in inbound.images[0]


@pytest.mark.asyncio
async def test_parse_inbound_image_only(adapter):
    attachments = [
        {"url": "https://cdn.discord.com/img.jpg", "content_type": "image/jpeg", "filename": "img.jpg"},
    ]
    raw = make_discord_raw(content="", attachments=attachments)
    inbound = await adapter.parse_inbound(raw)
    assert inbound.msg_type == "image"


@pytest.mark.asyncio
async def test_parse_inbound_raises_on_empty(adapter):
    raw = make_discord_raw(content="", attachments=[])
    with pytest.raises(ValueError, match="内容为空"):
        await adapter.parse_inbound(raw)


@pytest.mark.asyncio
async def test_parse_inbound_dm_chat_type(adapter):
    raw = make_discord_raw(channel_type="dm")
    inbound = await adapter.parse_inbound(raw)
    assert inbound.chat_type == "direct"


@pytest.mark.asyncio
async def test_parse_inbound_group_chat_type(adapter):
    raw = make_discord_raw(channel_type="text", channel_id="123456")
    inbound = await adapter.parse_inbound(raw)
    assert inbound.chat_type == "group"


# ============== send_outbound 测试 ==============

@pytest.mark.asyncio
async def test_send_outbound_success(adapter):
    mock_msg = MagicMock()
    mock_client = AsyncMock()
    mock_client.send_dm = AsyncMock(return_value=mock_msg)

    outbound = OutboundMessage(chat_id="dm:999", text="Hi there!", bot_key="discord-key")

    with patch.object(adapter, "_get_bot_client", return_value=mock_client):
        result = await adapter.send_outbound(outbound)

    assert result.success is True
    assert result.parts_sent == 1
    mock_client.send_dm.assert_called_once_with(user_id=999, content="Hi there!")


@pytest.mark.asyncio
async def test_send_outbound_no_client(adapter):
    outbound = OutboundMessage(chat_id="dm:999", text="Hi!", bot_key="unknown")
    with patch.object(adapter, "_get_bot_client", return_value=None):
        result = await adapter.send_outbound(outbound)
    assert result.success is False
    assert "DiscordBotClient" in result.error


@pytest.mark.asyncio
async def test_send_outbound_api_error(adapter):
    mock_client = AsyncMock()
    mock_client.send_dm = AsyncMock(side_effect=Exception("Forbidden"))

    outbound = OutboundMessage(chat_id="dm:999", text="Hi!", bot_key="discord-key")

    with patch.object(adapter, "_get_bot_client", return_value=mock_client):
        result = await adapter.send_outbound(outbound)

    assert result.success is False
    assert "Forbidden" in result.error


@pytest.mark.asyncio
async def test_send_outbound_long_message_splits(adapter):
    mock_msg = MagicMock()
    mock_client = AsyncMock()
    mock_client.send_dm = AsyncMock(return_value=mock_msg)

    long_text = "A" * 5000  # 超过 2000 字符
    outbound = OutboundMessage(chat_id="dm:999", text=long_text, bot_key="discord-key")

    with patch.object(adapter, "_get_bot_client", return_value=mock_client):
        result = await adapter.send_outbound(outbound)

    assert result.success is True
    assert result.parts_sent >= 3
    assert mock_client.send_dm.call_count >= 3


@pytest.mark.asyncio
async def test_send_outbound_send_dm_returns_none(adapter):
    mock_client = AsyncMock()
    mock_client.send_dm = AsyncMock(return_value=None)

    outbound = OutboundMessage(chat_id="dm:999", text="Hi!", bot_key="discord-key")

    with patch.object(adapter, "_get_bot_client", return_value=mock_client):
        result = await adapter.send_outbound(outbound)

    assert result.success is False


# ============== platform 属性测试 ==============

def test_platform_name(adapter):
    assert adapter.platform == "discord"
