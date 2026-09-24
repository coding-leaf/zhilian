# Intent: 判题编排、异步分流与自评/重判服务

- **任务编号**: ZL-123
- **提出人**: Dev
- **创建时间**: 2026-09-24 14:00
- **初始 Change Tier**: Tier 3
- **当前状态**: Accepted

---

## 1. 问题与现状背景 (Problem)
智练平台在完成组卷、作答保存与交卷入队 (ZL-122) 以及离线判题阈值与匹配算法核 (ZL-111) 后，仍缺少核心的判题编排与调度服务 (`GradingService`) 以及判题记录数据仓储 (`GradingRepository`)。当前系统存在以下业务与工程痛点：
1. **判题流水线断链**：练习交卷后派发了 `grading_jobs` 异步任务，但缺乏统一的服务编排器来分流客观题与主观题；客观题无法调用纯函数核 `match_and_grade_answer` 进行精准秒判，未答题目缺乏零分固化处理。
2. **主观题 AI 分流与超时降级机制缺失**：主观题在双阈值比对落入转 AI 区间或评分细则多义时，缺乏结构化提示词构造与大模型评估编排（调用 `run_structured_agent_workflow` 驱动 `LLMProtocol`）；一旦遇到大模型 20s 超时或限流，系统缺少降级至待重新判题（`pending_regrade`）的容灾机制，存在误判为错题的业务风险（违背 FR-42 严禁判错红线）。
3. **两阶段状态机流转未闭环**：依据《LEADER_ALIGNMENT.md》技术决策 1，当存在待重新判题主观题时，练习状态必须跃迁为 `PARTIALLY_GRADED`（部分判分/未决态），阻断正式诊断报告生成与掌握度快照计算；全卷题目判定成功后方可跃迁为 `COMPLETED`。当前状态机缺少驱动引擎。
4. **多渠道判题历史与自评/重判审计缺失**：系统需要支持离线判题、AI 判题、用户自评（`user_self`，FR-44）与后台重新判题（`ai_regrade`，FR-42）。当前缺少 `GradingRecord` 实体仓储与 `is_final` 生效指针切换逻辑，无法满足可追溯审计要求。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [ ] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [x] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **实现 GradingRepository 数据仓储**：严格落实租户隔离（全方法强制 `user_id` 过滤），提供判题记录的单条/批量创建、按作答项/练习查询、最终生效记录检索与 `is_final` 标志原子切换。
2. **实现 GradingService 判题编排服务**：
   - **整卷判题编排 (`grade_practice`)**：逐题提取作答项与快照，未作答题目快速标记零分；客观题离线秒判；主观题根据细则与纯函数算法核分流，必要时异步/同步调用 LLM 进行采分点与评语生成；
   - **20s 超时与限流降级**：调用大模型判题超时或异常时，严格降级为 `pending_regrade` 状态（严禁判错），并将练习状态跃迁为 `PARTIALLY_GRADED`；
   - **用户自主评分覆盖 (`self_evaluate_attempt`)**：允许用户对主观题进行自评分数覆盖，生成新的 `user_self` 渠道记录并将前序记录置为 `is_final=False`，重新计算卷面总分，并在全部判完后推进至 `COMPLETED`；
   - **异步重判服务 (`regrade_attempt`)**：对处于待重新判题的主观题重新触发 AI 判题，成功后更新最终得分与练习状态。
3. **全流程质量保障**：
   - 登记专属业务异常（`AttemptItemNotFoundError` 40013, `GradingNotAllowedError` 40014, `GradingExecutionError` 40015）；
   - 输出结构化 8 要素日志，绝密脱敏题干、参考答案、评分细则与用户作答原文；
   - 服务层单测行覆盖率 >= 85%，仓储层越权隔离拦截率 100%。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [ ] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [x] 数据持久化与状态存储 (Database & Storage & Schemas)
- [x] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - `GradingRepository` 严格禁止导入 `fastapi` 与 `app.integrations`，所有 SQL 操作强制包含 `user_id` 条件；
  - `GradingService` 是事务编排者，绝不在纯函数算法核内部引入任何 I/O；
  - 严格遵守 8 个缩写白名单 (`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`)；
  - 遵守两阶段状态机防错：存在 `pending_regrade` 时严禁将练习置为 `COMPLETED`；
  - 严禁将题干、标准答案、用户答案记录入日志（仅输出字符数、得分、耗时、状态等量化脱敏指标）。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含对外 HTTP 路由编写（由后续 `ZL-130` 承担）；
  - 不包含掌握度持久化聚合与诊断报告生成逻辑（由后续 `ZL-124` 承担，本服务负责在判题完成后更新作答项分值、练习总分与状态）；
  - 不包含前端自评面板与判题结果界面（由后续 `ZL-135` 承担）。
* **完成判定条件 (Definition of Done)**:
  - `backend/app/core/errors.py` 补充 3 个专属判题异常；
  - `backend/app/repositories/grading.py` 完成实现并通过多租户隔离单元测试；
  - `backend/app/services/grading.py` 完成判题编排、双阈值分流、LLM 超时降级、自评与重判全链路；
  - 全套单元测试覆盖率达标，`python3 tooling/check_layers.py --root backend/app` 验证零违规；
  - `ruff format`, `ruff check`, `mypy app` 质量门禁全绿。

## 6. 未决疑问与待探讨点 (Open Questions)
- 1. **主观题判题并发策略**：整卷若包含多道主观题需要大模型判题，是采用 `asyncio.gather` 异步并发还是线程池/单题队列拆分？经评估，当前服务采用受限并发或顺序调用（单题超时 20s），待高并发阶段可将每道主观题作为子任务投递队列。
- 2. **自评打分范围校验**：用户自评打分分值必须在 `[0, attempt_item.max_score]` 之间，且客观题严禁用户自评。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: Tech Lead / 2026-09-24 14:00
