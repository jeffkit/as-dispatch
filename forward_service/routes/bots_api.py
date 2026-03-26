"""
Bot 管理 API（用户级接口）

/api/bots/* — 使用 as-enterprise JWT Token 鉴权，供 AgentStudio 内置 MCP 工具调用。

与 /admin/bots/* 的区别：
- /admin/bots: X-Admin-Key 鉴权（内部管理使用）
- /api/bots:   JWT Bearer Token 鉴权（用户工具调用）
"""
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from ..auth import require_enterprise_jwt
from ..config import DEFAULT_TIMEOUT, config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bots", tags=["bots-api"])


class BotAsyncFields(BaseModel):
    """异步模式相关字段（创建/更新共用校验）"""

    model_config = ConfigDict(extra="ignore")

    async_mode: Optional[bool] = None
    processing_message: Optional[str] = Field(None, max_length=500)
    sync_timeout_seconds: Optional[int] = Field(None, ge=5, le=300)
    max_task_duration_seconds: Optional[int] = Field(None, ge=60, le=7200)


class BotCreateRequest(BotAsyncFields):
    model_config = ConfigDict(extra="ignore")

    bot_key: str
    name: str
    target_url: str = ""
    url_template: str = ""
    description: str = ""
    api_key: str = ""
    timeout: int = DEFAULT_TIMEOUT
    enabled: bool = True
    owner_id: Optional[str] = None
    access_mode: str = "allow_all"
    platform: str = "wecom"
    whitelist: list[str] = Field(default_factory=list)
    blacklist: list[str] = Field(default_factory=list)
    platform_config: Optional[dict[str, Any]] = None


class BotUpdateRequest(BotAsyncFields):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    description: Optional[str] = None
    target_url: Optional[str] = None
    url_template: Optional[str] = None
    api_key: Optional[str] = None
    timeout: Optional[int] = None
    enabled: Optional[bool] = None
    access_mode: Optional[str] = None
    platform_config: Optional[dict[str, Any]] = None
    whitelist: Optional[list[str]] = None
    blacklist: Optional[list[str]] = None


@router.get("")
async def list_bots(_user=Depends(require_enterprise_jwt)) -> dict:
    """获取所有 Bot 列表"""
    bots = await config.list_bots()
    return {"success": True, "bots": bots, "total": len(bots)}


@router.get("/{bot_key}")
async def get_bot(bot_key: str, _user=Depends(require_enterprise_jwt)) -> dict:
    """获取单个 Bot 详情"""
    bot = await config.get_bot_detail(bot_key)
    if not bot:
        return {"success": False, "error": f"Bot '{bot_key}' 不存在"}
    return {"success": True, "bot": bot}


@router.post("")
async def create_bot(request: Request, _user=Depends(require_enterprise_jwt)) -> dict:
    """
    创建新 Bot

    Body:
        bot_key: str     (必填) 企微机器人 Webhook URL 中的 key 值（UUID 格式）
        name: str        (必填) Bot 名称
        target_url: str  完整的 A2A 目标 URL
        description: str Bot 描述
        api_key: str     调用 Agent 的 API Key
        timeout: int     超时秒数（默认 300）
        enabled: bool    是否启用（默认 true）
        owner_id: str    创建者标识
    """
    try:
        raw = await request.json()
        req = BotCreateRequest.model_validate(raw)
        data = req.model_dump(exclude_unset=True)
        result = await config.create_bot(data)
        return result
    except Exception as e:
        logger.error(f"创建 Bot 失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@router.put("/{bot_key}")
async def update_bot(bot_key: str, request: Request, _user=Depends(require_enterprise_jwt)) -> dict:
    """更新 Bot 配置"""
    try:
        raw = await request.json()
        req = BotUpdateRequest.model_validate(raw)
        data = req.model_dump(exclude_unset=True)
        result = await config.update_bot(bot_key, data)
        return result
    except Exception as e:
        logger.error(f"更新 Bot 失败: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
