"""
Bot 管理 API 路由

/admin/bots/* 相关接口

所有路由均需要 X-Admin-Key 请求头鉴权（通过 AS_ADMIN_KEY 环境变量配置）。
"""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ..auth import require_admin_key
from ..config import config

logger = logging.getLogger(__name__)

AdminAuth = Annotated[None, Depends(require_admin_key)]

router = APIRouter(prefix="/admin/bots", tags=["bots"])


@router.get("")
async def list_bots(_auth: AdminAuth) -> dict:
    """获取所有 Bot 列表"""
    bots = await config.list_bots()
    return {
        "success": True,
        "bots": bots,
        "total": len(bots)
    }


@router.get("/{bot_key}")
async def get_bot_by_key(bot_key: str, _auth: AdminAuth) -> dict:
    """获取单个 Bot 详情"""
    bot = await config.get_bot_detail(bot_key)
    if not bot:
        return {
            "success": False,
            "error": f"Bot '{bot_key}' 不存在"
        }

    return {
        "success": True,
        "bot": bot
    }


@router.post("")
async def create_bot(request: Request, _auth: AdminAuth) -> dict:
    """
    创建新 Bot

    Body:
        bot_key: str     (必填) 企微机器人 Webhook URL 中的 key 值
        name: str        (必填) Bot 名称
        target_url: str  完整的 A2A 目标 URL
        description: str Bot 描述
        api_key: str     调用 Agent 的 API Key
        timeout: int     超时秒数（默认 300）
        access_mode: str allow_all / whitelist / blacklist
        enabled: bool    是否启用（默认 true）
        owner_id: str    创建者标识（如 "meta-agent" 或企微用户 ID）
        whitelist: list[str]
        blacklist: list[str]
    """
    try:
        data = await request.json()
        result = await config.create_bot(data)
        return result
    except Exception as e:
        logger.error(f"创建 Bot 失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@router.put("/{bot_key}")
async def update_bot_by_key(bot_key: str, request: Request, _auth: AdminAuth) -> dict:
    """更新 Bot 配置"""
    try:
        data = await request.json()
        result = await config.update_bot(bot_key, data)
        return result
    except Exception as e:
        logger.error(f"更新 Bot 失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@router.delete("/{bot_key}")
async def delete_bot_by_key(bot_key: str, _auth: AdminAuth) -> dict:
    """删除 Bot"""
    result = await config.delete_bot(bot_key)
    return result
