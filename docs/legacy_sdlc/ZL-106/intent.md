# Intent: 练习、答卷、掌握度与诊断报告数据模型

- **任务编号**: ZL-106
- **提出人**: Dev
- **创建时间**: 2026-09-23 20:36
- **初始 Change Tier**: Tier 3
- **当前状态**: Draft / In-Review

---

## 1. 问题与现状背景 (Problem)
在智练自主学习平台中，出题与质检完成后，系统由学生端自主练习主闭环驱动学习、逐题作答、答卷提交、混合判题、掌握度沉淀、诊断报告与错题闭环（需求规格说明书 FR-29 至 FR-58）。
当前系统已完成用户鉴权隔离底座（ZL-103）、资料与切片持久化模型（ZL-104）以及知识点树与题目数据模型（ZL-105）。然而，承载练习全流程交互与学情沉淀的核心持久化数据模型仍处于空白状态，面临以下关键问题与技术痛点：
1. **缺少练习主实体 (`practices`) 与多维度出题配置支持**：需求 FR-29 规定用户必须能够按知识点范围创建练习，按题型、难度、题数配置题目构成；FR-30 与 FR-52 规定支持从诊断报告继续练习入口创建仅包含薄弱知识点的练习；FR-31 规定同一练习中来自同一知识点的题目不得相邻排列（需在创建时固化打散后的有序题目列表 `ordered_question_ids`）；FR-58 规定继续练习入口必须做重复合并，存在未开始的同来源练习时严禁重复创建。若无练习主表及来源追踪字段，无法支撑出题配置与继续练习防重。
2. **缺少逐题作答保存、进度恢复与强幂等答卷作答项 (`attempt_items`)**：需求 FR-34 规定作答进度本地先行、后台同步，以 `(practice_id, question_id)` 作为幂等键支持断网恢复与逐题保存；FR-35 规定提交答卷必须强幂等（`submit_idempotency_key`），防止移动端弱网并发或重试导致重复判题与数据失真；FR-36 规定未作答题目必须按零分计入对应知识点，并在报告中与答错题目明确区分。
3. **缺少与题目实体彻底解耦的题目快照机制 (《LEADER_ALIGNMENT.md》技术决策 2)**：若答卷作答记录直接对 `questions` 表建立强外键级联绑定，当用户按 FR-13 删除资料或按 FR-26 软删除/修改题目时，将引发外键完整性崩溃或导致历史答卷数据失真。必须在作答项表 `attempt_items` 中采用弱关联（`question_id` 可空），并强制固化 `question_snapshot` (JSONB) 存储题干、选项、标准答案、解析、评分细则及来源切片，实现题目修改/删除与历史作答的物理彻底解耦。
4. **缺少混合判题明细与两阶段状态机支持 (`grading_records`)**：需求 FR-37~43 规定客观题走离线规则秒判、主观题走离线匹配与 AI 兜底的混合判题，且必须分别保存离线判题结果与 AI 判题结果，标注最终来源；FR-42 规定主观题大模型超时或限流时必须标记为待重新判题（`pending_regrade`），严禁判错；《LEADER_ALIGNMENT.md》技术决策 1 明确规定采纳“两阶段答卷状态机”：答卷存在待重新判题时处于 `PARTIALLY_GRADED` 状态，严禁计算掌握度快照与生成正式诊断报告，必须支持用户自评覆盖或重新判题。
5. **缺少基于遗忘衰减的知识点掌握度持久化模型 (`mastery_records`)**：需求 FR-45~48 规定为每个知识点计算 0~1 的连续掌握度数值，并严格映射到未学、薄弱、基本掌握、熟练四档；掌握度按 `(user_id, knowledge_point_id)` 唯一聚合，结合指数时间衰减算法与最近 200 条有效答题记录快照，待重新判题题目严禁参与计算。
6. **缺少必须关联错题的数据驱动诊断报告模型 (`diagnosis_reports`)**：需求 FR-49~53 规定练习提交后自动生成包含薄弱知识点、退步知识点、可能原因、下一步建议的诊断报告；FR-50 明确硬性红线：“每个薄弱知识点必须关联至少一条本次练习的答错记录，零答题记录/零错题场景下严禁给出薄弱结论”；FR-53 规定知识结构处于降级状态时，必须打上可信度较低的降级标记。
7. **缺少状态可流转、错误类型可分类的错题本持久化模型 (`wrong_records`)**：需求 FR-54~57 规定同一用户同一道题在错题本中保持唯一（`(user_id, question_id)` 唯一键），连续答错错误次数累加；FR-55 规定明确区分概念性错误、表述不全、审题偏差与未作答 4 类错误类型；FR-57 规定用户重做答对后移出待练列表（`is_mastered=True`），但历史记录与错误次数永久保留可查；待重新判题状态的题目严禁写入错题本。
8. **缺少严格多租户数据隔离与绝密脱敏保护 (NFR-14 & 核心红线)**：练习域全部 6 张表必须严格继承 `TenantModelMixin`（包含 `user_id` 外键级联与索引），防止水平越权；模型 `__repr__` 严禁打印题目题干、选项、答案、用户作答全文及评分细则，坚决守死日志安全红线。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [ ] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [x] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **多租户练习主实体 (`practices`)**：
   - 在 `backend/app/models/` 规范定义 `Practice` 实体，严格继承 `Base, TimestampMixin, TenantModelMixin`；
   - 字段完整支持：UUIDv4 主键、租户标识 `user_id`、资料主键 `material_id`、练习标题 `title`、知识点范围 `knowledge_point_ids`（JSONB）、题型范围 `question_types`（JSONB）、难度偏好 `difficulty`、题目总数 `question_count`；
   - 固化打散后的题目 ID 有序列表 `ordered_question_ids`（JSONB，同知识点不相邻）；
   - 支持练习生命周期枚举 `PracticeStatus`（`not_started`, `in_progress`, `partially_graded`, `completed`）；
   - 支持练习来源类型枚举 `PracticeSourceType`（`normal` 常规练习, `weakness` 薄弱知识点/继续练习）；
   - 包含来源诊断报告外键引用 `source_report_id`（UUID 可空），建立 `(user_id, source_report_id, status)` 索引支撑继续练习防重合并（FR-58）；
   - 包含交卷强幂等键 `submit_idempotency_key`（String 可空，建立唯一索引防重，FR-35）与提交/完成时间戳。
