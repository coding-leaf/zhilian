# Spec: 对象存储适配器 (MinIO/S3) - 技术契约

- **关联 Intent**: ZL-114
- **主导设计人**: Dev
- **当前状态**: In-Review
- **任务评级**: Tier 2 (Single-Module Feature)

---

## 1. 架构流向与设计方案

### 1.1 模块定位与分层边界
智练自主学习平台在资料导入（FR-01, FR-11）场景中，需要将用户上传的原始教材课件（PDF/DOCX/Markdown）、OCR 页面切图及临时排版中间产物托管于兼容 S3 的对象存储（MinIO / AWS S3）。
本模块位于系统五层单向架构矩阵的**外部能力适配层**（`app/integrations`）：
- **物理路径**: `backend/app/integrations/storage/`
- **分层依赖铁律**:
  - 依赖单向向下：由上层业务服务层 `app/services`（如 `MaterialService`）持有并调用，**外部适配层严禁导入 `app.services`**；
  - 纯函数计算核严禁导入外部适配器与网络驱动；
  - 仓储层 `app/repositories` 严禁导入 `app/integrations`；
  - 必须通过 `python3 tooling/check_layers.py --root backend/app` 静态依赖门禁校验（0 违规）。
- **绝密脱敏与凭据隔离红线**:
  - 遵循 `AGENTS.md` 绝密脱敏红线：**严禁在日志中记录 MinIO SecretKey、访问凭证（Token/Signatures）或文件原始二进制内容**；
  - 适配器对象的 `__repr__` / `__str__` 方法中必须严格对 `secret_key` 进行掩码脱敏（如 `secret_key="******"`）；
  - 日志排查仅允许输出桶名（`bucket`）、对象键名（`key`）、数据字节长度（`data_length`）与 MIME 类型（`content_type`）。

### 1.2 架构流向与交互拓扑

```mermaid
flowchart TD
    subgraph BusinessLayer [业务服务层: app/services]
        MaterialService[资料服务: MaterialService]
    end

    subgraph IntegrationLayer [外部适配层: app/integrations/storage]
        StorageProtocol["StorageProtocol (typing.Protocol 契约)"]
        Factory["工厂函数: create_storage_adapter()"]
        
        MemoryAdapter["MemoryStorageAdapter (内存 Fake / 单测隔离)"]
        S3Adapter["S3StorageAdapter / MinioStorageAdapter (S3客户端封装)"]
    end

    subgraph ExternalServices [外部存储服务 / 单测环境]
        MemoryMap[并发安全内存字典: Lock + dict]
        RemoteMinIO[MinIO / AWS S3 集群]
    end

    MaterialService -->|依赖注入 / 统一调用| StorageProtocol
    Factory -->|根据配置创建| MemoryAdapter
    Factory -->|根据配置创建| S3Adapter

    StorageProtocol <|.. MemoryAdapter
    StorageProtocol <|.. S3Adapter

    MemoryAdapter -->|单测与离线环境零网络| MemoryMap
    S3Adapter -->|Boto3 / REST 签名| RemoteMinIO
```

### 1.3 核心处理流水线与时效控制
1. **统一契约保障**：采用 `typing.Protocol` 结构化子类型机制定义存储行为，上层业务层只面向 `StorageProtocol` 编程；
2. **预签名 URL 时效严格约束**：
   - 默认有效期为 900 秒（15 分钟），契合前端直传与即时切图加载需求；
   - 设定防御性校验范围：`1 <= expires_in <= 604800`（1 秒至 7 天）；小于等于 0 或超过上限时抛出 `StorageError`，杜绝长期暴露凭证风险；
3. **流式分块读取**：
   - `get_object_stream(bucket, key, chunk_size=65536)` 默认采用 64KB 分块，避免上百兆大型教材文件一次性载入内存引发 OOM；
4. **单测网络阻断策略**：
   - 开发与单测环境默认注入 `MemoryStorageAdapter`，支持线程锁安全、预签名格式模拟、故障注入（`inject_failure`）与延迟模拟（`inject_latency`），确保单元测试单用例毫秒级通过且零外部套接字连接。

---

