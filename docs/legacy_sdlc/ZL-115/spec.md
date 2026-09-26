# Spec: OCR 识别适配器 (Tencent OCR) - 技术契约

- **关联 Intent**: ZL-115
- **主导设计人**: Dev
- **当前状态**: In-Review
- **任务评级**: Tier 2 (Single-Module Feature)

---

## 1. 架构流向与设计方案

### 1.1 模块定位与分层边界
智练自主学习平台在资料导入（FR-06, FR-08, NFR-11, NFR-26）场景中，支持用户上传教材排版切图、试卷及课件等图片，进行光学字符识别（OCR）。
本模块位于系统五层单向架构矩阵的**外部能力适配层**（`app/integrations`）：
- **物理路径**: `backend/app/integrations/ocr/`
- **分层依赖铁律**:
  - 依赖单向向下：由上层业务服务层 `app/services` 或异步任务执行器（如后续 `MaterialService` / `worker-ocr`）持有并调度，**外部适配层严禁反向导入 `app.services`**；
  - 适配层严禁导入数据仓储层 `app.repositories`；
  - 纯函数计算核（如 `backend/app/core/algorithms/ocr_quality.py`）严禁导入外部适配器与网络驱动；
  - 必须通过 `python3 tooling/check_layers.py --root backend/app` 静态依赖门禁校验（0 跨层违规）。
- **绝密脱敏与凭据隔离红线**:
  - 遵循 `AGENTS.md` 绝密脱敏红线：**严禁在日志中输出腾讯云 SecretKey、认证签名头或待识别图片完整 base64/二进制数据**；
  - 适配器对象的 `__repr__` / `__str__` 方法中必须严格对 `secret_key` 进行掩码脱敏（`secret_key="******"`）；
  - 日志排查仅允许输出识别耗时（`duration_ms`）、图片字节大小（`image_bytes_length`）、图片 URL（脱敏签名参数后）、识别文本字符数（`text_length`）与置信度。
- **命名与缩写规范**:
  - 严格遵守 8 个缩写白名单（`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`），严禁使用如 `pts`, `res`, `req`, `tmp`, `cnt` 等自造缩写，变量一律采用如 `points`, `result`, `request`, `temporary`, `count` 等完整英文单词。

### 1.2 架构流向与交互拓扑

```mermaid
flowchart TD
    subgraph BusinessLayer [业务服务层 / 异步任务层]
        MaterialService[资料处理服务: MaterialService / Worker]
    end

    subgraph IntegrationLayer [外部适配层: app/integrations/ocr]
        OCRProtocol["OCRProtocol (typing.Protocol 契约)"]
        Factory["工厂函数: create_ocr_adapter()"]
        
        FakeAdapter["FakeOCRAdapter (内存假实现 / 单测隔离)"]
        TencentAdapter["TencentOCRAdapter (腾讯云 SDK 封装)"]
    end

    subgraph ExternalServices [外部服务 / 单测环境]
        MemoryCanned[确定性预置数据 / 模拟故障 / 延迟注入]
        TencentAPI[腾讯云通用印刷体识别接口 / 云端集群]
    end

    MaterialService -->|依赖注入 / 统一调用| OCRProtocol
    Factory -->|根据配置创建| FakeAdapter
    Factory -->|根据配置创建| TencentAdapter

    OCRProtocol <|.. FakeAdapter
    OCRProtocol <|.. TencentAdapter

    FakeAdapter -->|单测与离线环境零网络| MemoryCanned
    TencentAdapter -->|退避重试 / 异常转译 / 20s 超时| TencentAPI
```

### 1.3 核心处理流水线与容错重试机制
1. **统一契约保障**：采用 `typing.Protocol` 结构化子类型机制定义标准 OCR 行为，屏蔽底层供应商专有 SDK 与参数差异；
2. **多模态输入支持**：契约原生支持二进制图片字节流（`recognize_image`）与公网/预签名图片地址（`recognize_url`）；
3. **生产高可用重试控制**：
   - 生产适配器针对偶发限流（`RequestLimitExceeded`）与网络抖动超时，内置指数退避重试（默认最大重试 3 次，初始等待时间 0.5 秒，按 2.0 指数递增）；
   - 单次 API 调用执行 20 秒超时上限控制（NFR-11），避免网络僵死导致工作流挂起；
