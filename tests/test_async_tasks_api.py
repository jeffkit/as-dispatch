"""
US3: 异步任务管理 Admin API 单元测试
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from forward_service.models import AsyncAgentTask
from forward_service.repository import get_async_task_repository
from forward_service.routes.async_tasks_api import router


@pytest.mark.asyncio
async def test_list_async_tasks_filters(mock_db_manager):
    import forward_service.auth as auth

    async with mock_db_manager.get_session() as session:
        repo = get_async_task_repository(session)
        await repo.create(
            AsyncAgentTask(
                task_id="t1",
                bot_key="bot-a",
                chat_id="chat-x",
                from_user_id="u1",
                chat_type="group",
                message="hi",
                target_url="http://a",
                status="PENDING",
                max_duration_seconds=100,
                processing_message="…",
                created_at=datetime.now(timezone.utc),
            )
        )
        await repo.create(
            AsyncAgentTask(
                task_id="t2",
                bot_key="bot-b",
                chat_id="chat-y",
                from_user_id="u2",
                chat_type="group",
                message="yo",
                target_url="http://b",
                status="COMPLETED",
                max_duration_seconds=100,
                processing_message="…",
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    app = _make_app()
    with patch.object(auth, "_ADMIN_KEY", ""):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.get("/api/admin/async-tasks?status=PENDING&bot_key=bot-a")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["task_id"] == "t1"

    with patch.object(auth, "_ADMIN_KEY", ""):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r2 = await client.get("/api/admin/async-tasks?chat_id=chat-y")
    assert r2.status_code == 200
    ids = {t["task_id"] for t in r2.json()["tasks"]}
    assert ids == {"t2"}


@pytest.mark.asyncio
async def test_get_async_task_detail_and_404(mock_db_manager):
    import forward_service.auth as auth

    async with mock_db_manager.get_session() as session:
        repo = get_async_task_repository(session)
        await repo.create(
            AsyncAgentTask(
                task_id="tid99",
                bot_key="b",
                chat_id="c",
                from_user_id="u",
                chat_type="group",
                message="m",
                target_url="http://x",
                status="FAILED",
                max_duration_seconds=50,
                processing_message="…",
                error_message="boom" * 100,
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    app = _make_app()
    with patch.object(auth, "_ADMIN_KEY", ""):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            ok = await client.get("/api/admin/async-tasks/tid99")
            missing = await client.get("/api/admin/async-tasks/nope")
    assert ok.status_code == 200
    assert ok.json()["task"]["error_message"].startswith("boom")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_admin_key_required_when_configured(mock_db_manager):
    import forward_service.auth as auth

    app = _make_app()
    with patch.object(auth, "_ADMIN_KEY", "secret-admin"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.get("/api/admin/async-tasks")
    assert r.status_code == 401

    with patch.object(auth, "_ADMIN_KEY", "secret-admin"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r2 = await client.get(
                "/api/admin/async-tasks",
                headers={"X-Admin-Key": "secret-admin"},
            )
    assert r2.status_code == 200


def _make_app():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return app
