"""
出站消息发送 API

POST /api/im/send — 将消息发送到 IM 通道（企微群），
生成 outbound_short_id 路由头，保存上下文用于回复路由。

鉴权：使用 as-enterprise JWT Token。
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import require_enterprise_jwt
from ..database import get_db_manager
from ..repository import get_outbound_context_repository
from ..sender import send_to_wecom
from ..utils.short_id import generate_unique_outbound_short_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/im", tags=["im-send"])


class DispatchRequest(BaseModel):
    message_content: str
    bot_key: str
    chat_id: str
    session_id: str
    agent_id: Optional[str] = None
    project_name: Optional[str] = None
    msg_type: Optional[str] = "text"


@router.post("/send")
async def send_to_im(
    body: DispatchRequest,
    _user=Depends(require_enterprise_jwt),
) -> dict:
    """
    发送消息到 IM 通道，生成路由标识并保存上下文。

    流程：
    1. 生成 ob_xxxxxx outbound_short_id
    2. 注入路由头 [#ob_xxxxxx ProjectName] 到消息开头
    3. 通过 fly-pigeon (send_to_wecom) 发送到企微群
    4. 发送成功后保存 OutboundMessageContext
    5. 返回 short_id 和完整消息
    """
    logger.info(
        f"收到出站消息发送请求: bot_key={body.bot_key[:10]}..., "
        f"chat_id={body.chat_id[:10]}..., session_id={body.session_id[:8]}..."
    )

    # 1. 生成唯一 outbound short_id
    db_manager = get_db_manager()

    async def check_exists(short_id: str) -> bool:
        async with db_manager.get_session() as session:
            repo = get_outbound_context_repository(session)
            existing = await repo.find_context_by_message_id(short_id)
            return existing is not None

    try:
        short_id = await generate_unique_outbound_short_id(exists_checker=check_exists)
    except RuntimeError as e:
        logger.error(f"生成 outbound short_id 失败: {e}")
        return {"success": False, "error": str(e)}

    # 2. 注入路由头
    project_label = body.project_name or ""
    routing_header = f"[#{short_id} {project_label}]".rstrip() if project_label else f"[#{short_id}]"
    message_with_header = f"{routing_header}\n\n{body.message_content}"

    # 3. 通过 fly-pigeon 发送（同步函数，用 run_in_executor 包装）
    loop = asyncio.get_event_loop()
    try:
        send_result = await loop.run_in_executor(
            None,
            lambda: send_to_wecom(
                message=message_with_header,
                chat_id=body.chat_id,
                msg_type=body.msg_type or "text",
                bot_key=body.bot_key,
            ),
        )
    except Exception as e:
        logger.error(f"fly-pigeon 发送失败: {e}", exc_info=True)
        return {"success": False, "error": f"fly-pigeon 发送失败: {e}"}

    # 检查 fly-pigeon 返回结果
    if isinstance(send_result, dict) and send_result.get("errcode", 0) != 0:
        error_msg = f"企微发送失败: errcode={send_result.get('errcode')}, errmsg={send_result.get('errmsg')}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}

    # 4. 发送成功，保存 OutboundMessageContext
    try:
        async with db_manager.get_session() as session:
            repo = get_outbound_context_repository(session)
            await repo.create_outbound_context(
                message_id=short_id,
                bot_key=body.bot_key,
                chat_id=body.chat_id,
                agent_id=body.agent_id,
                session_id=body.session_id,
                content_preview=body.message_content[:200],
            )
            await session.commit()
        logger.info(f"出站消息上下文已保存: short_id={short_id}, session_id={body.session_id[:8]}...")
    except Exception as e:
        logger.error(f"保存出站消息上下文失败（消息已发送）: {e}", exc_info=True)

    # 5. 返回结果
    return {
        "success": True,
        "short_id": short_id,
        "message_with_header": message_with_header,
    }
