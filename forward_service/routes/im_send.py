"""
出站消息发送 API

POST /api/im/send — 将消息发送到 IM 通道（企微群），
生成 outbound_short_id 路由头，保存上下文用于回复路由。
发送复用 send_reply（支持超长消息自动分拆，且每条都带相同 short_id）。
默认 msg_type 为 markdown_v2，与 Agent 回调回贴一致；可显式传 text / markdown。

鉴权：使用 as-enterprise JWT Token。
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import require_enterprise_jwt
from ..database import get_db_manager
from ..repository import get_outbound_context_repository
from ..message_splitter import create_message_header
from ..sender import send_reply
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
    msg_type: Optional[str] = "markdown_v2"


@router.post("/send")
async def send_to_im(
    body: DispatchRequest,
    _user=Depends(require_enterprise_jwt),
) -> dict:
    """
    发送消息到 IM 通道，生成路由标识并保存上下文。

    流程：
    1. 生成 ob_xxxxxx outbound_short_id
    2. 通过 send_reply 发送（自动注入 [#short_id]，必要时自动分拆）
    3. 发送成功后保存 OutboundMessageContext
    4. 返回 short_id 和完整消息头预览
    """
    session_preview = body.session_id[:8] if body.session_id else "None"
    logger.info(
        f"收到出站消息发送请求: bot_key={body.bot_key[:10]}..., "
        f"chat_id={body.chat_id[:10]}..., session_id={session_preview}..."
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

    # 2. 使用 send_reply 发送（支持自动分拆，且每段保留同一 short_id）
    project_label = body.project_name or None
    routing_header = create_message_header(short_id, project_label, 1, 1)
    message_with_header = f"{routing_header}\n{body.message_content}"
    try:
        send_result = await send_reply(
            chat_id=body.chat_id,
            message=body.message_content,
            msg_type=body.msg_type or "markdown_v2",
            bot_key=body.bot_key,
            short_id=short_id,
            project_name=project_label,
        )
    except Exception as e:
        logger.error(f"send_reply 发送失败: {e}", exc_info=True)
        return {"success": False, "error": f"send_reply 发送失败: {e}"}

    if not send_result.get("success"):
        error_msg = str(send_result.get("error") or "IM 发送失败")
        logger.error(f"send_reply 返回失败: {error_msg}")
        return {"success": False, "error": error_msg}

    parts_sent = int(send_result.get("parts_sent", 0) or 0)

    # 3. 发送成功，保存 OutboundMessageContext
    try:
        async with db_manager.get_session() as session:
            repo = get_outbound_context_repository(session)
            await repo.create_outbound_context(
                message_id=short_id,
                bot_key=body.bot_key,
                chat_id=body.chat_id,
                agent_id=body.agent_id,
                session_id=body.session_id or None,
                content_preview=body.message_content[:200],
                project_name=body.project_name,
            )
            await session.commit()
        logger.info(
            f"出站消息上下文已保存: short_id={short_id}, "
            f"session_id={session_preview}..., parts_sent={parts_sent}"
        )
    except Exception as e:
        logger.error(f"保存出站消息上下文失败（消息已发送）: {e}", exc_info=True)

    # 4. 返回结果
    return {
        "success": True,
        "short_id": short_id,
        "message_with_header": message_with_header,
        "parts_sent": parts_sent,
    }
