"""对象存储适配器单元测试套件。

涵盖：
- MemoryStorageAdapter 完整 CRUD、分块流式读取与字节一致性；
- 预签名上传/下载 URL 生成与时效边界（1, 900, 604800 及越界抛错）；
- 故障注入与延迟注入测试；
- 多线程并发安全性测试；
- S3StorageAdapter 绝密脱敏 repr 验证；
- S3StorageAdapter 在缺少 boto3 依赖时的防御捕获；
- S3StorageAdapter 客户端交互与 ClientError 异常转译 (404, 502/503, 403)；
- create_storage_adapter 工厂函数类型分发与参数校验。
"""

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.core.errors import (
    AppError,
    StorageConnectionError,
    StorageError,
    StorageNotFoundError,
)
from app.integrations.storage import (
    MemoryStorageAdapter,
    MinioStorageAdapter,
    S3StorageAdapter,
    StorageProtocol,
    create_storage_adapter,
)


class DummyStreamBody:
    """模拟支持 iter_chunks 的响应体。"""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self, amt: int | None = None) -> bytes:
        if amt is None:
            return self._data
        return self._data[:amt]

    def iter_chunks(self, chunk_size: int = 65536):
        for i in range(0, len(self._data), chunk_size):
            yield self._data[i : i + chunk_size]


class DummyPlainBody:
    """模拟仅支持 read() 的纯流响应体。"""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    def read(self, amt: int = -1) -> bytes:
        if amt < 0:
            res = self._data[self._offset :]
            self._offset = len(self._data)
            return res
        res = self._data[self._offset : self._offset + amt]
        self._offset += len(res)
        return res


class MockClientError(Exception):
    """模拟 botocore.exceptions.ClientError 结构。"""

    def __init__(self, code: str, http_status: int, message: str = "Client error") -> None:
        super().__init__(f"An error occurred ({code}) when calling operation: {message}")
        self.response = {
            "Error": {"Code": code, "Message": message},
            "ResponseMetadata": {"HTTPStatusCode": http_status},
        }


# ============================================================================
# 1. 异常定义测试
# ============================================================================


def test_storage_errors_hierarchy() -> None:
    """测试存储异常类的继承关系与默认错误码。"""
    err = StorageError()
    assert issubclass(StorageError, AppError)
    assert err.error_code == 30001
    assert err.status_code == 500
    assert err.message == "对象存储服务异常"

    not_found = StorageNotFoundError()
    assert issubclass(StorageNotFoundError, StorageError)
    assert not_found.error_code == 30002
    assert not_found.status_code == 404
    assert not_found.message == "请求的存储对象不存在"

    conn_err = StorageConnectionError()
    assert issubclass(StorageConnectionError, StorageError)
    assert conn_err.error_code == 30003
    assert conn_err.status_code == 503
    assert conn_err.message == "对象存储服务连接失败"


# ============================================================================
# 2. MemoryStorageAdapter 基础功能与 CRUD 测试
# ============================================================================


def test_memory_adapter_implements_protocol() -> None:
    """验证 MemoryStorageAdapter 满足 StorageProtocol 运行时检查。"""
    adapter = MemoryStorageAdapter()
    assert isinstance(adapter, StorageProtocol)


def test_memory_adapter_put_and_get() -> None:
    """测试内存存储对象的写入与全量读取。"""
    adapter = MemoryStorageAdapter()
    bucket = "test-bucket"
    key = "documents/sample.pdf"
    content = b"%PDF-1.4 test binary data"

    result_key = adapter.put_object(bucket, key, content, content_type="application/pdf")
    assert result_key == key

    read_data = adapter.get_object(bucket, key)
    assert read_data == content


