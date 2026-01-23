"""
数据库模型和 Repository 单元测试

测试内容:
1. 模型定义和关系
2. ChatbotRepository CRUD 操作
3. ChatAccessRuleRepository CRUD 操作
4. 访问控制逻辑
"""
import pytest
import pytest_asyncio
import asyncio
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

# 添加项目路径
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from forward_service.models import Base, Chatbot, ChatAccessRule, ChatInfo
from forward_service.repository import (
    ChatbotRepository,
    ChatAccessRuleRepository,
    ChatInfoRepository,
    get_chatbot_repository,
    get_access_rule_repository,
    get_chat_info_repository
)


# ============== 测试数据库设置 ==============

@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """创建测试数据库引擎 (内存 SQLite)"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )

    # 创建所有表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # 清理
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_session(test_engine):
    """创建测试 Session"""
    async_session_maker = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async with async_session_maker() as session:
        yield session
        await session.rollback()  # 确保每个测试后回滚


# ============== Chatbot 模型测试 ==============

class TestChatbotModel:
    """Chatbot 模型测试"""

    @pytest.mark.asyncio
    async def test_create_chatbot(self, test_session: AsyncSession):
        """测试创建 Chatbot"""
        bot = Chatbot(
            bot_key="test_key_123",
            name="测试 Bot",
            description="这是一个测试 Bot",
            url_template="https://api.com/handle",
            agent_id="agent-001",
            api_key="sk-test",
            timeout=30,
            access_mode="allow_all",
            enabled=True
        )

        test_session.add(bot)
        await test_session.commit()
        await test_session.refresh(bot)

        assert bot.id is not None
        assert bot.bot_key == "test_key_123"
        assert bot.name == "测试 Bot"
        assert bot.url_template == "https://api.com/handle"
        assert bot.agent_id == "agent-001"
        assert bot.api_key == "sk-test"
        assert bot.timeout == 30
        assert bot.access_mode == "allow_all"
        assert bot.enabled is True
        assert bot.created_at is not None
        assert bot.updated_at is not None

    @pytest.mark.asyncio
    async def test_get_url(self, test_session: AsyncSession):
        """测试 URL 生成"""
        # 带 agent_id
        bot1 = Chatbot(
            bot_key="bot1",
            name="Bot 1",
            url_template="https://api.com/a2a/{agent_id}/msg",
            agent_id="agent-A"
        )
        test_session.add(bot1)
        await test_session.commit()

        url = bot1.get_url()
        assert url == "https://api.com/a2a/agent-A/msg"

        # 不带 agent_id
        bot2 = Chatbot(
            bot_key="bot2",
            name="Bot 2",
            url_template="https://api.com/handle"
        )
        test_session.add(bot2)
        await test_session.commit()

        url = bot2.get_url()
        assert url == "https://api.com/handle"

    @pytest.mark.asyncio
    async def test_check_access_allow_all(self, test_session: AsyncSession):
        """测试访问控制 - allow_all 模式"""
        bot = Chatbot(
            bot_key="bot1",
            name="Bot 1",
            url_template="https://api.com",
            access_mode="allow_all",
            enabled=True
        )
        test_session.add(bot)
        await test_session.commit()

        # 任何用户都应该有权限
        allowed, reason = bot.check_access("any_user")
        assert allowed is True
        assert reason == ""

    @pytest.mark.asyncio
    async def test_check_access_whitelist(self, test_session: AsyncSession):
        """测试访问控制 - whitelist 模式"""
        bot = Chatbot(
            bot_key="bot1",
            name="Bot 1",
            url_template="https://api.com",
            access_mode="whitelist",
            enabled=True
        )
        test_session.add(bot)
        await test_session.commit()

        # 添加白名单规则
        rule1 = ChatAccessRule(
            chatbot_id=bot.id,
            chat_id="user1",
            rule_type="whitelist"
        )
        rule2 = ChatAccessRule(
            chatbot_id=bot.id,
            chat_id="user2",
            rule_type="whitelist"
        )
        test_session.add_all([rule1, rule2])
        await test_session.commit()

        # 刷新 bot 对象以加载关系
        await test_session.refresh(bot, attribute_names=["access_rules"])

        # 白名单中的用户应该有权限
        allowed, reason = bot.check_access("user1")
        assert allowed is True
        assert reason == ""

        # 不在白名单中的用户应该被拒绝
        allowed, reason = bot.check_access("user3")
        assert allowed is False
        assert "没有权限" in reason

    @pytest.mark.asyncio
    async def test_check_access_blacklist(self, test_session: AsyncSession):
        """测试访问控制 - blacklist 模式"""
        bot = Chatbot(
            bot_key="bot1",
            name="Bot 1",
            url_template="https://api.com",
            access_mode="blacklist",
            enabled=True
        )
        test_session.add(bot)
        await test_session.commit()

        # 添加黑名单规则
        rule = ChatAccessRule(
            chatbot_id=bot.id,
            chat_id="bad_user",
            rule_type="blacklist"
        )
        test_session.add(rule)
        await test_session.commit()

        # 刷新 bot 对象以加载关系
        await test_session.refresh(bot, attribute_names=["access_rules"])

        # 不在黑名单中的用户应该有权限
        allowed, reason = bot.check_access("good_user")
        assert allowed is True
        assert reason == ""

        # 在黑名单中的用户应该被拒绝
        allowed, reason = bot.check_access("bad_user")
        assert allowed is False
        assert "没有权限" in reason

    @pytest.mark.asyncio
    async def test_check_access_disabled_bot(self, test_session: AsyncSession):
        """测试访问控制 - 禁用的 Bot"""
        bot = Chatbot(
            bot_key="bot1",
            name="Bot 1",
            url_template="https://api.com",
            access_mode="allow_all",
            enabled=False  # Bot 已禁用
        )
        test_session.add(bot)
        await test_session.commit()

        # 禁用的 Bot 应该拒绝所有访问
        allowed, reason = bot.check_access("any_user")
        assert allowed is False
        assert "禁用" in reason


# ============== ChatAccessRule 模型测试 ==============

class TestChatAccessRuleModel:
    """ChatAccessRule 模型测试"""

    @pytest.mark.asyncio
    async def test_create_access_rule(self, test_session: AsyncSession):
        """测试创建访问规则"""
        bot = Chatbot(
            bot_key="bot1",
            name="Bot 1",
            url_template="https://api.com"
        )
        test_session.add(bot)
        await test_session.flush()

        rule = ChatAccessRule(
            chatbot_id=bot.id,
            chat_id="user1",
            rule_type="whitelist",
            remark="测试用户"
        )
        test_session.add(rule)
        await test_session.commit()
        await test_session.refresh(rule)

        assert rule.id is not None
        assert rule.chatbot_id == bot.id
        assert rule.chat_id == "user1"
        assert rule.rule_type == "whitelist"
        assert rule.remark == "测试用户"
        assert rule.created_at is not None


# ============== ChatbotRepository 测试 ==============

class TestChatbotRepository:
    """ChatbotRepository 测试"""

    @pytest.mark.asyncio
    async def test_create_bot(self, test_session: AsyncSession):
        """测试创建 Bot"""
        repo = get_chatbot_repository(test_session)

        bot = await repo.create(
            bot_key="test_key",
            name="测试 Bot",
            url_template="https://api.com",
            agent_id="agent-001",
            timeout=30
        )

        assert bot.id is not None
        assert bot.bot_key == "test_key"
        assert bot.name == "测试 Bot"

    @pytest.mark.asyncio
    async def test_get_by_id(self, test_session: AsyncSession):
        """测试根据 ID 获取 Bot"""
        repo = get_chatbot_repository(test_session)

        bot = await repo.create(bot_key="test_key", name="测试", url_template="https://api.com")
        found_bot = await repo.get_by_id(bot.id)

        assert found_bot is not None
        assert found_bot.id == bot.id
        assert found_bot.bot_key == "test_key"

    @pytest.mark.asyncio
    async def test_get_by_bot_key(self, test_session: AsyncSession):
        """测试根据 bot_key 获取 Bot"""
        repo = get_chatbot_repository(test_session)

        await repo.create(bot_key="test_key_123", name="测试", url_template="https://api.com")
        found_bot = await repo.get_by_bot_key("test_key_123")

        assert found_bot is not None
        assert found_bot.bot_key == "test_key_123"

    @pytest.mark.asyncio
    async def test_get_all(self, test_session: AsyncSession):
        """测试获取所有 Bot"""
        repo = get_chatbot_repository(test_session)

        await repo.create(bot_key="bot1", name="Bot 1", url_template="https://api1.com")
        await repo.create(bot_key="bot2", name="Bot 2", url_template="https://api2.com")
        await repo.create(bot_key="bot3", name="Bot 3", url_template="https://api3.com", enabled=False)

        # 获取所有 Bot
        all_bots = await repo.get_all()
        assert len(all_bots) == 3

        # 只获取启用的 Bot
        enabled_bots = await repo.get_all(enabled_only=True)
        assert len(enabled_bots) == 2

    @pytest.mark.asyncio
    async def test_update_bot(self, test_session: AsyncSession):
        """测试更新 Bot"""
        repo = get_chatbot_repository(test_session)

        bot = await repo.create(
            bot_key="test_key",
            name="旧名称",
            url_template="https://api.com",
            timeout=30
        )

        updated_bot = await repo.update(
            bot.id,
            name="新名称",
            timeout=60
        )

        assert updated_bot is not None
        assert updated_bot.name == "新名称"
        assert updated_bot.timeout == 60
        assert updated_bot.url_template == "https://api.com"  # 未更新的字段保持不变

    @pytest.mark.asyncio
    async def test_delete_bot(self, test_session: AsyncSession):
        """测试删除 Bot"""
        repo = get_chatbot_repository(test_session)

        bot = await repo.create(bot_key="test_key", name="测试", url_template="https://api.com")
        bot_id = bot.id

        # 删除 Bot
        success = await repo.delete(bot_id)
        assert success is True

        # 验证已删除
        deleted_bot = await repo.get_by_id(bot_id)
        assert deleted_bot is None

    @pytest.mark.asyncio
    async def test_count_bots(self, test_session: AsyncSession):
        """测试统计 Bot 数量"""
        repo = get_chatbot_repository(test_session)

        await repo.create(bot_key="bot1", name="Bot 1", url_template="https://api1.com", enabled=True)
        await repo.create(bot_key="bot2", name="Bot 2", url_template="https://api2.com", enabled=True)
        await repo.create(bot_key="bot3", name="Bot 3", url_template="https://api3.com", enabled=False)

        total_count = await repo.count()
        assert total_count == 3

        enabled_count = await repo.count(enabled_only=True)
        assert enabled_count == 2


# ============== ChatAccessRuleRepository 测试 ==============

class TestChatAccessRuleRepository:
    """ChatAccessRuleRepository 测试"""

    @pytest.mark.asyncio
    async def test_create_rule(self, test_session: AsyncSession):
        """测试创建规则"""
        bot_repo = get_chatbot_repository(test_session)
        rule_repo = get_access_rule_repository(test_session)

        bot = await bot_repo.create(bot_key="bot1", name="Bot 1", url_template="https://api.com")

        rule = await rule_repo.create(
            chatbot_id=bot.id,
            chat_id="user1",
            rule_type="whitelist",
            remark="测试用户"
        )

        assert rule.id is not None
        assert rule.chatbot_id == bot.id
        assert rule.chat_id == "user1"
        assert rule.rule_type == "whitelist"

    @pytest.mark.asyncio
    async def test_get_by_chatbot(self, test_session: AsyncSession):
        """测试获取 Bot 的所有规则"""
        bot_repo = get_chatbot_repository(test_session)
        rule_repo = get_access_rule_repository(test_session)

        bot = await bot_repo.create(bot_key="bot1", name="Bot 1", url_template="https://api.com")

        await rule_repo.create(bot.id, "user1", "whitelist")
        await rule_repo.create(bot.id, "user2", "whitelist")
        await rule_repo.create(bot.id, "bad_user", "blacklist")

        # 获取所有规则
        all_rules = await rule_repo.get_by_chatbot(bot.id)
        assert len(all_rules) == 3

        # 只获取白名单
        whitelist_rules = await rule_repo.get_by_chatbot(bot.id, rule_type="whitelist")
        assert len(whitelist_rules) == 2

        # 只获取黑名单
        blacklist_rules = await rule_repo.get_by_chatbot(bot.id, rule_type="blacklist")
        assert len(blacklist_rules) == 1

    @pytest.mark.asyncio
    async def test_get_whitelist_blacklist(self, test_session: AsyncSession):
        """测试获取白名单/黑名单 Chat ID 列表"""
        bot_repo = get_chatbot_repository(test_session)
        rule_repo = get_access_rule_repository(test_session)

        bot = await bot_repo.create(bot_key="bot1", name="Bot 1", url_template="https://api.com")

        await rule_repo.create(bot.id, "user1", "whitelist")
        await rule_repo.create(bot.id, "user2", "whitelist")
        await rule_repo.create(bot.id, "bad_user", "blacklist")

        whitelist = await rule_repo.get_whitelist(bot.id)
        assert set(whitelist) == {"user1", "user2"}

        blacklist = await rule_repo.get_blacklist(bot.id)
        assert blacklist == ["bad_user"]

    @pytest.mark.asyncio
    async def test_delete_rule(self, test_session: AsyncSession):
        """测试删除规则"""
        bot_repo = get_chatbot_repository(test_session)
        rule_repo = get_access_rule_repository(test_session)

        bot = await bot_repo.create(bot_key="bot1", name="Bot 1", url_template="https://api.com")
        rule = await rule_repo.create(bot.id, "user1", "whitelist")

        # 删除规则
        success = await rule_repo.delete(rule.id)
        assert success is True

        # 验证已删除
        deleted_rule = await rule_repo.get_by_id(rule.id)
        assert deleted_rule is None

    @pytest.mark.asyncio
    async def test_delete_by_chatbot(self, test_session: AsyncSession):
        """测试删除 Bot 的所有规则"""
        bot_repo = get_chatbot_repository(test_session)
        rule_repo = get_access_rule_repository(test_session)

        bot = await bot_repo.create(bot_key="bot1", name="Bot 1", url_template="https://api.com")

        await rule_repo.create(bot.id, "user1", "whitelist")
        await rule_repo.create(bot.id, "user2", "whitelist")
        await rule_repo.create(bot.id, "bad_user", "blacklist")

        # 删除所有规则
        count = await rule_repo.delete_by_chatbot(bot.id)
        assert count == 3

        # 验证已删除
        remaining_rules = await rule_repo.get_by_chatbot(bot.id)
        assert len(remaining_rules) == 0

    @pytest.mark.asyncio
    async def test_set_whitelist(self, test_session: AsyncSession):
        """测试批量设置白名单"""
        bot_repo = get_chatbot_repository(test_session)
        rule_repo = get_access_rule_repository(test_session)

        bot = await bot_repo.create(bot_key="bot1", name="Bot 1", url_template="https://api.com")

        # 设置白名单
        rules = await rule_repo.set_whitelist(bot.id, ["user1", "user2", "user3"])
        assert len(rules) == 3

        # 验证
        whitelist = await rule_repo.get_whitelist(bot.id)
        assert set(whitelist) == {"user1", "user2", "user3"}

        # 重新设置 (会清除旧的)
        new_rules = await rule_repo.set_whitelist(bot.id, ["user4", "user5"])
        assert len(new_rules) == 2

        whitelist = await rule_repo.get_whitelist(bot.id)
        assert set(whitelist) == {"user4", "user5"}

    @pytest.mark.asyncio
    async def test_set_blacklist(self, test_session: AsyncSession):
        """测试批量设置黑名单"""
        bot_repo = get_chatbot_repository(test_session)
        rule_repo = get_access_rule_repository(test_session)

        bot = await bot_repo.create(bot_key="bot1", name="Bot 1", url_template="https://api.com")

        # 设置黑名单
        rules = await rule_repo.set_blacklist(bot.id, ["bad_user1", "bad_user2"])
        assert len(rules) == 2

        # 验证
        blacklist = await rule_repo.get_blacklist(bot.id)
        assert set(blacklist) == {"bad_user1", "bad_user2"}


# ============== ChatInfoRepository 测试 ==============

class TestChatInfoRepository:
    """ChatInfoRepository 测试类"""

    @pytest.mark.asyncio
    async def test_record_chat_new(self, test_session: AsyncSession):
        """测试首次记录 Chat 信息"""
        repo = get_chat_info_repository(test_session)

        info = await repo.record_chat(
            chat_id="wrkSFfCgAAeOoN9UbWphOy5FXWKEiibA",
            chat_type="group",
            chat_name="测试群",
            bot_key="test_bot_key"
        )

        assert info.id is not None
        assert info.chat_id == "wrkSFfCgAAeOoN9UbWphOy5FXWKEiibA"
        assert info.chat_type == "group"
        assert info.chat_name == "测试群"
        assert info.first_bot_key == "test_bot_key"
        assert info.message_count == 1
        assert info.is_group is True
        assert info.is_single is False

    @pytest.mark.asyncio
    async def test_record_chat_update(self, test_session: AsyncSession):
        """测试更新已存在的 Chat 信息"""
        repo = get_chat_info_repository(test_session)

        # 首次记录
        await repo.record_chat(
            chat_id="chat1",
            chat_type="single",
            bot_key="bot1"
        )

        # 再次记录（更新）
        info = await repo.record_chat(
            chat_id="chat1",
            chat_type="single",
            bot_key="bot2"
        )

        # 验证 message_count 增加
        assert info.message_count == 2
        # bot_key 不会更新（只记录首次）
        assert info.first_bot_key == "bot1"

    @pytest.mark.asyncio
    async def test_get_chat_type(self, test_session: AsyncSession):
        """测试获取 chat_type"""
        repo = get_chat_info_repository(test_session)

        # 记录一个群聊
        await repo.record_chat(chat_id="group1", chat_type="group")
        # 记录一个私聊
        await repo.record_chat(chat_id="single1", chat_type="single")

        # 测试获取
        assert await repo.get_chat_type("group1") == "group"
        assert await repo.get_chat_type("single1") == "single"
        assert await repo.get_chat_type("unknown") is None

    @pytest.mark.asyncio
    async def test_is_group(self, test_session: AsyncSession):
        """测试 is_group 方法"""
        repo = get_chat_info_repository(test_session)

        await repo.record_chat(chat_id="g1", chat_type="group")
        await repo.record_chat(chat_id="s1", chat_type="single")

        assert await repo.is_group("g1") is True
        assert await repo.is_group("s1") is False
        assert await repo.is_group("unknown") is None

    @pytest.mark.asyncio
    async def test_get_all(self, test_session: AsyncSession):
        """测试获取所有 Chat 信息"""
        repo = get_chat_info_repository(test_session)

        # 创建测试数据
        await repo.record_chat(chat_id="g1", chat_type="group")
        await repo.record_chat(chat_id="g2", chat_type="group")
        await repo.record_chat(chat_id="s1", chat_type="single")

        # 获取所有
        all_chats = await repo.get_all()
        assert len(all_chats) == 3

        # 只获取群聊
        groups = await repo.get_groups()
        assert len(groups) == 2

        # 只获取私聊
        singles = await repo.get_singles()
        assert len(singles) == 1

    @pytest.mark.asyncio
    async def test_count(self, test_session: AsyncSession):
        """测试统计数量"""
        repo = get_chat_info_repository(test_session)

        await repo.record_chat(chat_id="g1", chat_type="group")
        await repo.record_chat(chat_id="g2", chat_type="group")
        await repo.record_chat(chat_id="s1", chat_type="single")

        assert await repo.count() == 3
        assert await repo.count(chat_type="group") == 2
        assert await repo.count(chat_type="single") == 1

    @pytest.mark.asyncio
    async def test_delete(self, test_session: AsyncSession):
        """测试删除 Chat 信息"""
        repo = get_chat_info_repository(test_session)

        await repo.record_chat(chat_id="test", chat_type="group")
        assert await repo.get_chat_type("test") == "group"

        # 删除
        result = await repo.delete("test")
        assert result is True
        assert await repo.get_chat_type("test") is None

        # 删除不存在的
        result = await repo.delete("nonexistent")
        assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
