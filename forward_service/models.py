"""
Forward Service 数据库模型

使用 SQLAlchemy ORM 定义数据库表结构:
- chatbots: 存储 Bot 配置
- chat_access_rules: 存储黑白名单规则

支持多种数据库引擎:
- 开发/测试: SQLite (内存或文件)
- 生产: MySQL
"""
from datetime import datetime, timezone
from typing import Optional
try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal
from sqlalchemy import (
    String, Boolean, Integer, Text, DateTime, ForeignKey,
    Index, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.hybrid import hybrid_property


# ============== Base Class ==============

class Base(DeclarativeBase):
    """所有模型的基类"""
    pass


# ============== 枚举类型定义 ==============

AccessMode = Literal["allow_all", "whitelist", "blacklist"]


# ============== 数据库模型 ==============

class Chatbot(Base):
    """
    Chatbot 配置表

    存储企业微信机器人的配置信息，包括:
    - 基本信息: bot_key, name, description
    - 转发配置: url_template, agent_id, api_key, timeout
    - 访问控制模式: allow_all, whitelist, blacklist
    - 状态: enabled
    """
    __tablename__ = "chatbots"

    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Bot Key (企业微信 Webhook Key，唯一标识)
    bot_key: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="企微机器人 Webhook Key (唯一)"
    )

    # 基本信息
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        default="未命名 Bot",
        comment="Bot 名称"
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Bot 描述"
    )

    # 平台类型
    platform: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="wecom",
        index=True,
        comment="平台类型: wecom, wecom-intelligent, slack, discord, telegram"
    )

    # 转发配置 - 新字段 target_url (推荐使用)
    target_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="转发目标 URL (完整地址，推荐使用)"
    )

    # 转发配置 - 旧字段 url_template (已废弃，保留兼容)
    url_template: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="URL 模板 (已废弃，保留用于数据迁移)"
    )

    agent_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        default="",
        comment="Agent ID (用于 URL 模板替换)"
    )

    api_key: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        default="",
        comment="转发请求的 API Key (可选)"
    )

    timeout: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
        comment="转发请求超时时间 (秒)"
    )

    # 平台特定配置（JSON 格式）
    platform_config: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
<<<<<<< HEAD
        comment="平台特定配置（JSON 格式），例如智能机器人: {support_stream, support_template_card}"
=======
        comment="平台特定配置（JSON 格式），例如 Slack: {bot_token, signing_secret}"
