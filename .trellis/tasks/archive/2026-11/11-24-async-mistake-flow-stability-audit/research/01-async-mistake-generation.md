# Research 01: 答题后错题归集、诊断与错题再生题同步阻塞全链路排查与异步改造方案

> **调研范围**：Issue #1 —「答题后怎么会是同步生成错题再生成? 应该异步」
> **调研方式**：只读源码静态追踪（Backend + Miniprogram 全链路）
> **状态**：已完成取证

---

## 1. 核心结论（Executive Summary）

全链路排查确认，用户体感到的「答题后同步生成错题再生成、长时间卡死/转圈」由 **1 个 P0 主根因 + 3 个 P1/P2 次生同步阻塞点** 共同造成：

1. **【P0 · 主根因】错题再生题 4 个入口全部走旧版同步出题接口 `POST /questions/generate` + 前端全屏遮罩 `withBlockingLoading('生成中...')`**
   - 答题交卷进入结果页后，点击「错题针对性生题」或底栏「错题靶向强化」（以及学情页错题本的「批量再生题」与「单考点练一练」），均调用 `practiceStore.regenerateFromWrongPoints` → `miniprogram/src/utils/questionGeneration.ts::regenerateWrongPractice` → `generateQuestionsInBatches`。
   - `generateQuestionsInBatches` 逐批**同步串行**请求 `POST /questions/generate`（`miniprogram/src/api/modules/questions.ts:44-59`，单批超时 90s），后端在 HTTP 请求线程内同步执行切片检索、LLM 结构化出题、向量查重与最多 `max_retries=2` 轮质检重抽，全部完成后前端再同步调 `POST /practices` 创建练习。
   - **强烈反差**：同一代码库中，普通出题页（`useQuestionCompose.ts:222-230, 330-375`）与薄弱点强化兜底（`useReviewCenter.ts:287-293`）已经迁移到异步队列接口 `POST /questions/jobs` + `useBackgroundTaskStore`。`questionGeneration.ts::generateQuestionsInBatches` 是**全前端仅存的同步 `apiGenerateQuestions` 调用点**。
2. **【P1 · 同步冗余】纯客观题交卷 `POST /practices/{id}/submit` 在 HTTP 请求内同步双倍执行错题归集 + 掌握度重算 + 诊断报告生成**
   - `backend/app/services/practice.py:1048-1062` 与 `1159-1173`：无主观题时，先在主事务内调用 `DiagnosisService.sync_practice_learning_state`（含按知识点逐个 `limit=200` 的 N+1 掌握度重算 + 错题 `WrongRecord` Upsert），commit 后又立即在**同一次 HTTP 请求**内调用 `DiagnosisService.ensure_diagnosis_report` → `generate_diagnosis_report`（`diagnosis.py:599-636`），后者**再次完整执行** `calculate_and_update_mastery` 与 `sync_wrong_records_from_evaluations`（纯 CPU + DB，无 LLM，但对多考点练习产生 2 倍 N+1 写放大，且受前端 `DEFAULT_REQUEST_TIMEOUT_MS = 15000ms` 约束）。
   - 含主观题时，虽然整卷判题走 `self.queue.enqueue("grading_jobs", ...)` 异步入队，但：① 若已有客观题，仍会在 submit HTTP 内同步跑一遍 `sync_practice_learning_state`；② Worker 判完后 `_sync_diagnosis_after_grading`（`grading.py:325-346`）同样先调 `sync_practice_learning_state` 再调 `ensure_diagnosis_report`，也存在双倍重算；③ 主观题在 Worker 内是 `for` 循环逐题串行调用 LLM（`grading.py:225-251`）。
3. **【P1 · 同步 LLM】报告页单题「申请 AI 复查」`POST /grading/regrade` 在 HTTP 请求内同步调用大模型并同步刷新诊断**
   - `backend/app/api/v1/grading.py:101-154` → `GradingService.regrade_attempt`（`grading.py:633-775`）直接同步调用 `invoke_subjective_llm_grading`（前端配 `LONG_REQUEST_TIMEOUT_MS = 90000ms`），落库后再同步跑 `_sync_diagnosis_after_grading`。