def test_memory_adapter_get_nonexistent_raises_404() -> None:
    """测试读取不存在的对象或桶时抛出 StorageNotFoundError。"""
    adapter = MemoryStorageAdapter()
    with pytest.raises(StorageNotFoundError) as exc_info:
        adapter.get_object("nonexistent-bucket", "file.txt")
    assert exc_info.value.error_code == 30002
    assert exc_info.value.status_code == 404

    adapter.ensure_bucket_exists("existing-bucket")
    with pytest.raises(StorageNotFoundError) as exc_info2:
        adapter.get_object("existing-bucket", "not_there.txt")
    assert exc_info2.value.error_code == 30002


def test_memory_adapter_object_exists_and_delete() -> None:
    """测试对象的存在性检查与幂等删除。"""
    adapter = MemoryStorageAdapter()
    bucket = "assets"
    key = "img/banner.png"

    assert not adapter.object_exists(bucket, key)

    adapter.put_object(bucket, key, b"fake-png-bytes")
    assert adapter.object_exists(bucket, key)

    # 首次删除存在对象返回 True
    assert adapter.delete_object(bucket, key) is True
    assert not adapter.object_exists(bucket, key)

    # 再次删除已不存在的对象依然幂等返回 True
    assert adapter.delete_object(bucket, key) is True


def test_memory_adapter_ensure_bucket_exists() -> None:
    """测试确保存储桶存在逻辑。"""
    adapter = MemoryStorageAdapter()
    bucket = "new-bucket"
    adapter.ensure_bucket_exists(bucket)
    assert "new-bucket" in repr(adapter) or "buckets=1" in repr(adapter)

    # 重复调用幂等不报错
    adapter.ensure_bucket_exists(bucket)


def test_memory_adapter_parameter_validation() -> None:
    """测试入参校验（桶名或对象键为空时报错）。"""
    adapter = MemoryStorageAdapter()

    with pytest.raises(StorageError, match="存储桶名称不能为空"):
        adapter.put_object("", "file.txt", b"data")

    with pytest.raises(StorageError, match="存储桶名称不能为空"):
        adapter.get_object("   ", "file.txt")

    with pytest.raises(StorageError, match="存储对象键路径不能为空"):
        adapter.put_object("b", "", b"data")

    with pytest.raises(StorageError, match="存储对象键路径不能为空"):
        adapter.get_object("b", "   ")


# ============================================================================
# 3. 流式分块读取与完整性测试
# ============================================================================


def test_memory_adapter_stream_chunking() -> None:
    """测试流式读取的分块大小与数据重组一致性。"""
    adapter = MemoryStorageAdapter()
    bucket = "media"
    key = "video.mp4"
    # 构造 150KB 测试数据
    payload = b"X" * 150000

    adapter.put_object(bucket, key, payload)

    # 按 64KB (65536 字节) 分块
    chunks = list(adapter.get_object_stream(bucket, key, chunk_size=65536))
    assert len(chunks) == 3
    assert len(chunks[0]) == 65536
    assert len(chunks[1]) == 65536
    assert len(chunks[2]) == 150000 - 65536 * 2

    # 重组后字节一致
    reassembled = b"".join(chunks)
    assert reassembled == payload


def test_memory_adapter_stream_invalid_chunk_size_defaults() -> None:
    """当 chunk_size <= 0 时自动回退至默认分块大小。"""
    adapter = MemoryStorageAdapter()
    bucket = "media"
    key = "test.bin"
    payload = b"A" * 100000

    adapter.put_object(bucket, key, payload)
    chunks = list(adapter.get_object_stream(bucket, key, chunk_size=-1))
    assert b"".join(chunks) == payload
    assert len(chunks[0]) == 65536


# ============================================================================
# 4. 预签名 URL 生成与时效边界拦截
# ============================================================================