4. **单测网络阻断策略**：
   - 开发与单测环境默认分发 `FakeOCRAdapter`，支持线程锁保护、固定确定性解析结果返回、预签名/哈希映射（`set_canned_result`）、故障注入（`inject_failure`）与延迟模拟（`inject_latency`），确保单元测试单用例毫秒级通过且零外部套接字连接。

---

## 2. API 与数据契约设计

### 2.1 协议契约与数据结构 (`backend/app/integrations/ocr/protocol.py`)

```python
"""OCR 适配器抽象协议与数据传输模型定义模块。

严格遵循 AGENTS.md 规范：
- 适配层通过 Protocol 抽象接口与外部供应商解耦；
- 纯协议与原生强类型模型定义，零框架与业务依赖；
- 遵守 8 个缩写白名单 (api, id, url, ocr, llm, db, config, env)。
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class OCRPoint:
    """图像二维平面坐标点。"""

    x: int
    y: int


@dataclass(frozen=True)
class OCRPolygon:
    """文字区块多边形外包围框。"""

    points: tuple[OCRPoint, ...]

    @classmethod
    def from_coordinates(cls, coordinates: Sequence[tuple[int, int]]) -> "OCRPolygon":
        """从元组序列构建多边形对象。"""
        return cls(points=tuple(OCRPoint(x=point[0], y=point[1]) for point in coordinates))


@dataclass(frozen=True)
class OCRTextBlock:
    """OCR 单行/单段文本识别结果块。"""

    text: str
    confidence: float
    polygon: OCRPolygon | None = None
    line_number: int = 0


@dataclass(frozen=True)
class OCRResult:
    """OCR 识别完整结果数据模型。"""

    full_text: str
    blocks: tuple[OCRTextBlock, ...] = field(default_factory=tuple)
    duration_ms: float = 0.0
    image_width: int | None = None
    image_height: int | None = None
    provider: str = "fake"
    raw_payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class OCROptions:
    """OCR 识别控制参数选项。"""

    language_type: str = "zh"
    need_location: bool = True
    timeout: float = 20.0

    def __post_init__(self) -> None:
        """防御性参数合法性校验。"""
        if self.timeout <= 0.0:
            raise ValueError("timeout must be greater than 0")


@runtime_checkable
class OCRProtocol(Protocol):
    """OCR 识别适配器抽象协议契约。

    定义与具体云厂商或底层模型解耦的通用 OCR 文本识别接口。
    """

    def recognize_image(
        self,
        image_bytes: bytes,
        options: OCROptions | None = None,
    ) -> OCRResult:
        """识别上传的本地/内存图片二进制字节数据。

        Args:
            image_bytes: 图片文件完整二进制字节流。
            options: 可选的识别配置选项。

        Returns:
            OCRResult: 结构化解析结果对象。

        Raises:
            OCRError: 识别失败或服务异常。
            OCRTimeoutError: 识别调用响应超时。
            OCRAuthError: 凭证鉴权拒绝或授权失效。
        """
        ...

    def recognize_url(
        self,
        image_url: str,
        options: OCROptions | None = None,
    ) -> OCRResult:
        """通过图片公网或预签名 URL 进行识别。

        Args:
            image_url: 可访问的图片资源网络链接。
            options: 可选的识别配置选项。

        Returns:
            OCRResult: 结构化解析结果对象。

        Raises:
            OCRError: 识别失败或服务异常。
            OCRTimeoutError: 识别调用响应超时。
            OCRAuthError: 凭证鉴权拒绝或授权失效。
        """
        ...


__all__ = [
    "OCROptions",
    "OCRPoint",
    "OCRPolygon",
    "OCRProtocol",
    "OCRResult",
    "OCRTextBlock",
]
```

### 2.2 统一异常体系与 5 位错误码矩阵 (`backend/app/core/errors.py`)

在统一异常基类 `AppError` 的 30xxx 外部能力网段扩充注册并导出：

