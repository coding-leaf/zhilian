"""对象存储适配器模块。

导出 StorageProtocol 抽象协议契约、MemoryStorageAdapter 虚拟内存实现、
S3StorageAdapter / MinioStorageAdapter 生产适配器与工厂函数。
"""

from app.integrations.storage.factory import create_storage_adapter
from app.integrations.storage.memory import MemoryStorageAdapter
from app.integrations.storage.protocol import StorageProtocol
from app.integrations.storage.s3 import MinioStorageAdapter, S3StorageAdapter

__all__ = [
    "MemoryStorageAdapter",
    "MinioStorageAdapter",
    "S3StorageAdapter",
    "StorageProtocol",
    "create_storage_adapter",
]
