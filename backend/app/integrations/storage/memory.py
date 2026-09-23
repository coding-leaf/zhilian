"""内存虚拟对象存储适配器实现模块。

严格遵循 AGENTS.md 规范：
- 专为单元测试与本地开发环境提供高性能内存 Fake 实现；
- 单元测试运行在网络绝对阻断环境下，零套接字连接；
- 并发安全（采用 threading.Lock 保护状态字典）；
- 具备模拟故障注入与调用延迟注入能力，支持异常重试与超时测试；
- 绝密脱敏保护：__repr__ 禁止打印任何对象二进制内容。
"""

import hashlib
import threading
import time
from collections.abc import Iterator

from app.core.errors import StorageError, StorageNotFoundError
from app.integrations.storage.protocol import StorageProtocol

_MIN_EXPIRES_IN_SECONDS: int = 1
# 7 天 = 7 * 24 * 3600 秒
_MAX_EXPIRES_IN_SECONDS: int = 604800
_DEFAULT_CHUNK_SIZE: int = 65536


class MemoryStorageAdapter(StorageProtocol):
    """基于内存的并发安全虚拟对象存储适配器。

    实现 StorageProtocol 协议，支持测试桩注入与时效拦截。
    """

    def __init__(self) -> None:
        """初始化内存对象存储适配器状态。"""
        self._lock = threading.Lock()
        self._buckets: set[str] = set()
        self._objects: dict[str, dict[str, tuple[bytes, str]]] = {}
        self._fault_injections: dict[str, Exception] = {}
        self._latency_seconds: float = 0.0

    def _check_hooks(self, method_name: str) -> None:
        """检查并触发注入的模拟故障与延迟。

        Args:
            method_name: 当前正在执行的方法名。

        Raises:
            Exception: 若该方法被注入故障，则直接抛出注入的异常。
        """
        if self._latency_seconds > 0.0:
            time.sleep(self._latency_seconds)

        if method_name in self._fault_injections:
            raise self._fault_injections[method_name]

    @staticmethod
    def _validate_bucket_and_key(bucket: str, key: str | None = None) -> None:
        """校验存储桶名与对象键合法性。

        Args:
            bucket: 存储桶名称。
            key: 存储对象键（可选）。

        Raises:
            StorageError: 当桶名或对象键为空时抛出。
        """
        if not bucket or not bucket.strip():
            raise StorageError("存储桶名称不能为空")
        if key is not None and (not key or not key.strip()):
            raise StorageError("存储对象键路径不能为空")

    @staticmethod
    def _validate_expires_in(expires_in: int) -> None:
        """校验预签名有效期。

        Args:
            expires_in: 凭证有效期（秒）。

        Raises:
            StorageError: 当有效期超出 1~604800 秒范围时抛出。
        """
        if expires_in < _MIN_EXPIRES_IN_SECONDS or expires_in > _MAX_EXPIRES_IN_SECONDS:
            raise StorageError(
                f"预签名 URL 有效期必须在 {_MIN_EXPIRES_IN_SECONDS} 到 "
                f"{_MAX_EXPIRES_IN_SECONDS} 秒之间，当前值为: {expires_in}"
            )

    def put_object(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """上传对象到指定存储桶。

        Args:
            bucket: 存储桶名称。
            key: 存储对象的完整键路径。
            data: 待写入的二进制字节数据。
            content_type: 对象的 MIME 类型，默认 "application/octet-stream"。

        Returns:
            str: 对象的唯一标识键。

        Raises:
            StorageError: 写入失败或参数非法。
        """
        self._check_hooks("put_object")
        self._validate_bucket_and_key(bucket, key)

        with self._lock:
            self._buckets.add(bucket)
            if bucket not in self._objects:
                self._objects[bucket] = {}
            self._objects[bucket][key] = (bytes(data), content_type)

        return key

    def get_object(self, bucket: str, key: str) -> bytes:
        """全量获取对象的二进制内容。

        Args:
            bucket: 存储桶名称。
            key: 存储对象键路径。

        Returns:
            bytes: 对象完整二进制内容。

        Raises:
            StorageNotFoundError: 对象或存储桶不存在。
            StorageError: 参数非法或存储故障。
        """
        self._check_hooks("get_object")
        self._validate_bucket_and_key(bucket, key)

        with self._lock:
            if bucket not in self._buckets or key not in self._objects.get(bucket, {}):
                raise StorageNotFoundError(f"请求的存储对象不存在: bucket='{bucket}', key='{key}'")
            return self._objects[bucket][key][0]

    def get_object_stream(
        self,
        bucket: str,
        key: str,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
    ) -> Iterator[bytes]:
        """流式分块读取对象内容。

        Args:
            bucket: 存储桶名称。
            key: 存储对象键路径。
            chunk_size: 单次分块字节数，默认 65536 (64KB)。

        Yields:
            Iterator[bytes]: 二进制分块生成器。

        Raises:
            StorageNotFoundError: 对象或存储桶不存在。
            StorageError: 参数非法或存储故障。
        """
        self._check_hooks("get_object_stream")
        data = self.get_object(bucket, key)
        actual_chunk_size = chunk_size if chunk_size > 0 else _DEFAULT_CHUNK_SIZE

        for offset in range(0, len(data), actual_chunk_size):
            yield data[offset : offset + actual_chunk_size]

    def generate_presigned_upload_url(
        self,
        bucket: str,
        key: str,
        expires_in: int = 900,
    ) -> str:
        """生成供客户端直传的预签名上传 URL。

        Args:
            bucket: 存储桶名称。
            key: 待上传的目标对象键路径。
            expires_in: 凭证有效期（秒），默认 900 秒（15 分钟）。

        Returns:
            str: 带有认证签名参数的完整 URL。

        Raises:
            StorageError: 参数校验不通过或生成失败。
        """
        self._check_hooks("generate_presigned_upload_url")
        self._validate_bucket_and_key(bucket, key)
        self._validate_expires_in(expires_in)

        token_source = f"upload:{bucket}:{key}:{expires_in}".encode()
        mock_signature = hashlib.sha256(token_source).hexdigest()[:16]
        return (
            f"https://mock-storage.local/{bucket}/{key}?"
            f"X-Amz-Algorithm=AWS4-HMAC-SHA256&"
            f"X-Amz-Expires={expires_in}&"
            f"X-Amz-Signature=mock-{mock_signature}"
        )

    def generate_presigned_download_url(
        self,
        bucket: str,
        key: str,
        expires_in: int = 900,
    ) -> str:
        """生成供客户端直接下载/读取的预签名下载 URL。

        Args:
            bucket: 存储桶名称。
            key: 目标对象键路径。
            expires_in: 凭证有效期（秒），默认 900 秒（15 分钟）。

        Returns:
            str: 带有认证签名参数的完整下载 URL。

        Raises:
            StorageError: 参数校验不通过或生成失败。
        """
        self._check_hooks("generate_presigned_download_url")
        self._validate_bucket_and_key(bucket, key)
        self._validate_expires_in(expires_in)

        token_source = f"download:{bucket}:{key}:{expires_in}".encode()
        mock_signature = hashlib.sha256(token_source).hexdigest()[:16]
        return (
            f"https://mock-storage.local/{bucket}/{key}?"
            f"X-Amz-Algorithm=AWS4-HMAC-SHA256&"
            f"X-Amz-Expires={expires_in}&"
            f"X-Amz-Signature=mock-{mock_signature}"
        )

    def delete_object(self, bucket: str, key: str) -> bool:
        """删除指定的存储对象（具备幂等性）。

        Args:
            bucket: 存储桶名称。
            key: 待删除的对象键路径。

        Returns:
            bool: 无论对象是否存在均返回 True。

        Raises:
            StorageError: 参数校验失败或故障注入。
        """
        self._check_hooks("delete_object")
        self._validate_bucket_and_key(bucket, key)

        with self._lock:
            if bucket in self._objects and key in self._objects[bucket]:
                del self._objects[bucket][key]

        return True

    def object_exists(self, bucket: str, key: str) -> bool:
        """检查指定的存储对象是否存在。

        Args:
            bucket: 存储桶名称。
            key: 目标对象键路径。

        Returns:
            bool: 存在返回 True，不存在返回 False。

        Raises:
            StorageError: 参数校验失败或故障注入。
        """
        self._check_hooks("object_exists")
        self._validate_bucket_and_key(bucket, key)

        with self._lock:
            return bucket in self._objects and key in self._objects[bucket]

    def ensure_bucket_exists(self, bucket: str) -> None:
        """确保存储桶已就绪，不存在则自动创建。

        Args:
            bucket: 目标存储桶名称。

        Raises:
            StorageError: 参数校验失败或故障注入。
        """
        self._check_hooks("ensure_bucket_exists")
        self._validate_bucket_and_key(bucket)

        with self._lock:
            self._buckets.add(bucket)
            if bucket not in self._objects:
                self._objects[bucket] = {}

    def inject_failure(self, method_name: str, exception: Exception) -> None:
        """为特定方法注入异常以模拟故障。

        Args:
            method_name: 目标方法名称（如 "get_object"）。
            exception: 待触发的异常实例。
        """
        self._fault_injections[method_name] = exception

    def clear_failure(self, method_name: str | None = None) -> None:
        """清除注入的故障。

        Args:
            method_name: 目标方法名；若为 None 则清除全部注入故障。
        """
        if method_name is None:
            self._fault_injections.clear()
        else:
            self._fault_injections.pop(method_name, None)

    def inject_latency(self, seconds: float) -> None:
        """为所有调用注入耗时延迟以模拟网络延时。

        Args:
            seconds: 延迟秒数。
        """
        self._latency_seconds = max(0.0, seconds)

    def clear(self) -> None:
        """清空所有存储桶、对象数据与测试注入状态。"""
        with self._lock:
            self._buckets.clear()
            self._objects.clear()
            self._fault_injections.clear()
            self._latency_seconds = 0.0

    def __repr__(self) -> str:
        """返回适配器状态摘要（绝密脱敏保护，禁止打印字节内容）。"""
        with self._lock:
            bucket_count = len(self._buckets)
            object_count = sum(len(objs) for objs in self._objects.values())
        return f"MemoryStorageAdapter(buckets={bucket_count}, objects={object_count})"


__all__ = ["MemoryStorageAdapter"]
