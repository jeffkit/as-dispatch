"""
Platform-specific clients

This package contains client implementations for different IM platforms:
- wecom_intelligent: 企微智能机器人客户端
- slack: Slack 客户端
- discord: Discord 客户端
"""
from .slack import SlackClient

__all__ = ["SlackClient"]
