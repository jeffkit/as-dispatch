"""
callback.py 回调处理单元测试

测试 handle_callback 函数及其相关逻辑
"""
import pytest
import pytest_asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import Request
from fastapi.testclient import TestClient

from forward_service.config import BotConfig, ForwardConfig, AccessControl


class TestCallbackProjectCommands:
    """测试回调中的项目命令处理"""

    @pytest.mark.asyncio
    async def test_project_command_detection(self, mock_db_manager):
        """测试检测项目命令"""
        from forward_service.routes.project_commands import is_project_command

        # 各种项目命令都应该被检测到
        assert is_project_command("/add-project test https://api.test.com")
        assert is_project_command("/list-projects")
        assert is_project_command("/use test")
        assert is_project_command("/set-default test")
        assert is_project_command("/remove-project test")
        assert is_project_command("/current-project")

        # 非项目命令不应该被检测
        assert not is_project_command("/help")
        assert not is_project_command("/reset")
        assert not is_project_command("hello world")


class TestCallbackSlashCommands:
    """测试回调中的 Slash 命令解析"""

    @pytest.fixture
    def session_manager(self, mock_db_manager):
        """创建 SessionManager 实例"""
        from forward_service.session_manager import SessionManager
        return SessionManager(mock_db_manager)

    def test_parse_session_commands(self, session_manager):
        """测试会话管理命令解析"""
        # /sess 或 /s - 列出会话
        result = session_manager.parse_slash_command("/sess")
        assert result is not None
        assert result[0] == "list"

        result = session_manager.parse_slash_command("/s")
        assert result is not None
        assert result[0] == "list"

        # /reset 或 /r - 重置会话
        result = session_manager.parse_slash_command("/reset")
        assert result is not None
        assert result[0] == "reset"

        result = session_manager.parse_slash_command("/r")
        assert result is not None
        assert result[0] == "reset"

        # /change 或 /c - 切换会话
        result = session_manager.parse_slash_command("/c abc12345")
        assert result is not None
        assert result[0] == "change"
        assert result[1] == "abc12345"

        # /c 不带参数 - 显示帮助
        result = session_manager.parse_slash_command("/c")
        assert result is not None
        assert result[0] == "change_help"

        # /c 带无效参数 - 显示错误
        result = session_manager.parse_slash_command("/c xyz")
        assert result is not None
        assert result[0] == "change_invalid"
        assert result[1] == "xyz"

        # /change 不带参数
        result = session_manager.parse_slash_command("/change")
        assert result is not None
        assert result[0] == "change_help"

    def test_parse_admin_commands(self, session_manager):
        """测试管理员命令解析"""
        # /ping
        result = session_manager.parse_slash_command("/ping")
        assert result is not None
        assert result[0] == "ping"

        # /status
        result = session_manager.parse_slash_command("/status")
        assert result is not None
        assert result[0] == "status"

        # /help
        result = session_manager.parse_slash_command("/help")
        assert result is not None
        assert result[0] == "help"

        # /bots
        result = session_manager.parse_slash_command("/bots")
        assert result is not None
        assert result[0] == "bots"

        # /pending
        result = session_manager.parse_slash_command("/pending")
        assert result is not None
        assert result[0] == "pending"

        # /recent
        result = session_manager.parse_slash_command("/recent")
        assert result is not None
        assert result[0] == "recent"

        # /errors
        result = session_manager.parse_slash_command("/errors")
        assert result is not None
        assert result[0] == "errors"

        # /health
        result = session_manager.parse_slash_command("/health")
        assert result is not None
        assert result[0] == "health"