def test_memory_adapter_presigned_urls() -> None:
    """测试上传与下载预签名 URL 的格式与包含签名参数。"""
    adapter = MemoryStorageAdapter()
    bucket = "docs"
    key = "guide.md"

    upload_url = adapter.generate_presigned_upload_url(bucket, key, expires_in=900)
    assert upload_url.startswith("https://mock-storage.local/docs/guide.md?")
    assert "X-Amz-Expires=900" in upload_url
    assert "X-Amz-Signature=mock-" in upload_url

    download_url = adapter.generate_presigned_download_url(bucket, key, expires_in=300)
    assert download_url.startswith("https://mock-storage.local/docs/guide.md?")
    assert "X-Amz-Expires=300" in download_url
    assert "X-Amz-Signature=mock-" in download_url


@pytest.mark.parametrize("invalid_expiry", [0, -1, 604801, 1000000])
def test_memory_presigned_url_expiry_out_of_bounds(invalid_expiry: int) -> None:
    """预签名有效时间必须在 1~604800 秒之间，越界抛出 StorageError。"""
    adapter = MemoryStorageAdapter()
    with pytest.raises(StorageError, match="有效期必须在 1 到 604800 秒之间"):
        adapter.generate_presigned_upload_url("b", "k", expires_in=invalid_expiry)

    with pytest.raises(StorageError, match="有效期必须在 1 到 604800 秒之间"):
        adapter.generate_presigned_download_url("b", "k", expires_in=invalid_expiry)


def test_memory_presigned_url_valid_boundary() -> None:
    """边界值 1 与 604800 秒正常通过。"""
    adapter = MemoryStorageAdapter()
    url1 = adapter.generate_presigned_upload_url("b", "k", expires_in=1)
    assert "X-Amz-Expires=1" in url1

    url2 = adapter.generate_presigned_download_url("b", "k", expires_in=604800)
    assert "X-Amz-Expires=604800" in url2


# ============================================================================
# 5. 故障注入与延迟注入
# ============================================================================


def test_memory_adapter_fault_injection() -> None:
    """测试通过 inject_failure 模拟下游异常并验证恢复机制。"""
    adapter = MemoryStorageAdapter()
    adapter.put_object("b", "k", b"hello")

    # 注入异常
    simulated_err = StorageError("Simulated network blip", error_code=30001)
    adapter.inject_failure("get_object", simulated_err)

    with pytest.raises(StorageError, match="Simulated network blip"):
        adapter.get_object("b", "k")

    # 清除单个方法的异常注入
    adapter.clear_failure("get_object")
    assert adapter.get_object("b", "k") == b"hello"


def test_memory_adapter_latency_injection() -> None:
    """测试通过 inject_latency 注入延时。"""
    adapter = MemoryStorageAdapter()
    adapter.inject_latency(0.05)

    start_time = time.perf_counter()
    adapter.ensure_bucket_exists("b")
    elapsed = time.perf_counter() - start_time

    assert elapsed >= 0.045

    # 清空适配器状态
    adapter.clear()
    start_time2 = time.perf_counter()
    adapter.ensure_bucket_exists("b")
    elapsed2 = time.perf_counter() - start_time2
    assert elapsed2 < 0.04


# ============================================================================
# 6. 多线程并发安全性
# ============================================================================


def test_memory_adapter_concurrency() -> None:
    """测试多线程并发写入时无竞态损坏。"""
    adapter = MemoryStorageAdapter()
    bucket = "concurrent-bucket"
    num_threads = 10
    items_per_thread = 20

    def worker(thread_idx: int) -> None:
        for i in range(items_per_thread):
            key = f"thread_{thread_idx}/item_{i}.txt"
            data = f"data from thread {thread_idx} item {i}".encode()
            adapter.put_object(bucket, key, data)

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, t) for t in range(num_threads)]
        for f in futures:
            f.result()

    # 验证写入总数
    assert "objects=200" in repr(adapter)
    for t in range(num_threads):
        for i in range(items_per_thread):
            key = f"thread_{t}/item_{i}.txt"
            assert adapter.object_exists(bucket, key)
            expected = f"data from thread {t} item {i}".encode()
            assert adapter.get_object(bucket, key) == expected