## 2. API 与数据契约设计

### 2.1 存储抽象协议契约 (`StorageProtocol`)

位于 `backend/app/integrations/storage/protocol.py`：

```python
from collections.abc import Iterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageProtocol(Protocol):
    """对象存储适配器抽象协议契约。

    定义与具体底层实现无关的标准对象存储交互方法。
    支持上下文安全调用与运行时类型断言。
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
            content_type: 对象的 MIME 类型。

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
            StorageNotFoundError: 对象或桶不存在。
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
            chunk_size: 单次分块字节数，默认 64KB。

        Yields:
            Iterator[bytes]: 二进制分块生成器。

        Raises:
            StorageNotFoundError: 对象或桶不存在。
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
            StorageError: 网络或鉴权异常。
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
```

### 2.2 统一异常体系与 5 位错误码矩阵

位于 `backend/app/core/errors.py`（在外部能力 30xxx 网段严格登记并导出）：

| 异常类名 | 父类 | 错误码 (`error_code`) | HTTP 状态码 | 默认文案 (`message`) | 触发场景 |
| :--- | :--- | :---: | :---: | :--- | :--- |
| `StorageError` | `AppError` | `30001` | `500` | 对象存储服务处理异常 | 通用存储写入/读取失败、预签名参数非法、配置缺失 |
| `StorageNotFoundError` | `StorageError` | `30002` | `404` | 请求的存储对象不存在 | 指定桶或键名未找到 (NoSuchKey / NoSuchBucket) |
| `StorageConnectionError` | `StorageError` | `30003` | `502` | 对象存储服务连接失败或凭据不可用 | 网络超时、Endpoint 无法解析、Boto3 依赖缺失、鉴权拒绝 |

```python
class StorageError(AppError):
    """对象存储基础业务异常 (错误码 30001, HTTP 500)。"""

    def __init__(
        self,
        message: str = "对象存储服务处理异常",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 30001,
        status_code: int = 500,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            error_code=error_code,
            message=message,
            status_code=status_code,
            details=details,
            detail=detail,
        )


class StorageNotFoundError(StorageError):
    """存储对象不存在异常 (错误码 30002, HTTP 404)。"""

    def __init__(
        self,
        message: str = "请求的存储对象不存在",
        details: dict[str, Any] | None = None,
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            detail=detail,
            error_code=30002,
            status_code=404,
        )


class StorageConnectionError(StorageError):
    """对象存储连接失败或驱动不可用异常 (错误码 30003, HTTP 502)。"""

    def __init__(
        self,
        message: str = "对象存储服务连接失败或凭证不可用",
        details: dict[str, Any] | None = None,
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            detail=detail,
            error_code=30003,
            status_code=502,
        )
```

### 2.3 适配器实现契约

#### 2.3.1 `MemoryStorageAdapter` (单测与本地开发)
- **文件路径**: `backend/app/integrations/storage/memory.py`
- **内部核心状态**:
  - `_lock: threading.Lock`
  - `_buckets: set[str]`
  - `_objects: dict[str, dict[str, tuple[bytes, str]]]`（结构: `bucket -> {key: (data_bytes, content_type)}`）
  - `_fault_injections: dict[str, Exception]`（方法名 -> 预置异常，触发后自动抛出）
  - `_latency_seconds: float`（注入的模拟调用耗时，默认 0.0）
- **预签名格式标准**:
  - `https://mock-storage.local/{bucket}/{key}?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires={expires_in}&X-Amz-Signature=mock-{hash}`
- **扩展测试支持方法**:
  - `inject_failure(method_name: str, exception: Exception) -> None`
  - `inject_latency(seconds: float) -> None`
  - `clear() -> None`

#### 2.3.2 `S3StorageAdapter` / `MinioStorageAdapter` (生产 MinIO / AWS S3)
- **文件路径**: `backend/app/integrations/storage/s3.py`
- **初始化签名与参数**:
  ```python
  def __init__(
      self,
      endpoint_url: str,
      access_key: str,
      secret_key: str,
      region_name: str = "us-east-1",
      secure: bool = True,
  ) -> None: ...
  ```
