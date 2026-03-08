"""
统一回调路由

提供多平台统一入口：
    POST /callback/{platform}  — 新的多平台统一入口

所有入口最终调用同一个平台无关的 process_message 管线。
旧的 /callback 路由保留在 callback.py 中（向后兼容）。
"""
import logging
from fastapi import APIRouter, Request, Header

from ..channel import get_adapter, list_adapters
from ..config import config
from ..pipeline import process_message

logger = logging.getLogger(__name__)

router = APIRouter(tags=["callback"])


@router.post("/callback/{platform}")
async def handle_callback_unified(
    request: Request,
    platform: str,
    x_api_key: str | None = Header(None, alias="x-api-key"),
):
    """
    统一多平台回调入口

    URL: POST /callback/{platform}
    例如:
        POST /callback/wecom     — 企业微信
        POST /callback/discord   — Discord
        POST /callback/telegram  — Telegram
        POST /callback/lark      — 飞书
        POST /callback/slack     — Slack

    各平台回调数据格式不同，由对应的 ChannelAdapter 负责解析。
    """
    # 鉴权
    if config.callback_auth_key and config.callback_auth_value:
        if x_api_key != config.callback_auth_value:
            logger.warning(f"回调鉴权失败: x_api_key={x_api_key}")
            return {"errcode": 401, "errmsg": "Unauthorized"}

    # 查找平台适配器（纯注册表查找，无 hardcoded 回退）
    adapter = get_adapter(platform)
    if not adapter:
        registered = list(list_adapters().keys())
        logger.warning(f"未注册的平台: {platform}, 已注册: {registered}")
        return {
            "errcode": 400,
            "errmsg": f"Unsupported platform: {platform}. "
            f"Available: {registered}"
        }

    # 读取请求体并注入 HTTP 请求头（供适配器级过滤使用，如 Slack 重试检测）
    data = await request.json()
    data["_request_headers"] = dict(request.headers)

    # Duck-type 验证响应：如果适配器支持 get_verification_response()，
    # 在 should_ignore() 之前调用（Lark/Slack URL challenge）
    if hasattr(adapter, "get_verification_response"):
        verification_resp = adapter.get_verification_response(data)
        if verification_resp is not None:
            logger.info(f"[{platform}] 返回验证响应")
            return verification_resp

    # 检查是否应忽略
    if adapter.should_ignore(data):
        logger.info(f"[{platform}] 忽略事件消息")
        return {"errcode": 0, "errmsg": "ok"}

    # 解析入站消息
    try:
        inbound = await adapter.parse_inbound(data)
    except ValueError as e:
        logger.error(f"[{platform}] 消息解析失败: {e}")
        return {"errcode": 400, "errmsg": f"Invalid message format: {e}"}

    # 进入统一处理管线
    return await process_message(adapter, inbound)
