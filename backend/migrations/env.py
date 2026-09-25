"""Alembic environment configuration."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings
from app.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata


def _get_target_db_url() -> str:
    """获取迁移目标数据库 URL，优先读取 AppSettings 强类型配置。"""
    try:
        settings = get_settings()
        db_url = settings.db.db_url
    except Exception:
        db_url = config.get_main_option("sqlalchemy.url", "sqlite:///./zhilian_dev.db")

    if "postgresql+asyncpg://" in db_url:
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    elif "sqlite+aiosqlite://" in db_url:
        db_url = db_url.replace("sqlite+aiosqlite://", "sqlite://")
    return db_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = _get_target_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_pk_length=128,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    db_url = _get_target_db_url()
    connectable = create_engine(
        db_url,
        poolclass=pool.NullPool,
        connect_args={"check_same_thread": False} if db_url.startswith("sqlite") else {},
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_pk_length=128,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
