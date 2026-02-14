"""
Forward Service 配置管理 - 数据库版本

与 config_v2.py 接口完全兼容,但使用数据库存储而不是 JSON 文件。

主要差异:
- 配置存储在数据库中,而不是 JSON 文件
- 支持动态更新,无需重启服务
- 与 config_v2.py 接口兼容,可以无缝切换

使用方式:
    # 使用数据库配置
    from forward_service.config_db import ConfigDB
    config = ConfigDB()
"""
import logging
import re
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .database import get_db_manager
from .models import Chatbot
from .repository import get_chatbot_repository, get_access_rule_repository

logger = logging.getLogger(__name__)

# 默认超时时间（秒）- 用户项目和 Bot 共用
DEFAULT_TIMEOUT = 300  # 5 分钟


# ============== 数据类定义 (与 config_v2 兼容) ==============

class ForwardConfig:
    """转发配置"""
    def __init__(
        self,
        target_url: str,
        api_key: str = "",
        timeout: int = DEFAULT_TIMEOUT
    ):
        self.target_url = target_url
        self.api_key = api_key
        self.timeout = timeout

    def to_dict(self) -> dict:
        return {
            "target_url": self.target_url,
            "api_key": self.api_key,
            "timeout": self.timeout
        }
    
    def get_url(self) -> str:
        """获取目标 URL（直接返回，不再需要模板替换）"""
        return self.target_url

    @classmethod
    def from_bot(cls, bot: Chatbot) -> "ForwardConfig":
        """从 Chatbot 模型创建 ForwardConfig"""
        # 优先使用 target_url，如果没有则从旧的 url_template + agent_id 构建
        if hasattr(bot, 'target_url') and bot.target_url:
            url = bot.target_url
        elif hasattr(bot, 'url_template') and bot.url_template:
            # 兼容旧数据：用 agent_id 替换模板
            url = bot.url_template.replace("{agent_id}", bot.agent_id or "")
        else:
            url = ""
        
        return cls(
            target_url=url,
            api_key=bot.api_key or "",
            timeout=bot.timeout
        )


class AccessControl:
    """访问控制配置 (与 config_v2.AccessControl 兼容)"""
    def __init__(
        self,
        mode: str = "allow_all",
        whitelist: list[str] | None = None,
        blacklist: list[str] | None = None
    ):
        self.mode = mode
        self.whitelist = whitelist or []
        self.blacklist = blacklist or []

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "whitelist": self.whitelist,
            "blacklist": self.blacklist
        }

    @classmethod
    def from_bot(cls, bot: Chatbot) -> "AccessControl":
        """从 Chatbot 模型创建 AccessControl (需要预加载 access_rules)"""
        whitelist = []
        blacklist = []

        for rule in bot.access_rules:
            if rule.rule_type == "whitelist":
                whitelist.append(rule.chat_id)
            elif rule.rule_type == "blacklist":
                blacklist.append(rule.chat_id)

        return cls(
            mode=bot.access_mode,
            whitelist=whitelist,
            blacklist=blacklist
        )

    def check_access(self, user_id: str, chat_id: str | None = None, alias: str | None = None) -> tuple[bool, str]:
        """
        检查用户是否有权限访问
        
        黑白名单支持三种格式：
        - user_id: 匹配特定用户 ID (如 T15500028A)
        - chat_id: 匹配特定群聊/会话 ID
        - alias: 匹配用户别名 (如 kongjie)
        
        只要 user_id、chat_id 或 alias 匹配其一即可
        """
        if self.mode == "allow_all":
            return True, ""

        elif self.mode == "whitelist":
            # 检查 user_id、chat_id 或 alias 是否在白名单中
            if user_id in self.whitelist:
                return True, ""
            if chat_id and chat_id in self.whitelist:
                return True, ""
            if alias and alias in self.whitelist:
                return True, ""
            return False, "抱歉，您还没有权限访问此 Bot，如有意向，请联系作者。"

        elif self.mode == "blacklist":
            # 检查 user_id、chat_id 或 alias 是否在黑名单中
            deny_msg = "抱歉，您还没有权限访问此 Bot，如有意向，请联系作者。"
            if user_id in self.blacklist:
                return False, deny_msg
            if chat_id and chat_id in self.blacklist:
                return False, deny_msg
            if alias and alias in self.blacklist:
                return False, deny_msg
            return True, ""

        return False, "未知的访问控制模式"


