"""对象存储适配器抽象协议定义模块。

严格遵循 AGENTS.md 规范：
- 适配层通过 Protocol 抽象接口与外部供应商解耦；
- 纯协议定义，无任何框架、网络驱动或业务服务依赖；
- 支持运行时类型检查与多态注入。
"""

from collections.abc import Iterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageProtocol(Protocol):
    """对象存储适配器抽象协议契约。

    定义与具体底层存储介质（如 MinIO、AWS S3、内存 Fake）无关的标准对象存储交互方法。
    """

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
            str: 对象的唯一标识键或版本路径。

        Raises:
            StorageError: 写入失败或存储异常。
        """
        ...

    def get_object(self, bucket: str, key: str) -> bytes:
        """全量获取对象的二进制内容。

        Args:
            bucket: 存储桶名称。
            key: 存储对象键路径。

        Returns:
            bytes: 对象完整二进制内容。

        Raises:
            StorageNotFoundError: 对象或存储桶不存在。
            StorageError: 读取失败或连接异常。
        """
        ...

    def get_object_stream(
        self,
        bucket: str,
        key: str,
        chunk_size: int = 65536,
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
            StorageError: 读取中断或网络异常。
        """
        ...

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
            StorageError: 签名生成失败或 expires_in 非法。
        """
        ...

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
            StorageNotFoundError: 对象不存在（可选校验）。
            StorageError: 签名生成失败或 expires_in 非法。
        """
        ...

    def delete_object(self, bucket: str, key: str) -> bool:
        """删除指定的存储对象。

        Args:
            bucket: 存储桶名称。
            key: 待删除的对象键路径。

        Returns:
            bool: 删除成功返回 True；若对象原先不存在亦返回 True（具备幂等性）。

        Raises:
            StorageError: 存储服务拒绝或删除失败。
        """
        ...

    def object_exists(self, bucket: str, key: str) -> bool:
        """检查指定的存储对象是否存在。

        Args:
            bucket: 存储桶名称。
            key: 目标对象键路径。

        Returns:
            bool: 存在返回 True，不存在返回 False。

        Raises:
            StorageError: 网络或存储异常。
        """
        ...

    def ensure_bucket_exists(self, bucket: str) -> None:
        """确保存储桶已就绪，不存在则自动创建。

        Args:
            bucket: 目标存储桶名称。

        Raises:
            StorageError: 创建失败或权限不足。
        """
        ...


__all__ = ["StorageProtocol"]
