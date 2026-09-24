# Intent: 题目生成、质检过滤与来源溯源服务

- **任务编号**: ZL-121
- **提出人**: Dev
- **创建时间**: 2026-09-24 11:17
- **初始 Change Tier**: Tier 2
- **当前状态**: Draft / In-Review / Accepted

---

## 1. 问题与现状背景 (Problem)
智练自主学习平台在完成了资料切分（ZL-107）、知识点建树（ZL-120）、纯函数题目质检核（ZL-110）及向量检索底座（ZL-116）后，缺少将各能力串联落地的出题核心服务层 `QuestionService` 与仓储层 `QuestionRepository`。
当前存在的核心业务痛点与技术缺口包括：
1. **缺少检索先于生成的强制门禁**（FR-21）：未能基于目标知识点执行切片检索，若片段缺失或最高相似度低于阈值未作阻断拒绝（40003 `MissingSourceSnippetError`）；
2. **缺少多题型结构化生成与切片溯源集成**（FR-20, FR-22）：尚未实现覆盖 7 大题型（单选/多选/判断/填空/名词解释/简答/案例分析）与 6 要素（含主观题评分细则）的 LLM 结构化提示词与反序列化，未将 Top 4 切片（<=2400 字符）溯源信息绑定至 `source_snippet_id` 与 `source_snippet_ids`；
3. **缺少质检门禁拦截与待处理区持久化**（FR-23, FR-24）：生成题目后未调用纯函数 `filter_qualified_questions` 执行无来源、重复题（1024 维向量查重）、答案冲突、明显歧义 4 类一票否决检查，不合格题目未被拦截存入待处理区（`pending_review`）并写入 `question_quality_checks` 表；
4. **缺少质检未通过重抽控制与重试上限**（FR-25）：质检拦截后未自适应调整 Prompt 并触发重抽，缺少最多重抽 2 次的熔断控制；
5. **缺少题目全生命周期修改痕迹审计与多租户仓储**（FR-26, FR-27）：尚未封装全量过滤 `user_id` 的题目 CRUD、质检记录持久化与只读审计日志持久化操作。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **仓储层沉淀 (`QuestionRepository`)**：
   - 严格在所有 SQL 查询与数据变更中强制携带 `user_id`，杜绝水平越权；
   - 零依赖 `fastapi` 与 `app.integrations`，提供针对 `questions`、`question_quality_checks`、`question_audit_logs` 的完整数据操作能力。
2. **业务服务层落地 (`QuestionService`)**：
   - **检索前置门禁**：通过 `SearchProtocol` 混合检索或 `KnowledgeRepository` 切片关联获取 Top 4 切片（<=2400 字符），若无切片或最高相似度 < 0.35 则阻断并抛出 `MissingSourceSnippetError` (40003)；
   - **大模型结构化生成**：通过 `LLMProtocol`（温度 0.3）并发/批次生成指定题型与难度的题目，校验题目 6 要素完整性与主观题分值平衡；
   - **题干语义向量化与查重准备**：通过 `EmbeddingProtocol` 计算 1024 维向量；
   - **纯函数质检核集成**：调用 `filter_qualified_questions`，滑动窗口 500 道已有题目；合格题目状态记为 `available`，不合格题目状态记为 `pending_review`；
   - **重抽熔断与持久化事务**：未通过题目自适应追加失败反馈至 Prompt，重试上限 2 次；终审合格入库，残余不合格题目入待处理区并批量记录 `QuestionQualityCheck`；全流程单事务提交/回滚；
   - **全生命周期审计与脱敏日志**：支持题目编辑/删除并落 `QuestionAuditLog`，输出 8 要素脱敏日志（严禁泄露题干、选项、答案与材料全文）。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [ ] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [x] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 严格遵守智练五层单向架构依赖：`app/services` 为全系统唯一事务开启者；`app/repositories` 严禁跨层导入 `fastapi` 与 `app/integrations`；
  - 英文标识符命名与 8 个缩写白名单（`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`）；
  - 核心计算核严禁修改（直接调用已达 100% 分支覆盖的 `filter_qualified_questions`）；
  - 单测 100% 离线，网络隔离，严禁真实联网或真实调用外部 LLM/Embedding API。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 本任务不包含对外 HTTP 路由与控制器编写（由 `ZL-128` 负责）；
  - 本任务不包含练习作答、答卷幂等与判题逻辑（由 `ZL-122`、`ZL-123` 负责）；
  - 本任务不包含前端组件与页面（由 `ZL-133` 负责）。
* **完成判定条件 (Definition of Done)**:
  - `backend/app/repositories/question.py` 完整实现并通过单元测试（越权阻断覆盖 100%）；
  - `backend/app/services/question.py` 完整实现并通过集成与单元测试（覆盖率 $\ge 85\%$）；
  - 运行 `tooling/check_layers.py` 与 `tooling/check_sdlc_integrity.py` 0 违规；
  - pytest 全量测试通过，耗时控制在毫秒/秒级。

## 6. 未决疑问与待探讨点 (Open Questions)
- **疑问 1**：当针对指定知识点出题时，切片检索优先采用 `KnowledgePointSnippet` 关联切片还是通过 `SearchProtocol` 混合检索？
  - *分析与建议*：优先取知识点显式关联的 `KnowledgePointSnippet`；若关联切片不足 4 个或为空，则调用 `SearchProtocol` 以知识点名称及考点描述为 query 进行混合检索补足，既保障关联精准度，又具备全局兜底能力。
- **疑问 2**：在质检未通过触发重抽时，是整批重抽还是仅针对不合格题目增量重抽？
  - *分析与建议*：针对未通过的具体题目增量重抽，保留已通过的合格题目，并将未通过的原因转化为 Prompt 约束，重抽上限 2 次，达到次数后若仍未通过则落入 `pending_review` 待处理区。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [ ] 场景与问题已客观复现并达成共识
- [ ] 边界、非目标与约束清晰明确
- [ ] 初始 Change Tier 评定合理
- **准出结论**: Pending
- **签批人 / 日期**: [待人类签批] / 2026-09-24 11:17
