"""
企业微信智能机器人路由集成测试

测试内容:
- 智能机器人回调接口
- 消息处理流程
- Slash 命令处理
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from forward_service.config import BotConfig, ForwardConfig, AccessControl


def create_mock_bot(
    name: str = "测试智能机器人",
    bot_key: str = "test-bot",
    platform: str = "wecom-intelligent",
    url: str = "https://api.test.com/messages",
) -> BotConfig:
    """创建测试用的 Bot 配置"""
    forward_config = ForwardConfig(
        target_url=url,
        api_key="test_api_key",
        timeout=60
    )
    access_control = AccessControl(
        mode="allow_all",
        whitelist=[],
        blacklist=[]
    )
    bot = BotConfig(
        name=name,
        bot_key=bot_key,
        enabled=True,
        forward_config=forward_config,
        access_control=access_control
    )
    # 添加 platform 属性
    bot.platform = platform
    return bot


@pytest.mark.asyncio
class TestIntelligentRoute:
    """测试智能机器人路由"""
    
    async def test_intelligent_callback_success(self):
        """测试成功处理智能机器人回调"""
        with patch('forward_service.routes.intelligent.config') as mock_config, \
             patch('forward_service.routes.intelligent.get_session_manager') as mock_get_sm, \
             patch('forward_service.routes.intelligent.forward_to_agent_with_user_project') as mock_forward:
            
            # Mock Bot 配置
            mock_bot = create_mock_bot()
            mock_config.get_bot_or_default.return_value = mock_bot
            mock_config.timeout = 60
            
            # Mock 会话管理器
            mock_sm = MagicMock()
            mock_session = MagicMock()
            mock_session.session_id = "session_123"
            mock_session.current_project_id = None
            mock_sm.get_active_session.return_value = mock_session
            mock_sm.parse_slash_command.return_value = None
            mock_sm.record_session = AsyncMock()
            mock_get_sm.return_value = mock_sm
            
            # Mock 转发结果
            mock_result = MagicMock()
            mock_result.reply = "你好！我是智能助手"
            mock_result.session_id = "new_session_456"
            mock_forward.return_value = mock_result
            
            # 导入 app（在 mock 之后）
            from forward_service.app import app
            from fastapi.testclient import TestClient
            
            client = TestClient(app)
            
            # 模拟企微回调
            xml = """<xml>
    <ToUserName><![CDATA[ww123]]></ToUserName>
    <FromUserName><![CDATA[user123]]></FromUserName>
    <CreateTime>1234567890</CreateTime>
    <MsgType><![CDATA[text]]></MsgType>
    <Content><![CDATA[你好]]></Content>
    <MsgId>1234567890123456</MsgId>
</xml>"""
            
            response = client.post(
                "/callback/intelligent/test-bot",
                content=xml,
                headers={"Content-Type": "text/xml"}
            )
            
            assert response.status_code == 200
            assert "application/xml" in response.headers["content-type"]
            
            # 验证响应是 XML
            response_xml = response.text
            assert "<xml>" in response_xml
            assert "<MsgType><![CDATA[stream]]></MsgType>" in response_xml
            assert "<Stream>" in response_xml
            assert "你好！我是智能助手" in response_xml
            
            # 验证调用了转发器
            mock_forward.assert_called_once()
            
            # 验证记录了会话
            mock_sm.record_session.assert_called_once()
    
    async def test_intelligent_callback_slash_command(self, mock_config, mock_session_manager):
        """测试处理 Slash 命令"""
        from forward_service.app import app
        
        client = TestClient(app)
        
        # Mock 命令解析
        mock_session_manager.parse_slash_command.return_value = ("reset", None, None)
        mock_session_manager.reset_session.return_value = True
        
        xml = """<xml>
    <ToUserName><![CDATA[ww123]]></ToUserName>
    <FromUserName><![CDATA[user123]]></FromUserName>
    <CreateTime>1234567890</CreateTime>
    <MsgType><![CDATA[text]]></MsgType>
    <Content><![CDATA[/reset]]></Content>
    <MsgId>123</MsgId>
</xml>"""
        
        response = client.post(
            "/callback/intelligent/test-bot",
            content=xml,
            headers={"Content-Type": "text/xml"}
        )
        
        assert response.status_code == 200
        
        # 应该返回文本消息（命令响应）
        assert "<MsgType><![CDATA[text]]></MsgType>" in response.text
        assert "会话已重置" in response.text
    
    async def test_intelligent_callback_wrong_platform(self, mock_config, mock_session_manager):
        """测试 Bot 平台类型错误"""
        from forward_service.app import app
        
        client = TestClient(app)
        
        # 修改 mock bot 的平台类型
        mock_config.get_bot_or_default.return_value.platform = "discord"
        
        xml = """<xml>
    <ToUserName><![CDATA[ww123]]></ToUserName>
    <FromUserName><![CDATA[user123]]></FromUserName>
    <CreateTime>1234567890</CreateTime>
    <MsgType><![CDATA[text]]></MsgType>
    <Content><![CDATA[hello]]></Content>
    <MsgId>123</MsgId>
