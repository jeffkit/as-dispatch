"""
微信个人号集成路由

处理微信个人号消息：
- 通过 iLinkAI HTTP 长轮询接收消息
- 将消息注入统一处理管线
- Bot 生命周期管理（启动/停止/状态）
- QR 码登录流程
- Admin HTTP API 用于动态管理微信 Bot
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from ..clients.weixin import WeixinClient
from ..channel import get_adapter
from ..channel.weixin import (
    WEIXIN_MSG_TYPE_NAMES,
    WEIXIN_MSG_TYPE_TEXT,
    WEIXIN_NON_TEXT_PLACEHOLDERS,
    WEIXIN_MESSAGE_TYPE_USER,
    WeixinPollerStatus,
)
from ..config import config
from ..database import get_db_manager
from ..pipeline import process_message
from ..repository import get_chatbot_repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/weixin", tags=["weixin-admin"])


# ============== 数据类 ==============


@dataclass
class QRLoginAttempt:
    """追踪进行中的 QR 码登录流程"""
    qrcode: str
    qrcode_url: str
    status: str = "wait"
    refresh_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    bot_token: str | None = None
    ilink_bot_id: str | None = None
    ilink_user_id: str | None = None
    _client: WeixinClient | None = field(default=None, repr=False)


@dataclass
class WeixinPoller:
    """单个微信 Bot 的长轮询运行时状态"""
    bot_key: str
    client: WeixinClient
    status: WeixinPollerStatus = WeixinPollerStatus.RUNNING
    get_updates_buf: str = ""
    context_tokens: dict[str, str] = field(default_factory=dict)
    consecutive_failures: int = 0
    _task: asyncio.Task[None] | None = None
    ilink_bot_id: str = ""
    last_poll_at: datetime | None = None


# ============== 模块级状态 ==============

weixin_pollers: dict[str, WeixinPoller] = {}
weixin_login_attempts: dict[str, QRLoginAttempt] = {}


# ============== 消息处理 ==============


def _parse_weixin_message(raw_msg: dict[str, Any], bot_key: str) -> dict[str, Any] | None:
    """
    将 iLinkAI WeixinMessage 转换为适配器可消费的 raw_data dict。

    过滤非用户消息和群聊消息。
    """
    msg_type_code = raw_msg.get("message_type")
    if msg_type_code is not None and msg_type_code != WEIXIN_MESSAGE_TYPE_USER:
        return None

    if raw_msg.get("group_id"):
        return None

    item_list = raw_msg.get("item_list") or []
    if not item_list:
        return None

    first_item = item_list[0]
    item_type = first_item.get("type", 0)
    type_name = WEIXIN_MSG_TYPE_NAMES.get(item_type, "unknown")

    if item_type == WEIXIN_MSG_TYPE_TEXT:
        text_item = first_item.get("text_item") or {}
        content = text_item.get("text", "")
    elif item_type in WEIXIN_NON_TEXT_PLACEHOLDERS:
        content = WEIXIN_NON_TEXT_PLACEHOLDERS[item_type]
    else:
        content = f"[收到了未知类型消息 (type={item_type})]"

    if not content:
        return None

    from_user_id = raw_msg.get("from_user_id", "")

    result: dict[str, Any] = {
        "type": "direct",
        "sender_id": from_user_id,
        "sender_name": from_user_id[:8] if from_user_id else "unknown",
        "content": content,
        "message_type": type_name,
        "context_token": raw_msg.get("context_token", ""),
        "message_id": str(raw_msg.get("message_id", "")),
        "_bot_key": bot_key,
    }

    # 非文本消息：传递完整 item_list 供媒体处理模块使用
    if item_type != WEIXIN_MSG_TYPE_TEXT:
        result["_media_items"] = item_list

    return result


async def handle_weixin_message(raw_data: dict[str, Any], bot_key: str) -> None:
    """
    处理单条微信消息（通过统一管线）

    将解析后的消息 dict 经由 WeixinAdapter 转换为 InboundMessage，
    进入统一的 process_message 管线。
    """
    adapter = get_adapter("weixin")
    if not adapter:
        logger.error("[weixin] WeixinAdapter 未注册，无法处理消息")
        return

    if adapter.should_ignore(raw_data):
        logger.debug(f"[weixin] 忽略消息: sender={raw_data.get('sender_id')}")
        return

    try:
        inbound = await adapter.parse_inbound(raw_data, bot_key=bot_key)
    except ValueError as e:
        logger.warning(f"[weixin] 消息解析失败（跳过）: {e}")
        return

    try:
        await process_message(adapter, inbound)
    except Exception as e:
        logger.error(f"[weixin] 处理消息失败: {e}", exc_info=True)


# ============== 长轮询循环 ==============


async def _poll_loop(poller: WeixinPoller) -> None:
    """
    微信消息长轮询主循环。

    持续调用 getUpdates 获取新消息，解析后注入处理管线。
    包含指数退避重试和会话过期检测逻辑。
    """
    bot_key = poller.bot_key
    logger.info(f"[weixin] 轮询循环启动: bot_key={bot_key[:10]}...")

    while poller.status == WeixinPollerStatus.RUNNING:
        try:
            resp = await poller.client.get_updates(
                get_updates_buf=poller.get_updates_buf,
            )

            poller.last_poll_at = datetime.now(timezone.utc)

            # 检查 API 错误
            errcode = resp.get("errcode", 0)
            ret = resp.get("ret", 0)
            is_error = (ret != 0 and ret is not None) or (errcode != 0 and errcode is not None)

            if is_error:
                # 会话过期检测
                if errcode == -14 or ret == -14:
                    logger.warning(
                        f"[weixin] 会话过期 (errcode=-14): bot_key={bot_key[:10]}..., "
                        f"暂停 1 小时后重试"
                    )
                    poller.status = WeixinPollerStatus.PAUSED
                    await asyncio.sleep(3600)

                    if poller.status != WeixinPollerStatus.PAUSED:
                        break

                    # 1 小时后重试
                    poller.status = WeixinPollerStatus.RUNNING
                    logger.info(
                        f"[weixin] 会话暂停结束，重试: bot_key={bot_key[:10]}..."
                    )
                    try:
                        test_resp = await poller.client.get_updates(
                            get_updates_buf=poller.get_updates_buf,
                        )
                        test_errcode = test_resp.get("errcode", 0)
                        if test_errcode == -14:
                            logger.error(
                                f"[weixin] 重试仍失败，会话已过期: bot_key={bot_key[:10]}..."
                            )
                            poller.status = WeixinPollerStatus.EXPIRED
                            break
                    except Exception:
                        logger.error(
                            f"[weixin] 重试异常，会话已过期: bot_key={bot_key[:10]}...",
                            exc_info=True,
                        )
                        poller.status = WeixinPollerStatus.EXPIRED
                        break
                    continue

                # 其他 API 错误：指数退避
                poller.consecutive_failures += 1
                backoff = min(2 ** poller.consecutive_failures, 30)
                logger.error(
                    f"[weixin] getUpdates 错误: ret={ret}, errcode={errcode}, "
                    f"errmsg={resp.get('errmsg', '')}, "
                    f"failures={poller.consecutive_failures}, backoff={backoff}s"
                )
                await asyncio.sleep(backoff)
                continue

            # 成功：重置失败计数
            poller.consecutive_failures = 0

            # 更新轮询游标
            new_buf = resp.get("get_updates_buf", "")
            if new_buf:
                poller.get_updates_buf = new_buf
                # 持久化 get_updates_buf 到数据库
                await _persist_get_updates_buf(bot_key, new_buf)

            # 处理消息
            msgs = resp.get("msgs") or []
            for raw_msg in msgs:
                from_user = raw_msg.get("from_user_id", "")

                # 缓存 context_token
                ctx_token = raw_msg.get("context_token", "")
                if from_user and ctx_token:
                    poller.context_tokens[from_user] = ctx_token

                # 解析并处理消息
                parsed = _parse_weixin_message(raw_msg, bot_key)
                if not parsed:
                    continue

                logger.info(
                    f"[weixin] 收到消息: bot_key={bot_key[:10]}..., "
                    f"from={from_user[:8] if from_user else '?'}, "
                    f"type={parsed.get('message_type')}, "
                    f"text={parsed.get('content', '')[:50]}"
                )

                # 发送打字指示器（非阻塞，失败不影响消息处理）
                await _send_typing_indicator(poller, from_user, ctx_token)

                try:
                    await handle_weixin_message(parsed, bot_key)
                except Exception as e:
                    logger.error(
                        f"[weixin] 处理单条消息失败: {e}", exc_info=True
                    )

                # 取消打字指示器（非阻塞）
                await _cancel_typing_indicator(poller, from_user, ctx_token)

        except asyncio.CancelledError:
            logger.info(f"[weixin] 轮询循环被取消: bot_key={bot_key[:10]}...")
            break
        except Exception as e:
            poller.consecutive_failures += 1
            backoff = min(2 ** poller.consecutive_failures, 30)
            logger.error(
                f"[weixin] 轮询异常: {e}, "
                f"failures={poller.consecutive_failures}, backoff={backoff}s",
                exc_info=True,
            )
            await asyncio.sleep(backoff)

    logger.info(
        f"[weixin] 轮询循环结束: bot_key={bot_key[:10]}..., "
        f"status={poller.status.value}"
    )


# ============== 打字指示器 ==============


async def _send_typing_indicator(
    poller: WeixinPoller, user_id: str, context_token: str,
) -> None:
    """发送打字指示器（失败不影响消息流）"""
    try:
        config_resp = await poller.client.get_config(user_id, context_token)
        typing_ticket = config_resp.get("typing_ticket", "")
        if typing_ticket:
            await poller.client.send_typing(
                ilink_user_id=user_id,
                typing_ticket=typing_ticket,
                status=1,  # typing
            )
    except Exception as e:
        logger.debug(f"[weixin] 发送打字指示器失败（非关键）: {e}")


async def _cancel_typing_indicator(
    poller: WeixinPoller, user_id: str, context_token: str,
) -> None:
    """取消打字指示器（失败不影响消息流）"""
    try:
        config_resp = await poller.client.get_config(user_id, context_token)
        typing_ticket = config_resp.get("typing_ticket", "")
        if typing_ticket:
            await poller.client.send_typing(
                ilink_user_id=user_id,
                typing_ticket=typing_ticket,
                status=2,  # cancel
            )
    except Exception as e:
        logger.debug(f"[weixin] 取消打字指示器失败（非关键）: {e}")


# ============== get_updates_buf 持久化 ==============


async def _persist_get_updates_buf(bot_key: str, buf: str) -> None:
    """将 get_updates_buf 持久化到数据库的 platform_config 中。

    安全机制: 从内存 poller 补全关键凭据字段（bot_token, ilink_bot_id,
    login_status），防止并发 read-modify-write 或 session 缓存导致
    credentials 被意外覆盖为空。
    """
    try:
        credential_fields: dict[str, str] = {}
        poller = weixin_pollers.get(bot_key)
        if poller:
            if poller.client.bot_token:
                credential_fields["bot_token"] = poller.client.bot_token
            if poller.ilink_bot_id:
                credential_fields["ilink_bot_id"] = poller.ilink_bot_id
            credential_fields["login_status"] = "logged_in"

        db = get_db_manager()
        async with db.get_session() as session:
            bot_repo = get_chatbot_repository(session)
            bot = await bot_repo.get_by_bot_key(bot_key)
            if bot:
                platform_config = bot.get_platform_config()

                for key, value in credential_fields.items():
                    if not platform_config.get(key):
                        platform_config[key] = value

                platform_config["get_updates_buf"] = buf
                platform_config["last_active_at"] = datetime.now(timezone.utc).isoformat()
                await bot_repo.update(
                    bot_id=bot.id,
                    platform_config=platform_config,
                )
                await session.commit()
    except Exception as e:
        logger.warning(f"[weixin] 持久化 get_updates_buf 失败: {e}")


# ============== 启动/停止 ==============


async def start_weixin(bot_key: str) -> dict[str, Any]:
    """
    启动微信 Bot 长轮询循环。

    从数据库加载凭据，创建 WeixinClient 和 WeixinPoller，
    启动后台 asyncio.Task。
    """
    await config.reload_config()

    bot_config = config.get_bot_or_default(bot_key)
    if not bot_config:
        return {"success": False, "error": f"Bot '{bot_key}' 不存在"}
    if not bot_config._bot:
        return {"success": False, "error": f"Bot '{bot_key}' 缺少数据库记录"}
    if bot_config._bot.platform != "weixin":
        return {"success": False, "error": f"Bot '{bot_key}' 不是微信平台"}

    platform_config = bot_config._bot.get_platform_config()
    bot_token = platform_config.get("bot_token", "")
    ilink_bot_id = platform_config.get("ilink_bot_id", "")

    if not bot_token:
        return {
            "success": False,
            "error": f"Bot '{bot_key}' 未登录，请先完成二维码登录",
        }

    # 如果已经运行，先停止
    if bot_key in weixin_pollers:
        await stop_weixin(bot_key)

    client = WeixinClient(bot_token=bot_token)

    # 从数据库加载 get_updates_buf
    get_updates_buf = platform_config.get("get_updates_buf", "")

    poller = WeixinPoller(
        bot_key=bot_key,
        client=client,
        status=WeixinPollerStatus.RUNNING,
        get_updates_buf=get_updates_buf,
        ilink_bot_id=ilink_bot_id,
    )

    task = asyncio.create_task(_poll_loop(poller))
    poller._task = task
    weixin_pollers[bot_key] = poller

    logger.info(
        f"[weixin] Bot 已启动: bot_key={bot_key[:10]}..., "
        f"ilink_bot_id={ilink_bot_id}"
    )

    return {
        "success": True,
        "bot_key": bot_key,
        "status": "running",
        "ilink_bot_id": ilink_bot_id,
        "message": "微信 Bot 已启动，正在接收消息",
    }


async def stop_weixin(bot_key: str) -> dict[str, Any]:
    """停止指定微信 Bot 的长轮询循环"""
    poller = weixin_pollers.pop(bot_key, None)
    if not poller:
        return {"success": False, "error": f"微信 Bot '{bot_key}' 未在运行"}

    logger.info(f"[weixin] 停止 Bot: bot_key={bot_key[:10]}...")

    poller.status = WeixinPollerStatus.STOPPED

    if poller._task and not poller._task.done():
        poller._task.cancel()
        try:
            await poller._task
        except asyncio.CancelledError:
            pass

    await poller.client.close()

    return {"success": True, "bot_key": bot_key, "message": "微信 Bot 已停止"}


# ============== Admin API 端点 ==============


@router.post("/{bot_key}/qr-login")
async def qr_login_endpoint(bot_key: str) -> dict[str, Any]:
    """触发微信 QR 码登录流程"""
    await config.reload_config()

    bot_config = config.get_bot_or_default(bot_key)
    if not bot_config:
        return {"success": False, "error": f"Bot '{bot_key}' 不存在"}
    if not bot_config._bot or bot_config._bot.platform != "weixin":
        return {"success": False, "error": f"Bot '{bot_key}' 不是微信平台"}

    client = WeixinClient()
    try:
        qr_data = await client.get_qrcode()
    except Exception as e:
        await client.close()
        logger.error(f"[weixin] 获取二维码失败: {e}", exc_info=True)
        return {"success": False, "error": f"获取二维码失败: {e}"}

    qrcode = qr_data.get("qrcode", "")
    qrcode_url = qr_data.get("qrcode_img_content", "")

    attempt = QRLoginAttempt(
        qrcode=qrcode,
        qrcode_url=qrcode_url,
        _client=client,
    )
    weixin_login_attempts[bot_key] = attempt

    logger.info(f"[weixin] QR 登录已触发: bot_key={bot_key[:10]}...")

    return {
        "success": True,
        "bot_key": bot_key,
        "qrcode": qrcode,
        "qrcode_url": qrcode_url,
        "message": "请使用微信扫描二维码完成登录",
    }


@router.get("/{bot_key}/qr-status")
async def qr_status_endpoint(bot_key: str) -> dict[str, Any]:
    """轮询 QR 码登录状态"""
    attempt = weixin_login_attempts.get(bot_key)
    if not attempt:
        return {
            "success": False,
            "error": f"没有进行中的登录流程，请先调用 POST /{bot_key}/qr-login",
        }

    client = attempt._client
    if not client:
        client = WeixinClient()
        attempt._client = client

    try:
        status_data = await client.get_qrcode_status(attempt.qrcode)
    except Exception as e:
        logger.error(f"[weixin] 获取 QR 状态失败: {e}", exc_info=True)
        return {"success": False, "error": f"获取 QR 状态失败: {e}"}

    status = status_data.get("status", "wait")
    attempt.status = status

    if status == "wait":
        return {
            "success": True,
            "bot_key": bot_key,
            "status": "wait",
            "qrcode_url": attempt.qrcode_url,
            "refresh_count": attempt.refresh_count,
            "message": "等待扫码...",
        }

    elif status == "scaned":
        return {
            "success": True,
            "bot_key": bot_key,
            "status": "scaned",
            "message": "已扫码，请在手机上确认",
        }

    elif status == "expired":
        # 自动刷新二维码（最多 3 次）
        if attempt.refresh_count < 3:
            attempt.refresh_count += 1
            try:
                new_qr = await client.get_qrcode()
                attempt.qrcode = new_qr.get("qrcode", "")
                attempt.qrcode_url = new_qr.get("qrcode_img_content", "")
                attempt.status = "wait"
                logger.info(
                    f"[weixin] QR 已自动刷新 ({attempt.refresh_count}/3): "
                    f"bot_key={bot_key[:10]}..."
                )
                return {
                    "success": True,
                    "bot_key": bot_key,
                    "status": "wait",
                    "qrcode_url": attempt.qrcode_url,
                    "refresh_count": attempt.refresh_count,
                    "message": f"二维码已过期，已自动刷新（第 {attempt.refresh_count}/3 次）",
                }
            except Exception as e:
                logger.error(f"[weixin] 刷新 QR 失败: {e}", exc_info=True)
                return {"success": False, "error": f"刷新二维码失败: {e}"}
        else:
            # 清理
            await client.close()
            weixin_login_attempts.pop(bot_key, None)
            return {
                "success": False,
                "bot_key": bot_key,
                "status": "expired",
                "error": "二维码已过期且自动刷新次数已达上限（3 次），请重新触发登录",
            }

    elif status == "confirmed":
        # 登录成功，提取凭据
        bot_token = status_data.get("bot_token", "")
        ilink_bot_id = status_data.get("ilink_bot_id", "")
        ilink_user_id = status_data.get("ilink_user_id", "")

        if not ilink_bot_id:
            logger.error("[weixin] 登录确认但缺少 ilink_bot_id")
            await client.close()
            weixin_login_attempts.pop(bot_key, None)
            return {
                "success": False,
                "error": "登录失败：服务器未返回 ilink_bot_id",
            }

        # 持久化凭据到数据库
        try:
            db = get_db_manager()
            async with db.get_session() as session:
                bot_repo = get_chatbot_repository(session)
                bot = await bot_repo.get_by_bot_key(bot_key)
                if bot:
                    platform_config = bot.get_platform_config()
                    platform_config["bot_token"] = bot_token
                    platform_config["ilink_bot_id"] = ilink_bot_id
                    platform_config["ilink_user_id"] = ilink_user_id
                    platform_config["login_status"] = "logged_in"
                    platform_config["last_active_at"] = (
                        datetime.now(timezone.utc).isoformat()
                    )
                    await bot_repo.update(
                        bot_id=bot.id,
                        platform_config=platform_config,
                    )
                    await session.commit()
                    logger.info(
                        f"[weixin] 凭据已持久化: bot_key={bot_key[:10]}..., "
                        f"ilink_bot_id={ilink_bot_id}"
                    )
        except Exception as e:
            logger.error(f"[weixin] 持久化凭据失败: {e}", exc_info=True)

        # 清理登录尝试
        await client.close()
        weixin_login_attempts.pop(bot_key, None)

        return {
            "success": True,
            "bot_key": bot_key,
            "status": "confirmed",
            "ilink_bot_id": ilink_bot_id,
            "message": "登录成功！可以使用 POST /{bot_key}/start 启动消息接收",
        }

    else:
        return {
            "success": False,
            "error": f"未知的 QR 状态: {status}",
        }


@router.post("/{bot_key}/start")
async def start_endpoint(bot_key: str) -> dict[str, Any]:
    """启动微信 Bot 长轮询"""
    result = await start_weixin(bot_key)
    return result


@router.post("/{bot_key}/stop")
async def stop_endpoint(bot_key: str) -> dict[str, Any]:
    """停止微信 Bot 长轮询"""
    result = await stop_weixin(bot_key)
    return result


@router.get("/{bot_key}/status")
async def status_endpoint(bot_key: str) -> dict[str, Any]:
    """获取微信 Bot 状态"""
    poller = weixin_pollers.get(bot_key)
    if not poller:
        return {"running": False, "bot_key": bot_key, "status": "stopped"}

    return {
        "running": poller.status == WeixinPollerStatus.RUNNING,
        "bot_key": bot_key,
        "status": poller.status.value,
        "ilink_bot_id": poller.ilink_bot_id,
        "consecutive_failures": poller.consecutive_failures,
        "last_poll_at": poller.last_poll_at.isoformat() if poller.last_poll_at else None,
        "active_users": len(poller.context_tokens),
    }


@router.get("/list")
async def list_endpoint() -> dict[str, Any]:
    """列出所有微信 Bot 状态"""
    bots_list: list[dict[str, Any]] = []

    # 从数据库获取所有微信平台的 Bot
    try:
        db = get_db_manager()
        async with db.get_session() as session:
            bot_repo = get_chatbot_repository(session)
            all_bots = await bot_repo.get_all(enabled_only=False)
            for bot in all_bots:
                if bot.platform != "weixin":
                    continue

                poller = weixin_pollers.get(bot.bot_key)
                platform_config = bot.get_platform_config()
                bots_list.append({
                    "bot_key": bot.bot_key,
                    "name": bot.name,
                    "running": poller is not None and poller.status == WeixinPollerStatus.RUNNING,
                    "status": poller.status.value if poller else "stopped",
                    "ilink_bot_id": platform_config.get("ilink_bot_id", ""),
                    "login_status": platform_config.get("login_status", ""),
                })
    except Exception as e:
        logger.error(f"[weixin] 获取 Bot 列表失败: {e}", exc_info=True)

    running_count = sum(1 for b in bots_list if b["running"])

    return {
        "bots": bots_list,
        "total": len(bots_list),
        "running_count": running_count,
    }