>>>>>>> feature/discord-integration
    )

    # 访问控制模式
    access_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="allow_all",
        comment="访问控制模式: allow_all, whitelist, blacklist"
    )

    # 状态
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="是否启用"
    )

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="创建时间"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="更新时间"
    )

    # 关系: 一个 Bot 有多个访问规则
    access_rules: Mapped[list["ChatAccessRule"]] = relationship(
        "ChatAccessRule",
        back_populates="chatbot",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    # 索引
    __table_args__ = (
        Index("idx_chatbots_enabled", "enabled"),
        Index("idx_chatbots_bot_key", "bot_key"),
        Index("idx_chatbots_platform", "platform"),
    )

    def __repr__(self) -> str:
        return f"<Chatbot(id={self.id}, bot_key={self.bot_key[:10]}..., name={self.name}, platform={self.platform})>"

    # ============== Platform Config Helpers ==============

    def get_platform_config(self) -> dict:
        """获取平台特定配置（解析 JSON）"""
        if not self.platform_config:
            return {}
        try:
            import json
            return json.loads(self.platform_config)
        except Exception:
            return {}

    def set_platform_config(self, config: dict) -> None:
        """设置平台特定配置（转为 JSON）"""
        import json
        self.platform_config = json.dumps(config, ensure_ascii=False)

    # ============== Hybird Properties (兼容旧代码) ==============

    @hybrid_property
    def forward_config_url_template(self) -> str:
        """兼容旧的 forward_config.url_template"""
        return self.url_template

    @hybrid_property
    def forward_config_agent_id(self) -> str:
        """兼容旧的 forward_config.agent_id"""
        return self.agent_id or ""

    @hybrid_property
    def forward_config_api_key(self) -> str:
        """兼容旧的 forward_config.api_key"""
        return self.api_key or ""

    @hybrid_property
    def forward_config_timeout(self) -> int:
        """兼容旧的 forward_config.timeout"""
        return self.timeout

    # ============== 实例方法 ==============

    def get_url(self) -> str:
        """获取完整的转发 URL
        
        优先使用 target_url，如果没有则回退到 url_template (兼容旧数据)
        """
        if self.target_url:
            return self.target_url
        # 兼容旧数据：使用 url_template 并替换占位符
        if self.url_template:
            return self.url_template.replace("{agent_id}", self.agent_id or "")
        return ""

    def check_access(self, user_id: str) -> tuple[bool, str]:
        """
        检查用户是否有权限访问此 Bot

        注意: 此方法假设 access_rules 已经预加载 (使用 selectin loading)
        如果没有预加载,应该在查询时使用 options(selectinload(Chatbot.access_rules))

        Args:
            user_id: 用户 ID

        Returns:
            (allowed, reason) - allowed 为 True 表示允许访问
        """
        if not self.enabled:
            return False, "Bot 已禁用"

        if self.access_mode == "allow_all":
            return True, ""

        elif self.access_mode == "whitelist":
            # 检查白名单
            for rule in self.access_rules:
                if rule.rule_type == "whitelist" and rule.chat_id == user_id:
                    return True, ""
            return False, "抱歉，您还没有权限访问此 Bot，如有意向，请联系作者。"

        elif self.access_mode == "blacklist":
            # 检查黑名单
            for rule in self.access_rules:
                if rule.rule_type == "blacklist" and rule.chat_id == user_id:
                    return False, "抱歉，您还没有权限访问此 Bot，如有意向，请联系作者。"
            return True, ""

        return False, "未知的访问控制模式"

    def to_dict(self, include_rules: bool = False) -> dict:
        """
        转换为字典 (用于 API 返回)

        Args:
            include_rules: 是否包含访问规则详情
        """
        data = {
            "id": self.id,
            "bot_key": self.bot_key,
            "name": self.name,
            "description": self.description,
            "forward_config": {
                "url_template": self.url_template,
                "agent_id": self.agent_id,
                "api_key": self.api_key,
                "timeout": self.timeout
            },
            "access_control": {
                "mode": self.access_mode,
                "whitelist": [],
                "blacklist": []
            },
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        # 添加访问规则
        if include_rules:
            for rule in self.access_rules:
                if rule.rule_type == "whitelist":
                    data["access_control"]["whitelist"].append(rule.chat_id)
                elif rule.rule_type == "blacklist":
                    data["access_control"]["blacklist"].append(rule.chat_id)

        return data


class UserProjectConfig(Base):
    """
    用户项目配置表

    存储每个用户在 Bot 下配置的多个转发项目：
    - 一个 Bot 下，每个用户可以配置多个项目
    - 每个项目包含完整的转发配置（URL、API Key）
    - 支持设置默认项目，优先级高于 Bot 级别配置
    """
    __tablename__ = "user_project_configs"

    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 所属 Bot
    bot_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="所属 Bot Key"
    )

    # 用户/群标识
    chat_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
        comment="用户/群 ID"
    )

    # 项目标识
    project_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="项目标识（如 'test', 'prod'）"
    )

    # 项目基本信息
    project_name: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="项目名称（显示用）"
    )

    # 转发配置
    url_template: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="转发目标 URL 模板"
    )

    agent_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        default="",
        comment="Agent ID (历史字段，保留用于兼容)"
    )

    api_key: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="转发请求的 API Key"
    )

    timeout: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=60,
        comment="转发请求超时时间 (秒)"
    )

    # 默认标记
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否为该用户的默认项目"
    )

    # 状态
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="是否启用"
    )

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="创建时间"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="更新时间"
    )

    # 约束和索引
    __table_args__ = (
        UniqueConstraint(
            "bot_key", "chat_id", "project_id",
            name="uq_user_project_bot_chat_project"
        ),
        Index("idx_user_projects_lookup", "bot_key", "chat_id", "enabled"),
        Index("idx_user_projects_default", "bot_key", "chat_id", "is_default"),
    )

    def __repr__(self) -> str:
        return f"<UserProjectConfig(id={self.id}, bot={self.bot_key[:10]}, user={self.chat_id[:10]}, project={self.project_id})>"

    def get_url(self) -> str:
        """获取完整的转发 URL (替换占位符)"""
        # 保留 agent_id 替换逻辑用于兼容，但实际使用中 URL 应该已经包含完整信息
        return self.url_template.replace("{agent_id}", self.agent_id or "")

    def to_dict(self) -> dict:
        """转换为字典 (用于 API 返回)"""
        return {
            "id": self.id,
            "bot_key": self.bot_key,
            "chat_id": self.chat_id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "url_template": self.url_template,
            "api_key": self.api_key,
            "timeout": self.timeout,
            "is_default": self.is_default,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UserSession(Base):
    """
    用户会话表

    记录用户与 Agent 的会话信息，用于：
    - 会话持续性：下次用户上行时带上 session_id
    - 会话管理：支持 /sess, /reset, /change 命令
    - 项目关联：每个会话可以关联一个用户项目配置
    """
    __tablename__ = "user_sessions"

    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 用户标识
    user_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="用户 ID"
    )

    # 会话上下文
    chat_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
        comment="Chat ID (群ID或私聊ID)"
    )

    bot_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="关联的 Bot Key"
    )

    # Agent 会话 ID
    session_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Agent 返回的 Session ID"
    )

    short_id: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        index=True,
        comment="Session ID 短标识 (前8位)"
    )

    # 会话信息
    last_message: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="用户最后一条消息 (用于展示)"
    )

    message_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="消息计数"
    )

    # 项目关联（新增）
    current_project_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="当前使用的项目 ID"
    )

    project_config_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user_project_configs.id", ondelete="SET NULL"),
        nullable=True,
        comment="关联的项目配置 ID (外键)"
    )

    # 状态
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="是否为当前活跃会话"
    )

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="创建时间"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="更新时间"
    )

    # 索引
    __table_args__ = (
        Index("idx_user_session_active", "user_id", "chat_id", "bot_key", "is_active"),
        Index("idx_user_session_short_id", "user_id", "chat_id", "short_id"),
        Index("idx_user_session_project", "current_project_id"),
    )
    
    def __repr__(self) -> str:
        return f"<UserSession(id={self.id}, user={self.user_id[:10]}, session={self.short_id})>"
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "bot_key": self.bot_key,
            "session_id": self.session_id,
            "short_id": self.short_id,
            "last_message": self.last_message,
            "message_count": self.message_count,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ChatAccessRule(Base):
    """
    Chat 访问规则表 (黑白名单)

    存储每个 Bot 的访问控制规则:
    - 白名单: 仅允许特定 chat_id 访问
    - 黑名单: 禁止特定 chat_id 访问

    与 chatbots 表是一对多关系
    """
    __tablename__ = "chat_access_rules"

    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 外键: 关联到 chatbots 表
    chatbot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("chatbots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的 Bot ID"
    )

    # Chat ID (用户 ID 或群 ID)
    chat_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Chat ID (用户ID或群ID)"
    )

    # 规则类型
    rule_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="规则类型: whitelist 或 blacklist"
    )

    # 备注 (可选)
    remark: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="备注说明"
    )

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="创建时间"
    )

    # 关系: 一个规则属于一个 Bot
    chatbot: Mapped["Chatbot"] = relationship(
        "Chatbot",
        back_populates="access_rules"
    )

    # 约束: 同一个 Bot 的 chat_id + rule_type 必须唯一
    __table_args__ = (
        UniqueConstraint(
            "chatbot_id", "chat_id", "rule_type",
            name="uq_chatbot_chat_rule"
        ),
        Index("idx_access_rules_chatbot_id", "chatbot_id"),
        Index("idx_access_rules_chat_id", "chat_id"),
        Index("idx_access_rules_rule_type", "rule_type"),
    )

    def __repr__(self) -> str:
        return f"<ChatAccessRule(id={self.id}, chatbot_id={self.chatbot_id}, chat_id={self.chat_id}, type={self.rule_type})>"

    def to_dict(self) -> dict:
        """转换为字典 (用于 API 返回)"""
        return {
            "id": self.id,
            "chatbot_id": self.chatbot_id,
            "chat_id": self.chat_id,
            "rule_type": self.rule_type,
            "remark": self.remark,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ============== Forward 日志模型 ==============

class ForwardLog(Base):
    """
    Forward 请求日志表
    
    存储每次企微消息转发的请求和响应记录，用于：
    - 调试和排查问题
    - 统计和分析
    - 审计追踪
    """
    __tablename__ = "forward_logs"
    
    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # 请求时间
    timestamp: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        comment="请求时间"
    )
    
    # 来源信息
    chat_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
        comment="群聊/会话 ID"
    )
    
    from_user_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="发送者用户 ID"
    )
    
    from_user_name: Mapped[str] = mapped_column(
        String(100),
        nullable=True,
        comment="发送者用户名"
    )
    
    # 请求内容
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="用户发送的消息内容"
    )
    
    msg_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="text",
        comment="消息类型 (text/image/mixed)"
    )
    
    # Bot 信息
    bot_key: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="使用的 Bot Key"
    )
    
    bot_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Bot 名称"
    )
    
    # 转发目标
    target_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="转发的目标 URL"
    )
    
    # 会话 ID
    session_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Agent 会话 ID"
    )

    # 项目信息（新增）
    project_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="使用的项目 ID"
    )

    project_name: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="项目名称（用于显示）"
    )

    # 响应信息
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        comment="状态: pending/success/error/timeout"
    )
    
    response: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Agent 响应内容"
    )
    
    error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="错误信息"
    )
    
    # 性能数据
    duration_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="请求耗时（毫秒）"
    )
    
    # 索引
    __table_args__ = (
        Index("idx_forward_logs_timestamp", "timestamp"),
        Index("idx_forward_logs_chat_id", "chat_id"),
        Index("idx_forward_logs_bot_key", "bot_key"),
        Index("idx_forward_logs_status", "status"),
    )
    
    def __repr__(self) -> str:
        return f"<ForwardLog(id={self.id}, chat_id={self.chat_id}, status={self.status})>"
    
    def to_dict(self) -> dict:
        """转换为字典 (用于 API 返回)"""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "chat_id": self.chat_id,
            "from_user": self.from_user_name or self.from_user_id,
            "content": self.content,
            "msg_type": self.msg_type,
            "bot_key": self.bot_key,
            "bot_name": self.bot_name,
            "target_url": self.target_url,
            "session_id": self.session_id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "status": self.status,
            "response": self.response,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


