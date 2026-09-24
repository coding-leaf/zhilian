# Intent: 练习组卷、作答保存与交卷调度服务

- **任务编号**: ZL-122
- **提出人**: Dev
- **创建时间**: 2026-09-24 12:44
- **初始 Change Tier**: Tier 2
- **当前状态**: Draft / In-Review / Accepted

---

## 1. 问题与现状背景 (Problem)
在智练自主学习平台中，出题与质检服务（ZL-121）及练习持久化模型（ZL-106）已经就绪，但系统尚缺少负责练习生命周期流转、组卷编排、作答保存与交卷调度的服务层与仓储层核心实现。
具体业务痛点与技术现状包括：
1. **多模式组卷与打散算法缺失**：需求 FR-29/FR-30/FR-31 规定练习支持常规范围组卷与薄弱点/错题重练组卷，且含两个以上知识点时相邻题目所属知识点不得相邻（出题打散）；当前未实现组卷排序与打散纯函数，也未有对可用题目题库不足（40012）时的严格阻断与缺口处理；
2. **练习作答持久化与断网恢复仓储缺失**：需求 FR-32/FR-33/FR-34 规定用户作答需按 `(practice_id, question_id)` 进行逐题暂存、用时统计与未答标记，并支持退出后恢复进度；缺少严格基于多租户 `user_id` 过滤的 `PracticeRepository` 与防越权封装；
3. **交卷强幂等与判题队列异步调度缺失**：需求 FR-35/FR-36 规定交卷请求必须基于客户端 `submit_idempotency_key` 实现分布式强幂等拦截（结合 `IdempotencyProtocol` 与底层联合唯一索引），阻断 24 小时内的重复交卷；交卷后需更新练习状态为 `in_progress` 并向 `QueueProtocol` 投递 `grading_jobs` 异步判题任务；未作答题目必须校验并由独立字段统计。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **纯函数题目打散算法**：实现 `scatter_adjacent_knowledge_questions` 纯函数，确保多知识点题目无缝打散、同知识点题目不相邻（满足环路复杂度 $V(G) \le 10$ 与 100% 分支覆盖）；
2. **多租户练习数据仓储 (`PracticeRepository`)**：在 `backend/app/repositories/practice.py` 中封装 `Practice` 与 `AttemptItem` 的全量 CRUD，100% 强制 `user_id` 过滤阻断水平越权，零跨层导入；
3. **练习核心领域服务 (`PracticeService`)**：在 `backend/app/services/practice.py` 中实现：
   - 组卷支持三种模式（顺序 SEQUENTIAL、随机 RANDOM、薄弱知识点/错题重练 WEAK_POINTS），题目不足时抛出 `PracticeEmptyQuestionsError` (40012)；
   - 固化题目 6 要素快照至 `AttemptItem.question_snapshot`，实现历史答卷与原题物理彻底解耦；
   - 逐题作答原子 Upsert 保存（更新 `user_answer`, `duration_seconds`, `is_answered`），支持作答草稿即时保存与用时累加；
   - 交卷强幂等调度：基于 `IdempotencyProtocol` 抢占分布式锁，写入 `submit_idempotency_key` 与提交时间，校验未答题目数量，向 `QueueProtocol` 投递 `grading_jobs` 任务；
   - 结构化 8 要素日志输出，严格遵守绝密脱敏红线（严禁泄漏题干与作答原文）。
4. **统一业务异常体系**：在 `backend/app/core/errors.py` 中新增 `PracticeNotFoundError` (40010, 404)、`PracticeStatusError` (40011, 400)、`PracticeEmptyQuestionsError` (40012, 400)。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [ ] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [x] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 严格遵循五层单向架构依赖：`app/services` $\to$ `app/repositories`，仓储层零导入 `fastapi` 与 `app.integrations`；
  - 缩写白名单仅限 8 个：`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`；
  - 纯函数计算核严禁导入数据库、网络或 Web 依赖；
  - 日志严格执行 8 要素脱敏（`timestamp`, `level`, `logger_name`, `request_id`, `user_ref`, `target_id`, `duration_ms`, `error_code`），严禁包含题干、选项与作答内容；
  - 单元测试严禁真实网络请求，执行时间毫秒级。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含对外 HTTP API 路由控制器实现（由后续 `ZL-129` 承担）；
  - 不包含实际混合判题（客观题判分、双阈值匹配、大模型主观题判题）服务逻辑（由后续 `ZL-123` 承担）；
  - 不包含掌握度更新计算与诊断报告生成逻辑（由后续 `ZL-124` 承担）；
  - 不修改现有数据库表结构或 Alembic 迁移脚本（完全复用 `ZL-106` 冻结的表结构）。
* **完成判定条件 (Definition of Done)**:
  - `PracticeRepository` 与 `PracticeService` 全量实现并通过单元测试；
  - 纯函数题目打散算法行覆盖率与分支覆盖率达标；
  - 仓储层 100% 覆盖跨租户水平越权阻断测试；
  - 交卷幂等并发冲突与重放测试 100% 通过；
  - `python3 tooling/check_layers.py --root backend/app` 0 违规；
  - 后端自动化测试全绿。

## 6. 未决疑问与待探讨点 (Open Questions)
- 概念命名映射：提示词中提及的 `PracticeSession` 与 `PracticeQuestion`/`PracticeAnswer` 已在架构基线 `ZL-106` 中统一标准化为 `Practice` (练习主实体) 与 `AttemptItem` (作答快照项)，生命周期状态采用两阶段状态机（`PracticeStatus`），本次设计需在保持向下兼容语义前提下严格对齐既有数据模型。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [ ] 场景与问题已客观复现并达成共识
- [ ] 边界、非目标与约束清晰明确
- [ ] 初始 Change Tier 评定合理
- **准出结论**: Pending
- **签批人 / 日期**: [待人类签批] / 2026-09-24 12:44
