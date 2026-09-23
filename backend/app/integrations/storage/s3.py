"""S3 / MinIO 对象存储适配器实现模块。

严格遵循 AGENTS.md 规范：
- 适配层通过 Protocol 抽象接口与外部具体供应商解耦；
- 绝密脱敏红线：__repr__ 与日志输出中严禁打印 SecretKey 或文件二进制内容；
- 延迟/按需加载 boto3 驱动，环境缺失时安全抛出 StorageConnectionError；
- 底层 ClientError / 网络异常映射到项目统一业务异常基类 AppError。
"""

from collections.abc import Iterator
from typing import Any

from app.core.errors import StorageConnectionError, StorageError, StorageNotFoundError
from app.integrations.storage.protocol import StorageProtocol

_MIN_EXPIRES_IN_SECONDS: int = 1
# 7 天 = 7 * 24 * 3600 秒
_MAX_EXPIRES_IN_SECONDS: int = 604800
_DEFAULT_CHUNK_SIZE: int = 65536


class S3StorageAdapter(StorageProtocol):
    """面向 AWS S3 及兼容协议（如 MinIO、Ceph）的对象存储适配器。

    实现 StorageProtocol 抽象协议，封装 boto3 客户端调用并提供异常转译与凭证脱敏保护。
    """

    def __init__(
        self,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region_name: str = "us-east-1",
        secure: bool = True,
        session_token: str | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        """初始化 S3 / MinIO 适配器配置。

        Args:
            endpoint_url: 对象存储服务接入端点 URL。
            access_key: 访问凭据 Access Key ID。
            secret_key: 访问密钥 Secret Access Key。
            region_name: 部署地域，默认 "us-east-1"。
            secure: 是否启用 HTTPS 安全传输，默认 True。
            session_token: 可选临时凭据 Session Token。
            client: 可选外部注入客户端实例（测试桩）。

        Raises:
            StorageConnectionError: 当未显式提供 client 且运行环境中未安装 boto3 时抛出。
        """
        self.endpoint_url = endpoint_url
        self.access_key = access_key
        self.secret_key = secret_key
        self.region_name = region_name
        self.secure = secure
        self.session_token = session_token

        if client is not None:
            self._client = client
        else:
            self._client = self._init_client()

    def _init_client(self) -> Any:
        """延迟加载并创建 boto3 S3 客户端。

        Returns:
            Any: boto3.client("s3") 实例。

        Raises:
            StorageConnectionError: 当环境中缺少 boto3 库时抛出。
        """
        try:
            import boto3
            from botocore.client import Config
        except ImportError as exc:
            raise StorageConnectionError(
                "boto3 库未安装，无法初始化 S3StorageAdapter 对象存储适配器"
            ) from exc

        return boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            aws_session_token=self.session_token,
            region_name=self.region_name,
            use_ssl=self.secure,
            config=Config(signature_version="s3v4"),
        )

    @property
    def client(self) -> Any:
        """获取底层 boto3 S3 客户端。"""
        if self._client is None:
            self._client = self._init_client()
        return self._client

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

    def _translate_error(
        self,
        exc: Exception,
        bucket: str,
        key: str | None = None,
    ) -> StorageError:
        """将 boto3/botocore 底层异常转译为系统统一业务异常。

        Args:
            exc: 捕获的底层异常。
            bucket: 关联的存储桶名。
            key: 关联的对象键名。

        Returns:
            StorageError: 转译后的业务异常实例。
        """
        if isinstance(exc, StorageError):
            return exc

        error_code = ""
        http_status = 0
        response_obj = getattr(exc, "response", None)
        if isinstance(response_obj, dict):
            error_code = str(response_obj.get("Error", {}).get("Code", ""))
            http_status = int(response_obj.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))

        target_desc = f"bucket='{bucket}', key='{key}'" if key else f"bucket='{bucket}'"

        if error_code in ("404", "NoSuchKey", "NoSuchBucket", "NotFound") or http_status == 404:
            return StorageNotFoundError(
                f"请求的存储对象不存在: {target_desc}",
                details={"code": error_code, "status": http_status, "raw_error": str(exc)},
            )

        exc_type_name = type(exc).__name__
        if (
            "Connection" in exc_type_name
            or "Timeout" in exc_type_name
            or error_code
            in ("EndpointConnectionError", "ConnectTimeoutError", "ConnectionRefusedError")
            or (500 <= http_status < 600)
        ):
            return StorageConnectionError(
                f"对象存储服务连接或服务异常: {exc}",
                details={"code": error_code, "status": http_status, "raw_error": str(exc)},
            )

        return StorageError(
            f"对象存储操作失败: {exc}",
            details={"code": error_code, "status": http_status, "raw_error": str(exc)},
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
            StorageError: 写入失败或存储异常。
        """
        self._validate_bucket_and_key(bucket, key)
        try:
            self.client.put_object(
                Bucket=bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
            return key
        except Exception as exc:
            raise self._translate_error(exc, bucket, key) from exc

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
        self._validate_bucket_and_key(bucket, key)
        try:
            response = self.client.get_object(Bucket=bucket, Key=key)
            body = response["Body"]
            return bytes(body.read())
        except Exception as exc:
            raise self._translate_error(exc, bucket, key) from exc

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
            StorageError: 读取中断或网络异常。
        """
        self._validate_bucket_and_key(bucket, key)
        actual_chunk_size = chunk_size if chunk_size > 0 else _DEFAULT_CHUNK_SIZE
        try:
            response = self.client.get_object(Bucket=bucket, Key=key)
            body = response["Body"]
            if hasattr(body, "iter_chunks"):
                for chunk in body.iter_chunks(chunk_size=actual_chunk_size):
                    yield bytes(chunk)
            else:
                while True:
                    chunk = body.read(actual_chunk_size)
                    if not chunk:
                        break
                    yield bytes(chunk)
        except Exception as exc:
            raise self._translate_error(exc, bucket, key) from exc

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
        self._validate_bucket_and_key(bucket, key)
        self._validate_expires_in(expires_in)
        try:
            url: str = self.client.generate_presigned_url(
                ClientMethod="put_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in,
            )
            return url
        except Exception as exc:
            raise self._translate_error(exc, bucket, key) from exc

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
            StorageError: 签名生成失败或 expires_in 非法。
        """
        self._validate_bucket_and_key(bucket, key)
        self._validate_expires_in(expires_in)
        try:
            url: str = self.client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in,
            )
            return url
        except Exception as exc:
            raise self._translate_error(exc, bucket, key) from exc

    def delete_object(self, bucket: str, key: str) -> bool:
        """删除指定的存储对象（具备幂等性）。

        Args:
            bucket: 存储桶名称。
            key: 待删除的对象键路径。

        Returns:
            bool: 删除成功返回 True。

        Raises:
            StorageError: 存储服务拒绝或删除失败。
        """
        self._validate_bucket_and_key(bucket, key)
        try:
            self.client.delete_object(Bucket=bucket, Key=key)
            return True
        except Exception as exc:
            raise self._translate_error(exc, bucket, key) from exc

    def object_exists(self, bucket: str, key: str) -> bool:
        """检查指定的存储对象是否存在。

        Args:
            bucket: 存储桶名称。
            key: 目标对象键路径。

        Returns:
            bool: 存在返回 True，不存在返回 False。

        Raises:
            StorageError: 网络或鉴权异常。
        """
        self._validate_bucket_and_key(bucket, key)
        try:
            self.client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception as exc:
            translated = self._translate_error(exc, bucket, key)
            if isinstance(translated, StorageNotFoundError):
                return False
            raise translated from exc

    def ensure_bucket_exists(self, bucket: str) -> None:
        """确保存储桶已就绪，不存在则自动创建。

        Args:
            bucket: 目标存储桶名称。

        Raises:
            StorageError: 创建失败或权限不足。
        """
        self._validate_bucket_and_key(bucket)
        try:
            self.client.head_bucket(Bucket=bucket)
            return
        except Exception as exc:
            translated = self._translate_error(exc, bucket)
            if not isinstance(translated, StorageNotFoundError):
                raise translated from exc

        try:
            self.client.create_bucket(Bucket=bucket)
        except Exception as create_exc:
            raise self._translate_error(create_exc, bucket) from create_exc

    def __repr__(self) -> str:
        """返回适配器描述（绝密脱敏保护，严禁明文输出 secret_key）。"""
        return (
            f"S3StorageAdapter(endpoint_url='{self.endpoint_url}', "
            f"access_key='{self.access_key}', secret_key='******', "
            f"region_name='{self.region_name}', secure={self.secure})"
        )

    def __str__(self) -> str:
        """字符串表示，遵循与 repr 一致的脱敏规范。"""
        return self.__repr__()


# MinIO 与 AWS S3 兼容实现别名
MinioStorageAdapter = S3StorageAdapter

__all__ = [
    "MinioStorageAdapter",
    "S3StorageAdapter",
]
