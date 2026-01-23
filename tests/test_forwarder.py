"""
消息转发服务单元测试

测试 forwarder.py 中的功能:
- get_forward_config_for_user
- forward_to_agent_with_bot
- forward_to_agent_with_user_project
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from dataclasses import dataclass

from forward_service.services.forwarder import (
    AgentResult,
    ForwardConfig,
    get_forward_config_for_user,
    forward_to_agent_with_bot,
    forward_to_agent_with_user_project,
)


class TestAgentResult:
    """测试 AgentResult 数据类"""

    def test_basic_agent_result(self):
        """测试基本的 AgentResult"""
        result = AgentResult(reply="Hello", msg_type="text")
        assert result.reply == "Hello"
        assert result.msg_type == "text"
        assert result.session_id is None
        assert result.project_id is None

    def test_agent_result_with_session(self):
        """测试带 session_id 的 AgentResult"""
        result = AgentResult(
            reply="Hello",
            msg_type="text",
            session_id="abc123",
            project_id="test"
        )
        assert result.session_id == "abc123"
        assert result.project_id == "test"


class TestForwardConfig:
    """测试 ForwardConfig 数据类"""

    def test_basic_forward_config(self):
        """测试基本的 ForwardConfig"""
        config = ForwardConfig(
            target_url="https://api.test.com/webhook",
            api_key="sk-test",
            timeout=60
        )
        assert config.target_url == "https://api.test.com/webhook"
        assert config.api_key == "sk-test"
        assert config.timeout == 60
        assert config.project_id is None

    def test_forward_config_get_url(self):
        """测试 ForwardConfig.get_url()"""
        config = ForwardConfig(
            target_url="https://api.test.com/webhook",
            api_key=None,
            timeout=60
        )
        assert config.get_url() == "https://api.test.com/webhook"


class TestGetForwardConfigForUser:
    """测试 get_forward_config_for_user 函数"""

    @pytest.mark.asyncio
    async def test_get_config_with_session_project(self, mock_db_manager):
        """测试获取会话指定的项目配置"""
        from forward_service.repository import get_user_project_repository
        
        # 先创建一个项目配置
        async with mock_db_manager.get_session() as session:
            repo = get_user_project_repository(session)
            await repo.create(
                bot_key="bot123",
                chat_id="user456",
                project_id="test",
                url_template="https://api.test.com/webhook",
                api_key="sk-test",
                timeout=60,
                is_default=False
            )

        # 获取配置（指定 current_project_id）
        config = await get_forward_config_for_user(
            bot_key="bot123",
            chat_id="user456",
            current_project_id="test"
        )

        assert config.target_url == "https://api.test.com/webhook"
        assert config.api_key == "sk-test"
        assert config.project_id == "test"

    @pytest.mark.asyncio
    async def test_get_config_with_default_project(self, mock_db_manager):
        """测试获取用户的默认项目配置"""
        from forward_service.repository import get_user_project_repository

        # 创建一个默认项目配置
        async with mock_db_manager.get_session() as session:
            repo = get_user_project_repository(session)
            await repo.create(
                bot_key="bot123",
                chat_id="user456",
                project_id="default_project",
                url_template="https://api.default.com/webhook",
                api_key="sk-default",
                timeout=120,
                is_default=True
            )

        # 获取配置（不指定 current_project_id，应返回默认项目）
        config = await get_forward_config_for_user(
            bot_key="bot123",
            chat_id="user456",
            current_project_id=None
        )

        assert config.target_url == "https://api.default.com/webhook"
        assert config.api_key == "sk-default"
        assert config.project_id == "default_project"
        assert config.timeout == 120

    @pytest.mark.asyncio
    async def test_get_config_fallback_to_bot(self, mock_db_manager):
        """测试回退到 Bot 配置"""
        # 创建一个 mock 的 bot 配置
        mock_bot = MagicMock()
        mock_bot.name = "Test Bot"
        mock_bot.forward_config = MagicMock()
        mock_bot.forward_config.target_url = "https://api.bot.com/webhook"
        mock_bot.forward_config.api_key = "sk-bot"
        mock_bot.forward_config.timeout = 30

        with patch(
            'forward_service.services.forwarder.config.get_bot_or_default_from_db',
            new_callable=AsyncMock
        ) as mock_get_bot:
            mock_get_bot.return_value = mock_bot

            # 获取配置（用户没有项目配置，应回退到 Bot 配置）
            config = await get_forward_config_for_user(
                bot_key="bot123",
                chat_id="user_no_projects",
                current_project_id=None
            )

            assert config.target_url == "https://api.bot.com/webhook"
            assert config.project_id is None


class TestForwardToAgentWithBot:
    """测试 forward_to_agent_with_bot 函数"""

    @pytest.mark.asyncio
    async def test_forward_success(self):
        """测试成功转发消息"""
        mock_bot = MagicMock()
        mock_bot.name = "Test Bot"
        mock_bot.forward_config = MagicMock()
        mock_bot.forward_config.get_url = MagicMock(return_value="https://api.test.com/webhook")
        mock_bot.forward_config.api_key = "sk-test"
        mock_bot.forward_config.timeout = 60

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={
            "response": "Hello from agent!",
            "sessionId": "session123"
        })

        with patch(
            'forward_service.services.forwarder.config.get_bot_or_default_from_db',
            new_callable=AsyncMock
        ) as mock_get_bot, patch(
            'forward_service.services.forwarder.httpx.AsyncClient'
        ) as mock_client_class:
            mock_get_bot.return_value = mock_bot

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await forward_to_agent_with_bot(
                bot_key="bot123",
                content="Hello",
                timeout=60,
                session_id=None
            )

            assert result is not None
            assert result.reply == "Hello from agent!"
            assert result.session_id == "session123"

    @pytest.mark.asyncio
    async def test_forward_no_bot(self):
        """测试没有 Bot 配置时返回 None"""
        with patch(
            'forward_service.services.forwarder.config.get_bot_or_default_from_db',
            new_callable=AsyncMock
        ) as mock_get_bot:
            mock_get_bot.return_value = None

            result = await forward_to_agent_with_bot(
                bot_key="nonexistent_bot",
                content="Hello",
                timeout=60
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_forward_timeout(self):
        """测试超时情况"""
        import httpx

        mock_bot = MagicMock()
        mock_bot.name = "Test Bot"
        mock_bot.forward_config = MagicMock()
        mock_bot.forward_config.get_url = MagicMock(return_value="https://api.test.com/webhook")
        mock_bot.forward_config.api_key = "sk-test"
        mock_bot.forward_config.timeout = 60

        with patch(
            'forward_service.services.forwarder.config.get_bot_or_default_from_db',
            new_callable=AsyncMock
        ) as mock_get_bot, patch(
            'forward_service.services.forwarder.httpx.AsyncClient'
        ) as mock_client_class:
            mock_get_bot.return_value = mock_bot

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await forward_to_agent_with_bot(
                bot_key="bot123",
                content="Hello",
                timeout=60
            )

            assert result is not None
            assert "超时" in result.reply

    @pytest.mark.asyncio
    async def test_forward_error_response(self):
        """测试错误响应"""
        mock_bot = MagicMock()
        mock_bot.name = "Test Bot"
        mock_bot.forward_config = MagicMock()
        mock_bot.forward_config.get_url = MagicMock(return_value="https://api.test.com/webhook")
        mock_bot.forward_config.api_key = "sk-test"
        mock_bot.forward_config.timeout = 60

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch(
            'forward_service.services.forwarder.config.get_bot_or_default_from_db',
            new_callable=AsyncMock
        ) as mock_get_bot, patch(
            'forward_service.services.forwarder.httpx.AsyncClient'
        ) as mock_client_class:
            mock_get_bot.return_value = mock_bot

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await forward_to_agent_with_bot(
                bot_key="bot123",
                content="Hello",
                timeout=60
            )

            assert result is not None
            assert "500" in result.reply


class TestForwardToAgentWithUserProject:
    """测试 forward_to_agent_with_user_project 函数"""

    @pytest.mark.asyncio
    async def test_forward_with_user_project_success(self, mock_db_manager):
        """测试使用用户项目配置成功转发"""
        from forward_service.repository import get_user_project_repository

        # 创建用户项目配置
        async with mock_db_manager.get_session() as session:
            repo = get_user_project_repository(session)
            await repo.create(
                bot_key="bot123",
                chat_id="user456",
                project_id="my_project",
                url_template="https://api.myproject.com/webhook",
                api_key="sk-myproject",
                timeout=90,
                is_default=True
            )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={
            "response": "Response from my project!",
            "sessionId": "proj_session_123"
        })

        with patch(
            'forward_service.services.forwarder.httpx.AsyncClient'
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await forward_to_agent_with_user_project(
                bot_key="bot123",
                chat_id="user456",
                content="Hello from user project test",
                timeout=60,
                session_id=None,
                current_project_id=None  # 应该自动使用默认项目
            )

            assert result is not None
            assert result.reply == "Response from my project!"
            assert result.project_id == "my_project"

    @pytest.mark.asyncio
    async def test_forward_with_specific_project(self, mock_db_manager):
        """测试使用指定的项目配置转发"""
        from forward_service.repository import get_user_project_repository

        # 创建多个用户项目配置
        async with mock_db_manager.get_session() as session:
            repo = get_user_project_repository(session)
            await repo.create(
                bot_key="bot123",
                chat_id="user456",
                project_id="prod",
                url_template="https://api.prod.com/webhook",
                api_key="sk-prod",
                timeout=120,
                is_default=True
            )
            await repo.create(
                bot_key="bot123",
                chat_id="user456",
                project_id="test",
                url_template="https://api.test.com/webhook",
                api_key="sk-test",
                timeout=60,
                is_default=False
            )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={
            "response": "Response from test project!",
            "sessionId": "test_session_123"
        })

        with patch(
            'forward_service.services.forwarder.httpx.AsyncClient'
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            # 明确指定使用 test 项目
            result = await forward_to_agent_with_user_project(
                bot_key="bot123",
                chat_id="user456",
                content="Hello from test",
                timeout=60,
                session_id=None,
                current_project_id="test"
            )

            assert result is not None
            assert result.project_id == "test"

    @pytest.mark.asyncio
    async def test_forward_timeout_with_user_project(self, mock_db_manager):
        """测试用户项目转发超时"""
        import httpx
        from forward_service.repository import get_user_project_repository

        # 创建用户项目配置
        async with mock_db_manager.get_session() as session:
            repo = get_user_project_repository(session)
            await repo.create(
                bot_key="bot123",
                chat_id="user456",
                project_id="slow_project",
                url_template="https://api.slow.com/webhook",
                api_key="sk-slow",
                timeout=60,
                is_default=True
            )

        with patch(
            'forward_service.services.forwarder.httpx.AsyncClient'
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await forward_to_agent_with_user_project(
                bot_key="bot123",
                chat_id="user456",
                content="Hello",
                timeout=60
            )

            assert result is not None
            assert "超时" in result.reply
            assert result.project_id == "slow_project"
