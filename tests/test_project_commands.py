"""
项目命令处理单元测试

测试 project_commands.py 中的所有命令:
- /add-project
- /list-projects
- /use
- /set-default
- /remove-project
- /current-project
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from forward_service.routes.project_commands import (
    is_project_command,
    handle_project_command,
    handle_add_project,
    handle_list_projects,
    handle_use_project,
    handle_set_default,
    handle_remove_project,
    handle_current_project,
    ADD_PROJECT_RE,
    LIST_PROJECTS_RE,
    USE_PROJECT_RE,
    REMOVE_PROJECT_RE,
    CURRENT_PROJECT_RE,
)


class TestIsProjectCommand:
    """测试 is_project_command 函数"""

    def test_add_project_command(self):
        """测试识别 /add-project 命令"""
        assert is_project_command("/add-project test https://api.test.com")
        assert is_project_command("/add-project prod https://api.prod.com --api-key sk123")
        assert is_project_command("/add-project test https://api.test.com --default")

    def test_list_projects_command(self):
        """测试识别 /list-projects 命令"""
        assert is_project_command("/list-projects")
        assert is_project_command("/projects")
        assert is_project_command("/LIST-PROJECTS")  # 大小写不敏感

    def test_use_command(self):
        """测试识别 /use 命令"""
        assert is_project_command("/use test")
        assert is_project_command("/use prod")
        assert is_project_command("/USE test")  # 大小写不敏感

    def test_set_default_command(self):
        """测试识别 /set-default 命令"""
        assert is_project_command("/set-default test")
        assert is_project_command("/set-default prod")

    def test_remove_project_command(self):
        """测试识别 /remove-project 命令"""
        assert is_project_command("/remove-project test")
        assert is_project_command("/remove-project prod")

    def test_current_project_command(self):
        """测试识别 /current-project 命令"""
        assert is_project_command("/current-project")
        assert is_project_command("/current")

    def test_non_project_commands(self):
        """测试非项目命令不被识别"""
        assert not is_project_command("/help")
        assert not is_project_command("/reset")
        assert not is_project_command("/sess")
        assert not is_project_command("hello world")
        assert not is_project_command("")


class TestAddProjectRegex:
    """测试 /add-project 命令的正则匹配"""

    def test_basic_add_project(self):
        """测试基本的添加项目命令"""
        match = ADD_PROJECT_RE.match("/add-project test https://api.test.com")
        assert match is not None
        assert match.group(1) == "test"
        assert match.group(2) == "https://api.test.com"

    def test_add_project_with_api_key(self):
        """测试带 API Key 的添加项目命令"""
        match = ADD_PROJECT_RE.match("/add-project test https://api.test.com --api-key sk123")
        assert match is not None
        assert match.group(1) == "test"
        assert match.group(2) == "https://api.test.com"
        # 注意：正则可能需要调整才能正确捕获可选参数

    def test_add_project_with_default(self):
        """测试带 --default 的添加项目命令"""
        cmd = "/add-project test https://api.test.com --default"
        match = ADD_PROJECT_RE.match(cmd)
        assert match is not None


class TestHandleAddProject:
    """测试 handle_add_project 函数"""

    @pytest.mark.asyncio
    async def test_add_project_success(self, mock_db_manager):
        """测试成功添加项目"""
        success, message = await handle_add_project(
            bot_key="bot123",
            chat_id="user456",
            message="/add-project test https://api.test.com"
        )

        assert success is True
        assert "✅" in message
        assert "test" in message

    @pytest.mark.asyncio
    async def test_add_project_invalid_format(self, mock_db_manager):
        """测试无效格式的命令"""
        success, message = await handle_add_project(
            bot_key="bot123",
            chat_id="user456",
            message="/add-project"  # 缺少参数
        )

        assert success is False
        assert "❌" in message
        assert "格式错误" in message

    @pytest.mark.asyncio
    async def test_add_project_duplicate(self, mock_db_manager):
        """测试添加重复项目"""
        # 先添加一个项目
        await handle_add_project(
            bot_key="bot123",
            chat_id="user456",
            message="/add-project test https://api.test.com"
        )

        # 再次添加同名项目
        success, message = await handle_add_project(
            bot_key="bot123",
            chat_id="user456",
            message="/add-project test https://api2.test.com"
        )

        assert success is False
        assert "已存在" in message


class TestHandleListProjects:
    """测试 handle_list_projects 函数"""

    @pytest.mark.asyncio
    async def test_list_projects_empty(self, mock_db_manager):
        """测试列出空项目列表"""
        success, message = await handle_list_projects(
            bot_key="bot123",
            chat_id="user456"
        )

        assert success is True
        assert "📭" in message or "暂无" in message

    @pytest.mark.asyncio
    async def test_list_projects_with_data(self, mock_db_manager):
        """测试列出有项目的列表"""
        # 先添加项目
        await handle_add_project(
            bot_key="bot123",
            chat_id="user456",
            message="/add-project test https://api.test.com"
        )

        success, message = await handle_list_projects(
            bot_key="bot123",
            chat_id="user456"
        )

        assert success is True
        assert "test" in message
        assert "📋" in message or "项目" in message


class TestHandleUseProject:
    """测试 handle_use_project 函数"""

    @pytest.mark.asyncio
    async def test_use_existing_project(self, mock_db_manager):
        """测试切换到存在的项目"""
        # 先添加项目
        await handle_add_project(
            bot_key="bot123",
            chat_id="user456",
            message="/add-project test https://api.test.com"
        )

        success, message = await handle_use_project(
            bot_key="bot123",
            chat_id="user456",
            project_id="test"
        )

        assert success is True
        assert "✅" in message
        assert "切换" in message

    @pytest.mark.asyncio
    async def test_use_nonexistent_project(self, mock_db_manager):
        """测试切换到不存在的项目"""
        success, message = await handle_use_project(
            bot_key="bot123",
            chat_id="user456",
            project_id="nonexistent"
        )

        assert success is False
        assert "不存在" in message


class TestHandleSetDefault:
    """测试 handle_set_default 函数"""

    @pytest.mark.asyncio
    async def test_set_default_success(self, mock_db_manager):
        """测试成功设置默认项目"""
        # 先添加项目
        await handle_add_project(
            bot_key="bot123",
            chat_id="user456",
            message="/add-project test https://api.test.com"
        )

        success, message = await handle_set_default(
            bot_key="bot123",
            chat_id="user456",
            project_id="test"
        )

        assert success is True
        assert "✅" in message

    @pytest.mark.asyncio
    async def test_set_default_nonexistent(self, mock_db_manager):
        """测试设置不存在的项目为默认"""
        success, message = await handle_set_default(
            bot_key="bot123",
            chat_id="user456",
            project_id="nonexistent"
        )

        assert success is False
        assert "不存在" in message


class TestHandleRemoveProject:
    """测试 handle_remove_project 函数"""

    @pytest.mark.asyncio
    async def test_remove_existing_project(self, mock_db_manager):
        """测试删除存在的项目"""
        # 先添加项目
        await handle_add_project(
            bot_key="bot123",
            chat_id="user456",
            message="/add-project test https://api.test.com"
        )

        success, message = await handle_remove_project(
            bot_key="bot123",
            chat_id="user456",
            project_id="test"
        )

        assert success is True
        assert "✅" in message
        assert "删除" in message

    @pytest.mark.asyncio
    async def test_remove_nonexistent_project(self, mock_db_manager):
        """测试删除不存在的项目"""
        success, message = await handle_remove_project(
            bot_key="bot123",
            chat_id="user456",
            project_id="nonexistent"
        )

        assert success is False
        assert "不存在" in message


class TestHandleCurrentProject:
    """测试 handle_current_project 函数"""

    @pytest.mark.asyncio
    async def test_current_project_none(self, mock_db_manager):
        """测试没有默认项目时的显示"""
        success, message = await handle_current_project(
            bot_key="bot123",
            chat_id="user456"
        )

        assert success is True
        assert "📭" in message or "暂无" in message

    @pytest.mark.asyncio
    async def test_current_project_with_default(self, mock_db_manager):
        """测试有默认项目时的显示"""
        # 先添加项目并设为默认
        await handle_add_project(
            bot_key="bot123",
            chat_id="user456",
            message="/add-project test https://api.test.com --default"
        )

        success, message = await handle_current_project(
            bot_key="bot123",
            chat_id="user456"
        )

        assert success is True
        assert "test" in message


class TestHandleProjectCommand:
    """测试 handle_project_command 统一入口函数"""

    @pytest.mark.asyncio
    async def test_handle_add_project_command(self, mock_db_manager):
        """测试通过统一入口处理 add-project 命令"""
        success, message = await handle_project_command(
            bot_key="bot123",
            chat_id="user456",
            message="/add-project test https://api.test.com"
        )

        assert success is True

    @pytest.mark.asyncio
    async def test_handle_list_projects_command(self, mock_db_manager):
        """测试通过统一入口处理 list-projects 命令"""
        success, message = await handle_project_command(
            bot_key="bot123",
            chat_id="user456",
            message="/list-projects"
        )

        assert success is True

    @pytest.mark.asyncio
    async def test_handle_use_command(self, mock_db_manager):
        """测试通过统一入口处理 use 命令"""
        # 先添加项目
        await handle_add_project(
            bot_key="bot123",
            chat_id="user456",
            message="/add-project test https://api.test.com"
        )

        success, message = await handle_project_command(
            bot_key="bot123",
            chat_id="user456",
            message="/use test"
        )

        assert success is True

    @pytest.mark.asyncio
    async def test_handle_unknown_project_command(self, mock_db_manager):
        """测试未知的项目命令"""
        success, message = await handle_project_command(
            bot_key="bot123",
            chat_id="user456",
            message="/unknown-command"
        )

        assert success is False
        assert "未知" in message