class BotConfig:
    """Bot 配置 (与 config_v2.BotConfig 兼容)"""
    def __init__(
        self,
        bot_key: str,
        name: str = "未命名 Bot",
        description: str = "",
        forward_config: ForwardConfig | None = None,
        access_control: AccessControl | None = None,
        enabled: bool = True,
        owner_id: str | None = None,
        _bot: Chatbot | None = None  # 内部使用,保留对数据库模型的引用
    ):
        self.bot_key = bot_key
        self.name = name
        self.description = description
        self.forward_config = forward_config or ForwardConfig(target_url="")
        self.access_control = access_control or AccessControl()
        self.enabled = enabled
        self.owner_id = owner_id
        self._bot = _bot  # 保留数据库模型引用

    @property
    def is_registered(self) -> bool:
        """Bot 是否已注册（有 owner）"""
        return self.owner_id is not None

    @property
    def is_configured(self) -> bool:
        """Bot 是否已配置转发目标"""
        return bool(self.forward_config and self.forward_config.get_url())

    def to_dict(self) -> dict:
        return {
            "bot_key": self.bot_key,
            "name": self.name,
            "description": self.description,
            "forward_config": self.forward_config.to_dict(),
            "access_control": self.access_control.to_dict(),
            "enabled": self.enabled,
            "owner_id": self.owner_id
        }

    @classmethod
    def from_bot(cls, bot: Chatbot) -> "BotConfig":
        """从 Chatbot 数据库模型创建 BotConfig"""
        return cls(
            bot_key=bot.bot_key,
            name=bot.name,
            description=bot.description or "",
            forward_config=ForwardConfig.from_bot(bot),
            access_control=AccessControl.from_bot(bot),
            enabled=bot.enabled,
            owner_id=bot.owner_id,
            _bot=bot  # 保留数据库模型引用
        )


# ============== 数据库配置类 ==============

