"""
Channel 基础类型和适配器抽象基类

定义：
- InboundMessage: 统一入站消息格式
- OutboundMessage: 统一出站消息格式
- SendResult: 发送结果
- ChannelAdapter: 通道适配器抽象基类
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ============== 统一消息格式 ==============


@dataclass
class InboundMessage:
    """
    统一入站消息格式

    各平台适配器将平台原始数据解析为此格式，
    核心处理管线只依赖此结构，不感知平台细节。
    """

    # 平台标识
    platform: str
    """平台类型: wecom / discord / telegram / lark"""

    # Bot 标识
    bot_key: str
    """平台特定的 Bot 标识（企微的 webhook key、Discord 的 bot id 等）"""

    # 发送者信息
    user_id: str
    """发送者 ID"""

    user_name: str
    """发送者显示名称"""

    user_alias: str = ""
    """发送者别名（可选，用于访问控制匹配）"""

    # 会话信息
    chat_id: str = ""
    """会话/群 ID"""

    chat_type: str = "group"
    """会话类型: group / direct"""

    # 消息内容
    text: str = ""
    """消息文本（已清洗：去除引用、去除 @bot 前缀）"""

    images: list[str] = field(default_factory=list)
    """图片 URL 列表"""

    msg_type: str = "text"
    """原始消息类型（text / image / mixed 等）"""

    # 引用回复
    quoted_short_id: Optional[str] = None
    """从引用消息中提取的会话短 ID（用于跨会话回复）"""

    # 去重
    message_id: str = ""
    """原始消息 ID（用于去重）"""

    # 原始数据
    raw_data: dict = field(default_factory=dict)
    """平台原始回调数据（保留以备扩展）"""


@dataclass
class OutboundMessage:
    """
    统一出站消息格式

    核心处理管线生成此结构，各平台适配器将其转换为平台特定格式发送。
    """

    # 目标
    chat_id: str
    """目标会话/群 ID"""

    # 消息内容
    text: str
    """消息文本"""

    msg_type: str = "text"
    """消息类型: text / markdown"""

    # Bot 标识
    bot_key: str = ""
    """使用哪个 Bot 发送"""

    # 会话标识（用于消息头部）
    short_id: Optional[str] = None
    """会话短 ID"""

    project_name: Optional[str] = None
    """项目名称"""

    # 交互
    mentioned_user_ids: Optional[list[str]] = None
    """需要 @ 提醒的用户 ID 列表（群聊场景）"""

    # 平台特定扩展
    extra: dict = field(default_factory=dict)
    """平台特定的扩展数据（如 Discord Embed、飞书卡片等）"""


# ============== 发送结果 ==============


@dataclass
class SendResult:
    """发送结果"""

    success: bool
    """是否发送成功"""

    parts_sent: int = 0
    """发送的消息条数（分拆后）"""

    error: Optional[str] = None
    """错误信息"""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "parts_sent": self.parts_sent,
            "error": self.error,
        }


# ============== 通道适配器基类 ==============


class ChannelAdapter(ABC):
    """
    通道适配器抽象基类

    每个 IM 平台实现此接口，负责：
    1. parse_inbound: 将平台原始数据解析为 InboundMessage
    2. send_outbound: 将 OutboundMessage 转换为平台特定格式并发送
    3. extract_bot_key: 从原始请求中提取 Bot 标识

    核心处理管线不感知平台细节，只通过此接口与平台交互。
    """

    @property
    @abstractmethod
    def platform(self) -> str:
        """平台标识，如 'wecom', 'discord', 'telegram', 'lark'"""
        ...

    @property
    def max_message_bytes(self) -> int:
        """平台消息最大字节数限制（子类可覆盖）"""
        return 2048

    @abstractmethod
    async def parse_inbound(self, raw_data: dict, **kwargs: Any) -> InboundMessage:
        """
        将平台原始回调数据解析为统一的 InboundMessage

        Args:
            raw_data: 平台回调的原始 JSON 数据
            **kwargs: 额外参数（如 HTTP headers）

        Returns:
            解析后的 InboundMessage

        Raises:
            ValueError: 无法解析消息时
        """
        ...

    @abstractmethod
    async def send_outbound(self, message: OutboundMessage) -> SendResult:
        """
        将 OutboundMessage 转换为平台特定格式并发送

        需要处理：
        - 消息格式化（添加会话标识头部等）
        - 消息分拆（超过平台限制时）
        - @ 提醒（群聊场景）
        - 平台特定的富消息格式（Embed、卡片等）

        Args:
            message: 统一出站消息

        Returns:
            发送结果
        """
        ...

    @abstractmethod
    def extract_bot_key(self, raw_data: dict, **kwargs: Any) -> Optional[str]:
        """
        从原始请求数据中提取 Bot 标识

        不同平台的 Bot 标识来源不同：
        - 企微: webhook_url 中的 ?key=xxx 参数
        - Discord: Bot application ID
        - Telegram: Bot token (from URL path)
        - 飞书: App ID

        Args:
            raw_data: 平台回调的原始数据
            **kwargs: 额外参数

        Returns:
            Bot 标识，如果无法提取返回 None
        """
        ...

    def should_ignore(self, raw_data: dict) -> bool:
        """
        判断是否应该忽略此消息（如事件通知、心跳等）

        默认不忽略任何消息，子类可覆盖。

        Args:
            raw_data: 平台回调的原始数据

        Returns:
            True 表示应该忽略
        """
        return False
