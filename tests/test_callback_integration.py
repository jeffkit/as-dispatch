"""
callback.py 集成测试

测试 handle_callback 函数的各种场景
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from forward_service.config import BotConfig, ForwardConfig, AccessControl
from forward_service.services.forwarder import AgentResult
from forward_service.utils.content import ExtractedContent


class MockRequest:
    """模拟 FastAPI Request 对象"""
    
    def __init__(self, data: dict):
        self._data = data
    
    async def json(self):
        return self._data


def create_callback_data(
    chat_id: str = "test_chat_123",
    msg_type: str = "text",
    content: str = "hello world",
    user_id: str = "user_123",
    user_name: str = "Test User",
    webhook_url: str = "http://in.qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test_bot_key",
    image_url: str = None
) -> dict:
    """创建测试用的回调数据"""
    data = {
        "chatid": chat_id,
        "chattype": "group",
        "msgtype": msg_type,
        "from": {
            "userid": user_id,
            "name": user_name,
            "alias": ""
        },
        "webhook_url": webhook_url,
    }
    
    if msg_type == "text":
        data["text"] = {"content": f"@Bot {content}"}
    elif msg_type == "image":
        data["image"] = {"url": image_url or "http://example.com/image.jpg"}
    elif msg_type == "event":
        data["event"] = {"type": "enter_chat"}
    
    return data


def create_mock_bot(
    name: str = "Test Bot",
    bot_key: str = "test_bot_key",
    url: str = "https://api.test.com/messages",
    api_key: str = "test_api_key",
    enabled: bool = True,
    access_mode: str = "allow_all"
) -> BotConfig:
    """创建测试用的 Bot 配置"""
    forward_config = ForwardConfig(
        target_url=url,
        api_key=api_key,
        timeout=60
    )
    access_control = AccessControl(
        mode=access_mode,
        whitelist=[],
        blacklist=[]
    )
    return BotConfig(
        name=name,
        bot_key=bot_key,
        enabled=enabled,
        forward_config=forward_config,
        access_control=access_control
    )


@pytest.fixture
def mock_db_manager():
    """创建 mock 数据库管理器"""
    from contextlib import asynccontextmanager
    
    manager = MagicMock()
    
    # 创建异步上下文管理器
    @asynccontextmanager
    async def mock_get_session():
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))))
        mock_session.commit = AsyncMock()
        mock_session.flush = AsyncMock()
        yield mock_session
    
    manager.get_session = mock_get_session
    return manager


class TestHandleCallbackAuth:
    """测试回调认证"""

    @pytest.mark.asyncio
    async def test_auth_success(self, mock_db_manager):
        """测试认证成功"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()
        
        # 创建 mock session manager（混合同步/异步方法）
        mock_session_mgr = MagicMock()
        mock_session_mgr.get_active_session = AsyncMock(return_value=None)
        mock_session_mgr.parse_slash_command = MagicMock(return_value=None)  # 同步方法
        mock_session_mgr.record_session = AsyncMock(return_value=None)  # 异步方法

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract, \
             patch('forward_service.routes.callback.forward_to_agent_with_bot') as mock_forward, \
             patch('forward_service.routes.callback.add_pending_request') as mock_add_pending, \
             patch('forward_service.routes.callback.remove_pending_request') as mock_remove_pending, \
             patch('forward_service.routes.callback.get_session_manager', return_value=mock_session_mgr):
            
            mock_config.callback_auth_key = "x-api-key"
            mock_config.callback_auth_value = "test_secret"
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default = MagicMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ExtractedContent(text="Hello", image_urls=[])
            mock_forward.return_value = AgentResult(
                reply="Hi!", msg_type="text", session_id="sess_123", project_id=None
            )
            mock_send.return_value = {"success": True}

            # 使用正确的 auth header
            request = MockRequest(create_callback_data(content="Hello"))
            result = await handle_callback(request, x_api_key="test_secret")

            assert result["errcode"] == 0

    @pytest.mark.asyncio
    async def test_auth_failure(self, mock_db_manager):
        """测试认证失败"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)

        with patch('forward_service.routes.callback.config') as mock_config:
            mock_config.callback_auth_key = "x-api-key"
            mock_config.callback_auth_value = "correct_secret"

            request = MockRequest(create_callback_data())
            result = await handle_callback(request, x_api_key="wrong_secret")

            assert result["errcode"] == 401


class TestHandleCallbackEvents:
    """测试事件类型处理"""

    @pytest.mark.asyncio
    async def test_ignore_event_type(self, mock_db_manager):
        """测试忽略事件类型"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)

        with patch('forward_service.routes.callback.config') as mock_config:
            mock_config.callback_auth_key = None

            request = MockRequest(create_callback_data(msg_type="event"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert result["errmsg"] == "ok"


class TestHandleCallbackBotConfig:
    """测试 Bot 配置处理"""

    @pytest.mark.asyncio
    async def test_no_bot_config(self, mock_db_manager):
        """测试无 Bot 配置"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send:
            
            mock_config.callback_auth_key = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="unknown_key")
            mock_config.get_bot_or_default = MagicMock(return_value=None)
            mock_send.return_value = {"success": True}

            request = MockRequest(create_callback_data())
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert "no bot config" in result["errmsg"]


class TestHandleCallbackAccessControl:
    """测试访问控制"""

    @pytest.mark.asyncio
    async def test_access_denied(self, mock_db_manager):
        """测试访问被拒绝"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot(access_mode="whitelist")

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send:
            
            mock_config.callback_auth_key = None
            mock_config.default_bot_key = "default"
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default = MagicMock(return_value=mock_bot)
            mock_config.get_bot = MagicMock(return_value=None)  # 无默认 bot
            mock_config.check_access = MagicMock(return_value=(False, "Not in whitelist"))
            mock_send.return_value = {"success": True}

            request = MockRequest(create_callback_data())
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert "access denied" in result["errmsg"]


class TestHandleCallbackSlashCommands:
    """测试斜杠命令"""

    @pytest.mark.asyncio
    async def test_reset_command(self, mock_db_manager):
        """测试 /r 重置命令"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()
        
        # 创建 mock session manager（混合同步/异步方法）
        mock_sm = MagicMock()
        mock_sm.get_active_session = AsyncMock(return_value=None)
        mock_sm.parse_slash_command = MagicMock(return_value=("reset", None, None))  # 同步方法
        mock_sm.reset_session = AsyncMock(return_value=True)

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract, \
             patch('forward_service.routes.callback.get_session_manager', return_value=mock_sm):
            
            mock_config.callback_auth_key = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default = MagicMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ExtractedContent(text="/r", image_urls=[])
            mock_send.return_value = {"success": True}

            request = MockRequest(create_callback_data(content="/r"))
            result = await handle_callback(request)

            assert result["errcode"] == 0

    @pytest.mark.asyncio
    async def test_sess_command(self, mock_db_manager):
        """测试 /s 会话列表命令"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()
        
        # 创建 mock session manager（混合同步/异步方法）
        mock_sm = MagicMock()
        mock_sm.get_active_session = AsyncMock(return_value=None)
        mock_sm.parse_slash_command = MagicMock(return_value=("list", None, None))  # 同步方法
        mock_sm.list_sessions = AsyncMock(return_value=[])
        mock_sm.format_session_list = MagicMock(return_value="No sessions")  # 同步方法

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract, \
             patch('forward_service.routes.callback.get_session_manager', return_value=mock_sm):
            
            mock_config.callback_auth_key = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default = MagicMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ExtractedContent(text="/s", image_urls=[])
            mock_send.return_value = {"success": True}

            request = MockRequest(create_callback_data(content="/s"))
            result = await handle_callback(request)

            assert result["errcode"] == 0


class TestHandleCallbackForward:
    """测试消息转发"""

    @pytest.mark.asyncio
    async def test_forward_success(self, mock_db_manager):
        """测试成功转发消息"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()
        mock_result = AgentResult(
            reply="Hello from Agent!",
            msg_type="text",
            session_id="session_123456789",
            project_id=None
        )

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract, \
             patch('forward_service.routes.callback.forward_to_agent_with_bot') as mock_forward, \
             patch('forward_service.routes.callback.add_request_log') as mock_add_log, \
             patch('forward_service.routes.callback.update_request_log') as mock_update_log, \
             patch('forward_service.routes.callback.add_pending_request') as mock_add_pending, \
             patch('forward_service.routes.callback.remove_pending_request') as mock_remove_pending:
            
            mock_config.callback_auth_key = None
            mock_config.timeout = 60
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default = MagicMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ExtractedContent(text="Hello", image_urls=[])
            mock_forward.return_value = mock_result
            mock_send.return_value = {"success": True}
            mock_add_log.return_value = 1

            request = MockRequest(create_callback_data(content="Hello"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert result["errmsg"] == "ok"
            mock_forward.assert_called_once()
            mock_send.assert_called()

    @pytest.mark.asyncio
    async def test_forward_failure(self, mock_db_manager):
        """测试转发失败"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract, \
             patch('forward_service.routes.callback.forward_to_agent_with_bot') as mock_forward, \
             patch('forward_service.routes.callback.add_request_log') as mock_add_log, \
             patch('forward_service.routes.callback.update_request_log') as mock_update_log, \
             patch('forward_service.routes.callback.add_pending_request') as mock_add_pending, \
             patch('forward_service.routes.callback.remove_pending_request') as mock_remove_pending:
            
            mock_config.callback_auth_key = None
            mock_config.timeout = 60
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default = MagicMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ExtractedContent(text="Hello", image_urls=[])
            mock_forward.return_value = None  # 转发失败
            mock_send.return_value = {"success": True}
            mock_add_log.return_value = 1

            request = MockRequest(create_callback_data(content="Hello"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            assert "forward failed" in result["errmsg"]


class TestHandleCallbackAdminCommands:
    """测试管理员命令"""

    @pytest.mark.asyncio
    async def test_help_command_admin(self, mock_db_manager):
        """测试管理员 /help 命令"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract, \
             patch('forward_service.routes.callback.check_is_admin') as mock_check_admin, \
             patch('forward_service.routes.callback.get_admin_full_help') as mock_admin_help:
            
            mock_config.callback_auth_key = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default = MagicMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ExtractedContent(text="/help", image_urls=[])
            mock_check_admin.return_value = True
            mock_admin_help.return_value = "Admin Help"
            mock_send.return_value = {"success": True}

            request = MockRequest(create_callback_data(content="/help"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            mock_admin_help.assert_called_once()

    @pytest.mark.asyncio
    async def test_help_command_regular_user(self, mock_db_manager):
        """测试普通用户 /help 命令"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract, \
             patch('forward_service.routes.callback.check_is_admin') as mock_check_admin, \
             patch('forward_service.routes.callback.get_regular_user_help') as mock_user_help:
            
            mock_config.callback_auth_key = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default = MagicMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ExtractedContent(text="/help", image_urls=[])
            mock_check_admin.return_value = False
            mock_user_help.return_value = "User Help"
            mock_send.return_value = {"success": True}

            request = MockRequest(create_callback_data(content="/help"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            mock_user_help.assert_called_once()


class TestHandleCallbackExceptions:
    """测试异常处理"""

    @pytest.mark.asyncio
    async def test_json_parse_error(self, mock_db_manager):
        """测试 JSON 解析错误"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)

        class BadRequest:
            async def json(self):
                raise ValueError("Invalid JSON")

        with patch('forward_service.routes.callback.config') as mock_config:
            mock_config.callback_auth_key = None

            request = BadRequest()
            result = await handle_callback(request)

            assert result["errcode"] == -1  # 内部错误返回 -1


class TestHandleCallbackProjectCommands:
    """测试项目命令"""

    @pytest.mark.asyncio
    async def test_project_command_routing(self, mock_db_manager):
        """测试项目命令路由"""
        from forward_service.routes.callback import handle_callback
        from forward_service.session_manager import init_session_manager

        init_session_manager(mock_db_manager)
        mock_bot = create_mock_bot()

        with patch('forward_service.routes.callback.config') as mock_config, \
             patch('forward_service.routes.callback.send_reply') as mock_send, \
             patch('forward_service.routes.callback.extract_content') as mock_extract, \
             patch('forward_service.routes.callback.is_project_command') as mock_is_proj, \
             patch('forward_service.routes.callback.handle_project_command') as mock_handle_proj:
            
            mock_config.callback_auth_key = None
            mock_config.extract_bot_key_from_webhook_url = MagicMock(return_value="test_key")
            mock_config.get_bot_or_default = MagicMock(return_value=mock_bot)
            mock_config.check_access = MagicMock(return_value=(True, ""))
            mock_extract.return_value = ExtractedContent(text="/lp", image_urls=[])
            mock_is_proj.return_value = True
            mock_handle_proj.return_value = (True, "Projects list")  # 返回 (success, message) 元组
            mock_send.return_value = {"success": True}

            request = MockRequest(create_callback_data(content="/lp"))
            result = await handle_callback(request)

            assert result["errcode"] == 0
            mock_is_proj.assert_called()