4. **【P2 · UX 与基础设施断层】报告页缺失全局后台任务条且判题轮询不可跨页**
   - `miniprogram/src/subpackages/report/pages/detail/index.vue` 未挂载 `<BackgroundTaskBar />`；判题轮询使用页面局部 `createPoller()`（20 次 × 2.5s = 50s，`useReportDetail.ts:78-96`），离开页面即销毁，未纳入 `useBackgroundTaskStore`。
   - 现有 `BackgroundTaskBar.vue:56-72` 对完成的 `question_job` 点击「去查看」会硬编码跳转 `/subpackages/material/pages/questions/index?view=generated&batch_id=...`（题库/组卷页），无法直接进入练习会话页（与 Issue #2 存在强联动）。

---

## 2. 端到端完整调用链追踪（Exact Code Anchors）

### 2.1 链路 A：答题交卷 → 判题 → 错题归集 → 诊断报告

```
[用户点击交卷]
  miniprogram/src/subpackages/practice/pages/session/index.vue:183-210 (confirmSubmit)
    └─ withBlockingLoading('正在提交交卷...', () => practiceStore.submit())   [阻塞全屏 mask]
         miniprogram/src/stores/practice.ts:128-146 (submit)
           1) await draftQueue.flush()                                        [等待未落库草稿 PUT /practices/{id}/answers]
           2) await apiSubmitPractice(practiceId, confirmUnanswered, key)     [POST /practices/{id}/submit, 15s timeout]
           3) await apiGetPracticeSession(practiceId)                         [GET /practices/{id}]
           4) uni.redirectTo('/subpackages/report/pages/detail/index?practice_id=...')

[后端 POST /practices/{id}/submit]
  backend/app/api/v1/practices.py:328-400 (submit_practice)
    └─ backend/app/services/practice.py:906-1120 (PracticeService.submit_practice)
         ├─ 强幂等检查/加锁 (practice.py:947-979)
         ├─ 状态跃迁 -> submitted (practice.py:1041-1047)
         ├─ _process_submission_grading (practice.py:1122-1195)
         │    ├─ 遍历全部 items，客观题同步调用 grade_offline_attempt_item (practice.py:1136-1158)
         │    ├─ [分支 1：纯客观题，needs_async_grading == False]
         │    │    ├─ practice.status = COMPLETED, completed_at = submitted_at (practice.py:1160-1163)
         │    │    └─ [同步#1] DiagnosisService.sync_practice_learning_state(partial_ok=True, commit=False)
         │    │         (practice.py:1167-1172)
         │    │         ├─ calculate_and_update_mastery: for kp in kps -> 查历史 200 条 + upsert MasteryRecord (diagnosis.py:268-358)
         │    │         └─ sync_wrong_records_from_evaluations: for item -> upsert WrongRecord / mark mastered (_diagnosis_report.py:221-258)
         │    └─ [分支 2：含主观题，needs_async_grading == True]
         │         ├─ 若 graded_any: [同步] sync_practice_learning_state(partial_ok=True, commit=False) (practice.py:1175-1184)
         │         └─ [异步] self.queue.enqueue(task_name="grading_jobs", payload={practice_id, user_id}) (practice.py:1186-1193)
         ├─ self.session.commit() (practice.py:1055)
         └─ 若 not enqueued_async:
              [同步#2 - 重复计算!] DiagnosisService.ensure_diagnosis_report() (practice.py:1056-1062)
                └─ generate_diagnosis_report() (diagnosis.py:477-692)
                     ├─ calculate_and_update_mastery()        [再算一遍全部知识点 N+1!] (diagnosis.py:599-604)
                     ├─ build_evaluation_inputs_and_mistakes() [逐知识点 knowledge_repo.get_by_id N+1] (_diagnosis_report.py:156-157)
                     ├─ synthesize_diagnosis_report()          [纯 Python 算法，无 LLM] (diagnosis.py:623-627)
                     ├─ sync_wrong_records_from_evaluations()  [再写一遍全部错题!] (diagnosis.py:630-636)
                     └─ create_diagnosis_report() + commit()   (diagnosis.py:651-652)

[异步 Worker（仅分支 2，RQ Redis 模式）]
  backend/app/integrations/queue/rq_adapter.py:40-92 (RQQueueAdapter.enqueue -> queue "zhilian")
    └─ backend/app/worker.py:56-61 (_grade_practice)
         └─ backend/app/services/grading.py:174-314 (GradingService.grade_practice)
              ├─ for item in items: _grade_attempt_item() [主观题逐题串行 _grade_with_llm, 20s/题降级 pending_regrade] (grading.py:225-251, 394-453)
              ├─ self.session.commit() (grading.py:285)
              └─ _sync_diagnosis_after_grading() (grading.py:286, 325-346)
                   ├─ sync_practice_learning_state(commit=True)  [计算#1]
                   └─ ensure_diagnosis_report() -> generate_diagnosis_report() [计算#2 重复!]

[结果页加载与轮询]
  miniprogram/src/subpackages/report/pages/detail/index.vue:107-117 (onLoad)
    └─ useReportDetail.ts:65-76 (bootstrap) -> withBlockingLoading('加载作答结果...')
         ├─ practiceStore.refreshSession(practiceId)
         ├─ loadReportIfGraded() -> diagnosisStore.loadReport() -> POST /practices/{id}/diagnosis (apiTriggerDiagnosis)
         └─ 若未 fullyGraded -> pollGrading() (页面局部 poller, 20×2500ms=50s, onUnload 即销毁)
```

