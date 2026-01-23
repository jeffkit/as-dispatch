"""
管理员命令处理单元测试

测试 admin_commands.py 中的功能:
- check_is_admin
- get_system_status
- get_admin_help
- get_bots_list
- get_bot_detail
- update_bot_config
- get_pending_list
- get_recent_logs
- get_error_logs
- pending 请求管理
"""
import pytest
import pytest_asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock

from forward_service.routes.admin_commands import (
    check_is_admin,
    get_system_status,
    get_admin_help,
    get_bots_list,
    get_bot_detail,
    update_bot_config,
    get_pending_list,
    get_recent_logs,
    get_error_logs,
    add_pending_request,
    remove_pending_request,
    _pending_requests,
    get_session_key,
)


class TestCheckIsAdmin:
    """测试管理员权限检查"""

    @pytest.mark.asyncio
    async def test_admin_by_user_id(self, mock_db_manager):
        """测试通过 user_id 识别管理员"""
        from forward_service.repository import get_system_config_repository

        # 设置管理员列表
        async with mock_db_manager.get_session() as session:
            repo = get_system_config_repository(session)
            await repo.set("admin_users", json.dumps(["admin123", "superuser"]))

        result = await check_is_admin("admin123")
        assert result is True

    @pytest.mark.asyncio
    async def test_admin_by_alias(self, mock_db_manager):
        """测试通过 alias 识别管理员"""
        from forward_service.repository import get_system_config_repository

        # 设置管理员列表
        async with mock_db_manager.get_session() as session:
            repo = get_system_config_repository(session)
            await repo.set("admin_users", json.dumps(["admin123", "admin_alias"]))

        result = await check_is_admin("other_user", alias="admin_alias")
        assert result is True

    @pytest.mark.asyncio
    async def test_not_admin(self, mock_db_manager):
        """测试非管理员用户"""
        from forward_service.repository import get_system_config_repository

        # 设置管理员列表
        async with mock_db_manager.get_session() as session:
            repo = get_system_config_repository(session)
            await repo.set("admin_users", json.dumps(["admin123"]))

        result = await check_is_admin("regular_user")
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_admin_list(self, mock_db_manager):
        """测试空管理员列表"""
        result = await check_is_admin("any_user")
        assert result is False


class TestGetAdminHelp:
    """测试管理员帮助信息"""

    @pytest.mark.asyncio
    async def test_get_admin_help(self):
        """测试获取帮助信息"""
        result = await get_admin_help()

        assert "📖" in result
        assert "/ping" in result
        assert "/status" in result
        assert "/bots" in result
        assert "/bot" in result
        assert "/pending" in result
        assert "/health" in result


class TestGetSystemStatus:
    """测试系统状态获取"""

    @pytest.mark.asyncio
    async def test_get_system_status(self, mock_db_manager):
        """测试获取系统状态"""
        with patch('forward_service.routes.admin_commands.config') as mock_config:
            mock_config.bots = {"bot1": MagicMock(), "bot2": MagicMock()}

            result = await get_system_status()

            assert "Forward Service" in result
            assert "状态" in result
            assert "Bot 数量" in result


class TestGetBotsList:
    """测试获取 Bot 列表"""

    @pytest.mark.asyncio
    async def test_get_bots_list_empty(self):
        """测试空 Bot 列表"""
        with patch('forward_service.routes.admin_commands.config') as mock_config:
            mock_config.bots = {}

            result = await get_bots_list()

            assert "暂无" in result or "📭" in result

    @pytest.mark.asyncio
    async def test_get_bots_list_with_data(self):
        """测试有数据的 Bot 列表"""
        with patch('forward_service.routes.admin_commands.config') as mock_config:
            mock_bot1 = MagicMock()
            mock_bot1.name = "Test Bot 1"
            mock_bot1.enabled = True

            mock_bot2 = MagicMock()
            mock_bot2.name = "Test Bot 2"
            mock_bot2.enabled = False

            mock_config.bots = {"bot1": mock_bot1, "bot2": mock_bot2}

            result = await get_bots_list()

            assert "Bot 列表" in result
            assert "Test Bot 1" in result
            assert "Test Bot 2" in result
            assert "✅" in result  # 启用的 Bot
            assert "❌" in result  # 禁用的 Bot


