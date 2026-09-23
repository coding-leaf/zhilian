# Intent: 对象存储适配器 (MinIO/S3)

- **任务编号**: ZL-114
- **提出人**: Dev
- **创建时间**: 2026-09-23 23:43
- **初始 Change Tier**: Tier 2
- **当前状态**: Accepted

---

## 1. 问题与现状背景 (Problem)
智练自主学习平台在资料导入（FR-01, FR-11）场景中，需要存储用户上传的 PDF、DOCX、Markdown 文件原件、页面切图及解析中间产物：
- 根据系统设计，数据库（PostgreSQL）仅保存文件元数据、存储键（Object Key）与 SHA-256 摘要，二进制文件一律托管于对象存储；
- 小程序端直传文件或获取切图时，需要生成有严格时效限制的预签名上传/下载凭证（Presigned URL，默认 15 分钟失效）；
- 核心分层与网络隔离红线：
  - `app/integrations` 必须通过标准 `Protocol` 抽象与外部具体供应商解耦（NFR-26 供应商可配置）；
  - 单元测试运行在网络绝对阻断环境下，严禁在单测中真实连接外部 MinIO，必须提供高性能、具备完整语义的内存虚拟存储实现（`MemoryStorageAdapter` / Fake）；
  - 真实 S3/MinIO 客户端适配器必须支持桶初始化、文件上传、流式下载、预签名 URL 生成、对象删除及状态检查。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **外部能力适配层规范**：在 `backend/app/integrations/storage/` 建立存储适配模块；
2. **抽象协议契约 (StorageProtocol)**：
   - 定义统一的 `StorageProtocol` 异步/同步方法：
     - `put_object(bucket: str, key: str, data: bytes | BinaryIO, content_type: str) -> str`
     - `get_object(bucket: str, key: str) -> bytes`
     - `get_object_stream(bucket: str, key: str) -> Iterator[bytes]`
     - `generate_presigned_upload_url(bucket: str, key: str, expires_in: int = 900) -> str`
     - `generate_presigned_download_url(bucket: str, key: str, expires_in: int = 900) -> str`
     - `delete_object(bucket: str, key: str) -> bool`
     - `object_exists(bucket: str, key: str) -> bool`
     - `ensure_bucket_exists(bucket: str) -> None`
3. **内存虚拟存储适配器 (MemoryStorageAdapter / Fake)**：
   - 支持并发安全（线程安全锁）的纯内存字节存储；
   - 具备完整预签名 URL 生成与校验模拟（生成带签名参数的合法 URL 字符串）；
   - 支持延迟注入与模拟故障开关（用于上层服务超时与重试测试）；
   - 单测 100% 依赖此类，零真实外部连接。
4. **MinIO / S3 兼容适配器 (MinioStorageAdapter / S3StorageAdapter)**：
   - 基于原生可拔插设计（支持 boto3 / minio-py 客户端或原生 HTTP REST 签名封装，不破坏分层规范）；
   - 包含连接异常映射为项目统一业务异常基类 `AppError`（错误码 30001~30010）；
   - 预签名凭证严格遵守 15 分钟（900 秒）默认过期时间约束。
5. **分层架构与质量门禁**：
   - `tooling/check_layers.py` 严格校验 `app/integrations` 严禁导入 `app/services`；
   - 单测全绿，代码覆盖率 $\ge 90\%$，`bandit` 0 高危 0 中危。

## 4. 波及工程分面 (Affected Architectural Layers)
- [ ] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [ ] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [x] 外部能力适配与集成层 (External Integrations & Adapters)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 位于 `backend/app/integrations/storage/`，严禁导入 `app/services`，严禁逆向依赖上层；
  - 单元测试运行时间必须在毫秒级，禁止发生网络连接；
  - 命名全英文，仅使用 8 个缩写白名单（`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`）；
  - 绝密脱敏红线：日志中严禁打印 MinIO SecretKey、原始文件完整二进制内容或明文认证头。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含用户上传权限校验（由 `MaterialService` 负责）；
  - 不包含数据库中的文件元数据与版本记录落库（属于 `ZL-119`）；
  - 不包含文件切片分块与 OCR 识别业务逻辑。
* **完成判定条件 (Definition of Done)**:
  - `StorageProtocol` 接口定义完备；
  - `MemoryStorageAdapter` 实现完整且通过单测；
  - `MinioStorageAdapter` / `S3StorageAdapter` 实现参数校验、异常转化与预签名签名逻辑；
  - 单测覆盖上传、下载、流式、预签名、删除、异常映射、延迟/故障注入；
  - 静态检查 `ruff`, `mypy`, `bandit`, `check_layers` 全部 0 报错通过。

## 6. 未决疑问与待探讨点 (Open Questions)
- 默认对象存储适配器在测试环境中默认初始化为 `MemoryStorageAdapter`，保证开箱即用零配置。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: Dev / 2026-09-23 23:44
