"""
消息处理管线（平台无关）

从 callback.py 中抽取的核心业务逻辑。
接收统一的 InboundMessage，完成：
  命令处理 → 会话管理 → 去重 → 并发控制 → 转发 → 响应

所有平台共用此管线，不感知平台细节。
"""
import hashlib
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from .channel.base import InboundMessage, OutboundMessage, ChannelAdapter, SendResult
from .config import config
from .session_manager import get_session_manager, get_effective_user, compute_processing_key
from .database import get_db_manager
from .repository import get_chat_info_repository, get_processing_session_repository

logger = logging.getLogger(__name__)


# ============== 延迟导入（避免循环依赖） ==============


def _import_services():
    """延迟导入服务层，避免循环依赖"""
    from .services import forward_to_agent_with_user_project
    return forward_to_agent_with_user_project


def _import_route_helpers():
    """延迟导入路由模块中的辅助函数，避免循环依赖"""
    from .routes.admin import add_request_log, update_request_log, RequestLogData
    from .routes.admin_commands import (
        check_is_admin,
        get_system_status,
        get_admin_full_help,
        get_regular_user_help,
        get_bots_list,
        get_bot_detail,
        update_bot_config,
        get_pending_list,
        get_recent_logs,
        get_error_logs,
        check_agents_health,
        add_pending_request,
        remove_pending_request,
    )
    from .routes.project_commands import (
        is_project_command,
        handle_project_command,
    )
    from .routes.tunnel_commands import (
        is_tunnel_command,
        handle_tunnel_command,
    )
    from .routes.bot_commands import (
        is_bot_command,
        handle_bot_command,
        get_register_help,
    )
    return {
        "add_request_log": add_request_log,
        "update_request_log": update_request_log,
        "RequestLogData": RequestLogData,
        "check_is_admin": check_is_admin,
        "get_system_status": get_system_status,
        "get_admin_full_help": get_admin_full_help,
        "get_regular_user_help": get_regular_user_help,
        "get_bots_list": get_bots_list,
        "get_bot_detail": get_bot_detail,
        "update_bot_config": update_bot_config,
        "get_pending_list": get_pending_list,
        "get_recent_logs": get_recent_logs,
        "get_error_logs": get_error_logs,
        "check_agents_health": check_agents_health,
        "add_pending_request": add_pending_request,
        "remove_pending_request": remove_pending_request,
        "is_project_command": is_project_command,
        "handle_project_command": handle_project_command,
        "is_tunnel_command": is_tunnel_command,
        "handle_tunnel_command": handle_tunnel_command,
        "is_bot_command": is_bot_command,
        "handle_bot_command": handle_bot_command,
        "get_register_help": get_register_help,
    }


# 模块级缓存（首次调用后缓存）
_helpers = None


def _get_helpers():
    global _helpers
    if _helpers is None:
        _helpers = _import_route_helpers()
    return _helpers


# ============== 消息去重 ==============

_dedup_cache: dict[str, float] = {}
_DEDUP_TTL_SECONDS = 120
_DEDUP_CLEANUP_THRESHOLD = 500


def _make_dedup_key(bot_key: str, chat_id: str, content: str, message_id: str) -> str:
    """生成去重 key：优先使用消息 ID，否则用 bot+chat+内容 的哈希。"""
    if message_id:
        return f"id:{bot_key}:{chat_id}:{message_id}"
    raw = f"{bot_key}|{chat_id}|{(content or '').strip()}"
    return f"hash:{hashlib.sha256(raw.encode()).hexdigest()}"


def _is_duplicate_message(dedup_key: str) -> bool:
    now = time.time()
    if dedup_key in _dedup_cache:
        if _dedup_cache[dedup_key] > now:
            return True
        del _dedup_cache[dedup_key]
    return False


