"""
会话管理器单元测试

测试 session_manager.py 中的功能:
- SessionManager 类
- Slash 命令解析
- 会话列表格式化
- 项目关联功能
"""
import pytest
import pytest_asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from forward_service.session_manager import (
    SessionManager,
    get_session_manager,
    init_session_manager,
    SLASH_COMMANDS,
)
from forward_service.models import UserSession


class TestSlashCommandParsing:
    """测试 Slash 命令解析"""

    @pytest.fixture
    def session_manager(self, mock_db_manager):
        """创建 SessionManager 实例"""
        return SessionManager(mock_db_manager)

    def test_parse_list_command(self, session_manager):
        """测试解析 /sess 命令"""
        result = session_manager.parse_slash_command("/sess")
        assert result is not None
        assert result[0] == "list"

        result = session_manager.parse_slash_command("/s")
        assert result is not None
        assert result[0] == "list"

    def test_parse_reset_command(self, session_manager):
        """测试解析 /reset 命令"""
        result = session_manager.parse_slash_command("/reset")
        assert result is not None
        assert result[0] == "reset"

        result = session_manager.parse_slash_command("/r")
        assert result is not None
        assert result[0] == "reset"

    def test_parse_change_command(self, session_manager):
        """测试解析 /change 命令"""
        result = session_manager.parse_slash_command("/change abc12345")
        assert result is not None
        assert result[0] == "change"
        assert result[1] == "abc12345"

        result = session_manager.parse_slash_command("/c abc12345")
        assert result is not None
        assert result[0] == "change"
        assert result[1] == "abc12345"

    def test_parse_change_with_message(self, session_manager):
        """测试解析带附加消息的 /change 命令"""
        result = session_manager.parse_slash_command("/c abc12345 你好世界")
        assert result is not None
        assert result[0] == "change"
        assert result[1] == "abc12345"
        assert result[2] == "你好世界"

    def test_parse_ping_command(self, session_manager):
        """测试解析 /ping 命令"""
        result = session_manager.parse_slash_command("/ping")
        assert result is not None
        assert result[0] == "ping"

        result = session_manager.parse_slash_command("/p")
        assert result is not None
        assert result[0] == "ping"

    def test_parse_status_command(self, session_manager):
        """测试解析 /status 命令"""
        result = session_manager.parse_slash_command("/status")
        assert result is not None
        assert result[0] == "status"

        result = session_manager.parse_slash_command("/st")
        assert result is not None
        assert result[0] == "status"

    def test_parse_help_command(self, session_manager):
        """测试解析 /help 命令"""
        result = session_manager.parse_slash_command("/help")
        assert result is not None
        assert result[0] == "help"

        result = session_manager.parse_slash_command("/h")
        assert result is not None
        assert result[0] == "help"

    def test_parse_bots_command(self, session_manager):
        """测试解析 /bots 命令"""
        result = session_manager.parse_slash_command("/bots")
        assert result is not None
        assert result[0] == "bots"

    def test_parse_bot_command(self, session_manager):
        """测试解析 /bot 命令"""
        result = session_manager.parse_slash_command("/bot mybot")
        assert result is not None
        assert result[0] == "bot"
        assert result[1] == "mybot"

    def test_parse_bot_command_with_update(self, session_manager):
        """测试解析带更新参数的 /bot 命令"""
        result = session_manager.parse_slash_command("/bot mybot url https://new.api.com")
        assert result is not None
        assert result[0] == "bot"
        assert result[1] == "mybot"
        assert result[2] == "url:https://new.api.com"

    def test_parse_non_slash_command(self, session_manager):
        """测试解析普通消息（非命令）"""
        result = session_manager.parse_slash_command("Hello world")
        assert result is None

        result = session_manager.parse_slash_command("")
        assert result is None

    def test_parse_unknown_command(self, session_manager):
        """测试解析未知命令"""
        result = session_manager.parse_slash_command("/unknown")
        assert result is None


