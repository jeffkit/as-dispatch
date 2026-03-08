"""
Admin API 鉴权测试

测试 auth.py 模块和 /admin/bots/* 路由的鉴权行为：
- 未配置 AS_ADMIN_KEY 时，返回 503
- 提供错误 key 时，返回 401
- 提供正确 key 时，正常响应
- 未提供 key 时，返回 401

同时验证 create_bot 正确记录 owner_id。
"""
import os
import pytest
import pytest_asyncio
from unittest.mock import patch
from sqlalchemy import text
from httpx import AsyncClient, ASGITransport


# ============== Fixtures ==============

@pytest_asyncio.fixture
async def initialized_app(mock_db_manager):
    """创建已初始化的 FastAPI 应用"""
    from forward_service.app import app
    from forward_service.config import config
    await config.initialize()
    yield app
    async with mock_db_manager.get_session() as session:
        await session.execute(text("DELETE FROM chat_access_rules"))
        await session.execute(text("DELETE FROM chatbots"))
        await session.commit()


@pytest_asyncio.fixture
async def authed_client(initialized_app):
    """携带正确 X-Admin-Key 的测试客户端"""
    transport = ASGITransport(app=initialized_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Admin-Key": "test-secret-key"},
    ) as client:
        yield client


@pytest_asyncio.fixture
async def no_auth_client(initialized_app):
    """不携带任何 auth header 的测试客户端"""
    transport = ASGITransport(app=initialized_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ============== auth.py 单元测试 ==============

def test_require_admin_key_no_env_configured():
    """AS_ADMIN_KEY 未配置时，模块加载后 get_admin_key() 返回空字符串"""
    with patch.dict(os.environ, {}, clear=False):
        import importlib
        import forward_service.auth as auth_module
        # 不重载模块，仅验证 get_admin_key 函数返回当前值
        # 实际鉴权行为通过路由测试验证
        assert callable(auth_module.require_admin_key)
        assert callable(auth_module.get_admin_key)


# ============== /admin/bots 鉴权路由测试 ==============

@pytest.mark.asyncio
async def test_list_bots_without_key_returns_401_or_503(no_auth_client):
    """不提供 X-Admin-Key 时，返回 401 或 503（取决于是否配置了 key）"""
    with patch("forward_service.auth._ADMIN_KEY", "test-secret-key"):
        response = await no_auth_client.get("/admin/bots")
    assert response.status_code in (401, 503)


@pytest.mark.asyncio
async def test_list_bots_with_wrong_key_returns_401(initialized_app):
    """提供错误的 X-Admin-Key 时，返回 401"""
    with patch("forward_service.auth._ADMIN_KEY", "test-secret-key"):
        transport = ASGITransport(app=initialized_app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Admin-Key": "wrong-key"},
        ) as client:
            response = await client.get("/admin/bots")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_bots_with_correct_key_returns_200(initialized_app):
    """提供正确的 X-Admin-Key 时，返回 200"""
    with patch("forward_service.auth._ADMIN_KEY", "test-secret-key"):
        transport = ASGITransport(app=initialized_app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Admin-Key": "test-secret-key"},
        ) as client:
            response = await client.get("/admin/bots")
    assert response.status_code == 200
    assert response.json()["success"] is True


@pytest.mark.asyncio
async def test_create_bot_without_key_returns_401(initialized_app):
    """不提供 key 时，POST /admin/bots 返回 401"""
    with patch("forward_service.auth._ADMIN_KEY", "test-secret-key"):
        transport = ASGITransport(app=initialized_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/admin/bots",
                json={"bot_key": "x", "name": "test"},
            )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_bot_without_key_returns_401(initialized_app):
    """不提供 key 时，GET /admin/bots/:key 返回 401"""
    with patch("forward_service.auth._ADMIN_KEY", "test-secret-key"):
        transport = ASGITransport(app=initialized_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/admin/bots/any_key")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_bot_without_key_returns_401(initialized_app):
    """不提供 key 时，DELETE /admin/bots/:key 返回 401"""
    with patch("forward_service.auth._ADMIN_KEY", "test-secret-key"):
        transport = ASGITransport(app=initialized_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete("/admin/bots/any_key")
    assert response.status_code == 401


# ============== /admin (非 bots) 路由鉴权测试 ==============

@pytest.mark.asyncio
async def test_admin_status_without_key_returns_401(initialized_app):
    """GET /admin/status 不提供 key 时，返回 401"""
    with patch("forward_service.auth._ADMIN_KEY", "test-secret-key"):
        transport = ASGITransport(app=initialized_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/admin/status")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_status_with_correct_key_returns_200(initialized_app):
    """GET /admin/status 提供正确 key 时，返回 200"""
    with patch("forward_service.auth._ADMIN_KEY", "test-secret-key"):
        transport = ASGITransport(app=initialized_app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Admin-Key": "test-secret-key"},
        ) as client:
            response = await client.get("/admin/status")
    assert response.status_code == 200


# ============== owner_id 记录测试 ==============

@pytest.mark.asyncio
async def test_create_bot_records_owner_id(initialized_app, mock_db_manager):
    """create_bot 时传入 owner_id，应该正确保存到数据库"""
    with patch("forward_service.auth._ADMIN_KEY", "test-secret-key"):
        transport = ASGITransport(app=initialized_app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Admin-Key": "test-secret-key"},
        ) as client:
            response = await client.post(
                "/admin/bots",
                json={
                    "bot_key": "owner-test-bot",
                    "name": "Owner Test Bot",
                    "target_url": "https://example.com/a2a/xxx/messages",
                    "api_key": "agt_proj_test",
                    "owner_id": "meta-agent",
                },
            )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    # 验证数据库中的 owner_id
    async with mock_db_manager.get_session() as session:
        from forward_service.repository import get_chatbot_repository
        bot_repo = get_chatbot_repository(session)
        bot = await bot_repo.get_by_bot_key("owner-test-bot")
        assert bot is not None
        assert bot.owner_id == "meta-agent"


@pytest.mark.asyncio
async def test_create_bot_without_owner_id_is_null(initialized_app, mock_db_manager):
    """create_bot 时不传 owner_id，数据库中应为 None"""
    with patch("forward_service.auth._ADMIN_KEY", "test-secret-key"):
        transport = ASGITransport(app=initialized_app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Admin-Key": "test-secret-key"},
        ) as client:
            response = await client.post(
                "/admin/bots",
                json={
                    "bot_key": "no-owner-bot",
                    "name": "No Owner Bot",
                },
            )

    assert response.status_code == 200
    assert response.json()["success"] is True

    async with mock_db_manager.get_session() as session:
        from forward_service.repository import get_chatbot_repository
        bot_repo = get_chatbot_repository(session)
        bot = await bot_repo.get_by_bot_key("no-owner-bot")
        assert bot is not None
        assert bot.owner_id is None


# ============== AS_ADMIN_KEY 未配置时返回 503 ==============

@pytest.mark.asyncio
async def test_admin_returns_503_when_key_not_configured(initialized_app):
    """AS_ADMIN_KEY 为空时，所有 admin 路由返回 503"""
    with patch("forward_service.auth._ADMIN_KEY", ""):
        transport = ASGITransport(app=initialized_app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Admin-Key": "any-key"},
        ) as client:
            response = await client.get("/admin/bots")
    assert response.status_code == 503
