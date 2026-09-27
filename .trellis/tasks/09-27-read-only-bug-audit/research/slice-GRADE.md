# Research: Slice GRADE 只读 Bug 审计（评分/批改/自评/重批）

- **Query**: 只读审计切片 GRADE，前后端同片核对，重点分数边界/自评范围/重批状态机与幂等/乐观更新/算法分支/舍入/错误码/props 默认值与空态
- **Scope**: mixed (backend + frontend + cross-layer)
- **Date**: 2026-09-27
- **Ledger schema**: design.md §8（ID / 级别 / 层 / file:line / 现象 / 证据复现 / 影响 / 修复方向 + 证据强度）

---

## 0. 文件清单（本次核对范围）

| 层 | 文件 |
|---|---|
| backend | `backend/app/services/grading.py`、`backend/app/api/v1/grading.py`、`backend/app/repositories/grading.py`、`backend/app/schemas/grading.py`、`backend/app/core/algorithms/grading.py` |
| backend(契约对照) | `backend/app/models/practice.py`、`backend/app/schemas/practice.py`、`backend/app/schemas/diagnosis.py`、`backend/app/services/practice.py`、`backend/app/api/v1/practices.py`、`backend/app/core/errors.py`、`backend/app/main.py` |
| frontend | `miniprogram/src/api/diagnosis.ts`、`subpackages/report/components/GradingResultList.vue`、`SelfGradeModal.vue`、`RegradeModal.vue`、`OriginalSnippetDrawer.vue`、`subpackages/report/utils/reportFormat.ts`、`subpackages/report/pages/detail/index.vue`、`src/types/report.ts`、`src/stores/reportStore.ts` |
| tests | `miniprogram/tests/unit/report/gradingResults.spec.ts`、`gradingModals.spec.ts`；`backend/tests/unit/{core/algorithms,services,api,schemas,repositories}/test_*grad*` |

注：前端无 `src/api/grading.ts`，评分相关接口位于 `src/api/diagnosis.ts`（`selfGradeQuestion` / `requestRegrade`）。

---

## 1. 跨层契约核对小结（GRADE 切片）

| 契约点 | 后端 | 前端 | 结论 |
|---|---|---|---|
| 自评/重批路径 | `POST /api/v1/grading/self-evaluate`、`POST /api/v1/grading/regrade`（api/v1/grading.py:40,101） | `diagnosis.ts:132,148` 同路径 | 一致 |
| 成功响应包 | 直接返回 Pydantic 模型（无 `code` 包裹），全局异常返回 `{code,message,details}`（main.py:89-99） | `utils/request.ts` 兼容两种（合成 `code:0`） | 一致 |
| 自评请求字段 | `attempt_item_id/score/is_correct/feedback`（schemas/grading.py:16-33） | `SelfGradePayload{attempt_item_id,score,feedback?}`（types/report.ts:201-205） | `is_correct` 后端接收但被丢弃 → BUG-GRADE-011 |
| 重批响应状态语义 | 同步执行后返回 `record.status = "success"`（services/grading.py:830-852；api/v1/grading.py:137） | 前端硬编码 `status='pending_regrade'`（detail/index.vue:243-247） | 语义不一致 → BUG-GRADE-001 |
| 逐题判题状态 | 仅存于 `GradingRecord.status`，练习项接口不返回（schemas/practice.py:143-179） | `getGradingStatusInfo` 依赖 `item.status`/`score`（reportFormat.ts:110-183） | 不一致 → BUG-GRADE-002 |
| 命中/遗漏要点 | 存于 `GradingRecord.hit_keywords/missing_keywords`（models/practice.py:531-537） | 读 `item.question_snapshot.hit_keywords/missing_keywords`（GradingResultList.vue:60-75） | 后端不注入 → BUG-GRADE-003 |
| 原文切片 | 快照仅 `source_snippet_id`（services/practice.py:310） | 期望 `source_snippet{snippet_content,chapter_title,page_index}`（types/report.ts:76-82） | 不一致 → BUG-GRADE-004 |
| 报告 items | `DiagnosisReportResponse` 无 `items`（schemas/diagnosis.py:172-211） | 首选 `repData.items`（detail/index.vue:173,182） | 死分支 → BUG-GRADE-005 |
| 错误码 | 40013/40014/40015（errors.py:1025-1104），路由自评/重批强制 403（api/v1/grading.py:94,147） | `request.ts` 抛 `AppError(code,message)` | 一致（无阻断） |
| 题型集合 | 主观 = `term_explanation/short_answer/case_analysis`（algorithms/grading.py:137-143） | 仅 `short_answer` 可自评（GradingResultList.vue:178） | 不一致 → BUG-GRADE-007 |