class TestSessionManagerRecordSession:
    """测试会话记录功能"""

    @pytest.fixture
    def session_manager(self, mock_db_manager):
        """创建 SessionManager 实例"""
        return SessionManager(mock_db_manager)

    @pytest.mark.asyncio
    async def test_record_new_session(self, session_manager):
        """测试记录新会话"""
        session = await session_manager.record_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789",
            session_id="session_abc123",
            last_message="Hello",
            current_project_id="my_project"
        )

        assert session is not None
        assert session.user_id == "user123"
        assert session.chat_id == "chat456"
        assert session.bot_key == "bot789"
        assert session.session_id == "session_abc123"
        assert session.short_id == "session_"
        assert session.last_message == "Hello"
        assert session.message_count == 1
        assert session.is_active is True
        assert session.current_project_id == "my_project"

    @pytest.mark.asyncio
    async def test_record_existing_session(self, session_manager):
        """测试更新现有会话"""
        # 先创建一个会话
        session1 = await session_manager.record_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789",
            session_id="session_abc123",
            last_message="First message"
        )

        # 更新同一会话
        session2 = await session_manager.record_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789",
            session_id="session_abc123",
            last_message="Second message"
        )

        assert session2.id == session1.id
        assert session2.last_message == "Second message"
        assert session2.message_count == 2

    @pytest.mark.asyncio
    async def test_new_session_deactivates_old(self, session_manager):
        """测试新会话会使旧会话变为非活跃"""
        # 创建第一个会话
        session1 = await session_manager.record_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789",
            session_id="session_first",
            last_message="First"
        )

        # 创建第二个会话
        session2 = await session_manager.record_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789",
            session_id="session_second",
            last_message="Second"
        )

        # 获取活跃会话，应该是第二个
        active = await session_manager.get_active_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789"
        )

        assert active is not None
        assert active.session_id == "session_second"


class TestSessionManagerGetActiveSession:
    """测试获取活跃会话"""

    @pytest.fixture
    def session_manager(self, mock_db_manager):
        """创建 SessionManager 实例"""
        return SessionManager(mock_db_manager)

    @pytest.mark.asyncio
    async def test_get_active_session(self, session_manager):
        """测试获取活跃会话"""
        # 创建会话
        await session_manager.record_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789",
            session_id="session_active",
            last_message="Active session"
        )

        active = await session_manager.get_active_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789"
        )

        assert active is not None
        assert active.session_id == "session_active"
        assert active.is_active is True

    @pytest.mark.asyncio
    async def test_get_active_session_none(self, session_manager):
        """测试没有活跃会话时返回 None"""
        active = await session_manager.get_active_session(
            user_id="user_no_session",
            chat_id="chat_no_session",
            bot_key="bot_no_session"
        )

        assert active is None


class TestSessionManagerListSessions:
    """测试会话列表功能"""

    @pytest.fixture
    def session_manager(self, mock_db_manager):
        """创建 SessionManager 实例"""
        return SessionManager(mock_db_manager)

    @pytest.mark.asyncio
    async def test_list_sessions(self, session_manager):
        """测试列出会话"""
        # 创建多个会话
        await session_manager.record_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789",
            session_id="session_first",
            last_message="First"
        )
        await session_manager.record_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789",
            session_id="session_second",
            last_message="Second"
        )

        sessions = await session_manager.list_sessions(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789"
        )

        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, session_manager):
        """测试列出空会话列表"""
        sessions = await session_manager.list_sessions(
            user_id="user_no_session",
            chat_id="chat_no_session"
        )

        assert len(sessions) == 0


class TestSessionManagerResetSession:
    """测试重置会话功能"""

    @pytest.fixture
    def session_manager(self, mock_db_manager):
        """创建 SessionManager 实例"""
        return SessionManager(mock_db_manager)

    @pytest.mark.asyncio
    async def test_reset_session(self, session_manager):
        """测试重置会话"""
        # 创建会话
        await session_manager.record_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789",
            session_id="session_to_reset",
            last_message="To reset"
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
    async def test_reset_session_no_active(self, session_manager):
        """测试重置不存在的会话"""
        result = await session_manager.reset_session(
            user_id="user_no_session",
            chat_id="chat_no_session",
            bot_key="bot_no_session"
        )

        assert result is False


