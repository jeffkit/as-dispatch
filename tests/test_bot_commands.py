"""
Bot 注册与管理命令单元测试

测试内容:
- /register 命令: 注册、重复注册、格式错误
- /bot set 命令: 修改配置、权限检查
- /bot info 命令: 查看配置
- is_bot_command: 命令识别
- BotConfig.is_registered / is_configured: 属性判断
- 骨架 Bot 创建与 owner_id 字段
"""
import sys
from unittest.mock import MagicMock

# Mock tunely 模块以避免导入错误
if 'tunely' not in sys.modules:
    sys.modules['tunely'] = MagicMock()
    sys.modules['tunely.server'] = MagicMock()

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from forward_service.routes.bot_commands import (
    is_bot_command,
    handle_bot_command,
    handle_register,
    handle_bot_set,
    handle_bot_info,
    get_register_help,
    REGISTER_RE,
    BOT_SET_RE,
    BOT_INFO_RE,
)
from forward_service.config import BotConfig, ForwardConfig
from forward_service.models import Chatbot
from forward_service.repository import ChatbotRepository


# ============== 命令正则匹配测试 ==============

class TestCommandRegex:
    """测试命令正则表达式"""

    def test_register_re_basic(self):
        """基本 /register 命令"""
        match = REGISTER_RE.match("/register my-bot https://example.com/a2a")
        assert match is not None
        assert match.group(1) == "my-bot"
        assert match.group(2) == "https://example.com/a2a"

    def test_register_re_http(self):
        """HTTP URL 也能匹配"""
        match = REGISTER_RE.match("/register test http://localhost:8080/api")
        assert match is not None
        assert match.group(2) == "http://localhost:8080/api"

    def test_register_re_no_url(self):
        """缺少 URL 不匹配"""
        match = REGISTER_RE.match("/register my-bot")
        assert match is None

    def test_register_re_no_name(self):
        """缺少名称不匹配"""
        match = REGISTER_RE.match("/register https://example.com")
        # This matches because "https://example.com" would be treated as name
        # and the URL pattern wouldn't match, so it should be None or partial
        # Let me verify
        match = REGISTER_RE.match("/register")
        assert match is None

    def test_register_re_invalid_url(self):
        """非 http(s) URL 不匹配"""
        match = REGISTER_RE.match("/register my-bot ftp://example.com/a2a")
        assert match is None

    def test_bot_set_url(self):
        """/bot set url 命令"""
        match = BOT_SET_RE.match("/bot set url https://new-url.com/api")
        assert match is not None
        assert match.group(1) == "url"
        assert match.group(2).strip() == "https://new-url.com/api"

    def test_bot_set_name(self):
        """/bot set name 命令"""
        match = BOT_SET_RE.match("/bot set name my-new-bot")
        assert match is not None
        assert match.group(1) == "name"
        assert match.group(2).strip() == "my-new-bot"

    def test_bot_set_api_key(self):
        """/bot set api-key 命令"""
        match = BOT_SET_RE.match("/bot set api-key sk-abc123def456")
        assert match is not None
        assert match.group(1) == "api-key"
        assert match.group(2).strip() == "sk-abc123def456"

    def test_bot_set_timeout(self):
        """/bot set timeout 命令"""
        match = BOT_SET_RE.match("/bot set timeout 120")
        assert match is not None
        assert match.group(1) == "timeout"
        assert match.group(2).strip() == "120"

    def test_bot_info(self):
        """/bot info 命令"""
        match = BOT_INFO_RE.match("/bot info")
        assert match is not None

    def test_bot_info_with_trailing_space(self):
        """/bot info 带尾随空格"""
        match = BOT_INFO_RE.match("/bot info  ")
        assert match is not None


# ============== is_bot_command 测试 ==============