class ConfigDB:
    """
    数据库配置类 (与 ConfigV2 接口兼容)

    从数据库加载配置,而不是 JSON 文件。

    环境变量:
        DATABASE_URL: 数据库连接 URL
        DEFAULT_BOT_KEY: 默认 Bot Key
    """

    def __init__(self):
        """初始化配置"""
        self.default_bot_key: str = ""
        self.bots: dict[str, BotConfig] = {}
        self.port: int = 8083
        self.timeout: int = DEFAULT_TIMEOUT
        self.callback_auth_key: str = ""
        self.callback_auth_value: str = ""

    async def initialize(self):
        """初始化配置 - 从数据库加载"""
        import os

        # 从环境变量加载基本配置
        if os.getenv("FORWARD_PORT"):
            self.port = int(os.getenv("FORWARD_PORT"))
        if os.getenv("FORWARD_TIMEOUT"):
            self.timeout = int(os.getenv("FORWARD_TIMEOUT"))
        self.callback_auth_key = os.getenv("CALLBACK_AUTH_KEY", "")
        self.callback_auth_value = os.getenv("CALLBACK_AUTH_VALUE", "")

        # 设置默认 bot_key
        self.default_bot_key = os.getenv("DEFAULT_BOT_KEY", "")

        # 从数据库加载所有 Bot 配置
        await self._load_bots_from_db()

        logger.info(f"从数据库加载了 {len(self.bots)} 个 Bot 配置")
        logger.info(f"默认 Bot Key: {self.default_bot_key}")

    async def _load_bots_from_db(self):
        """从数据库加载所有 Bot 配置"""
        db = get_db_manager()

        async with db.get_session() as session:
            bot_repo = get_chatbot_repository(session)

            # 获取所有 Bot (包括已禁用的)
            bots = await bot_repo.get_all(enabled_only=False)

            # 转换为 BotConfig 对象
            for bot in bots:
                # 预加载 access_rules
                await session.refresh(bot, attribute_names=["access_rules"])

                bot_config = BotConfig.from_bot(bot)
                self.bots[bot.bot_key] = bot_config

                # 设置默认 bot_key (如果还没设置)
                if not self.default_bot_key and bot.enabled:
                    self.default_bot_key = bot.bot_key

    def extract_bot_key_from_webhook_url(self, webhook_url: str) -> Optional[str]:
        """从 webhook_url 提取 bot_key"""
        match = re.search(r'[?&]key=([^&]+)', webhook_url)
        if match:
            return match.group(1)
        return None

    def get_bot(self, bot_key: str) -> Optional[BotConfig]:
        """根据 bot_key 获取 Bot 配置"""
        return self.bots.get(bot_key)

    def get_bot_or_default(self, bot_key: str | None) -> Optional[BotConfig]:
        """获取 Bot 配置，如果找不到则返回默认 Bot"""
        if bot_key and bot_key in self.bots:
            return self.bots[bot_key]

        # 回退到默认 Bot
        if self.default_bot_key and self.default_bot_key in self.bots:
            logger.info(f"Bot {bot_key} 不存在，使用默认 Bot: {self.default_bot_key}")
            return self.bots[self.default_bot_key]

        return None

    def check_access(self, bot: BotConfig, user_id: str, chat_id: str | None = None, alias: str | None = None) -> tuple[bool, str]:
        """
        检查用户是否有权限访问 Bot
        
        Args:
            bot: Bot 配置
            user_id: 用户 ID
            chat_id: 群聊/会话 ID (可选)
            alias: 用户别名 (可选)
        
        Returns:
            (是否允许, 拒绝原因)
        """
        if not bot.enabled:
            return False, "Bot 已禁用"

        return bot.access_control.check_access(user_id, chat_id, alias)

    async def reload_config(self) -> dict:
        """重新加载配置 (从数据库)"""
        try:
            self.bots.clear()
            await self._load_bots_from_db()
            return {"success": True, "message": "配置已重新加载"}
        except Exception as e:
            logger.error(f"重新加载配置失败: {e}")
            return {"success": False, "error": str(e)}

    def get_all_bots(self) -> dict[str, dict]:
        """获取所有 Bot 配置（用于管理台）"""
        return {
            bot_key: bot.to_dict()
            for bot_key, bot in self.bots.items()
        }

    def get_config_dict(self) -> dict:
        """获取完整配置（JSON 格式）"""
        return {
            "default_bot_key": self.default_bot_key,
            "bots": self.get_all_bots()
        }

    async def update_from_dict(self, data: dict) -> dict:
        """
        从字典更新配置 (写入数据库)

        注意: 这是全量更新,会覆盖现有配置
        """
        try:
            # 验证格式
            if "default_bot_key" not in data or "bots" not in data:
                return {"success": False, "error": "配置格式错误：缺少 default_bot_key 或 bots"}

            db = get_db_manager()

            async with db.get_session() as session:
                bot_repo = get_chatbot_repository(session)
                rule_repo = get_access_rule_repository(session)

                # 更新默认 bot_key
                self.default_bot_key = data["default_bot_key"]

                # 获取数据库中现有的所有 Bot
                existing_bots = await bot_repo.get_all(enabled_only=False)
                existing_bot_keys = {bot.bot_key for bot in existing_bots}
                new_bot_keys = set(data["bots"].keys())

                # 删除不再存在的 Bot
                bot_keys_to_delete = existing_bot_keys - new_bot_keys
                for bot_key in bot_keys_to_delete:
                    bot = await bot_repo.get_by_bot_key(bot_key)
                    if bot:
                        await bot_repo.delete(bot.id)
                        logger.info(f"删除 Bot: {bot_key}")

                # 更新或创建 Bot
                for bot_key, bot_dict in data["bots"].items():
                    forward_config = bot_dict.get("forward_config", {})
                    access_control = bot_dict.get("access_control", {})

                    # 检查是否已存在
                    existing_bot = await bot_repo.get_by_bot_key(bot_key)

                    if existing_bot:
                        # 更新现有 Bot
                        await bot_repo.update(
                            bot_id=existing_bot.id,
                            name=bot_dict.get("name"),
                            description=bot_dict.get("description"),
                            url_template=forward_config.get("url_template"),
                            agent_id=forward_config.get("agent_id"),
                            api_key=forward_config.get("api_key"),
                            timeout=forward_config.get("timeout"),
                            access_mode=access_control.get("mode", "allow_all"),
                            enabled=bot_dict.get("enabled", True)
                        )

                        # 更新访问规则
                        whitelist = access_control.get("whitelist", [])
                        blacklist = access_control.get("blacklist", [])

                        if whitelist or blacklist:
                            # 清除旧规则并设置新规则
                            await rule_repo.delete_by_chatbot(existing_bot.id)

                            for chat_id in whitelist:
                                await rule_repo.create(existing_bot.id, chat_id, "whitelist")

                            for chat_id in blacklist:
                                await rule_repo.create(existing_bot.id, chat_id, "blacklist")

                        logger.info(f"更新 Bot: {bot_key}")
                    else:
                        # 创建新 Bot
                        bot = await bot_repo.create(
                            bot_key=bot_key,
                            name=bot_dict.get("name"),
                            description=bot_dict.get("description"),
                            url_template=forward_config.get("url_template"),
                            agent_id=forward_config.get("agent_id"),
                            api_key=forward_config.get("api_key"),
                            timeout=forward_config.get("timeout", DEFAULT_TIMEOUT),
                            access_mode=access_control.get("mode", "allow_all"),
                            enabled=bot_dict.get("enabled", True)
                        )

                        # 添加访问规则
                        whitelist = access_control.get("whitelist", [])
                        blacklist = access_control.get("blacklist", [])

                        for chat_id in whitelist:
                            await rule_repo.create(bot.id, chat_id, "whitelist")

                        for chat_id in blacklist:
                            await rule_repo.create(bot.id, chat_id, "blacklist")

                        logger.info(f"创建 Bot: {bot_key}")

            # 重新加载配置到内存
            await self.reload_config()

            return {"success": True, "message": "配置已更新"}

        except Exception as e:
            logger.error(f"更新配置失败: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def validate(self) -> list[str]:
        """验证配置"""
        errors = []

        if not self.bots:
            errors.append("至少需要配置一个 Bot")

        if self.default_bot_key and self.default_bot_key not in self.bots:
            errors.append(f"默认 Bot Key '{self.default_bot_key}' 不存在于 bots 配置中")

        for bot_key, bot in self.bots.items():
            # target_url 现在是可选的，用户可以通过绑定项目来指定转发目标
            # 所以不再强制验证 target_url
            pass

        return errors

    # ============== Bot CRUD 操作 (用于 API) ==============

    async def list_bots(self) -> list[dict]:
        """
        获取所有 Bot 列表

        Returns:
            Bot 列表，每个 Bot 包含统计信息
        """
        db = get_db_manager()

        async with db.get_session() as session:
            bot_repo = get_chatbot_repository(session)
            rule_repo = get_access_rule_repository(session)

            bots = await bot_repo.get_all(enabled_only=False)

            result = []
            for bot in bots:
                # 统计访问规则数量
                whitelist = await rule_repo.get_whitelist(bot.id)
                blacklist = await rule_repo.get_blacklist(bot.id)
                
                # 优先使用 target_url，兼容 url_template
                effective_url = bot.target_url or bot.url_template or ""

                result.append({
                    "id": bot.id,
                    "bot_key": bot.bot_key,
                    "name": bot.name,
                    "description": bot.description or "",
                    "url_template": effective_url,  # 前端兼容
                    "target_url": effective_url,    # 新字段
                    "agent_id": bot.agent_id or "",
                    "api_key": bot.api_key or "",
                    "timeout": bot.timeout,
                    "access_mode": bot.access_mode,
                    "enabled": bot.enabled,
                    "whitelist_count": len(whitelist),
                    "blacklist_count": len(blacklist),
                    "created_at": bot.created_at.isoformat() if bot.created_at else None,
                    "updated_at": bot.updated_at.isoformat() if bot.updated_at else None
                })

            return result

    async def get_bot_detail(self, bot_key: str) -> dict | None:
        """
        获取单个 Bot 详情（从数据库）

        Args:
            bot_key: Bot Key

        Returns:
            Bot 详情字典，包含访问规则列表，如果不存在返回 None
        """
        db = get_db_manager()

        async with db.get_session() as session:
            bot_repo = get_chatbot_repository(session)
            rule_repo = get_access_rule_repository(session)

            bot = await bot_repo.get_by_bot_key(bot_key)
            if not bot:
                return None

            # 获取访问规则
            whitelist_rules = await rule_repo.get_by_chatbot(bot.id, "whitelist")
            blacklist_rules = await rule_repo.get_by_chatbot(bot.id, "blacklist")

            # 优先使用 target_url，兼容 url_template
            effective_url = bot.target_url or bot.url_template or ""
            
            return {
                "id": bot.id,
                "bot_key": bot.bot_key,
                "name": bot.name,
                "description": bot.description or "",
                "url_template": effective_url,  # 前端兼容
                "target_url": effective_url,    # 新字段
                "agent_id": bot.agent_id or "",
                "api_key": bot.api_key or "",
                "timeout": bot.timeout,
                "access_mode": bot.access_mode,
                "enabled": bot.enabled,
                "created_at": bot.created_at.isoformat() if bot.created_at else None,
                "updated_at": bot.updated_at.isoformat() if bot.updated_at else None,
                "whitelist": [
                    {
                        "id": rule.id,
                        "chat_id": rule.chat_id,
                        "remark": rule.remark or ""
                    }
                    for rule in whitelist_rules
                ],
                "blacklist": [
                    {
                        "id": rule.id,
                        "chat_id": rule.chat_id,
                        "remark": rule.remark or ""
                    }
                    for rule in blacklist_rules
                ]
            }

    async def get_bot_or_default_from_db(self, bot_key: str | None) -> Optional[BotConfig]:
        """
        从数据库获取 Bot 配置，如果指定的 bot_key 不存在，返回默认 Bot

        Args:
            bot_key: Bot Key，可以为 None

        Returns:
            BotConfig 对象，如果都不存在返回 None
        """
        db = get_db_manager()

        async with db.get_session() as session:
            bot_repo = get_chatbot_repository(session)

            # 1. 尝试获取指定的 bot
            if bot_key:
                bot = await bot_repo.get_by_bot_key(bot_key)
                if bot and bot.enabled:
                    return BotConfig(
                        bot_key=bot.bot_key,
                        name=bot.name,
                        description=bot.description or "",
                        forward_config=ForwardConfig(
                            target_url=bot.get_url(),
                            api_key=bot.api_key or "",
                            timeout=bot.timeout
                        ),
                        enabled=bot.enabled
                    )

            # 2. 尝试获取默认 bot
            if self.default_bot_key:
                default_bot = await bot_repo.get_by_bot_key(self.default_bot_key)
                if default_bot and default_bot.enabled:
                    return BotConfig(
                        bot_key=default_bot.bot_key,
                        name=default_bot.name,
                        description=default_bot.description or "",
                        forward_config=ForwardConfig(
                            target_url=default_bot.get_url(),
                            api_key=default_bot.api_key or "",
                            timeout=default_bot.timeout
                        ),
                        enabled=default_bot.enabled
                    )

            return None

    async def create_bot(self, data: dict) -> dict:
        """
        创建新 Bot

        Args:
            data: Bot 配置字典

        Returns:
            {"success": bool, "bot": dict, "error": str}
        """
        try:
            # 验证必填字段（target_url 可选，用户可以通过绑定项目来指定）
            required_fields = ["bot_key", "name"]
            missing = [f for f in required_fields if not data.get(f)]
            if missing:
                return {"success": False, "error": f"缺少必填字段: {', '.join(missing)}"}

            db = get_db_manager()

            async with db.get_session() as session:
                bot_repo = get_chatbot_repository(session)
                rule_repo = get_access_rule_repository(session)

                # 检查 bot_key 是否已存在
                existing = await bot_repo.get_by_bot_key(data["bot_key"])
                if existing:
                    return {"success": False, "error": f"Bot Key '{data['bot_key']}' 已存在"}

                # 创建 Bot（target_url 可选）
                bot = await bot_repo.create(
                    bot_key=data["bot_key"],
                    name=data["name"],
                    url_template=data.get("target_url", ""),  # 可选，用户可通过绑定项目指定
                    api_key=data.get("api_key", ""),
                    timeout=data.get("timeout", DEFAULT_TIMEOUT),
                    access_mode=data.get("access_mode", "allow_all"),
                    description=data.get("description", ""),
                    enabled=data.get("enabled", True),
                    platform=data.get("platform", "wecom")
                )

                # 创建访问规则
                whitelist = data.get("whitelist", [])
                blacklist = data.get("blacklist", [])

                for chat_id in whitelist:
                    await rule_repo.create(bot.id, chat_id, "whitelist",
                                          remark=data.get("whitelist_remark", ""))

                for chat_id in blacklist:
                    await rule_repo.create(bot.id, chat_id, "blacklist",
                                          remark=data.get("blacklist_remark", ""))

                await session.commit()

                logger.info(f"创建 Bot 成功: {data['bot_key']}")

                # 刷新内存缓存，确保新创建的 Bot 立即可用于消息路由
                await self.reload_config()

                # 返回创建的 Bot 详情（使用异步方法从数据库获取）
                created_bot = await self.get_bot_detail(data["bot_key"])
                return {"success": True, "bot": created_bot}

        except Exception as e:
            logger.error(f"创建 Bot 失败: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def update_bot(self, bot_key: str, data: dict) -> dict:
        """
        更新 Bot 配置

        Args:
            bot_key: Bot Key
            data: 更新数据字典

        Returns:
            {"success": bool, "bot": dict, "error": str}
        """
        try:
            db = get_db_manager()

            async with db.get_session() as session:
                bot_repo = get_chatbot_repository(session)
                rule_repo = get_access_rule_repository(session)

                # 检查 Bot 是否存在
                bot = await bot_repo.get_by_bot_key(bot_key)
                if not bot:
                    return {"success": False, "error": f"Bot '{bot_key}' 不存在"}

                # 更新 Bot 基本信息
                # 优先使用 target_url，兼容 url_template
                target_url = data.get("target_url") or data.get("url_template")
                await bot_repo.update(
                    bot_id=bot.id,
                    name=data.get("name"),
                    description=data.get("description"),
                    target_url=target_url,
                    api_key=data.get("api_key"),
                    timeout=data.get("timeout"),
                    access_mode=data.get("access_mode"),
                    enabled=data.get("enabled")
                )

                # 更新访问规则 (如果提供)
                if "whitelist" in data or "blacklist" in data:
                    # 清除现有规则
                    await rule_repo.delete_by_chatbot(bot.id)

                    # 创建新规则
                    whitelist = data.get("whitelist", [])
                    blacklist = data.get("blacklist", [])

                    for chat_id in whitelist:
                        await rule_repo.create(bot.id, chat_id, "whitelist")

                    for chat_id in blacklist:
                        await rule_repo.create(bot.id, chat_id, "blacklist")

                await session.commit()

                logger.info(f"更新 Bot 成功: {bot_key}")

                # 重新加载配置到内存
                await self.reload_config()

                # 返回更新后的 Bot 详情
                updated_bot = await self.get_bot_detail(bot_key)
                return {"success": True, "bot": updated_bot}

        except Exception as e:
            logger.error(f"更新 Bot 失败: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def delete_bot(self, bot_key: str) -> dict:
        """
        删除 Bot

        Args:
            bot_key: Bot Key

        Returns:
            {"success": bool, "error": str}
        """
        try:
            db = get_db_manager()

            async with db.get_session() as session:
                bot_repo = get_chatbot_repository(session)

                # 检查 Bot 是否存在
                bot = await bot_repo.get_by_bot_key(bot_key)
                if not bot:
                    return {"success": False, "error": f"Bot '{bot_key}' 不存在"}

                # 删除 Bot (会级联删除 access_rules)
                success = await bot_repo.delete(bot.id)

                if not success:
                    return {"success": False, "error": "删除失败"}

                await session.commit()

                logger.info(f"删除 Bot 成功: {bot_key}")

                # 重新加载配置到内存
                await self.reload_config()

                return {"success": True}

        except Exception as e:
            logger.error(f"删除 Bot 失败: {e}", exc_info=True)
            return {"success": False, "error": str(e)}


# ============== 全局配置实例 ==============

config = ConfigDB()
