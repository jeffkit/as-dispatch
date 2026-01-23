"""
pytest 配置文件
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from contextlib import asynccontextmanager

# Mock pigeon 模块以避免导入错误（pigeon 需要 SOCKS 代理支持）
if 'pigeon' not in sys.modules:
    sys.modules['pigeon'] = MagicMock()
    sys.modules['pigeon.Bot'] = MagicMock()

# 将包目录添加到 Python 路径
pkg_root = Path(__file__).parent.parent
if str(pkg_root) not in sys.path:
    sys.path.insert(0, str(pkg_root))


# ============== 数据库测试 Fixtures ==============

@pytest_asyncio.fixture
async def test_db_engine():
    """创建测试数据库引擎"""
    from forward_service.models import Base
    
    # 使用内存 SQLite 数据库
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False
    )

    # 创建所有表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # 清理
    await engine.dispose()


@pytest_asyncio.fixture
async def test_db_session(test_db_engine):
    """创建测试数据库 Session"""
    session_maker = async_sessionmaker(
        test_db_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
    async with session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def mock_db_manager(test_db_engine):
    """
    Mock 数据库管理器
    
    替换全局的 db_manager，使测试使用内存数据库
    """
    import forward_service.database as db_module
    from forward_service.database import DatabaseManager
    from forward_service.models import Base
    
    # 保存原始的 db_manager
    original_db_manager = db_module.db_manager
    
    # 创建测试用的 DatabaseManager
    class TestDatabaseManager:
        def __init__(self, engine):
            self._engine = engine
            self._session_factory = async_sessionmaker(
                bind=engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autocommit=False,
                autoflush=False,
            )
        
        @property
        def engine(self):
            return self._engine
        
        @property
        def session_factory(self):
            return self._session_factory
        
        @asynccontextmanager
        async def get_session(self):
            async with self._session_factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
    
    # 替换全局 db_manager
    test_manager = TestDatabaseManager(test_db_engine)
    db_module.db_manager = test_manager
    
    yield test_manager
    
    # 恢复原始的 db_manager
    db_module.db_manager = original_db_manager


@pytest.fixture(autouse=True)
def mock_agent_connectivity():
    """
    Mock _test_agent_connectivity 函数
    
    在测试中跳过实际的 HTTP 连接测试
    """
    from unittest.mock import patch, AsyncMock
    
    with patch(
        'forward_service.routes.project_commands._test_agent_connectivity',
        new_callable=AsyncMock,
        return_value={"success": True, "latency": 50, "response": {"status": "ok"}}
    ):
        yield