---

## 2. 功能性 Bug Ledger

### BUG-GRADE-001（P1 · cross-layer）重批实际同步完成，前后端仍按“待重判”呈现
- **位置**: `backend/app/services/grading.py:810-852`、`backend/app/api/v1/grading.py:131-140`、`backend/app/schemas/grading.py:83-97`；`miniprogram/src/subpackages/report/pages/detail/index.vue:243-247`
- **现象**: `regrade_attempt` 在请求内同步调用 LLM 并写入 `status=SUCCESS, is_final=True` 的新记录、直接更新 `item.score`；接口把 `record.status` 原样返回为 `"success"`。前端 `onRegradeSuccess` 忽略响应 status，硬编码 `target.status='pending_regrade'` 且不更新该题分数。
- **证据/复现**:
  - services/grading.py:823 `final_score = ...`、:830-852 构造 `GradingRecord(... status=GradingStatus.SUCCESS.value ...)`、:855 `item.score = final_score`。
  - api/v1/grading.py:137 `status=getattr(record, "status", "pending_regrade")` → 实际返回 `"success"`（仅当 record 无 status 才回退默认值）。
  - schemas/grading.py:88-93 `RegradeResponse.status` 默认/描述为 `pending_regrade`；后端路由测试 `tests/unit/api/test_grading_router.py:255` 用 mock `status_str="pending_regrade"` 与真实服务行为冲突。
  - 前端 detail/index.vue:243-247 未读取 `res.status`。
- **影响**: 重判成功后 UI 显示“待重新判题/待判定”，分数仍是旧值，与后端最终态（success + 新分）矛盾；用户误以为需等待。
- **修复方向**: 明确重批是同步还是异步。若同步，前端应读取 `res.data.status` 并回填新分；后端 `RegradeResponse` 默认/文档改为 `success`（或返回新分数）。
- **证据强度**: 高（代码路径可直读；前后端与测试三方冲突）

### BUG-GRADE-002（P1 · cross-layer）pending_regrade 题目被当作“判错”显示
- **位置**: `backend/app/services/grading.py:500-527`（:508 `item.score = 0.0`）；`backend/app/schemas/practice.py:143-179`；`miniprogram/src/subpackages/report/utils/reportFormat.ts:127-183`；`miniprogram/src/subpackages/report/components/GradingResultList.vue:137-153`
- **现象**: LLM 超时/失败时降级记录 `status=pending_regrade`，但 `item.score` 被置 `0.0`。练习详情 DTO 不含任何判题状态字段，`AttemptItem` 也无 status 列，前端只能依据 `score` 判级：`score=0.0` 且非 null → `判错`。因此“待重判”题在逐题列表显示为“判错 0/x 分”。
- **证据/复现**:
  - services/grading.py:508 `item.score = 0.0`；:516 `status=GradingStatus.PENDING_REGRADE.value`。
  - reportFormat.ts:151 `if (item.score === null || item.score === undefined) → pending_regrade`；score=0.0 不命中，落到 :163-182 `score >= max*0.6?` → `wrong`。
  - schemas/practice.py:155-158 item.status 描述仅 `unanswered/answered/graded`，且 validator（:220-224）只产出 `unanswered/answered`。
- **影响**: 判错结果错误呈现；与报告层 `pending_regrade_count` 口径不一致，用户对成绩产生误判。
- **修复方向**: 练习项 DTO 暴露 `is_final` 判题记录状态（或后端补 item 级判题状态映射），前端优先按 grading status 渲染。
- **证据强度**: 中高（静态直读；推理链完整，未跑集成）

