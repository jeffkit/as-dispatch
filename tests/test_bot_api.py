"""
Forward Service Bot 管理 API 单元测试

测试 Bot CRUD 操作
"""
import pytest
import pytest_asyncio

from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from forward_service.models import Chatbot


# ============== 测试 Fixtures ==============

@pytest_asyncio.fixture
async def initialized_app(mock_db_manager):
    """创建已初始化的 FastAPI 应用"""
    from forward_service.app import app
    from forward_service.config import config
    
    # 初始化配置
    await config.initialize()
    
    yield app
    
    # 清理：删除所有数据
    async with mock_db_manager.get_session() as session:
        await session.execute(text("DELETE FROM chat_access_rules"))
        await session.execute(text("DELETE FROM chatbots"))
        await session.commit()


@pytest_asyncio.fixture
async def test_client(initialized_app):
    """创建测试客户端"""
    transport = ASGITransport(app=initialized_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def sample_bot(mock_db_manager):
    """创建示例 Bot"""
    async with mock_db_manager.get_session() as session:
        from forward_service.repository import get_chatbot_repository

        bot_repo = get_chatbot_repository(session)
        bot = await bot_repo.create(
            bot_key="test_bot",
            name="测试 Bot",
            url_template="https://api.example.com/agent/{agent_id}/message",
            agent_id="agent_123",
            api_key="key_456",
            timeout=60,
            access_mode="allow_all",
            enabled=True
        )
        await session.commit()
        return bot


# ============== Bot 列表 API 测试 ==============

@pytest.mark.asyncio
async def test_list_bots_empty(test_client):
    """测试获取空的 Bot 列表"""
    response = await test_client.get("/admin/bots")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True
    assert data["bots"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_bots_with_data(test_client, sample_bot):
    """测试获取 Bot 列表"""
    response = await test_client.get("/admin/bots")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True
    assert data["total"] == 1

    bots = data["bots"]
    assert len(bots) == 1
    assert bots[0]["bot_key"] == "test_bot"
    assert bots[0]["name"] == "测试 Bot"
    assert bots[0]["enabled"] == True


# ============== Bot 详情 API 测试 ==============

@pytest.mark.asyncio
async def test_get_bot_by_key(test_client, sample_bot):
    """测试获取单个 Bot 详情"""
    response = await test_client.get("/admin/bots/test_bot")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True

    bot = data["bot"]
    assert bot["bot_key"] == "test_bot"
    assert bot["name"] == "测试 Bot"
    assert bot["url_template"] == "https://api.example.com/agent/{agent_id}/message"


@pytest.mark.asyncio
async def test_get_bot_not_found(test_client):
    """测试获取不存在的 Bot"""
    response = await test_client.get("/admin/bots/nonexistent")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == False
    assert "不存在" in data["error"]


# ============== Bot 创建 API 测试 ==============

@pytest.mark.asyncio
async def test_create_bot_success(test_client):
    """测试成功创建 Bot"""
    bot_data = {
        "bot_key": "new_bot",
        "name": "新 Bot",
        "url_template": "https://api.example.com/test",
        "agent_id": "test_agent",
        "api_key": "test_key",
        "timeout": 30,
        "access_mode": "allow_all",
        "enabled": True
    }
    response = await test_client.post("/admin/bots", json=bot_data)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True
    assert data["bot"]["bot_key"] == "new_bot"


@pytest.mark.asyncio
async def test_create_bot_missing_required_field(test_client):
    """测试缺少必填字段"""
    bot_data = {
        "name": "新 Bot",
        # 缺少 bot_key 和 url_template
    }
    response = await test_client.post("/admin/bots", json=bot_data)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == False


@pytest.mark.asyncio
async def test_create_bot_duplicate_key(test_client, sample_bot):
    """测试重复的 bot_key"""
    bot_data = {
        "bot_key": "test_bot",  # 已存在
        "name": "另一个 Bot",
        "url_template": "https://api.example.com/test",
    }
    response = await test_client.post("/admin/bots", json=bot_data)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == False


# ============== Bot 更新 API 测试 ==============

@pytest.mark.asyncio
async def test_update_bot_success(test_client, sample_bot):
    """测试成功更新 Bot"""
    update_data = {
        "name": "更新后的 Bot",
        "timeout": 120
    }
    response = await test_client.put("/admin/bots/test_bot", json=update_data)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True


@pytest.mark.asyncio
async def test_update_bot_not_found(test_client):
    """测试更新不存在的 Bot"""
    update_data = {"name": "新名称"}
    response = await test_client.put("/admin/bots/nonexistent", json=update_data)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == False


# ============== Bot 删除 API 测试 ==============

@pytest.mark.asyncio
async def test_delete_bot_success(test_client, sample_bot):
    """测试成功删除 Bot"""
    response = await test_client.delete("/admin/bots/test_bot")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True

    # 验证已删除
    response = await test_client.get("/admin/bots/test_bot")
    data = response.json()
    assert data["success"] == False


@pytest.mark.asyncio
async def test_delete_bot_not_found(test_client):
    """测试删除不存在的 Bot"""
    response = await test_client.delete("/admin/bots/nonexistent")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] == False


# ============== 模式 API 测试 ==============

@pytest.mark.asyncio
async def test_get_mode_database(test_client):
    """测试获取数据库模式"""
    response = await test_client.get("/admin/mode")

    assert response.status_code == 200
    data = response.json()
    # 在测试环境中，USE_DATABASE=true
    assert data["mode"] == "database"
    assert data["supports_bot_api"] == True
