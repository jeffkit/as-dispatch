"""
路由模块
"""
from fastapi import APIRouter

from .admin import router as admin_router
from .bots import router as bots_router
from .bots_api import router as bots_api_router
from .callback import router as callback_router
from .unified_callback import router as unified_callback_router
from .intelligent import router as intelligent_router
from .outbound_context_api import router as outbound_context_router
from .slack import router as slack_router
from .telegram import router as telegram_router
from .lark import router as lark_router
from .tunnel_proxy import router as tunnel_proxy_router
from .qqbot import router as qqbot_admin_router
from .weixin import router as weixin_admin_router

__all__ = [
    "admin_router",
    "bots_router",
    "bots_api_router",
    "callback_router",
    "unified_callback_router",
    "intelligent_router",
    "outbound_context_router",
    "slack_router",
    "telegram_router",
    "lark_router",
    "tunnel_proxy_router",
    "qqbot_admin_router",
    "weixin_admin_router",
]
