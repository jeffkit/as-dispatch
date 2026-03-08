"""
SlackAdapter 单元测试

测试覆盖：
- parse_inbound: 正常路径（文本/图片文件）
- send_outbound: 成功 + 失败（mocked SlackClient）
- should_ignore: 重试请求头 / Bot 消息
- get_verification_response: url_verification payload
- extract_bot_key: 从 api_app_id
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

from forward_service.channel.slack import SlackAdapter
from forward_service.channel.base import OutboundMessage


# ============== Fixtures ==============

@pytest.fixture
def adapter():
    return SlackAdapter()


def make_slack_event(
    api_app_id: str = "A123456",
    user_id: str = "U999",
    channel: str = "C123",
    channel_type: str = "channel",
    event_type: str = "message",
    text: str = "Hello Slack",
    bot_id: str = None,
    subtype: str = None,
    files: list = None,
    retry_num: str = None,
) -> dict:
    event = {
        "type": event_type,
        "user": user_id,
        "channel": channel,
        "channel_type": channel_type,
        "text": text,
        "ts": "1700000000.000001",
    }
    if bot_id:
        event["bot_id"] = bot_id
    if subtype:
        event["subtype"] = subtype
    if files:
        event["files"] = files

    headers = {}
    if retry_num is not None:
        headers["x-slack-retry-num"] = retry_num

    return {
        "type": "event_callback",
        "api_app_id": api_app_id,
        "event": event,
        "_request_headers": headers,
    }


# ============== get_verification_response 测试 ==============

def test_get_verification_response_url_verification(adapter):
    payload = {"type": "url_verification", "challenge": "xyz789", "token": "tok"}
    resp = adapter.get_verification_response(payload)
    assert resp == {"challenge": "xyz789"}


def test_get_verification_response_non_verification(adapter):
    payload = {"type": "event_callback"}
    assert adapter.get_verification_response(payload) is None


def test_get_verification_response_missing_challenge(adapter):
    payload = {"type": "url_verification"}
    assert adapter.get_verification_response(payload) is None


# ============== should_ignore 测试 ==============

def test_should_ignore_retry_header(adapter):
    raw = make_slack_event(retry_num="1")
    assert adapter.should_ignore(raw) is True


def test_should_ignore_url_verification(adapter):
    raw = {"type": "url_verification", "_request_headers": {}}
    assert adapter.should_ignore(raw) is True


def test_should_ignore_bot_id(adapter):
    raw = make_slack_event(bot_id="B123")
    assert adapter.should_ignore(raw) is True


def test_should_ignore_bot_message_subtype(adapter):
    raw = make_slack_event(subtype="bot_message")
    assert adapter.should_ignore(raw) is True


def test_should_not_ignore_user_message(adapter):
    raw = make_slack_event()
    assert adapter.should_ignore(raw) is False


# ============== extract_bot_key 测试 ==============

def test_extract_bot_key_from_api_app_id(adapter):
    raw = make_slack_event(api_app_id="A_MY_APP")
    assert adapter.extract_bot_key(raw) == "A_MY_APP"


def test_extract_bot_key_missing(adapter):
    raw = {"_request_headers": {}}
    assert adapter.extract_bot_key(raw) is None


# ============== parse_inbound 测试 ==============

@pytest.mark.asyncio
async def test_parse_inbound_text_message(adapter):
    raw = make_slack_event(text="Hello Slack!", user_id="U001", channel="C001")
    inbound = await adapter.parse_inbound(raw)

    assert inbound.platform == "slack"
    assert inbound.text == "Hello Slack!"
    assert inbound.user_id == "U001"
    assert inbound.chat_id == "C001"
    assert inbound.msg_type == "text"
    assert inbound.images == []
    assert inbound.bot_key == "A123456"


@pytest.mark.asyncio
async def test_parse_inbound_with_image_files(adapter):
    files = [
        {
            "mimetype": "image/png",
            "url_private_download": "https://files.slack.com/img.png",
            "url_private": "https://files.slack.com/priv/img.png",
        }
    ]
    raw = make_slack_event(text="See image", files=files)
    inbound = await adapter.parse_inbound(raw)

    assert inbound.msg_type == "mixed"
    assert len(inbound.images) == 1
    assert "img.png" in inbound.images[0]


@pytest.mark.asyncio
async def test_parse_inbound_image_only(adapter):
    files = [{"mimetype": "image/jpeg", "url_private_download": "https://files.slack.com/img.jpg"}]
    raw = make_slack_event(text="", files=files)
    inbound = await adapter.parse_inbound(raw)
    assert inbound.msg_type == "image"


@pytest.mark.asyncio
async def test_parse_inbound_raises_on_missing_event(adapter):
    raw = {"_request_headers": {}, "api_app_id": "A123"}
    with pytest.raises(ValueError, match="event"):
        await adapter.parse_inbound(raw)


@pytest.mark.asyncio
async def test_parse_inbound_raises_on_missing_user(adapter):
    raw = make_slack_event(user_id="")
    with pytest.raises(ValueError, match="user"):
        await adapter.parse_inbound(raw)


@pytest.mark.asyncio
async def test_parse_inbound_direct_message(adapter):
    raw = make_slack_event(channel_type="im")
    inbound = await adapter.parse_inbound(raw)
    assert inbound.chat_type == "direct"


@pytest.mark.asyncio
async def test_parse_inbound_channel_message(adapter):
    raw = make_slack_event(channel_type="channel")
    inbound = await adapter.parse_inbound(raw)
    assert inbound.chat_type == "group"


# ============== send_outbound 测试 ==============

@pytest.mark.asyncio
async def test_send_outbound_success(adapter):
    mock_client = AsyncMock()
    mock_client.post_message = AsyncMock(return_value={"ok": True})

    outbound = OutboundMessage(chat_id="C001", text="Reply!", bot_key="A123456")

    with patch.object(adapter, "_get_client", return_value=mock_client):
        result = await adapter.send_outbound(outbound)

    assert result.success is True
    assert result.parts_sent == 1
    mock_client.post_message.assert_called_once_with(channel="C001", text="Reply!")


@pytest.mark.asyncio
async def test_send_outbound_no_client(adapter):
    outbound = OutboundMessage(chat_id="C001", text="Reply!", bot_key="unknown")
    with patch.object(adapter, "_get_client", return_value=None):
        result = await adapter.send_outbound(outbound)
    assert result.success is False
    assert "SlackClient" in result.error


@pytest.mark.asyncio
async def test_send_outbound_api_error(adapter):
    mock_client = AsyncMock()
    mock_client.post_message = AsyncMock(side_effect=Exception("channel_not_found"))

    outbound = OutboundMessage(chat_id="C001", text="Reply!", bot_key="A123456")

    with patch.object(adapter, "_get_client", return_value=mock_client):
        result = await adapter.send_outbound(outbound)

    assert result.success is False
    assert "channel_not_found" in result.error


# ============== platform 属性测试 ==============

def test_platform_name(adapter):
    assert adapter.platform == "slack"
