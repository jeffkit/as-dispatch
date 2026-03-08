"""
Admin API 鉴权模块

使用 AS_ADMIN_KEY 环境变量保护 /admin/* 路由。
Header 名称 X-Admin-Key 与 as-enterprise ConfigSyncService 保持一致。

向后兼容策略：
- 未设置 AS_ADMIN_KEY 时：跳过鉴权（内网部署兼容，与旧版行为一致）
- 已设置 AS_ADMIN_KEY 时：强制校验 X-Admin-Key 请求头

使用方式（FastAPI Depends）：
    AdminAuth = Annotated[None, Depends(require_admin_key)]

    @router.get("")
    async def my_route(_auth: AdminAuth) -> dict:
        ...
"""
import os
import logging
from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)

# 从环境变量读取（对齐 as-enterprise 的 AS_ADMIN_API_KEY 命名规范）
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

    - 未配置 AS_ADMIN_KEY 环境变量时 → 跳过鉴权（向后兼容，内网模式）
    - 已配置且 Key 不匹配 → 401 Unauthorized
    """
    if not _ADMIN_KEY:
        # 内网/未配置模式：跳过鉴权，与旧版行为一致
        return

    if x_admin_key != _ADMIN_KEY:
        logger.warning("Admin API 鉴权失败（key 不匹配）")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 X-Admin-Key",
        )
