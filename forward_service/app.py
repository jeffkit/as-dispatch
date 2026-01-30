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

from .config import config
from .database import database_lifespan, get_db_manager, get_database_url
from .session_manager import init_session_manager
from .routes import (
    admin_router, bots_router, callback_router, intelligent_router,
    slack_router, telegram_router, lark_router
)
from .routes import discord as discord_router
from .tunnel import tunnel_server, init_tunnel_server

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
        for bot_key, bot in config.bots.items():
            logger.info(f"  - {bot.name} (key={bot_key[:10]}..., platform={bot.platform}, enabled={bot.enabled})")
            # 收集需要启动的 Discord Bot
            if bot.platform == "discord" and bot.enabled:
                discord_bots.append(bot_key)
        
        # 启动 Discord Bot（后台任务）
        discord_tasks = []
        for bot_key in discord_bots:
            task = asyncio.create_task(discord_router.start_discord_bot(bot_key))
            discord_tasks.append(task)
            logger.info(f"  🚀 启动 Discord Bot 任务: {bot_key[:10]}...")

        yield

        # 关闭 Discord Bot
        for bot_key, client in discord_router.discord_bots.items():
            logger.info(f"  ⏹️  关闭 Discord Bot: {bot_key[:10]}...")
            await client.close()
        
        # 取消 Discord Bot 任务
        for task in discord_tasks:
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
app.include_router(callback_router)
app.include_router(intelligent_router)  # 智能机器人路由
app.include_router(slack_router)  # Slack 集成路由
app.include_router(telegram_router)  # Telegram 集成路由
app.include_router(lark_router)  # 飞书集成路由
app.include_router(tunnel_server.router)  # 隧道服务路由

# 静态文件目录
STATIC_DIR = Path(__file__).parent / "static"


# ============== 基础路由 ==============

@app.get("/")
async def root() -> dict:
    """根路径"""
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