- **客户端隔离与依赖捕获**:
  - 动态按需导入 `boto3` 与 `botocore.exceptions`；
  - 若环境中未安装 `boto3`，实例化或初始化客户端时抛出 `StorageConnectionError("boto3 库未安装，无法初始化 S3StorageAdapter")`，确保在无 boto3 环境下依然可安全加载代码模块并清晰报错；
  - 捕获 `botocore.exceptions.ClientError`：
    - HTTP 404 / `NoSuchKey` / `NoSuchBucket` 统一映射为 `StorageNotFoundError`；
    - Endpoint 解析失败 / 连接拒绝映射为 `StorageConnectionError`；
    - 其他未归类错误映射为通用 `StorageError`；
- **绝密脱敏保护**:
  - `__repr__` 实现：返回 `f"S3StorageAdapter(endpoint_url='{self.endpoint_url}', access_key='{self.access_key}', secret_key='******')"`，阻断在调试输出、栈追踪或日志中泄露 SecretKey。

### 2.4 工厂函数契约 (`create_storage_adapter`)

位于 `backend/app/integrations/storage/factory.py`：

```python
def create_storage_adapter(
    storage_type: str = "memory",
    *,
    endpoint_url: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    region_name: str = "us-east-1",
    secure: bool = True,
) -> StorageProtocol:
    """根据类型与配置创建对象存储适配器实例。

    Args:
        storage_type: 存储类型 ("memory" 或 "s3" / "minio")。
        endpoint_url: S3/MinIO 端点地址。
        access_key: 访问密钥 ID。
        secret_key: 访问秘密密钥。
        region_name: 地域标识，默认 "us-east-1"。
        secure: 是否使用 HTTPS，默认 True。

    Returns:
        StorageProtocol: 具备标准协议能力的存储适配器实例。

    Raises:
        StorageError: storage_type 不支持或配置参数缺失。
    """
```

---

## 3. 可测性设计 (Design for Testability)

### 3.1 零网络隔离红线与 Fake 驱动策略
- **网络阻断铁律**：后端全部单元测试必须在 30 秒内执行完毕，且网络绝对阻断；
- **单测执行矩阵**：
  1. `test_memory_storage.py`：直接测试 `MemoryStorageAdapter` 的并发写入、大文件流式切分、预签名参数解析、异常与延迟注入、幂等删除等完整语义，覆盖率达到 100%；
  2. `test_s3_storage.py`：针对 `S3StorageAdapter` 的入参校验、时效上下限拦截、脱敏 `__repr__` 进行真实执行；对涉及 `boto3` 的底层 Client 交互，通过本地 Mock / Stub 隔离模拟 `botocore.exceptions.ClientError`（404 与网络失败），验证异常转译机制，**严禁发起真实套接字网络连接**；
  3. `test_factory.py`：验证工厂函数根据不同 `storage_type` 正确实例化，以及对非法类型的校验拦截。

### 3.2 决策表与边界值测试用例矩阵 (Coverage $\ge 90\%$)