def test_memory_adapter_repr_security() -> None:
    """验证 MemoryStorageAdapter 的 repr 不泄露数据内容。"""
    adapter = MemoryStorageAdapter()
    adapter.put_object("b", "k", b"super_secret_raw_content")
    repr_str = repr(adapter)
    assert "super_secret_raw_content" not in repr_str
    assert "buckets=1" in repr_str
    assert "objects=1" in repr_str


# ============================================================================
# 7. S3StorageAdapter 绝密脱敏与环境依赖防御
# ============================================================================


def test_s3_adapter_secret_key_masked() -> None:
    """S3 适配器 repr 和 str 中 secret_key 必须强制显示为 ******。"""
    mock_client = MagicMock()
    adapter = S3StorageAdapter(
        endpoint_url="https://s3.example.com",
        access_key="AKIA12345678",
        secret_key="my_super_secret_key_999",  # noqa: S106
        region_name="ap-southeast-1",
        secure=True,
        client=mock_client,
    )

    repr_output = repr(adapter)
    str_output = str(adapter)

    assert "my_super_secret_key_999" not in repr_output
    assert "secret_key='******'" in repr_output
    assert "my_super_secret_key_999" not in str_output
    assert "secret_key='******'" in str_output
    assert "AKIA12345678" in repr_output
    assert "https://s3.example.com" in repr_output


def test_s3_adapter_missing_boto3_raises_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """当运行环境缺少 boto3 时实例化未注入 client 的适配器抛出 StorageConnectionError。"""
    import builtins

    real_import = builtins.__import__

    def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "boto3":
            raise ImportError("No module named boto3")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    with pytest.raises(StorageConnectionError, match="boto3 库未安装"):
        S3StorageAdapter(
            endpoint_url="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",  # noqa: S106
        )


def test_s3_adapter_implements_protocol() -> None:
    """验证注入 client 的 S3StorageAdapter 满足 StorageProtocol 契约。"""
    mock_client = MagicMock()
    adapter = S3StorageAdapter(
        endpoint_url="http://localhost:9000",
        access_key="ak",
        secret_key="sk",  # noqa: S106
        client=mock_client,
    )
    assert isinstance(adapter, StorageProtocol)
    assert MinioStorageAdapter is S3StorageAdapter


# ============================================================================
# 8. S3StorageAdapter 客户端交互与异常转译
# ============================================================================


def test_s3_adapter_put_and_get_success() -> None:
    """测试 S3StorageAdapter 调用底层 client 的 put_object 和 get_object。"""
    mock_client = MagicMock()
    mock_client.put_object.return_value = {"ETag": '"xyz"'}
    mock_client.get_object.return_value = {"Body": DummyPlainBody(b"s3 file content")}

    adapter = S3StorageAdapter("http://minio", "ak", "sk", client=mock_client)

    # put_object
    ret = adapter.put_object("my-bucket", "path/file.txt", b"s3 file content", "text/plain")
    assert ret == "path/file.txt"
    mock_client.put_object.assert_called_once_with(
        Bucket="my-bucket",
        Key="path/file.txt",
        Body=b"s3 file content",
        ContentType="text/plain",
    )

    # get_object
    data = adapter.get_object("my-bucket", "path/file.txt")
    assert data == b"s3 file content"
    mock_client.get_object.assert_called_once_with(Bucket="my-bucket", Key="path/file.txt")


def test_s3_adapter_get_stream_with_iter_chunks() -> None:
    """测试 S3StorageAdapter 流式读取（优先使用 iter_chunks）。"""
    mock_client = MagicMock()
    mock_client.get_object.return_value = {"Body": DummyStreamBody(b"1234567890")}

    adapter = S3StorageAdapter("http://minio", "ak", "sk", client=mock_client)
    chunks = list(adapter.get_object_stream("b", "k", chunk_size=4))
    assert chunks == [b"1234", b"5678", b"90"]


