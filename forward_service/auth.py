"""
鉴权模块

提供两套 FastAPI Depends 鉴权：

1. require_admin_key  —  X-Admin-Key 保护 /admin/* 路由（内部管理）
2. require_enterprise_jwt  —  Bearer JWT 保护 /api/* 路由（用户工具调用）

向后兼容策略：
- 未设置对应环境变量时：跳过鉴权（内网模式）
- 已设置且校验失败：401 Unauthorized
"""
import os
import logging
from fastapi import Header, HTTPException, Request, status

logger = logging.getLogger(__name__)

# ============================================================
# Admin Key 鉴权（/admin/* 路由）
# ============================================================

_ADMIN_KEY: str = os.getenv("AS_ADMIN_KEY", "")

if _ADMIN_KEY:
    logger.info("Admin API 鉴权已启用（AS_ADMIN_KEY 已配置）")
else:
    logger.warning("AS_ADMIN_KEY 未配置，Admin API 跳过鉴权（内网模式）")


def get_admin_key() -> str:
    """获取当前配置的 admin key（用于测试或调试）"""
    return _ADMIN_KEY


async def require_admin_key(
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
) -> None:
    """
    FastAPI Depends：校验 X-Admin-Key 请求头。

    - 未配置 AS_ADMIN_KEY 时 → 跳过鉴权（向后兼容，内网模式）
    - 已配置且 Key 不匹配 → 401 Unauthorized
    """
    if not _ADMIN_KEY:
        return

    if x_admin_key != _ADMIN_KEY:
        logger.warning("Admin API 鉴权失败（key 不匹配）")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 X-Admin-Key",
        )



# ============================================================
# Enterprise JWT 鉴权（/api/* 路由）
# ============================================================

_JWT_SECRET: str = os.getenv("JWT_SECRET_KEY", "")

if _JWT_SECRET:
    logger.info("Enterprise JWT 鉴权已启用（JWT_SECRET_KEY 已配置）")
else:
    logger.warning("JWT_SECRET_KEY 未配置，/api/* 端点跳过 JWT 鉴权（内网模式）")


async def require_enterprise_jwt(request: Request) -> dict:
    """
    FastAPI Depends：校验 Authorization: Bearer <enterprise_token>。

    - 未配置 JWT_SECRET_KEY 时 → 跳过鉴权，返回空 payload（内网模式）
    - 校验失败 → 401 Unauthorized
    """
    if not _JWT_SECRET:
        return {}

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要 Authorization: Bearer <as-enterprise-token>",
        )

    token = auth[7:]
    try:
        import jwt as pyjwt
        payload = pyjwt.decode(token, _JWT_SECRET, algorithms=["HS256"])
        return payload
    except Exception as exc:
        logger.warning("JWT 验证失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token 无效或已过期，请重新登录 as-enterprise ({exc})",
        )