class TestGetBotDetail:
    """测试获取 Bot 详情"""

    @pytest.mark.asyncio
    async def test_get_bot_detail_not_found(self):
        """测试 Bot 不存在"""
        with patch('forward_service.routes.admin_commands.config') as mock_config:
            mock_config.bots = {}

            result = await get_bot_detail("nonexistent")

            assert "未找到" in result

    @pytest.mark.asyncio
    async def test_get_bot_detail_success(self, mock_db_manager):
        """测试成功获取 Bot 详情"""
        with patch('forward_service.routes.admin_commands.config') as mock_config:
            mock_bot = MagicMock()
            mock_bot.name = "Test Bot"
            mock_bot.bot_key = "test_key_123"
            mock_bot.enabled = True
            mock_bot.forward_config = MagicMock()
            mock_bot.forward_config.get_url = MagicMock(return_value="https://api.test.com")
            mock_bot.forward_config.api_key = "sk-test123456789"

            mock_config.bots = {"test_key_123": mock_bot}

            result = await get_bot_detail("Test Bot")

            assert "Test Bot" in result
            assert "详情" in result
            assert "统计" in result or "配置" in result


class TestUpdateBotConfig:
    """测试更新 Bot 配置"""

    @pytest.mark.asyncio
    async def test_update_bot_not_found(self):
        """测试更新不存在的 Bot"""
        with patch('forward_service.routes.admin_commands.config') as mock_config:
            mock_config.bots = {}

            result = await update_bot_config("nonexistent", "url", "https://new.url")

            assert "未找到" in result

    @pytest.mark.asyncio
    async def test_update_bot_unknown_field(self, mock_db_manager):
        """测试更新未知字段"""
        with patch('forward_service.routes.admin_commands.config') as mock_config:
            mock_bot = MagicMock()
            mock_bot.name = "Test Bot"
            mock_config.bots = {"test_key": mock_bot}

            result = await update_bot_config("Test Bot", "unknown_field", "value")

            assert "未知" in result or "未找到" in result


class TestPendingRequests:
    """测试 pending 请求管理"""

    def test_add_pending_request(self):
        """测试添加 pending 请求"""
        # 清空之前的请求
        _pending_requests.clear()

        add_pending_request(
            request_id="req123",
            bot_name="Test Bot",
            user="user1",
            message="Hello world"
        )

        assert "req123" in _pending_requests
        assert _pending_requests["req123"]["bot_name"] == "Test Bot"
        assert _pending_requests["req123"]["user"] == "user1"

    def test_remove_pending_request(self):
        """测试移除 pending 请求"""
        # 清空并添加请求
        _pending_requests.clear()
        add_pending_request(
            request_id="req456",
            bot_name="Test Bot",
            user="user1",
            message="Test"
        )

        remove_pending_request("req456")

        assert "req456" not in _pending_requests

    def test_remove_nonexistent_request(self):
        """测试移除不存在的请求（不应抛出异常）"""
        _pending_requests.clear()

        # 应该不抛出异常
        remove_pending_request("nonexistent")


class TestGetPendingList:
    """测试获取 pending 列表"""

    def test_pending_requests_tracking(self):
        """测试 pending 请求追踪（不涉及数据库）"""
        _pending_requests.clear()

        # 添加请求
        add_pending_request(
            request_id="req001",
            bot_name="Test Bot",
            user="user1",
            message="Processing message"
        )
        add_pending_request(
            request_id="req002",
            bot_name="Test Bot 2",
            user="user2",
            message="Another message"
        )

        assert len(_pending_requests) == 2
        assert "req001" in _pending_requests
        assert "req002" in _pending_requests
        assert _pending_requests["req001"]["bot_name"] == "Test Bot"
        assert _pending_requests["req002"]["user"] == "user2"

        # 移除请求
        remove_pending_request("req001")
        assert len(_pending_requests) == 1
        assert "req001" not in _pending_requests

        # 清理
        _pending_requests.clear()


