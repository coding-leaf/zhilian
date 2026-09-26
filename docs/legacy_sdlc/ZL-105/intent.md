# Intent: 知识点与题目持久化数据模型及审计日志

- **任务编号**: ZL-105
- **提出人**: Dev
- **创建时间**: 2026-09-23 20:08
- **初始 Change Tier**: Tier 3
- **当前状态**: Draft / In-Review / Accepted

---

## 1. 问题与现状背景 (Problem)
在智练自主学习平台中，系统以学生自主上传的学习资料切片（`material_snippets`）为唯一事实输入源，经由大模型抽取建树形成知识图谱，并由检索增强出题引擎生成题目驱动练习主闭环（需求规格说明书 FR-14~28）。
当前系统已完成工程协议基线（ZL-102）、用户空间与鉴权隔离底座（ZL-103）、学习资料/版本/切片持久化模型（ZL-104）以及资料分块纯函数核（ZL-107）。然而，承载知识结构沉淀与题目出题质检的持久化数据底座仍处于空白状态，面临以下关键问题与技术痛点：
1. **缺少知识点树形拓扑持久化模型 (`knowledge_points`)**：需求 FR-14 明确要求“从知识片段中全自动抽取建树，支持 2~5 级层级，本期不提供人工编辑入口”，FR-15 要求“从知识点可查到来源片段，从片段可查到知识点”。当前缺少基于自引用外键（`parent_id`）的树形结构模型；无法按 `(user_id, material_id, version_id)` 三元组隔离多版本知识点；无法持久化记录层级深度（`level`）、抽取批次号（`batch_id`）以及质检重抽超限后的低可信度降级标记（`is_low_confidence`，对应 FR-19）；亦缺少片段与知识点的双向溯源关联表模型（`knowledge_point_snippets`）。
2. **缺少全面覆盖 7 大题型与 6 要素的题目主实体 (`questions`)**：需求 FR-20 规定系统必须支持生成单选、多选、判断、填空、名词解释、简答、案例分析七类题目；FR-22 明确每道题必须包含题干、答案、解析、难度、来源片段、所属知识点 6 要素及主观题必填的评分细则（要点分值总和与题目总分一致）。当前缺乏标准题目实体与题型枚举；缺乏客观题选项（`options`）与主观题评分细则（`grading_rubric`）的结构化 JSONB 约束；缺乏可用与待处理区状态划分（`status`），导致出题流程产物无处落库。
3. **缺少题干语义向量表示与高效查重索引 (pgvector 1024 维 HNSW)**：概要设计 4.2 节与需求 FR-24 明确规定“服务层为每道题的题干与选项组合计算 1024 维向量，与同一资料下已通过质检的题目向量做相似度比较，相似度高于 0.90 的判为重复题”。若题目表未引入定长 1024 维向量列（`embedding`）及 HNSW 余弦距离索引，重复题质检将退化为全量扫表，导致出题质检接口延迟大幅恶化。
4. **缺少题目四类质检结果记录模型 (`question_quality_checks`)**：需求 FR-24 与 FR-25 规定题目生成后必须由题目质检算法执行四项一票否决式检查（重复题、答案冲突、无来源题目、明显歧义），不合格题目被拦截进入待处理区并记录剔除原因与批次号。当前缺少统一的质检记录模型，无法持久化记录生成批次中的逐题质检明细与相似度度量值。
5. **缺少用户题目修改痕迹的审计日志模型 (`question_audit_logs`)**：需求 FR-26 规定用户必须能够预览、修改、删除与重新生成题目，且“修改后的题目保留修改痕迹”。若缺少专门的不可变审计日志表，用户对题目的编辑、软删除或重新生成操作将覆灭原始大模型生成数据与演化历史，无法满足合规追溯与后续知识点掌握度准确性对账需求。
6. **缺少严格的多租户隔离与绝密脱敏保护**：根据 NFR-14 与系统核心安全红线，所有知识点、题目与审计表必须强制继承 `TenantModelMixin`（包含 `user_id` 外键与前导索引，CASCADE 级联）；实体的 `__repr__` 必须执行绝密脱敏，严禁泄露题干、答案、选项全文与评分细则，严防敏感数据泄露入日志。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [ ] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [x] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **多租户知识点树实体与片段双向溯源模型 (`knowledge_points`, `knowledge_point_snippets`)**：
   - 在 `backend/app/models/` 规范定义 `KnowledgePoint` 实体，严格继承 `Base, TimestampMixin, TenantModelMixin`；
   - 字段完整支持：UUIDv4 主键、租户标识 `user_id`、资料主键 `material_id`、版本标识 `version_id`、父节点引用 `parent_id`（自引用外键，根节点为空）、知识点名称 `name`、描述 `description`、层级深度 `level`（取值范围 1~5，满足 2~5 级层级约束）、抽取批次号 `batch_id`、低可信度标记 `is_low_confidence`（默认 False）及 UTC 时间戳；
   - 定义 `KnowledgePointSnippet` 关联实体，承载知识点与切片的多对多映射，支持通过知识点反查来源切片列表，以及从切片反查挂载的知识点集合；
   - 建立 `(user_id, material_id, version_id)` 三元组联合索引，保证多版本知识点物理隔离。
