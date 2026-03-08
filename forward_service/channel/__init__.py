"""
Channel 模块 - 多平台通道适配层

提供统一的消息格式（InboundMessage / OutboundMessage）和适配器接口（ChannelAdapter），
使核心处理管线不感知平台细节。

使用方式：
    from forward_service.channel import InboundMessage, OutboundMessage, ChannelAdapter
    from forward_service.channel import get_adapter, register_adapter, list_adapters

平台适配器：
    from forward_service.channel import WeComAdapter
    from forward_service.channel import TelegramAdapter
    from forward_service.channel import LarkAdapter
    from forward_service.channel import DiscordAdapter
    from forward_service.channel import SlackAdapter
"""

from .base import InboundMessage, OutboundMessage, ChannelAdapter, SendResult
from .registry import get_adapter, register_adapter, list_adapters
from .wecom import WeComAdapter
from .telegram import TelegramAdapter
from .lark import LarkAdapter
from .discord import DiscordAdapter
from .slack import SlackAdapter

__all__ = [
    # 消息格式
    "InboundMessage",
    "OutboundMessage",
    "ChannelAdapter",
    "SendResult",
    # 注册表
    "get_adapter",
    "register_adapter",
    "list_adapters",
    # 适配器
    "WeComAdapter",
    "TelegramAdapter",
    "LarkAdapter",
    "DiscordAdapter",
    "SlackAdapter",
]