| 异常类名 | 父类 | 错误码 (`error_code`) | HTTP 状态码 | 默认文案 (`message`) | 触发场景 |
| :--- | :--- | :---: | :---: | :--- | :--- |
| `OCRError` | `AppError` | `30004` | `502` | OCR服务异常 | 腾讯云通用接口失败、图像解码异常、内部系统错误、缺少第三方 SDK 依赖 |
| `OCRTimeoutError` | `OCRError` | `30005` | `504` | OCR服务响应超时 | 超过 20s 超时时间、网络连接超时、底层 Socket 读写超时 |
| `OCRAuthError` | `OCRError` | `30006` | `502` | OCR服务认证或授权失败 | 腾讯云 SecretId/SecretKey 无效、未开通 OCR 接口服务、签名计算失败、欠费停服 |

```python
class OCRError(AppError):
    """OCR 识别服务基础异常 (错误码 30004, HTTP 502)。

    当 OCR 服务发生通用识别失败、图像解码异常或底层第三方 SDK 故障时抛出。
    """

    def __init__(
        self,
        message: str = "OCR服务异常",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 30004,
        status_code: int = 502,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            error_code=error_code,
            message=message,
            status_code=status_code,
            details=details,
            code=code,
            detail=detail,
        )


class OCRTimeoutError(OCRError):
    """OCR 识别服务调用超时异常 (错误码 30005, HTTP 504)。

    当 OCR 服务网络连接超时、等待响应超时（超过预设 timeout 阈值）时抛出。
    """

    def __init__(
        self,
        message: str = "OCR服务响应超时",
        details: dict[str, Any] | None = None,
        *,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code=30005,
            status_code=504,
            code=code,
            detail=detail,
        )


class OCRAuthError(OCRError):
    """OCR 识别服务鉴权或授权失败异常 (错误码 30006, HTTP 502)。

    当腾讯云或第三方 OCR 凭证密钥失效、权限不足或未开通服务时抛出。
    """

    def __init__(
        self,
        message: str = "OCR服务认证或授权失败",
        details: dict[str, Any] | None = None,
        *,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code=30006,
            status_code=502,
            code=code,
            detail=detail,
        )
```

### 2.3 适配器实现契约

#### 2.3.1 `FakeOCRAdapter` (`backend/app/integrations/ocr/fake.py`)
- **功能定位**: 专用于本地开发调试与单元测试，完全基于内存，绝对阻断外部网络套接字连接；
- **核心状态**:
  - `_lock: threading.Lock`：并发安全性保护；
  - `_canned_results: dict[str, OCRResult]`：支持针对特定图片 SHA-256 哈希或 URL 预置结果；
  - `_default_result: OCRResult | None`：未命中预置时的通用保底返回；
  - `_fault_injections: dict[str, Exception]`：方法级别故障模拟注入；
  - `_latency_seconds: float`：调用耗时模拟注入；
- **扩展管理接口**:
  - `set_canned_result(key: str | bytes, result: OCRResult) -> None`
  - `inject_failure(method_name: str, exception: Exception) -> None`
  - `inject_latency(seconds: float) -> None`
  - `clear() -> None`

#### 2.3.2 `TencentOCRAdapter` (`backend/app/integrations/ocr/tencent.py`)
- **功能定位**: 面向腾讯云 OCR API（如通用印刷体识别 `GeneralBasicOCR` 或 `GeneralAccurateOCR`）的生产适配器；
- **初始化签名与参数**:
  ```python
  def __init__(
      self,
      secret_id: str,
      secret_key: str,
      region: str = "ap-guangzhou",
      endpoint: str = "ocr.tencentcloudapi.com",
      timeout: float = 20.0,
      max_retries: int = 3,
      client: Any | None = None,
  ) -> None: ...
  ```
- **脱敏安全防护**:
  - 显式覆写 `__repr__` 与 `__str__`：
    ```python
    def __repr__(self) -> str:
        return (
            f"TencentOCRAdapter(secret_id='{self.secret_id}', "
            f"secret_key='******', region='{self.region}', "
            f"endpoint='{self.endpoint}', timeout={self.timeout})"
        )
    ```
- **依赖按需加载机制**:
  - 动态导入 `tencentcloud-sdk-python` 相关模块；若宿主环境未安装，在客户端初始化时抛出 `OCRError("tencentcloud-sdk-python 库未安装，无法初始化 TencentOCRAdapter")`，确保在无 SDK 环境下仍可安全导入本模块；
