"""
as-dispatch MCP Server

为 AgentStudio 提供隧道管理和企微 Bot 自助配置工具。

部署模式（推荐）：HTTP 模式，挂载到 as-dispatch FastAPI 主应用
  - 访问地址：http://<as-dispatch-host>/mcp
  - 鉴权：AS_ENTERPRISE_JWT_SECRET 已配置时，要求 Authorization: Bearer <as-enterprise-token>
  - 未配置 AS_ENTERPRISE_JWT_SECRET 时：跳过鉴权（内网/开发模式）

备用模式（本地调试）：stdio 模式
  AS_DISPATCH_URL=http://hitl.woa.com:8083 \\
      uv run python -m forward_service.mcp_server

环境变量（HTTP 模式）：
    AS_ENTERPRISE_JWT_SECRET  as-enterprise SECRET_KEY（同一个值），用于验证用户身份
                               未配置时跳过鉴权（内网模式）

环境变量（仅 stdio 模式需要）：
    AS_DISPATCH_URL  as-dispatch 服务地址（默认 http://localhost:8083）
"""

import logging
import os
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# ============================================================
# JWT 鉴权中间件
# ============================================================

class EnterpriseJWTMiddleware(BaseHTTPMiddleware):
    """
    验证 as-enterprise 颁发的 JWT Token。

    as-enterprise 使用 Django ninja_jwt（HS256），签名密钥为 SECRET_KEY。
    as-dispatch 配置相同的 AS_ENTERPRISE_JWT_SECRET 即可本地验证，无需回调。

    Token 载荷示例：
        {"token_type": "access", "user_id": 1, "jti": "...", "exp": ...}
    """

    def __init__(self, app, jwt_secret: str) -> None:
        super().__init__(app)
        self.jwt_secret = jwt_secret

    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(
                {"error": "需要企业身份认证，请提供 Authorization: Bearer <as-enterprise-token>"},
                status_code=401,
            )
        token = auth[7:]
        try:
            import jwt
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            request.state.enterprise_user = payload
        except Exception as exc:
            logger.warning("JWT 验证失败: %s", exc)
            return JSONResponse(
                {"error": f"Token 无效或已过期，请重新登录 as-enterprise ({exc})"},
                status_code=401,
            )
        return await call_next(request)


# ============================================================
# FastMCP Server
# ============================================================

mcp = FastMCP(
    name="as-dispatch",
    instructions=(
        "Tools for managing tunnels and WeCom bots in as-dispatch. "
        "Requires a valid as-enterprise JWT token (Authorization: Bearer <token>). "
        "Use tunnel tools to create/list/delete WebSocket tunnels for your local AgentStudio. "
        "Use wecom tools to register WeChat Work group bots pointing to your agents."
    ),
)


# ============================================================
# 内部调用辅助
# ============================================================

def _get_config():
    """获取 forward_service config（进程内 HTTP 模式）"""
    try:
        from .config import config
        return config
    except ImportError:
        return None


def _get_tunnel_server():
    """获取 tunely TunnelServer 实例（进程内 HTTP 模式）"""
    try:
        from .tunnel import get_tunnel_server
        return get_tunnel_server()
    except Exception:
        return None


async def _http_fallback(method: str, path: str, payload: dict | None = None) -> dict:
    """stdio 模式降级：直接调用 as-dispatch HTTP API（内网，无需 Admin Key）"""
    import httpx
    base_url = os.getenv("AS_DISPATCH_URL", "http://localhost:8083").rstrip("/")
    url = f"{base_url}{path}"

    async with httpx.AsyncClient(timeout=10) as client:
        if method == "GET":
            resp = await client.get(url)
        elif method == "POST":
            resp = await client.post(url, json=payload)
        elif method == "PUT":
            resp = await client.put(url, json=payload)
        elif method == "DELETE":
            resp = await client.delete(url)
        else:
            return {"success": False, "error": f"Unsupported method: {method}"}
        resp.raise_for_status()
        return resp.json()


# ============================================================
# 隧道管理工具
# ============================================================

