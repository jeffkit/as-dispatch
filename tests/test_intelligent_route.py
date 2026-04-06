"""
企业微信智能机器人路由集成测试
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from forward_service.config import AccessControl, BotConfig, ForwardConfig


def create_mock_bot(
    name: str = "测试智能机器人",
    bot_key: str = "test-bot",
    platform: str = "wecom-intelligent",
    url: str = "https://api.test.com/messages",
) -> BotConfig:
    forward_config = ForwardConfig(target_url=url, api_key="test_api_key", timeout=60)
    access_control = AccessControl(mode="allow_all", whitelist=[], blacklist=[])
    bot = BotConfig(
        name=name,
        bot_key=bot_key,
        enabled=True,
        forward_config=forward_config,
        access_control=access_control,
    )
    bot.platform = platform
    return bot


@pytest.fixture
def mock_config():
    with patch("forward_service.routes.intelligent.config") as cfg:
        cfg.get_bot_or_default.return_value = create_mock_bot()
        cfg.timeout = 60
        yield cfg


@pytest.fixture
def mock_session_manager():
    sm = MagicMock()
    sm.get_active_session = AsyncMock(return_value=None)
    sm.parse_slash_command = MagicMock(return_value=None)
    sm.record_session = AsyncMock()
    sm.list_sessions = AsyncMock(return_value=[])
    sm.format_session_list = MagicMock(return_value="📋 会话列表\n\n暂无活跃会话")
    sm.reset_session = AsyncMock(return_value=True)
    sm.change_session = AsyncMock(return_value=None)
    return sm


def _post_xml(client: TestClient, bot_key: str, xml: str):
    return client.post(
        f"/callback/intelligent/{bot_key}",
        content=xml,
        headers={"Content-Type": "text/xml"},
    )


class TestIntelligentRoute:
    def test_intelligent_callback_success(self, mock_config, mock_session_manager):
        with (
            patch(
                "forward_service.routes.intelligent.get_session_manager",
                return_value=mock_session_manager,
            ),
            patch(
                "forward_service.routes.intelligent.forward_to_agent_with_user_project",
                new_callable=AsyncMock,
                return_value=MagicMock(reply="你好！我是智能助手", session_id="new_session_456"),
            ) as mock_forward,
        ):
            mock_session = MagicMock()
            mock_session.session_id = "session_123"
            mock_session.current_project_id = None
            mock_session_manager.get_active_session.return_value = mock_session
            mock_session_manager.parse_slash_command.return_value = None

            from forward_service.app import app

            client = TestClient(app)
            response = _post_xml(
                client,
                "test-bot",
                """<xml>
<ToUserName><![CDATA[ww123]]></ToUserName>
<FromUserName><![CDATA[user123]]></FromUserName>
<CreateTime>1234567890</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[你好]]></Content>
<MsgId>1234567890123456</MsgId>
</xml>""",
            )

        assert response.status_code == 200
        assert "application/xml" in response.headers["content-type"]
        assert "<MsgType><![CDATA[stream]]></MsgType>" in response.text
        assert "你好！我是智能助手" in response.text
        mock_forward.assert_awaited_once()
        mock_session_manager.record_session.assert_awaited_once()

    def test_intelligent_callback_slash_command(self, mock_config, mock_session_manager):
        with (
            patch(
                "forward_service.routes.intelligent.get_session_manager",
                return_value=mock_session_manager,
            ),
            patch(
                "forward_service.routes.intelligent.forward_to_agent_with_user_project",
                new_callable=AsyncMock,
            ) as mock_forward,
        ):
            mock_session_manager.parse_slash_command.return_value = ("reset", None, None)
            mock_session_manager.reset_session.return_value = True

            from forward_service.app import app

            client = TestClient(app)
            response = _post_xml(
                client,
                "test-bot",
                """<xml>
<ToUserName><![CDATA[ww123]]></ToUserName>
<FromUserName><![CDATA[user123]]></FromUserName>
<CreateTime>1234567890</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[/reset]]></Content>
<MsgId>123</MsgId>
</xml>""",
            )

        assert response.status_code == 200
        assert "<MsgType><![CDATA[text]]></MsgType>" in response.text
        assert "会话已重置" in response.text
        mock_forward.assert_not_awaited()

    def test_intelligent_callback_wrong_platform(self, mock_config, mock_session_manager):
        with patch(
            "forward_service.routes.intelligent.get_session_manager",
            return_value=mock_session_manager,
        ):
            mock_config.get_bot_or_default.return_value.platform = "discord"
            from forward_service.app import app

            client = TestClient(app)
            response = _post_xml(
                client,
                "test-bot",
                """<xml>
