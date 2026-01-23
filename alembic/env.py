"""Alembic 迁移环境配置

此文件由 Alembic 自动生成，用于配置迁移环境。

关键配置：
1. 从环境变量 DATABASE_URL 读取数据库连接
2. 导入项目模型 (forward_service.models)
3. 支持 async SQLAlchemy (SQLite/MySQL)
"""
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

# 将项目根目录添加到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# ============== 加载 .env 文件 ==============
# 优先从当前目录的 .env 读取，然后是项目根目录的 .env
def load_dotenv_file():
    """加载 .env 文件到环境变量"""
    # 尝试的 .env 文件路径
    env_paths = [
        project_root / ".env",  # packages/forward-service/.env
        project_root.parent.parent / ".env",  # hitl/.env (旧的共享配置)
    ]
    
    for env_path in env_paths:
        if env_path.exists():
            print(f"[Alembic] 加载 .env 文件: {env_path}")
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        # 不覆盖已有的环境变量
                        if key not in os.environ:
                            os.environ[key] = value
            return True
    return False

load_dotenv_file()

from alembic import context
from forward_service.models import Base

# ============== Alembic Config ==============

config = context.config

# ============== 日志配置 ==============

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ============== 数据库 URL 配置 ==============

# 从环境变量读取 DATABASE_URL (优先级高于 alembic.ini)
database_url = os.getenv("DATABASE_URL")
if database_url:
    # 转换 async URL 为 sync URL (Alembic 需要同步引擎)
    # sqlite+aiosqlite:///... -> sqlite:///
    # mysql+aiomysql:///... -> mysql+pymysql:///
    if database_url.startswith("sqlite+aiosqlite"):
        sync_url = database_url.replace("sqlite+aiosqlite", "sqlite")
    elif database_url.startswith("mysql+aiomysql"):
        sync_url = database_url.replace("mysql+aiomysql", "mysql+pymysql")
    else:
        # 未知类型，保持原样
        sync_url = database_url

    # 转义 % 符号，避免 configparser 解析问题
    escaped_url = sync_url.replace("%", "%%")
    config.set_main_option("sqlalchemy.url", escaped_url)
    print(f"[Alembic] 使用环境变量 DATABASE_URL: {sync_url[:50]}...")

# ============== 模型元数据 ==============

# 导入项目的模型元数据，用于 autogenerate
target_metadata = Base.metadata

# ============== 其他配置 ==============

# 其他自定义配置可以在这里添加
# my_important_option = config.get_main_option("my_important_option")


# ============== 迁移执行函数 ==============

def run_migrations_offline() -> None:
    """离线模式运行迁移

    此模式下不需要数据库连接，只生成 SQL 脚本。
    适用于生产环境需要审查 SQL 的情况。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # 渲染项配置
        render_as_batch=True,  # SQLite 支持 ALTER TABLE
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式运行迁移

    此模式下会连接数据库并执行迁移。
    """
    # 使用同步引擎创建迁移 (Alembic 不支持 async)
    configuration = config.get_section(config.config_ini_section, {})

    # SQLite 连接参数配置
    url = configuration.get("sqlalchemy.url", "")
    if url.startswith("sqlite"):
        configuration["sqlalchemy.connect_args"] = {"check_same_thread": False}

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # 配置项
            render_as_batch=True,  # SQLite 支持 ALTER TABLE
            compare_type=True,  # 比较列类型
            compare_server_default=True,  # 比较默认值
        )

        with context.begin_transaction():
            context.run_migrations()


# ============== 入口点 ==============

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