2. **多题型题目主实体与向量语义查重索引体系 (`questions` + pgvector)**：
   - 定义 `Question` 实体，严格继承 `Base, TimestampMixin, TenantModelMixin`；
   - 支持 7 大题型枚举 `QuestionType`（`single_choice`, `multiple_choice`, `true_false`, `fill_in_blank`, `term_explanation`, `short_answer`, `case_analysis`）；
   - 支持题目状态枚举 `QuestionStatus`（`available` 可用, `pending_review` 待处理区/质检拦截）；支持软删除标记 `is_deleted`（默认 False，支持用户删除与历史答卷解耦）；
   - 严格落实题目 6 要素：题干 `stem`（Text）、选项列表 `options`（JSONB，客观题有效）、参考/标准答案 `answer`（Text）、解析 `analysis`（Text）、难度系数 `difficulty`（Integer 1~5）、主来源切片标识 `source_snippet_id`（外键关联 `material_snippets.id`）及所属知识点 `knowledge_point_id`（外键关联 `knowledge_points.id`）；
   - 包含主观题评分细则 `grading_rubric`（JSONB，存储要点清单、分值分配与采分关键词，主观题必填）；
   - 包含定长 1024 维语义向量 `embedding`，基于 `get_vector_type(1024)` 实现方言兼容（生产 PG 使用 pgvector，本地测试使用 JSON 降级）；
   - 在 PostgreSQL 环境下构建 HNSW 余弦索引（`vector_cosine_ops`，参数 `m=16, ef_construction=200`），支持出题查重相似度 >0.90 高效过滤；
   - 建立 `(user_id, material_id, version_id, status)` 与 `(user_id, knowledge_point_id)` 等高效复合检索索引。
3. **题目质检结果记录模型 (`question_quality_checks`)**：
   - 定义 `QuestionQualityCheck` 实体，继承 `Base, TimestampMixin, TenantModelMixin`；
   - 字段覆盖：UUIDv4 主键、关联题目标识 `question_id`、生成批次号 `batch_id`、检查项类型 `check_type`（枚举涵盖：`NO_SOURCE`, `DUPLICATE`, `ANSWER_CONFLICT`, `AMBIGUITY`）、是否通过 `is_passed`、未通过原因 `reason`、相似度数值 `similarity_score`（浮点型，重复题检查时记录）、质检上下文元数据 `check_metadata`（JSONB）；
   - 建立 `(question_id, check_type)` 唯一或组合索引，以及 `(user_id, batch_id)` 批次过滤索引。
4. **题目修改痕迹审计日志模型 (`question_audit_logs`)**：
   - 定义 `QuestionAuditLog` 实体，继承 `Base, TimestampMixin, TenantModelMixin`；
   - 记录题目全生命周期操作：关联题目标识 `question_id`、操作动作 `action`（枚举涵盖：`CREATE`, `EDIT`, `DELETE`, `REGENERATE`）、操作人 `user_id`、修改字段名列表 `changed_fields`（JSONB）、修改前快照 `before_payload`（JSONB）、修改后快照 `after_payload`（JSONB）、修改原因/说明 `reason`；
   - 建立 `(user_id, question_id)` 索引与 `(question_id, created_at)` 时间倒序审计追踪索引。
