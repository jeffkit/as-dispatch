"""
Bot 管理 API 路由

/admin/bots/* 相关接口
"""
import logging

from fastapi import APIRouter, Request

from ..config import config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/bots", tags=["bots"])


@router.get("")
async def list_bots() -> dict:
    """获取所有 Bot 列表"""
    bots = await config.list_bots()
    return {
        "success": True,
        "bots": bots,
        "total": len(bots)
    }


@router.get("/{bot_key}")
async def get_bot_by_key(bot_key: str) -> dict:
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
async def create_bot(request: Request) -> dict:
    """
    创建新 Bot

    Body:
        bot_key: str (必填)
        name: str (必填)
        target_url: str (必填) - 完整的目标 URL
        description: str
        api_key: str
        timeout: int
        access_mode: str
        enabled: bool
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
async def update_bot_by_key(bot_key: str, request: Request) -> dict:
    """更新 Bot 配置"""
    try:
        data = await request.json()
        result = await config.update_bot(bot_key, data)
        return result
    except Exception as e:
        logger.error(f"更新 Bot 失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@router.delete("/{bot_key}")
async def delete_bot_by_key(bot_key: str) -> dict:
    """删除 Bot"""
    result = await config.delete_bot(bot_key)
    return result