class TestCallbackBotAccess:
    """测试回调中的 Bot 访问控制"""

    def test_check_access_allow_all(self):
        """测试 allow_all 模式"""
        from forward_service.config import ConfigDB

        config = ConfigDB()
        bot = BotConfig(
            bot_key="bot1",
            name="Test Bot",
            access_control=AccessControl(mode="allow_all"),
            enabled=True
        )

        allowed, reason = config.check_access(bot, "any_user")
        assert allowed is True
        assert reason == ""

    def test_check_access_whitelist_allowed(self):
        """测试白名单允许"""
        from forward_service.config import ConfigDB

        config = ConfigDB()
        bot = BotConfig(
            bot_key="bot1",
            name="Test Bot",
            access_control=AccessControl(
                mode="whitelist",
                whitelist=["user123", "user456"]
            ),
            enabled=True
        )

        allowed, reason = config.check_access(bot, "user123")
        assert allowed is True

    def test_check_access_whitelist_denied(self):
        """测试白名单拒绝"""
        from forward_service.config import ConfigDB

        config = ConfigDB()
        bot = BotConfig(
            bot_key="bot1",
            name="Test Bot",
            access_control=AccessControl(
                mode="whitelist",
                whitelist=["user123"]
            ),
            enabled=True
        )

        allowed, reason = config.check_access(bot, "other_user")
        assert allowed is False
        assert "没有权限" in reason

    def test_check_access_blacklist_allowed(self):
        """测试黑名单允许"""
        from forward_service.config import ConfigDB

        config = ConfigDB()
        bot = BotConfig(
            bot_key="bot1",
            name="Test Bot",
            access_control=AccessControl(
                mode="blacklist",
                blacklist=["bad_user"]
            ),
            enabled=True
        )

        allowed, reason = config.check_access(bot, "good_user")
        assert allowed is True

    def test_check_access_blacklist_denied(self):
        """测试黑名单拒绝"""
        from forward_service.config import ConfigDB

        config = ConfigDB()
        bot = BotConfig(
            bot_key="bot1",
            name="Test Bot",
            access_control=AccessControl(
                mode="blacklist",
                blacklist=["bad_user"]
            ),
            enabled=True
        )

        allowed, reason = config.check_access(bot, "bad_user")
        assert allowed is False

    def test_check_access_disabled_bot(self):
        """测试禁用的 Bot"""
        from forward_service.config import ConfigDB

        config = ConfigDB()
        bot = BotConfig(
            bot_key="bot1",
            name="Test Bot",
            access_control=AccessControl(mode="allow_all"),
            enabled=False
        )

        allowed, reason = config.check_access(bot, "any_user")
        assert allowed is False
        assert "禁用" in reason

    def test_check_access_with_alias(self):
        """测试使用别名检查白名单"""
        from forward_service.config import ConfigDB

        config = ConfigDB()
        bot = BotConfig(
            bot_key="bot1",
            name="Test Bot",
            access_control=AccessControl(
                mode="whitelist",
                whitelist=["user_alias"]
            ),
            enabled=True
        )

        # 使用别名检查
        allowed, reason = config.check_access(bot, "user_id", alias="user_alias")
        assert allowed is True

    def test_check_access_with_chat_id(self):
        """测试使用 chat_id 检查白名单"""
        from forward_service.config import ConfigDB

        config = ConfigDB()
        bot = BotConfig(
            bot_key="bot1",
            name="Test Bot",
            access_control=AccessControl(
                mode="whitelist",
                whitelist=["chat_room_123"]
            ),
            enabled=True
        )

        # 使用 chat_id 检查
        allowed, reason = config.check_access(bot, "user_id", chat_id="chat_room_123")
        assert allowed is True