### 2.2 链路 B：答题后「错题针对性生题 / 错题靶向强化」（P0 同步阻塞主链路）

4 个用户入口汇聚到同一条同步阻塞链路：

| 入口位置 | 按钮/交互 | 调用函数 | 文件锚点 |
| --- | --- | --- | --- |
| 报告详情页卡片 | 「错题针对性生题」 | `detail.startAdaptivePractice` | `miniprogram/src/subpackages/report/components/AdaptivePracticeCard.vue:7-13` → `useReportDetail.ts:142-165` |
| 报告详情页底栏 | 「错题靶向强化」 | `detail.startAdaptivePractice` | `miniprogram/src/subpackages/report/pages/detail/index.vue:51-58` → `useReportDetail.ts:142-165` |
| 学情页错题本批量 | 批量再生题 / 选中无题ID回退 | `handleBatchRegenerate` → `runRegenerate` | `miniprogram/src/pages/review/components/WrongBookSection.vue:56` → `useReviewCenter.ts:304-325, 396` |
| 学情页错题本单题 | 单考点练一练 | `handleSingleKpPractice` → `runRegenerate` | `miniprogram/src/pages/review/index.vue:86` → `useReviewCenter.ts:304-335` |

完整阻塞调用链：

```
useReportDetail.ts:150 / useReviewCenter.ts:307
  └─ withBlockingLoading('生成中...', () => practiceStore.regenerateFromWrongPoints(kpIds, scope))  [全屏阻塞遮罩!]
       └─ miniprogram/src/stores/practice.ts:175-185 (regenerateFromWrongPoints)
            └─ miniprogram/src/utils/questionGeneration.ts:71-101 (regenerateWrongPractice)
                 1) validateWrongRegenerateInput(kpIds, scope)
                 2) [同步阻塞循环] await generateQuestionsInBatches({ desiredCount: Math.max(3, kpIds.length), difficulty: 3 })
                      miniprogram/src/utils/questionGeneration.ts:31-58
                      for (const batch of batches) {                                    // 串行批次循环
                        await apiGenerateQuestions({ ... })                             // POST /questions/generate, timeout=90s!
                      }
                        └─ miniprogram/src/api/modules/questions.ts:44-59 (apiGenerateQuestions)
                             └─ backend/app/api/v1/questions.py:119-202 (POST /questions/generate)  [同步 HTTP 路由!]
                                  ├─ folder_id -> QuestionService.generate_questions_for_folder (question.py:663-789)
                                  │    └─ for material_group in groups:                 // 跨资料串行!
                                  │         generate_questions_for_knowledge_points (question.py:492-661)
                                  │           └─ 预取切片 + ThreadPoolExecutor(3) 同步等 LLM 出题/Embedding/最多 2 轮质检重抽
                                  ├─ 多 KP -> generate_questions_for_knowledge_points (同步等全部 LLM 完成)
                                  └─ 单 KP -> generate_questions (question.py:328-490, 同步等 LLM 完成)
                 3) [同步] await apiCreatePractice({ title: '错题巩固练习', question_ids, source_type: 'wrong_record' })
                      miniprogram/src/utils/questionGeneration.ts:90-98 -> POST /practices
                 4) uni.redirectTo / uni.navigateTo('/subpackages/practice/pages/session/index?practice_id=...')
```