- **指数退避重试与异常转译体系**:
  - 当底层调用抛出异常时，根据错误分类决策是否重试与最终转译：
    1. **可重试错误**（偶发网络断连、SDK 超时、`RequestLimitExceeded` 限流）：采用公式 $T_{wait} = 0.5 \times 2^{\text{attempt}}$ 进行休眠后重试，最多重试 `max_retries` 次；
    2. **认证异常**（`AuthFailure.*`，如签名过期、SecretId/SecretKey 错误）：不重试，立即转译抛出 `OCRAuthError`；
    3. **超时异常**（HTTP 504、网络 read/connect timeout 或重试耗尽的超时）：转译抛出 `OCRTimeoutError`；
    4. **其他业务错误**（`FailedOperation.ImageDecodeFailed`、无效参数等）：转译抛出 `OCRError`。

### 2.4 工厂函数契约 (`backend/app/integrations/ocr/factory.py`)

```python
def create_ocr_adapter(
    adapter_type: str = "fake",
    *,
    secret_id: str | None = None,
    secret_key: str | None = None,
    region: str = "ap-guangzhou",
    endpoint: str = "ocr.tencentcloudapi.com",
    timeout: float = 20.0,
    max_retries: int = 3,
    client: Any | None = None,
) -> OCRProtocol:
    """根据类型与配置创建 OCR 适配器实例。

    Args:
        adapter_type: 适配器类型 ("fake" 或 "tencent")，默认 "fake"。
        secret_id: 腾讯云 SecretId。
        secret_key: 腾讯云 SecretKey。
        region: 腾讯云地域标识，默认 "ap-guangzhou"。
        endpoint: API 接入点地址，默认 "ocr.tencentcloudapi.com"。
        timeout: 超时时间（秒），默认 20.0。
        max_retries: 最大重试次数，默认 3。
        client: 可选外部注入的底层 SDK 客户端实例（供测试打桩）。

    Returns:
        OCRProtocol: 符合抽象协议的 OCR 适配器实例。

    Raises:
        OCRError: adapter_type 不支持或必要凭据缺失。
    """
```

### 2.5 模块统一导出契约 (`backend/app/integrations/ocr/__init__.py`)

统一维护 `__all__` 并按严格字典序排列：
```python
__all__ = [
    "FakeOCRAdapter",
    "OCROptions",
    "OCRPoint",
    "OCRPolygon",
    "OCRProtocol",
    "OCRResult",
    "OCRTextBlock",
    "TencentOCRAdapter",
    "create_ocr_adapter",
]
```

---

## 3. 可测性设计 (Design for Testability)

### 3.1 零网络隔离红线与测试策略
- **单元测试网络物理阻断**：单测严禁发起任何外部网络连接。
- **单测执行分工矩阵**：
  1. `test_fake_ocr.py`：测试 `FakeOCRAdapter` 的确定性解析、预置文本匹配、多边形外包围框坐标构造、故障与延迟注入、线程安全等能力，行/分支覆盖率达到 100%；
  2. `test_tencent_ocr.py`：针对 `TencentOCRAdapter` 的凭证脱敏 `__repr__`、入参边界、SDK 依赖缺失捕获执行白盒测试；利用本地注入的 Mock Client 模拟腾讯云 SDK 的各种返回值及异常（`TencentCloudSDKException`），验证指数退避重试次数与异常转译映射；
  3. `test_ocr_factory.py`：验证 `create_ocr_adapter` 在不同入参下的分发正确性及缺少凭据时的防御报错；
  4. `test_ocr_errors.py`：验证 `OCRError`、`OCRTimeoutError`、`OCRAuthError` 的继承关系、错误码与 HTTP 状态码映射。

### 3.2 决策表与边界值测试用例矩阵 (覆盖率要求: 行 $\ge 95\%$, 分支 $\ge 90\%$)