</xml>"""
        
        response = client.post(
            "/callback/intelligent/test-bot",
            content=xml,
            headers={"Content-Type": "text/xml"}
        )
        
        assert response.status_code == 200
        assert "机器人类型错误" in response.text
    
    async def test_intelligent_callback_bot_not_found(self, mock_config):
        """测试 Bot 未找到"""
        from forward_service.app import app
        
        client = TestClient(app)
        
        # Mock bot 不存在
        mock_config.get_bot_or_default.return_value = None
        
        xml = """<xml>
    <ToUserName><![CDATA[ww123]]></ToUserName>
    <FromUserName><![CDATA[user123]]></FromUserName>
    <CreateTime>1234567890</CreateTime>
    <MsgType><![CDATA[text]]></MsgType>
    <Content><![CDATA[hello]]></Content>
    <MsgId>123</MsgId>
</xml>"""
        
        response = client.post(
            "/callback/intelligent/non-existent-bot",
            content=xml,
            headers={"Content-Type": "text/xml"}
        )
        
        assert response.status_code == 200
        assert "机器人配置错误" in response.text
    
    async def test_intelligent_callback_non_text_message(self, mock_config, mock_session_manager):
        """测试非文本消息"""
        from forward_service.app import app
        
        client = TestClient(app)
        
        # 发送事件类型消息
        xml = """<xml>
    <ToUserName><![CDATA[ww123]]></ToUserName>
    <FromUserName><![CDATA[user123]]></FromUserName>
    <CreateTime>1234567890</CreateTime>
    <MsgType><![CDATA[event]]></MsgType>
    <Event><![CDATA[enter_session]]></Event>
</xml>"""
        
        response = client.post(
            "/callback/intelligent/test-bot",
            content=xml,
            headers={"Content-Type": "text/xml"}
        )
        
        assert response.status_code == 200
        # 应该返回空响应（忽略非文本消息）
        # 或者返回欢迎语（取决于实现）
    
    async def test_intelligent_callback_invalid_xml(self):
        """测试无效的 XML"""
        from forward_service.app import app
        
        client = TestClient(app)
        
        response = client.post(
            "/callback/intelligent/test-bot",
            content="not a valid xml",
            headers={"Content-Type": "text/xml"}
        )
        
        # 应该返回错误响应
        assert response.status_code == 200
        assert "服务器错误" in response.text or "xml" in response.text.lower()


@pytest.mark.asyncio
class TestIntelligentCommand:
    """测试智能机器人命令处理"""
    
    async def test_command_list_sessions(self, mock_config, mock_session_manager):
        """测试列出会话命令"""
        from forward_service.routes.intelligent import handle_intelligent_command
        
        # Mock 会话列表
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
            current_session_id=None
        )
        
        assert "会话列表" in reply
        mock_session_manager.list_sessions.assert_called_once()
    
    async def test_command_reset_session(self, mock_session_manager):
        """测试重置会话命令"""
        from forward_service.routes.intelligent import handle_intelligent_command
        
        # Mock 重置成功
        mock_session_manager.reset_session.return_value = True
        
        reply = await handle_intelligent_command(
            session_mgr=mock_session_manager,
            from_user="user123",
            bot=MagicMock(bot_key="test-bot"),
            cmd_type="reset",
            cmd_arg=None,
            extra_msg=None,
            session_key="intelligent:user123",
            current_session_id="session_001"
        )
        
        assert "会话已重置" in reply
        mock_session_manager.reset_session.assert_called_once()
    
    async def test_command_change_session(self, mock_session_manager):
        """测试切换会话命令"""
        from forward_service.routes.intelligent import handle_intelligent_command
        
        # Mock 目标会话
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
            current_session_id="session_001"
        )
        
        assert "已切换到会话" in reply
        assert "abc123" in reply
        mock_session_manager.change_session.assert_called_once()
    
    async def test_command_change_session_not_found(self, mock_session_manager):
        """测试切换到不存在的会话"""
        from forward_service.routes.intelligent import handle_intelligent_command
        
        # Mock 会话不存在
        mock_session_manager.change_session.return_value = None
        
        reply = await handle_intelligent_command(
            session_mgr=mock_session_manager,
            from_user="user123",
            bot=MagicMock(bot_key="test-bot"),
            cmd_type="change",
            cmd_arg="nonexistent",
            extra_msg=None,
            session_key="intelligent:user123",
            current_session_id=None
        )
        
        assert "未找到会话" in reply
        assert "nonexistent" in reply
    
    async def test_command_unknown(self, mock_session_manager):
        """测试未知命令"""
        from forward_service.routes.intelligent import handle_intelligent_command
        
        reply = await handle_intelligent_command(
            session_mgr=mock_session_manager,
            from_user="user123",
            bot=MagicMock(bot_key="test-bot"),
            cmd_type="unknown",
            cmd_arg=None,
            extra_msg=None,
            session_key="intelligent:user123",
            current_session_id=None
        )
        
        assert "未知命令" in reply
