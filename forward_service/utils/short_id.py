"""
出站消息短 ID 生成工具

生成 `ob_xxxxxx` 格式的 outbound short_id，用于消息路由头标识。
- 前缀 `ob_` 与 HITL session short_id（纯十六进制）区分
- 6 位 hex 随机后缀，约 16M 命名空间，7 天窗口内碰撞概率极低
"""
import logging
import secrets
from typing import Callable, Awaitable, Optional

logger = logging.getLogger(__name__)

OB_PREFIX = "ob_"
OB_HEX_LENGTH = 3  # secrets.token_hex(3) → 6 hex chars


def generate_outbound_short_id() -> str:
    """生成一个 outbound short_id: `ob_` + 6 位十六进制随机字符"""
    return f"{OB_PREFIX}{secrets.token_hex(OB_HEX_LENGTH)}"


async def generate_unique_outbound_short_id(
    exists_checker: Optional[Callable[[str], Awaitable[bool]]] = None,
    max_retries: int = 5,
) -> str:
    """
    生成唯一的 outbound short_id，通过回调验证唯一性。

    Args:
        exists_checker: 异步回调，接收 short_id 返回是否已存在
        max_retries: 最大重试次数（碰撞时重新生成）

    Returns:
        唯一的 outbound short_id

    Raises:
        RuntimeError: 超过最大重试次数仍无法生成唯一 ID
    """
    for attempt in range(max_retries):
        short_id = generate_outbound_short_id()

        if exists_checker is None:
            return short_id

        if not await exists_checker(short_id):
            return short_id

        logger.warning(f"outbound short_id 碰撞，重试: attempt={attempt + 1}, id={short_id}")

    raise RuntimeError(
        f"无法在 {max_retries} 次尝试内生成唯一的 outbound short_id"
    )