### BUG-GRADE-003（P2 · cross-layer）要点命中/遗漏永远不显示（契约位置不一致）
- **位置**: `backend/app/models/practice.py:531-537`、`backend/app/services/grading.py:397-398`、`backend/app/schemas/practice.py:90-127`、`backend/app/schemas/diagnosis.py:172-211`；`miniprogram/src/subpackages/report/components/GradingResultList.vue:60-75,165-169`、`miniprogram/src/types/report.ts:108-109`
- **现象**: 前端从 `item.question_snapshot.hit_keywords/missing_keywords` 读取关键词；后端把这两个字段写在 `GradingRecord` 上，`QuestionSnapshotDTO`/`PracticeItemDetailResponse` 既不注入也不合并，诊断报告响应也无逐题 items。故 `hasKeywords` 恒为 false，胶囊区不渲染。
- **证据/复现**: `rg "hit_keywords" backend/app` 仅命中 models/practice.py、schemas/grading.py、services/grading.py；`QuestionSnapshotDTO`（schemas/practice.py:90-127）与 `PracticeItemDetailResponse`（:143-179）均无该字段；snapshot 构造（services/practice.py:302-312）也不含。
- **影响**: 主观题要点命中/遗漏 UI 完全失效。
- **修复方向**: 练习/报告逐题接口合并当前生效 `GradingRecord.hit_keywords/missing_keywords`（放到 item 顶或 snapshot），或前端改读判题记录字段。
- **证据强度**: 高（跨层 grep + 契约直读）

### BUG-GRADE-004（P2 · cross-layer）原文溯源抽屉入口可见但内容恒为空
- **位置**: `backend/app/services/practice.py:310`、`backend/app/schemas/practice.py:110-117`；`miniprogram/src/subpackages/report/components/GradingResultList.vue:48-52,171-175`、`pages/detail/index.vue:207-214`、`types/report.ts:76-82,106`
- **现象**: `hasSnippet` 因 `source_snippet_id` 为真而显示“查看原文依据”，但 `handleViewSnippet` 读取 `question_snapshot.source_snippet`（后端从不产出该对象）→ `activeSnippet=null` → 抽屉恒显示“暂无原文切片内容”。
- **证据/复现**: snapshot 仅写 `"source_snippet_id": str(q.source_snippet_id)`（services/practice.py:310）；`rg "source_snippet\b" backend/app` 无产出该对象的写入；前端 `source_snippet?: OriginalSnippet`（types/report.ts:106）。
- **影响**: 原文溯源功能不可用；空态被误当作无数据。
- **修复方向**: 逐题接口按 `source_snippet_id` 关联返回 `{snippet_content,chapter_title,page_index}`，或前端改从命中的切片元数据组装。
- **证据强度**: 高

### BUG-GRADE-005（P2 · cross-layer）报告响应的 `items` 分支为死代码
- **位置**: `backend/app/schemas/diagnosis.py:172-211`；`miniprogram/src/subpackages/report/pages/detail/index.vue:173,182-186`
- **现象**: 详情页优先使用 `reportRes.data.items` 作为判题列表，但 `DiagnosisReportResponse` 无 `items` 字段，恒走 `practiceRes.data.items` 回退。若 practice 请求失败（`catch(()=>null)`，:163），列表为空 → `GradingResultList` 空态。
- **证据/复现**: schemas/diagnosis.py:172-211 字段集合无 `items`；前端 :182-186 双分支。
- **影响**: 主数据源契约不成立，依赖次级请求；容错路径下逐题区静默为空。
- **修复方向**: 二选一收敛：报告接口返回 items，或删除前端 `repData.items` 分支并显式处理 practice 失败。
- **证据强度**: 高

### BUG-GRADE-006（P2 · frontend）报告页初始化重复请求（onLoad + onMounted 双触发）
- **位置**: `miniprogram/src/subpackages/report/pages/detail/index.vue:259-275`
- **现象**: `onMounted` 与 `onLoad` 均调用 `loadReportData`。uni-app 页面生命周期下 `onLoad` 先执行并设置 `currentPracticeId`，随后 `onMounted` 命中 `currentPracticeId` 再次请求，同一页发起两次 `fetchDiagnosisReport` + `fetchPracticeSession`。
- **证据/复现**: :269-275 `onLoad` 内 `loadReportData(pid)`；:259-267 `onMounted` 内再次 `loadReportData(pid)`；无去重/守卫标志。
- **影响**: 首屏重复网络请求与状态写入，浪费配额、可能覆盖用户刚做的乐观更新。
- **修复方向**: 只保留一个加载入口（建议 `onLoad`），或加 `loaded` 标志/请求去重。
- **证据强度**: 中（静态生命周期推断）