<ToUserName><![CDATA[ww123]]></ToUserName>
<FromUserName><![CDATA[user123]]></FromUserName>
<CreateTime>1234567890</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[hello]]></Content>
<MsgId>123</MsgId>
</xml>""",
            )

        assert response.status_code == 200
        assert "机器人类型错误" in response.text

    def test_intelligent_callback_bot_not_found(self, mock_config, mock_session_manager):
        with patch(
            "forward_service.routes.intelligent.get_session_manager",
            return_value=mock_session_manager,
        ):
            mock_config.get_bot_or_default.return_value = None
            from forward_service.app import app

            client = TestClient(app)
            response = _post_xml(
                client,
                "non-existent-bot",
                """<xml>
<ToUserName><![CDATA[ww123]]></ToUserName>
<FromUserName><![CDATA[user123]]></FromUserName>
<CreateTime>1234567890</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[hello]]></Content>
<MsgId>123</MsgId>
</xml>""",
            )

        assert response.status_code == 200
        assert "机器人配置错误" in response.text

    def test_intelligent_callback_non_text_message(self, mock_config, mock_session_manager):
        with patch(
            "forward_service.routes.intelligent.get_session_manager",
            return_value=mock_session_manager,
        ):
            from forward_service.app import app

            client = TestClient(app)
            response = _post_xml(
                client,
                "test-bot",
                """<xml>
<ToUserName><![CDATA[ww123]]></ToUserName>
<FromUserName><![CDATA[user123]]></FromUserName>
<CreateTime>1234567890</CreateTime>
<MsgType><![CDATA[event]]></MsgType>
<Event><![CDATA[enter_session]]></Event>
</xml>""",
            )

        assert response.status_code == 200
        assert response.text == ""

    def test_intelligent_callback_invalid_xml(self):
        from forward_service.app import app

        client = TestClient(app)
        response = _post_xml(client, "test-bot", "not a valid xml")

        assert response.status_code == 200
        assert "服务器错误" in response.text or "xml" in response.text.lower()


class TestIntelligentCommand:
    @pytest.mark.asyncio
    async def test_command_list_sessions(self, mock_session_manager):
        from forward_service.routes.intelligent import handle_intelligent_command

        mock_session_manager.list_sessions.return_value = []
        mock_session_manager.format_session_list.return_value = "📋 会话列表\n\n暂无活跃会话"

        reply = await handle_intelligent_command(
            session_mgr=mock_session_manager,
            from_user="user123",
            bot=MagicMock(bot_key="test-bot"),
            cmd_type="list",
            cmd_arg=None,
            extra_msg=None,
            session_key="intelligent:user123",
            current_session_id=None,
        )

        assert "会话列表" in reply
        mock_session_manager.list_sessions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_command_reset_session(self, mock_session_manager):
        from forward_service.routes.intelligent import handle_intelligent_command

        mock_session_manager.reset_session.return_value = True
        reply = await handle_intelligent_command(
            session_mgr=mock_session_manager,
            from_user="user123",
            bot=MagicMock(bot_key="test-bot"),
            cmd_type="reset",
            cmd_arg=None,
            extra_msg=None,
            session_key="intelligent:user123",
            current_session_id="session_001",
        )

        assert "会话已重置" in reply
        mock_session_manager.reset_session.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_command_change_session(self, mock_session_manager):
        from forward_service.routes.intelligent import handle_intelligent_command

        target_session = MagicMock()
        target_session.short_id = "abc123"
        target_session.last_message = "上次的消息"
        mock_session_manager.change_session.return_value = target_session

        reply = await handle_intelligent_command(
            session_mgr=mock_session_manager,
            from_user="user123",
            bot=MagicMock(bot_key="test-bot"),
            cmd_type="change",
            cmd_arg="abc123",
            extra_msg=None,
            session_key="intelligent:user123",
            current_session_id="session_001",
        )

        assert "已切换到会话" in reply
        assert "abc123" in reply
        mock_session_manager.change_session.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_command_change_session_not_found(self, mock_session_manager):
        from forward_service.routes.intelligent import handle_intelligent_command

        mock_session_manager.change_session.return_value = None
        reply = await handle_intelligent_command(
            session_mgr=mock_session_manager,
            from_user="user123",
            bot=MagicMock(bot_key="test-bot"),
            cmd_type="change",
            cmd_arg="nonexistent",
            extra_msg=None,
            session_key="intelligent:user123",
            current_session_id=None,
        )

        assert "未找到会话" in reply
        assert "nonexistent" in reply

    @pytest.mark.asyncio
    async def test_command_unknown(self, mock_session_manager):
        from forward_service.routes.intelligent import handle_intelligent_command

        reply = await handle_intelligent_command(
            session_mgr=mock_session_manager,
            from_user="user123",
            bot=MagicMock(bot_key="test-bot"),
            cmd_type="unknown",
            cmd_arg=None,
            extra_msg=None,
            session_key="intelligent:user123",
            current_session_id=None,
        )

        assert "未知命令" in reply