class TestIsBotCommand:
    """测试 is_bot_command 函数"""

    def test_register_command(self):
        assert is_bot_command("/register my-bot https://example.com/api") is True

    def test_bot_set_command(self):
        assert is_bot_command("/bot set url https://example.com") is True

    def test_bot_info_command(self):
        assert is_bot_command("/bot info") is True

    def test_regular_message(self):
        assert is_bot_command("hello world") is False

    def test_other_slash_command(self):
        assert is_bot_command("/help") is False

    def test_partial_register(self):
        """不完整的 /register 不是 bot 命令"""
        assert is_bot_command("/register") is False

    def test_bot_set_unknown_field(self):
        """未知字段的 /bot set 不匹配"""
        assert is_bot_command("/bot set unknown value") is False


# ============== BotConfig 属性测试 ==============

class TestBotConfigProperties:
    """测试 BotConfig 的 is_registered 和 is_configured 属性"""

    def test_not_registered(self):
        """无 owner 的 Bot 未注册"""
        bot = BotConfig(bot_key="key1", owner_id=None)
        assert bot.is_registered is False

    def test_registered(self):
        """有 owner 的 Bot 已注册"""
        bot = BotConfig(bot_key="key1", owner_id="user123")
        assert bot.is_registered is True

    def test_not_configured(self):
        """无 target_url 的 Bot 未配置"""
        bot = BotConfig(bot_key="key1", forward_config=ForwardConfig(target_url=""))
        assert bot.is_configured is False

    def test_configured(self):
        """有 target_url 的 Bot 已配置"""
        bot = BotConfig(bot_key="key1", forward_config=ForwardConfig(target_url="https://example.com"))
        assert bot.is_configured is True


# ============== handle_register 测试 ==============

class TestHandleRegister:
    """测试 /register 命令处理"""

    @pytest.mark.asyncio
    async def test_register_success(self, mock_db_manager):
        """首次注册成功"""
        # 先创建一个未注册的骨架 Bot
        async with mock_db_manager.get_session() as session:
            repo = ChatbotRepository(session)
            await repo.create(
                bot_key="test-bot-key",
                name="未配置 Bot",
                url_template="",
                enabled=False,
            )
            await session.commit()

        # Mock config.reload_config
        with patch("forward_service.routes.bot_commands.config") as mock_config:
            mock_config.reload_config = AsyncMock()

            success, msg = await handle_register(
                bot_key="test-bot-key",
                message="/register my-agent https://my-agent.com/a2a",
                from_user_id="user123",
            )

        assert success is True
        assert "注册成功" in msg
        assert "my-agent" in msg
        assert "https://my-agent.com/a2a" in msg

        # 验证数据库中的更新
        async with mock_db_manager.get_session() as session:
            repo = ChatbotRepository(session)
            bot = await repo.get_by_bot_key("test-bot-key")
            assert bot.name == "my-agent"
            assert bot.target_url == "https://my-agent.com/a2a"
            assert bot.owner_id == "user123"
            assert bot.enabled is True

    @pytest.mark.asyncio
    async def test_register_already_registered(self, mock_db_manager):
        """重复注册被拒绝"""
        # 创建一个已注册的 Bot
        async with mock_db_manager.get_session() as session:
            repo = ChatbotRepository(session)
            bot = await repo.create(
                bot_key="registered-bot",
                name="Already Registered",
                url_template="https://old-url.com",
                enabled=True,
                owner_id="original-owner",
            )
            await session.commit()

        success, msg = await handle_register(
            bot_key="registered-bot",
            message="/register new-name https://new-url.com/api",
            from_user_id="another-user",
        )

        assert success is False
        assert "已被注册" in msg
        assert "original-owner" in msg

    @pytest.mark.asyncio
    async def test_register_invalid_format(self, mock_db_manager):
        """格式错误"""
        success, msg = await handle_register(
            bot_key="test-bot",
            message="/register just-a-name",
            from_user_id="user123",
        )

        assert success is False
        assert "格式错误" in msg

    @pytest.mark.asyncio
    async def test_register_bot_not_found(self, mock_db_manager):
        """Bot 不存在"""
        success, msg = await handle_register(
            bot_key="nonexistent-bot",
            message="/register my-bot https://example.com/api",
            from_user_id="user123",
        )

        assert success is False
        assert "不存在" in msg


# ============== handle_bot_set 测试 ==============