### BUG-GRADE-007（P2 · cross-layer）非 short_answer 主观题（名词解释/案例分析）无自评与重判入口
- **位置**: `backend/app/core/algorithms/grading.py:137-143`、`backend/app/services/grading.py:628`；`miniprogram/src/subpackages/report/components/GradingResultList.vue:177-181,124-130`
- **现象**: 前端 `canSelfGrade` 仅当 `question_type === 'short_answer'`；后端主观集为 `term_explanation/short_answer/case_analysis`（自评仅拦客观题）。故名词解释、案例分析题不显示“手动自评/申请重判”。且 `questionTypeMap` 缺这两类 → 题型标签回退“试题”。
- **证据/复现**: GradingResultList.vue:178；algorithms/grading.py:137-143 `SUBJECTIVE_QUESTION_TYPES`；services/grading.py:628 仅 `q_type in OBJECTIVE_QUESTION_TYPES` 才拒绝。
- **影响**: 合法主观题无法自评/重判，功能可用性缺口。
- **修复方向**: 前端改用主观题集合判定（并补全题型标签映射）。
- **证据强度**: 高

### BUG-GRADE-008（P2 · cross-layer）未作答主观题展示“申请重判”，后端拒绝
- **位置**: `miniprogram/src/subpackages/report/components/GradingResultList.vue:177-181,93-95`；`backend/app/services/grading.py:778-782`
- **现象**: `canSelfGrade` 对 `short_answer` 恒真，未作答题（status=unanswered、score=0.0）也显示“申请重判”；后端 `regrade_attempt` 对 `not item.is_answered or not item.user_answer` 抛 `GradingNotAllowedError`（403）。
- **证据/复现**: 前端条件不含 `is_answered`；后端 :778-782。
- **影响**: 用户可点击后被 403 拒绝，入口有效性错误。
- **修复方向**: 重判入口增加 `is_answered` 判定（自评是否允许未作答按产品定）。
- **证据强度**: 高

### BUG-GRADE-009（P2 · backend algorithm）得分舍入用 Python 银行家舍入，与声明的 half-up 0.5 粒度冲突
- **位置**: `backend/app/core/algorithms/grading.py:47-48,791-795`
- **现象**: 常量注释声明“得分舍入粒度为 0.5 分 (half-up)”，实现 `round(raw_score / unit) * unit`。Python `round` 为 round-half-to-even；在 `raw_score/unit = k.5` 且 k 为偶数时结果与 half-up 差 0.5。
- **证据/复现**:
  - 可达例：`max_score=10`，`match_score=0.925`（≥0.82 走离线判对）→ `raw=9.25`，`9.25/0.5=18.5`，`round(18.5)=18`（偶数）→ 9.0；half-up 应 9.5。
  - 现有测试仅断言 `result.score % 0.5 == 0.0`（`tests/unit/core/algorithms/test_grading.py:512-533`），未覆盖 `.25` 边界。
- **影响**: 分数边界少给 0.5 分，与设计文档/注释不符。
- **修复方向**: 使用 `decimal.Decimal(...).quantize(ROUND_HALF_UP)` 或 `math.floor(raw/unit + 0.5)`。
- **证据强度**: 中高（静态 + Python 语义；边界可达性依赖精确 quarter 值）

