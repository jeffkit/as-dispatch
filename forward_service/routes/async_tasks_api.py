"""
管理端异步任务查询 API

GET /api/admin/async-tasks — X-Admin-Key 鉴权（与 /admin/bots 一致）。
"""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict

from ..auth import require_admin_key
from ..database import get_db_manager
from ..repository import get_async_task_repository

AdminAuth = Annotated[None, Depends(require_admin_key)]

router = APIRouter(prefix="/api/admin/async-tasks", tags=["admin-async-tasks"])


class AsyncTaskResponse(BaseModel):
    """单条异步任务（与 AsyncAgentTask.to_dict 对齐，Pydantic 校验响应）"""

    model_config = ConfigDict(extra="allow")

    id: int
    task_id: str
    bot_key: str
    chat_id: str
    from_user_id: str
    chat_type: str
    mentioned_list: Optional[str] = None
    message: str
    image_urls: Optional[str] = None
    target_url: str
    api_key: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    session_id: Optional[str] = None
    new_session_id: Optional[str] = None
    status: str
    retry_count: int
    max_retries: int
    response_text: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    max_duration_seconds: int
    processing_message: str


class AsyncTaskListResponse(BaseModel):
    success: bool = True
    tasks: list[AsyncTaskResponse]
    limit: int
    offset: int


class AsyncTaskDetailResponse(BaseModel):
    success: bool = True
    task: AsyncTaskResponse


@router.get("", response_model=AsyncTaskListResponse)
async def list_async_tasks(
    _auth: AdminAuth,
    task_status: Optional[str] = Query(
        None, alias="status", description="PENDING|PROCESSING|COMPLETED|FAILED|TIMEOUT"
    ),
    bot_key: Optional[str] = None,
    chat_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> AsyncTaskListResponse:
    db = get_db_manager()
    async with db.get_session() as session:
        repo = get_async_task_repository(session)
        rows = await repo.list_for_admin(
            bot_key=bot_key,
            status=task_status,
            chat_id=chat_id,
            limit=limit,
            offset=offset,
        )
    tasks = [AsyncTaskResponse.model_validate(r.to_dict(include_api_key=False)) for r in rows]
    return AsyncTaskListResponse(tasks=tasks, limit=limit, offset=offset)


@router.get("/{task_id}", response_model=AsyncTaskDetailResponse)
async def get_async_task(task_id: str, _auth: AdminAuth) -> AsyncTaskDetailResponse:
    db = get_db_manager()
    async with db.get_session() as session:
        repo = get_async_task_repository(session)
        row = await repo.get_by_task_id(task_id)
    if not row:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return AsyncTaskDetailResponse(
        task=AsyncTaskResponse.model_validate(row.to_dict(include_api_key=False))
    )