| 测试用例标识 | 待测模块 | 考查维度 | 核心输入参数与场景 | 预期断言结果 |
| :--- | :--- | :--- | :--- | :--- |
| `test_memory_put_and_get_success` | MemoryAdapter | 正常读写 | 写入 `key="docs/a.pdf"`, 字节数据 | 返回内容与原字节一致，`content_type` 匹配 |
| `test_memory_get_nonexistent_raises_404` | MemoryAdapter | 边界异常 | 获取未写入的 `key="not_exist.bin"` | 抛出 `StorageNotFoundError` (30002, 404) |
| `test_memory_stream_chunking` | MemoryAdapter | 流式切分 | 写入 150KB 数据，以 64KB 读取 | 生成 3 个 chunk（64KB, 64KB, 22KB）且内容完整拼接 |
| `test_memory_presigned_url_format` | MemoryAdapter | 凭证格式 | `expires_in=900` | 包含 `X-Amz-Expires=900` 与 `X-Amz-Signature` |
| `test_presigned_url_expires_out_of_bounds` | Memory / S3 | 时效边界 | `expires_in=0` 或 `expires_in=604801` | 抛出 `StorageError` (时效超出合法区间) |
| `test_memory_delete_idempotent` | MemoryAdapter | 幂等删除 | 删除存在的 key 与删除不存在的 key | 两次均返回 `True`，随后查询 `object_exists` 为 `False` |
| `test_memory_ensure_bucket_exists` | MemoryAdapter | 自动建桶 | 传入新桶名调用 `ensure_bucket_exists` | 桶被创建，随后写入无需报错 |
| `test_memory_inject_failure` | MemoryAdapter | 故障注入 | 注入 `get_object -> StorageError` | 调用 `get_object` 触发预置异常，清除后恢复 |
| `test_memory_inject_latency` | MemoryAdapter | 延迟注入 | 注入延迟 0.05s | 执行时间 $\ge 0.05\text{ s}$ |
| `test_memory_thread_safe_concurrent_write`| MemoryAdapter | 并发安全 | 10 个线程并发写入不同 key | 数据完整无竞态丢失，最终记录数准确 |
| `test_s3_secret_key_masked_in_repr` | S3Adapter | 安全脱敏 | 实例化传入真实明文 secret_key | `repr(adapter)` 不包含明文，显示 `******` |
| `test_s3_missing_boto3_dependency_handling`| S3Adapter | 依赖防御 | 模拟环境中无 boto3 模块 | 实例化抛出清晰 `StorageConnectionError` |
| `test_s3_client_error_mapping_404` | S3Adapter | 异常转译 | Mock client 抛出 `ClientError(404)` | 转译并抛出 `StorageNotFoundError` |
| `test_s3_client_error_mapping_connection` | S3Adapter | 异常转译 | Mock client 抛出 `EndpointConnectionError` | 转译并抛出 `StorageConnectionError` |
| `test_factory_create_memory_adapter` | Factory | 工厂分发 | `create_storage_adapter("memory")` | 返回 `MemoryStorageAdapter` 实例 |
| `test_factory_create_unknown_type_raises` | Factory | 参数校验 | `create_storage_adapter("invalid_type")` | 抛出 `StorageError`，错误提示类型不支持 |

---

## 4. 替代方案与权衡考量 (Alternatives Considered & Trade-offs)

### 4.1 方案 A (采纳方案)：`typing.Protocol` 结构化子类型 + `MemoryStorageAdapter` (Fake) + `S3StorageAdapter`
- **实现机制**:
  - 利用 Python 标准库 `typing.Protocol` 实现隐式类型契约，上层完全解耦具体驱动；
  - 专为测试提供 `MemoryStorageAdapter`，提供 100% 内存语义、并发保护与预置故障模拟；
  - 面向 MinIO 与 S3 提供统一 `S3StorageAdapter`，封装 boto3 客户端并做统一异常转译；
- **优点**:
  - **单测零外部依赖**：单测 100% 运行在本地内存，毫秒级反馈，完全符合无网络红线；
  - **供应商自由切换**：生产环境只需修改配置即可切换为 MinIO、Ceph、AWS S3 或阿里云 OSS（S3 兼容模式）；
  - **严格分层**：适配层与业务服务层彻底解耦，无循环或反向依赖。
- **代价**: 需要自行维护一套完整的 MemoryFake 实现（已充分评估，内存字典与锁维护成本低且收益极高）。

### 4.2 方案 B (否决方案)：强绑定 `minio-py` 官方 SDK
- **原理**: 直接在代码中引入 `minio` Python 库，使用 `Minio(endpoint, ...)`；
- **否决原因**:
  - `minio-py` 与 AWS S3 / 阿里云 OSS API 不完全对齐，后续若迁移到公有云对象存储迁移成本高；
  - 在单元测试中极难轻量化 Mock，通常需要启动 Docker 容器或侵入性 Patch，严重拖慢单测运行耗时。

### 4.3 方案 C (否决方案)：在业务服务层直接调用 `boto3` (无 Protocol 抽象)
- **原理**: 在 `MaterialService` 中直接 `import boto3`，调用 `s3_client.put_object(...)`；
- **否决原因**:
  - 严重违背 `AGENTS.md` 分层架构铁律（服务层直接耦合具体外部 SDK）；
  - 无法在单测中实现纯内存零网络隔离；
  - 破坏了 `NFR-26`（组件可配置与可拔插）要求。