def test_s3_adapter_get_stream_with_plain_read() -> None:
    """测试 S3StorageAdapter 流式读取（降级使用 read()）。"""
    mock_client = MagicMock()
    mock_client.get_object.return_value = {"Body": DummyPlainBody(b"abcdefghij")}

    adapter = S3StorageAdapter("http://minio", "ak", "sk", client=mock_client)
    chunks = list(adapter.get_object_stream("b", "k", chunk_size=3))
    assert chunks == [b"abc", b"def", b"ghi", b"j"]


def test_s3_adapter_presigned_urls() -> None:
    """测试 S3StorageAdapter 预签名 URL 生成与时效拦截。"""
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "https://s3.example.com/b/k?signed=1"

    adapter = S3StorageAdapter("http://minio", "ak", "sk", client=mock_client)

    url1 = adapter.generate_presigned_upload_url("b", "k", expires_in=600)
    assert url1 == "https://s3.example.com/b/k?signed=1"
    mock_client.generate_presigned_url.assert_called_with(
        ClientMethod="put_object",
        Params={"Bucket": "b", "Key": "k"},
        ExpiresIn=600,
    )

    url2 = adapter.generate_presigned_download_url("b", "k", expires_in=1200)
    assert url2 == "https://s3.example.com/b/k?signed=1"
    mock_client.generate_presigned_url.assert_called_with(
        ClientMethod="get_object",
        Params={"Bucket": "b", "Key": "k"},
        ExpiresIn=1200,
    )

    # 边界越界校验
    with pytest.raises(StorageError, match="有效期必须在 1 到 604800 秒之间"):
        adapter.generate_presigned_upload_url("b", "k", expires_in=0)
    with pytest.raises(StorageError, match="有效期必须在 1 到 604800 秒之间"):
        adapter.generate_presigned_download_url("b", "k", expires_in=604801)


def test_s3_adapter_delete_object() -> None:
    """测试 S3StorageAdapter 删除对象。"""
    mock_client = MagicMock()
    adapter = S3StorageAdapter("http://minio", "ak", "sk", client=mock_client)

    assert adapter.delete_object("b", "k") is True
    mock_client.delete_object.assert_called_once_with(Bucket="b", Key="k")


def test_s3_adapter_object_exists() -> None:
    """测试 S3StorageAdapter 检查对象存在。"""
    mock_client = MagicMock()
    adapter = S3StorageAdapter("http://minio", "ak", "sk", client=mock_client)

    # 对象存在
    mock_client.head_object.return_value = {"ContentLength": 100}
    assert adapter.object_exists("b", "k") is True

    # 对象不存在 (404 NoSuchKey)
    mock_client.head_object.side_effect = MockClientError("NoSuchKey", 404)
    assert adapter.object_exists("b", "k") is False

    # 其他严重异常（如 500）应被正确转译抛出
    mock_client.head_object.side_effect = MockClientError("InternalError", 500)
    with pytest.raises(StorageConnectionError):
        adapter.object_exists("b", "k")


def test_s3_adapter_ensure_bucket_exists() -> None:
    """测试确保存储桶已就绪。"""
    mock_client = MagicMock()
    adapter = S3StorageAdapter("http://minio", "ak", "sk", client=mock_client)

    # 桶已存在
    mock_client.head_bucket.return_value = {}
    adapter.ensure_bucket_exists("b")
    mock_client.create_bucket.assert_not_called()

    # 桶不存在 (404) -> 触发自动创建
    mock_client.head_bucket.side_effect = MockClientError("NoSuchBucket", 404)
    adapter.ensure_bucket_exists("b")
    mock_client.create_bucket.assert_called_once_with(Bucket="b")


def test_s3_adapter_ensure_bucket_exists_create_error() -> None:
    """测试创建存储桶失败时转译异常。"""
    mock_client = MagicMock()
    adapter = S3StorageAdapter("http://minio", "ak", "sk", client=mock_client)

    mock_client.head_bucket.side_effect = MockClientError("NoSuchBucket", 404)
    mock_client.create_bucket.side_effect = MockClientError("AccessDenied", 403)

    with pytest.raises(StorageError) as exc_info:
        adapter.ensure_bucket_exists("b")
    assert exc_info.value.error_code == 30001


