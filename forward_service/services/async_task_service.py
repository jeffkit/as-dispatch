"""
异步 Agent 任务：企微快速 ACK 后后台执行转发与结果投递。
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from ..config import config
from ..database import get_db_manager
from ..repository import get_async_task_repository
from ..sender import send_reply
from ..session_manager import get_session_manager
from ..models import AsyncAgentTask, AsyncTaskStatus
from .forwarder import ForwardConfig, forward_to_agent_with_user_project, AgentResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_async_task_service_instance: Optional["AsyncTaskService"] = None


def get_async_task_service() -> "AsyncTaskService":
    global _async_task_service_instance
    if _async_task_service_instance is None:
        _async_task_service_instance = AsyncTaskService()
    return _async_task_service_instance


class AsyncTaskService:
    """异步任务提交、执行、恢复"""

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(max(1, int(config.async_task_max_concurrency)))

    async def submit_task(
        self,
        *,
        bot_key: str,
        chat_id: str,
        from_user_id: str,
        chat_type: str,
        message: str,
        session_id: str | None,
        forward_config: ForwardConfig,
        mentioned_list: list[str] | None = None,
        image_urls: list[str] | None = None,
        processing_message: str,
        max_duration_seconds: int,
    ) -> str:
        task_id = uuid.uuid4().hex[:12]
        row = AsyncAgentTask(
            task_id=task_id,
            bot_key=bot_key,
            chat_id=chat_id,
            from_user_id=from_user_id,
            chat_type=chat_type or "group",
            mentioned_list=json.dumps(mentioned_list, ensure_ascii=False) if mentioned_list else None,
            message=message,
            image_urls=json.dumps(image_urls, ensure_ascii=False) if image_urls else None,
            target_url=forward_config.get_url(),
            api_key=forward_config.api_key,
            project_id=forward_config.project_id,
            project_name=forward_config.project_name,
            session_id=session_id,
            status="PENDING",
            max_duration_seconds=max_duration_seconds,
            processing_message=processing_message[:500],
        )
        db = get_db_manager()
        async with db.get_session() as session:
            repo = get_async_task_repository(session)
            await repo.create(row)
            await session.commit()
        asyncio.create_task(self.execute_task(task_id))
        logger.info(
            "异步任务已提交: task_id=%s bot_key=%s chat_id=%s",
            task_id,
            bot_key[:10] + "…" if len(bot_key) > 10 else bot_key,
            chat_id[:20] + "…" if len(chat_id) > 20 else chat_id,
        )
        return task_id

    async def get_task_status(self, task_id: str) -> AsyncTaskStatus | None:
        db = get_db_manager()
        async with db.get_session() as session:
            repo = get_async_task_repository(session)
            task = await repo.get_by_task_id(task_id)
            if not task:
                return None
            try:
                return AsyncTaskStatus(task.status)
            except ValueError:
                return None

    async def execute_task(self, task_id: str) -> None:
        async with self._semaphore:
            db = get_db_manager()
            async with db.get_session() as session:
                repo = get_async_task_repository(session)
                task = await repo.get_by_task_id(task_id)
                if not task or task.status != "PENDING":
                    return
                await repo.update_status(
                    task_id,
                    "PROCESSING",
                    started_at=datetime.now(timezone.utc),
                )
                await session.commit()

            async with db.get_session() as session:
                repo = get_async_task_repository(session)
                task = await repo.get_by_task_id(task_id)
                if not task:
                    return
                t_url = task.target_url
                t_api = task.api_key or ""
                t_max = task.max_duration_seconds
                t_pid = task.project_id
                t_pname = task.project_name
                t_bot = task.bot_key
                t_chat = task.chat_id
                t_msg = task.message
                t_sess = task.session_id
                t_imgs_raw = task.image_urls

            forward_cfg = ForwardConfig(
                target_url=t_url,
                api_key=t_api,
                timeout=t_max,
                project_id=t_pid,
                project_name=t_pname,
            )
            imgs = json.loads(t_imgs_raw) if t_imgs_raw else None
            result: AgentResult | None
            try:
                result = await asyncio.wait_for(
                    forward_to_agent_with_user_project(
                        bot_key=t_bot,
                        chat_id=t_chat,
                        content=t_msg,
                        timeout=t_max,
                        session_id=t_sess,
                        current_project_id=t_pid,
                        image_urls=imgs,
                        forward_config_override=forward_cfg,
                    ),
                    timeout=float(t_max),
                )
            except asyncio.TimeoutError:
                await self._handle_timeout(task_id)
                return
            except Exception as e:
                logger.error("异步任务执行异常 task_id=%s: %s", task_id, e, exc_info=True)
                await self._handle_failure(task_id, str(e))
                return

            if result is None:
                await self._handle_failure(task_id, "Agent 转发返回空结果")
                return

            await self._deliver_result(task_id, result)

    async def _deliver_result(self, task_id: str, result: AgentResult) -> None:
        db = get_db_manager()
        async with db.get_session() as session:
            repo = get_async_task_repository(session)
            task = await repo.get_by_task_id(task_id)
            if not task:
                return
            mentioned_raw = task.mentioned_list
            max_retries = int(task.max_retries)
            t_chat = task.chat_id
            t_bot = task.bot_key
            t_from = task.from_user_id
            t_msg = task.message
            t_proj = task.project_id

        mentioned = json.loads(mentioned_raw) if mentioned_raw else None
        max_attempts = max_retries + 1

        for attempt in range(max_attempts):
            send_result = await send_reply(
                chat_id=t_chat,
                message=result.reply,
                msg_type=result.msg_type,
                bot_key=t_bot,
                short_id=result.session_id[:8] if result.session_id else None,
                project_name=result.project_name or (result.project_id if result.project_id else None),
                mentioned_list=mentioned,
            )
            if send_result.get("success"):
                text = (result.reply or "")[:10000]
                async with db.get_session() as session:
                    repo = get_async_task_repository(session)
                    await repo.update_status(
                        task_id,
                        "COMPLETED",
                        completed_at=datetime.now(timezone.utc),
                        response_text=text,
                        new_session_id=result.session_id,
                    )
                    await session.commit()
                if result.session_id:
                    session_mgr = get_session_manager()
                    await session_mgr.record_session(
                        user_id=t_from,
                        chat_id=t_chat,
                        bot_key=t_bot,
                        session_id=result.session_id,
                        last_message=(t_msg or "")[:500],
                        current_project_id=t_proj,
                        set_active=True,
                    )
                return

            async with db.get_session() as session:
                repo = get_async_task_repository(session)
                await repo.increment_retry(task_id)
                await session.commit()

            if attempt < max_attempts - 1:
                await asyncio.sleep(2 ** (attempt + 1))

        await self._handle_failure(task_id, "结果投递失败（重试耗尽）")

    async def _handle_timeout(self, task_id: str) -> None:
        msg = "⏱️ 任务处理超时，请稍后重试"
        db = get_db_manager()
        async with db.get_session() as session:
            repo = get_async_task_repository(session)
            task = await repo.get_by_task_id(task_id)
            if not task or task.status in ("COMPLETED", "FAILED", "TIMEOUT"):
                return
            await repo.update_status(
                task_id,
                "TIMEOUT",
                completed_at=datetime.now(timezone.utc),
                error_message="超过 max_duration_seconds",
            )
            await session.commit()
            mentioned = json.loads(task.mentioned_list) if task.mentioned_list else None
            bot_key = task.bot_key
            chat_id = task.chat_id

        await send_reply(
            chat_id=chat_id,
            message=msg,
            msg_type="text",
            bot_key=bot_key,
            mentioned_list=mentioned,
        )

    async def _handle_failure(self, task_id: str, error_message: str) -> None:
        msg = "⚠️ 处理失败，请稍后重试"
        db = get_db_manager()
        async with db.get_session() as session:
            repo = get_async_task_repository(session)
            task = await repo.get_by_task_id(task_id)
            if not task or task.status in ("COMPLETED", "FAILED", "TIMEOUT"):
                return
            await repo.update_status(
                task_id,
                "FAILED",
                completed_at=datetime.now(timezone.utc),
                error_message=error_message[:2000] if error_message else None,
            )
            await session.commit()
            mentioned = json.loads(task.mentioned_list) if task.mentioned_list else None
            bot_key = task.bot_key
            chat_id = task.chat_id

        logger.error("异步任务失败 task_id=%s: %s", task_id, error_message)
        await send_reply(
            chat_id=chat_id,
            message=msg,
            msg_type="text",
            bot_key=bot_key,
            mentioned_list=mentioned,
        )

    async def recover_pending_tasks(self) -> None:
        db = get_db_manager()
        async with db.get_session() as session:
            repo = get_async_task_repository(session)
            pending = await repo.get_by_status(["PENDING", "PROCESSING"])
        recovered = 0
        timed_out = 0
        for task in pending:
            created = task.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - created).total_seconds()
            if elapsed > float(task.max_duration_seconds):
                await self._handle_timeout(task.task_id)
                timed_out += 1
                continue
            async with db.get_session() as session:
                repo = get_async_task_repository(session)
                await repo.update_status(task.task_id, "PENDING", started_at=None)
                await session.commit()
            asyncio.create_task(self.execute_task(task.task_id))
            recovered += 1
        logger.info(
            "异步任务恢复完成: 重新调度=%s 超时关闭=%s",
            recovered,
            timed_out,
        )
