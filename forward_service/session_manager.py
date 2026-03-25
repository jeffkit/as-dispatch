"""
Forward Service 会话管理器

管理用户与 Agent 的会话：
- 记录 session_id
- 支持会话持续性
- 处理 Slash 命令
- 群聊共享会话（effective_user 机制）
"""
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from .models import UserSession

logger = logging.getLogger(__name__)


def get_effective_user(user_id: str, chat_id: str, chat_type: str) -> str:
    """
    获取会话的有效用户标识

    群聊: 返回 chat_id（所有人共享同一会话）
    私聊: 返回 user_id（个人独立会话）

    Args:
        user_id: 实际发送者 ID
        chat_id: 会话 ID（私聊中 ≈ user_id，群聊中为群 ID）
        chat_type: 会话类型 ("group" 或 "single")

    Returns:
        有效用户标识
    """
    if chat_type == "group":
        return chat_id  # 群内所有人共用
    return user_id  # 私聊按用户隔离


def compute_processing_key(
    session_id: str | None,
    user_id: str,
    chat_id: str,
    bot_key: str,
    chat_type: str
) -> str:
    """
    计算并发锁的 key

    有活跃会话（已有 session_id）：锁定具体的 Agent 会话
    新会话（无 session_id）：按 effective_user:bot_key 锁定

    Args:
        session_id: Agent 会话 ID（可能为 None）
        user_id: 发送者 ID
        chat_id: 会话 ID
        bot_key: Bot Key
        chat_type: 会话类型 ("group" 或 "single")

    Returns:
        processing session key
    """
    if session_id:
        return session_id
    effective_user = get_effective_user(user_id, chat_id, chat_type)
    return f"{effective_user}:{bot_key}"

# Slash 命令正则
SLASH_COMMANDS = {
    # 会话管理（所有用户可用）
    "list": re.compile(r'^/(sess|s)\s*$', re.IGNORECASE),
    "reset": re.compile(r'^/(reset|r)\s*$', re.IGNORECASE),
    # /c <short_id> [message] - 允许会话 ID 后面有空格和消息内容
    "change": re.compile(r'^/(change|c)\s+([a-f0-9]{6,8})(?:\s+(.+))?$', re.IGNORECASE | re.DOTALL),
    # /c 不带参数或参数无效 - 显示帮助
    "change_help": re.compile(r'^/(change|c)\s*$', re.IGNORECASE),
    "change_invalid": re.compile(r'^/(change|c)\s+(\S+)', re.IGNORECASE),
    
    # 系统状态命令（需要管理员权限）
    "ping": re.compile(r'^/(ping|p)\s*$', re.IGNORECASE),
    "status": re.compile(r'^/(status|st)\s*$', re.IGNORECASE),
    "help": re.compile(r'^/(help|h)\s*$', re.IGNORECASE),
    "id": re.compile(r'^/(id)\s*$', re.IGNORECASE),
    
    # Bot 相关（管理员）
    "bots": re.compile(r'^/(bots)\s*$', re.IGNORECASE),
    # /bot <name> [url <url>] [key <key>]
    "bot": re.compile(r'^/(bot)\s+(\S+)(?:\s+(url|key)\s+(\S+))?\s*$', re.IGNORECASE),
    
    # 请求监控（管理员）
    "pending": re.compile(r'^/(pending)\s*$', re.IGNORECASE),
    "recent": re.compile(r'^/(recent)\s*$', re.IGNORECASE),
    "errors": re.compile(r'^/(errors)\s*$', re.IGNORECASE),
    
    # 系统运维（管理员）
    "health": re.compile(r'^/(health)\s*$', re.IGNORECASE),
}