# ============== 会话处理状态模型 ==============

class ProcessingSession(Base):
    """
    正在处理中的会话记录
    
    用于防止同一会话并发发送多个请求到 Agent Studio
    当一个会话正在处理时，新的请求会被拒绝
    
    注意：这个表用于跨进程共享状态，所有 worker 进程都可以访问
    """
    __tablename__ = "processing_sessions"
    
    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # 会话标识 (唯一)
    session_key: Mapped[str] = mapped_column(
        String(500),
        unique=True,
        nullable=False,
        index=True,
        comment="会话唯一标识: user_id:chat_id:bot_key"
    )
    
    # 用户信息
    user_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="用户 ID"
    )
    
    chat_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Chat ID"
    )
    
    bot_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Bot Key"
    )
    
    # 正在处理的消息
    message: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="正在处理的消息内容 (截断)"
    )
    
    # 开始时间
    started_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="处理开始时间"
    )
    
    def __repr__(self) -> str:
        return f"<ProcessingSession(session_key={self.session_key[:30]}...)>"
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "session_key": self.session_key,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "bot_key": self.bot_key,
            "message": self.message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
        }


# ============== Chat 信息模型 ==============

class ChatInfo(Base):
    """
    Chat 信息表
    
    存储 chat_id 和 chat_type 的对应关系：
    - 首次收到某 chat_id 的回调时自动记录
    - 用于在发送消息时判断目标类型（群聊/私聊）
    - 不同 chat_type 有不同的消息条数限制
    """
    __tablename__ = "chat_info"
    
    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Chat ID (唯一)
    chat_id: Mapped[str] = mapped_column(
        String(200),
        unique=True,
        nullable=False,
        index=True,
        comment="Chat ID (群ID或私聊ID)"
    )
    
    # Chat 类型
    chat_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="group",
        comment="Chat 类型: group (群聊) / single (私聊)"
    )
    
    # Chat 名称（可选，用于显示）
    chat_name: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="Chat 名称（群名/用户名）"
    )
    
    # 关联的 Bot Key（首次收到消息的 Bot）
    first_bot_key: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="首次收到消息的 Bot Key"
    )
    
    # 消息计数
    message_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="收到的消息总数"
    )
    
    # 时间戳
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="首次收到消息的时间"
    )
    
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="最后收到消息的时间"
    )
    
    # 索引
    __table_args__ = (
        Index("idx_chat_info_chat_id", "chat_id"),
        Index("idx_chat_info_chat_type", "chat_type"),
        Index("idx_chat_info_last_seen", "last_seen_at"),
    )
    
    def __repr__(self) -> str:
        return f"<ChatInfo(chat_id={self.chat_id[:20]}..., type={self.chat_type})>"
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "chat_type": self.chat_type,
            "chat_name": self.chat_name,
            "first_bot_key": self.first_bot_key,
            "message_count": self.message_count,
            "first_seen_at": self.first_seen_at.isoformat() if self.first_seen_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
        }
    
    @property
    def is_group(self) -> bool:
        """是否为群聊"""
        return self.chat_type == "group"
    
    @property
    def is_single(self) -> bool:
        """是否为私聊"""
        return self.chat_type == "single"


# ============== 系统配置模型 ==============

class SystemConfig(Base):
    """
    系统配置表
    
    存储全局配置项，如管理员用户列表
    使用 key-value 形式存储
    """
    __tablename__ = "system_config"
    
    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # 配置键（唯一）
    key: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="配置键"
    )
    
    # 配置值（JSON 格式）
    value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="配置值 (JSON 格式)"
    )
    
    # 描述
    description: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="配置描述"
    )
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="创建时间"
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="更新时间"
    )
    
    def __repr__(self) -> str:
        return f"<SystemConfig(key={self.key})>"
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "key": self.key,
            "value": self.value,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