def _mark_message_processed(dedup_key: str) -> None:
    now = time.time()
    _dedup_cache[dedup_key] = now + _DEDUP_TTL_SECONDS
    if len(_dedup_cache) >= _DEDUP_CLEANUP_THRESHOLD:
        expired = [k for k, v in _dedup_cache.items() if v <= now]
        for k in expired:
            del _dedup_cache[k]


def _compute_elapsed_seconds(started_at: datetime) -> float:
    now_utc = datetime.now(timezone.utc)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return (now_utc - started_at).total_seconds()


# ============== 辅助函数 ==============


def _build_outbound(
    adapter: ChannelAdapter,
    inbound: InboundMessage,
    text: str,
    bot_key: str,
    short_id: Optional[str] = None,
    project_name: Optional[str] = None,
    msg_type: str = "text",
) -> OutboundMessage:
    """构建出站消息"""
    mentioned = (
        [inbound.user_id] if inbound.chat_type == "group" else None
    )
    return OutboundMessage(
        chat_id=inbound.chat_id,
        text=text,
        msg_type=msg_type,
        bot_key=bot_key,
        short_id=short_id,
        project_name=project_name,
        mentioned_user_ids=mentioned,
    )


async def _send(
    adapter: ChannelAdapter,
    inbound: InboundMessage,
    text: str,
    bot_key: str,
    short_id: Optional[str] = None,
    project_name: Optional[str] = None,
    msg_type: str = "text",
) -> SendResult:
    """快捷发送：构建 OutboundMessage 并通过适配器发送"""
    msg = _build_outbound(
        adapter, inbound, text, bot_key,
        short_id=short_id, project_name=project_name, msg_type=msg_type,
    )
    return await adapter.send_outbound(msg)


# ============== 核心管线 ==============