| 测试用例标识 | 待测模块 | 考查维度 | 核心输入参数与场景 | 预期断言结果 |
| :--- | :--- | :--- | :--- | :--- |
| `test_fake_ocr_default_recognition` | FakeOCRAdapter | 默认解析 | 传入标准二进制字节流与默认选项 | 返回包含完整文本与非空分块列表的 `OCRResult` |
| `test_fake_ocr_canned_result_match` | FakeOCRAdapter | 预置结果 | 预置 key 与专属 `OCRResult` 后调用 | 精准返回预置对象，未匹配 key 返回默认结果 |
| `test_fake_ocr_inject_failure` | FakeOCRAdapter | 故障注入 | 注入 `recognize_image -> OCRTimeoutError` | 调用时抛出预置异常，`clear()` 后恢复正常 |
| `test_fake_ocr_inject_latency` | FakeOCRAdapter | 延迟注入 | 注入延迟 0.05 秒 | 调用耗时 $\ge 0.05\text{ s}$ 且数据完整返回 |
| `test_fake_ocr_thread_safety` | FakeOCRAdapter | 并发安全 | 10 个线程并发执行识别与更新 | 无竞态报错，调用次数统计与返回一致 |
| `test_options_validation_negative_timeout` | OCROptions | 边界值防御 | `timeout = -1.0` 或 `0.0` | 实例化抛出 `ValueError` |
| `test_polygon_from_coordinates_helper` | OCRPolygon | 数据转换 | 传入四边形坐标列表 `[(0,0), (10,0), ...]` | 正确生成具有对应 `OCRPoint` 的多边形 |
| `test_tencent_repr_masks_secret_key` | TencentOCRAdapter | 绝密脱敏 | 传入明文 `secret_key="my_secret_key_123"` | `repr(adapter)` 输出包含 `******`，无明文 |
| `test_tencent_missing_sdk_raises_error` | TencentOCRAdapter | 依赖捕获 | 模拟环境中缺失 `tencentcloud` 库 | 初始化时捕获并抛出清晰 `OCRError` |
| `test_tencent_auth_failure_mapping` | TencentOCRAdapter | 异常转译 | Mock client 抛出 `AuthFailure.SecretIdNotFound` | 立即转译为 `OCRAuthError` (30006, 502) 不重试 |
| `test_tencent_timeout_retry_and_mapping`| TencentOCRAdapter | 退避重试 | Mock client 抛出超时异常 3 次 | 触发 3 次指数重试，最终转译为 `OCRTimeoutError` |
| `test_tencent_rate_limit_retry_success` | TencentOCRAdapter | 重试恢复 | Mock 第 1 次报限流，第 2 次成功返回 | 退避重试后成功返回结果，无未处理异常抛出 |
| `test_tencent_generic_error_mapping` | TencentOCRAdapter | 异常转译 | Mock client 抛出 `FailedOperation` | 转译为通用 `OCRError` (30004, 502) |
| `test_factory_create_fake_adapter` | OCRFactory | 工厂分发 | `create_ocr_adapter("fake")` | 返回 `FakeOCRAdapter` 实例 |
| `test_factory_create_tencent_missing_keys`| OCRFactory | 参数校验 | `create_ocr_adapter("tencent")` 无 key | 抛出 `OCRError` 提示必填凭据缺失 |
| `test_factory_create_unknown_type` | OCRFactory | 参数校验 | `create_ocr_adapter("invalid")` | 抛出 `OCRError` 提示不支持类型 |

---

## 4. 替代方案与权衡考量 (Alternatives Considered & Trade-offs)

### 4.1 方案 A (采纳方案)：`typing.Protocol` 抽象契约 + 纯内存 `FakeOCRAdapter` + 生产 `TencentOCRAdapter`
- **核心考量**:
  - 利用 Python `typing.Protocol` 实现结构化子类型解耦，业务层与适配层彻底分离；
  - 离线 Fake 适配器满足《AGENTS.md》规定的零网络隔离红线，单测执行耗时在毫秒级；
  - 生产适配器内聚凭证脱敏、依赖延迟加载、指数退避重试与五位业务错误码映射。
- **代价与权衡**: 需要维护纯内存 Fake 模拟逻辑，但极大降低了系统集成测试对外部云配额的依赖。

### 4.2 方案 B (否决方案)：在业务服务层直接导入并调用腾讯云官方 SDK
- **否决原因**:
  - 严重违背五层单向依赖架构规范（服务层耦合具体第三方供应商 SDK）；
  - 无法满足单元测试中 100% 零套接字连接与秒级运行门禁；
  - 供应商被死锁，后续接入阿里云 OCR 或本地大模型 OCR 时需重构业务调用逻辑。