2. **解耦型答卷作答项实体 (`attempt_items`) 与题目快照机制**：
   - 定义 `AttemptItem` 实体，严格继承 `Base, TimestampMixin, TenantModelMixin`；
   - 落实《LEADER_ALIGNMENT.md》技术决策 2：`question_id` 为可空弱外键，严禁建立物理级联删除强外键；
   - 强制包含 `question_snapshot` 字段（JSONB），交卷时完整固化题干、选项、标准答案、解析、评分细则及来源切片，实现题目软删除/修改与历史答卷的彻底解耦；
   - 建立 `(practice_id, question_id)` 联合唯一索引，支撑逐题暂存进度与幂等保存（FR-34）；
   - 记录用户作答内容 `user_answer`（Text，客观题选项标识或主观题文本）、是否作答 `is_answered`（Boolean，未作答题目按 FR-36 标记）、作答耗时 `duration_seconds`、题目得分 `score` 与满分 `max_score`。
3. **混合判题记录模型 (`grading_records`) 与两阶段状态机支持**：
   - 定义 `GradingRecord` 实体，严格继承 `Base, TimestampMixin, TenantModelMixin`；
   - 关联 `practice_id`、`attempt_item_id`，弱关联 `question_id`；
   - 覆盖判题渠道枚举 `GradingChannel`（`offline` 离线判分, `ai` 大模型判题, `user_self` 用户自评）；
   - 覆盖判题状态枚举 `GradingStatus`（`pending` 待判题, `success` 判分完成, `pending_regrade` 待重新判题, `failed` 判题失败）；
   - 独立记录离线与 AI 判题明细（FR-43），记录最终判定来源、匹配度/向量相似度 `similarity_score`、命中关键词 `hit_keywords`（JSONB）、遗漏要点 `missing_keywords`（JSONB）、置信度 `confidence` 与反馈评语 `feedback`；
   - 支撑两阶段状态机：若存在 `pending_regrade` 题目，练习状态跃迁为 `partially_graded`，不触发掌握度快照计算。
4. **知识点掌握度持久化模型 (`mastery_records`)**：
   - 定义 `MasteryRecord` 实体，严格继承 `Base, TimestampMixin, TenantModelMixin`；
   - 建立 `(user_id, knowledge_point_id)` 联合唯一键；
   - 记录 0.0~1.0 连续掌握度数值 `mastery_score` 与四档等级枚举 `MasteryLevel`（`unlearned` 未学, `weak` 薄弱, `basic` 基本掌握, `proficient` 熟练）；
   - 包含最后练习时间 `last_practiced_at`（用于 30 天半衰期遗忘时间衰减）、衰减更新时间戳 `decayed_at`、累计作答次数 `practice_count`、累计正确次数 `correct_count` 以及参与计算的最近 200 条有效答题记录简要元数据 `recent_records_snapshot`（JSONB）。
