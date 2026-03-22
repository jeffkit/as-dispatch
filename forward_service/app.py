"""
Forward Service 主应用

接收企微机器人回调，转发到目标 URL，并将结果返回给用户。

运行方式:
    python -m forward_service.app
    # 或
    uvicorn forward_service.app:app --host 0.0.0.0 --port 8083

配置存储:
    - 默认使用 SQLite 数据库 (data/forward_service.db)
    - 支持 MySQL (通过 DATABASE_URL 环境变量配置)
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from fastapi import Request

from .config import config
from .database import database_lifespan, get_db_manager, get_database_url
from .session_manager import init_session_manager
from .routes import (
    admin_router, bots_router, bots_api_router, callback_router, unified_callback_router,
    intelligent_router, slack_router, telegram_router, lark_router, tunnel_proxy_router,
    qqbot_admin_router
)
from .routes import discord as discord_router
from .tunnel import tunnel_server, init_tunnel_server, load_tunnel_config
from .channel import register_adapter
from .channel.wecom import WeComAdapter
from .channel.telegram import TelegramAdapter
from .channel.lark import LarkAdapter
from .channel.discord import DiscordAdapter
from .channel.slack import SlackAdapter
from .channel.qqbot import QQBotAdapter
from .mcp_server import get_http_app as get_mcp_http_app

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============== FastAPI 应用 ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    import asyncio
    
    async with database_lifespan():
        # 初始化配置
        await config.initialize()

        # 初始化会话管理器
        init_session_manager(get_db_manager())
        logger.info("  会话管理器已初始化")

        # 启动时清理过期的 ProcessingSession 锁（防止服务崩溃导致的死锁）
        try:
            from .repository import get_processing_session_repository
            db = get_db_manager()
            async with db.get_session() as session:
                processing_repo = get_processing_session_repository(session)
                cleaned = await processing_repo.cleanup_stale(timeout_seconds=300)
                await session.commit()
                if cleaned > 0:
                    logger.info(f"  清理了 {cleaned} 条过期的处理锁")
                else:
                    logger.info("  处理锁检查完毕，无过期记录")
        except Exception as e:
            logger.warning(f"  清理处理锁失败（不影响启动）: {e}")

        # 注册通道适配器
        register_adapter(WeComAdapter())
        register_adapter(TelegramAdapter())
        register_adapter(LarkAdapter())
        register_adapter(DiscordAdapter())
        register_adapter(SlackAdapter())
        register_adapter(QQBotAdapter())
        logger.info("  通道适配器已注册: wecom, telegram, lark, discord, slack, qqbot")

        # 初始化隧道服务器（使用相同的数据库）
        database_url = get_database_url()
        await init_tunnel_server(database_url)
        logger.info("  隧道服务器已初始化")

        # 验证配置
        errors = config.validate()
        if errors:
            for error in errors:
                logger.warning(f"配置警告: {error}")

        logger.info(f"Forward Service 启动 v3.0")
        logger.info(f"  端口: {config.port}")
        logger.info(f"  默认 Bot Key: {config.default_bot_key[:10]}..." if config.default_bot_key else "  默认 Bot Key: 未配置")
        logger.info(f"  Bot 数量: {len(config.bots)}")

        # 列出所有 Bot
        discord_bots = []
        qqbot_bots = []
        for bot_key, bot in config.bots.items():
            bot_platform = bot._bot.platform if bot._bot else "unknown"
            logger.info(f"  - {bot.name} (key={bot_key[:10]}..., platform={bot_platform}, enabled={bot.enabled})")
            if bot_platform == "discord" and bot.enabled:
                discord_bots.append(bot_key)
            elif bot_platform == "qqbot" and bot.enabled:
                qqbot_bots.append(bot_key)
        
        # 启动 Discord Bot（后台任务）
        discord_tasks = []
        for bot_key in discord_bots:
            task = asyncio.create_task(discord_router.start_discord_bot(bot_key))
            discord_tasks.append(task)
            logger.info(f"  🚀 启动 Discord Bot 任务: {bot_key[:10]}...")

        # 启动 QQ Bot（后台任务）
        from .routes import qqbot as qqbot_router
        qqbot_tasks = []
        for bot_key in qqbot_bots:
            task = asyncio.create_task(qqbot_router.start_qqbot(bot_key))
            qqbot_tasks.append(task)
            logger.info(f"  🚀 启动 QQ Bot 任务: {bot_key[:10]}...")

        yield

        # 关闭 Discord Bot
        for bot_key, client in discord_router.discord_bots.items():
            logger.info(f"  ⏹️  关闭 Discord Bot: {bot_key[:10]}...")
            await client.close()
        
        # 关闭 QQ Bot
        for bot_key, client in qqbot_router.qqbot_clients.items():
            logger.info(f"  ⏹️  关闭 QQ Bot: {bot_key[:10]}...")
            await client.close()

        # 取消 Discord Bot 任务
        for task in discord_tasks:
            if not task.done():
                task.cancel()

        # 取消 QQ Bot 任务
        for task in qqbot_tasks:
            if not task.done():
                task.cancel()

        # 关闭隧道服务器
        await tunnel_server.close()
        logger.info("Forward Service 关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="Forward Service",
    description="消息转发服务 - 接收企微回调，转发到 Agent",
    version="3.0.0",
    lifespan=lifespan
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(admin_router)
app.include_router(bots_router)
app.include_router(bots_api_router)              # 用户级接口，JWT 鉴权
app.include_router(callback_router)              # 旧的 /callback（向后兼容）
app.include_router(unified_callback_router)      # 新的 /callback/{platform}（多平台统一入口）
app.include_router(intelligent_router)           # 智能机器人路由
app.include_router(slack_router)                 # Slack 集成路由
app.include_router(telegram_router)              # Telegram 集成路由
app.include_router(lark_router)                  # 飞书集成路由
app.include_router(tunnel_server.router)         # 隧道服务路由
app.include_router(tunnel_proxy_router)          # 隧道代理路由 (/t/{domain}/...)
app.include_router(qqbot_admin_router)           # QQ Bot 管理路由 (/admin/qqbot/...)

# MCP HTTP 端点
# 配置 JWT_SECRET_KEY 时启用 JWT 鉴权（与 as-enterprise 共享同一个密钥）
# 未配置时跳过鉴权（内网/开发模式）
app.mount("/mcp", get_mcp_http_app(jwt_secret=os.getenv("JWT_SECRET_KEY")))

# 静态文件目录
STATIC_DIR = Path(__file__).parent / "static"

# 隧道域名配置（用于子域名路由）
_tunnel_config = load_tunnel_config()
TUNNEL_BASE_DOMAIN = _tunnel_config.get("domain", "tunnel")


def _extract_subdomain(host: str) -> str | None:
    """从 Host 头中提取子域名"""
    host = host.split(":")[0]
    if host == TUNNEL_BASE_DOMAIN:
        return None
    suffix = f".{TUNNEL_BASE_DOMAIN}"
    if host.endswith(suffix):
        subdomain = host[:-len(suffix)]
        if "." not in subdomain:
            return subdomain
    return None


async def _forward_subdomain_request(request: Request, subdomain: str, path: str):
    """将子域名请求转发到隧道（复用 tunnel_proxy 的逻辑）"""
    import json
    from fastapi.responses import StreamingResponse, Response as FastAPIResponse
    
    if not tunnel_server.manager.is_connected(subdomain):
        return FastAPIResponse(
            content=json.dumps({"error": f"Tunnel not connected: {subdomain}"}),
            status_code=503,
            media_type="application/json",
        )
    
    method = request.method
    headers = dict(request.headers)
    # Remove hop-by-hop and proxy headers that should not be forwarded through tunnel
    for h in ["host", "content-length", "connection", "upgrade",
              "x-real-ip", "x-forwarded-for", "x-forwarded-proto",
              "transfer-encoding", "te", "trailer", "keep-alive",
              "proxy-connection", "proxy-authorization"]:
        headers.pop(h, None)
    
    body = None
    if method in ("POST", "PUT", "PATCH"):
        body_bytes = await request.body()
        if body_bytes:
            try:
                body = json.loads(body_bytes)
            except json.JSONDecodeError:
                body = body_bytes.decode("utf-8", errors="replace")
    
    accept_header = headers.get("accept", "")
    is_sse = "text/event-stream" in accept_header
    
    logger.info(f"[SubdomainProxy] {method} {subdomain}{path} (SSE={is_sse})")
    
    if is_sse:
        from tunely import StreamStartMessage, StreamChunkMessage, StreamEndMessage
        
        async def stream_gen():
            try:
                async for msg in tunnel_server.forward_stream(
                    domain=subdomain, method=method, path=path,
                    headers=headers, body=body, timeout=300.0,
                ):
                    if isinstance(msg, StreamStartMessage):
                        yield f"event: start\ndata: {{}}\n\n"
                    elif isinstance(msg, StreamChunkMessage):
                        yield f"data: {msg.data}\n\n"
                    elif isinstance(msg, StreamEndMessage):
                        if msg.error:
                            yield f"event: error\ndata: {msg.error}\n\n"
                        else:
                            yield f"event: done\ndata: {{}}\n\n"
                        break
            except Exception as e:
                logger.error(f"[SubdomainProxy] Stream error: {e}", exc_info=True)
                yield f"event: error\ndata: {str(e)}\n\n"
        
        return StreamingResponse(
            stream_gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )
    else:
        try:
            response = await tunnel_server.forward(
                domain=subdomain, method=method, path=path,
                headers=headers, body=body, timeout=300.0,
            )
            logger.info(f"[SubdomainProxy] Forward response: status={response.status}, body_type={type(response.body).__name__}, body_len={len(response.body) if response.body else 0}, error={response.error}")
            
            if response.error:
                return FastAPIResponse(
                    content=json.dumps({"error": response.error}),
                    status_code=response.status or 502,
                    media_type="application/json",
                )
            
            resp_headers = dict(response.headers) if response.headers else {}
            for h in ["connection", "keep-alive", "transfer-encoding", "te", "trailer",
                       "upgrade", "proxy-connection", "content-length", "content-encoding",
                       "access-control-allow-origin", "access-control-allow-methods",
                       "access-control-allow-headers", "access-control-allow-credentials",
                       "access-control-expose-headers", "access-control-max-age"]:
                resp_headers.pop(h, None)
            content = response.body
            if content is None:
                content = b""
            elif not isinstance(content, (str, bytes)):
                content = json.dumps(content)
            media_type = resp_headers.get("content-type", "application/octet-stream")
            return FastAPIResponse(
                content=content, status_code=response.status,
                headers=resp_headers,
                media_type=media_type,
            )
        except Exception as e:
            logger.error(f"[SubdomainProxy] Forward error: {e}", exc_info=True)
            return FastAPIResponse(
                content=json.dumps({"error": f"Forward failed: {str(e)}"}),
                status_code=502,
                media_type="application/json",
            )


# ============== 基础路由 ==============

@app.api_route("/", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def root(request: Request):
    """根路径 - 支持子域名转发"""
    host = request.headers.get("host", "")
    subdomain = _extract_subdomain(host)
    if subdomain:
        return await _forward_subdomain_request(request, subdomain, "/")
    return {
        "service": "Forward Service",
        "version": "3.0.0",
        "status": "running"
    }


@app.get("/health")
async def health() -> dict:
    """健康检查"""
    errors = config.validate()
    return {
        "status": "healthy" if not errors else "unhealthy",
        "version": "3.0.0"
    }


# ============== 子域名模式路由（通用 catch-all） ==============

@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def catch_all(request: Request, path: str):
    """通用路由 - 子域名转发"""
    import json
    from fastapi.responses import Response as FastAPIResponse
    
    host = request.headers.get("host", "")
    subdomain = _extract_subdomain(host)
    
    if subdomain:
        full_path = f"/{path}"
        if request.query_params:
            full_path += f"?{request.query_params}"
        return await _forward_subdomain_request(request, subdomain, full_path)
    
    return FastAPIResponse(
        content=json.dumps({"detail": "Not Found"}),
        status_code=404,
        media_type="application/json",
    )


# ============== 入口点 ==============

def main():
    """主函数"""
    import uvicorn
    uvicorn.run(
        "forward_service.app:app",
        host="0.0.0.0",
        port=config.port,
        reload=False
    )


if __name__ == "__main__":
    main()
