"""
Forward Service 数据库连接管理

支持多种数据库引擎:
- 开发/测试: SQLite (文件或内存)
- 生产: MySQL

环境变量配置:
    DATABASE_URL: 数据库连接 URL (可选)
        - SQLite: sqlite:///./data/forward.db
        - 内存: sqlite:///:memory:
        - MySQL: mysql+pymysql://user:password@host:port/database
    DATABASE_ECHO: 是否打印 SQL 语句 (默认 False)
"""
import os
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker
)
from sqlalchemy.pool import NullPool

from .models import Base

logger = logging.getLogger(__name__)


# ============== 数据库 URL 构建器 ==============

def build_database_url() -> str:
    """
    构建数据库连接 URL

    优先级:
    1. 环境变量 DATABASE_URL
    2. 默认: SQLite 文件数据库
    """
    database_url = os.getenv("DATABASE_URL")

    if database_url:
        logger.info(f"使用环境变量 DATABASE_URL: {database_url[:30]}...")
        return database_url

    # 默认使用 SQLite
    db_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "data",
        "forward_service.db"
    )
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # SQLAlchemy async SQLite URL
    database_url = f"sqlite+aiosqlite:///{db_path}"
    logger.info(f"使用默认 SQLite 数据库: {database_url}")
    return database_url


def is_mysql_database(url: str) -> bool:
    """检查是否为 MySQL 数据库"""
    return url.startswith("mysql+") or url.startswith("mysql+")


def is_sqlite_database(url: str) -> bool:
    """检查是否为 SQLite 数据库"""
    return url.startswith("sqlite+")


# ============== 数据库引擎管理 ==============

class DatabaseManager:
    """
    数据库管理器

    管理数据库连接池、Session 创建、表初始化等
    """

    def __init__(self, database_url: str | None = None):
        """
        初始化数据库管理器

        Args:
            database_url: 数据库连接 URL (如果不提供则使用环境变量或默认值)
        """
        self.database_url = database_url or build_database_url()
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker | None = None

    @property
    def engine(self) -> AsyncEngine:
        """获取数据库引擎 (延迟初始化)"""
        if self._engine is None:
            raise RuntimeError("数据库引擎未初始化，请先调用 init_db()")
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker:
        """获取 Session 工厂 (延迟初始化)"""
        if self._session_factory is None:
            raise RuntimeError("Session 工厂未初始化，请先调用 init_db()")
        return self._session_factory

    def init_engine(self, echo: bool = False):
        """
        初始化数据库引擎

        Args:
            echo: 是否打印 SQL 语句 (用于调试)
        """
        # 从环境变量读取 echo 设置
        if os.getenv("DATABASE_ECHO", "").lower() in ("1", "true", "yes"):
            echo = True

        # 创建引擎
        engine_kwargs = {
            "echo": echo,
            "future": True,
        }

        # SQLite 特殊配置
        if is_sqlite_database(self.database_url):
            engine_kwargs.update({
                "poolclass": NullPool,  # SQLite 不需要连接池
                "connect_args": {
                    "check_same_thread": False,  # 允许多线程访问
                }
            })
            logger.info("使用 SQLite 数据库引擎")

        # MySQL 特殊配置
        elif is_mysql_database(self.database_url):
            engine_kwargs.update({
                "pool_size": 5,  # 连接池大小
                "max_overflow": 10,  # 最大溢出连接数
                "pool_recycle": 3600,  # 连接回收时间 (秒)
                "pool_pre_ping": True,  # 连接前先 ping 检查
            })
            logger.info("使用 MySQL 数据库引擎")

        self._engine = create_async_engine(self.database_url, **engine_kwargs)
        logger.info(f"数据库引擎已创建: {self.database_url[:50]}...")

    def init_session_factory(self):
        """初始化 Session 工厂"""
        if self._engine is None:
            self.init_engine()

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,  # 避免对象在 commit 后过期
            autocommit=False,
            autoflush=False,
        )
        logger.info("Session 工厂已创建")

    async def init_db(self, echo: bool = False):
        """
        初始化数据库

        Args:
            echo: 是否打印 SQL 语句
        """
        logger.info("正在初始化数据库...")

        # 1. 创建引擎
        self.init_engine(echo=echo)

        # 2. 创建 Session 工厂
        self.init_session_factory()

        # 3. 创建表 (如果不存在)
        await self.create_tables()

        logger.info("数据库初始化完成")

    async def create_tables(self):
        """创建所有表 (如果不存在)"""
        if self._engine is None:
            raise RuntimeError("数据库引擎未初始化")

        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("数据库表已创建 (如果不存在)")

    async def drop_tables(self):
        """删除所有表 (危险操作，仅用于测试)"""
        if self._engine is None:
            raise RuntimeError("数据库引擎未初始化")

        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            logger.warning("所有数据库表已删除")

    async def close(self):
        """关闭数据库连接"""
        if self._engine:
            await self._engine.dispose()
            logger.info("数据库连接已关闭")

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        获取数据库 Session (上下文管理器)

        用法:
            async with db_manager.get_session() as session:
                # 使用 session
                result = await session.execute(...)
        """
        if self._session_factory is None:
            raise RuntimeError("Session 工厂未初始化")

        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


# ============== 全局数据库管理器 ==============

# 全局数据库管理器实例
db_manager: DatabaseManager | None = None


def get_database_url() -> str:
    """获取数据库 URL"""
    global db_manager
    if db_manager is None:
        return build_database_url()
    return db_manager.database_url


async def init_database(echo: bool = False):
    """
    初始化全局数据库管理器

    Args:
        echo: 是否打印 SQL 语句
    """
    global db_manager
    if db_manager is None:
        db_manager = DatabaseManager()
        await db_manager.init_db(echo=echo)
        logger.info("全局数据库管理器已初始化")


async def close_database():
    """关闭全局数据库管理器"""
    global db_manager
    if db_manager:
        await db_manager.close()
        db_manager = None
        logger.info("全局数据库管理器已关闭")


def get_db_manager() -> DatabaseManager:
    """获取全局数据库管理器"""
    global db_manager
    if db_manager is None:
        raise RuntimeError("数据库未初始化，请先调用 init_database()")
    return db_manager


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    获取数据库 Session (FastAPI 依赖注入用)

    用法:
        @app.get("/api/bots")
        async def list_bots(session: AsyncSession = Depends(get_session)):
            ...
    """
    db = get_db_manager()
    async with db.get_session() as session:
        yield session


# ============== 辅助函数 ==============

async def check_database_connection() -> bool:
    """
    检查数据库连接是否正常

    Returns:
        True 表示连接正常
    """
    try:
        db = get_db_manager()
        async with db.get_session() as session:
            # 执行简单查询
            from sqlalchemy import text
            await session.execute(text("SELECT 1"))
            return True
    except Exception as e:
        logger.error(f"数据库连接检查失败: {e}")
        return False


# ============== FastAPI 生命周期管理 ==============

from contextlib import asynccontextmanager


@asynccontextmanager
async def database_lifespan():
    """
    数据库生命周期管理器 (FastAPI lifespan)

    用法:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            async with database_lifespan():
                yield
    """
    # 启动时初始化数据库
    logger.info("正在启动数据库...")
    await init_database()
    logger.info("数据库已启动")

    yield

    # 关闭时清理数据库
    logger.info("正在关闭数据库...")
    await close_database()
    logger.info("数据库已关闭")