### 2.3 链路 C：报告页主观题「申请 AI 复查」与「自评」

- **AI 复查 (`POST /grading/regrade`)**：
  - `useReportDetail.ts:126-128` → `practiceStore.requestRegrade` (`stores/practice.ts:149-153`) → `apiRegradeAttempt` (`api/modules/grading.ts:25-32`, `timeout: LONG_REQUEST_TIMEOUT_MS = 90000ms`) → `backend/app/api/v1/grading.py:101-154` → `GradingService.regrade_attempt` (`grading.py:633-775`)。
  - **在 HTTP 请求内同步调用 `invoke_subjective_llm_grading`**（`grading.py:715-722`），提交事务后再同步调用 `_sync_diagnosis_after_grading`（`grading.py:763`）。
- **用户自评 (`POST /grading/self-evaluate`)**：
  - `GradingService.self_evaluate_attempt` (`grading.py:491-628`)：无 LLM 调用，但落库后同样在 HTTP 内同步执行 `_sync_diagnosis_after_grading`（`grading.py:615`）。

---

## 3. 全量同步阻塞点清单与风险评级

| 编号 | 阻塞环节 | 精确代码位置 | 阻塞类型与耗时特征 | 严重度 |
| --- | --- | --- | --- | --- |
| **B1** | **错题再生题调用同步 `POST /questions/generate`** | `miniprogram/src/utils/questionGeneration.ts:31-101`<br>`miniprogram/src/stores/practice.ts:175-185`<br>`miniprogram/src/subpackages/report/composables/useReportDetail.ts:142-165`<br>`miniprogram/src/pages/review/composables/useReviewCenter.ts:304-335`<br>`backend/app/api/v1/questions.py:119-202` | **HTTP 同步阻塞 + 全屏 UI mask 阻塞**<br>多批次串行 × 跨资料串行 × LLM 出题/质检重抽（单批 15–90s+，极易触发小程序/网关超时与连接断开） | **P0** |
| **B2** | **纯客观题交卷同步执行 2 遍掌握度/错题归集 + 诊断报告生成** | `backend/app/services/practice.py:1048-1062, 1159-1184`<br>`backend/app/services/diagnosis.py:268-358, 376-436, 438-692`<br>`backend/app/services/_diagnosis_report.py:156-157, 221-258` | **HTTP 同步写放大 + N+1 查询**<br>无 LLM，但对 20–50 题练习在单次 15s 超时的 `submit` 请求内跑 2 遍全知识点 200 条历史查询与错题 Upsert | **P1** |
| **B3** | **单题 AI 复查同步调 LLM** | `backend/app/api/v1/grading.py:101-154`<br>`backend/app/services/grading.py:633-775`<br>`miniprogram/src/api/modules/grading.ts:25-32` | **HTTP 同步等 LLM (timeout 90s)** + 弹窗锁定 + 同步 `_sync_diagnosis_after_grading` | **P1** |
| **B4** | **Worker 整卷主观题串行调 LLM + 双倍诊断联动** | `backend/app/services/grading.py:225-251, 286, 325-346` | 虽已在 RQ Worker 异步执行，但多道主观题 `for` 循环串行调 LLM（5 题 × 10–20s = 50–100s，易超结果页 50s 轮询上限），且完成后重复算 2 遍掌握度与错题 | **P2** |
| **B5** | **`MemoryQueueAdapter` 模式下 `grading_jobs` 无后台线程兜底** | `backend/app/services/practice.py:1186-1194, 1322-1330`<br>`backend/app/integrations/queue/memory.py:140-180` | 对比 `QuestionService.create_generation_job` (`question.py:1053-1071`) 自带 `threading.Thread` 兜底，若本地以 `ZHILIAN_QUEUE__PROVIDER=memory` 启动服务，`grading_jobs` 在 `immediate_mode=False` 时永远无人消费、在 `immediate_mode=True` 时退化为同步阻塞（默认配置为 `provider="redis"`） | **P2** |
| **B6** | **报告页无 `<BackgroundTaskBar />` 且判题进度仅局部轮询** | `miniprogram/src/subpackages/report/pages/detail/index.vue`<br>`miniprogram/src/subpackages/report/composables/useReportDetail.ts:78-96` | 报告页发起异步任务后无统一非阻塞进度条承载；判题中离开报告页即丢失进度跟踪 | **P2** |

