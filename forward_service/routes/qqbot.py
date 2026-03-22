"""
QQ Bot 集成路由

处理 QQ Bot 消息：
- 通过 WebSocket Gateway 接收消息（类似 Discord）
- 将消息注入统一处理管线
- Bot 生命周期管理（启动/停止）
- HTTP API 用于动态启停 QQ Bot 连接
"""
import asyncio
import logging
from typing import Dict

from fastapi import APIRouter
from ..clients.qqbot import QQBotClient
from ..config import config
from ..channel import get_adapter
from ..pipeline import process_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/qqbot", tags=["qqbot-admin"])

# 全局 QQ Bot 客户端实例字典
qqbot_clients: Dict[str, QQBotClient] = {}


async def handle_qqbot_message(raw_msg: dict, bot_key: str):
    """
    处理 QQ Bot 消息（通过统一管线）

    将 QQBotClient 解析的消息 dict 经由 QQBotAdapter 转换为 InboundMessage，
    进入统一的 process_message 管线。

    Args:
        raw_msg: QQBotClient._parse_message_event 返回的消息字典
        bot_key: Bot 标识键
    """
    adapter = get_adapter("qqbot")
    if not adapter:
        logger.error("[qqbot] QQBotAdapter 未注册，无法处理消息")
        return

    raw_msg["_bot_key"] = bot_key

    if adapter.should_ignore(raw_msg):
        logger.debug(f"[qqbot] 忽略消息: sender={raw_msg.get('sender_id')}")
        return

    try:
        inbound = await adapter.parse_inbound(raw_msg, bot_key=bot_key)
    except ValueError as e:
        logger.warning(f"[qqbot] 消息解析失败（跳过）: {e}")
        return

    try:
        await process_message(adapter, inbound)
    except Exception as e:
        logger.error(f"[qqbot] 处理消息失败: {e}", exc_info=True)
        # 尝试发送错误提示
        try:
            client = qqbot_clients.get(bot_key)
            if client:
                msg_type = raw_msg.get("type", "c2c")
                target_id = (
                    raw_msg.get("sender_id")
                    if msg_type == "c2c"
                    else raw_msg.get("group_openid") or raw_msg.get("channel_id")
                )
                if target_id:
                    await client.send_text(
                        msg_type, target_id,
                        f"❌ 处理消息时出错: {str(e)[:200]}",
                        msg_id=raw_msg.get("message_id"),
                    )
        except Exception:
            pass


async def start_qqbot(bot_key: str):
    """
    启动 QQ Bot（WebSocket Gateway 连接）

    从 Bot 配置的 platform_config 中读取 app_id 和 client_secret，
    创建 QQBotClient 并启动。

    Args:
        bot_key: Bot 标识键
    """
    bot_config = config.get_bot_or_default(bot_key)
    if not bot_config:
        logger.error(f"未找到 QQ Bot 配置: {bot_key}")
        return

    if not bot_config._bot:
        logger.error(f"QQ Bot 配置缺少底层数据库模型: {bot_key}")
        return

    platform_config = bot_config._bot.get_platform_config()
    app_id = platform_config.get("app_id", "")
    client_secret = platform_config.get("client_secret", "")

    if not app_id or not client_secret:
        logger.error(f"QQ Bot 凭据未配置: {bot_key} (需要 app_id 和 client_secret)")
        return

    async def on_message(raw_msg: dict):
        await handle_qqbot_message(raw_msg, bot_key)

    client = QQBotClient(
        app_id=app_id,
        client_secret=client_secret,
        on_message=on_message,
    )
    qqbot_clients[bot_key] = client

    logger.info(f"[qqbot] 启动 QQ Bot: {bot_key}, appId={app_id}")
    await client.start()


async def stop_qqbot(bot_key: str):
    """停止指定 QQ Bot 的 WebSocket 连接"""
    client = qqbot_clients.pop(bot_key, None)
    if client:
        logger.info(f"[qqbot] 停止 QQ Bot: {bot_key}")
        await client.close()


@router.post("/{bot_key}/start")
async def start_qqbot_endpoint(bot_key: str):
    """动态启动指定 QQ Bot 的 WebSocket 连接（无需重启服务）"""
    await config.reload_config()

    bot_cfg = config.get_bot_or_default(bot_key)
    if not bot_cfg:
        return {"success": False, "error": f"Bot '{bot_key}' 不存在"}
    if not bot_cfg._bot or bot_cfg._bot.platform != "qqbot":
        return {"success": False, "error": f"Bot '{bot_key}' 不是 QQ Bot 平台"}

    if bot_key in qqbot_clients:
        await stop_qqbot(bot_key)

    task = asyncio.create_task(start_qqbot(bot_key))
    await asyncio.sleep(3)

    client = qqbot_clients.get(bot_key)
    connected = client is not None and client.gateway._session_id is not None if client else False
    return {
        "success": True,
        "bot_key": bot_key,
        "connected": connected,
        "session_id": client.gateway._session_id if connected else None,
    }


@router.post("/{bot_key}/stop")
async def stop_qqbot_endpoint(bot_key: str):
    """停止指定 QQ Bot 的 WebSocket 连接"""
    if bot_key not in qqbot_clients:
        return {"success": False, "error": f"QQ Bot '{bot_key}' 未在运行"}
    await stop_qqbot(bot_key)
    return {"success": True, "bot_key": bot_key}


@router.get("/{bot_key}/status")
async def qqbot_status_endpoint(bot_key: str):
    """获取指定 QQ Bot 的连接状态"""
    client = qqbot_clients.get(bot_key)
    if not client:
        return {"running": False, "bot_key": bot_key}
    return {
        "running": True,
        "bot_key": bot_key,
        "app_id": client.app_id,
        "session_id": client.gateway._session_id,
        "connected": client.gateway._session_id is not None,
    }