5. **强依据诊断报告实体 (`diagnosis_reports`)**：
   - 定义 `DiagnosisReport` 实体，严格继承 `Base, TimestampMixin, TenantModelMixin`；
   - 关联 `practice_id`（一对一外键，建立唯一索引）；
   - 结构化存储报告四大核心模块：
     * `weak_knowledge_points`（JSONB，主要薄弱知识点列表，每项强校验关联本次错题 ID 列表；零错题时为空，FR-50）；
     * `regressed_knowledge_points`（JSONB，退步知识点列表，与上次快照相比退步量 $\Delta \ge 0.05$）；
     * `analysis_causes`（JSONB，结合题型分布、未作答数量、判题渠道分析出的归因，FR-51）；
     * `actionable_suggestions`（JSONB，针对具体薄弱知识点的下一步建议与继续练习入口，FR-52）；
   - 记录未作答题目数 `unanswered_count`（FR-36 独立统计）、答错题目数 `wrong_count`、待重新判题题目数 `pending_regrade_count`、知识结构降级标记 `is_structure_degraded`（FR-53）。
6. **防重累加错题本实体 (`wrong_records`)**：
   - 定义 `WrongRecord` 实体，严格继承 `Base, TimestampMixin, TenantModelMixin`；
   - 建立 `(user_id, question_id)` 联合唯一键，确保同一用户同一题仅一条错题记录；
   - 错误类型枚举 `ErrorType` 严格覆盖需求 FR-55 四类：`conceptual` 概念性错误、`incomplete_expression` 表述不全、`question_misreading` 审题偏差、`unanswered` 未作答；
   - 支持连续答错错误次数 `error_count` 累加（FR-54），支持重做答对后移出待练列表标记 `is_mastered=True` 同时保留历史记录与错误次数可查（FR-57）；
   - 包含最近一次答错练习 `practice_id`、作答项 `attempt_item_id`、最近一次错误作答内容 `last_wrong_answer`、首次答错时间与掌握时间戳。
7. **数据迁移脚本与双向对称回滚物理验证**：
   - 编写 Alembic 迁移脚本，在 `upgrade()` 中幂等创建 6 张数据表、联合唯一约束、外键级联与索引；
   - 在 `downgrade()` 中提供安全对称的反向清理逻辑；
   - 编写迁移双向升降级自动化测试，物理验证 `upgrade` 与 `downgrade` 均 100% 成功。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [x] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - **声明式多租户隔离与外键级联铁律**: 练习域全部 6 张表必须严格继承 `TenantModelMixin`，`user_id` 必须作为外键（`ForeignKey("users.id", ondelete="CASCADE")`）与非空索引列；所有业务查询强制携带 `user_id` 条件，从数据层物理阻断水平越权；
  - **题目弱关联与快照彻底解耦**: 落实《LEADER_ALIGNMENT.md》技术决策 2 与 NFR-14，`attempt_items` 与 `wrong_records` 对 `question_id` 采用可空弱外键，严禁使用 CASCADE 物理级联删除；必须在 `attempt_items.question_snapshot` 中存储完整题目 6 要素 JSONB，保证原题被软删除或原资料被清理时，历史答卷与错题仍可完整渲染与复盘；
  - **交卷强幂等与作答逐题防并发**: `practices.submit_idempotency_key` 建立联合唯一索引（`(user_id, submit_idempotency_key)`），拦截 24 小时内的重复交卷请求；`attempt_items` 基于 `(practice_id, question_id)` 联合唯一键保证逐题保存幂等无竞态（FR-34, FR-35）；
  - **继续练习重复合并防重约束**: `practices` 表针对薄弱知识点来源建立 `(user_id, source_report_id, status)` 索引，保障“存在同来源且未开始的练习时直接复用”（FR-58）；
  - **两阶段答卷状态机与掌握度因果防错**: 严格落实技术决策 1，`practices.status` 支持 `partially_graded`；在存在待重新判题（`pending_regrade`）时，严禁写入掌握度快照，严禁生成正式诊断报告，严禁写入错题本（FR-42, FR-54）；
  - **诊断报告硬性数据支撑约束**: 落实 FR-50，报告中的薄弱知识点必须严格回溯到本次答错记录，若无错题则薄弱列表必须为空；未作答按零分统计但独立展示（FR-36）；
  - **绝密脱敏红线**: 所有实体的 `__repr__` 绝对禁止输出题目题干、选项、答案全文、用户作答内容及评分细则，仅允许打印实体 ID、状态、得分、题型及字符长度等非敏感元数据；
  - **架构分层依赖铁律**: 模型代码位于 `backend/app/models/`，严禁导入 `app/services`、`app/api`、`fastapi` 或网络库，必须通过 `tooling/check_layers.py --root backend/app`；
  - **全英文与命名规范**: 表名复数 snake_case（`practices`, `attempt_items`, `grading_records`, `mastery_records`, `diagnosis_reports`, `wrong_records`）；字段名 snake_case（布尔加 `is_`）；严格限定 8 个缩写白名单。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含练习创建与出题打散的具体服务编排逻辑（属于 `ZL-122`）；
  - 不包含客观题判题、主观题双阈值判定与 LLM 超时降级调度服务（属于 `ZL-123`）；
  - 不包含掌握度 30 天指数衰减纯函数算法与诊断报告合成纯函数的代码实现（分别属于 `ZL-112` 与 `ZL-113`）；
  - 不包含掌握度更新与错题本维护服务逻辑（属于 `ZL-124`）；
  - 不包含前端小程序练习作答页面与报告页面实现（属于 `ZL-133` 与 `ZL-134`）；
  - 永久不实现多用户答题 PK、班级作业批改与教务系统对接。