async def process_message(
    adapter: ChannelAdapter,
    inbound: InboundMessage,
) -> dict:
    """
    核心消息处理管线（平台无关）

    处理流程：
    1. 记录 Chat 信息
    2. Bot 查找与自动发现
    3. 访问控制检查
    4. 命令处理（Bot 命令 → 项目命令 → 隧道命令 → Slash 命令）
    5. 会话管理
    6. 消息去重
    7. 并发控制
    8. 转发到 Agent
    9. 记录会话
    10. 发送响应

    Args:
        adapter: 通道适配器（负责收发消息）
        inbound: 统一入站消息

    Returns:
        处理结果 {"errcode": int, "errmsg": str}
    """
    h = _get_helpers()
    start_time = datetime.now()
    log_id = None

    try:
        bot_key = inbound.bot_key
        chat_id = inbound.chat_id
        chat_type_raw = "single" if inbound.chat_type == "direct" else "group"

        logger.info(
            f"[{adapter.platform}] 收到消息: chat_id={chat_id}, "
            f"chat_type={inbound.chat_type}, from={inbound.user_name}"
        )

        # === 1. 记录 Chat 信息 ===
        try:
            db_manager = get_db_manager()
            async with db_manager.get_session() as session:
                chat_info_repo = get_chat_info_repository(session)
                await chat_info_repo.record_chat(
                    chat_id=chat_id,
                    chat_type=chat_type_raw,
                    chat_name=None,
                    bot_key=bot_key,
                )
                await session.commit()
        except Exception as e:
            logger.warning(f"记录 chat_type 失败: {e}")

        # === 2. Bot 查找与自动发现 ===
        bot = config.get_bot(bot_key) if bot_key else None

        if not bot and bot_key:
            logger.info(f"未知的 bot_key={bot_key[:10]}...，尝试自动创建骨架 Bot")
            try:
                from .repository import get_chatbot_repository
                db_mgr = get_db_manager()
                async with db_mgr.get_session() as auto_session:
                    bot_repo = get_chatbot_repository(auto_session)
                    existing = await bot_repo.get_by_bot_key(bot_key)
                    if not existing:
                        await bot_repo.create(
                            bot_key=bot_key,
                            name=f"未配置 Bot ({bot_key[:8]}...)",
                            url_template="",
                            enabled=False,
                            platform=adapter.platform,
                        )
                        await auto_session.commit()
                        logger.info(f"自动创建骨架 Bot: {bot_key[:10]}...")
                    await config.reload_config()
                    bot = config.get_bot(bot_key)
            except Exception as e:
                logger.error(f"自动创建 Bot 失败: {e}")

        if not bot:
            if config.default_bot_key:
                bot = config.get_bot(config.default_bot_key)
            if not bot:
                logger.warning(f"未找到 bot_key={bot_key} 的配置，且无默认 Bot")
                await _send(adapter, inbound, "⚠️ Bot 配置错误，请联系管理员", bot_key or "")
                return {"errcode": 0, "errmsg": "no bot config"}

        logger.info(
            f"使用 Bot: {bot.name} (key={bot.bot_key[:10]}..., registered={bot.is_registered})"
        )

        # === 3. 访问控制检查 ===
        if not bot.is_registered:
            allowed, reason = True, ""
        else:
            allowed, reason = config.check_access(
                bot, inbound.user_id, chat_id, inbound.user_alias
            )
        if not allowed:
            logger.warning(
                f"用户 {inbound.user_name} ({inbound.user_id}) 被拒绝访问 Bot {bot.name}: {reason}"
            )
            if bot.bot_key != config.default_bot_key:
                default_bot = config.get_bot(config.default_bot_key)
                if default_bot:
                    default_allowed, default_reason = config.check_access(
                        default_bot, inbound.user_id, chat_id, inbound.user_alias
                    )
                    if default_allowed:
                        bot = default_bot
                    else:
                        await _send(
                            adapter, inbound,
                            f"⚠️ {reason}\n\n默认 Bot 也无法访问: {default_reason}",
                            default_bot.bot_key,
                        )
                        return {"errcode": 0, "errmsg": "access denied"}
                else:
                    await _send(adapter, inbound, f"⚠️ {reason}", bot.bot_key)
                    return {"errcode": 0, "errmsg": "access denied"}
            else:
                await _send(adapter, inbound, f"⚠️ {reason}", bot.bot_key)
                return {"errcode": 0, "errmsg": "access denied"}

        # 提取内容
        content = inbound.text
        image_urls = inbound.images
        quoted_short_id = inbound.quoted_short_id

        if quoted_short_id:
            logger.info(f"检测到引用回复，quoted_short_id={quoted_short_id}")

        if not content and not image_urls:
            logger.warning("消息内容为空，跳过处理")
            return {"errcode": 0, "errmsg": "empty content"}

        # === 4. 命令处理 ===

        # Bot 注册/管理命令
        if content and h["is_bot_command"](content):
            success, response_msg = await h["handle_bot_command"](
                bot.bot_key, content, inbound.user_id
            )
            await _send(adapter, inbound, response_msg, bot.bot_key)
            return {"errcode": 0, "errmsg": "bot command handled"}

        # 未配置 Bot：引导注册
        if not bot.is_configured and not bot.is_registered:
            await _send(adapter, inbound, h["get_register_help"](), bot.bot_key)
            return {"errcode": 0, "errmsg": "bot not configured, register help shown"}

        # 项目命令
        if content and h["is_project_command"](content):
            success, response_msg = await h["handle_project_command"](
                bot.bot_key, chat_id, content, inbound.user_id
            )
            await _send(adapter, inbound, response_msg, bot.bot_key)
            return {"errcode": 0, "errmsg": "project command handled"}

        # 隧道命令
        if content and h["is_tunnel_command"](content):
            success, response_msg = await h["handle_tunnel_command"](content)
            await _send(adapter, inbound, response_msg, bot.bot_key)
            return {"errcode": 0, "errmsg": "tunnel command handled"}

        # === 5. 会话管理 ===
        effective_user = get_effective_user(
            inbound.user_id, chat_id, chat_type_raw
        )
        session_mgr = get_session_manager()

        # Slash 命令处理
        if content:
            slash_cmd = session_mgr.parse_slash_command(content)

            if slash_cmd:
                result = await _handle_slash_command(
                    adapter, inbound, bot, session_mgr, effective_user,
                    slash_cmd, start_time,
                )
                if result is not None:
                    return result

        # 获取现有 session_id
        current_session_id = None
        active_session = None
        is_quote_pinned = False

        if quoted_short_id:
            quoted_session = await session_mgr.get_session_by_short_id(
                effective_user, chat_id, quoted_short_id, bot_key=bot.bot_key
            )
            if quoted_session:
                active_session = quoted_session
                current_session_id = quoted_session.session_id
                is_quote_pinned = True
                logger.info(
                    f"引用回复临时使用会话: {quoted_session.short_id} (不切换活跃会话)"
                )
            else:
                logger.warning(
                    f"引用 short_id={quoted_short_id} 未匹配到会话，使用当前活跃会话"
                )

        if not active_session:
            active_session = await session_mgr.get_active_session(
                effective_user, chat_id, bot.bot_key
            )
            if active_session:
                current_session_id = active_session.session_id
                logger.info(f"找到活跃会话: {active_session.short_id}")

        # === 6. 消息去重 ===
        dedup_key = _make_dedup_key(
            bot.bot_key, chat_id, content or "", inbound.message_id
        )
        if _is_duplicate_message(dedup_key):
            logger.info(f"忽略重复消息: dedup_key={dedup_key[:64]}...")
            return {"errcode": 0, "errmsg": "ok"}
        _mark_message_processed(dedup_key)

        # 获取目标 URL
        target_url = bot.forward_config.get_url()

        # 检查转发目标
        if not target_url:
            from .repository import get_user_project_repository
            db_manager = get_db_manager()
            async with db_manager.get_session() as session:
                project_repo = get_user_project_repository(session)
                user_projects = await project_repo.get_user_projects(
                    bot.bot_key, chat_id
                )
                if not user_projects:
                    if not bot.is_registered:
                        help_msg = h["get_register_help"]()
                    else:
                        from .routes.project_commands import get_user_help
                        help_msg = get_user_help()
                    await _send(adapter, inbound, help_msg, bot.bot_key)
                    return {"errcode": 0, "errmsg": "no target configured, help shown"}

        # === 7. 并发控制 ===
        processing_key = compute_processing_key(
            current_session_id, inbound.user_id, chat_id, bot.bot_key, chat_type_raw
        )
        PROCESSING_TIMEOUT_SECONDS = 300
        processing_acquired = False
        db_manager = get_db_manager()

        try:
            async with db_manager.get_session() as lock_session:
                processing_repo = get_processing_session_repository(lock_session)
                processing_acquired = await processing_repo.try_acquire(
                    session_key=processing_key,
                    user_id=inbound.user_id,
                    chat_id=chat_id,
                    bot_key=bot.bot_key,
                    message=content or "(image)",
                )
                if processing_acquired:
                    await lock_session.commit()
                else:
                    lock_info = await processing_repo.get_lock_info(processing_key)
                    if lock_info:
                        elapsed = _compute_elapsed_seconds(lock_info.started_at)
                        if elapsed > PROCESSING_TIMEOUT_SECONDS:
                            await processing_repo.force_release(processing_key)
                            await lock_session.commit()
                            async with db_manager.get_session() as retry_session:
                                retry_repo = get_processing_session_repository(retry_session)
                                processing_acquired = await retry_repo.try_acquire(
                                    session_key=processing_key,
                                    user_id=inbound.user_id,
                                    chat_id=chat_id,
                                    bot_key=bot.bot_key,
                                    message=content or "(image)",
                                )
                                if processing_acquired:
                                    await retry_session.commit()
                        if not processing_acquired:
                            elapsed_str = (
                                f"{int(elapsed // 60)}分{int(elapsed % 60)}秒"
                                if elapsed >= 60
                                else f"{int(elapsed)}秒"
                            )
                            await _send(
                                adapter, inbound,
                                f"⏳ 前一条消息正在处理中（已等待 {elapsed_str}），请稍候...\n💡 等处理完毕后再发送新消息",
                                bot.bot_key,
                            )
                            return {"errcode": 0, "errmsg": "session busy"}
                    else:
                        processing_acquired = True
        except Exception as lock_err:
            logger.error(f"并发锁处理异常: {lock_err}", exc_info=True)
            await _send(
                adapter, inbound,
                "⏳ 前一条消息可能还在处理中，请稍候再试...",
                bot.bot_key,
            )
            return {"errcode": 0, "errmsg": "lock error"}

        # 创建日志记录
        log_data = h["RequestLogData"](
            chat_id=chat_id,
            from_user_id=inbound.user_id,
            from_user_name=inbound.user_name,
            content=content or "(image)",
            target_url=target_url,
            msg_type=inbound.msg_type,
            bot_key=bot.bot_key,
            bot_name=bot.name,
            session_id=current_session_id,
            status="pending",
        )
        log_id = await h["add_request_log"](log_data)

        request_id = str(uuid.uuid4())[:8]
        h["add_pending_request"](
            request_id=request_id,
            bot_name=bot.name,
            user=inbound.user_name or inbound.user_id,
            message=content or "(image)",
        )

        try:
            # === 8. 转发到 Agent ===
            current_project_id = (
                active_session.current_project_id if active_session else None
            )
            forward_to_agent = _import_services()
            result = await forward_to_agent(
                bot_key=bot.bot_key,
                chat_id=chat_id,
                content=content or "",
                timeout=config.timeout,
                session_id=current_session_id,
                current_project_id=current_project_id,
                image_urls=image_urls if image_urls else None,
            )
        except ValueError as e:
            error_msg = str(e)
            h["remove_pending_request"](request_id)

            if "无可用项目" in error_msg or "未配置转发 URL" in error_msg:
                from .repository import get_user_project_repository
                db_manager = get_db_manager()
                async with db_manager.get_session() as session:
                    project_repo = get_user_project_repository(session)
                    user_projects = await project_repo.get_user_projects(
                        bot.bot_key, chat_id
                    )
                    if user_projects:
                        project_list = ", ".join(
                            [f"`{p.project_id}`" for p in user_projects[:3]]
                        )
                        more_hint = (
                            f" 等 {len(user_projects)} 个项目"
                            if len(user_projects) > 3
                            else ""
                        )
                        help_msg = (
                            f"💡 **检测到你有以下项目**\n\n"
                            f"项目: {project_list}{more_hint}\n\n"
                            f"请使用 `/use <项目ID>` 切换到要使用的项目\n\n"
                            f"示例: `/use {user_projects[0].project_id}`"
                        )
                    else:
                        from .routes.project_commands import get_user_help
                        help_msg = get_user_help()
                    await _send(adapter, inbound, help_msg, bot.bot_key)
                    duration_ms = int(
                        (datetime.now() - start_time).total_seconds() * 1000
                    )
                    if log_id:
                        await h["update_request_log"](
                            log_id=log_id,
                            status="error",
                            error=f"配置错误: {error_msg}",
                            duration_ms=duration_ms,
                        )
                    return {"errcode": 0, "errmsg": "no project configured"}
            raise
        finally:
            h["remove_pending_request"](request_id)
            if processing_acquired:
                try:
                    async with db_manager.get_session() as release_session:
                        release_repo = get_processing_session_repository(release_session)
                        await release_repo.release(processing_key)
                        await release_session.commit()
                except Exception as release_err:
                    logger.error(f"释放处理锁失败: {release_err}")

        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        if not result:
            if log_id:
                await h["update_request_log"](
                    log_id=log_id,
                    status="error",
                    error="转发失败或无配置",
                    duration_ms=duration_ms,
                )
            await _send(
                adapter, inbound,
                "⚠️ 处理请求时发生错误，请稍后重试",
                bot.bot_key,
            )
            return {"errcode": 0, "errmsg": "forward failed"}

        # === 9. 记录会话 ===
        if result.session_id:
            should_set_active = not is_quote_pinned
            await session_mgr.record_session(
                user_id=effective_user,
                chat_id=chat_id,
                bot_key=bot.bot_key,
                session_id=result.session_id,
                last_message=content or "(image)",
                current_project_id=current_project_id,
                set_active=should_set_active,
            )
            logger.info(
                f"会话已记录: session={result.session_id[:8]}, "
                f"project={current_project_id or 'None'}, pinned={is_quote_pinned}..."
            )

        # === 10. 发送响应 ===
        send_result = await _send(
            adapter, inbound,
            result.reply,
            bot.bot_key,
            short_id=result.session_id[:8] if result.session_id else None,
            project_name=result.project_name or result.project_id if result.project_id else None,
            msg_type=result.msg_type,
        )

        if log_id:
            await h["update_request_log"](
                log_id=log_id,
                status="success" if send_result.success else "error",
                response=result.reply,
                session_id=result.session_id,
                error=send_result.error if not send_result.success else None,
                duration_ms=duration_ms,
            )

        if send_result.success:
            logger.info(f"回复已发送: chat_id={chat_id}")
        else:
            logger.error(f"发送回复失败: {send_result.error}")

        return {"errcode": 0, "errmsg": "ok"}

    except Exception as e:
        logger.error(f"处理消息失败: {e}", exc_info=True)
        if log_id:
            await h["update_request_log"](
                log_id=log_id,
                status="error",
                error=str(e),
                duration_ms=int(
                    (datetime.now() - start_time).total_seconds() * 1000
                ),
            )
        return {"errcode": -1, "errmsg": str(e)}


