"""
出站消息上下文 API

/api/outbound-context — 供 AgentStudio / hitl-mcp 调用，
保存和查询 Agent 发出的企微消息上下文，用于异步回复路由。

鉴权：使用 as-enterprise JWT Token（与 /api/bots 相同）。
"""
import logging
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from typing import Optional

from ..auth import require_enterprise_jwt
from ..database import get_db_manager
from ..repository import get_outbound_context_repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/outbound-context", tags=["outbound-context"])


class CreateOutboundContextRequest(BaseModel):
    message_id: str
    bot_key: str
    chat_id: str
    task_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    content_preview: Optional[str] = None


@router.post("")
async def create_outbound_context(
    body: CreateOutboundContextRequest,
    _user=Depends(require_enterprise_jwt),
) -> dict:
    """保存出站消息上下文"""
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_outbound_context_repository(session)
            ctx = await repo.create_outbound_context(
                message_id=body.message_id,
                bot_key=body.bot_key,
                chat_id=body.chat_id,
                task_id=body.task_id,
                agent_id=body.agent_id,
                session_id=body.session_id,
                content_preview=body.content_preview,
            )
            await session.commit()
            return {"success": True, "context": ctx.to_dict()}
    except Exception as e:
        logger.error(f"保存出站消息上下文失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@router.get("/{message_id}")
async def get_outbound_context(
    message_id: str,
    _user=Depends(require_enterprise_jwt),
) -> dict:
    """根据企微消息 ID 查询出站上下文"""
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_outbound_context_repository(session)
            ctx = await repo.find_context_by_message_id(message_id)
            if not ctx:
                return {"success": False, "error": f"未找到 message_id={message_id} 的上下文"}
            return {"success": True, "context": ctx.to_dict()}
    except Exception as e:
        logger.error(f"查询出站消息上下文失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
