"""
Forward Service 数据库访问层 (Repository/DAO)

提供对数据库的 CRUD 操作，封装所有数据库访问逻辑。
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Chatbot, ChatAccessRule, ForwardLog, SystemConfig, UserProjectConfig, ChatInfo
from .database import get_db_manager

logger = logging.getLogger(__name__)


# ============== Chatbot Repository ==============

class ChatbotRepository:
    """
    Chatbot 数据访问层

    提供对 chatbots 表的所有数据库操作
    """

    def __init__(self, session: AsyncSession):
        """
        初始化 Repository

        Args:
            session: SQLAlchemy AsyncSession
        """
        self.session = session

    async def create(
        self,
        bot_key: str,
        name: str,
        url_template: str,
        agent_id: str = "",
        api_key: str = "",
        timeout: int = 300,
        access_mode: str = "allow_all",
        description: str = "",
        enabled: bool = True
    ) -> Chatbot:
        """
        创建新的 Bot 配置

        Args:
            bot_key: Bot Key (唯一)
            name: Bot 名称
            url_template: 转发 URL 模板
            agent_id: Agent ID
            api_key: API Key
            timeout: 超时时间
            access_mode: 访问控制模式
            description: 描述
            enabled: 是否启用

        Returns:
            创建的 Chatbot 对象
        """
        bot = Chatbot(
            bot_key=bot_key,
            name=name,
            url_template=url_template,
            agent_id=agent_id,
            api_key=api_key,
            timeout=timeout,
            access_mode=access_mode,
            description=description,
            enabled=enabled
        )

        self.session.add(bot)
        await self.session.flush()

        logger.info(f"创建 Bot: {bot_key} ({name})")
        return bot

    async def get_by_id(self, bot_id: int) -> Optional[Chatbot]:
        """
        根据 ID 获取 Bot

        Args:
            bot_id: Bot ID

        Returns:
            Chatbot 对象或 None
        """
        stmt = select(Chatbot).where(Chatbot.id == bot_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_bot_key(self, bot_key: str) -> Optional[Chatbot]:
        """
        根据 bot_key 获取 Bot

        Args:
            bot_key: Bot Key

        Returns:
            Chatbot 对象或 None
        """
        stmt = select(Chatbot).where(Chatbot.bot_key == bot_key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        enabled_only: bool = False,
        include_rules: bool = False
    ) -> List[Chatbot]:
        """
        获取所有 Bot

        Args:
            enabled_only: 是否只返回启用的 Bot
            include_rules: 是否预加载访问规则

        Returns:
            Chatbot 对象列表
        """
        stmt = select(Chatbot)

        if enabled_only:
            stmt = stmt.where(Chatbot.enabled == True)

        # 按 ID 排序
        stmt = stmt.order_by(Chatbot.id)

        result = await self.session.execute(stmt)
        bots = result.scalars().all()

        return list(bots)

    async def update(
        self,
        bot_id: int,
        name: str | None = None,
        target_url: str | None = None,
        url_template: str | None = None,
        agent_id: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
        access_mode: str | None = None,
        description: str | None = None,
        enabled: bool | None = None
    ) -> Optional[Chatbot]:
        """
        更新 Bot 配置

        Args:
            bot_id: Bot ID
            name: Bot 名称
            target_url: 转发目标 URL (推荐使用)
            url_template: URL 模板 (已废弃)
            agent_id: Agent ID
            api_key: API Key
            timeout: 超时时间
            access_mode: 访问控制模式
            description: 描述
            enabled: 是否启用

        Returns:
            更新后的 Chatbot 对象或 None
        """
        # 构建更新数据
        update_data = {}
        if name is not None:
            update_data["name"] = name
        if target_url is not None:
            update_data["target_url"] = target_url
        if url_template is not None:
            update_data["url_template"] = url_template
        if agent_id is not None:
            update_data["agent_id"] = agent_id
        if api_key is not None:
            update_data["api_key"] = api_key
        if timeout is not None:
            update_data["timeout"] = timeout
        if access_mode is not None:
            update_data["access_mode"] = access_mode
        if description is not None:
            update_data["description"] = description
        if enabled is not None:
            update_data["enabled"] = enabled

        if not update_data:
            return await self.get_by_id(bot_id)

        # 执行更新
        stmt = (
            update(Chatbot)
            .where(Chatbot.id == bot_id)
            .values(**update_data)
        )
        await self.session.execute(stmt)
        await self.session.flush()

        logger.info(f"更新 Bot: id={bot_id}, fields={list(update_data.keys())}")
        return await self.get_by_id(bot_id)

    async def delete(self, bot_id: int) -> bool:
        """
        删除 Bot

        Args:
            bot_id: Bot ID

        Returns:
            是否删除成功
        """
        # 先检查是否存在
        bot = await self.get_by_id(bot_id)
        if not bot:
            return False

        # 执行删除 (会级联删除关联的 access_rules)
        stmt = delete(Chatbot).where(Chatbot.id == bot_id)
        await self.session.execute(stmt)
        await self.session.flush()

        logger.info(f"删除 Bot: id={bot_id}, bot_key={bot.bot_key}")
        return True

    async def count(self, enabled_only: bool = False) -> int:
        """
        统计 Bot 数量

        Args:
            enabled_only: 是否只统计启用的 Bot

        Returns:
            Bot 数量
        """
        stmt = select(func.count(Chatbot.id))
        if enabled_only:
            stmt = stmt.where(Chatbot.enabled == True)

        result = await self.session.execute(stmt)
        return result.scalar_one()


# ============== ChatAccessRule Repository ==============

class ChatAccessRuleRepository:
    """
    ChatAccessRule 数据访问层

    提供对 chat_access_rules 表的所有数据库操作
    """

    def __init__(self, session: AsyncSession):
        """
        初始化 Repository

        Args:
            session: SQLAlchemy AsyncSession
        """
        self.session = session

    async def create(
        self,
        chatbot_id: int,
        chat_id: str,
        rule_type: str,
        remark: str = ""
    ) -> ChatAccessRule:
        """
        创建访问规则

        Args:
            chatbot_id: Bot ID
            chat_id: Chat ID (用户ID或群ID)
            rule_type: 规则类型 (whitelist/blacklist)
            remark: 备注

        Returns:
            创建的 ChatAccessRule 对象
        """
        rule = ChatAccessRule(
            chatbot_id=chatbot_id,
            chat_id=chat_id,
            rule_type=rule_type,
            remark=remark
        )

        self.session.add(rule)
        await self.session.flush()

        logger.info(f"创建访问规则: chatbot_id={chatbot_id}, chat_id={chat_id}, type={rule_type}")
        return rule

    async def get_by_id(self, rule_id: int) -> Optional[ChatAccessRule]:
        """
        根据 ID 获取规则

        Args:
            rule_id: 规则 ID

        Returns:
            ChatAccessRule 对象或 None
        """
        stmt = select(ChatAccessRule).where(ChatAccessRule.id == rule_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_chatbot(
        self,
        chatbot_id: int,
        rule_type: str | None = None
    ) -> List[ChatAccessRule]:
        """
        获取 Bot 的所有访问规则

        Args:
            chatbot_id: Bot ID
            rule_type: 规则类型过滤 (whitelist/blacklist，None 表示全部)

        Returns:
            ChatAccessRule 对象列表
        """
        stmt = select(ChatAccessRule).where(ChatAccessRule.chatbot_id == chatbot_id)

        if rule_type:
            stmt = stmt.where(ChatAccessRule.rule_type == rule_type)

        stmt = stmt.order_by(ChatAccessRule.id)

        result = await self.session.execute(stmt)
        rules = result.scalars().all()

        return list(rules)

    async def get_whitelist(self, chatbot_id: int) -> List[str]:
        """
        获取 Bot 的白名单 Chat ID 列表

        Args:
            chatbot_id: Bot ID

        Returns:
            Chat ID 列表
        """
        stmt = select(ChatAccessRule.chat_id).where(
            ChatAccessRule.chatbot_id == chatbot_id,
            ChatAccessRule.rule_type == "whitelist"
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_blacklist(self, chatbot_id: int) -> List[str]:
        """
        获取 Bot 的黑名单 Chat ID 列表

        Args:
            chatbot_id: Bot ID

        Returns:
            Chat ID 列表
        """
        stmt = select(ChatAccessRule.chat_id).where(
            ChatAccessRule.chatbot_id == chatbot_id,
            ChatAccessRule.rule_type == "blacklist"
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, rule_id: int) -> bool:
        """
        删除规则

        Args:
            rule_id: 规则 ID

        Returns:
            是否删除成功
        """
        rule = await self.get_by_id(rule_id)
        if not rule:
            return False

        stmt = delete(ChatAccessRule).where(ChatAccessRule.id == rule_id)
        await self.session.execute(stmt)
        await self.session.flush()

        logger.info(f"删除访问规则: id={rule_id}")
        return True

    async def delete_by_chatbot(self, chatbot_id: int) -> int:
        """
        删除 Bot 的所有访问规则

        Args:
            chatbot_id: Bot ID

        Returns:
            删除的规则数量
        """
        stmt = delete(ChatAccessRule).where(ChatAccessRule.chatbot_id == chatbot_id)
        result = await self.session.execute(stmt)
        await self.session.flush()

        count = result.rowcount
        logger.info(f"删除 Bot {chatbot_id} 的所有访问规则: count={count}")
        return count

    async def set_whitelist(
        self,
        chatbot_id: int,
        chat_ids: List[str],
        clear_existing: bool = True
    ) -> List[ChatAccessRule]:
        """
        设置白名单 (批量)

        Args:
            chatbot_id: Bot ID
            chat_ids: Chat ID 列表
            clear_existing: 是否清除现有白名单

        Returns:
            创建的规则列表
        """
        # 清除现有白名单
        if clear_existing:
            await self._clear_rules_by_type(chatbot_id, "whitelist")

        # 批量创建新规则
        rules = []
        for chat_id in chat_ids:
            rule = await self.create(chatbot_id, chat_id, "whitelist")
            rules.append(rule)

        logger.info(f"设置白名单: chatbot_id={chatbot_id}, count={len(rules)}")
        return rules

    async def set_blacklist(
        self,
        chatbot_id: int,
        chat_ids: List[str],
        clear_existing: bool = True
    ) -> List[ChatAccessRule]:
        """
        设置黑名单 (批量)

        Args:
            chatbot_id: Bot ID
            chat_ids: Chat ID 列表
            clear_existing: 是否清除现有黑名单

        Returns:
            创建的规则列表
        """
        # 清除现有黑名单
        if clear_existing:
            await self._clear_rules_by_type(chatbot_id, "blacklist")

        # 批量创建新规则
        rules = []
        for chat_id in chat_ids:
            rule = await self.create(chatbot_id, chat_id, "blacklist")
            rules.append(rule)

        logger.info(f"设置黑名单: chatbot_id={chatbot_id}, count={len(rules)}")
        return rules

    async def _clear_rules_by_type(self, chatbot_id: int, rule_type: str):
        """清除指定类型的所有规则"""
        stmt = delete(ChatAccessRule).where(
            ChatAccessRule.chatbot_id == chatbot_id,
            ChatAccessRule.rule_type == rule_type
        )
        await self.session.execute(stmt)
        await self.session.flush()


# ============== Forward Log Repository ==============

class ForwardLogRepository:
    """
    Forward 日志数据访问层
    
    提供对 forward_logs 表的所有数据库操作
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(
        self,
        chat_id: str,
        from_user_id: str,
        content: str,
        target_url: str,
        from_user_name: str = None,
        msg_type: str = "text",
        bot_key: str = None,
        bot_name: str = None,
        session_id: str = None,
        status: str = "pending",
        response: str = None,
        error: str = None,
        duration_ms: int = 0,
    ) -> ForwardLog:
        """创建日志记录"""
        log = ForwardLog(
            chat_id=chat_id,
            from_user_id=from_user_id,
            from_user_name=from_user_name,
            content=content[:5000] if content else "",  # 限制长度
            msg_type=msg_type,
            bot_key=bot_key,
            bot_name=bot_name,
            target_url=target_url[:1000] if target_url else "",  # 限制长度
            session_id=session_id,
            status=status,
            response=response[:10000] if response else None,  # 限制长度
            error=error[:2000] if error else None,  # 限制长度
            duration_ms=duration_ms,
        )
        self.session.add(log)
        await self.session.flush()
        await self.session.refresh(log)
        return log
    
    async def update_response(
        self,
        log_id: int,
        status: str,
        response: str = None,
        error: str = None,
        session_id: str = None,
        duration_ms: int = None,
    ) -> ForwardLog | None:
        """更新日志的响应信息"""
        stmt = select(ForwardLog).where(ForwardLog.id == log_id)
        result = await self.session.execute(stmt)
        log = result.scalar_one_or_none()
        
        if log:
            log.status = status
            if response is not None:
                log.response = response[:10000] if response else None
            if error is not None:
                log.error = error[:2000] if error else None
            if session_id is not None:
                log.session_id = session_id
            if duration_ms is not None:
                log.duration_ms = duration_ms
            await self.session.flush()
        
        return log
    
    async def get_recent(self, limit: int = 100) -> List[ForwardLog]:
        """获取最近的日志"""
        stmt = (
            select(ForwardLog)
            .order_by(ForwardLog.timestamp.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def get_by_chat_id(self, chat_id: str, limit: int = 50) -> List[ForwardLog]:
        """获取指定会话的日志"""
        stmt = (
            select(ForwardLog)
            .where(ForwardLog.chat_id == chat_id)
            .order_by(ForwardLog.timestamp.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def get_by_bot_key(self, bot_key: str, limit: int = 50) -> List[ForwardLog]:
        """获取指定 Bot 的日志"""
        stmt = (
            select(ForwardLog)
            .where(ForwardLog.bot_key == bot_key)
            .order_by(ForwardLog.timestamp.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def count(self) -> int:
        """获取日志总数"""
        stmt = select(func.count(ForwardLog.id))
        result = await self.session.execute(stmt)
        return result.scalar() or 0
    
    async def cleanup_old_logs(self, days: int = 30) -> int:
        """清理指定天数之前的日志"""
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        stmt = delete(ForwardLog).where(ForwardLog.timestamp < cutoff)
        result = await self.session.execute(stmt)
        await self.session.flush()
        
        deleted = result.rowcount or 0
        if deleted > 0:
            logger.info(f"清理 {deleted} 条旧日志 (超过 {days} 天)")
        return deleted


# ============== System Config Repository ==============

class SystemConfigRepository:
    """
    系统配置数据访问层
    
    提供对 system_config 表的所有数据库操作
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get(self, key: str) -> SystemConfig | None:
        """获取配置项"""
        stmt = select(SystemConfig).where(SystemConfig.key == key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_value(self, key: str, default: str = "") -> str:
        """获取配置值"""
        config = await self.get(key)
        return config.value if config else default
    
    async def set(self, key: str, value: str, description: str = None) -> SystemConfig:
        """设置配置项"""
        config = await self.get(key)
        
        if config:
            config.value = value
            if description is not None:
                config.description = description
            await self.session.flush()
        else:
            config = SystemConfig(
                key=key,
                value=value,
                description=description
            )
            self.session.add(config)
            await self.session.flush()
            await self.session.refresh(config)
        
        return config
    
    async def delete(self, key: str) -> bool:
        """删除配置项"""
        stmt = delete(SystemConfig).where(SystemConfig.key == key)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0
    
    async def get_all(self) -> List[SystemConfig]:
        """获取所有配置项"""
        stmt = select(SystemConfig).order_by(SystemConfig.key)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ============== 辅助函数 ==============

def get_chatbot_repository(session: AsyncSession) -> ChatbotRepository:
    """获取 ChatbotRepository 实例"""
    return ChatbotRepository(session)


def get_access_rule_repository(session: AsyncSession) -> ChatAccessRuleRepository:
    """获取 ChatAccessRuleRepository 实例"""
    return ChatAccessRuleRepository(session)


def get_forward_log_repository(session: AsyncSession) -> ForwardLogRepository:
    """获取 ForwardLogRepository 实例"""
    return ForwardLogRepository(session)


def get_system_config_repository(session: AsyncSession) -> SystemConfigRepository:
    """获取 SystemConfigRepository 实例"""
    return SystemConfigRepository(session)


# ============== UserProjectConfig Repository ==============

class UserProjectConfigRepository:
    """
    用户项目配置数据访问层

    提供对 user_project_configs 表的所有数据库操作
    """

    def __init__(self, session: AsyncSession):
        """
        初始化 Repository

        Args:
            session: SQLAlchemy AsyncSession
        """
        self.session = session

    async def create(
        self,
        bot_key: str,
        chat_id: str,
        project_id: str,
        url_template: str,
        api_key: Optional[str] = None,
        project_name: Optional[str] = None,
        timeout: int = 300,
        is_default: bool = False,
        enabled: bool = True
    ) -> UserProjectConfig:
        """
        创建新的用户项目配置

        Args:
            bot_key: 所属 Bot Key
            chat_id: 用户/群 ID
            project_id: 项目标识
            url_template: 转发 URL 模板
            api_key: API Key（可选）
            project_name: 项目名称（可选）
            timeout: 超时时间
            is_default: 是否为默认项目
            enabled: 是否启用

        Returns:
            创建的 UserProjectConfig 对象
        """
        # 如果设置为默认，先将同一用户的其他默认项目取消
        if is_default:
            await self._clear_default_flag(bot_key, chat_id)

        config = UserProjectConfig(
            bot_key=bot_key,
            chat_id=chat_id,
            project_id=project_id,
            url_template=url_template,
            api_key=api_key,
            project_name=project_name,
            timeout=timeout,
            is_default=is_default,
            enabled=enabled
        )

        self.session.add(config)
        await self.session.flush()

        logger.info(f"创建用户项目配置: bot={bot_key[:10]}, user={chat_id[:10]}, project={project_id}")
        return config

    async def get_by_id(self, config_id: int) -> Optional[UserProjectConfig]:
        """
        根据 ID 获取配置

        Args:
            config_id: 配置 ID

        Returns:
            UserProjectConfig 对象或 None
        """
        stmt = select(UserProjectConfig).where(UserProjectConfig.id == config_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_project_id(
        self,
        bot_key: str,
        chat_id: str,
        project_id: str
    ) -> Optional[UserProjectConfig]:
        """
        根据 bot_key + chat_id + project_id 获取配置

        Args:
            bot_key: Bot Key
            chat_id: 用户/群 ID
            project_id: 项目 ID

        Returns:
            UserProjectConfig 对象或 None
        """
        stmt = select(UserProjectConfig).where(
            UserProjectConfig.bot_key == bot_key,
            UserProjectConfig.chat_id == chat_id,
            UserProjectConfig.project_id == project_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_projects(
        self,
        bot_key: str,
        chat_id: str,
        enabled_only: bool = True
    ) -> List[UserProjectConfig]:
        """
        获取用户在指定 Bot 下的所有项目配置

        Args:
            bot_key: Bot Key
            chat_id: 用户/群 ID
            enabled_only: 是否只返回启用的配置

        Returns:
            UserProjectConfig 对象列表
        """
        conditions = [
            UserProjectConfig.bot_key == bot_key,
            UserProjectConfig.chat_id == chat_id
        ]

        if enabled_only:
            conditions.append(UserProjectConfig.enabled == True)

        stmt = select(UserProjectConfig).where(*conditions).order_by(
            UserProjectConfig.is_default.desc(),
            UserProjectConfig.created_at
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_default_project(
        self,
        bot_key: str,
        chat_id: str
    ) -> Optional[UserProjectConfig]:
        """
        获取用户的默认项目配置

        Args:
            bot_key: Bot Key
            chat_id: 用户/群 ID

        Returns:
            默认的 UserProjectConfig 对象或 None
        """
        stmt = select(UserProjectConfig).where(
            UserProjectConfig.bot_key == bot_key,
            UserProjectConfig.chat_id == chat_id,
            UserProjectConfig.is_default == True,
            UserProjectConfig.enabled == True
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(
        self,
        config_id: int,
        url_template: Optional[str] = None,
        api_key: Optional[str] = None,
        project_name: Optional[str] = None,
        timeout: Optional[int] = None,
        is_default: Optional[bool] = None,
        enabled: Optional[bool] = None
    ) -> Optional[UserProjectConfig]:
        """
        更新项目配置

        Args:
            config_id: 配置 ID
            url_template: 新的 URL 模板（可选）
            api_key: 新的 API Key（可选）
            project_name: 新的项目名称（可选）
            timeout: 新的超时时间（可选）
            is_default: 新的默认标记（可选）
            enabled: 新的启用状态（可选）

        Returns:
            更新后的 UserProjectConfig 对象，如果不存在返回 None
        """
        # 构建更新字典
        update_values = {}
        if url_template is not None:
            update_values['url_template'] = url_template
        if api_key is not None:
            update_values['api_key'] = api_key
        if project_name is not None:
            update_values['project_name'] = project_name
        if timeout is not None:
            update_values['timeout'] = timeout
        if enabled is not None:
            update_values['enabled'] = enabled
        if is_default is not None:
            update_values['is_default'] = is_default

        if not update_values:
            return await self.get_by_id(config_id)

        # 如果设置为默认，先将同一用户的其他默认项目取消
        if is_default:
            config = await self.get_by_id(config_id)
            if config:
                await self._clear_default_flag(config.bot_key, config.chat_id)

        # 执行更新
        stmt = update(UserProjectConfig).where(
            UserProjectConfig.id == config_id
        ).values(**update_values)
        await self.session.execute(stmt)
        await self.session.flush()

        logger.info(f"更新用户项目配置: id={config_id}")
        return await self.get_by_id(config_id)

    async def delete(self, config_id: int) -> bool:
        """
        删除项目配置

        Args:
            config_id: 配置 ID

        Returns:
            是否成功删除
        """
        stmt = delete(UserProjectConfig).where(UserProjectConfig.id == config_id)
        result = await self.session.execute(stmt)
        await self.session.flush()

        if result.rowcount > 0:
            logger.info(f"删除用户项目配置: id={config_id}")
            return True
        return False

    async def delete_by_project_id(
        self,
        bot_key: str,
        chat_id: str,
        project_id: str
    ) -> bool:
        """
        根据 bot_key + chat_id + project_id 删除配置

        Args:
            bot_key: Bot Key
            chat_id: 用户/群 ID
            project_id: 项目 ID

        Returns:
            是否成功删除
        """
        stmt = delete(UserProjectConfig).where(
            UserProjectConfig.bot_key == bot_key,
            UserProjectConfig.chat_id == chat_id,
            UserProjectConfig.project_id == project_id
        )
        result = await self.session.execute(stmt)
        await self.session.flush()

        if result.rowcount > 0:
            logger.info(f"删除用户项目配置: bot={bot_key[:10]}, user={chat_id[:10]}, project={project_id}")
            return True
        return False

    async def set_default(
        self,
        bot_key: str,
        chat_id: str,
        project_id: str
    ) -> bool:
        """
        设置默认项目

        Args:
            bot_key: Bot Key
            chat_id: 用户/群 ID
            project_id: 项目 ID

        Returns:
            是否成功设置
        """
        # 先取消其他默认项目
        await self._clear_default_flag(bot_key, chat_id)

        # 设置新的默认项目
        stmt = update(UserProjectConfig).where(
            UserProjectConfig.bot_key == bot_key,
            UserProjectConfig.chat_id == chat_id,
            UserProjectConfig.project_id == project_id
        ).values(is_default=True)

        result = await self.session.execute(stmt)
        await self.session.flush()

        if result.rowcount > 0:
            logger.info(f"设置默认项目: bot={bot_key[:10]}, user={chat_id[:10]}, project={project_id}")
            return True
        return False

    async def count_user_projects(
        self,
        bot_key: str,
        chat_id: str,
        enabled_only: bool = True
    ) -> int:
        """
        统计用户的项目配置数量

        Args:
            bot_key: Bot Key
            chat_id: 用户/群 ID
            enabled_only: 是否只统计启用的配置

        Returns:
            配置数量
        """
        conditions = [
            UserProjectConfig.bot_key == bot_key,
            UserProjectConfig.chat_id == chat_id
        ]

        if enabled_only:
            conditions.append(UserProjectConfig.enabled == True)

        stmt = select(func.count(UserProjectConfig.id)).where(*conditions)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def _clear_default_flag(self, bot_key: str, chat_id: str) -> None:
        """
        清除用户的所有默认项目标记（内部方法）

        Args:
            bot_key: Bot Key
            chat_id: 用户/群 ID
        """
        stmt = update(UserProjectConfig).where(
            UserProjectConfig.bot_key == bot_key,
            UserProjectConfig.chat_id == chat_id,
            UserProjectConfig.is_default == True
        ).values(is_default=False)

        await self.session.execute(stmt)

    async def get_all_by_bot_key(
        self,
        bot_key: str,
        enabled_only: bool = False
    ) -> list[UserProjectConfig]:
        """
        获取某个 Bot 下的所有用户配置

        Args:
            bot_key: Bot Key
            enabled_only: 是否只返回启用的配置

        Returns:
            用户配置列表
        """
        conditions = [UserProjectConfig.bot_key == bot_key]

        if enabled_only:
            conditions.append(UserProjectConfig.enabled == True)

        stmt = select(UserProjectConfig).where(*conditions).order_by(
            UserProjectConfig.chat_id,
            UserProjectConfig.project_id
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


def get_user_project_repository(session: AsyncSession) -> UserProjectConfigRepository:
    """获取 UserProjectConfigRepository 实例"""
    return UserProjectConfigRepository(session)


# ============== ChatInfo Repository ==============

class ChatInfoRepository:
    """
    Chat 信息数据访问层
    
    提供对 chat_info 表的所有数据库操作
    用于存储和查询 chat_id -> chat_type 的映射关系
    """
    
    def __init__(self, session: AsyncSession):
        """
        初始化 Repository
        
        Args:
            session: SQLAlchemy AsyncSession
        """
        self.session = session
    
    async def get_by_chat_id(self, chat_id: str) -> Optional[ChatInfo]:
        """
        根据 chat_id 获取 Chat 信息
        
        Args:
            chat_id: Chat ID
        
        Returns:
            ChatInfo 对象或 None
        """
        stmt = select(ChatInfo).where(ChatInfo.chat_id == chat_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_chat_type(self, chat_id: str) -> Optional[str]:
        """
        获取 chat_id 对应的 chat_type
        
        Args:
            chat_id: Chat ID
        
        Returns:
            chat_type ("group" / "single") 或 None（如果未记录）
        """
        info = await self.get_by_chat_id(chat_id)
        return info.chat_type if info else None
    
    async def is_group(self, chat_id: str) -> Optional[bool]:
        """
        判断 chat_id 是否为群聊
        
        Args:
            chat_id: Chat ID
        
        Returns:
            True（群聊）/ False（私聊）/ None（未知）
        """
        chat_type = await self.get_chat_type(chat_id)
        if chat_type is None:
            return None
        return chat_type == "group"
    
    async def record_chat(
        self,
        chat_id: str,
        chat_type: str,
        chat_name: Optional[str] = None,
        bot_key: Optional[str] = None
    ) -> ChatInfo:
        """
        记录或更新 Chat 信息
        
        如果 chat_id 已存在，更新 last_seen_at 和 message_count
        如果 chat_id 不存在，创建新记录
        
        Args:
            chat_id: Chat ID
            chat_type: Chat 类型 ("group" / "single")
            chat_name: Chat 名称（可选）
            bot_key: 收到消息的 Bot Key（可选）
        
        Returns:
            ChatInfo 对象
        """
        existing = await self.get_by_chat_id(chat_id)
        
        if existing:
            # 更新现有记录
            existing.message_count += 1
            existing.last_seen_at = datetime.now(timezone.utc)
            # 如果 chat_type 发生变化（理论上不应该），记录日志
            if existing.chat_type != chat_type:
                logger.warning(
                    f"Chat type changed: chat_id={chat_id}, "
                    f"old={existing.chat_type}, new={chat_type}"
                )
                existing.chat_type = chat_type
            # 更新 chat_name（如果提供）
            if chat_name and not existing.chat_name:
                existing.chat_name = chat_name
            await self.session.flush()
            return existing
        else:
            # 创建新记录
            info = ChatInfo(
                chat_id=chat_id,
                chat_type=chat_type,
                chat_name=chat_name,
                first_bot_key=bot_key,
                message_count=1
            )
            self.session.add(info)
            await self.session.flush()
            logger.info(f"记录新 Chat: chat_id={chat_id[:20]}..., type={chat_type}")
            return info
    
    async def get_all(
        self,
        chat_type: Optional[str] = None,
        limit: int = 100
    ) -> List[ChatInfo]:
        """
        获取所有 Chat 信息
        
        Args:
            chat_type: 过滤类型（可选）
            limit: 返回数量限制
        
        Returns:
            ChatInfo 对象列表
        """
        stmt = select(ChatInfo)
        
        if chat_type:
            stmt = stmt.where(ChatInfo.chat_type == chat_type)
        
        stmt = stmt.order_by(ChatInfo.last_seen_at.desc()).limit(limit)
        
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def get_groups(self, limit: int = 100) -> List[ChatInfo]:
        """获取所有群聊"""
        return await self.get_all(chat_type="group", limit=limit)
    
    async def get_singles(self, limit: int = 100) -> List[ChatInfo]:
        """获取所有私聊"""
        return await self.get_all(chat_type="single", limit=limit)
    
    async def count(self, chat_type: Optional[str] = None) -> int:
        """
        统计 Chat 数量
        
        Args:
            chat_type: 过滤类型（可选）
        
        Returns:
            Chat 数量
        """
        stmt = select(func.count(ChatInfo.id))
        
        if chat_type:
            stmt = stmt.where(ChatInfo.chat_type == chat_type)
        
        result = await self.session.execute(stmt)
        return result.scalar() or 0
    
    async def delete(self, chat_id: str) -> bool:
        """
        删除 Chat 信息
        
        Args:
            chat_id: Chat ID
        
        Returns:
            是否删除成功
        """
        stmt = delete(ChatInfo).where(ChatInfo.chat_id == chat_id)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0


def get_chat_info_repository(session: AsyncSession) -> ChatInfoRepository:
    """获取 ChatInfoRepository 实例"""
    return ChatInfoRepository(session)
