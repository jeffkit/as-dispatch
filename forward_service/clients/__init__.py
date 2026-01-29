"""
Platform-specific clients

This package contains client implementations for different IM platforms:
- slack: Slack client
- wecom_intelligent: 企微智能机器人客户端
"""
from .slack import SlackClient

__all__ = ["SlackClient"]
