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
from ..utils.message_splitter import split_message
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


def _ms_since(start: datetime) -> int:
    return int((datetime.now(timezone.utc) - start).total_seconds() * 1000)


class AsyncTaskService:
    """异步任务提交、执行、恢复"""

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(max(1, int(config.async_task_max_concurrency)))
        self._shutting_down = False
        self._execute_tasks: set[asyncio.Task] = set()
        self._correlation_by_task: dict[str, str] = {}

    def _schedule_execute_task(self, task_id: str) -> None:
        """Schedule task execution in background."""
        asyncio.create_task(self.execute_task(task_id))

    def _log(
        self,
        level: int,
        event: str,
        *,
        task_id: str,
        bot_key: str,
        chat_id: str,
        status: str | None = None,
        correlation_id: str | None = None,
        elapsed_ms: int | None = None,
        error: str | None = None,
        exc_info: bool = False,
        extra: str = "",
    ) -> None:
        parts = [
            f"event={event}",
            f"task_id={task_id}",
            f"bot_key={bot_key[:16]}…" if len(bot_key) > 16 else f"bot_key={bot_key}",
            f"chat_id={chat_id[:24]}…" if len(chat_id) > 24 else f"chat_id={chat_id}",
        ]
        if correlation_id:
            parts.append(f"correlation_id={correlation_id}")
        if status:
            parts.append(f"status={status}")
        if elapsed_ms is not None:
            parts.append(f"elapsed_ms={elapsed_ms}")
        if error:
            parts.append(f"error={error[:500]}")
        if extra:
            parts.append(extra)
        msg = "async_task " + " ".join(parts)
        logger.log(level, msg, exc_info=exc_info)

    async def shutdown(self, timeout: float = 60.0) -> None:
        self._shutting_down = True
        pending = [t for t in self._execute_tasks if not t.done()]
        if not pending:
            logger.info("async_task shutdown: 无在途 execute 任务")
            return
        logger.info("async_task shutdown: 等待 %s 个在途任务（超时=%ss）", len(pending), timeout)
        _done, not_done = await asyncio.wait(pending, timeout=timeout)
        incomplete = len(not_done)
        if incomplete:
            logger.warning(
                "async_task shutdown: %s 个任务在超时内未完成",
                incomplete,
            )
        else:
            logger.info("async_task shutdown: 在途任务已全部结束")

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
        correlation_id: str | None = None,
    ) -> str:
        task_id = uuid.uuid4().hex[:12]
        if correlation_id:
            self._correlation_by_task[task_id] = correlation_id

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

        t0 = datetime.now(timezone.utc)
        self._log(
            logging.INFO,
            "submitted",
            task_id=task_id,
            bot_key=bot_key,
            chat_id=chat_id,
            status="PENDING",
            correlation_id=correlation_id,
            elapsed_ms=_ms_since(t0),
        )

        if self._shutting_down:
            self._correlation_by_task.pop(task_id, None)
            self._log(
                logging.WARNING,
                "submit_skipped_schedule_shutdown",
                task_id=task_id,
                bot_key=bot_key,
                chat_id=chat_id,
                correlation_id=correlation_id,
                elapsed_ms=_ms_since(t0),
            )
            return task_id

        self._schedule_execute_task(task_id)
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
        cur = asyncio.current_task()
        if cur is not None and isinstance(cur, asyncio.Task):
            self._execute_tasks.add(cur)
        run_started = datetime.now(timezone.utc)
        cid = self._correlation_by_task.get(task_id)
        try:
            async with self._semaphore:
                db = get_db_manager()
                async with db.get_session() as session:
                    repo = get_async_task_repository(session)
                    task = await repo.get_by_task_id(task_id)
                    if not task or task.status != "PENDING":
                        if task:
                            self._log(
                                logging.INFO,
                                "execute_skipped_not_pending",
                                task_id=task_id,
                                bot_key=task.bot_key,
                                chat_id=task.chat_id,
                                status=task.status,
                                correlation_id=cid,
                                elapsed_ms=_ms_since(run_started),
                            )
                        return
                    await repo.update_status(
                        task_id,
                        "PROCESSING",
                        started_at=datetime.now(timezone.utc),
                    )
                    await session.commit()
                    bk, ch = task.bot_key, task.chat_id

                self._log(
                    logging.INFO,
                    "status_transition",
                    task_id=task_id,
                    bot_key=bk,
                    chat_id=ch,
                    status="PROCESSING",
                    correlation_id=cid,
                    elapsed_ms=_ms_since(run_started),
                )

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
                    self._log(
                        logging.WARNING,
                        "agent_wait_timeout",
                        task_id=task_id,
                        bot_key=t_bot,
                        chat_id=t_chat,
                        status="TIMEOUT",
                        correlation_id=cid,
                        elapsed_ms=_ms_since(run_started),
                    )
                    await self._handle_timeout(task_id, correlation_id=cid)
                    return
                except Exception as e:
                    self._log(
                        logging.ERROR,
                        "agent_forward_error",
                        task_id=task_id,
                        bot_key=t_bot,
                        chat_id=t_chat,
                        correlation_id=cid,
                        elapsed_ms=_ms_since(run_started),
                        error=str(e),
                        exc_info=True,
                    )
                    await self._handle_failure(task_id, str(e), correlation_id=cid)
                    return

                if result is None:
                    await self._handle_failure(task_id, "Agent 转发返回空结果", correlation_id=cid)
                    return

                await self._deliver_result(task_id, result, correlation_id=cid, run_started=run_started)
        finally:
            if cur is not None and isinstance(cur, asyncio.Task):
                self._execute_tasks.discard(cur)
            self._correlation_by_task.pop(task_id, None)

    async def _deliver_result(
        self,
        task_id: str,
        result: AgentResult,
        *,
        correlation_id: str | None,
        run_started: datetime,
    ) -> None:
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

        if (result.msg_type or "text") == "text":
            chunks = split_message(result.reply or "", max_len=2048)
        else:
            chunks = [result.reply or ""]

        self._log(
            logging.INFO,
            "deliver_chunks",
            task_id=task_id,
            bot_key=t_bot,
            chat_id=t_chat,
            status="DELIVERING",
            correlation_id=correlation_id,
            elapsed_ms=_ms_since(run_started),
            extra=f"chunk_count={len(chunks)}",
        )

        for attempt in range(max_attempts):
            all_ok = True
            for part in chunks:
                send_result = await send_reply(
                    chat_id=t_chat,
                    message=part,
                    msg_type=result.msg_type,
                    bot_key=t_bot,
                    short_id=result.session_id[:8] if result.session_id else None,
                    project_name=result.project_name or (result.project_id if result.project_id else None),
                    mentioned_list=mentioned,
                )
                if not send_result.get("success"):
                    all_ok = False
                    break

            if all_ok:
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
                self._log(
                    logging.INFO,
                    "status_transition",
                    task_id=task_id,
                    bot_key=t_bot,
                    chat_id=t_chat,
                    status="COMPLETED",
                    correlation_id=correlation_id,
                    elapsed_ms=_ms_since(run_started),
                )
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

            self._log(
                logging.WARNING,
                "deliver_retry",
                task_id=task_id,
                bot_key=t_bot,
                chat_id=t_chat,
                status="PROCESSING",
                correlation_id=correlation_id,
                elapsed_ms=_ms_since(run_started),
                extra=f"attempt={attempt + 1}/{max_attempts}",
            )

            if attempt < max_attempts - 1:
                await asyncio.sleep(2 ** (attempt + 1))

        await self._handle_failure(task_id, "结果投递失败（重试耗尽）", correlation_id=correlation_id)

    async def _handle_timeout(self, task_id: str, *, correlation_id: str | None = None) -> None:
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

        self._log(
            logging.INFO,
            "status_transition",
            task_id=task_id,
            bot_key=bot_key,
            chat_id=chat_id,
            status="TIMEOUT",
            correlation_id=correlation_id,
        )

        await send_reply(
            chat_id=chat_id,
            message=msg,
            msg_type="text",
            bot_key=bot_key,
            mentioned_list=mentioned,
        )

    async def _handle_failure(
        self, task_id: str, error_message: str, *, correlation_id: str | None = None
    ) -> None:
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

        self._log(
            logging.ERROR,
            "status_transition",
            task_id=task_id,
            bot_key=bot_key,
            chat_id=chat_id,
            status="FAILED",
            correlation_id=correlation_id,
            error=error_message,
            exc_info=False,
        )
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
            if not self._shutting_down:
                self._schedule_execute_task(task.task_id)
            recovered += 1
        logger.info(
            "异步任务恢复完成: 重新调度=%s 超时关闭=%s",
            recovered,
            timed_out,
        )