5. **数据库迁移与双向对称回滚物理验证**：
   - 编写 Alembic 迁移脚本，在 `upgrade()` 中幂等创建 5 张数据表、外键级联与 HNSW 向量索引；
   - 在 `downgrade()` 中提供安全对称的反向清理逻辑；
   - 编写自动化升降级测试，物理验证双向迁移 100% 成功，保证生产环境可追溯与可回滚。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [x] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - **声明式多租户隔离与外键级联铁律**：所有业务实体表必须严格继承 `TenantModelMixin`，`user_id` 必须作为外键（`ForeignKey("users.id", ondelete="CASCADE")`）与非空索引列；所有涉及查询强制携带 `user_id`（阻断水平越权）；
  - **三元组检索与版本隔离约束**：知识点树与题目表必须记录 `material_id` 与 `version_id`，并建立 `(user_id, material_id, version_id)` 联合索引；出题与检索必须基于激活版本精准过滤，杜绝跨版本过期数据污染；
  - **知识点树只读与深度边界**：落实 FR-14，知识点全由算法抽取自动建树，不开放前端增删改接口；层级深度限定为 2~5 级（根节点为 1 级，叶子节点最大不超过 5 级）；
  - **pgvector 维度与索引参数**：语义向量列必须固定为定长 1024 维；HNSW 索引参数严格固定为余弦距离 `vector_cosine_ops`、`m=16, ef_construction=200`；通过 `get_vector_type(1024)` 兼容 SQLite 单测；
  - **分级软删除与答卷解耦**：落实《LEADER_ALIGNMENT.md》技术决策 2，用户删除题目必须采用软删除机制（`is_deleted=True`），禁止物理硬删除，避免破坏已有答卷关联；未来答卷表通过题目快照 JSONB 解耦；
  - **日志绝密脱敏红线**：所有实体的 `__repr__` 严禁打印题干 `stem`、选项 `options`、答案 `answer`、解析 `analysis` 及评分细则 `grading_rubric` 全文，日志仅允许记录 ID、题型、状态、知识点引用与字符长度等量化指标；
  - **架构分层依赖铁律**：实体模型位于 `backend/app/models/`，绝对禁止反向导入 `app/services`、`app/api` 或外部网络库，必须 100% 通过 `python3 tooling/check_layers.py --root backend/app`；
  - **命名与全英文规范**：表名复数 snake_case（`knowledge_points`, `knowledge_point_snippets`, `questions`, `question_quality_checks`, `question_audit_logs`）；字段名 snake_case（布尔字段加 `is_` 前缀）；标识符全英文，严禁拼音；严格限定 8 个缩写白名单。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含大模型抽取知识点与建树的调度服务逻辑（属于 `ZL-120`）；
  - 不包含检索前置阻断、大模型出题与知识点覆盖校验服务逻辑（属于 `ZL-121`）；
  - 不包含纯函数知识点质检核与题目质检核的算法实现（分别由 `ZL-109` 与 `ZL-110` 承载）；
  - 不包含练习创建、作答进度暂存、答卷提交与作答快照持久化模型（属于 `ZL-106`）；
  - 不包含题目列表管理与题目编辑的 HTTP API 控制器（属于 `ZL-128`）；
  - 永久不实现外部题库模板批量导入导出、复杂跨资料全局知识图谱拓扑融合。
* **完成判定条件 (Definition of Done)**:
  - 在 `backend/app/models/` 完成 `KnowledgePoint`, `KnowledgePointSnippet`, `Question`, `QuestionQualityCheck`, `QuestionAuditLog` 实体模型定义并通过 mypy 严格模式校验；
  - 完成包含 5 张表结构、外键关联、索引及 pgvector HNSW 向量索引的 Alembic 迁移脚本；
  - 编写并执行并通过实体模型字段约束校验单测、关系映射单测以及 Alembic 升降级（`upgrade` 与 `downgrade`）双向测试；
  - 门禁检查全绿：`ruff format --check .`、`ruff check .`、`mypy app`、`bandit -r app -ll`、`python3 tooling/check_layers.py --root backend/app`、`python3 tooling/task_cli.py check ZL-105` 退出码全部为 0。

## 6. 未决疑问与待探讨点 (Open Questions)
- 1. **知识点与切片的关联持久化设计**：需求 FR-15 要求从知识点可查到来源片段，从片段可查到知识点。在实现上存在两种方案：方案 A 是建立独立的多对多关联表 `knowledge_point_snippets`；方案 B 是在 `knowledge_points` 表中通过 JSONB 数组字段 `snippet_ids` 存储切片 UUID。权衡考量：方案 A 具备外键完整性约束（CASCADE 级联清理）、支持高效的双向索引查询，并在资料版本更新或切片重构时保证数据一致性，推荐采纳方案 A 建立标准关联表。
- 2. **题目来源切片的主关联与多切片上下文存储**：需求 FR-22 明确每道题必须包含“来源片段”，而概要设计 4.2 节指出出题上下文最多聚合 4 个切片（最多 2400 字）。一道题可能由主切片直接引出，也可能综合了 2~4 个连续切片的上下文信息。方案设计上建议在 `questions` 表中设计 `source_snippet_id: UUID`（主来源片段标识，建立外键索引便于精准定位）同时补充 `source_snippet_ids: JSONB`（记录完整出题上下文切片 ID 列表与相似度评分元数据），既满足外键完整性约束，又完整保留多切片溯源上下文。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Approved
- **签批人 / 日期**: User / 2026-09-23 20:10