class TestSessionManagerChangeSession:
    """测试切换会话功能"""

    @pytest.fixture
    def session_manager(self, mock_db_manager):
        """创建 SessionManager 实例"""
        return SessionManager(mock_db_manager)

    @pytest.mark.asyncio
    async def test_change_session(self, session_manager):
        """测试切换到指定会话"""
        # 创建多个会话（使用不同的前缀确保 short_id 不同）
        await session_manager.record_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789",
            session_id="abc12345678901234",  # short_id = "abc12345"
            last_message="First"
        )
        await session_manager.record_session(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789",
            session_id="xyz98765432109876",  # short_id = "xyz98765"
            last_message="Second"
        )

        # 切换到第一个会话
        result = await session_manager.change_session(
            user_id="user123",
            chat_id="chat456",
            short_id="abc12345",  # 短 ID 是 session_id 的前 8 位
            bot_key="bot789"
        )

        assert result is not None
        assert result.session_id == "abc12345678901234"
        assert result.is_active is True

    @pytest.mark.asyncio
    async def test_change_session_not_found(self, session_manager):
        """测试切换到不存在的会话"""
        result = await session_manager.change_session(
            user_id="user123",
            chat_id="chat456",
            short_id="notfound",
            bot_key="bot789"
        )

        assert result is None


class TestFormatSessionList:
    """测试格式化会话列表"""

    @pytest.fixture
    def session_manager(self, mock_db_manager):
        """创建 SessionManager 实例"""
        return SessionManager(mock_db_manager)

    def test_format_empty_list(self, session_manager):
        """测试格式化空列表"""
        result = session_manager.format_session_list([])
        assert "暂无" in result or "📭" in result

    def test_format_session_list(self, session_manager):
        """测试格式化会话列表"""
        # 创建 mock 会话
        session1 = MagicMock(spec=UserSession)
        session1.short_id = "abc12345"
        session1.last_message = "Hello world"
        session1.message_count = 5
        session1.is_active = True

        session2 = MagicMock(spec=UserSession)
        session2.short_id = "def67890"
        session2.last_message = "Another message"
        session2.message_count = 3
        session2.is_active = False

        result = session_manager.format_session_list([session1, session2])

        assert "abc12345" in result
        assert "def67890" in result
        assert "5条" in result
        assert "3条" in result
        assert "✅" in result  # 活跃会话标记


class TestSessionManagerInit:
    """测试 SessionManager 初始化"""

    def test_init_session_manager(self, mock_db_manager):
        """测试初始化全局 SessionManager"""
        manager = init_session_manager(mock_db_manager)
        assert manager is not None

        # 获取应该返回同一个实例
        from forward_service.session_manager import _session_manager
        assert _session_manager is manager

    def test_get_session_manager_not_initialized(self):
        """测试未初始化时获取 SessionManager 会抛出异常"""
        import forward_service.session_manager as sm_module

        # 保存原始值
        original = sm_module._session_manager
        sm_module._session_manager = None

        try:
            with pytest.raises(RuntimeError):
                get_session_manager()
        finally:
            # 恢复原始值
            sm_module._session_manager = original


class TestSessionManagerSetSessionProject:
    """测试 SessionManager.set_session_project 方法"""

    @pytest.fixture
    def mock_db_manager(self):
        """创建 mock 数据库管理器"""
        mock_manager = MagicMock()
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.refresh = AsyncMock()
        
        @asynccontextmanager
        async def get_session():
            yield mock_session
        
        mock_manager.get_session = get_session
        return mock_manager

    @pytest.fixture
    def session_manager(self, mock_db_manager):
        """创建 SessionManager 实例"""
        return SessionManager(mock_db_manager)

    @pytest.mark.asyncio
    async def test_set_session_project_existing_session(self, session_manager, mock_db_manager):
        """测试更新已有会话的项目"""
        # 模拟更新影响了 1 行
        mock_result = MagicMock()
        mock_result.rowcount = 1
        
        async with mock_db_manager.get_session() as session:
            session.execute.return_value = mock_result

        result = await session_manager.set_session_project(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789",
            project_id="new_project"
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_set_session_project_no_existing_session(self, session_manager, mock_db_manager):
        """测试没有活跃会话时创建新会话"""
        # 模拟更新影响了 0 行（没有现有会话）
        mock_result = MagicMock()
        mock_result.rowcount = 0
        
        async with mock_db_manager.get_session() as session:
            session.execute.return_value = mock_result

        result = await session_manager.set_session_project(
            user_id="user123",
            chat_id="chat456",
            bot_key="bot789",
            project_id="new_project"
        )

        assert result is True