class SessionManager:
    """会话管理器"""
    
    def __init__(self, db_manager):
        self._db_manager = db_manager
    
    async def get_active_session(
        self,
        user_id: str,
        chat_id: str,
        bot_key: str
    ) -> Optional[UserSession]:
        """
        获取用户的活跃会话
        
        Returns:
            活跃的 UserSession，如果没有返回 None
        """
        async with self._db_manager.get_session() as db:
            result = await db.execute(
                select(UserSession)
                .where(and_(
                    UserSession.user_id == user_id,
                    UserSession.chat_id == chat_id,
                    UserSession.bot_key == bot_key,
                    UserSession.is_active == True
                ))
                .order_by(desc(UserSession.updated_at))
                .limit(1)
            )
            return result.scalar_one_or_none()
    
    async def record_session(
        self,
        user_id: str,
        chat_id: str,
        bot_key: str,
        session_id: str,
        last_message: str,
        current_project_id: str | None = None,
        set_active: bool = True
    ) -> UserSession:
        """
        记录或更新会话
        
        如果是新的 session_id，创建新会话并将旧会话设为非活跃（除非 set_active=False）
        如果是相同的 session_id，更新最后消息
        
        Args:
            set_active: 是否将此会话设为活跃（默认 True）。
                        引用回复场景下传 False，避免切换活跃会话。
        """
        short_id = session_id[:8] if len(session_id) >= 8 else session_id
        truncated_message = last_message[:200] if last_message else ""
        
        async with self._db_manager.get_session() as db:
            # 查找是否已存在该 session
            result = await db.execute(
                select(UserSession)
                .where(and_(
                    UserSession.user_id == user_id,
                    UserSession.chat_id == chat_id,
                    UserSession.bot_key == bot_key,
                    UserSession.session_id == session_id
                ))
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                # 更新现有会话
                existing.last_message = truncated_message
                existing.message_count += 1
                if set_active:
                    existing.is_active = True
                existing.updated_at = datetime.now(timezone.utc)
                await db.commit()
                return existing
            else:
                if set_active:
                    # 将该用户的其他会话设为非活跃
                    await db.execute(
                        update(UserSession)
                        .where(and_(
                            UserSession.user_id == user_id,
                            UserSession.chat_id == chat_id,
                            UserSession.bot_key == bot_key,
                            UserSession.is_active == True
                        ))
                        .values(is_active=False)
                    )
                
                # 创建新会话
                new_session = UserSession(
                    user_id=user_id,
                    chat_id=chat_id,
                    bot_key=bot_key,
                    session_id=session_id,
                    short_id=short_id,
                    last_message=truncated_message,
                    message_count=1,
                    is_active=set_active,
                    current_project_id=current_project_id
                )
                db.add(new_session)
                await db.commit()
                await db.refresh(new_session)
                
                logger.info(f"新会话创建: user={user_id[:10]}, session={short_id}, project={current_project_id or 'None'}, active={set_active}")
                return new_session
    
    async def list_sessions(
        self,
        user_id: str,
        chat_id: str,
        bot_key: str | None = None,
        limit: int = 10
    ) -> list[UserSession]:
        """
        列出用户最近的会话
        
        Args:
            user_id: 用户 ID
            chat_id: 会话 ID
            bot_key: Bot Key (可选，如果提供则只返回该 Bot 的会话)
            limit: 返回数量限制
        """
        async with self._db_manager.get_session() as db:
            # 构建查询条件
            conditions = [
                UserSession.user_id == user_id,
                UserSession.chat_id == chat_id
            ]
            
            # 如果提供了 bot_key，只返回该 Bot 的会话
            if bot_key:
                conditions.append(UserSession.bot_key == bot_key)
            
            result = await db.execute(
                select(UserSession)
                .where(and_(*conditions))
                .order_by(desc(UserSession.updated_at))
                .limit(limit)
            )
            return list(result.scalars().all())
    
    async def set_session_project(
        self,
        user_id: str,
        chat_id: str,
        bot_key: str,
        project_id: str
    ) -> bool:
        """
        设置活跃会话的项目 ID
        
        Args:
            user_id: 用户 ID
            chat_id: 会话 ID
            bot_key: Bot Key
            project_id: 要切换到的项目 ID
        
        Returns:
            是否成功设置
        """
        async with self._db_manager.get_session() as db:
            # 更新活跃会话的 current_project_id
            result = await db.execute(
                update(UserSession)
                .where(and_(
                    UserSession.user_id == user_id,
                    UserSession.chat_id == chat_id,
                    UserSession.bot_key == bot_key,
                    UserSession.is_active == True
                ))
                .values(
                    current_project_id=project_id,
                    updated_at=datetime.now(timezone.utc)
                )
            )
            await db.commit()
            
            if result.rowcount > 0:
                logger.info(f"会话项目已切换: user={user_id[:10]}, project={project_id}")
                return True
            
            # 如果没有活跃会话，创建一个新的空会话来保存项目偏好
            import uuid
            new_session_id = str(uuid.uuid4())
            new_session = UserSession(
                user_id=user_id,
                chat_id=chat_id,
                bot_key=bot_key,
                session_id=new_session_id,
                short_id=new_session_id[:8],
                last_message="(项目切换)",
                message_count=0,
                is_active=True,
                current_project_id=project_id
            )
            db.add(new_session)
            await db.commit()
            logger.info(f"创建新会话用于项目切换: user={user_id[:10]}, project={project_id}")
            return True
    
    async def reset_session(
        self,
        user_id: str,
        chat_id: str,
        bot_key: str
    ) -> bool:
        """
        重置会话（将当前会话设为非活跃）
        
        Returns:
            是否成功重置
        """
        async with self._db_manager.get_session() as db:
            result = await db.execute(
                update(UserSession)
                .where(and_(
                    UserSession.user_id == user_id,
                    UserSession.chat_id == chat_id,
                    UserSession.bot_key == bot_key,
                    UserSession.is_active == True
                ))
                .values(is_active=False)
            )
            await db.commit()
            
            if result.rowcount > 0:
                logger.info(f"会话已重置: user={user_id[:10]}, chat={chat_id[:10]}")
                return True
            return False
    
    async def get_session_by_short_id(
        self,
        user_id: str,
        chat_id: str,
        short_id: str,
        bot_key: str | None = None
    ) -> Optional[UserSession]:
        """
        根据 short_id 查找会话（不切换活跃状态）
        
        用于引用回复场景：临时借用某个会话的 session_id，
        不影响当前活跃会话。
        
        Args:
            user_id: 用户 ID
            chat_id: 会话 ID
            short_id: 会话短 ID
            bot_key: Bot Key (可选)
        
        Returns:
            找到的 UserSession，如果没找到返回 None
        """
        async with self._db_manager.get_session() as db:
            # 构建基础查询条件
            base_conditions = [
                UserSession.user_id == user_id,
                UserSession.chat_id == chat_id
            ]
            if bot_key:
                base_conditions.append(UserSession.bot_key == bot_key)
            
            # 先尝试精确匹配 short_id
            result = await db.execute(
                select(UserSession)
                .where(and_(
                    *base_conditions,
                    UserSession.short_id == short_id
                ))
            )
            target = result.scalar_one_or_none()
            
            # 如果精确匹配没找到，尝试用 session_id 前缀匹配
            if not target:
                result = await db.execute(
                    select(UserSession)
                    .where(and_(
                        *base_conditions,
                        UserSession.session_id.like(f"{short_id}%")
                    ))
                )
                target = result.scalar_one_or_none()
            
            if target:
                logger.info(f"找到会话 (不切换): short_id={target.short_id}")
            
            return target
    
    async def change_session(
        self,
        user_id: str,
        chat_id: str,
        short_id: str,
        bot_key: str | None = None
    ) -> Optional[UserSession]:
        """
        切换到指定会话
        
        Args:
            user_id: 用户 ID
            chat_id: 会话 ID
            short_id: 会话短 ID
            bot_key: Bot Key (可选，如果提供则只在该 Bot 的会话中查找)
        
        Returns:
            切换到的 UserSession，如果没找到返回 None
        """
        async with self._db_manager.get_session() as db:
            # 构建基础查询条件
            base_conditions = [
                UserSession.user_id == user_id,
                UserSession.chat_id == chat_id
            ]
            if bot_key:
                base_conditions.append(UserSession.bot_key == bot_key)
            
            # 查找目标会话（使用 like 进行前缀匹配）
            # 先尝试精确匹配 short_id
            result = await db.execute(
                select(UserSession)
                .where(and_(
                    *base_conditions,
                    UserSession.short_id == short_id
                ))
            )
            target = result.scalar_one_or_none()
            
            # 如果精确匹配没找到，尝试用 session_id 前缀匹配
            if not target:
                result = await db.execute(
                    select(UserSession)
                    .where(and_(
                        *base_conditions,
                        UserSession.session_id.like(f"{short_id}%")
                    ))
                )
                target = result.scalar_one_or_none()
            
            if not target:
                return None
            
            # 将其他会话设为非活跃（只在同一 Bot 的会话中）
            deactivate_conditions = [
                UserSession.user_id == user_id,
                UserSession.chat_id == chat_id,
                UserSession.is_active == True,
                UserSession.id != target.id
            ]
            if bot_key:
                deactivate_conditions.append(UserSession.bot_key == bot_key)
            
            await db.execute(
                update(UserSession)
                .where(and_(*deactivate_conditions))
                .values(is_active=False)
            )
            
            # 激活目标会话
            target.is_active = True
            target.updated_at = datetime.now(timezone.utc)
            await db.commit()
            
            logger.info(f"会话已切换: user={user_id[:10]}, session={target.short_id}")
            return target
    
    def parse_slash_command(self, message: str) -> Optional[tuple[str, Optional[str], Optional[str]]]:
        """
        解析 Slash 命令
        
        Returns:
            (command_type, arg, extra_message) 或 None
            command_type: "list", "reset", "change"
            arg: 命令参数（如 short_id）
            extra_message: 附带消息（仅 /c 命令支持，如 "/c abc123 你好" 中的 "你好"）
        """
        message = message.strip()
        
        for cmd_type, pattern in SLASH_COMMANDS.items():
            match = pattern.match(message)
            if match:
                if cmd_type == "change":
                    # change 命令特殊处理：group(2) 是 short_id, group(3) 是附带消息
                    short_id = match.group(2)
                    extra_msg = match.group(3).strip() if match.lastindex >= 3 and match.group(3) else None
                    return (cmd_type, short_id, extra_msg)
                elif cmd_type in ("change_help", "change_invalid"):
                    # /c 不带参数或参数无效
                    invalid_arg = match.group(2) if cmd_type == "change_invalid" and match.lastindex >= 2 else None
                    return (cmd_type, invalid_arg, None)
                elif cmd_type == "bot":
                    # bot 命令：/bot <name> [url|key <value>]
                    # group(2) 是 bot 名称, group(3) 是字段类型, group(4) 是值
                    bot_name = match.group(2)
                    field_type = match.group(3) if match.lastindex >= 3 else None
                    field_value = match.group(4) if match.lastindex >= 4 else None
                    # 如果有 field_type 和 field_value，格式化为 "bot_name:field_type:value"
                    if field_type and field_value:
                        return (cmd_type, bot_name, f"{field_type}:{field_value}")
                    return (cmd_type, bot_name, None)
                else:
                    arg = match.group(2) if match.lastindex and match.lastindex >= 2 else None
                    return (cmd_type, arg, None)
        
        return None
    
    def format_session_list(self, sessions: list[UserSession]) -> str:
        """
        格式化会话列表为用户可读的消息
        """
        if not sessions:
            return "📭 暂无会话记录"
        
        lines = ["📋 **最近会话**\n"]
        
        for i, s in enumerate(sessions, 1):
            active_mark = "✅" if s.is_active else "  "
            preview = (s.last_message[:30] + "...") if s.last_message and len(s.last_message) > 30 else (s.last_message or "")
            lines.append(f"{active_mark} `{s.short_id}` - {preview} ({s.message_count}条)")
        
        lines.append("\n---")
        lines.append("💡 命令: `/c <短ID>` 切换会话, `/r` 新建会话")
        
        return "\n".join(lines)


# 全局会话管理器实例（延迟初始化）
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """获取全局会话管理器"""
    global _session_manager
    if _session_manager is None:
        raise RuntimeError("SessionManager 未初始化")
    return _session_manager


def init_session_manager(db_manager) -> SessionManager:
    """初始化全局会话管理器"""
    global _session_manager
    _session_manager = SessionManager(db_manager)
    logger.info("SessionManager 已初始化")
    return _session_manager