---

## 4. 仓库现有可复用异步基础设施盘点与缺口

仓库已经具备一套相当完整的异步任务基础设施，无需从零造轮子：

### 4.1 后端现有能力
1. **队列协议与 RQ Worker**：
   - `backend/app/integrations/queue/protocol.py:19`：`REGISTERED_TASK_NAMES = {"parse_material_pipeline", "grading_jobs", "generate_questions_job"}`。
   - `backend/app/integrations/queue/rq_adapter.py:40-92`：`RQQueueAdapter` 支持普通/高优双队列（`zhilian` / `zhilian_high`）、指数退避重试（`retry_limit=3`）、`job_timeout=1800s`、终态失败回调 `app.worker.handle_job_terminal_failure`。
   - `backend/app/worker.py:44-91, 157-282`：已注册 `_parse_material` / `_grade_practice` / `_generate_questions` 及对应终态失败回写 `_mark_*_failed`。
2. **异步出题任务表与 REST API**：
   - ORM 表：`question_generation_jobs`（`backend/app/models/question.py:431-521`），字段包含 `id, user_id, material_id, folder_id, status (queued|running|completed|failed), request_payload, total_kps, completed_kps, generated_count, batch_id, question_ids, error_message, created_at, updated_at, completed_at`。
   - API（`backend/app/api/v1/questions.py:205-260`）：
     - `POST /questions/jobs`（`202 Accepted`）
     - `GET /questions/jobs?active_only=true&material_id=...&folder_id=...`
     - `GET /questions/jobs/{job_id}`
   - 执行器（`backend/app/services/question.py:1015-1204`）：`run_generation_job` 使用 `execute_concurrent_kp_generation(..., max_workers=3)` 并发跑 LLM 并按考点实时 commit 进度 `completed_kps`，且在 `MemoryQueueAdapter` 下自动起 daemon 线程兜底。

### 4.2 前端现有能力
1. **全局后台任务 Store**：`miniprogram/src/stores/backgroundTask.ts`（`useBackgroundTaskStore`）
   - 统一追踪 `material_parse` 与 `question_job`，支持分阶段退避轮询（快轮询 `2.5s × 48` + 慢轮询 `5s × 157`，覆盖 `>= 15min`）、`startQuestionJob()`、`refreshActiveTasks()`、`dismissTask()`。
2. **全局非阻塞进度条组件**：`miniprogram/src/components/BackgroundTaskBar.vue`
   - 已挂载于 `pages/index/index.vue`、`pages/review/index.vue`、`subpackages/material/pages/course/index.vue`、`subpackages/material/pages/questions/index.vue`。
3. **已有异步参考实现**：
   - `miniprogram/src/subpackages/material/composables/useQuestionCompose.ts:222-375`：完整演示了如何用 `taskStore.startQuestionJob` 拆批调度异步任务并消费完成态。
   - `miniprogram/src/pages/review/composables/useReviewCenter.ts:287-293`：`handleReinforceWeak` 在题库不足时已调用 `backgroundTaskStore.startQuestionJob(...)` 并 toast「已在后台自动生成薄弱点练习题」。