def test_s3_adapter_error_translations() -> None:
    """测试 ClientError 到标准异常体系的完整转译映射。"""
    mock_client = MagicMock()
    adapter = S3StorageAdapter("http://minio", "ak", "sk", client=mock_client)

    # 1. 404 映射为 StorageNotFoundError
    mock_client.get_object.side_effect = MockClientError("NoSuchKey", 404)
    with pytest.raises(StorageNotFoundError) as exc_404:
        adapter.get_object("b", "k")
    assert exc_404.value.error_code == 30002
    assert exc_404.value.status_code == 404

    # 2. 503 映射为 StorageConnectionError
    mock_client.get_object.side_effect = MockClientError("ServiceUnavailable", 503)
    with pytest.raises(StorageConnectionError) as exc_503:
        adapter.get_object("b", "k")
    assert exc_503.value.error_code == 30003
    assert exc_503.value.status_code == 503

    # 3. 403 映射为 StorageError
    mock_client.get_object.side_effect = MockClientError("AccessDenied", 403)
    with pytest.raises(StorageError) as exc_403:
        adapter.get_object("b", "k")
    assert exc_403.value.error_code == 30001

    # 4. 连接超时/连接失败名称映射
    class EndpointConnectionError(Exception):
        pass

    mock_client.get_object.side_effect = EndpointConnectionError("Connection timed out")
    with pytest.raises(StorageConnectionError):
        adapter.get_object("b", "k")


def test_s3_adapter_param_validation() -> None:
    """S3 适配器入参校验。"""
    mock_client = MagicMock()
    adapter = S3StorageAdapter("http://minio", "ak", "sk", client=mock_client)

    with pytest.raises(StorageError, match="存储桶名称不能为空"):
        adapter.put_object("", "k", b"data")
    with pytest.raises(StorageError, match="存储对象键路径不能为空"):
        adapter.put_object("b", " ", b"data")
    with pytest.raises(StorageError, match="存储桶名称不能为空"):
        adapter.get_object("  ", "k")


# ============================================================================
# 9. 工厂函数 create_storage_adapter 测试
# ============================================================================


def test_create_storage_adapter_memory() -> None:
    """工厂分发创建内存适配器。"""
    adapter = create_storage_adapter("memory")
    assert isinstance(adapter, MemoryStorageAdapter)


def test_create_storage_adapter_s3_and_minio() -> None:
    """工厂分发创建 S3 / MinIO 适配器。"""
    mock_client = MagicMock()
    s3_adapter = create_storage_adapter(
        "s3",
        endpoint_url="http://s3.local",
        access_key="ak",
        secret_key="sk",  # noqa: S106
        client=mock_client,
    )
    assert isinstance(s3_adapter, S3StorageAdapter)

    minio_adapter = create_storage_adapter(
        "minio",
        endpoint_url="http://minio.local",
        access_key="ak",
        secret_key="sk",  # noqa: S106
        client=mock_client,
    )
    assert isinstance(minio_adapter, S3StorageAdapter)


def test_create_storage_adapter_missing_params() -> None:
    """配置缺失参数时抛出 StorageError。"""
    with pytest.raises(StorageError, match="必填配置参数"):
        create_storage_adapter("s3", endpoint_url="http://s3.local")


def test_create_storage_adapter_unknown_type() -> None:
    """不支持的存储类型抛出 StorageError。"""
    with pytest.raises(StorageError, match="不支持的对象存储类型"):
        create_storage_adapter("azure_blob")


def test_memory_adapter_clear_failure_all() -> None:
    """测试 clear_failure(None) 清除全部注入故障。"""
    adapter = MemoryStorageAdapter()
    adapter.inject_failure("put_object", StorageError("fail1"))
    adapter.inject_failure("get_object", StorageError("fail2"))
    adapter.clear_failure(None)
    adapter.put_object("b", "k", b"data")
    assert adapter.get_object("b", "k") == b"data"


