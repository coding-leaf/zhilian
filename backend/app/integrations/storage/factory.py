"""对象存储适配器工厂模块。

严格遵循 AGENTS.md 规范：
- 根据配置参数分发并创建符合 StorageProtocol 契约的适配器实例；
- 单元测试与离线环境默认分发 MemoryStorageAdapter 实现，具备零外部依赖特性；
- 生产环境支持创建 S3StorageAdapter / MinioStorageAdapter。
"""

from typing import Any

from app.core.errors import StorageError
from app.integrations.storage.memory import MemoryStorageAdapter
from app.integrations.storage.protocol import StorageProtocol
from app.integrations.storage.s3 import S3StorageAdapter


def create_storage_adapter(
    storage_type: str = "memory",
    *,
    endpoint_url: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    region_name: str = "us-east-1",
    secure: bool = True,
    client: Any | None = None,
) -> StorageProtocol:
    """根据类型与配置创建对象存储适配器实例。

    Args:
        storage_type: 存储类型 ("memory" 或 "s3" / "minio")，默认 "memory"。
        endpoint_url: S3/MinIO 端点地址。
        access_key: 访问密钥 ID。
        secret_key: 访问秘密密钥。
        region_name: 地域标识，默认 "us-east-1"。
        secure: 是否使用 HTTPS，默认 True。
        client: 可选外部注入的底层 S3 客户端（供测试打桩）。

    Returns:
        StorageProtocol: 具备标准协议能力的存储适配器实例。

    Raises:
        StorageError: storage_type 不支持或配置参数缺失。
    """
    normalized_type = storage_type.strip().lower()

    if normalized_type == "memory":
        return MemoryStorageAdapter()

    if normalized_type in ("s3", "minio"):
        if not endpoint_url or not access_key or not secret_key:
            raise StorageError(
                f"创建 {normalized_type} 适配器失败：endpoint_url, "
                "access_key, secret_key 均为必填配置参数"
            )
        return S3StorageAdapter(
            endpoint_url=endpoint_url,
            access_key=access_key,
            secret_key=secret_key,
            region_name=region_name,
            secure=secure,
            client=client,
        )

    raise StorageError(f"不支持的对象存储类型: '{storage_type}'，仅支持 'memory', 's3', 'minio'")


__all__ = ["create_storage_adapter"]
