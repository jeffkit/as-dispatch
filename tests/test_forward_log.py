"""
ForwardLog 模型和 Repository 测试
"""
import pytest
import pytest_asyncio
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from forward_service.models import ForwardLog, Base
from forward_service.repository import ForwardLogRepository


class TestForwardLogModel:
    """ForwardLog 模型测试"""
    
    @pytest.mark.asyncio
    async def test_create_forward_log(self, test_db_session: AsyncSession):
        """测试创建 ForwardLog"""
        log = ForwardLog(
            chat_id="test-chat-123",
            from_user_id="user-001",
            from_user_name="Test User",
            content="Hello, world!",
            msg_type="text",
            bot_key="bot-key-001",
            bot_name="Test Bot",
            target_url="https://api.example.com/forward",
            status="pending"
        )
        test_db_session.add(log)
        await test_db_session.commit()
        
        assert log.id is not None
        assert log.chat_id == "test-chat-123"
        assert log.from_user_id == "user-001"
        assert log.status == "pending"
        assert log.timestamp is not None
    
    @pytest.mark.asyncio
    async def test_forward_log_to_dict(self, test_db_session: AsyncSession):
        """测试 to_dict 方法"""
        log = ForwardLog(
            chat_id="test-chat-456",
            from_user_id="user-002",
            from_user_name="Another User",
            content="Test message",
            msg_type="text",
            target_url="https://api.example.com",
            status="success",
            response="Agent response",
            duration_ms=150
        )
        test_db_session.add(log)
        await test_db_session.commit()
        
        data = log.to_dict()
        
        assert data["chat_id"] == "test-chat-456"
        assert data["from_user"] == "Another User"
        assert data["content"] == "Test message"
        assert data["status"] == "success"
        assert data["response"] == "Agent response"
        assert data["duration_ms"] == 150
        assert data["timestamp"] is not None


class TestForwardLogRepository:
    """ForwardLogRepository 测试"""
    
    @pytest.mark.asyncio
    async def test_create_log(self, test_db_session: AsyncSession):
        """测试创建日志"""
        repo = ForwardLogRepository(test_db_session)
        
        log = await repo.create(
            chat_id="chat-001",
            from_user_id="user-001",
            from_user_name="Test User",
            content="Hello",
            target_url="https://api.example.com",
            bot_key="bot-001",
            bot_name="Test Bot",
            status="pending"
        )
        
        assert log.id is not None
        assert log.chat_id == "chat-001"
        assert log.status == "pending"
    
    @pytest.mark.asyncio
    async def test_update_response(self, test_db_session: AsyncSession):
        """测试更新响应信息"""
        repo = ForwardLogRepository(test_db_session)
        
        # 创建日志
        log = await repo.create(
            chat_id="chat-002",
            from_user_id="user-002",
            content="Test",
            target_url="https://api.example.com",
            status="pending"
        )
        
        # 更新响应
        updated_log = await repo.update_response(
            log_id=log.id,
            status="success",
            response="Agent response here",
            session_id="session-123",
            duration_ms=200
        )
        
        assert updated_log is not None
        assert updated_log.status == "success"
        assert updated_log.response == "Agent response here"
        assert updated_log.session_id == "session-123"
        assert updated_log.duration_ms == 200
    
    @pytest.mark.asyncio
    async def test_get_recent(self, test_db_session: AsyncSession):
        """测试获取最近日志"""
        repo = ForwardLogRepository(test_db_session)
        
        # 创建多条日志
        for i in range(5):
            await repo.create(
                chat_id=f"chat-{i}",
                from_user_id=f"user-{i}",
                content=f"Message {i}",
                target_url="https://api.example.com",
                status="success"
            )
        
        # 获取最近 3 条
        logs = await repo.get_recent(limit=3)
        
        assert len(logs) == 3
        # 应该按时间倒序
        assert logs[0].chat_id == "chat-4"
    
    @pytest.mark.asyncio
    async def test_get_by_chat_id(self, test_db_session: AsyncSession):
        """测试按 chat_id 查询"""
        repo = ForwardLogRepository(test_db_session)
        
        # 创建不同 chat_id 的日志
        await repo.create(
            chat_id="chat-A",
            from_user_id="user-1",
            content="Message 1",
            target_url="https://api.example.com",
            status="success"
        )
        await repo.create(
            chat_id="chat-B",
            from_user_id="user-2",
            content="Message 2",
            target_url="https://api.example.com",
            status="success"
        )
        await repo.create(
            chat_id="chat-A",
            from_user_id="user-1",
            content="Message 3",
            target_url="https://api.example.com",
            status="success"
        )
        
        # 查询 chat-A 的日志
        logs = await repo.get_by_chat_id("chat-A")
        
        assert len(logs) == 2
        for log in logs:
            assert log.chat_id == "chat-A"
    
    @pytest.mark.asyncio
    async def test_get_by_bot_key(self, test_db_session: AsyncSession):
        """测试按 bot_key 查询"""
        repo = ForwardLogRepository(test_db_session)
        
        # 创建不同 bot_key 的日志
        await repo.create(
            chat_id="chat-1",
            from_user_id="user-1",
            content="Message 1",
            target_url="https://api.example.com",
            bot_key="bot-X",
            status="success"
        )
        await repo.create(
            chat_id="chat-2",
            from_user_id="user-2",
            content="Message 2",
            target_url="https://api.example.com",
            bot_key="bot-Y",
            status="success"
        )
        
        # 查询 bot-X 的日志
        logs = await repo.get_by_bot_key("bot-X")
        
        assert len(logs) == 1
        assert logs[0].bot_key == "bot-X"
    
    @pytest.mark.asyncio
    async def test_count(self, test_db_session: AsyncSession):
        """测试统计日志数量"""
        repo = ForwardLogRepository(test_db_session)
        
        # 初始应该为 0
        count = await repo.count()
        assert count == 0
        
        # 创建几条日志
        for i in range(3):
            await repo.create(
                chat_id=f"chat-{i}",
                from_user_id=f"user-{i}",
                content=f"Message {i}",
                target_url="https://api.example.com",
                status="success"
            )
        
        # 应该为 3
        count = await repo.count()
        assert count == 3
    
    @pytest.mark.asyncio
    async def test_content_length_limit(self, test_db_session: AsyncSession):
        """测试内容长度限制"""
        repo = ForwardLogRepository(test_db_session)
        
        # 创建超长内容的日志
        long_content = "x" * 10000
        long_response = "y" * 20000
        
        log = await repo.create(
            chat_id="chat-long",
            from_user_id="user-long",
            content=long_content,
            target_url="https://api.example.com",
            response=long_response,
            status="success"
        )
        
        # 内容应该被截断
        assert len(log.content) <= 5000
        assert len(log.response) <= 10000