### BUG-GRADE-010（P2 · backend）LLM 判分/重批未按 0.5 粒度舍入，与离线路径不一致
- **位置**: `backend/app/services/grading.py:461-462`、`backend/app/services/grading.py:823`
- **现象**: 离线路径按 `score_rounding_unit` 取整，LLM 首次评分与重批仅 `min/max` 夹取，未按 0.5 粒度舍入；同一题目不同渠道得分粒度不一致。
- **证据/复现**: :461 `final_score = min(item.max_score, max(0.0, float(output.score)))`；:823 同形；对比 algorithms/grading.py:791-795。
- **影响**: 分值出现非 0.5 倍数（如 7.3），与全局舍入策略/前端展示（`toFixed(1)`）不统一。
- **修复方向**: 统一在服务层落库前应用 `score_rounding_unit`。
- **证据强度**: 中（静态；是否属约定偏差需产品确认）

### BUG-GRADE-011（P2 · cross-layer）`SelfEvaluateRequest.is_correct` 被接收但静默丢弃
- **位置**: `backend/app/schemas/grading.py:25-28`；`backend/app/api/v1/grading.py:66-74`；`backend/app/services/grading.py:60-66`
- **现象**: 请求 schema 暴露 `is_correct`，但路由构造 `SelfEvaluateDTO` 时不传（DTO 无该字段），服务端始终按 `score > 0` 推导对错。客户端传 `is_correct=false`（如 0 分但语义正确）不生效。
- **证据/复现**: api/v1/grading.py:66-70 `SelfEvaluateDTO(attempt_item_id, score, feedback)`；services/grading.py:61-67 DTO 定义无 `is_correct`。
- **影响**: 契约字段无效果，可能导致对错判定与用户预期不符（写入 `grading_metadata.is_correct`）。
- **修复方向**: DTO 增加并透传 `is_correct`，或在 schema 移除该字段消除歧义。
- **证据强度**: 高

### BUG-GRADE-012（P2 · frontend）自评弹窗把嵌套评分细则渲染为原始 JSON
- **位置**: `miniprogram/src/subpackages/report/components/SelfGradeModal.vue:187-196`；`backend/app/models/practice.py:139-149`、`backend/app/services/grading.py:354-370`
- **现象**: `rubricEntries` 对 `grading_rubric` 做顶层 `Object.entries`，后端细则是 `{dimensions|points: [...], total_score}` 结构，故显示 `label="dimensions"`、`text=JSON.stringify(数组)`，而非逐要点标签/分值。
- **证据/复现**: SelfGradeModal.vue:192-195；services/grading.py:354-356 读取 `points`/`dimensions`；models/practice.py:142-149 校验同一结构。
- **影响**: 评分细则说明区信息不可读（功能降级）。
- **修复方向**: 解析 `points/dimensions` 数组，映射 `description + weight/score` 为条目。
- **证据强度**: 中（结构性直读；属显示契约不符）

### BUG-GRADE-013（P2 · cross-layer）重批理由前端限 200 字，后端允许 500 字
- **位置**: `miniprogram/src/subpackages/report/components/RegradeModal.vue:37`；`backend/app/schemas/grading.py:72-76`
- **现象**: 前端 `:maxlength="200"`，后端 `max_length=500` 且 `reason` 可空。201–500 字的合法理由被前端静默截断；反之后端不强制最少 2 字，前端强制。前后端校验边界不一致。
- **证据/复现**: 两处字段定义直读。
- **影响**: 有效理由被截断，或两端校验语义漂移。
- **修复方向**: 对齐长度上限与必填策略（前端 500 或后端 200）。
- **证据强度**: 高

### BUG-GRADE-015（P2 · frontend）判题列表模板对 `question_snapshot` 无空值防护
- **位置**: `miniprogram/src/subpackages/report/components/GradingResultList.vue:17-19,39,62-73`
- **现象**: 模板直接访问 `item.question_snapshot.stem`、`item.question_snapshot.hit_keywords`；`hasKeywords`（:165-168）用了可选链，但渲染分支内未用。若 `question_snapshot` 为 null/缺失（后端 DTO 为 `QuestionSnapshotDTO | dict`，数据异常/旧数据可能为 null），渲染抛 `TypeError` 导致卡片区崩溃。
- **证据/复现**: :39 `{{ item.question_snapshot?.stem }}` 有可选链，但 :62 `item.question_snapshot.hit_keywords` 在 `v-if="hasKeywords(item)"` 内（hasKeywords 对 undefined snapshot 返回 false，此支不触发）；:39 无崩溃。真正无防护点为 :50 `item.question_snapshot.answer` 在 `v-if="item.question_snapshot?.answer"` 条件后（安全）及 :56 `item.question_snapshot.analysis` 在 `v-if="item.question_snapshot?.analysis"`（安全）。**复核结论：现有模板均有 `v-if`/可选链守卫，不构成空指针**。保留为低置信观察，不计入。
- **证据强度**: 低（复核后降级，暂不计）
- **状态**: 复核撤销（保留在册以便后续复核）