class TestCallbackMessageExtraction:
    """测试回调中的消息内容提取"""

    def test_extract_text_message(self):
        """测试提取文本消息"""
        from forward_service.utils import extract_content

        data = {
            "msgtype": "text",
            "text": {"content": "@Bot hello world"}
        }

        result = extract_content(data)
        assert result.text == "hello world"
        assert result.image_urls == []
        assert result.quoted_short_id is None

    def test_extract_text_without_at(self):
        """测试提取没有 @ 的文本消息"""
        from forward_service.utils import extract_content

        data = {
            "msgtype": "text",
            "text": {"content": "direct message"}
        }

        result = extract_content(data)
        assert result.text == "direct message"

    def test_extract_image_message(self):
        """测试提取图片消息 - 纯图片应使用占位文本"""
        from forward_service.utils import extract_content

        data = {
            "msgtype": "image",
            "image": {"image_url": "https://example.com/image.png"}
        }

        result = extract_content(data)
        assert result.text == "[图片]"  # 占位文本，避免转发空 message
        assert result.image_urls == ["https://example.com/image.png"]

    def test_extract_image_message_no_url(self):
        """测试图片消息无 URL 时返回空"""
        from forward_service.utils import extract_content

        data = {
            "msgtype": "image",
            "image": {}
        }

        result = extract_content(data)
        assert result.text is None
        assert result.image_urls == []

    def test_extract_mixed_message(self):
        """测试提取混合消息"""
        from forward_service.utils import extract_content

        data = {
            "msgtype": "mixed",
            "mixed_message": {
                "msg_item": [
                    {
                        "msg_type": "text",
                        "text": {"content": "@Bot text part"}
                    },
                    {
                        "msg_type": "image",
                        "image": {"image_url": "https://example.com/img.png"}
                    }
                ]
            }
        }

        result = extract_content(data)
        assert result.text == "text part"
        assert result.image_urls == ["https://example.com/img.png"]

    def test_extract_mixed_message_at_bot_only_with_image(self):
        """测试混合消息：只有 @Bot 提及 + 图片（无额外文本）"""
        from forward_service.utils import extract_content

        data = {
            "msgtype": "mixed",
            "mixed_message": {
                "msg_item": [
                    {
                        "msg_type": "text",
                        "text": {"content": "@Bot "}
                    },
                    {
                        "msg_type": "image",
                        "image": {"image_url": "https://example.com/img.png"}
                    }
                ]
            }
        }

        result = extract_content(data)
        # @Bot 被 strip 后文本为空，但有图片，应使用占位文本
        assert result.text == "[图片]"
        assert result.image_urls == ["https://example.com/img.png"]

    def test_extract_empty_message(self):
        """测试空消息"""
        from forward_service.utils import extract_content

        data = {"msgtype": "text", "text": {"content": ""}}

        result = extract_content(data)
        assert result.text == ""
        assert result.image_urls == []


class TestQuoteMessageExtraction:
    """测试引用消息解析"""

    def test_strip_quote_with_short_id(self):
        """测试剥离引用消息并提取 short_id"""
        from forward_service.utils.content import strip_quote_content

        text = '\u201cBot: \n[#ca899477 agent-studio]\n这是 AI 的回复内容...\u201d\n------\n@Bot 这是我的实际回复'
        clean_text, short_id = strip_quote_content(text)

        assert clean_text == "@Bot 这是我的实际回复"
        assert short_id == "ca899477"

    def test_strip_quote_without_short_id(self):
        """测试剥离不含 short_id 的引用消息"""
        from forward_service.utils.content import strip_quote_content

        text = '\u201c这是一条普通的被引用消息\u201d\n------\n@Bot 我的回复'
        clean_text, short_id = strip_quote_content(text)

        assert clean_text == "@Bot 我的回复"
        assert short_id is None

    def test_no_quote_passthrough(self):
        """测试非引用消息原样通过"""
        from forward_service.utils.content import strip_quote_content

        text = "这是一条普通消息"
        clean_text, short_id = strip_quote_content(text)

        assert clean_text == "这是一条普通消息"
        assert short_id is None

    def test_extract_content_with_quote(self):
        """测试 extract_content 完整流程：引用消息"""
        from forward_service.utils import extract_content

        data = {
            "msgtype": "text",
            "text": {
                "content": '\u201cBot: \n[#abcd1234 my-project]\nAI 回复内容...\u201d\n------\n@Bot 用户的实际问题'
            }
        }

        result = extract_content(data)
        # 引用被剥离，@Bot 被去除，只剩用户实际内容
        assert result.text == "用户的实际问题"
        assert result.quoted_short_id == "abcd1234"

    def test_extract_content_quote_empty_reply(self):
        """测试引用消息但用户没有写回复"""
        from forward_service.utils import extract_content

        data = {
            "msgtype": "text",
            "text": {
                "content": '\u201c[#abcd1234]\nAI 回复\u201d\n------\n'
            }
        }

        result = extract_content(data)
        assert result.text == ""
        assert result.quoted_short_id == "abcd1234"

    def test_strip_quote_short_id_without_project(self):
        """测试提取不带项目名的 short_id"""
        from forward_service.utils.content import strip_quote_content

        text = '\u201c[#abc12345]\n回复内容\u201d\n------\n我的消息'
        clean_text, short_id = strip_quote_content(text)

        assert clean_text == "我的消息"
        assert short_id == "abc12345"

    def test_not_quote_format_with_separator(self):
        """测试包含分隔线但非引用格式的消息"""
        from forward_service.utils.content import strip_quote_content

        # 不以中文左引号开头，不是引用格式
        text = '这不是引用\n------\n但有分隔线'
        clean_text, short_id = strip_quote_content(text)

        assert clean_text == text  # 原样返回
        assert short_id is None


