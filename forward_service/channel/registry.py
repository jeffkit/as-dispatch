"""
Channel 适配器注册表

管理所有已注册的平台适配器，通过 platform 名称查找适配器实例。
"""
import logging
from typing import Optional

from .base import ChannelAdapter

logger = logging.getLogger(__name__)

# 全局适配器注册表：platform -> adapter instance
_adapters: dict[str, ChannelAdapter] = {}


def register_adapter(adapter: ChannelAdapter) -> None:
    """
    注册一个通道适配器

    Args:
        adapter: 适配器实例
    """
    platform = adapter.platform
    if platform in _adapters:
        logger.warning(f"覆盖已注册的适配器: {platform}")
    _adapters[platform] = adapter
    logger.info(f"注册通道适配器: {platform}")


def get_adapter(platform: str) -> Optional[ChannelAdapter]:
    """
    根据平台名称获取适配器

    Args:
        platform: 平台标识 (wecom / discord / telegram / lark)

    Returns:
        适配器实例，如果未注册返回 None
    """
    return _adapters.get(platform)


def list_adapters() -> dict[str, ChannelAdapter]:
    """
    获取所有已注册的适配器

    Returns:
        platform -> adapter 的字典
    """
    return dict(_adapters)
