# Intent: 学习资料、版本与知识片段存储模型 (含 pgvector)

- **任务编号**: ZL-104
- **提出人**: Dev
- **创建时间**: 2026-09-23 19:40
- **初始 Change Tier**: Tier 3
- **当前状态**: Draft / In-Review / Accepted

---

## 1. 问题与现状背景 (Problem)
在智练自主学习平台中，系统以学生自主上传的学习材料（PDF、DOCX、PPTX、Markdown、TXT 及图片扫描件）为唯一事实输入源驱动个性化出题与练习主闭环（需求规格说明书 FR-01~03, FR-11~13, FR-61）。
当前系统已完成工程协议基线（ZL-102）、用户空间模型与安全鉴权底座（ZL-103）以及资料分块纯函数核（ZL-107）。然而，承载学习流水线首要载体的数据持久化底座尚处于空白状态，面临以下关键问题与技术痛点：
1. **缺少学习资料主实体与生命周期状态模型 (`materials`)**：无法持久化记录用户导入资料的元数据（标题、格式、大小、导入来源、当前激活版本引用等）；无法支持《LEADER_ALIGNMENT.md》技术决策 3 所确立的统一连续生命周期状态机（`QUEUED -> PARSING -> OCR_PROCESSING -> EXTRACTING_KNOWLEDGE -> AUDITING_KNOWLEDGE -> READY / FAILED`），缺乏出题前置状态门禁阻断，极易引发出题接口“踩空”竞态（Race Condition）。
2. **缺少多版本演进与隔离存储机制 (`material_versions`)**：需求 FR-12 明确要求“重新导入同名或同内容文件时按新版本处理，不得覆盖既有版本的知识片段与题目，旧版本练习记录仍可访问”。当前缺乏版本表实体，若直接在资料表原地覆盖将破坏历史作答溯源与答卷完整性；同时缺乏文件 SHA-256 内容摘要（用于查重与复用判定）与对象存储脱敏路径（`storage_key`）映射。
3. **缺少向量切片持久化与语义检索底座 (`material_snippets` + pgvector)**：ZL-107 分块算法产出的知识片段（800 字符以内）缺乏持久化模型；后续 ZL-116（混合检索）与 ZL-121（检索增强出题）强依赖 1024 维定长向量存储与高效近邻检索；若缺乏 pgvector 扩展及 HNSW 索引（余弦距离度量），出题检索无法达到 P95 < 200ms 的性能要求。
4. **缺少资料多版本与向量多租户隔离的安全约束**：《LEADER_ALIGNMENT.md》核心矛盾 2 揭示，若切片仅按 `(user_id, material_id)` 检索，多版本共存时旧版本切片会污染新版本出题召回。底层必须建立 `(user_id, material_id, version_id)` 三元组隔离与索引机制。
5. **缺少 OCR 页面级识别质量记录模型 (`material_ocr_pages`)**：需求 FR-08, FR-09 要求逐页校验乱码率（$\le 15\%$）与有效字数（$\ge 40$），并支持前端标黄与就地重拍（最多 3 次）。若无页级质量记录表，无法对不合格页进行持久化跟踪与幂等更新。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [ ] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [x] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **多租户资料与版本持久化模型 (`materials`, `material_versions`)**：
   - 在 `backend/app/models/` 规范定义 `Material` 与 `MaterialVersion` 实体，严格继承 `Base, TimestampMixin, TenantModelMixin`；
   - `materials` 表完整覆盖：UUIDv4 主键、租户标识 `user_id`（外键 `users.id`，CASCADE 级联，带索引）、资料名称 `title`、文件格式 `file_format`、文件大小 `file_size`、导入方式 `source_type`（微信导入/本地导入）、当前激活版本 `current_version_id`、连续生命周期状态 `status`（枚举覆盖 QUEUED 至 READY/FAILED）、软删除标记 `is_deleted`（默认 False）及 UTC 时间戳；
   - `material_versions` 表实现：`version_number`（递增序号）、关联 `material_id`、对象存储路径 `storage_key`、SHA-256 内容摘要 `content_hash`、解析状态 `parse_status`、失败阶段 `failed_stage`、全量纯文本存储键 `raw_text_storage_key`、激活标记 `is_active`；建立 `(material_id, version_number)` 唯一约束。
2. **切片实体与 pgvector 1024 维向量索引体系 (`material_snippets`)**：
   - 定义 `MaterialSnippet` 实体，关联 `material_id` 与 `version_id`，继承 `TenantModelMixin`；
   - 包含切片文本 `content`（800 字符限制）、`char_length`、偏移区间 `start_offset`/`end_offset`、章节标记 `chapter_title`、结构化来源元数据 `source_info`（JSONB 存储页码/幻灯片/段落）；
   - 引入 pgvector 扩展并声明 `Vector(1024)` 定长语义向量列 `embedding`；
   - 在数据库层面构建 HNSW 索引（`vector_cosine_ops`，参数 `m=16, ef_construction=200`）；
   - 建立 `(user_id, material_id, version_id)` 联合索引，确保多租户隔离与三元组检索过滤零污染。