### BUG-GRADE-016（P2 · backend）整卷判题先失效旧记录再判分，判分抛错则该项无生效记录
- **位置**: `backend/app/services/grading.py:317-318,372-379`；`backend/app/core/algorithms/grading.py:921-930,965-966`
- **现象**: `_grade_attempt_item` 首行 `set_records_non_final_by_attempt_id`（含 `session.flush()`）把旧生效记录全部置非最终，随后才调用 `match_and_grade_answer`。若快照 `question_type` 缺失（:349 默认 `""`）或非法，`_resolve_question_type` 抛 `ValueError`（未被捕获），整批 `grade_practice` 中断；此时该项旧记录已失效，事务内出现“无生效记录”中间态，`grade_practice` 自身无 rollback。
- **证据/复现**: services/grading.py:318、:349、:372；algorithms/grading.py:925-929、:965-966；`grade_practice` 无 try/except/rollback（:194-295）。
- **影响**: 脏快照/异常题型可造成整卷判题失败且部分题目失去生效判分（依赖外层事务兜底）。
- **修复方向**: 先判分成功再切换 final；对 `match_and_grade_answer` 的 ValueError 按题目降级为 pending/failed 而非中断整卷。
- **证据强度**: 中（静态；防线依赖外部事务边界，未验证调用侧）

---

## 3. 待确认（WIRING，单列不计级）

### WIRING-GRADE-01（待确认）`grading_jobs` 仓库内无消费者，交卷后判题链路可能未触发
- **位置**: `backend/app/services/practice.py:732-740`（enqueue `grading_jobs`）；全仓无 `register_handler("grading_jobs")` 或 worker 消费实现（`queue/memory.py:57` 仅测试用 `register_handler`）。
- **证据/复现**: 全仓检索 `grading_jobs` 仅命中 `services/practice.py:734`、测试与文档；`QueueProtocol` 仅定义 `enqueue/get_status/cancel`（integrations/queue/protocol.py:60-122），无消费者。CLI `smoke.py:427-442` 直接调用 `grade_practice_submission` 绕过队列。
- **说明**: 无法证伪“外部独立 worker 进程承担消费”。若确无外部 worker，则交卷后逐题判分不执行，属 P0 级功能中断。**因证据受仓库边界限制，单列待人工确认，不计入 P0/P1/P2。**
- **建议核实**: 部署侧是否存在消费 `grading_jobs` 的工作进程；`MemoryQueueAdapter` 生产配置是否 `immediate_mode` 且注册了 handler。

---

## 4. 计数小结

| 级别 | 数量 | 编号 |
|---|---|---|
| P0 | 0 | — |
| P1 | 2 | BUG-GRADE-001、BUG-GRADE-002 |
| P2 | 12 | BUG-GRADE-003、004、005、006、007、008、009、010、011、012、013、016 |
| 疑似(SR) | 0 | — |
| 环境(ENV) | 0 | — |
| 复核撤销 | 1 | BUG-GRADE-015（空指针复核后不成立） |
| 待确认(WIRING) | 1 | WIRING-GRADE-01（不计级） |

**层分布**: backend 2（009、010、016 中 016 跨服务→计入 backend，009/010/016=3；其中 016 cross-layer 计 backend）；cross-layer 7（001、002、003、004、005、007、008、011、013 → 9）；frontend 2（006、012）。
精确计：backend=3（009、010、016），frontend=2（006、012），cross-layer=9（001、002、003、004、005、007、008、011、013）。合计 14 条（含撤销不计）。

> 说明：`cross-layer` 条目同时涉及后端契约与前端消费，按本切片“前后端同片核对”要求归为 cross-layer。`BUG-GRADE-015` 经空值守卫复核不成立，列在册但**不计入**。
