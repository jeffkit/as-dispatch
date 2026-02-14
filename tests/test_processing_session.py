"""
ProcessingSession 并发控制单元测试

测试内容:
- ProcessingSessionRepository: 加锁、释放、超时清理
- get_effective_user: 群聊/私聊的 effective_user 计算
- compute_processing_key: 处理锁 key 的计算逻辑
"""
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from forward_service.repository import (
    ProcessingSessionRepository,
    get_processing_session_repository,
)
from forward_service.session_manager import (
    get_effective_user,
    compute_processing_key,
)
from forward_service.models import ProcessingSession


# ============== get_effective_user 测试 ==============

class TestGetEffectiveUser:
    """测试 effective_user 计算逻辑"""

    def test_private_chat_returns_user_id(self):
        """私聊场景返回 user_id"""
        result = get_effective_user("user123", "chat_user123", "single")
        assert result == "user123"

    def test_group_chat_returns_chat_id(self):
        """群聊场景返回 chat_id（共享会话）"""
        result = get_effective_user("user123", "group_abc", "group")
        assert result == "group_abc"

    def test_group_chat_different_users_same_result(self):
        """群聊中不同用户返回相同 effective_user"""
        result1 = get_effective_user("user1", "group_abc", "group")
        result2 = get_effective_user("user2", "group_abc", "group")
        assert result1 == result2 == "group_abc"

    def test_private_chat_different_users_different_result(self):
        """私聊中不同用户返回不同 effective_user"""
        result1 = get_effective_user("user1", "chat_user1", "single")
        result2 = get_effective_user("user2", "chat_user2", "single")
        assert result1 != result2


# ============== compute_processing_key 测试 ==============

class TestComputeProcessingKey:
    """测试处理锁 key 计算逻辑"""

    def test_with_session_id_returns_session_id(self):
        """有 session_id 时直接使用 session_id 作为 key"""
        result = compute_processing_key(
            session_id="sess-abc-123",
            user_id="user1",
            chat_id="chat1",
            bot_key="bot1",
            chat_type="single"
        )
        assert result == "sess-abc-123"

    def test_without_session_id_private_chat(self):
        """私聊无 session_id 时使用 user_id:bot_key"""
        result = compute_processing_key(
            session_id=None,
            user_id="user1",
            chat_id="chat_user1",
            bot_key="bot1",
            chat_type="single"
        )
        assert result == "user1:bot1"

    def test_without_session_id_group_chat(self):
        """群聊无 session_id 时使用 chat_id:bot_key"""
        result = compute_processing_key(
            session_id=None,
            user_id="user1",
            chat_id="group_abc",
            bot_key="bot1",
            chat_type="group"
        )
        assert result == "group_abc:bot1"

    def test_with_session_id_ignores_chat_type(self):
        """有 session_id 时不区分群聊/私聊"""
        result_single = compute_processing_key(
            "sess-123", "user1", "chat1", "bot1", "single"
        )
        result_group = compute_processing_key(
            "sess-123", "user1", "group1", "bot1", "group"
        )
        assert result_single == result_group == "sess-123"

    def test_empty_session_id_treated_as_none(self):
        """空字符串 session_id 等同于 None"""
        result = compute_processing_key(
            session_id="",
            user_id="user1",
            chat_id="chat1",
            bot_key="bot1",
            chat_type="single"
        )
        assert result == "user1:bot1"


# ============== ProcessingSessionRepository 测试 ==============