3. **页级 OCR 质量门禁持久化模型 (`material_ocr_pages`)**：
   - 定义 `MaterialOCRPage` 实体，继承 `TenantModelMixin`，关联 `version_id`；
   - 字段包含 `page_number`、页面图片键 `image_storage_key`、乱码率 `gibberish_ratio`、有效字数 `valid_char_count`、合格标记 `is_qualified`、不合格原因 `unqualified_reason`、重拍计数 `reshoot_count`（默认 0，上限 3）；建立 `(version_id, page_number)` 唯一索引，支持重拍就地更新。
4. **数据库迁移与双向回滚物理验证**：
   - 编写 Alembic 迁移脚本，在 `upgrade()` 中幂等激活 `vector` 扩展并创建全部 4 张实体表及复合/HNSW 索引；
   - 在 `downgrade()` 中提供完全对称的反向清理逻辑；
   - 编写自动化升降级测试，物理验证双向迁移 100% 成功。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [x] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - **声明式多租户隔离铁律**：所有业务表必须严格继承 `TenantModelMixin`，`user_id` 必须作为外键（`ForeignKey("users.id", ondelete="CASCADE")`）与非空索引列；所有涉及查询强制携带 `user_id`（阻断水平越权）；
  - **三元组检索约束**：切片表检索与外键关联必须支持 `(user_id, material_id, version_id)` 三元组过滤，从底层彻底阻断跨版本过期切片召回交叉污染；
  - **pgvector 维度与索引配置**：语义向量固定为定长 1024 维；知识片段 HNSW 索引参数严格固定为余弦距离 `vector_cosine_ops`、`m=16, ef_construction=200`；
  - **分级软删除与防外键崩溃**：落实《LEADER_ALIGNMENT.md》技术决策 2，资料删除操作采用软删除机制（`is_deleted=True`），避免因物理 CASCADE 破坏未来作答快照与练习外键关联；账号注销时方在后台 7 天定时任务中执行不可逆物理级联清理；
  - **架构分层依赖铁律**：数据模型位于 `backend/app/models/`，绝对禁止反向导入 `app/services`、`app/api` 或外部网络库；代码必须 100% 通过 `python3 tooling/check_layers.py --root backend/app`；
  - **日志绝密脱敏红线**：严禁在 `__repr__` 或结构化日志中打印 `content`（资料切片全文）与未脱敏对象存储凭证；
  - **命名与全英文规范**：表名复数 snake_case（`materials`, `material_versions`, `material_snippets`, `material_ocr_pages`）；字段名 snake_case（布尔字段严格以 `is_` 前缀）；标识符全英文，严禁拼音；仅使用 8 个缩写白名单。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含对象存储 MinIO/S3 真实文件直传与预签名 URL 签发逻辑（属于 `ZL-114`）；
  - 不包含腾讯云 OCR 真实网络 SDK 调用与图像解析客户端（属于 `ZL-115`）；
  - 不包含切片分块纯函数逻辑（已由 `ZL-107` 完成）及解析调度流水线编排服务（属于 `ZL-119`）；
  - 不包含知识点树（`knowledge_points`）与题目（`questions`）实体建模（属于 `ZL-105`）；
  - 不包含资料导入 HTTP API 控制器（`POST /api/v1/materials` 属于 `ZL-127`）；
  - 永久不实现教务系统对接、复杂跨资料知识图谱交叉融合与多模态音视频解析。
* **完成判定条件 (Definition of Done)**:
  - 在 `backend/app/models/` 完成 `Material`, `MaterialVersion`, `MaterialSnippet`, `MaterialOCRPage` 实体模型定义并通过 mypy 严格类型校验；
  - 完成包含 pgvector 扩展及 HNSW 索引定义的 Alembic 数据库迁移脚本；
  - 编写并执行并通过模型实例化单测、字段约束校验单测及 Alembic 升降级（`upgrade` 与 `downgrade`）双向测试；
  - 静态检查与分层门禁全绿：`ruff format --check .`、`ruff check .`、`mypy app`、`bandit -r app -ll`、`python3 tooling/check_layers.py --root backend/app`、`python3 tooling/check_sdlc_integrity.py` 退出码全部为 0。

## 6. 未决疑问与待探讨点 (Open Questions)
- 1. **全量原始文本存储方案平衡**：解析抽取后的整篇长文档文本（可能达数十万字）是直接落库于 `material_versions.raw_text`，还是统一作为对象写入 MinIO/S3，仅在版本表中记录 `raw_text_storage_key`？建议采用 MinIO 存储纯文本对象，数据库仅保留 800 字以内的切片与对象存储 Key，保持 PostgreSQL 紧凑高效并规避大型 TOAST 频繁 I/O。
- 2. **本地单测与轻量环境下的 pgvector 兼容适配**：开发机与 CI 若在无 pgvector 原生扩展的轻量环境（如纯内存 SQLite 或无扩展环境）中执行测试，pgvector 的 `Vector` 类型和 HNSW 索引语法无法直接执行。建议确认在 `conftest.py` 或测试环境中是否统一采用真实 PostgreSQL 16 + pgvector 容器作为集成测试依赖，而在模型单元测试中对 Vector 类型做优雅映射。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: yezisama / 2026-09-23
