"""
回调处理路由

处理企微机器人回调。
支持消息去重：企微在未及时收到 200 时会重试，同一消息可能被推送多次，通过去重避免重复转发和重复回复。
"""
import hashlib
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Header

from ..config import config
from ..sender import send_reply
from ..session_manager import get_session_manager, get_effective_user, compute_processing_key
from ..utils import extract_content
from ..services import forward_to_agent_with_user_project
from ..database import get_db_manager
from ..repository import get_chat_info_repository, get_processing_session_repository
from .admin import add_request_log, update_request_log, RequestLogData
from .admin_commands import (
    check_is_admin,
    get_system_status,
    get_admin_help,
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
from .project_commands import (
    is_project_command,
    handle_project_command
)
from .tunnel_commands import (
    is_tunnel_command,
    handle_tunnel_command
)
from .bot_commands import (
    is_bot_command,
    handle_bot_command,
    get_register_help,
)

logger = logging.getLogger(__name__)


# ============== 消息去重（防企微重试导致重复转发/重复回复）==============

# 已处理消息 key -> 过期时间戳；定期清理过期项
_dedup_cache: dict[str, float] = {}
_DEDUP_TTL_SECONDS = 120
_DEDUP_CLEANUP_THRESHOLD = 500


def _make_dedup_key(bot_key: str, chat_id: str, content: str, data: dict) -> str:
    """生成去重 key：优先使用企微/飞鸽的 msgid（若有），否则用 bot+chat+内容 的哈希。"""
    msg_id = data.get("msgid") or data.get("msg_id") or data.get("message_id")
    if msg_id is not None:
        return f"id:{bot_key}:{chat_id}:{msg_id}"
    raw = f"{bot_key}|{chat_id}|{(content or '').strip()}"
    return f"hash:{hashlib.sha256(raw.encode()).hexdigest()}"


def _is_duplicate_message(dedup_key: str) -> bool:
    """判断是否为重复消息（在 TTL 内已处理过）。"""
    now = time.time()
    if dedup_key in _dedup_cache:
        if _dedup_cache[dedup_key] > now:
            return True
        del _dedup_cache[dedup_key]
    return False


def _mark_message_processed(dedup_key: str) -> None:
    """标记消息已处理（用于去重）。"""
    now = time.time()
    _dedup_cache[dedup_key] = now + _DEDUP_TTL_SECONDS
    if len(_dedup_cache) >= _DEDUP_CLEANUP_THRESHOLD:
        expired = [k for k, v in _dedup_cache.items() if v <= now]
        for k in expired:
            del _dedup_cache[k]


def _compute_elapsed_seconds(started_at: datetime) -> float:
    """
    计算从 started_at 到现在经过的秒数。
    
    安全处理 timezone-aware 和 timezone-naive 的 datetime：
    - MySQL 的 DATETIME 列不保存时区信息，读回来是 naive datetime
    - 代码中使用 datetime.now(timezone.utc) 是 aware datetime
    - 直接相减会抛 TypeError，这里统一处理
    """
    now_utc = datetime.now(timezone.utc)
    
    if started_at.tzinfo is None:
        # DB 读回的 naive datetime，假定为 UTC
        started_at = started_at.replace(tzinfo=timezone.utc)
    
    return (now_utc - started_at).total_seconds()


# ============== 路由定义 ==============

router = APIRouter(tags=["callback"])


@router.post("/callback")
async def handle_callback(
    request: Request,
    x_api_key: str | None = Header(None, alias="x-api-key")
):
    """
    处理企微机器人回调（多 Bot 支持）
    
    工作流程：
    1. 从 webhook_url 提取 bot_key
    2. 查找对应的 Bot 配置
    3. 检查访问权限
    4. 转发到 Agent
    5. 将结果发送给用户
    """
    # 验证鉴权（可选）
    if config.callback_auth_key and config.callback_auth_value:
        if x_api_key != config.callback_auth_value:
            logger.warning(f"回调鉴权失败: x_api_key={x_api_key}")
            return {"errcode": 401, "errmsg": "Unauthorized"}
    
    start_time = datetime.now()
    log_id = None  # 日志 ID，用于更新响应信息
    
    try:
        data = await request.json()
        
        chat_id = data.get("chatid", "")
        chat_type = data.get("chattype", "group")  # group 或 single
        msg_type = data.get("msgtype", "")
        from_user = data.get("from", {})
        from_user_name = from_user.get("name", "unknown")
        from_user_id = from_user.get("userid", "unknown")
        from_user_alias = from_user.get("alias", "")  # 用户别名
        webhook_url = data.get("webhook_url", "")
        
        logger.info(f"收到企微回调: chat_id={chat_id}, chat_type={chat_type}, msg_type={msg_type}, from={from_user_name}")
        
        # 群聊场景下，回复时 @发送者
        mentioned_list = [from_user_id] if chat_type == "group" else None
        
        # 忽略某些事件类型
        if msg_type in ("event", "enter_chat"):
            logger.info(f"忽略事件类型: {msg_type}")
            return {"errcode": 0, "errmsg": "ok"}
        
        # === 多 Bot 支持：从 webhook_url 提取 bot_key ===
        bot_key = config.extract_bot_key_from_webhook_url(webhook_url)
        logger.info(f"提取的 bot_key: {bot_key}")
        
        # === 记录 Chat 信息（chat_id -> chat_type 映射）===
        try:
            db_manager = get_db_manager()
            async with db_manager.get_session() as session:
                chat_info_repo = get_chat_info_repository(session)
                await chat_info_repo.record_chat(
                    chat_id=chat_id,
                    chat_type=chat_type,
                    chat_name=None,  # 企微回调暂不提供群名
                    bot_key=bot_key
                )
                await session.commit()
        except Exception as e:
            # 记录失败不影响主流程
            logger.warning(f"记录 chat_type 失败: {e}")
        
        # === Bot 查找与自动发现 ===
        bot = config.get_bot(bot_key) if bot_key else None
        
        if not bot and bot_key:
            # bot_key 存在但未注册：自动创建骨架 Bot
            logger.info(f"未知的 bot_key={bot_key[:10]}...，尝试自动创建骨架 Bot")
            try:
                from ..repository import get_chatbot_repository
                db_mgr = get_db_manager()
                async with db_mgr.get_session() as auto_session:
                    bot_repo = get_chatbot_repository(auto_session)
                    # 再次检查是否已存在（可能刚刚被并发创建）
                    existing = await bot_repo.get_by_bot_key(bot_key)
                    if not existing:
                        await bot_repo.create(
                            bot_key=bot_key,
                            name=f"未配置 Bot ({bot_key[:8]}...)",
                            url_template="",
                            enabled=False,
                        )
                        await auto_session.commit()
                        logger.info(f"自动创建骨架 Bot: {bot_key[:10]}...")
                    # 刷新内存缓存
                    await config.reload_config()
                    bot = config.get_bot(bot_key)
            except Exception as e:
                logger.error(f"自动创建 Bot 失败: {e}")
        
        if not bot:
            # 无 bot_key 或创建失败：回退到默认 Bot
            if config.default_bot_key:
                bot = config.get_bot(config.default_bot_key)
            if not bot:
                logger.warning(f"未找到 bot_key={bot_key} 的配置，且无默认 Bot")
                await send_reply(
                    chat_id=chat_id,
                    message="⚠️ Bot 配置错误，请联系管理员",
                    msg_type="text",
                    mentioned_list=mentioned_list,
                )
                return {"errcode": 0, "errmsg": "no bot config"}
        
        logger.info(f"使用 Bot: {bot.name} (key={bot.bot_key[:10]}..., registered={bot.is_registered})")
        
        # === 访问控制检查 ===
        # 未注册的 Bot（无 owner）跳过访问控制，允许任何人发送 /register
        if not bot.is_registered:
            logger.info(f"Bot 未注册，跳过访问控制检查")
            allowed, reason = True, ""
        else:
            allowed, reason = config.check_access(bot, from_user_id, chat_id, from_user_alias)
        if not allowed:
            logger.warning(f"用户 {from_user_name} ({from_user_id}) 被拒绝访问 Bot {bot.name}: {reason}")
            
            # 尝试回退到默认 Bot
            if bot.bot_key != config.default_bot_key:
                logger.info(f"尝试回退到默认 Bot: {config.default_bot_key}")
                default_bot = config.get_bot(config.default_bot_key)
                if default_bot:
                    default_allowed, default_reason = config.check_access(default_bot, from_user_id, chat_id, from_user_alias)
                    if default_allowed:
                        bot = default_bot
                        logger.info(f"使用默认 Bot: {bot.name}")
                    else:
                        await send_reply(
                            chat_id=chat_id,
                            message=f"⚠️ {reason}\n\n默认 Bot 也无法访问: {default_reason}",
                            msg_type="text",
                            bot_key=default_bot.bot_key,
                            mentioned_list=mentioned_list,
                        )
                        return {"errcode": 0, "errmsg": "access denied"}
                else:
                    await send_reply(
                        chat_id=chat_id,
                        message=f"⚠️ {reason}",
                        msg_type="text",
                        bot_key=bot.bot_key,
                        mentioned_list=mentioned_list,
                    )
                    return {"errcode": 0, "errmsg": "access denied"}
            else:
                await send_reply(
                    chat_id=chat_id,
                    message=f"⚠️ {reason}",
                    msg_type="text",
                    bot_key=bot.bot_key,
                    mentioned_list=mentioned_list,
                )
                return {"errcode": 0, "errmsg": "access denied"}
        
        # 提取消息内容（自动剥离引用消息，只保留用户实际回复）
        extracted = extract_content(data)
        content = extracted.text
        image_urls = extracted.image_urls
        quoted_short_id = extracted.quoted_short_id
        quoted_message_id = extracted.quoted_message_id
        
        if quoted_short_id:
            logger.info(f"检测到引用回复，quoted_short_id={quoted_short_id}")
        if quoted_message_id:
            logger.info(f"检测到引用消息 ID: quoted_message_id={quoted_message_id}")
        
        # === Outbound dispatch 路由: ob_ 前缀 short_id → 设置 session_id 并走正常转发 ===
        ob_dispatch_session_id = None
        if quoted_short_id and quoted_short_id.startswith("ob_"):
            try:
                from ..repository import get_outbound_context_repository
                db_mgr = get_db_manager()
                async with db_mgr.get_session() as ob_session:
                    ob_repo = get_outbound_context_repository(ob_session)
                    ob_ctx = await ob_repo.find_context_by_message_id(quoted_short_id)
                    if ob_ctx and ob_ctx.session_id:
                        ob_dispatch_session_id = ob_ctx.session_id
                        logger.info(
                            f"ob_ 路由匹配: short_id={quoted_short_id}, "
                            f"session_id={ob_ctx.session_id[:8]}... "
                            f"→ 使用此 session_id 走正常转发流程"
                        )
                        await ob_repo.mark_context_replied(ob_ctx.id)
                        await ob_session.commit()
                    elif ob_ctx:
                        logger.warning(f"ob_ 路由匹配但上下文无 session_id: short_id={quoted_short_id}")
                    else:
                        logger.info(f"ob_ short_id={quoted_short_id} 未匹配到有效上下文，回退到默认路由")
            except Exception as e:
                logger.warning(f"ob_ 路由处理失败（回退到默认路由）: {e}")
        
        # === 出站消息上下文路由：引用回复 → 查找原始任务上下文 ===
        outbound_ctx = None
        if quoted_message_id:
            try:
                from ..repository import get_outbound_context_repository
                db_mgr = get_db_manager()
                async with db_mgr.get_session() as ctx_session:
                    ctx_repo = get_outbound_context_repository(ctx_session)
                    outbound_ctx = await ctx_repo.find_context_by_message_id(quoted_message_id)
                    if outbound_ctx:
                        logger.info(
                            f"匹配到出站消息上下文: task_id={outbound_ctx.task_id}, "
                            f"agent_id={outbound_ctx.agent_id}, session_id={outbound_ctx.session_id}"
                        )
                        await ctx_repo.mark_context_replied(outbound_ctx.id)
                        await ctx_session.commit()
            except Exception as e:
                logger.warning(f"查找出站消息上下文失败（不影响主流程）: {e}")
        
        if not content and not image_urls:
            logger.warning("消息内容为空，跳过处理")
            return {"errcode": 0, "errmsg": "empty content"}
        
        # === Bot 注册/管理命令处理（优先于其他命令）===
        if content and is_bot_command(content):
            success, response_msg = await handle_bot_command(
                bot.bot_key, content, from_user_id
            )
            await send_reply(
                chat_id=chat_id,
                message=response_msg,
                msg_type="text",
                bot_key=bot.bot_key,
                mentioned_list=mentioned_list,
            )
            return {"errcode": 0, "errmsg": "bot command handled"}
        
        # === 未配置 Bot 检查：无 target_url 且无用户项目时，引导注册 ===
        if not bot.is_configured and not bot.is_registered:
            await send_reply(
                chat_id=chat_id,
                message=get_register_help(),
                msg_type="text",
                bot_key=bot.bot_key,
                mentioned_list=mentioned_list,
            )
            return {"errcode": 0, "errmsg": "bot not configured, register help shown"}
        
        # === 项目命令处理 ===
        if content and is_project_command(content):
            success, response_msg = await handle_project_command(bot.bot_key, chat_id, content, from_user_id)
            await send_reply(
                chat_id=chat_id,
                message=response_msg,
                msg_type="text",
                bot_key=bot.bot_key,
                mentioned_list=mentioned_list,
            )
            return {"errcode": 0, "errmsg": "project command handled"}
        
        # === 隧道命令处理 ===
        if content and is_tunnel_command(content):
            success, response_msg = await handle_tunnel_command(content)
            await send_reply(
                chat_id=chat_id,
                message=response_msg,
                msg_type="text",
                bot_key=bot.bot_key,
                mentioned_list=mentioned_list,
            )
            return {"errcode": 0, "errmsg": "tunnel command handled"}
        
        # === 计算 effective_user：群聊共享会话，私聊独立 ===
        effective_user = get_effective_user(from_user_id, chat_id, chat_type)
        
        # === 会话管理：处理 Slash 命令 ===
        session_mgr = get_session_manager()  # 提前获取，供项目命令和 slash 命令使用
        
        if content:
            slash_cmd = session_mgr.parse_slash_command(content)
            
            if slash_cmd:
                cmd_type, cmd_arg, extra_msg = slash_cmd
                logger.info(f"处理 Slash 命令: {cmd_type}, arg={cmd_arg}, extra={extra_msg[:20] if extra_msg else None}")
                
                if cmd_type == "list":
                    # /sess - 列出会话（只列出当前 Bot 的会话）
                    sessions = await session_mgr.list_sessions(effective_user, chat_id, bot_key=bot.bot_key)
                    reply_msg = session_mgr.format_session_list(sessions)
                    await send_reply(
                        chat_id=chat_id,
                        message=reply_msg,
                        msg_type="text",
                        bot_key=bot.bot_key,
                        mentioned_list=mentioned_list,
                    )
                    return {"errcode": 0, "errmsg": "slash command handled"}
                
                elif cmd_type == "reset":
                    # /reset 或 /r - 新建会话（重置当前会话）
                    success = await session_mgr.reset_session(effective_user, chat_id, bot.bot_key)
                    if success:
                        await send_reply(
                            chat_id=chat_id,
                            message="✅ 会话已重置，下次发送消息将开始新对话",
                            msg_type="text",
                            bot_key=bot.bot_key,
                            mentioned_list=mentioned_list,
                        )
                    else:
                        # 没有活跃会话也算成功 - 下次发消息会自动创建新会话
                        await send_reply(
                            chat_id=chat_id,
                            message="✅ 已准备好开始新对话，请发送消息",
                            msg_type="text",
                            bot_key=bot.bot_key,
                            mentioned_list=mentioned_list,
                        )
                    return {"errcode": 0, "errmsg": "slash command handled"}
                
                elif cmd_type in ("change_help", "change_invalid"):
                    # /c 不带参数或参数无效 - 显示帮助
                    if cmd_type == "change_invalid":
                        help_msg = f"❌ `{cmd_arg}` 不是有效的会话 ID\n\n使用 `/s` 查看可用会话\n示例: `/c abc12345`"
                    else:
                        help_msg = "💡 `/c <会话ID>` - 切换到指定会话\n\n使用 `/s` 查看可用会话列表\n示例: `/c abc12345`"
                    await send_reply(
                        chat_id=chat_id,
                        message=help_msg,
                        msg_type="text",
                        bot_key=bot.bot_key,
                        mentioned_list=mentioned_list,
                    )
                    return {"errcode": 0, "errmsg": "slash command handled"}
                
                elif cmd_type == "change":
                    # /change <short_id> [message] - 切换会话，可选附带消息
                    target_session = await session_mgr.change_session(effective_user, chat_id, cmd_arg, bot_key=bot.bot_key)
                    if not target_session:
                        await send_reply(
                            chat_id=chat_id,
                            message=f"❌ 未找到会话 `{cmd_arg}`\n使用 `/s` 查看可用会话",
                            msg_type="text",
                            bot_key=bot.bot_key,
                            mentioned_list=mentioned_list,
                        )
                        return {"errcode": 0, "errmsg": "slash command handled"}
                    
                    # 如果有附带消息，继续转发给 Agent
                    if extra_msg:
                        logger.info(f"会话已切换到 {target_session.short_id}，继续转发消息: {extra_msg[:30]}...")
                        content = extra_msg
                    else:
                        await send_reply(
                            chat_id=chat_id,
                            message=f"✅ 已切换到会话 `{target_session.short_id}`\n最后消息: {target_session.last_message or '(无)'}",
                            msg_type="text",
                            bot_key=bot.bot_key,
                            mentioned_list=mentioned_list,
                        )
                        return {"errcode": 0, "errmsg": "slash command handled"}
                
                elif cmd_type in ("ping", "status"):
                    # /ping 或 /status - 系统状态（需要管理员权限）
                    is_admin = await check_is_admin(from_user_id, from_user_alias)
                    if not is_admin:
                        await send_reply(
                            chat_id=chat_id,
                            message="⚠️ 此命令仅限管理员使用",
                            msg_type="text",
                            bot_key=bot.bot_key,
                            mentioned_list=mentioned_list,
                        )
                        return {"errcode": 0, "errmsg": "permission denied"}
                    
                    if cmd_type == "ping":
                        # 简单的 ping 响应
                        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                        await send_reply(
                            chat_id=chat_id,
                            message=f"🟢 pong! (延迟: {duration_ms}ms)",
                            msg_type="text",
                            bot_key=bot.bot_key,
                            mentioned_list=mentioned_list,
                        )
                    else:
                        # 详细状态信息
                        status_msg = await get_system_status()
                        await send_reply(
                            chat_id=chat_id,
                            message=status_msg,
                            msg_type="text",
                            bot_key=bot.bot_key,
                            mentioned_list=mentioned_list,
                        )
                    return {"errcode": 0, "errmsg": "slash command handled"}
                
                elif cmd_type == "help":
                    # /help 命令对所有用户可用，但显示不同内容
                    is_admin = await check_is_admin(from_user_id, from_user_alias)
                    if is_admin:
                        response_msg = get_admin_full_help()
                    else:
                        response_msg = get_regular_user_help()
                    
                    await send_reply(
                        chat_id=chat_id,
                        message=response_msg,
                        msg_type="text",
                        bot_key=bot.bot_key,
                        mentioned_list=mentioned_list,
                    )
                    return {"errcode": 0, "errmsg": "slash command handled"}
                
                elif cmd_type in ("bots", "bot", "pending", "recent", "errors", "health"):
                    # 其他管理员命令
                    is_admin = await check_is_admin(from_user_id, from_user_alias)
                    if not is_admin:
                        await send_reply(
                            chat_id=chat_id,
                            message="⚠️ 此命令仅限管理员使用",
                            msg_type="text",
                            bot_key=bot.bot_key,
                            mentioned_list=mentioned_list,
                        )
                        return {"errcode": 0, "errmsg": "permission denied"}
                    
                    # 根据命令类型获取响应
                    if cmd_type == "bots":
                        response_msg = await get_bots_list()
                    elif cmd_type == "bot":
                        # extra_msg 格式可能是 "field_type:value"
                        if extra_msg and ":" in extra_msg:
                            parts = extra_msg.split(":", 1)
                            field_type, field_value = parts[0], parts[1]
                            response_msg = await update_bot_config(cmd_arg or "", field_type, field_value)
                        else:
                            response_msg = await get_bot_detail(cmd_arg or "")
                    elif cmd_type == "pending":
                        response_msg = await get_pending_list()
                    elif cmd_type == "recent":
                        response_msg = await get_recent_logs()
                    elif cmd_type == "errors":
                        response_msg = await get_error_logs()
                    elif cmd_type == "health":
                        response_msg = await check_agents_health()
                    else:
                        response_msg = f"❓ 未知命令: {cmd_type}"
                    
                    await send_reply(
                        chat_id=chat_id,
                        message=response_msg,
                        msg_type="text",
                        bot_key=bot.bot_key,
                        mentioned_list=mentioned_list,
                    )
                    return {"errcode": 0, "errmsg": "slash command handled"}
        
        # === 会话管理：获取现有 session_id（使用 effective_user）===
        # 引用回复时「临时使用」目标会话，不切换活跃会话，支持多会话交叉回复
        current_session_id = None
        active_session = None
        is_quote_pinned = False  # 标记是否为引用回复指定的会话
        outbound_task_id = None  # 从出站上下文注入的 task_id
        
        # 优先级 0: ob_ dispatch 路由（从 AgentStudio 转发到企微后的引用回复）
        if ob_dispatch_session_id:
            current_session_id = ob_dispatch_session_id
            is_quote_pinned = True
            logger.info(f"ob_ dispatch 路由: 使用 session_id={ob_dispatch_session_id[:8]}...")
        
        # 优先级 1: 出站消息上下文路由（quoted_message_id → DB 查找 → 注入 session/task/agent）
        if not current_session_id and outbound_ctx and outbound_ctx.session_id:
            current_session_id = outbound_ctx.session_id
            outbound_task_id = outbound_ctx.task_id
            is_quote_pinned = True
            logger.info(
                f"出站上下文路由: session_id={outbound_ctx.session_id[:8]}, "
                f"task_id={outbound_ctx.task_id}"
            )
        
        # 优先级 2: 引用回复中的 short_id（现有逻辑）
        if not current_session_id and quoted_short_id:
            quoted_session = await session_mgr.get_session_by_short_id(
                effective_user, chat_id, quoted_short_id, bot_key=bot.bot_key
            )
            if quoted_session:
                active_session = quoted_session
                current_session_id = quoted_session.session_id
                is_quote_pinned = True
                logger.info(f"引用回复临时使用会话: {quoted_session.short_id} (不切换活跃会话)")
            else:
                logger.warning(f"引用 short_id={quoted_short_id} 未匹配到会话，使用当前活跃会话")
        
        # 优先级 3: 当前活跃会话
        if not active_session and not current_session_id:
            active_session = await session_mgr.get_active_session(effective_user, chat_id, bot.bot_key)
            if active_session:
                current_session_id = active_session.session_id
                logger.info(f"找到活跃会话: {active_session.short_id}")
        
        # === 消息去重：企微重试会导致同一条消息多次回调，避免重复转发和重复回复 ===
        dedup_key = _make_dedup_key(bot.bot_key, chat_id, content or "", data)
        if _is_duplicate_message(dedup_key):
            logger.info(f"忽略重复消息: dedup_key={dedup_key[:64]}...")
            return {"errcode": 0, "errmsg": "ok"}
        _mark_message_processed(dedup_key)
        
        # 获取目标 URL（用于日志）
        target_url = bot.forward_config.get_url()
        
        # 检查是否有可用的转发目标（Bot 配置或用户项目）
        if not target_url:
            # 检查用户是否有绑定的项目
            from ..repository import get_user_project_repository
            db_manager = get_db_manager()
            async with db_manager.get_session() as session:
                project_repo = get_user_project_repository(session)
                user_projects = await project_repo.get_user_projects(bot.bot_key, chat_id)
                if not user_projects:
                    # 没有目标 URL 也没有绑定项目
                    if not bot.is_registered:
                        # Bot 未注册：显示注册引导
                        help_msg = get_register_help()
                    else:
                        # Bot 已注册但用户无项目：显示用户帮助
                        help_msg = get_user_help()
                    await send_reply(
                        chat_id=chat_id,
                        message=help_msg,
                        msg_type="text",
                        bot_key=bot.bot_key,
                        mentioned_list=mentioned_list,
                    )
                    return {"errcode": 0, "errmsg": "no target configured, help shown"}
        
        # === 并发控制：基于 DB 的 ProcessingSession 锁 ===
        processing_key = compute_processing_key(
            current_session_id, from_user_id, chat_id, bot.bot_key, chat_type
        )
        
        PROCESSING_TIMEOUT_SECONDS = 300  # 5 分钟超时
        processing_acquired = False
        
        db_manager = get_db_manager()
        try:
            async with db_manager.get_session() as lock_session:
                processing_repo = get_processing_session_repository(lock_session)
                
                # 尝试获取处理锁
                processing_acquired = await processing_repo.try_acquire(
                    session_key=processing_key,
                    user_id=from_user_id,
                    chat_id=chat_id,
                    bot_key=bot.bot_key,
                    message=content or "(image)"
                )
                
                if processing_acquired:
                    await lock_session.commit()
                else:
                    # 锁定失败：检查是否超时
                    lock_info = await processing_repo.get_lock_info(processing_key)
                    if lock_info:
                        elapsed = _compute_elapsed_seconds(lock_info.started_at)
                        
                        if elapsed > PROCESSING_TIMEOUT_SECONDS:
                            # 超时：强制释放旧锁并重试
                            await processing_repo.force_release(processing_key)
                            await lock_session.commit()
                            
                            # 重新获取锁
                            async with db_manager.get_session() as retry_session:
                                retry_repo = get_processing_session_repository(retry_session)
                                processing_acquired = await retry_repo.try_acquire(
                                    session_key=processing_key,
                                    user_id=from_user_id,
                                    chat_id=chat_id,
                                    bot_key=bot.bot_key,
                                    message=content or "(image)"
                                )
                                if processing_acquired:
                                    await retry_session.commit()
                        
                        if not processing_acquired:
                            # 仍然被锁定：立即回复用户等待
                            elapsed_str = f"{int(elapsed // 60)}分{int(elapsed % 60)}秒" if elapsed >= 60 else f"{int(elapsed)}秒"
                            await send_reply(
                                chat_id=chat_id,
                                message=f"⏳ 前一条消息正在处理中（已等待 {elapsed_str}），请稍候...\n💡 等处理完毕后再发送新消息",
                                msg_type="text",
                                bot_key=bot.bot_key,
                                mentioned_list=mentioned_list,
                            )
                            return {"errcode": 0, "errmsg": "session busy"}
                    else:
                        # 无锁信息但获取失败（理论上不应发生），直接通过
                        processing_acquired = True
        except Exception as lock_err:
            # 并发锁异常不能静默吞掉，必须通知用户
            logger.error(f"并发锁处理异常: {lock_err}", exc_info=True)
            await send_reply(
                chat_id=chat_id,
                message="⏳ 前一条消息可能还在处理中，请稍候再试...",
                msg_type="text",
                bot_key=bot.bot_key,
                mentioned_list=mentioned_list,
            )
            return {"errcode": 0, "errmsg": "lock error"}
        
        # 创建日志记录（持久化到数据库）
        log_data = RequestLogData(
            chat_id=chat_id,
            from_user_id=from_user_id,
            from_user_name=from_user_name,
            content=content or "(image)",
            target_url=target_url,
            msg_type=msg_type,
            bot_key=bot.bot_key,
            bot_name=bot.name,
            session_id=current_session_id,
            status="pending"
        )
        log_id = await add_request_log(log_data)
        
        # 生成请求 ID 用于追踪
        import uuid
        request_id = str(uuid.uuid4())[:8]
        
        # 添加到 pending 请求列表
        add_pending_request(
            request_id=request_id,
            bot_name=bot.name,
            user=from_user_name or from_user_id,
            message=content or "(image)"
        )
        
        try:
            # 转发到 Agent（优先使用用户项目配置，带上 session_id）
            # 获取当前会话指定的项目 ID（如果有）
            current_project_id = active_session.current_project_id if active_session else None
            
            # 出站上下文路由：将 task_id 注入到转发内容，让 Agent 知道上下文
            forward_content = content or ""
            if outbound_task_id:
                forward_content = f"[TASK_REPLY task_id={outbound_task_id}] {forward_content}"
                logger.info(f"注入任务上下文到转发内容: task_id={outbound_task_id}")
            
            result = await forward_to_agent_with_user_project(
                bot_key=bot.bot_key,
                chat_id=chat_id,
                content=forward_content,
                timeout=config.timeout,
                session_id=current_session_id,
                current_project_id=current_project_id,
                image_urls=image_urls if image_urls else None,
            )
        except ValueError as e:
            # 捕获配置错误（forwarder 抛出的 ValueError）
            error_msg = str(e)
            remove_pending_request(request_id)

            if "无可用项目" in error_msg or "未配置转发 URL" in error_msg:
                # 检查用户是否有项目但没有设置默认
                from ..repository import get_user_project_repository
                db_manager = get_db_manager()
                async with db_manager.get_session() as session:
                    project_repo = get_user_project_repository(session)
                    user_projects = await project_repo.get_user_projects(bot.bot_key, chat_id)

                    if user_projects:
                        # 有项目但没有设置默认，引导用户使用 /use
                        project_list = ", ".join([f"`{p.project_id}`" for p in user_projects[:3]])
                        more_hint = f" 等 {len(user_projects)} 个项目" if len(user_projects) > 3 else ""

                        help_msg = (
                            f"💡 **检测到你有以下项目**\n\n"
                            f"项目: {project_list}{more_hint}\n\n"
                            f"请使用 `/use <项目ID>` 切换到要使用的项目\n\n"
                            f"示例: `/use {user_projects[0].project_id}`"
                        )
                    else:
                        # 没有项目，显示帮助信息
                        from .project_commands import get_user_help
                        help_msg = get_user_help()

                    await send_reply(
                        chat_id=chat_id,
                        message=help_msg,
                        msg_type="text",
                        bot_key=bot.bot_key
                    )

                    # 记录日志
                    duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                    if log_id:
                        await update_request_log(
                            log_id=log_id,
                            status="error",
                            error=f"配置错误: {error_msg}",
                            duration_ms=duration_ms
                        )

                    return {"errcode": 0, "errmsg": "no project configured"}

            # 其他 ValueError，重新抛出
            raise
        finally:
            # 无论成功失败，都从 pending 列表移除
            remove_pending_request(request_id)
            
            # 释放 ProcessingSession 锁
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
            # 更新日志：转发失败
            if log_id:
                await update_request_log(
                    log_id=log_id,
                    status="error",
                    error="转发失败或无配置",
                    duration_ms=duration_ms
                )
            
            await send_reply(
                chat_id=chat_id,
                message="⚠️ 处理请求时发生错误，请稍后重试",
                msg_type="text",
                bot_key=bot.bot_key,
                mentioned_list=mentioned_list,
            )
            return {"errcode": 0, "errmsg": "forward failed"}
        
        # === 会话管理：记录 Agent 返回的 session_id（使用 effective_user）===
        if result.session_id:
            # 引用回复时不切换活跃会话，只更新被引用会话的消息记录
            should_set_active = not is_quote_pinned
            await session_mgr.record_session(
                user_id=effective_user,
                chat_id=chat_id,
                bot_key=bot.bot_key,
                session_id=result.session_id,
                last_message=content or "(image)",
                # 保持当前项目设置，避免切换项目后会话项目丢失
                current_project_id=current_project_id,
                set_active=should_set_active
            )
            logger.info(f"会话已记录: session={result.session_id[:8]}, project={current_project_id or 'None'}, pinned={is_quote_pinned}...")
        
        # 发送结果给用户（使用正确的 bot_key）
        # 使用消息分拆功能，传入 short_id 和 project_name
        send_result = await send_reply(
            chat_id=chat_id,
            message=result.reply,
            msg_type=result.msg_type,
            bot_key=bot.bot_key,
            short_id=result.session_id[:8] if result.session_id else None,
            project_name=result.project_name or result.project_id if result.project_id else None,
            mentioned_list=mentioned_list,
        )
        
        # 更新日志：成功或发送失败
        if log_id:
            await update_request_log(
                log_id=log_id,
                status="success" if send_result.get("success") else "error",
                response=result.reply,
                session_id=result.session_id,
                error=send_result.get("error") if not send_result.get("success") else None,
                duration_ms=duration_ms
            )
        
        if send_result.get("success"):
            logger.info(f"回复已发送: chat_id={chat_id}")
        else:
            logger.error(f"发送回复失败: {send_result.get('error')}")
        
        return {"errcode": 0, "errmsg": "ok"}
        
    except Exception as e:
        logger.error(f"处理回调失败: {e}", exc_info=True)
        
        # 尝试更新日志
        if log_id:
            await update_request_log(
                log_id=log_id,
                status="error",
                error=str(e),
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )
        
        return {"errcode": -1, "errmsg": str(e)}
