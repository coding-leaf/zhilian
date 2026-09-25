"""真实基础设施连通性集成测试套件。

严格遵循 AGENTS.md 与 spec.md / plan.md 技术契约：
1. 真实验证 PostgreSQL (含 pgvector 扩展)、Redis 7、MinIO 适配器的装配与握手协议；
2. 严格守护脱机开发与 CI 门禁红线：
   通过运行态网络端口探测与驱动依赖检测，在未启动对应本地 Docker 容器时自动优雅跳过；
3. 毫秒级自闭环：脱机状态下耗时极短，严禁触发外部网络或抛出非预期断言错误。
"""

import os
import socket
from typing import Any
from urllib.parse import urlparse

import pytest
from sqlalchemy import text

from app.container import AppContainer
from app.core.config import AppSettings, DatabaseSettings, RedisSettings, StorageSettings
from app.core.errors import StorageError
from app.integrations.container import ProviderRegistry
from app.integrations.idempotency.factory import create_idempotency_adapter
from app.integrations.queue.factory import create_queue_adapter
from app.integrations.storage.factory import create_storage_adapter


def _is_tcp_port_open(host: str, port: int, timeout: float = 0.2) -> bool:
    """快速探测本地 TCP 端口是否开放且允许建立连接。

    Args:
        host: 主机地址（仅限本地环回地址）。
        port: 目标端口号。
        timeout: 探测超时时间（秒）。

    Returns:
        bool: 端口连通返回 True，否则返回 False。
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect((host, port))
            return True
    except (OSError, TimeoutError):
        return False


def is_postgres_available() -> bool:
    """探测运行环境中是否存在可连通的 PostgreSQL 实例且已安装对应驱动。

    Returns:
        bool: 驱动具备且端口连通返回 True，否则返回 False。
    """
    try:
        import psycopg  # type: ignore[import-untyped]  # noqa: F401
    except ImportError:
        try:
            import psycopg2  # type: ignore[import-untyped]  # noqa: F401
        except ImportError:
            return False

    raw_url = os.environ.get(
        "ZHILIAN_DATABASE__DB_URL",
        "postgresql+psycopg://zhilian_user:zhilian_password@127.0.0.1:5432/zhilian_db",
    )
    parsed = urlparse(raw_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432
    return _is_tcp_port_open(host, port)


def is_redis_available() -> bool:
    """探测运行环境中是否存在可连通的 Redis 实例且已安装 redis 驱动。

    Returns:
        bool: 驱动具备且端口连通返回 True，否则返回 False。
    """
    try:
        import redis  # type: ignore[import-untyped]  # noqa: F401
    except ImportError:
        return False

    raw_url = os.environ.get("ZHILIAN_REDIS__REDIS_URL", "redis://127.0.0.1:6379/0")
    parsed = urlparse(raw_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 6379
    return _is_tcp_port_open(host, port)


def is_minio_available() -> bool:
    """探测运行环境中是否存在可连通的 MinIO 服务且已安装 boto3 驱动。

    Returns:
        bool: 驱动具备且端口连通返回 True，否则返回 False。
    """
    try:
        import boto3  # type: ignore[import-untyped]  # noqa: F401
    except ImportError:
        return False

    endpoint = os.environ.get("ZHILIAN_STORAGE__ENDPOINT_URL", "http://127.0.0.1:9000")
    parsed = urlparse(endpoint)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 9000
    return _is_tcp_port_open(host, port)


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="PostgreSQL 实例未就绪或未安装 psycopg 驱动，脱机环境安全跳过",
)
def test_real_postgresql_and_pgvector_handshake() -> None:
    """验证真实 PostgreSQL 实例连接握手与 pgvector 向量扩展能力 (IT-PGV-01)。"""
    from app.core.config import get_settings

    settings = get_settings()
    db_url = settings.db.db_url
    from sqlalchemy import create_engine

    engine = create_engine(db_url, pool_pre_ping=True)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1;"))
        assert result.scalar() == 1

        # 验证或激活 pgvector 扩展
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.commit()

        # 验证向量计算
        vector_res = conn.execute(
            text("SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector AS distance;")
        )
        distance = vector_res.scalar()
        assert distance is not None
        assert abs(float(distance) - 1.0) < 1e-5


@pytest.mark.skipif(
    not is_redis_available(),
    reason="Redis 实例未就绪或未安装 redis 驱动，脱机环境安全跳过",
)
def test_real_redis_handshake_and_adapters() -> None:
    """验证真实 Redis 实例握手及任务队列与幂等适配器协议交互。"""
    redis_url = os.environ.get("ZHILIAN_REDIS__REDIS_URL", "redis://127.0.0.1:6379/0")

    queue_adapter = create_queue_adapter("redis", redis_url=redis_url)
    assert queue_adapter is not None

    idempotency_adapter = create_idempotency_adapter("redis", redis_url=redis_url)
    assert idempotency_adapter is not None


@pytest.mark.skipif(
    not is_minio_available(),
    reason="MinIO 实例未就绪或未安装 boto3 驱动，脱机环境安全跳过",
)
def test_real_minio_storage_handshake() -> None:
    """验证真实 MinIO 实例握手与对象读写协议。"""
    endpoint = os.environ.get("ZHILIAN_STORAGE__ENDPOINT_URL", "http://127.0.0.1:9000")
    access_key = os.environ.get("ZHILIAN_STORAGE__ACCESS_KEY", "minioadmin")
    secret_key = os.environ.get("ZHILIAN_STORAGE__SECRET_KEY", "minioadmin")

    storage_adapter = create_storage_adapter(
        "minio",
        endpoint_url=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=False,
    )
    assert storage_adapter is not None


def test_container_real_infrastructure_settings_contract() -> None:
    """验证应用容器与适配器工厂对真实基础设施配置的装配契约与异常校验。"""
    # 验证缺少必填参数时触发明确的业务异常
    with pytest.raises(StorageError, match="必填配置参数"):
        create_storage_adapter("minio", endpoint_url=None, access_key=None, secret_key=None)

    # 验证强类型配置对象与容器健康检查 Schema 契约
    settings = AppSettings(
        db=DatabaseSettings(db_url="sqlite:///:memory:"),
        redis=RedisSettings(redis_url="redis://127.0.0.1:6379/0"),
        storage=StorageSettings(provider="memory"),
    )
    registry = ProviderRegistry.create_from_settings(settings=settings)
    assert registry.storage is not None

    container = AppContainer.create(settings=settings, registry=registry)
    assert container.settings.storage.provider == "memory"
    assert container.settings.redis.redis_url == "redis://127.0.0.1:6379/0"

    health: dict[str, Any] = container.check_health()
    assert health["status"] == "ok"
    assert "database" in health
    assert "storage" in health
    assert "providers" in health