### 4.3 复用现有基础设施支撑「错题异步再生题」的 5 个关键缺口
1. **无「生成完成自动组卷」语义**：`QuestionGenerationJob` 仅产出 `batch_id` 与 `question_ids`，不自动创建 `Practice`；若用户点击错题再生后离开报告页/切后台，前端无法继续执行 `apiCreatePractice`！
2. **无来源意图区分（普通出题 vs 错题强化）**：`BackgroundTaskItem`（`backgroundTask.ts:31-45`）和 `QuestionGenerationJobResponse`（`schemas/question.py:386-406`）无法区分这是一次普通出题还是错题巩固任务；`BackgroundTaskBar.vue:56-72` 点击「去查看」永远跳 `questions/index?view=generated`（题库页），不符合「错题再生完直接进答题页」的预期。
3. **单任务题量上限为 20**：`QuestionGenerateRequest.count` 校验 `le=20`（`schemas/question.py:60`）；若错题涉及超过 20 个考点，前端串行多批（如 `useQuestionCompose.ts:276-290`）在页面卸载后会中断后续批次。
4. **缺少幂等防重复提交**：`POST /questions/jobs` 无 `Idempotency-Key` 或活跃任务去重，用户连点「错题针对性生题」会入队多份相同 LLM 任务造成算力浪费。
5. **报告页未接入任务条**：`subpackages/report/pages/detail/index.vue` 未引入 `<BackgroundTaskBar />`。

---

## 5. 异步化重构方案对比与推荐

### 方案 A：最小改动——仅前端迁至现有 `POST /questions/jobs`（无后端表结构变更）

- **改动方式**：
  - 废除 `questionGeneration.ts` 中对 `apiGenerateQuestions` 的同步调用；`useReportDetail.ts::startAdaptivePractice` 与 `useReviewCenter.ts::runRegenerate` 改为调用 `backgroundTaskStore.startQuestionJob(...)`（若 `kpIds.length > 20` 截断或优先取薄弱度最高的 20 个考点），立即解除阻塞并提示「已在后台为您生成错题巩固题，完成后可直接开始练习」。
  - 在 `report/pages/detail/index.vue` 挂载 `<BackgroundTaskBar auto-refresh />`。
  - 在 `backgroundTaskStore` 前端内存中标记该 `jobId` 的本地意图（如 `intent: 'wrong_practice'`），完成点击时前端再调 `apiCreatePractice(question_ids)` 并跳 `session/index`。
- **优点**：改动极小、零数据库迁移、立即可消除 P0 90s 同步阻塞。
- **缺点 / 风险**：
  - **跨会话/重载丢失意图**：小程序被回收或刷新后，`refreshActiveTasks()` 从服务端拉回 `QuestionGenerationJob` 时不知道该任务原本是要建错题练习，只能退回跳题库页。
  - **点击「开始练习」仍有二次建卷延迟与并发风险**；缺少服务端幂等去重，连点会重复消耗 LLM。

### 方案 B（推荐）：服务端「异步出题任务 + 可选自动建卷」+ 提交/判题链路减负去重

将错题再生题彻底演进为**服务端一等公民异步作业**，同时顺带消除提交链路的重复同步计算：

#### B1. 错题再生题全异步化（解决 P0 + 对齐 Issue #2）
1. **后端契约扩展（兼容现有 `POST /questions/jobs`）**：
   - 在 `QuestionGenerateRequest` 新增可选字段（向后完全兼容）：
     - `auto_create_practice: bool = False`
     - `practice_title: str | None = None`（如 `"错题巩固练习"`）
     - `source_type: str | None = None`（如 `"wrong_record"` / `"weakness"`）
     - `source_practice_id: uuid.UUID | None = None`（溯源原练习，用于幂等去重与展示）
   - 在 `QuestionGenerationJob` 表通过 Alembic 迁移新增可空列：
     - `result_practice_id: UUID | None`（任务完成后自动建卷产出的 `Practice.id`）
     - `idempotency_key: str | None`（或基于 `(user_id, source_practice_id, status in ('queued','running'))` 做进行中任务幂等复用，防止连点重复派发）
   - 若需要支持单次错题超 20 考点：在异步 `POST /questions/jobs` 内部允许单 Job 拆批或将异步路径 `count` 放宽至 `MAX_PRACTICE_QUESTIONS = 50`（因为已在 Worker 内分 KP 3 并发执行，不再受单次 HTTP 超时限制；同步端点 `POST /questions/generate` 保持 `le=20` 并标记 Deprecated）。