class TestGetRecentLogs:
    """测试获取最近日志"""

    @pytest.mark.asyncio
    async def test_get_recent_logs_empty(self, mock_db_manager):
        """测试空日志"""
        result = await get_recent_logs()

        assert "暂无" in result or "📭" in result or "日志" in result

    @pytest.mark.asyncio
    async def test_get_recent_logs_with_data(self, mock_db_manager):
        """测试有日志数据"""
        from forward_service.repository import get_forward_log_repository

        # 创建日志记录
        async with mock_db_manager.get_session() as session:
            repo = get_forward_log_repository(session)
            await repo.create(
                chat_id="chat123",
                from_user_id="user456",
                content="Test message",
                target_url="https://api.test.com",
                status="success",
                duration_ms=500
            )

        result = await get_recent_logs()

        assert "日志" in result or "最近" in result


class TestGetErrorLogs:
    """测试获取错误日志"""

    @pytest.mark.asyncio
    async def test_get_error_logs_empty(self, mock_db_manager):
        """测试空错误日志"""
        result = await get_error_logs()

        assert "暂无" in result or "📭" in result or "错误" in result

    @pytest.mark.asyncio
    async def test_get_error_logs_with_data(self, mock_db_manager):
        """测试有错误日志"""
        from forward_service.repository import get_forward_log_repository

        # 创建错误日志记录
        async with mock_db_manager.get_session() as session:
            repo = get_forward_log_repository(session)
            await repo.create(
                chat_id="chat123",
                from_user_id="user456",
                content="Test message",
                target_url="https://api.test.com",
                status="error",
                error="Connection timeout",
                duration_ms=5000
            )

        result = await get_error_logs()

        assert "错误" in result or "error" in result.lower()


class TestGetSessionKey:
    """测试会话 key 生成"""

    def test_get_session_key(self):
        """测试生成会话唯一标识"""
        key = get_session_key("user123", "chat456", "bot789")

        assert key == "user123:chat456:bot789"

    def test_get_session_key_different_inputs(self):
        """测试不同输入生成不同的 key"""
        key1 = get_session_key("user1", "chat1", "bot1")
        key2 = get_session_key("user2", "chat1", "bot1")
        key3 = get_session_key("user1", "chat2", "bot1")

        assert key1 != key2
        assert key1 != key3
        assert key2 != key3


class TestGetPendingRequests:
    """测试获取 pending 请求列表"""

    def test_get_pending_requests_empty(self):
        """测试获取空的 pending 请求列表"""
        from forward_service.routes.admin_commands import get_pending_requests

        _pending_requests.clear()

        result = get_pending_requests()

        assert len(result) == 0

    def test_get_pending_requests_with_data(self):
        """测试获取有数据的 pending 请求列表"""
        from forward_service.routes.admin_commands import get_pending_requests

        _pending_requests.clear()
        add_pending_request("req1", "Bot 1", "user1", "Message 1")
        add_pending_request("req2", "Bot 2", "user2", "A very long message that should be truncated by the function")

        result = get_pending_requests()

        assert len(result) == 2
        # 检查排序（按 elapsed_seconds 降序）
        assert all("elapsed_str" in r for r in result)
        assert all("bot_name" in r for r in result)

        _pending_requests.clear()