* **完成判定条件 (Definition of Done)**:
  - 在 `backend/app/models/` 完成 `Practice`, `AttemptItem`, `GradingRecord`, `MasteryRecord`, `DiagnosisReport`, `WrongRecord` 6 个实体模型及相关枚举类的规范定义，并通过 mypy 严格模式校验；
  - 实体模型中完整落实题目快照 JSONB、`(practice_id, question_id)` 唯一键、`(user_id, knowledge_point_id)` 掌握度唯一键、`(user_id, question_id)` 错题唯一键以及交卷幂等约束；
  - 完成包含 6 张表结构、外键关联、索引的 Alembic 迁移脚本，并编写自动化升降级测试，物理验证 `upgrade()` 与 `downgrade()` 均 100% 成功；
  - 编写完备的单元测试，验证实体字段约束、枚举合法性、级联软解耦机制与 `__repr__` 绝密脱敏逻辑；
  - 后端门禁与合规检查全部通过：`ruff format --check .`、`ruff check .`、`mypy app`、`bandit -r app -ll`、`python3 tooling/check_layers.py --root backend/app`、`python3 tooling/task_cli.py check ZL-106` 退出码全部为 0。

## 6. 未决疑问与待探讨点 (Open Questions)
- 1. **答卷作答项与练习实体的粒度设计（单表合并 vs 双表分离）**：在领域建模中，传统设计常分为“答卷主表 (`exam_papers`/`practice_attempts`)”与“作答明细表 (`attempt_items`)”。而在智练轻量级自主学习场景下，每次练习（`practices`）对应一次作答全生命周期（`not_started` -> `in_progress` -> `partially_graded` -> `completed`）。若拆分出独立的答卷主表，在单次练习单次交付的模型下会引入多余的 1:1 冗余关系。权衡考量：推荐采纳以 `practices` 为练习与答卷统一主实体，直接关联 `attempt_items`（逐题作答项），既简化状态机流转与查询复杂度，又能完全满足交卷幂等（`submit_idempotency_key`）与逐题进度保存（`attempt_items`）的需求。若未来支持同练习多次重做，可通过新建练习或版本字段平滑演进。
- 2. **主观题判题过程记录与最终结果在 `grading_records` 中的存储形态**：需求 FR-43 规定“系统必须分别保存离线判题结果与 AI 判题结果，并为最终结果标注来源为离线、AI 或用户自评”。存在两种方案：方案 A 是单条判题主记录中包含 `offline_result: JSONB` 与 `ai_result: JSONB` 字段；方案 B 是每次判题尝试均生成一条独立的 `GradingRecord` 历史日志，通过 `is_final: Boolean` 标记当前生效的裁定。权衡考量：方案 B 具备完备的审计溯源能力，支持用户自评覆盖、AI 超时重试及人工重判等多次流转，不丢失任何中间判题数据，契合系统“结论可信、过程可追溯”的架构准则，推荐采纳方案 B 并建立 `(attempt_item_id, is_final)` 索引。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Approved
- **签批人 / 日期**: User / 2026-09-23 20:45
