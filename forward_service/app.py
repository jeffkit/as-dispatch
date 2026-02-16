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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from fastapi import Request

from .config import config
from .database import database_lifespan, get_db_manager, get_database_url
from .session_manager import init_session_manager
from .routes import admin_router, bots_router, callback_router, tunnel_proxy_router
from .tunnel import tunnel_server, init_tunnel_server, load_tunnel_config

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
        for bot_key, bot in config.bots.items():
            logger.info(f"  - {bot.name} (key={bot_key[:10]}..., enabled={bot.enabled})")

        yield

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
app.include_router(callback_router)
app.include_router(tunnel_server.router)  # 隧道服务路由
app.include_router(tunnel_proxy_router)   # 隧道代理路由 (/t/{domain}/...)

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
    headers.pop("host", None)
    headers.pop("content-length", None)
    
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
            resp_headers = dict(response.headers) if response.headers else {}
            for h in ["connection", "keep-alive", "transfer-encoding", "te", "trailer",
                       "upgrade", "proxy-connection", "content-length", "content-encoding",
                       "access-control-allow-origin", "access-control-allow-methods",
                       "access-control-allow-headers", "access-control-allow-credentials",
                       "access-control-expose-headers", "access-control-max-age"]:
                resp_headers.pop(h, None)
            content = response.body
            if not isinstance(content, (str, bytes)):
                content = json.dumps(content)
            return FastAPIResponse(
                content=content, status_code=response.status,
                headers=resp_headers,
                media_type=resp_headers.get("content-type", "application/json"),
            )
        except Exception as e:
            logger.error(f"[SubdomainProxy] Forward error: {e}", exc_info=True)
            return FastAPIResponse(
                content=json.dumps({"error": f"Forward failed: {str(e)}"}),
                status_code=502,
                media_type="application/json",
            )


# ============== 基础路由 ==============

@app.get("/")
async def root(request: Request) -> dict:
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
        "config_errors": errors,
        "default_bot_key": config.default_bot_key[:10] + "..." if config.default_bot_key else None,
        "bots_count": len(config.bots),
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
