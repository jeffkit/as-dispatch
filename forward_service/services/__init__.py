"""
服务模块
"""
from .forwarder import forward_to_agent_with_bot, forward_to_agent_with_user_project, AgentResult

__all__ = ["forward_to_agent_with_bot", "forward_to_agent_with_user_project", "AgentResult"]