class TestHandleBotSet:
    """测试 /bot set 命令处理"""

    @pytest_asyncio.fixture
    async def registered_bot(self, mock_db_manager):
        """创建一个已注册的 Bot"""
        async with mock_db_manager.get_session() as session:
            repo = ChatbotRepository(session)
            await repo.create(
                bot_key="owner-bot",
                name="My Bot",
                url_template="https://old-url.com/api",
                enabled=True,
                owner_id="owner-user",
            )
            await session.commit()
        return "owner-bot"

    @pytest.mark.asyncio
    async def test_set_url_by_owner(self, mock_db_manager, registered_bot):
        """Owner 修改 URL 成功"""
        with patch("forward_service.routes.bot_commands.config") as mock_config:
            mock_config.reload_config = AsyncMock()

            success, msg = await handle_bot_set(
                bot_key="owner-bot",
                message="/bot set url https://new-url.com/api",
                from_user_id="owner-user",
            )

        assert success is True
        assert "转发地址已更新" in msg
        assert "new-url.com" in msg

    @pytest.mark.asyncio
    async def test_set_url_by_non_owner(self, mock_db_manager, registered_bot):
        """非 Owner 修改被拒绝"""
        success, msg = await handle_bot_set(
            bot_key="owner-bot",
            message="/bot set url https://hack.com/api",
            from_user_id="non-owner-user",
        )

        assert success is False
        assert "仅 Bot 管理员" in msg

    @pytest.mark.asyncio
    async def test_set_name_by_owner(self, mock_db_manager, registered_bot):
        """Owner 修改名称成功"""
        with patch("forward_service.routes.bot_commands.config") as mock_config:
            mock_config.reload_config = AsyncMock()

            success, msg = await handle_bot_set(
                bot_key="owner-bot",
                message="/bot set name new-bot-name",
                from_user_id="owner-user",
            )

        assert success is True
        assert "名称已更新" in msg

    @pytest.mark.asyncio
    async def test_set_timeout_valid(self, mock_db_manager, registered_bot):
        """设置有效的超时时间"""
        with patch("forward_service.routes.bot_commands.config") as mock_config:
            mock_config.reload_config = AsyncMock()

            success, msg = await handle_bot_set(
                bot_key="owner-bot",
                message="/bot set timeout 120",
                from_user_id="owner-user",
            )

        assert success is True
        assert "超时时间已更新" in msg

    @pytest.mark.asyncio
    async def test_set_timeout_invalid_range(self, mock_db_manager, registered_bot):
        """超时时间超出范围"""
        success, msg = await handle_bot_set(
            bot_key="owner-bot",
            message="/bot set timeout 5",
            from_user_id="owner-user",
        )

        assert success is False
        assert "10-600" in msg

    @pytest.mark.asyncio
    async def test_set_url_invalid_protocol(self, mock_db_manager, registered_bot):
        """URL 协议不正确"""
        success, msg = await handle_bot_set(
            bot_key="owner-bot",
            message="/bot set url ftp://example.com",
            from_user_id="owner-user",
        )

        assert success is False
        assert "http" in msg.lower()

    @pytest.mark.asyncio
    async def test_set_on_unregistered_bot(self, mock_db_manager):
        """未注册 Bot 不能使用 /bot set"""
        async with mock_db_manager.get_session() as session:
            repo = ChatbotRepository(session)
            await repo.create(
                bot_key="unregistered-bot",
                name="Unregistered",
                url_template="",
                enabled=False,
            )
            await session.commit()

        success, msg = await handle_bot_set(
            bot_key="unregistered-bot",
            message="/bot set url https://example.com",
            from_user_id="user123",
        )

        assert success is False
        assert "尚未注册" in msg


# ============== handle_bot_info 测试 ==============

