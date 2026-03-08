"""
LarkAdapter 单元测试

测试覆盖：
- parse_inbound: 正常路径（文本/图片）+ 解密失败
- send_outbound: 成功 + 失败（mocked LarkClient）
- get_verification_response: url_verification payload
- should_ignore: sender_type == "bot"（app）/ URL 验证
"""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if 'pigeon' not in sys.modules:
    sys.modules['pigeon'] = MagicMock()

pkg_root = Path(__file__).parent.parent.parent
if str(pkg_root) not in sys.path:
    sys.path.insert(0, str(pkg_root))

from forward_service.channel.lark import LarkAdapter
from forward_service.channel.base import OutboundMessage


# ============== Fixtures ==============

@pytest.fixture
def adapter():
    return LarkAdapter()


def make_lark_event(
    app_id: str = "cli_test123",
    event_type: str = "im.message.receive_v1",
    open_id: str = "ou_testuser",
    chat_id: str = "oc_testchat",
    chat_type: str = "group",
    message_type: str = "text",
    content_text: str = "Hello",
    sender_type: str = "user",
    message_id: str = "om_test123",
) -> dict:
    """构建飞书事件 dict"""
    content = json.dumps({"text": content_text}) if message_type == "text" else json.dumps({})
    return {
        "schema": "2.0",
        "header": {
            "event_id": "ev_test",
            "event_type": event_type,
            "create_time": "1700000000000",
            "app_id": app_id,
        },
        "event": {
            "sender": {
                "sender_id": {
                    "open_id": open_id,
                    "user_id": "u_testuser",
                },
                "sender_type": sender_type,
            },
            "message": {
                "message_id": message_id,
                "message_type": message_type,
                "chat_id": chat_id,
                "chat_type": chat_type,
                "content": content,
            },
        },
    }


# ============== get_verification_response 测试 ==============

def test_get_verification_response_url_verification(adapter):
    payload = {"type": "url_verification", "challenge": "abc123", "token": "mytoken"}
    resp = adapter.get_verification_response(payload)
    assert resp == {"challenge": "abc123"}


def test_get_verification_response_non_verification(adapter):
    payload = {"type": "event_callback"}
    resp = adapter.get_verification_response(payload)
    assert resp is None


def test_get_verification_response_missing_challenge(adapter):
    payload = {"type": "url_verification"}
    resp = adapter.get_verification_response(payload)
    assert resp is None


# ============== should_ignore 测试 ==============

def test_should_ignore_url_verification(adapter):
    raw = {"type": "url_verification"}
    assert adapter.should_ignore(raw) is True


def test_should_ignore_bot_sender(adapter):
    raw = make_lark_event(sender_type="app")
    assert adapter.should_ignore(raw) is True


def test_should_not_ignore_user_message(adapter):
    raw = make_lark_event(sender_type="user")
    assert adapter.should_ignore(raw) is False


def test_should_ignore_non_message_event(adapter):
    raw = make_lark_event(event_type="contact.user.updated_v3")
    assert adapter.should_ignore(raw) is True


# ============== extract_bot_key 测试 ==============

def test_extract_bot_key_from_header(adapter):
    raw = make_lark_event(app_id="cli_myapp")
    assert adapter.extract_bot_key(raw) == "cli_myapp"


def test_extract_bot_key_from_root_app_id(adapter):
    raw = {"app_id": "cli_root_app"}
    assert adapter.extract_bot_key(raw) == "cli_root_app"


def test_extract_bot_key_missing(adapter):
    raw = {}
    assert adapter.extract_bot_key(raw) is None


# ============== parse_inbound 测试 ==============

@pytest.mark.asyncio
async def test_parse_inbound_text_message(adapter):
    raw = make_lark_event(content_text="Hello Lark", open_id="ou_user1", chat_id="oc_chat1")

    with patch.object(adapter, "_decrypt_if_needed", return_value=raw):
        inbound = await adapter.parse_inbound(raw)

    assert inbound.platform == "lark"
    assert inbound.text == "Hello Lark"
    assert inbound.user_id == "ou_user1"
    assert inbound.chat_id == "oc_chat1"
    assert inbound.msg_type == "text"
    assert inbound.images == []


@pytest.mark.asyncio
async def test_parse_inbound_image_message(adapter):
    raw = make_lark_event(message_type="image")
    raw["event"]["message"]["content"] = json.dumps({"image_key": "img_key_abc"})

    with patch.object(adapter, "_decrypt_if_needed", return_value=raw):
        inbound = await adapter.parse_inbound(raw)

    assert inbound.msg_type == "image"
    assert "img_key_abc" in inbound.images


@pytest.mark.asyncio
async def test_parse_inbound_raises_on_missing_open_id(adapter):
    raw = make_lark_event()
    raw["event"]["sender"]["sender_id"]["open_id"] = ""
    raw["event"]["sender"]["sender_id"]["user_id"] = ""

    with patch.object(adapter, "_decrypt_if_needed", return_value=raw):
        with pytest.raises(ValueError, match="open_id"):
            await adapter.parse_inbound(raw)


@pytest.mark.asyncio
async def test_parse_inbound_group_chat(adapter):
    raw = make_lark_event(chat_type="group")
    with patch.object(adapter, "_decrypt_if_needed", return_value=raw):
        inbound = await adapter.parse_inbound(raw)
    assert inbound.chat_type == "group"


@pytest.mark.asyncio
async def test_parse_inbound_direct_chat(adapter):
    raw = make_lark_event(chat_type="p2p")
    with patch.object(adapter, "_decrypt_if_needed", return_value=raw):
        inbound = await adapter.parse_inbound(raw)
    assert inbound.chat_type == "direct"


# ============== send_outbound 测试 ==============

@pytest.mark.asyncio
async def test_send_outbound_success(adapter):
    mock_client = AsyncMock()
    mock_client.send_text = AsyncMock(return_value={"data": {}})

    outbound = OutboundMessage(chat_id="oc_chat1", text="Reply!", bot_key="cli_app1")

    with patch.object(adapter, "_get_client", return_value=mock_client):
        result = await adapter.send_outbound(outbound)

    assert result.success is True
    assert result.parts_sent == 1
    mock_client.send_text.assert_called_once_with(
        receive_id="oc_chat1",
        text="Reply!",
        receive_id_type="chat_id",
    )


@pytest.mark.asyncio
async def test_send_outbound_no_client(adapter):
    outbound = OutboundMessage(chat_id="oc_chat1", text="Reply!", bot_key="unknown")
    with patch.object(adapter, "_get_client", return_value=None):
        result = await adapter.send_outbound(outbound)
    assert result.success is False
    assert "LarkClient" in result.error


@pytest.mark.asyncio
async def test_send_outbound_api_error(adapter):
    mock_client = AsyncMock()
    mock_client.send_text = AsyncMock(side_effect=Exception("Token expired"))

    outbound = OutboundMessage(chat_id="oc_chat1", text="Reply!", bot_key="cli_app1")

    with patch.object(adapter, "_get_client", return_value=mock_client):
        result = await adapter.send_outbound(outbound)

    assert result.success is False
    assert "Token expired" in result.error


# ============== platform 属性测试 ==============

def test_platform_name(adapter):
    assert adapter.platform == "lark"