2. **Worker 原子收尾（`QuestionService.run_generation_job`）**：
   - 题目落库完成后，若 `request_payload.get("auto_create_practice")` 为真且存在 `available` 题目：
     - 在 Worker 内调用 `PracticeService.create_practice(...)`（使用已生成的 `available` 题目 ID，截取至 `MAX_PRACTICE_QUESTIONS`），将生成的 `practice.id` 写入 `job.result_practice_id` 后一并置 `COMPLETED`。
     - 若全部题目都落入 `pending_review`（无可用题），则 `result_practice_id = None` 并在 `job` 摘要/错误提示中明确告知，避免静默建空卷。
3. **前端无阻塞交互（`backgroundTaskStore` + `BackgroundTaskBar` + 4 个入口）**：
   - `startAdaptivePractice`（报告页）与 `runRegenerate`（学情错题本）移除 `withBlockingLoading('生成中...')`，改为调用 `backgroundTaskStore.startQuestionJob({ ..., auto_create_practice: true, source_type: 'wrong_record', practice_title: '错题巩固练习', source_practice_id })`。
   - 请求 `202 Accepted`（< 200ms）立即返回，按钮态切换为「后台生题中 X/Y 考点」并可自由浏览报告或切换其他页面。
   - `report/pages/detail/index.vue` 挂载 `<BackgroundTaskBar auto-refresh />`。
   - `BackgroundTaskBar` 识别 `job.result_practice_id`：
     - 完成态文案为「错题巩固卷已就绪（N 题）」，主按钮为「立即作答」；
     - 点击直接 `uni.navigateTo('/subpackages/practice/pages/session/index?practice_id=' + job.result_practice_id)`，**不经过题库页**（天然避免 Issue #2 的「先闪现题库」体验问题）。
     - 若用户此时仍停留在发起页且愿意自动进入，可提供轻提示条或一键按钮，不做突兀强跳以免打断用户正在看错题解析。

#### B2. 答题提交与判题后同步链路减负（解决 P1/P2）
1. **消除 `sync_practice_learning_state` + `ensure_diagnosis_report` 双倍重复计算**：
   - 现状：`practice.py:1056-1062` + `1164-1172`（纯客观题 submit）以及 `grading.py:325-346`（Worker 判完与复查/自评）均连续调用了 `sync_practice_learning_state` 和 `ensure_diagnosis_report` → `generate_diagnosis_report`，导致 `calculate_and_update_mastery`（N+1 查询）与 `sync_wrong_records_from_evaluations` 被完整执行 **2 遍**。
   - 优化：
     - 当练习已达成 `COMPLETED` 时，只调用一次 `ensure_diagnosis_report`（内部已包含完整的掌握度更新 + 错题同步 + 报告生成），**不再先调一遍 `sync_practice_learning_state`**；仅在未全判完（`submitted` / `partially_graded`）时才调用 `sync_practice_learning_state(partial_ok=True)`。
     - 进一步地，可评估在 `POST /practices/{id}/submit` 路径中**把诊断报告生成（或纯客观题的后置学习态同步）也统一异步化或保持快速单次执行**：
       - 若纯客观题同步判分仅需 < 100ms，优化 N+1 批量查询并去掉双倍计算后，单次 submit 可稳定控制在 100–300ms 内，进入结果页立刻可见分数与错题（UX 最好）；
       - 若后续希望**所有**练习交卷后错题归集与诊断报告完全解耦，也可将 `sync_practice_learning_state + ensure_diagnosis_report` 统一放入 `grading_jobs` Worker，由 `POST /practices/{id}/submit` 仅落库交卷并立即返回 `202/200 submitted`（但需权衡纯客观题多一次 2.5s 轮询延迟）。
2. **主观题 Worker 并发判分 + 判题进度接入全局任务条（可选二期）**：
   - `GradingService.grade_practice`（`grading.py:225-251`）中多道主观题可参考 `_question_generation.py:524` 的受控 `ThreadPoolExecutor(max_workers=3)` 并行调用 LLM，单线程汇总写库，将 5 道主观题判分时间从 60–100s 降至 ~20s。
   - `POST /grading/regrade`（单题 AI 复查）可改为 `202 Accepted` 入队或将复查项先置为 `pending_regrade` 再复用 `grading_jobs` Worker 异步执行，彻底消除 90s 同步 LLM HTTP 阻塞。
   - `PracticeService` 在 `MemoryQueueAdapter` 且无 handler 时补齐与 `QuestionService` 一致的 daemon 线程兜底（开发体验一致）。