@mcp.tool
async def create_tunnel(
    domain: str,
    name: str = "",
    description: str = "",
) -> dict:
    """
    创建 WebSocket 隧道，用于将 AgentStudio 本地服务暴露到 as-dispatch。

    Args:
        domain:      隧道域名（唯一标识，小写字母+数字+连字符，如 "my-agent"）
        name:        显示名称（可选）
        description: 描述（可选）

    Returns:
        {"domain": str, "token": str, "name": str}
        token 是连接隧道时需要的认证令牌，请妥善保存。
    """
    tunnel_server = _get_tunnel_server()
    if tunnel_server is not None:
        from tunely import CreateTunnelRequest
        req = CreateTunnelRequest(domain=domain, name=name, description=description)
        # 内部调用，传入 admin_api_key 绕过外部鉴权
        result = await tunnel_server._create_tunnel(req, tunnel_server.config.admin_api_key)
        return {"domain": result.domain, "token": result.token, "name": result.name or ""}

    data = await _http_fallback(
        "POST", "/api/tunnels",
        {"domain": domain, "name": name, "description": description},
    )
    return data


@mcp.tool
async def list_tunnels() -> dict:
    """
    列出所有已创建的隧道及其连接状态。

    Returns:
        {"tunnels": [...], "total": int}
        每条隧道包含 domain, name, connected, created_at 等字段。
    """
    tunnel_server = _get_tunnel_server()
    if tunnel_server is not None:
        tunnels = await tunnel_server._list_tunnels(tunnel_server.config.admin_api_key)
        items = [
            {
                "domain": t.domain,
                "name": t.name or "",
                "connected": t.connected,
                "enabled": t.enabled,
                "created_at": t.created_at,
                "total_requests": t.total_requests,
            }
            for t in tunnels
        ]
        return {"tunnels": items, "total": len(items)}

    data = await _http_fallback("GET", "/api/tunnels")
    return {"tunnels": data, "total": len(data) if isinstance(data, list) else 0}


@mcp.tool
async def get_tunnel(domain: str) -> dict:
    """
    查询指定隧道的详情和当前连接状态。

    Args:
        domain: 隧道域名

    Returns:
        隧道详情，包含连接状态、请求统计等。
    """
    tunnel_server = _get_tunnel_server()
    if tunnel_server is not None:
        t = await tunnel_server._get_tunnel(domain, tunnel_server.config.admin_api_key)
        return {
            "domain": t.domain,
            "name": t.name or "",
            "connected": t.connected,
            "enabled": t.enabled,
            "created_at": t.created_at,
            "total_requests": t.total_requests,
        }

    return await _http_fallback("GET", f"/api/tunnels/{domain}")


@mcp.tool
async def delete_tunnel(domain: str) -> dict:
    """
    删除隧道配置。

    Args:
        domain: 要删除的隧道域名

    Returns:
        {"success": bool, "domain": str}
    """
    tunnel_server = _get_tunnel_server()
    if tunnel_server is not None:
        return await tunnel_server._delete_tunnel(domain, tunnel_server.config.admin_api_key)

    return await _http_fallback("DELETE", f"/api/tunnels/{domain}")


# ============================================================
# 企微 Bot 管理工具
# ============================================================

@mcp.tool
async def create_wecom_bot(
    bot_key: str,
    name: str,
    target_url: str,
    api_key: str,
    owner_id: str,
    description: str = "",
    timeout: int = 300,
    access_mode: str = "allow_all",
) -> dict:
    """
    在 as-dispatch 注册企微群机器人，将企微消息转发到指定 AgentStudio Agent。

    Args:
        bot_key:     从企微机器人 Webhook URL 提取的 key（UUID 格式）
        name:        Bot 名称（如 "my-project-agent"）
        target_url:  AgentStudio A2A 端点 URL（已含 agentId）
        api_key:     AgentStudio A2A API Key（agt_proj_xxx_yyy），用于标识所有者
        owner_id:    创建者标识（如企业用户 ID 或 "meta-agent"）
        description: Bot 描述（可选）
        timeout:     转发超时秒数（默认 300）
        access_mode: 访问控制："allow_all" / "whitelist" / "blacklist"

    Returns:
        {"success": bool, "bot": {...}}
    """
    cfg = _get_config()
    payload: dict[str, Any] = {
        "bot_key": bot_key,
        "name": name,
        "target_url": target_url,
        "api_key": api_key,
        "owner_id": owner_id,
        "description": description,
        "timeout": timeout,
        "access_mode": access_mode,
        "enabled": True,
        "platform": "wecom",
    }

    if cfg is not None:
        return await cfg.create_bot(payload)

    return await _http_fallback("POST", "/admin/bots", payload)