def test_s3_adapter_str_and_translate_existing_error() -> None:
    """测试 S3 适配器 __str__ 与 _translate_error 遇到已有 StorageError 时的直通透传。"""
    mock_client = MagicMock()
    adapter = S3StorageAdapter("http://minio", "ak", "sk", client=mock_client)
    assert str(adapter) == repr(adapter)

    existing = StorageError("already storage error")
    assert adapter._translate_error(existing, "b", "k") is existing


def test_s3_adapter_operations_error_handling() -> None:
    """测试 S3StorageAdapter 各 API 在底层抛出异常时的转译捕获覆盖。"""
    mock_client = MagicMock()
    adapter = S3StorageAdapter("http://minio", "ak", "sk", client=mock_client)

    # put_object 异常
    mock_client.put_object.side_effect = MockClientError("AccessDenied", 403)
    with pytest.raises(StorageError):
        adapter.put_object("b", "k", b"data")

    # get_object_stream 异常
    mock_client.get_object.side_effect = MockClientError("NoSuchKey", 404)
    with pytest.raises(StorageNotFoundError):
        list(adapter.get_object_stream("b", "k"))

    # generate_presigned_upload_url 异常
    mock_client.generate_presigned_url.side_effect = MockClientError("InternalError", 500)
    with pytest.raises(StorageConnectionError):
        adapter.generate_presigned_upload_url("b", "k", expires_in=900)

    # generate_presigned_download_url 异常
    mock_client.generate_presigned_url.side_effect = MockClientError("InternalError", 500)
    with pytest.raises(StorageConnectionError):
        adapter.generate_presigned_download_url("b", "k", expires_in=900)

    # delete_object 异常
    mock_client.delete_object.side_effect = MockClientError("AccessDenied", 403)
    with pytest.raises(StorageError):
        adapter.delete_object("b", "k")


def test_s3_adapter_init_client_when_boto3_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """当运行环境存在 boto3 时，测试 S3StorageAdapter 正常通过 boto3.client 初始化。"""
    import sys

    mock_boto3 = MagicMock()
    mock_botocore = MagicMock()
    mock_botocore_client = MagicMock()

    monkeypatch.setitem(sys.modules, "boto3", mock_boto3)
    monkeypatch.setitem(sys.modules, "botocore", mock_botocore)
    monkeypatch.setitem(sys.modules, "botocore.client", mock_botocore_client)

    adapter = S3StorageAdapter("http://mock-s3:9000", "myak", "mysk", secure=False)
    mock_boto3.client.assert_called_once()
    assert adapter.client is not None


def test_s3_adapter_ensure_bucket_head_bucket_error() -> None:
    """测试 ensure_bucket_exists 在 head_bucket 遇到非 404 错误时直接抛出。"""
    mock_client = MagicMock()
    adapter = S3StorageAdapter("http://minio", "ak", "sk", client=mock_client)
    mock_client.head_bucket.side_effect = MockClientError("AccessDenied", 403)
    with pytest.raises(StorageError) as exc_info:
        adapter.ensure_bucket_exists("b")
    assert exc_info.value.error_code == 30001


def test_s3_adapter_lazy_client_property(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试 adapter.client 在 _client 为 None 时触发延迟初始化。"""
    import sys

    mock_boto3 = MagicMock()
    mock_botocore = MagicMock()
    mock_botocore_client = MagicMock()
    monkeypatch.setitem(sys.modules, "boto3", mock_boto3)
    monkeypatch.setitem(sys.modules, "botocore", mock_botocore)
    monkeypatch.setitem(sys.modules, "botocore.client", mock_botocore_client)

    adapter = S3StorageAdapter("http://minio", "ak", "sk", client=MagicMock())
    adapter._client = None
    assert adapter.client is not None
    mock_boto3.client.assert_called()
