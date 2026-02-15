"""
路由模块
"""
from fastapi import APIRouter

from .admin import router as admin_router
from .bots import router as bots_router
from .callback import router as callback_router
from .slack import router as slack_router
from .tunnel_proxy import router as tunnel_proxy_router

__all__ = ["admin_router", "bots_router", "callback_router", "slack_router", "tunnel_proxy_router"]