@mcp.tool
async def get_wecom_bot(bot_key: str) -> dict:
    """
    查询企微 Bot 配置详情。

    Args:
        bot_key: 企微机器人的 key 值

    Returns:
        {"success": bool, "bot": {...}}
    """
    cfg = _get_config()
    if cfg is not None:
        bot = await cfg.get_bot_detail(bot_key)
        if not bot:
            return {"success": False, "error": f"Bot '{bot_key}' 不存在"}
        return {"success": True, "bot": bot}

    return await _http_fallback("GET", f"/admin/bots/{bot_key}")


@mcp.tool
async def list_wecom_bots() -> dict:
    """
    列出所有已配置的企微 Bot。

    Returns:
        {"success": bool, "bots": [...], "total": int}
    """
    cfg = _get_config()
    if cfg is not None:
        bots = await cfg.list_bots()
        return {"success": True, "bots": bots, "total": len(bots)}

    return await _http_fallback("GET", "/admin/bots")


@mcp.tool
async def update_wecom_bot(
    bot_key: str,
    target_url: str | None = None,
    api_key: str | None = None,
    name: str | None = None,
    timeout: int | None = None,
    enabled: bool | None = None,
) -> dict:
    """
    更新企微 Bot 配置。只传入需要修改的字段。

    Args:
        bot_key:    企微 Bot key（必填，定位 bot）
        target_url: 新的 A2A 端点 URL（可选）
        api_key:    新的 API Key（可选）
        name:       新的 Bot 名称（可选）
        timeout:    新的超时秒数（可选）
        enabled:    是否启用，设为 false 可软下线（可选）

    Returns:
        {"success": bool, "bot": {...}}
    """
    payload = {
        k: v for k, v in {
            "target_url": target_url,
            "api_key": api_key,
            "name": name,
            "timeout": timeout,
            "enabled": enabled,
        }.items() if v is not None
    }
    if not payload:
        return {"success": False, "error": "未提供任何需要更新的字段"}

    cfg = _get_config()
    if cfg is not None:
        return await cfg.update_bot(bot_key, payload)

    return await _http_fallback("PUT", f"/admin/bots/{bot_key}", payload)


# ============================================================
# HTTP App 工厂
# ============================================================

def get_http_app(jwt_secret: str | None = None) -> "ASGIApp":
    """
    返回可挂载到 FastAPI 的 ASGI app。

    Args:
        jwt_secret: as-enterprise SECRET_KEY（AS_ENTERPRISE_JWT_SECRET 环境变量）。
                    传入时启用 JWT 鉴权；未传入时跳过鉴权（内网/开发模式）。

    用法（在 app.py 中）：
        from .mcp_server import get_http_app
        app.mount("/mcp", get_http_app(jwt_secret=os.getenv("AS_ENTERPRISE_JWT_SECRET")))
    """
    middleware = []
    if jwt_secret:
        middleware.append(
            lambda app: EnterpriseJWTMiddleware(app, jwt_secret)
        )
        logger.info("MCP /mcp 端点：已启用 as-enterprise JWT 鉴权")
    else:
        logger.warning(
            "AS_ENTERPRISE_JWT_SECRET 未配置，MCP /mcp 端点跳过鉴权（内网/开发模式）"
        )

    return mcp.http_app(path="/", middleware=middleware)


def main():
    """以 stdio 模式运行 MCP 服务（本地调试用）"""
    logger.warning(
        "Running in stdio mode. "
        "For production, mount at /mcp in the FastAPI app with AS_ENTERPRISE_JWT_SECRET set."
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
