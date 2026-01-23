"""
测试 Forward Service 数据库集成

测试:
1. 使用数据库配置启动服务
2. API 接口正常工作
3. 配置更新功能
"""
import pytest
import pytest_asyncio

from forward_service.config import ConfigDB, BotConfig, ForwardConfig, AccessControl


@pytest.mark.asyncio
async def test_database_config_initialization(mock_db_manager):
    """测试数据库配置初始化"""
    from forward_service.repository import get_chatbot_repository, get_access_rule_repository
    
    # 添加测试数据
    async with mock_db_manager.get_session() as session:
        bot_repo = get_chatbot_repository(session)
        rule_repo = get_access_rule_repository(session)

        # 创建测试 Bot
        bot1 = await bot_repo.create(
            bot_key="test_bot_1",
            name="测试 Bot 1",
            url_template="https://api1.com",
            access_mode="allow_all",
            enabled=True
        )

        await rule_repo.create(bot1.id, "user1", "whitelist")

        bot2 = await bot_repo.create(
            bot_key="test_bot_2",
            name="测试 Bot 2",
            url_template="https://api2.com",
            access_mode="whitelist",
            enabled=True
        )

        await rule_repo.set_whitelist(bot2.id, ["user2", "user3"])

    # 初始化配置
    config = ConfigDB()
    await config.initialize()

    # 调试
    print(f"加载的 bots: {list(config.bots.keys())}")

    # 验证配置
    assert len(config.bots) == 2, f"期望 2 个 bots,实际 {len(config.bots)}"
    assert "test_bot_1" in config.bots
    assert "test_bot_2" in config.bots

    # 测试 get_bot (注意: get_bot 是同步方法，使用缓存)
    bot = config.bots.get("test_bot_1")
    assert bot is not None
    assert bot.name == "测试 Bot 1"
    assert bot.forward_config.target_url == "https://api1.com"

    # 测试访问控制 (check_access 是同步方法)
    allowed, reason = config.check_access(bot, "user1")
    # bot1 是 allow_all 模式
    assert allowed is True

    bot2 = config.bots.get("test_bot_2")
    allowed, reason = config.check_access(bot2, "user2")
    # bot2 是 whitelist 模式, user2 在白名单中
    assert allowed is True

    allowed, reason = config.check_access(bot2, "user4")
    # bot2 是 whitelist 模式, user4 不在白名单中
    assert allowed is False
    assert "没有权限" in reason

    print("✅ 数据库配置初始化测试通过")


@pytest.mark.asyncio
async def test_config_dict_serialization():
    """测试配置序列化"""
    # 创建测试配置
    bot_config = BotConfig(
        bot_key="test_key",
        name="测试 Bot",
        description="测试描述",
        forward_config=ForwardConfig(
            target_url="https://api.example.com/agent123",
            api_key="key456",
            timeout=30
        ),
        access_control=AccessControl(
            mode="whitelist",
            whitelist=["user1", "user2"],
            blacklist=[]
        ),
        enabled=True
    )

    # 转换为字典
    d = bot_config.to_dict()

    # 验证序列化结果
    assert d["bot_key"] == "test_key"
    assert d["name"] == "测试 Bot"
    assert d["forward_config"]["target_url"] == "https://api.example.com/agent123"
    assert d["access_control"]["mode"] == "whitelist"
    assert d["access_control"]["whitelist"] == ["user1", "user2"]
    assert d["enabled"] == True

    print("✅ 配置序列化测试通过")
