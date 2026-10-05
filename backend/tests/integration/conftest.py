"""集成与接口测试共用 fixture（《代码管理工作介绍 V1.0》§4.4、《概要设计》§7.2）。

本文件提供集成测试层的共用设施：

1. **基础设施可用性探测**：PostgreSQL / Redis / MinIO 端口与驱动探测；
   容器未启动时相关用例按设计优雅跳过（不报错、不超时）；
2. **真实基础设施 fixture**（容器可用时启用，环境隔离按文档 §4.4 执行）：
   - `pg_session`：每测试会话建一次结构与 pgvector 扩展，每个用例在事务中执行并回滚；
   - `redis_client`：使用独立库编号（DB 15），每个用例前清空；
   - `minio_temp_bucket`：临时存储桶，用例结束删除全部对象并删桶。
3. **网络策略说明**：根 `tests/conftest.py` 的 `block_external_network` 对全部测试
   （含本目录）生效，仅放行环回地址（127.0.0.1 / localhost / ::1）；
   容器化依赖经环回访问，不受拦截影响；禁止真实公网连接。

接口测试（FastAPI TestClient）位于 `tests/unit/api/`：通过 `dependency_overrides`
离线运行、不依赖容器；需要真实容器的接口验证归入本目录。
"""

import os
import socket
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import pytest

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查
    from redis import Redis
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

_DEFAULT_PG_URL = "postgresql+psycopg://zhilian_user:zhilian_password@127.0.0.1:5432/zhilian_db"
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
_DEFAULT_MINIO_ENDPOINT = "http://127.0.0.1:9000"

_REDIS_TEST_DB = 15
"""集成测试专用 Redis 库编号（与开发默认库 0 隔离）。"""

_MINIO_TEST_BUCKET = "zhilian-integration-test"
"""集成测试临时桶名，用例结束即删。"""


def _tcp_port_open(host: str, port: int, timeout: float = 0.2) -> bool:
    """快速探测环回地址 TCP 端口是否可建立连接（毫秒级，不触发外部网络）。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect((host, port))
            return True
    except (OSError, TimeoutError):
        return False


def _driver_installed(module: str) -> bool:
    try:
        __import__(module)
    except ImportError:
        return False
    return True


def postgres_available() -> bool:
    """PostgreSQL 驱动具备且端口连通（docker compose 已启动）。"""
    if not _driver_installed("psycopg") and not _driver_installed("psycopg2"):
        return False
    parsed = urlparse(os.environ.get("ZHILIAN_DB__DB_URL", _DEFAULT_PG_URL))
    return _tcp_port_open(parsed.hostname or "127.0.0.1", parsed.port or 5432)


def redis_available() -> bool:
    """Redis 驱动具备且端口连通。"""
    if not _driver_installed("redis"):
        return False
    parsed = urlparse(os.environ.get("ZHILIAN_REDIS__REDIS_URL", _DEFAULT_REDIS_URL))
    return _tcp_port_open(parsed.hostname or "127.0.0.1", parsed.port or 6379)


def minio_available() -> bool:
    """对象存储驱动具备且端点端口连通。"""
    if not _driver_installed("boto3"):
        return False
    parsed = urlparse(os.environ.get("ZHILIAN_STORAGE__ENDPOINT_URL", _DEFAULT_MINIO_ENDPOINT))
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 9000)
    return _tcp_port_open(host, port)


@pytest.fixture(scope="session")
def pg_engine() -> Iterator["Engine"]:
    """会话级真实 PostgreSQL 引擎：建一次结构与 pgvector 扩展；不可用则跳过。"""
    if not postgres_available():
        pytest.skip("PostgreSQL 容器不可用（docker compose 未启动），按设计跳过")
    from sqlalchemy import create_engine, text

    engine = create_engine(os.environ.get("ZHILIAN_DB__DB_URL", _DEFAULT_PG_URL))
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine: "Engine") -> Iterator["Session"]:
    """每用例独立事务：执行后回滚，保证用例之间互不污染。"""
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=pg_engine)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def redis_client() -> Iterator["Redis"]:
    """独立库编号（15）的 Redis 客户端：用例前清空，不可用则跳过。"""
    if not redis_available():
        pytest.skip("Redis 容器不可用（docker compose 未启动），按设计跳过")
    import redis

    client = redis.Redis.from_url(
        os.environ.get("ZHILIAN_REDIS__REDIS_URL", _DEFAULT_REDIS_URL),
        db=_REDIS_TEST_DB,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )
    client.flushdb()
    yield client
    client.flushdb()


@pytest.fixture
def minio_temp_bucket() -> Iterator[dict[str, Any]]:
    """临时存储桶：用例结束删除全部对象并删桶；不可用则跳过。"""
    if not minio_available():
        pytest.skip("MinIO 容器不可用（docker compose 未启动），按设计跳过")
    import boto3

    endpoint = os.environ.get("ZHILIAN_STORAGE__ENDPOINT_URL", _DEFAULT_MINIO_ENDPOINT)
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("ZHILIAN_STORAGE__ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.environ.get("ZHILIAN_STORAGE__SECRET_KEY", "minioadmin"),
        region_name="us-east-1",
    )
    client.create_bucket(Bucket=_MINIO_TEST_BUCKET)
    try:
        yield {"client": client, "bucket": _MINIO_TEST_BUCKET}
    finally:
        response = client.list_objects_v2(Bucket=_MINIO_TEST_BUCKET)
        for item in response.get("Contents", []):
            client.delete_object(Bucket=_MINIO_TEST_BUCKET, Key=item["Key"])
        client.delete_bucket(Bucket=_MINIO_TEST_BUCKET)
