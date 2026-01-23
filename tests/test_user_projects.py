"""
用户项目配置功能单元测试

测试 UserProjectConfig Repository 的所有功能
"""
import pytest
from datetime import datetime

from forward_service.models import UserProjectConfig
from forward_service.repository import get_user_project_repository


class TestUserProjectConfigRepository:
    """测试 UserProjectConfigRepository"""

    @pytest.fixture
    def repo(self, test_db_session):
        """创建 Repository 实例"""
        return get_user_project_repository(test_db_session)

    @pytest.mark.asyncio
    async def test_create_user_project(self, repo, test_db_session):
        """测试创建用户项目配置"""
        project = await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="test",
            url_template="https://api.test.com/webhook",
            api_key="sk-test",
            project_name="测试环境",
            timeout=60,
            is_default=False,
            enabled=True
        )

        assert project.id is not None
        assert project.bot_key == "bot1"
        assert project.chat_id == "user123"
        assert project.project_id == "test"
        assert project.url_template == "https://api.test.com/webhook"
        assert project.api_key == "sk-test"
        assert project.project_name == "测试环境"
        assert project.timeout == 60
        assert project.is_default is False

    @pytest.mark.asyncio
    async def test_create_multiple_projects_with_default(self, repo, test_db_session):
        """测试创建多个项目，自动管理默认标记"""
        # 创建第一个项目并设为默认
        project1 = await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="project1",
            url_template="https://api1.test.com",
            is_default=True
        )

        # 创建第二个项目并设为默认（第一个项目的默认标记应该被清除）
        project2 = await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="project2",
            url_template="https://api2.test.com",
            is_default=True
        )

        await test_db_session.refresh(project1)
        await test_db_session.refresh(project2)

        assert project1.is_default is False
        assert project2.is_default is True

    @pytest.mark.asyncio
    async def test_get_by_project_id(self, repo):
        """测试根据 project_id 获取配置"""
        # 先创建一个配置
        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="test_project",
            url_template="https://api.test.com"
        )

        # 查询
        found = await repo.get_by_project_id("bot1", "user123", "test_project")

        assert found is not None
        assert found.project_id == "test_project"
        assert found.url_template == "https://api.test.com"

    @pytest.mark.asyncio
    async def test_get_by_project_id_not_found(self, repo):
        """测试查询不存在的配置"""
        found = await repo.get_by_project_id("bot1", "user999", "nonexistent")
        assert found is None

    @pytest.mark.asyncio
    async def test_get_user_projects(self, repo):
        """测试获取用户的所有项目"""
        # 创建多个项目
        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="project1",
            url_template="https://api1.test.com"
        )
        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="project2",
            url_template="https://api2.test.com"
        )
        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="project3",
            url_template="https://api3.test.com",
            enabled=False  # 禁用该项目
        )

        # 查询所有项目（包括禁用的）
        all_projects = await repo.get_user_projects("bot1", "user123", enabled_only=False)
        assert len(all_projects) == 3

        # 只查询启用的项目
        enabled_projects = await repo.get_user_projects("bot1", "user123", enabled_only=True)
        assert len(enabled_projects) == 2

    @pytest.mark.asyncio
    async def test_get_default_project(self, repo):
        """测试获取默认项目"""
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
            project_id="project2",
            url_template="https://api2.test.com",
            is_default=True
        )

        # 查询默认项目
        default = await repo.get_default_project("bot1", "user123")

        assert default is not None
        assert default.project_id == "project2"
        assert default.is_default is True

    @pytest.mark.asyncio
    async def test_update_user_project(self, repo):
        """测试更新项目配置"""
        # 创建项目
        project = await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="test",
            url_template="https://api.test.com",
            api_key="old-key"
        )

        # 更新配置
        updated = await repo.update(
            config_id=project.id,
            url_template="https://new-api.test.com",
            api_key="new-key",
            project_name="新名称",
            timeout=120
        )

        assert updated is not None
        assert updated.url_template == "https://new-api.test.com"
        assert updated.api_key == "new-key"
        assert updated.project_name == "新名称"
        assert updated.timeout == 120

    @pytest.mark.asyncio
    async def test_delete_user_project(self, repo):
        """测试删除项目配置"""
        # 创建项目
        project = await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="test",
            url_template="https://api.test.com"
        )

        # 删除项目
        success = await repo.delete(project.id)
        assert success is True

        # 验证已删除
        found = await repo.get_by_project_id("bot1", "user123", "test")
        assert found is None

    @pytest.mark.asyncio
    async def test_delete_by_project_id(self, repo):
        """测试根据 project_id 删除配置"""
        # 创建项目
        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="test",
            url_template="https://api.test.com"
        )

        # 删除
        success = await repo.delete_by_project_id("bot1", "user123", "test")
        assert success is True

        # 验证已删除
        found = await repo.get_by_project_id("bot1", "user123", "test")
        assert found is None

    @pytest.mark.asyncio
    async def test_set_default(self, repo):
        """测试设置默认项目"""
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

        # 将 project2 设为默认
        success = await repo.set_default("bot1", "user123", "project2")
        assert success is True

        # 验证
        default = await repo.get_default_project("bot1", "user123")
        assert default.project_id == "project2"

    @pytest.mark.asyncio
    async def test_count_user_projects(self, repo):
        """测试统计用户项目数量"""
        # 创建多个项目
        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="project1",
            url_template="https://api1.test.com"
        )
        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="project2",
            url_template="https://api2.test.com"
        )
        await repo.create(
            bot_key="bot1",
            chat_id="user123",
            project_id="project3",
            url_template="https://api3.test.com",
            enabled=False
        )

        # 统计所有项目
        all_count = await repo.count_user_projects("bot1", "user123", enabled_only=False)
        assert all_count == 3

        # 只统计启用的项目
        enabled_count = await repo.count_user_projects("bot1", "user123", enabled_only=True)
        assert enabled_count == 2
