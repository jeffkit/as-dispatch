"""
路由模块
"""
from fastapi import APIRouter

from .admin import router as admin_router
from .bots import router as bots_router
from .callback import router as callback_router
from .intelligent import router as intelligent_router

__all__ = ["admin_router", "bots_router", "callback_router", "intelligent_router"]