# ============== Slash 命令处理 ==============


async def _handle_slash_command(
    adapter: ChannelAdapter,
    inbound: InboundMessage,
    bot,
    session_mgr,
    effective_user: str,
    slash_cmd: tuple,
    start_time: datetime,
) -> Optional[dict]:
    """
    处理 Slash 命令

    Returns:
        处理结果字典（如果命令被处理），或 None（如果不是终止命令，需要继续处理）
    """
    h = _get_helpers()
    cmd_type, cmd_arg, extra_msg = slash_cmd
    chat_id = inbound.chat_id

    logger.info(
        f"处理 Slash 命令: {cmd_type}, arg={cmd_arg}, "
        f"extra={extra_msg[:20] if extra_msg else None}"
    )

    if cmd_type == "list":
        sessions = await session_mgr.list_sessions(
            effective_user, chat_id, bot_key=bot.bot_key
        )
        reply_msg = session_mgr.format_session_list(sessions)
        await _send(adapter, inbound, reply_msg, bot.bot_key)
        return {"errcode": 0, "errmsg": "slash command handled"}

    elif cmd_type == "reset":
        success = await session_mgr.reset_session(
            effective_user, chat_id, bot.bot_key
        )
        msg = (
            "✅ 会话已重置，下次发送消息将开始新对话"
            if success
            else "✅ 已准备好开始新对话，请发送消息"
        )
        await _send(adapter, inbound, msg, bot.bot_key)
        return {"errcode": 0, "errmsg": "slash command handled"}

    elif cmd_type in ("change_help", "change_invalid"):
        if cmd_type == "change_invalid":
            help_msg = (
                f"❌ `{cmd_arg}` 不是有效的会话 ID\n\n"
                f"使用 `/s` 查看可用会话\n示例: `/c abc12345`"
            )
        else:
            help_msg = (
                "💡 `/c <会话ID>` - 切换到指定会话\n\n"
                "使用 `/s` 查看可用会话列表\n示例: `/c abc12345`"
            )
        await _send(adapter, inbound, help_msg, bot.bot_key)
        return {"errcode": 0, "errmsg": "slash command handled"}

    elif cmd_type == "change":
        target_session = await session_mgr.change_session(
            effective_user, chat_id, cmd_arg, bot_key=bot.bot_key
        )
        if not target_session:
            await _send(
                adapter, inbound,
                f"❌ 未找到会话 `{cmd_arg}`\n使用 `/s` 查看可用会话",
                bot.bot_key,
            )
            return {"errcode": 0, "errmsg": "slash command handled"}

        if extra_msg:
            logger.info(
                f"会话已切换到 {target_session.short_id}，继续转发消息: {extra_msg[:30]}..."
            )
            inbound.text = extra_msg
            return None  # 继续处理管线
        else:
            await _send(
                adapter, inbound,
                f"✅ 已切换到会话 `{target_session.short_id}`\n"
                f"最后消息: {target_session.last_message or '(无)'}",
                bot.bot_key,
            )
            return {"errcode": 0, "errmsg": "slash command handled"}

    elif cmd_type in ("ping", "status"):
        is_admin = await h["check_is_admin"](inbound.user_id, inbound.user_alias)
        if not is_admin:
            await _send(adapter, inbound, "⚠️ 此命令仅限管理员使用", bot.bot_key)
            return {"errcode": 0, "errmsg": "permission denied"}

        if cmd_type == "ping":
            duration_ms = int(
                (datetime.now() - start_time).total_seconds() * 1000
            )
            await _send(
                adapter, inbound,
                f"🟢 pong! (延迟: {duration_ms}ms)",
                bot.bot_key,
            )
        else:
            status_msg = await h["get_system_status"]()
            await _send(adapter, inbound, status_msg, bot.bot_key)
        return {"errcode": 0, "errmsg": "slash command handled"}

    elif cmd_type == "help":
        is_admin = await h["check_is_admin"](inbound.user_id, inbound.user_alias)
        response_msg = h["get_admin_full_help"]() if is_admin else h["get_regular_user_help"]()
        await _send(adapter, inbound, response_msg, bot.bot_key)
        return {"errcode": 0, "errmsg": "slash command handled"}

    elif cmd_type == "id":
        await _send(adapter, inbound, f"🆔 Chat ID: `{inbound.chat_id}`", bot.bot_key)
        return {"errcode": 0, "errmsg": "slash command handled"}

    elif cmd_type in ("bots", "bot", "pending", "recent", "errors", "health"):
        is_admin = await h["check_is_admin"](inbound.user_id, inbound.user_alias)
        if not is_admin:
            await _send(adapter, inbound, "⚠️ 此命令仅限管理员使用", bot.bot_key)
            return {"errcode": 0, "errmsg": "permission denied"}

        if cmd_type == "bots":
            response_msg = await h["get_bots_list"]()
        elif cmd_type == "bot":
            if extra_msg and ":" in extra_msg:
                parts = extra_msg.split(":", 1)
                response_msg = await h["update_bot_config"](cmd_arg or "", parts[0], parts[1])
            else:
                response_msg = await h["get_bot_detail"](cmd_arg or "")
        elif cmd_type == "pending":
            response_msg = await h["get_pending_list"]()
        elif cmd_type == "recent":
            response_msg = await h["get_recent_logs"]()
        elif cmd_type == "errors":
            response_msg = await h["get_error_logs"]()
        elif cmd_type == "health":
            response_msg = await h["check_agents_health"]()
        else:
            response_msg = f"❓ 未知命令: {cmd_type}"

        await _send(adapter, inbound, response_msg, bot.bot_key)
        return {"errcode": 0, "errmsg": "slash command handled"}

    return None  # 未处理的命令类型
