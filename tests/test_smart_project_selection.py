"""
测试智能项目选择功能

测试 forwarder.py 中的 get_forward_config_for_user 智能选择逻辑
以及 project_commands.py 中首个项目自动设为默认的功能
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from contextlib import asynccontextmanager

from forward_service.services.forwarder import get_forward_config_for_user, ForwardConfig
from forward_service.routes.project_commands import handle_add_project
from forward_service.repository import get_user_project_repository


def mock_db_session(test_db_session):
    """创建一个 Mock 数据库会话的上下文管理器"""
    @asynccontextmanager
    async def mock_get_session():
        yield test_db_session

    return mock_get_session


class TestSmartProjectSelection:
    """测试智能项目选择逻辑"""

    @pytest.mark.asyncio
    async def test_single_project_auto_selection(self, test_db_session):
        """测试只有一个项目时自动选择"""
        repo = get_user_project_repository(test_db_session)

        # 创建唯一项目（未设为默认）
        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="only_project",
            url_template="https://api.test.com",
            api_key="sk-test",
            is_default=False,  # 未设为默认
            enabled=True
        )
        await test_db_session.commit()

        # 测试智能选择
        with patch('forward_service.services.forwarder.get_db_manager') as mock_db_manager:
            mock_db_manager.return_value.get_session = mock_db_session(test_db_session)

            with patch('forward_service.services.forwarder.config') as mock_config:
                # Mock bot 没有 target_url
                mock_bot = MagicMock()
                mock_bot.forward_config.target_url = None
                mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)

                config = await get_forward_config_for_user("bot1", "user123")

                # 应该自动选择唯一的项目
                assert config.project_id == "only_project"
                assert config.target_url == "https://api.test.com"
                assert config.api_key == "sk-test"

    @pytest.mark.asyncio
    async def test_multiple_projects_select_latest(self, test_db_session):
        """测试多个项目时选择最近添加的"""
        repo = get_user_project_repository(test_db_session)

        # 创建多个项目（都未设为默认）
        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="project1",
            url_template="https://api1.test.com",
            is_default=False
        )

        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="project2",
            url_template="https://api2.test.com",
            is_default=False
        )

        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="project3",
            url_template="https://api3.test.com",
            is_default=False
        )
        await test_db_session.commit()

        # 测试智能选择
        with patch('forward_service.services.forwarder.get_db_manager') as mock_db_manager:
            mock_db_manager.return_value.get_session = mock_db_session(test_db_session)

            with patch('forward_service.services.forwarder.config') as mock_config:
                mock_bot = MagicMock()
                mock_bot.forward_config.target_url = None
                mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)

                config = await get_forward_config_for_user("bot1", "user123")

                # 应该选择第一个项目（get_user_projects 按 is_default DESC, created_at ASC 排序）
                # 由于都是 is_default=False，所以按 created_at 升序排序，最早的是 project1
                assert config.project_id == "project1"

    @pytest.mark.asyncio
    async def test_default_project_priority(self, test_db_session):
        """测试默认项目优先级高于智能选择"""
        repo = get_user_project_repository(test_db_session)

        # 创建多个项目，其中一个设为默认
        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="project1",
            url_template="https://api1.test.com",
            is_default=False
        )

        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="default_project",
            url_template="https://api-default.test.com",
            is_default=True
        )

        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="project3",
            url_template="https://api3.test.com",
            is_default=False
        )
        await test_db_session.commit()

        # 测试选择
        with patch('forward_service.services.forwarder.get_db_manager') as mock_db_manager:
            mock_db_manager.return_value.get_session = mock_db_session(test_db_session)

            config = await get_forward_config_for_user("bot1", "user123")

            # 应该选择默认项目，而不是最新的项目
            assert config.project_id == "default_project"

    @pytest.mark.asyncio
    async def test_no_project_no_bot_url_raises_error(self, test_db_session):
        """测试没有项目且 Bot 没有 URL 时抛出异常"""
        # 用户没有任何项目
        with patch('forward_service.services.forwarder.get_db_manager') as mock_db_manager:
            mock_db_manager.return_value.get_session = mock_db_session(test_db_session)

            with patch('forward_service.services.forwarder.config') as mock_config:
                mock_bot = MagicMock()
                mock_bot.name = "Test Bot"
                mock_bot.forward_config.target_url = None  # Bot 也没有 URL
                mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)

                # 应该抛出 ValueError
                with pytest.raises(ValueError) as exc_info:
                    await get_forward_config_for_user("bot1", "user123")

                assert "无可用项目" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_no_project_with_bot_url_uses_bot(self, test_db_session):
        """测试没有项目但 Bot 有 URL 时使用 Bot 配置"""
        # 用户没有任何项目
        with patch('forward_service.services.forwarder.get_db_manager') as mock_db_manager:
            mock_db_manager.return_value.get_session = mock_db_session(test_db_session)

            with patch('forward_service.services.forwarder.config') as mock_config:
                mock_bot = MagicMock()
                mock_bot.name = "Test Bot"
                mock_bot.forward_config.target_url = "https://bot-api.test.com"
                mock_bot.forward_config.api_key = "bot-key"
                mock_bot.forward_config.timeout = 300
                mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)

                config = await get_forward_config_for_user("bot1", "user123")

                # 应该使用 Bot 配置
                assert config.target_url == "https://bot-api.test.com"
                assert config.api_key == "bot-key"
                assert config.timeout == 300
                assert config.project_id is None

    @pytest.mark.asyncio
    async def test_session_project_overrides_all(self, test_db_session):
        """测试会话指定的项目优先级最高"""
        repo = get_user_project_repository(test_db_session)

        # 创建多个项目
        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="default_project",
            url_template="https://api-default.test.com",
            is_default=True
        )

        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="session_project",
            url_template="https://api-session.test.com",
            is_default=False
        )
        await test_db_session.commit()

        # 测试会话指定项目
        with patch('forward_service.services.forwarder.get_db_manager') as mock_db_manager:
            mock_db_manager.return_value.get_session = mock_db_session(test_db_session)

            config = await get_forward_config_for_user(
                "bot1",
                "user123",
                current_project_id="session_project"
            )

            # 应该使用会话指定的项目，而不是默认项目
            assert config.project_id == "session_project"


class TestFirstProjectAutoDefault:
    """测试首个项目自动设为默认"""

    @pytest.mark.asyncio
    async def test_first_project_auto_default(self, test_db_session):
        """测试第一个项目自动设为默认"""
        repo = get_user_project_repository(test_db_session)

        # Mock _test_agent_connectivity 和数据库
        with patch('forward_service.routes.project_commands._test_agent_connectivity') as mock_test:
            mock_test.return_value = {"success": True}

            with patch('forward_service.routes.project_commands.get_db_manager') as mock_db_manager:
                mock_db_manager.return_value.get_session = mock_db_session(test_db_session)

                # 添加第一个项目
                success, message = await handle_add_project(
                    bot_key="bot1",
                    chat_id="user123",
                    message="/ap project1 https://api1.test.com --api-key sk-test"
                )

                assert success is True
                assert "已自动设为默认项目" in message
                assert "现在可以直接开始对话了" in message

                # 验证项目已设为默认
                project = await repo.get_by_project_id("bot1", "user123", "project1")
                assert project is not None
                assert project.is_default is True

    @pytest.mark.asyncio
    async def test_second_project_not_auto_default(self, test_db_session):
        """测试第二个项目不自动设为默认"""
        repo = get_user_project_repository(test_db_session)

        # 先创建第一个项目
        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="existing",
            url_template="https://api-existing.test.com",
            is_default=True
        )
        await test_db_session.commit()

        # Mock _test_agent_connectivity 和数据库
        with patch('forward_service.routes.project_commands._test_agent_connectivity') as mock_test:
            mock_test.return_value = {"success": True}

            with patch('forward_service.routes.project_commands.get_db_manager') as mock_db_manager:
                mock_db_manager.return_value.get_session = mock_db_session(test_db_session)

                # 添加第二个项目
                success, message = await handle_add_project(
                    bot_key="bot1",
                    chat_id="user123",
                    message="/ap project2 https://api2.test.com --api-key sk-test"
                )

                assert success is True
                assert "已自动设为默认项目" not in message
                assert "使用 `/use" in message

                # 验证第二个项目未设为默认
                project2 = await repo.get_by_project_id("bot1", "user123", "project2")
                assert project2 is not None
                assert project2.is_default is False

                # 验证第一个项目仍然是默认
                existing = await repo.get_by_project_id("bot1", "user123", "existing")
                assert existing.is_default is True

    @pytest.mark.asyncio
    async def test_first_project_different_users_independent(self, test_db_session):
        """测试不同用户的首个项目独立管理"""
        repo = get_user_project_repository(test_db_session)

        # Mock _test_agent_connectivity 和数据库
        with patch('forward_service.routes.project_commands._test_agent_connectivity') as mock_test:
            mock_test.return_value = {"success": True}

            with patch('forward_service.routes.project_commands.get_db_manager') as mock_db_manager:
                mock_db_manager.return_value.get_session = mock_db_session(test_db_session)

                # 用户1添加第一个项目
                success1, message1 = await handle_add_project(
                    bot_key="bot1",
                    chat_id="user1",
                    message="/ap project1 https://api1.test.com"
                )

                # 用户2也添加第一个项目
                success2, message2 = await handle_add_project(
                    bot_key="bot1",
                    chat_id="user2",
                    message="/ap project1 https://api1.test.com"
                )

                assert success1 is True
                assert success2 is True

                # 验证两个用户的项目都设为默认
                user1_project = await repo.get_by_project_id("bot1", "user1", "project1")
                user2_project = await repo.get_by_project_id("bot1", "user2", "project1")

                assert user1_project.is_default is True
                assert user2_project.is_default is True


class TestRegressionTests:
    """回归测试：确保修改不影响现有功能"""

    @pytest.mark.asyncio
    async def test_manual_use_command_still_works(self, test_db_session):
        """测试手动 /use 命令仍然有效"""
        repo = get_user_project_repository(test_db_session)

        # 创建多个项目
        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="project1",
            url_template="https://api1.test.com",
            is_default=True
        )

        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="project2",
            url_template="https://api2.test.com",
            is_default=False
        )
        await test_db_session.commit()

        # 手动设置默认项目
        success = await repo.set_default("bot1", "user123", "project2")
        assert success is True

        # 验证 project2 是默认
        default = await repo.get_default_project("bot1", "user123")
        assert default.project_id == "project2"

        # 验证 get_forward_config_for_user 使用新的默认项目
        with patch('forward_service.services.forwarder.get_db_manager') as mock_db_manager:
            mock_db_manager.return_value.get_session = mock_db_session(test_db_session)

            config = await get_forward_config_for_user("bot1", "user123")
            assert config.project_id == "project2"

    @pytest.mark.asyncio
    async def test_disabled_projects_not_selected(self, test_db_session):
        """测试禁用的项目不会被智能选择"""
        repo = get_user_project_repository(test_db_session)

        # 创建一个禁用的项目
        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="disabled",
            url_template="https://api-disabled.test.com",
            is_default=False,
            enabled=False
        )

        # 创建一个启用的项目
        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="enabled",
            url_template="https://api-enabled.test.com",
            is_default=False,
            enabled=True
        )
        await test_db_session.commit()

        # 测试智能选择
        with patch('forward_service.services.forwarder.get_db_manager') as mock_db_manager:
            mock_db_manager.return_value.get_session = mock_db_session(test_db_session)

            with patch('forward_service.services.forwarder.config') as mock_config:
                mock_bot = MagicMock()
                mock_bot.forward_config.target_url = None
                mock_config.get_bot_or_default_from_db = AsyncMock(return_value=mock_bot)

                config = await get_forward_config_for_user("bot1", "user123")

                # 应该选择启用的项目，而不是禁用的项目
                assert config.project_id == "enabled"
