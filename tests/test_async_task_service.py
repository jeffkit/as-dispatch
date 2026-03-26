"""
异步任务服务单元测试（US1 / US2）
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forward_service.models import AsyncAgentTask
from forward_service.repository import get_async_task_repository
from forward_service.services.forwarder import AgentResult, ForwardConfig


def _reset_async_service_singleton():
    import forward_service.services.async_task_service as m

    m._async_task_service_instance = None


@pytest.mark.asyncio
async def test_submit_task_persists_pending(mock_db_manager):
    """T011: submit_task 落库 PENDING 并返回 task_id，不依赖 execute 完成。"""
    _reset_async_service_singleton()

    with patch("forward_service.services.async_task_service.asyncio.create_task") as ct:
        ct.return_value = MagicMock()

        from forward_service.services.async_task_service import AsyncTaskService

        svc = AsyncTaskService()
        tid = await svc.submit_task(
            bot_key="test-bot-key",
            chat_id="chat-1",
            from_user_id="u1",
            chat_type="group",
            message="hello",
            session_id=None,
            forward_config=ForwardConfig(
                target_url="http://localhost/agent",
                api_key="k",
                timeout=120,
                project_id="p1",
                project_name="P",
            ),
            mentioned_list=None,
            image_urls=None,
            processing_message="请稍候",
            max_duration_seconds=600,
        )

    assert tid
    assert len(tid) <= 16

    async with mock_db_manager.get_session() as session:
        repo = get_async_task_repository(session)
        row = await repo.get_by_task_id(tid)
        assert row is not None
        assert row.status == "PENDING"
        assert row.message == "hello"

    assert ct.called


@pytest.mark.asyncio
async def test_execute_task_state_machine(mock_db_manager):
    """T016: execute_task PENDING→PROCESSING→COMPLETED，并调用 send_reply。"""
    _reset_async_service_singleton()

    with patch("forward_service.services.async_task_service.asyncio.create_task"):
        from forward_service.services.async_task_service import AsyncTaskService

        svc = AsyncTaskService()
        tid = await svc.submit_task(
            bot_key="bk",
            chat_id="cid",
            from_user_id="uid",
            chat_type="group",
            message="m",
            session_id="sess1",
            forward_config=ForwardConfig(
                target_url="http://x/y",
                api_key="",
                timeout=60,
                project_id=None,
                project_name=None,
            ),
            processing_message="…",
            max_duration_seconds=120,
        )

    with (
        patch(
            "forward_service.services.async_task_service.forward_to_agent_with_user_project",
            new_callable=AsyncMock,
            return_value=AgentResult(
                reply="done",
                msg_type="text",
                session_id="sess2",
                project_id=None,
                project_name=None,
            ),
        ) as mock_fwd,
        patch(
            "forward_service.services.async_task_service.send_reply",
            new_callable=AsyncMock,
            return_value={"success": True, "parts_sent": 1},
        ) as mock_send,
        patch(
            "forward_service.services.async_task_service.get_session_manager"
        ) as gsm,
    ):
        gsm.return_value.record_session = AsyncMock()
        await svc.execute_task(tid)

    mock_fwd.assert_awaited()
    mock_send.assert_awaited()

    async with mock_db_manager.get_session() as session:
        repo = get_async_task_repository(session)
        row = await repo.get_by_task_id(tid)
        assert row.status == "COMPLETED"
        assert row.response_text == "done"


@pytest.mark.asyncio
async def test_deliver_result_retry_then_success(mock_db_manager):
    """T017: send_reply 失败两次后成功 → COMPLETED 且 retry_count==2。"""
    _reset_async_service_singleton()

    with patch("forward_service.services.async_task_service.asyncio.create_task"):
        from forward_service.services.async_task_service import AsyncTaskService

        svc = AsyncTaskService()
        tid = await svc.submit_task(
            bot_key="bk",
            chat_id="cid",
            from_user_id="uid",
            chat_type="group",
            message="m",
            session_id=None,
            forward_config=ForwardConfig("http://a", "", 60),
            processing_message="…",
            max_duration_seconds=120,
        )

    send_results = [
        {"success": False, "error": "e1"},
        {"success": False, "error": "e2"},
        {"success": True, "parts_sent": 1},
    ]

    with (
        patch(
            "forward_service.services.async_task_service.forward_to_agent_with_user_project",
            new_callable=AsyncMock,
            return_value=AgentResult(reply="ok", msg_type="text", session_id="s"),
        ),
        patch(
            "forward_service.services.async_task_service.send_reply",
            new_callable=AsyncMock,
            side_effect=send_results,
        ),
        patch("forward_service.services.async_task_service.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "forward_service.services.async_task_service.get_session_manager"
        ) as gsm,
    ):
        gsm.return_value.record_session = AsyncMock()
        await svc.execute_task(tid)

    async with mock_db_manager.get_session() as session:
        repo = get_async_task_repository(session)
        row = await repo.get_by_task_id(tid)
        assert row.status == "COMPLETED"
        assert row.retry_count == 2


@pytest.mark.asyncio
async def test_deliver_result_all_retries_fail(mock_db_manager):
    """T017: 投递全部失败 → FAILED。"""
    _reset_async_service_singleton()

    with patch("forward_service.services.async_task_service.asyncio.create_task"):
        from forward_service.services.async_task_service import AsyncTaskService

        svc = AsyncTaskService()
        tid = await svc.submit_task(
            bot_key="bk",
            chat_id="cid",
            from_user_id="uid",
            chat_type="group",
            message="m",
            session_id=None,
            forward_config=ForwardConfig("http://a", "", 60),
            processing_message="…",
            max_duration_seconds=120,
        )

    # max_retries default 3 → 4 attempts, all fail
    fail = {"success": False, "error": "x"}

    with (
        patch(
            "forward_service.services.async_task_service.forward_to_agent_with_user_project",
            new_callable=AsyncMock,
            return_value=AgentResult(reply="body", msg_type="text"),
        ),
        patch(
            "forward_service.services.async_task_service.send_reply",
            new_callable=AsyncMock,
            return_value=fail,
        ),
        patch("forward_service.services.async_task_service.asyncio.sleep", new_callable=AsyncMock),
    ):
        await svc.execute_task(tid)

    async with mock_db_manager.get_session() as session:
        repo = get_async_task_repository(session)
        row = await repo.get_by_task_id(tid)
        assert row.status == "FAILED"


@pytest.mark.asyncio
async def test_recover_resets_processing_to_pending_before_execute(mock_db_manager):
    """T022: PROCESSING 任务恢复时先置为 PENDING 再调度 execute_task。"""
    _reset_async_service_singleton()

    async with mock_db_manager.get_session() as session:
        repo = get_async_task_repository(session)
        t = AsyncAgentTask(
            task_id="recover1",
            bot_key="bk",
            chat_id="c",
            from_user_id="u",
            chat_type="group",
            message="m",
            target_url="http://x",
            status="PROCESSING",
            max_duration_seconds=99999,
            processing_message="…",
            created_at=datetime.now(timezone.utc),
            started_at=datetime.now(timezone.utc),
        )
        await repo.create(t)
        await session.commit()

    scheduled = []

    from forward_service.services.async_task_service import AsyncTaskService

    svc = AsyncTaskService()

    async def bound_execute(task_id: str):
        async with mock_db_manager.get_session() as session:
            r = get_async_task_repository(session)
            row = await r.get_by_task_id(task_id)
            assert row is not None
            assert row.status == "PENDING"

    svc.execute_task = bound_execute

    def capture(coro):
        scheduled.append(coro)
        return MagicMock()

    with patch(
        "forward_service.services.async_task_service.asyncio.create_task",
        side_effect=capture,
    ):
        await svc.recover_pending_tasks()

    assert len(scheduled) == 1
    await scheduled[0]