class TestProcessingSessionRepository:
    """测试 ProcessingSession DB 锁"""

    @pytest_asyncio.fixture
    async def repo(self, test_db_session):
        """创建 Repository 实例"""
        return ProcessingSessionRepository(test_db_session)

    @pytest.mark.asyncio
    async def test_try_acquire_success(self, repo, test_db_session):
        """首次获取锁应成功"""
        result = await repo.try_acquire(
            session_key="test-key-1",
            user_id="user1",
            chat_id="chat1",
            bot_key="bot1",
            message="hello"
        )
        assert result is True
        await test_db_session.commit()

    @pytest.mark.asyncio
    async def test_try_acquire_duplicate_fails(self, repo, test_db_session):
        """重复获取同一个 key 应失败"""
        # 首次获取成功
        result1 = await repo.try_acquire(
            session_key="test-key-dup",
            user_id="user1",
            chat_id="chat1",
            bot_key="bot1",
            message="hello"
        )
        assert result1 is True
        await test_db_session.commit()

        # 重复获取失败
        result2 = await repo.try_acquire(
            session_key="test-key-dup",
            user_id="user2",
            chat_id="chat1",
            bot_key="bot1",
            message="world"
        )
        assert result2 is False

    @pytest.mark.asyncio
    async def test_different_keys_can_coexist(self, repo, test_db_session):
        """不同 key 可以同时存在"""
        result1 = await repo.try_acquire(
            "key-a", "user1", "chat1", "bot1", "msg1"
        )
        await test_db_session.commit()

        result2 = await repo.try_acquire(
            "key-b", "user2", "chat2", "bot1", "msg2"
        )
        await test_db_session.commit()

        assert result1 is True
        assert result2 is True

    @pytest.mark.asyncio
    async def test_release_success(self, repo, test_db_session):
        """释放锁应成功"""
        await repo.try_acquire("release-key", "user1", "chat1", "bot1", "msg")
        await test_db_session.commit()

        result = await repo.release("release-key")
        await test_db_session.commit()
        assert result is True

    @pytest.mark.asyncio
    async def test_release_nonexistent(self, repo, test_db_session):
        """释放不存在的锁返回 False"""
        result = await repo.release("nonexistent-key")
        assert result is False

    @pytest.mark.asyncio
    async def test_acquire_after_release(self, repo, test_db_session):
        """释放后可以重新获取"""
        await repo.try_acquire("reuse-key", "user1", "chat1", "bot1", "msg1")
        await test_db_session.commit()

        await repo.release("reuse-key")
        await test_db_session.commit()

        result = await repo.try_acquire("reuse-key", "user2", "chat1", "bot1", "msg2")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_lock_info(self, repo, test_db_session):
        """获取锁信息"""
        await repo.try_acquire("info-key", "user1", "chat1", "bot1", "test message")
        await test_db_session.commit()

        info = await repo.get_lock_info("info-key")
        assert info is not None
        assert info.session_key == "info-key"
        assert info.user_id == "user1"
        assert info.message == "test message"
        assert info.started_at is not None

    @pytest.mark.asyncio
    async def test_get_lock_info_nonexistent(self, repo, test_db_session):
        """获取不存在的锁信息返回 None"""
        info = await repo.get_lock_info("no-such-key")
        assert info is None

    @pytest.mark.asyncio
    async def test_cleanup_stale_removes_old_locks(self, repo, test_db_session):
        """清理超时的锁"""
        from sqlalchemy import update

        # 创建一条记录
        await repo.try_acquire("stale-key", "user1", "chat1", "bot1", "old msg")
        await test_db_session.commit()

        # 手动将 started_at 修改为 10 分钟前
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        stmt = update(ProcessingSession).where(
            ProcessingSession.session_key == "stale-key"
        ).values(started_at=old_time)
        await test_db_session.execute(stmt)
        await test_db_session.commit()

        # 清理（5 分钟超时）
        cleaned = await repo.cleanup_stale(timeout_seconds=300)
        await test_db_session.commit()
        assert cleaned == 1

        # 确认已清除
        info = await repo.get_lock_info("stale-key")
        assert info is None

    @pytest.mark.asyncio
    async def test_cleanup_stale_preserves_fresh_locks(self, repo, test_db_session):
        """清理不影响新的锁"""
        await repo.try_acquire("fresh-key", "user1", "chat1", "bot1", "new msg")
        await test_db_session.commit()

        cleaned = await repo.cleanup_stale(timeout_seconds=300)
        await test_db_session.commit()
        assert cleaned == 0

        info = await repo.get_lock_info("fresh-key")
        assert info is not None

    @pytest.mark.asyncio
    async def test_message_truncation(self, repo, test_db_session):
        """消息超过 500 字符应截断"""
        long_message = "a" * 1000
        await repo.try_acquire("trunc-key", "user1", "chat1", "bot1", long_message)
        await test_db_session.commit()

        info = await repo.get_lock_info("trunc-key")
        assert info is not None
        assert len(info.message) == 500

    @pytest.mark.asyncio
    async def test_count(self, repo, test_db_session):
        """统计锁数量"""
        count_before = await repo.count()
        assert count_before == 0

        await repo.try_acquire("count-1", "user1", "chat1", "bot1", "msg1")
        await test_db_session.commit()
        await repo.try_acquire("count-2", "user2", "chat2", "bot1", "msg2")
        await test_db_session.commit()

        count_after = await repo.count()
        assert count_after == 2

    @pytest.mark.asyncio
    async def test_get_all_active(self, repo, test_db_session):
        """获取所有活跃锁"""
        await repo.try_acquire("active-1", "user1", "chat1", "bot1", "msg1")
        await test_db_session.commit()
        await repo.try_acquire("active-2", "user2", "chat2", "bot1", "msg2")
        await test_db_session.commit()

        active = await repo.get_all_active()
        assert len(active) == 2
        keys = {r.session_key for r in active}
        assert keys == {"active-1", "active-2"}