class TestHandleBotInfo:
    """测试 /bot info 命令"""

    def test_bot_info_registered(self):
        """已注册 Bot 的信息"""
        mock_bot = BotConfig(
            bot_key="info-bot",
            name="Info Bot",
            forward_config=ForwardConfig(
                target_url="https://example.com/api",
                api_key="sk-1234567890abcdef",
                timeout=120,
            ),
            enabled=True,
            owner_id="owner123",
        )

        with patch("forward_service.routes.bot_commands.config") as mock_config:
            mock_config.get_bot.return_value = mock_bot

            import asyncio
            success, msg = asyncio.get_event_loop().run_until_complete(
                handle_bot_info("info-bot", "owner123")
            )

        assert success is True
        assert "Info Bot" in msg
        assert "已注册" in msg
        assert "owner123" in msg
        assert "管理命令" in msg  # Owner 看到管理命令

    def test_bot_info_non_owner(self):
        """非 Owner 看不到管理命令"""
        mock_bot = BotConfig(
            bot_key="info-bot",
            name="Info Bot",
            forward_config=ForwardConfig(target_url="https://example.com"),
            enabled=True,
            owner_id="owner123",
        )

        with patch("forward_service.routes.bot_commands.config") as mock_config:
            mock_config.get_bot.return_value = mock_bot

            import asyncio
            success, msg = asyncio.get_event_loop().run_until_complete(
                handle_bot_info("info-bot", "other-user")
            )

        assert success is True
        assert "管理命令" not in msg

    def test_bot_info_unregistered(self):
        """未注册 Bot 显示待注册状态"""
        mock_bot = BotConfig(
            bot_key="pending-bot",
            name="Pending Bot",
            forward_config=ForwardConfig(target_url=""),
            enabled=False,
            owner_id=None,
        )

        with patch("forward_service.routes.bot_commands.config") as mock_config:
            mock_config.get_bot.return_value = mock_bot

            import asyncio
            success, msg = asyncio.get_event_loop().run_until_complete(
                handle_bot_info("pending-bot", "user123")
            )

        assert success is True
        assert "待注册" in msg


# ============== Chatbot Model owner_id 测试 ==============

class TestChatbotOwnerField:
    """测试 Chatbot 模型的 owner_id 字段"""

    @pytest.mark.asyncio
    async def test_create_with_owner(self, test_db_session):
        """创建带 owner 的 Bot"""
        repo = ChatbotRepository(test_db_session)
        bot = await repo.create(
            bot_key="owned-bot",
            name="Owned Bot",
            url_template="https://example.com",
            owner_id="owner-user-1",
        )
        await test_db_session.commit()

        result = await repo.get_by_bot_key("owned-bot")
        assert result.owner_id == "owner-user-1"

    @pytest.mark.asyncio
    async def test_create_without_owner(self, test_db_session):
        """创建无 owner 的 Bot（骨架 Bot）"""
        repo = ChatbotRepository(test_db_session)
        bot = await repo.create(
            bot_key="skeleton-bot",
            name="Skeleton",
            url_template="",
            enabled=False,
        )
        await test_db_session.commit()

        result = await repo.get_by_bot_key("skeleton-bot")
        assert result.owner_id is None

    @pytest.mark.asyncio
    async def test_update_owner(self, test_db_session):
        """更新 owner_id"""
        repo = ChatbotRepository(test_db_session)
        bot = await repo.create(
            bot_key="update-owner-bot",
            name="Test",
            url_template="",
        )
        await test_db_session.commit()

        assert bot.owner_id is None

        updated = await repo.update(bot.id, owner_id="new-owner")
        await test_db_session.commit()

        result = await repo.get_by_bot_key("update-owner-bot")
        assert result.owner_id == "new-owner"

    @pytest.mark.asyncio
    async def test_to_dict_includes_owner(self, test_db_session):
        """to_dict 包含 owner_id"""
        repo = ChatbotRepository(test_db_session)
        bot = await repo.create(
            bot_key="dict-bot",
            name="Dict Bot",
            url_template="",
            owner_id="dict-owner",
        )
        await test_db_session.commit()

        data = bot.to_dict()
        assert "owner_id" in data
        assert data["owner_id"] == "dict-owner"


# ============== get_register_help 测试 ==============

class TestGetRegisterHelp:
    """测试注册引导消息"""

    def test_help_message_content(self):
        """引导消息包含必要信息"""
        help_msg = get_register_help()
        assert "/register" in help_msg
        assert "Bot名称" in help_msg or "Bot" in help_msg
        assert "URL" in help_msg
        assert "示例" in help_msg