### 方案 C：交卷判完后系统自动后台预生成错题巩固题

- **做法**：在 `GradingService.grade_practice` / 诊断完成后，只要存在 `wrong_count > 0`，Worker 自动静默派发一个 `generate_questions_job`。
- **对比评估**：
  - **优点**：用户看完报告点「错题强化」时可能已提前生成好。
  - **明显缺点**：① 用户可能根本不想马上再做新题（只想看解析或直接重练原错题），会造成**大量无谓 LLM Token 消耗与队列拥堵**（与 `SimpleWorker` Windows 单进程排队冲突更严重）；② 无法让用户选择/排除本次想练哪些错题考点或题型；③ 违背显式触发成本可控原则。
- **结论**：**不推荐自动静默预生成**，建议坚持**用户显式触发 + 方案 B 的全异步任务 + 幂等去重**。

### 三方案横向对比

| 维度 | 方案 A（纯前端迁 `jobs`） | 方案 B（推荐：扩展异步 Job + 自动建卷 + 去重减负） | 方案 C（交卷后自动预生题） |
| --- | --- | --- | --- |
| 消除 P0 同步阻塞 | 是 | 是 | 是 |
| 页面退出/重进后完整恢复并直达练习 | 否（退回题库页） | **是（`result_practice_id` 持久化）** | 是 |
| 幂等防连点重复扣 LLM | 否 | **是（服务端活跃任务去重/幂等键）** | 需额外去重 |
| LLM 成本控制 | 好 | **好（按需触发）** | 差（无差别预生成浪费算力） |
| 与 Issue #2（不闪现题库）契合度 | 差（完成跳 `questions/index`） | **极佳（直达 `session/index`）** | 佳 |
| 改动复杂度 | 低（仅前端） | 中（1 次小迁移 + Service/API/前端复用） | 高 |

---

## 6. 已发现的相关 `.trellis/spec/` 规范文件清单（供 `implement.jsonl` / `check.jsonl` 编排）

### Backend Specs
- `D:/code/Workspace/zhilian/.trellis/spec/backend/index.md`
- `D:/code/Workspace/zhilian/.trellis/spec/backend/directory-structure.md`
- `D:/code/Workspace/zhilian/.trellis/spec/backend/database-guidelines.md`（若扩展 `question_generation_jobs` 字段，必读迁移一致性闸门与事务边界）
- `D:/code/Workspace/zhilian/.trellis/spec/backend/error-handling.md`
- `D:/code/Workspace/zhilian/.trellis/spec/backend/logging-guidelines.md`
- `D:/code/Workspace/zhilian/.trellis/spec/backend/quality-guidelines.md`

### Frontend Specs
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/index.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/network-contract.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/api-payload-contracts.md`（必读：`POST /practices` `question_ids`/`question_count` 静默语义）
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/state-management.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/component-guidelines.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/type-safety.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/quality-guidelines.md`

### Shared Guides
- `D:/code/Workspace/zhilian/.trellis/spec/guides/cross-layer-thinking-guide.md`
- `D:/code/Workspace/zhilian/.trellis/spec/guides/code-reuse-thinking-guide.md`

---

## 7. 待收敛产品/技术决策（供主会话向用户确认）

1. **错题异步生题完成后的跳转体验**：任务完成后是在 `BackgroundTaskBar` 展示「错题巩固卷已就绪 · 立即作答」由用户点击直达答题页（推荐，不打断当前阅读解析），还是在仍停留原页时自动跳转？
2. **改造范围边界**：本次是否一并处理次生同步阻塞项——① 去除 `submit`/`grading` 双倍 `sync_practice_learning_state` 冗余计算（低风险高收益，建议纳入）；② 单题 AI 复查 `POST /grading/regrade` 是否也改为异步任务；③ Worker 整卷主观题判分是否改为 3 并发 LLM？
3. **旧同步接口 `POST /questions/generate` 处理**：前端清零调用后，后端是保留兼容（标 Deprecated 供测试/CLI 使用）还是直接下线？
