"""
US4: 同步回调与超时降级异步的集成测试（路由级，大量 mock）
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from forward_service.config import AccessControl, BotConfig, ForwardConfig
from forward_service.routes.callback import router
from forward_service.services.forwarder import AgentResult, ForwardConfig as FwCfg


def _make_minimal_app():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return app


def _sync_bot(**kwargs) -> BotConfig:
    defaults = dict(
        bot_key="bk-sync",
        name="SyncBot",
        forward_config=ForwardConfig(target_url="http://agent.test/a2a", api_key="", timeout=300),
        access_control=AccessControl(mode="allow_all"),
        enabled=True,
        owner_id="owner1",
        async_mode=False,
        sync_timeout_seconds=30,
        processing_message="处理中…",
        max_task_duration_seconds=600,
    )
    defaults.update(kwargs)
    return BotConfig(**defaults)


@pytest.mark.asyncio
async def test_sync_bot_direct_reply_no_async_submit(mock_db_manager):
    app = _make_minimal_app()
    bot = _sync_bot(sync_timeout_seconds=60)

    payload = {
        "chatid": "chat-1",
        "chattype": "single",
        "msgtype": "text",
        "from": {"name": "u", "userid": "owner1"},
        "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bk-sync",
        "text": {"content": "hello"},
    }

    submit_mock = AsyncMock(return_value="async-id")

    with (
        patch("forward_service.routes.callback.config.get_bot", return_value=bot),
        patch("forward_service.routes.callback.config.check_access", return_value=(True, "")),
        patch(
            "forward_service.routes.callback.config.extract_bot_key_from_webhook_url",
            return_value="bk-sync",
        ),
        patch(
            "forward_service.routes.callback.forward_to_agent_with_user_project",
            new_callable=AsyncMock,
            return_value=AgentResult(
                reply="direct",
                msg_type="text",
                session_id="sess-long-id-here",
                project_id=None,
                project_name=None,
            ),
        ),
        patch(
            "forward_service.routes.callback.send_reply",
            new_callable=AsyncMock,
            return_value={"success": True},
        ),
        patch(
            "forward_service.routes.callback.get_async_task_service"
        ) as gsvc,
        patch("forward_service.routes.callback.add_request_log", new_callable=AsyncMock, return_value=1),
        patch("forward_service.routes.callback.update_request_log", new_callable=AsyncMock),
        patch("forward_service.routes.callback.add_pending_request"),
        patch("forward_service.routes.callback.remove_pending_request"),
        patch("forward_service.routes.callback.get_session_manager") as gsm,
    ):
        svc = MagicMock()
        svc.submit_task = submit_mock
        gsvc.return_value = svc
        sm = MagicMock()
        sm.parse_slash_command = MagicMock(return_value=None)
        sm.get_active_session = AsyncMock(return_value=None)
        sm.record_session = AsyncMock()
        gsm.return_value = sm

        transport = ASGITransport(app=app, lifespan="off")
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/callback", json=payload)

    assert r.status_code == 200
    assert r.json().get("errcode") == 0
    submit_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_timeout_fallback_submits_async_task(mock_db_manager):
    app = _make_minimal_app()
    bot = _sync_bot(sync_timeout_seconds=0.05, processing_message="请排队")

    payload = {
        "chatid": "chat-2",
        "chattype": "single",
        "msgtype": "text",
        "from": {"name": "u", "userid": "owner1"},
        "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bk-sync",
        "text": {"content": "slow"},
    }

    async def slow_agent(**_kwargs):
        await asyncio.sleep(1.0)
        return AgentResult(reply="late", msg_type="text", session_id="s")

    submit_mock = AsyncMock(return_value="tid-async")

    with (
        patch("forward_service.routes.callback.config.get_bot", return_value=bot),
        patch("forward_service.routes.callback.config.check_access", return_value=(True, "")),
        patch(
            "forward_service.routes.callback.config.extract_bot_key_from_webhook_url",
            return_value="bk-sync",
        ),
        patch(
            "forward_service.routes.callback.forward_to_agent_with_user_project",
            new_callable=AsyncMock,
            side_effect=slow_agent,
        ),
        patch(
            "forward_service.routes.callback.get_forward_config_for_user",
            new_callable=AsyncMock,
            return_value=FwCfg(
                target_url="http://agent.test/a2a",
                api_key="k",
                timeout=120,
                project_id="p1",
                project_name="P",
            ),
        ),
        patch(
            "forward_service.routes.callback.send_reply",
            new_callable=AsyncMock,
            return_value={"success": True},
        ),
        patch(
            "forward_service.routes.callback.get_async_task_service"
        ) as gsvc,
        patch("forward_service.routes.callback.add_request_log", new_callable=AsyncMock, return_value=2),
        patch("forward_service.routes.callback.update_request_log", new_callable=AsyncMock),
        patch("forward_service.routes.callback.add_pending_request"),
        patch("forward_service.routes.callback.remove_pending_request"),
        patch("forward_service.routes.callback.get_session_manager") as gsm,
    ):
        svc = MagicMock()
        svc.submit_task = submit_mock
        gsvc.return_value = svc
        sm = MagicMock()
        sm.parse_slash_command = MagicMock(return_value=None)
        sm.get_active_session = AsyncMock(return_value=None)
        gsm.return_value = sm

        transport = ASGITransport(app=app, lifespan="off")
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/callback", json=payload)

    assert r.status_code == 200
    assert r.json().get("errmsg") == "ok"
    submit_mock.assert_awaited_once()
    kwargs = submit_mock.await_args.kwargs
    assert kwargs.get("correlation_id") is not None
    assert "请排队" in (kwargs.get("processing_message") or "")