---

## 5. 动态风险核验与回滚预案 (Risk & Rollback Verification)

### 5.1 7 大风险维度核验 (7-Dimensional Dynamic Risk Scan)

| 风险维度 | 风险等级 | 核验结论与控制措施 |
| :--- | :---: | :--- |
| **1. Files** | 低 | 物理集中在 `backend/app/integrations/storage/` 目录与 `backend/app/core/errors.py` 扩充；新增对应的单元测试目录 `backend/tests/unit/integrations/storage/`。不修改现有任何既有业务逻辑。 |
| **2. API** | 无 | 本任务属于底层外部能力适配层，不直接变更对外 HTTP RESTful API 路由或出入参契约。 |
| **3. Schema** | 无 | 不涉及 PostgreSQL 数据库 Schema、ORM 模型或 Alembic 迁移脚本。 |
| **4. Auth** | 无 | 本模块仅负责对象存储操作与签名生成，业务鉴权（如用户是否有权上传/下载特定资料）由上层 `MaterialService` 与 `deps/auth.py` 统一拦截控制。 |
| **5. Deps** | 低 | 适配器设计支持动态隔离检测，开发与测试环境开箱即用（依赖纯标准库）。生产环境可选引入 `boto3`。 |
| **6. Migration** | 无 | 无历史数据迁移需求。 |
| **7. Blast Radius** | 低 | 变更完全限制在 `app/integrations/storage/`，对外通过只读依赖暴露，零破坏性连锁反应。 |

### 5.2 标注关键关注点 (Flagged Concerns)
1. **绝密脱敏与凭据泄露防护 (Security Concern)**:
   - *关注点*: S3 的 `secret_key` 和预签名 URL 包含高危敏感信息，若不慎进入日志或异常栈追踪，可能造成存储桶权限被盗用。
   - *对齐裁决*: `S3StorageAdapter` 的 `__repr__` 显式脱敏为 `******`；`generate_presigned_*` 记录日志时仅记录桶名、对象键名与时效数值，严禁输出签名 URL 全文；禁止打印 `data` 二进制字节。
2. **预签名 URL 的过期时间安全性 (Security Concern)**:
   - *关注点*: 若上层调用方传入过大的 `expires_in`（如数月），生成的凭证将长期有效，违背需求中 15 分钟临时凭据的设计原则。
   - *对齐裁决*: 协议实现强制执行时效防御性拦截，默认 900 秒，合法范围限制为 `[1, 604800]`，超出范围立即抛出 `StorageError` 终止生成。
3. **Boto3 依赖缺失与环境平滑降级 (Portability Concern)**:
   - *关注点*: 若开发机或精简 CI 容器未安装 `boto3`，如果直接在模块顶层 `import boto3` 将导致整个应用在启动导入时直接崩溃报错。
   - *对齐裁决*: 采用延迟加载与 `ImportError` 捕获封装，当未安装 `boto3` 时仅在显式实例化 `S3StorageAdapter` 时抛出受控的 `StorageConnectionError`，不影响使用 `MemoryStorageAdapter` 的测试流程。

### 5.3 回滚与故障应急策略
本模块为新增独立模块，具备 100% 独立可拔插性：
1. **物理回滚步骤**:
   ```bash
   git rm -rf backend/app/integrations/storage/ backend/tests/unit/integrations/storage/
   git checkout develop -- backend/app/core/errors.py
   ```
2. **回滚后健康验证**:
   执行 `cd backend && pytest tests` 与 `python3 tooling/check_layers.py --root backend/app`，验证全量单测通过且分层架构零违规。

---

## 6. 阶段准出签批 (Gate 2 Sign-off)

- [x] 架构流向与 API 契约已冻结
- [x] 替代方案已完成推演与权衡
- [x] 7 维风险已核验且具备明确回滚预案
- **审查结论**: Pending
- **签批人 / 日期**: [待人类签批] / 2026-09-23