### 4.3 方案 C (否决方案)：采用本地开源 OCR（如 PaddleOCR / Tesseract）作为默认生产实现
- **否决原因**:
  - 本地深度学习 OCR 模型需要数 GB 权重镜像与重型 C++ 编译依赖，导致后端 Docker 镜像过大；
  - 部署环境对 GPU/CPU 计算资源占用高，不适合学生端教材高并发排版识别要求；
  - 腾讯云 OCR 等公有云服务在复杂印刷体、公式排版及倾斜矫正上具备更高的开箱即用准确度。

---

## 5. 动态风险核验与回滚预案 (Risk & Rollback Verification)

### 5.1 7 大风险维度核验 (7-Dimensional Dynamic Risk Scan)

| 风险维度 | 风险等级 | 核验结论与控制措施 |
| :--- | :---: | :--- |
| **1. Files** | 低 | 新增物理隔离目录 `backend/app/integrations/ocr/` 与对应单元测试目录 `backend/tests/unit/integrations/ocr/`；在 `backend/app/core/errors.py` 扩充 3 个 30xxx 异常类。不破坏现有代码。 |
| **2. API** | 无 | 本模块属于基础设施适配层，不直接暴露或变更对外 HTTP RESTful API 路由契约。 |
| **3. Schema** | 无 | 不涉及数据库表变更、模型修改或 Alembic 迁移脚本。 |
| **4. Auth** | 无 | 不涉及业务租户鉴权逻辑（由上层业务与鉴权依赖链控制）。模块仅管理云服务 SecretKey 凭据。 |
| **5. Deps** | 低 | 腾讯云 SDK 采用延迟加载与异常防御捕获，宿主环境未安装时仍可安全加载与运行 Fake 测试套件。 |
| **6. Migration** | 无 | 无数据持久化状态变更，零历史数据迁移风险。 |
| **7. Blast Radius** | 低 | 变更完全限制在 `app/integrations/ocr/` 及其对应单元测试，对外通过只读依赖暴露，零连锁破坏。 |

### 5.2 标注关键关注点 (Flagged Concerns)
1. **绝密脱敏与凭据泄露风险 (Security Concern)**:
   - *关注点*: 腾讯云 `SecretKey` 与待识别图片的 Base64/二进制数据若进入日志或异常栈追踪，将造成严重安全违规。
   - *对齐裁决*: `TencentOCRAdapter` 的 `__repr__` 强制执行 `secret_key="******"` 掩码脱敏；日志中严禁输出图片原始二进制内容或 Base64 编码，仅允许记录字节长度、字符数与识别耗时。
2. **偶发网络抖动与限流雪崩 (Reliability Concern)**:
   - *关注点*: 公有云 OCR 存在 QPS 限流与网络偶发超时，若直接失败将导致用户切图标注流程频繁中断。
   - *对齐裁决*: 生产适配器内建最多 3 次指数退避重试（初始 0.5s，指数 2.0），并设定 20.0s 总超时门槛，平衡调用弹性与资源占用。
3. **零网络单测与 SDK 依赖解耦 (Portability Concern)**:
   - *关注点*: CI 环境与开发机可能缺少腾讯云 SDK 或无法访问外网，若硬编码导入会导致全量单测挂掉。
   - *对齐裁决*: 适配器按需加载 SDK 并对缺失异常做防御性包装；工厂与单测统一默认分发 `FakeOCRAdapter`，确保在无网环境下通过全量门禁。

### 5.3 回滚与故障应急策略
本模块具备 100% 独立可拔插性，若出现任何异常可执行极简回滚：
1. **物理回滚命令**:
   ```bash
   git rm -rf backend/app/integrations/ocr/ backend/tests/unit/integrations/ocr/
   git checkout develop -- backend/app/core/errors.py
   ```
2. **回滚后健康验证**:
   执行 `cd backend && pytest tests` 与 `python3 tooling/check_layers.py --root backend/app`，验证全量测试绿灯且分层检查 0 违规。

---

## 6. 阶段准出签批 (Gate 2 Sign-off)

- [x] 架构流向与 API 契约已冻结
- [x] 替代方案已完成推演与权衡
- [x] 7 维风险已核验且具备明确回滚预案
- **审查结论**: Pending
- **签批人 / 日期**: [待人类签批] / 2026-09-24 00:15
