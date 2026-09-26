# Intent: 资料导入、多版本管理与解析调度服务

- **任务编号**: ZL-119
- **提出人**: Dev
- **创建时间**: 2026-09-24 08:48
- **初始 Change Tier**: Tier 3
- **当前状态**: Accepted

---

## 1. 问题与现状背景 (Problem)
智练自主学习平台以用户自主上传的学习材料（PDF、DOCX、PPTX、Markdown、TXT 及图片扫描件）作为事实源，驱动后续知识提取、个性化出题与智能判题。
当前系统已完成底层数据模型（ZL-104 `Material`, `MaterialVersion`, `MaterialSnippet`, `MaterialOCRPage`）、纯函数计算核（ZL-107 `split_material_into_snippets`, ZL-108 `verify_ocr_quality`）与各外设适配器抽象（ZL-114 `StorageProtocol`, ZL-115 `OCRProtocol`, ZL-116 `EmbeddingProtocol`, ZL-118 `QueueProtocol`, `IdempotencyProtocol`）。
然而，目前系统缺少将上述独立外设能力与纯函数算法串联成完整闭环的**业务编排服务与数据仓储实现**（`app/repositories/material.py` 与 `app/services/material.py`），导致：
1. **多格式解析与魔数预检缺失**：客户端上传文件扩展名容易伪造，缺乏真实文件二进制魔数（Magic Number）校验与大小边界控制，容易引发格式解析崩溃或安全隐患；
2. **多版本管理与防重复入库断层**：同用户重复上传相同文件时缺乏 `content_hash` 秒级查重与防重机制；资料更新时缺乏多版本隔离流转，容易污染旧版练习记录；
3. **逐页 OCR 门禁与就地重拍熔断未编排**：图片与扫描件 OCR 识别后未与 ZL-108 门禁算法集成，缺少未达标页标记、逐页替换更新逻辑及超过 3 次重拍的强制熔断保护；
4. **解析调度流水线未组装**：文本提取、OCR 门禁、纯函数分块、批量向量化生成、切片写入与版本激活的完整流水线缺乏统一的异步排队、状态流转与事务控制；
5. **软删除与不可逆物理级联销毁断裂**：缺乏租户级别的数据隔离查询，软删除未生效，且物理销毁时未能同步级联清理 MinIO 中的对象文件与向量切片。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [ ] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [x] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **建立仓储层 (`app/repositories/material.py`)**：
   - 封装 `MaterialRepository`，提供 `materials`, `material_versions`, `material_snippets`, `material_ocr_pages` 的完整 CRUD 查询与原子写入；
   - **执行多租户绝对隔离铁律**：所有查询与更新必须强制携带 `user_id`，杜绝水平越权；严格禁止导入 `fastapi` 与 `app/integrations`。
2. **建立服务编排层 (`app/services/material.py`)**：
   - 实现 `MaterialService`，作为系统内唯一允许开启数据库事务的层，编排数据库、对象存储、OCR、向量化、任务队列与幂等拦截器；
   - 提供 `create_material`：校验魔数、计算 SHA-256 查重秒传、MinIO 隔离存储、分布式幂等锁、事务落库并调度异步解析；
   - 提供 `parse_material_pipeline`：编排文档提取/OCR识别 -> OCR 质量门禁 -> 纯函数切分 -> 批量向量化 -> 批量入库 -> 激活版本状态；
   - 提供 `retry_ocr_pages`：逐页替换并重新评估质检，重拍次数严格递增，超过 3 次触发 `40002` 熔断；
   - 提供 `get_material`, `list_materials`, `soft_delete_material`, `hard_delete_material`：严格租户隔离，物理删除同步清理 MinIO 对象。
3. **扩充统一异常体系 (`app/core/errors.py`)**：
   - 登记 40001 (资料不达标/魔数不支持/超限)、40002 (重拍次数超限熔断)、40003 (资料解析处理失败) 等业务异常。
4. **性能与质量门禁对齐**：
   - 解析流水线端到端满足 NFR-07 (P90 < 30s)；测试具备 100% 隔离 Fake，单测零网络，覆盖率满足算法 $\ge 95\%$、服务 $\ge 85\%$。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [ ] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [x] 数据持久化与状态存储 (Database & Storage & Schemas)
- [x] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 严格遵守 AGENTS.md 依赖单向向下铁律：`app/services` $\rightarrow$ `app/repositories`，仓储层严禁导入 `fastapi` 与 `app/integrations`；
  - 缩写白名单限定（`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`），严禁任何私造缩写；
  - 绝密脱敏红线：结构化日志输出必须包含 8 要素，严禁记录资料全文、识别原文或明文凭证；
  - 单元测试严禁真实联网（`conftest.py` 物理阻断），外设一律采用 Memory/Fake 实现。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 本任务不包含 HTTP API 路由控制器实现（由后续 ZL-127 承担）；
  - 本任务不包含出题生成与知识点质检业务逻辑（由 ZL-120/ZL-121 承担）；
  - 本任务不修改既有数据库 DDL 模型（ZL-104 已冻结）。
* **完成判定条件 (Definition of Done)**:
  - `python3 tooling/check_layers.py --root backend/app` 0 违规；
  - 单元测试与集成编排测试 100% 通过且用时 $< 5\text{s}$；
  - 覆盖率满足 `app/services` $\ge 85\%$，无网络连接，无水平越权漏洞。

## 6. 未决疑问与待探讨点 (Open Questions)
- 纯文本/Markdown/PDF/DOCX 的文本提取实现：是否需引入第三方纯 Python 提取工具（如 `pypdf`, `python-docx`），抑或在 MVP 阶段对多媒体格式建立可插拔提取适配器与 Fake 回退？
- 异步解析流水线的触发时机：`create_material` 是由后台任务队列异步轮询驱动，还是在测试与轻量模式下支持立即同步执行？（建议：复用 `QueueProtocol` 的 `immediate_mode` 参数，保持与 ZL-118 一致）。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [ ] 场景与问题已客观复现并达成共识
- [ ] 边界、非目标与约束清晰明确
- [ ] 初始 Change Tier 评定合理
- **准出结论**: Pending
- **签批人 / 日期**: [待人类签批] / 2026-09-24 08:48