class TestCheckAgentsHealth:
    """测试 Agent 健康检查"""

    @pytest.mark.asyncio
    async def test_check_agents_health_empty(self):
        """测试没有 Bot 时的健康检查"""
        from forward_service.routes.admin_commands import check_agents_health

        with patch('forward_service.routes.admin_commands.config') as mock_config:
            mock_config.bots = {}

            result = await check_agents_health()

            assert "暂无" in result

    @pytest.mark.asyncio
    async def test_check_agents_health_disabled_bot(self):
        """测试禁用的 Bot 健康检查"""
        from forward_service.routes.admin_commands import check_agents_health

        mock_bot = MagicMock()
        mock_bot.name = "Disabled Bot"
        mock_bot.enabled = False

        with patch('forward_service.routes.admin_commands.config') as mock_config, \
             patch('forward_service.routes.admin_commands.httpx.AsyncClient') as mock_client:
            mock_config.bots = {"bot1": mock_bot}

            mock_client_instance = AsyncMock()
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_client_instance

            result = await check_agents_health()

            assert "已禁用" in result

    @pytest.mark.asyncio
    async def test_check_agents_health_success(self):
        """测试健康检查成功"""
        from forward_service.routes.admin_commands import check_agents_health
        import httpx

        mock_bot = MagicMock()
        mock_bot.name = "Test Bot"
        mock_bot.enabled = True
        mock_bot.forward_config = MagicMock()
        mock_bot.forward_config.get_url = MagicMock(return_value="https://api.test.com")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch('forward_service.routes.admin_commands.config') as mock_config, \
             patch('forward_service.routes.admin_commands.httpx.AsyncClient') as mock_client:
            mock_config.bots = {"bot1": mock_bot}

            mock_client_instance = AsyncMock()
            mock_client_instance.head = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_client_instance

            result = await check_agents_health()

            assert "Test Bot" in result
            assert "ms" in result

    @pytest.mark.asyncio
    async def test_check_agents_health_timeout(self):
        """测试健康检查超时"""
        from forward_service.routes.admin_commands import check_agents_health
        import httpx

        mock_bot = MagicMock()
        mock_bot.name = "Slow Bot"
        mock_bot.enabled = True
        mock_bot.forward_config = MagicMock()
        mock_bot.forward_config.get_url = MagicMock(return_value="https://api.slow.com")

        with patch('forward_service.routes.admin_commands.config') as mock_config, \
             patch('forward_service.routes.admin_commands.httpx.AsyncClient') as mock_client:
            mock_config.bots = {"bot1": mock_bot}

            mock_client_instance = AsyncMock()
            mock_client_instance.head = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_client_instance

            result = await check_agents_health()

            assert "超时" in result

    @pytest.mark.asyncio
    async def test_check_agents_health_server_error(self):
        """测试健康检查返回服务器错误"""
        from forward_service.routes.admin_commands import check_agents_health

        mock_bot = MagicMock()
        mock_bot.name = "Error Bot"
        mock_bot.enabled = True
        mock_bot.forward_config = MagicMock()
        mock_bot.forward_config.get_url = MagicMock(return_value="https://api.error.com")

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch('forward_service.routes.admin_commands.config') as mock_config, \
             patch('forward_service.routes.admin_commands.httpx.AsyncClient') as mock_client:
            mock_config.bots = {"bot1": mock_bot}

            mock_client_instance = AsyncMock()
            mock_client_instance.head = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_client_instance

            result = await check_agents_health()

            assert "HTTP 500" in result

    @pytest.mark.asyncio
    async def test_check_agents_health_no_url(self):
        """测试没有 URL 配置的 Bot"""
        from forward_service.routes.admin_commands import check_agents_health

        mock_bot = MagicMock()
        mock_bot.name = "No URL Bot"
        mock_bot.enabled = True
        mock_bot.forward_config = MagicMock()
        mock_bot.forward_config.get_url = MagicMock(return_value="")

        with patch('forward_service.routes.admin_commands.config') as mock_config, \
             patch('forward_service.routes.admin_commands.httpx.AsyncClient') as mock_client:
            mock_config.bots = {"bot1": mock_bot}

            mock_client_instance = AsyncMock()
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_client_instance

            result = await check_agents_health()

            assert "URL 未配置" in result


class TestGetPendingRequestsFormat:
    """测试 pending 请求的格式化"""

    def test_add_pending_request_truncates_long_message(self):
        """测试长消息被截断"""
        _pending_requests.clear()

        long_message = "A" * 100  # 超过 50 个字符
        add_pending_request("req1", "Bot", "user", long_message)

        assert "..." in _pending_requests["req1"]["message"]
        assert len(_pending_requests["req1"]["message"]) < 60

        _pending_requests.clear()

    def test_add_pending_request_keeps_short_message(self):
        """测试短消息不被截断"""
        _pending_requests.clear()

        short_message = "Hello"
        add_pending_request("req1", "Bot", "user", short_message)

        assert "..." not in _pending_requests["req1"]["message"]
        assert _pending_requests["req1"]["message"] == short_message

        _pending_requests.clear()
