# Intent: OCR 识别适配器 (Tencent OCR)

- **任务编号**: ZL-115
- **提出人**: Dev
- **创建时间**: 2026-09-24 00:07
- **初始 Change Tier**: Tier 2
- **当前状态**: Accepted

---

## 1. 问题与现状背景 (Problem)
智练自主学习平台在资料导入（FR-06, FR-08, NFR-11, NFR-26）场景中，支持用户上传教材、教辅试卷等图片进行光学字符识别（OCR）：
- **外部能力解耦红线**：业务服务与工作流（`worker-ocr` / `MaterialService`）严禁与特定公有云 OCR SDK 深度绑定，必须通过通用 `Protocol` 契约抽象隔离，满足供应商可配置切换（NFR-26）；
- **测试网络隔离红线**：根据《AGENTS.md》与代码管理规范，单元测试中严禁真实联网或消耗公网配额，大模型与 OCR 必须提供固定确定性返回的假实现（`FakeOCRAdapter`），且需支持延迟注入与故障模拟（用于验证后续流水线超时重试与降级）；
- **生产稳定性与退避重试**：公网 API 偶发抖动或限流，客户端需具备最大 20s 超时时间（NFR-11）、指数退避重试（重试 3 次）、结构化坐标/置信度解析、以及将底层 SDK/HTTP 异常规范转译为系统统一业务异常（30004~30006）；
- **绝密脱敏红线**：严禁在日志中输出腾讯云 `SecretKey`、认证签名头或待识别图片完整 base64/二进制数据。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **外部能力适配层规范**：在 `backend/app/integrations/ocr/` 建立标准 OCR 适配模块；
2. **抽象协议契约 (OCRProtocol)**：
   - 定义统一的 `OCRProtocol(typing.Protocol)` 接口：
     - `recognize_image(image_bytes: bytes, options: OCROptions | None = None) -> OCRResult`
     - `recognize_url(image_url: str, options: OCROptions | None = None) -> OCRResult`
   - 强类型数据模型：`OCRTextBlock`（文本、置信度、四边形坐标/边界框、行号）、`OCRResult`（完整拼接文本、分块列表、图片宽高、耗时、语言与扩展信息）；
3. **离线假实现适配器 (FakeOCRAdapter / Mock)**：
   - 支持开箱即用、确定性解析返回；
   - 支持按图片摘要或模式配置固定返回值（`set_canned_result`）；
   - 支持延迟注入（`inject_latency`）与故障异常注入（`inject_failure`）；
   - 单测 100% 依赖此类，毫秒级执行，零网络外联；
4. **腾讯云 OCR 生产适配器 (TencentOCRAdapter)**：
   - 支持配置：`secret_id`, `secret_key`, `region="ap-guangzhou"`, `endpoint="ocr.tencentcloudapi.com"`, `timeout=20.0`, `max_retries=3`；
   - `__repr__` 强制脱敏 `secret_key`（掩码为 `******`）；
   - 依赖隔离：按需加载 `tencentcloud-sdk-python`，若未安装或离线，捕获异常并抛出清晰的 `OCRError`；
   - 异常转译：将限流、认证失败、网络超时映射为统一业务异常 `OCRError`、`OCRTimeoutError`、`OCRAuthError`（错误码 30004~30006）；
5. **工厂与分层质量门禁**：
   - 提供 `create_ocr_adapter(adapter_type: str = "fake", ...)` 工厂；
   - `tooling/check_layers.py` 扫描 0 跨层违规（严禁导入 `app/services`）；
   - 单元测试分支覆盖率 $\ge 90\%$，`bandit` 0 高危 0 中危。

## 4. 波及工程分面 (Affected Architectural Layers)
- [ ] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [ ] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [x] 外部能力适配与集成层 (External Integrations & Adapters)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 位于 `backend/app/integrations/ocr/`，严禁导入 `app/services` 与 `app/repositories`；
  - 缩写白名单仅限 8 个（`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`）；
  - 单测运行在网络绝对阻断环境下，0 真实 Socket 连接；
  - 严禁打印敏感凭据和图片 Base64 全文。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含 OCR 识别文本的质量门禁计算（乱码率、有效字符等由纯函数核 `verify_ocr_quality` / `ZL-108` 负责）；
  - 不包含图片在 MinIO 中的上传存储与预签名分发（由 `ZL-114` 负责）；
  - 不包含异步任务队列消费者逻辑（由 `worker-ocr` / `ZL-119` 负责）。
* **完成判定条件 (Definition of Done)**:
  - `OCRProtocol` 契约与 DTO 完备；
  - `FakeOCRAdapter` 支持确定性返回、延迟与异常注入，通过单测；
  - `TencentOCRAdapter` 实现凭证脱敏、超时与退避重试、异常转译；
  - 单测覆盖率达标，分层检查通过，SDLC 完整归档。

## 6. 未决疑问与待探讨点 (Open Questions)
- 默认初始化环境为 `FakeOCRAdapter`，确保无云端 SecretKey 时本地与 CI 门禁开箱即用。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: Dev / 2026-09-24 00:08