class TestCallbackWebhookExtraction:
    """测试从 webhook_url 提取 bot_key"""

    def test_extract_bot_key_standard_format(self):
        """测试标准格式的 webhook URL"""
        from forward_service.config import ConfigDB

        config = ConfigDB()
        webhook_url = "http://in.qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc123def456"

        bot_key = config.extract_bot_key_from_webhook_url(webhook_url)
        assert bot_key == "abc123def456"

    def test_extract_bot_key_with_params(self):
        """测试带其他参数的 webhook URL"""
        from forward_service.config import ConfigDB

        config = ConfigDB()
        webhook_url = "http://in.qyapi.weixin.qq.com/cgi-bin/webhook/send?key=mykey123&other=param"

        bot_key = config.extract_bot_key_from_webhook_url(webhook_url)
        assert bot_key == "mykey123"

    def test_extract_bot_key_empty_url(self):
        """测试空 URL"""
        from forward_service.config import ConfigDB

        config = ConfigDB()
        bot_key = config.extract_bot_key_from_webhook_url("")

        # 空 URL 返回 None 或空字符串
        assert bot_key is None or bot_key == ""

    def test_extract_bot_key_no_key_param(self):
        """测试没有 key 参数的 URL"""
        from forward_service.config import ConfigDB

        config = ConfigDB()
        webhook_url = "http://example.com/webhook"

        bot_key = config.extract_bot_key_from_webhook_url(webhook_url)
        # 没有 key 参数返回 None 或空字符串
        assert bot_key is None or bot_key == ""


class TestCallbackSessionManagement:
    """测试回调中的会话管理逻辑"""

    @pytest.mark.asyncio
    async def test_record_and_get_active_session(self, mock_db_manager):
        """测试记录和获取活跃会话"""
        from forward_service.session_manager import SessionManager

        session_manager = SessionManager(mock_db_manager)

        # 记录会话
        session = await session_manager.record_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789",
            session_id="session_abc123456",
            last_message="Hello",
            current_project_id="my_project"
        )

        assert session is not None
        assert session.session_id == "session_abc123456"
        assert session.current_project_id == "my_project"

        # 获取活跃会话
        active = await session_manager.get_active_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789"
        )

        assert active is not None
        assert active.session_id == "session_abc123456"

    @pytest.mark.asyncio
    async def test_reset_session(self, mock_db_manager):
        """测试重置会话"""
        from forward_service.session_manager import SessionManager

        session_manager = SessionManager(mock_db_manager)

        # 先创建会话
        await session_manager.record_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789",
            session_id="session_to_reset",
            last_message="Test"
        )

        # 重置会话
        result = await session_manager.reset_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789"
        )

        assert result is True

        # 验证没有活跃会话
        active = await session_manager.get_active_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789"
        )

        assert active is None

    @pytest.mark.asyncio
    async def test_list_sessions(self, mock_db_manager):
        """测试列出会话"""
        from forward_service.session_manager import SessionManager

        session_manager = SessionManager(mock_db_manager)

        # 创建多个会话
        await session_manager.record_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789",
            session_id="session_111111111",
            last_message="First"
        )
        await session_manager.record_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789",
            session_id="session_222222222",
            last_message="Second"
        )

        # 列出会话
        sessions = await session_manager.list_sessions(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789"
        )

        assert len(sessions) == 2


class TestCallbackForwardIntegration:
    """测试回调中的转发逻辑集成"""

    @pytest.mark.asyncio
    async def test_forward_config_priority(self, mock_db_manager):
        """测试转发配置优先级"""
        from forward_service.services.forwarder import get_forward_config_for_user
        from forward_service.repository import get_user_project_repository

        # 创建用户项目配置
        async with mock_db_manager.get_session() as session:
            repo = get_user_project_repository(session)
            await repo.create(
                bot_key="bot123",
                chat_id="user456",
                project_id="user_project",
                url_template="https://user.api.com/webhook",
                api_key="sk-user",
                timeout=120,
                is_default=True
            )

        # 获取配置应该返回用户的项目配置
        config = await get_forward_config_for_user(
            bot_key="bot123",
            chat_id="user456"
        )

        assert config.project_id == "user_project"
        assert config.target_url == "https://user.api.com/webhook"
        assert config.api_key == "sk-user"
        assert config.timeout == 120
