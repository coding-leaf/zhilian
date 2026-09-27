# Research: 全量只读审计切片 PRAC（练习作答/草稿/答案单）

- **Query**: 对 PRAC 切片做前后端同片只读 bug 审计（草稿持久化/恢复、提交幂等、未答题处理、计时器清理、题型渲染覆盖、答案单同步、离场状态重置、乐观提交与失败回滚、状态/store 脱节），并做跨层契约核对。
- **Scope**: mixed（backend + frontend + cross-layer）
- **Date**: 2026-09-27
- **边界**: 只读；本文件为唯一产出，未修改任何业务代码。
- **级别依据**: `design.md` §4；ledger schema `design.md` §8。
- **证据强度标注**: 实测 > 测试 > 推理（静态）。本片无命令级实测（工具链基线由父任务单独采集）。

---

## 0. 审计范围文件

| 层 | 文件 |
|---|---|
| backend | `backend/app/services/practice.py`、`backend/app/api/v1/practices.py`、`backend/app/repositories/practice.py`、`backend/app/schemas/practice.py`、`backend/app/models/practice.py`、`backend/app/core/algorithms/practice.py` |
| frontend | `miniprogram/src/api/practice.ts`、`miniprogram/src/types/practice.ts`、`miniprogram/src/stores/practiceStore.ts`、`miniprogram/src/subpackages/practice/**` |
| 关联证据 | `miniprogram/src/utils/storage.ts`、`miniprogram/src/utils/request.ts`、`miniprogram/src/utils/recentLearning.ts`、`miniprogram/src/types/storage.ts`、`miniprogram/src/pages/index/index.vue`、`miniprogram/src/subpackages/report/components/ContinuePracticeBar.vue`、`miniprogram/src/api/diagnosis.ts`、`backend/app/services/grading.py`、`backend/app/core/algorithms/grading.py`、`miniprogram/tests/unit/**` |

---

## 1. 跨层契约核对矩阵（PRAC）

| 契约点 | 后端 | 前端 | 结论 |
|---|---|---|---|
| 练习详情题目列表字段名 | `PracticeDetailResponse.items`（嵌套 `question_snapshot`）`schemas/practice.py:256` | `PracticeSession.questions`（扁平）`types/practice.ts:23`；消费 `usePracticeSession.ts:54`、`ContinuePracticeBar.vue:136` | **不符（P0，BUG-PRAC-001）** |
| 选择题选项字段名 | 快照 `{"key","content"}` `models/practice.py:135`、`services/practice.py:305` | `{key,text}` `types/question.ts:11`；渲染 `QuestionRenderer.vue:20` | **不符（P1，BUG-PRAC-002）** |
| 交卷幂等键 | Header `Idempotency-Key`（`practices.py:352`） | 每次提交新生成（`session/index.vue:197`） | **行为不符（P1，BUG-PRAC-003）** |
| 交卷响应回放标记 | `is_idempotent_replay` 字段（`schemas/practice.py:515`） | 未消费；后端恒 false | 后端未赋值（P2，PRAC-005） |
| 练习状态枚举 | `not_started/in_progress/partially_graded/completed` + 字面量 `paused/timeout` | `idle/in_progress/paused/submitted/graded` | **不符（P2，PRAC-010）** |
| 逐题作答字段 | `user_answer: str | None`（`services/practice.py:84`），`str(list)` 强转（`:446-450`） | 允许 `string[]`（`types/practice.ts:64`） | 存储为 Python repr（P2，PRAC-016） |
| 作答列表 / 详情 API | `PUT /practices/{id}/answers`、`GET /practices/{id}` 路径一致 | `api/practice.ts` 路径一致 | 路径通过 |
| 暂停/恢复 API | `POST /practices/{id}/pause|resume`（`practices.py:252/298`） | 前端**无调用封装**（`api/practice.ts` 未导出） | 能力缺失（P2，PRAC-017） |
| 计时回填字段 | `PracticeDetailResponse` 无 `time_elapsed_seconds` | 读取 `res.data.time_elapsed_seconds`（`usePracticeSession.ts:55`） | 恒 0（P2，PRAC-015） |

---

## 2. 功能性 Bug 清单

### BUG-PRAC-001
- **级别**: P0
- **切片**: PRAC
- **层**: cross-layer
- **位置**: `backend/app/schemas/practice.py:256-259`；`backend/app/api/v1/practices.py:156-190`；`miniprogram/src/types/practice.ts:23`；`miniprogram/src/subpackages/practice/composables/usePracticeSession.ts:54`；`miniprogram/src/subpackages/report/components/ContinuePracticeBar.vue:136`
- **现象**: 后端练习详情/创建响应返回题目字段名为 `items`（每项为 `{question_snapshot:{...}}`），前端类型与消费代码读取 `res.data.questions`，不存在任何 `items→questions` 适配层，导致会话页题目列表恒为空，进入练习后只显示“暂无题目数据”。
- **证据/复现**:
  - 后端测试断言 `items`：`backend/tests/unit/api/test_practice_router.py:173`（`assert len(data["items"]) == 1`）、`:349`；schema 字段 `schemas/practice.py:256`。
  - 前端读取 `questions`：`usePracticeSession.ts:54`（`res.data.questions as PracticeQuestion[]`）、`ContinuePracticeBar.vue:136`（`res.data.questions || []`）。
  - `types/practice.ts:23` 定义 `questions`，无 `items`；`utils/request.ts:288-296` 为透传，无字段重映射。
  - 前端测试通过 mock 规避：`miniprogram/tests/unit/practice/practiceSession.spec.ts:198`、`tests/unit/api/practice.spec.ts:57` 均 mock 出 `questions`，因此真实契约不符被测试掩盖。
  - **强度**: 测试+静态（后端测试可确证 `items`；前端静态确证读 `questions`，无适配层）。
- **影响**: 核心作答流程中断——用户看不到任何题目，无法作答/交卷；PRAC 全链路不可用。
- **修复方向**: 在 `api/practice.ts` 或 composable 增加响应适配，将 `items[].question_snapshot` 展平为前端 `PracticeQuestion[]`（需同时处理 BUG-PRAC-002 的选项字段），或统一后端/前端字段契约。

### BUG-PRAC-002
- **级别**: P1
- **切片**: PRAC
- **层**: cross-layer
- **位置**: `backend/app/models/practice.py:135`；`backend/app/services/practice.py:305`；`miniprogram/src/types/question.ts:9-12`；`miniprogram/src/subpackages/practice/components/QuestionRenderer.vue:20`
- **现象**: 后端题目快照选项结构为 `{key, content}`，前端 `QuestionOption` 为 `{key, text}`，`QuestionRenderer` 向 `OptionCard` 传 `:content="opt.text"`，真实数据下 `opt.text` 为 undefined，选项正文渲染为空白。
- **证据/复现**:
  - 后端契约：`models/practice.py:129-136` 校验 `key/content`；`services/practice.py:305` 快照写入 `"options": q.options or []`；后端测试快照 `{"key":"A","content":"1次"}`（`test_practice_router.py:117-121`）。
  - 前端读取 `opt.text`：`QuestionRenderer.vue:20` 与 `:33`、`:47`（单选/多选/判断共用 `formattedOptions`）。
  - **强度**: 测试+静态（后端测试数据含 `content`；前端静态读 `text`）。当前被 BUG-PRAC-001 掩盖（列表为空时不触发）。
- **影响**: 修复 PRAC-001 后，客观选择题选项文本全部空白，无法辨识与选择。
- **修复方向**: 在响应适配层把 `content` 映射为 `text`（或统一选项字段名并同步三端）。

### BUG-PRAC-003
- **级别**: P1
- **切片**: PRAC
- **层**: frontend
- **位置**: `miniprogram/src/subpackages/practice/pages/session/index.vue:197`；`miniprogram/src/subpackages/practice/utils/draft.ts:221-229`
- **现象**: 每次点击交卷都调用 `generateIdempotencyKey()` 生成全新 UUID，未在任何位置持久化/复用；首个请求若“服务端成功但响应丢失/超时”，重试会携带新幂等键，后端因练习已 `completed` 直接返回 400（`PracticeStatusError`），用户看到失败提示但实际已交卷，强幂等 FR-35 失效。
- **证据/复现**:
  - 生成点：`session/index.vue:197`；实现：`draft.ts:221-229`（`crypto.randomUUID()`）。
  - 无持久化：全仓无 `idempotency_key` 前端缓存（`practice_drafts` 结构 `types/draft.ts:25-30` 不含该字段）。
  - 后端行为：`services/practice.py:650-676` 仅同 key 才回放；`:693-697` 已完成练习二次提交报错。
  - **强度**: 静态推理（逻辑链完整，无对应测试）。
- **影响**: 交卷失败重试不可幂等，用户可能误以为交卷失败并重复操作；极端下卡在错误提示页。
- **修复方向**: 交卷前生成一次并写入本地（如随草稿或独立缓存），在收到确定成功/明确业务终态前复用同一 key；成功后清理。

### BUG-PRAC-004
- **级别**: P1（含数据丢失风险；触发依赖体量阈值）
- **切片**: PRAC
- **层**: frontend
- **位置**: `miniprogram/src/utils/storage.ts:11,73-75`；`miniprogram/src/subpackages/practice/utils/draft.ts:181-189`；`miniprogram/src/subpackages/practice/composables/usePracticeSession.ts:80-92`
- **现象**: 每次作答同步写 `practice_drafts` 到 Storage；`storage.setItem` 在序列化体 > `MAX_STORAGE_BYTES`(20KB) 时抛 `AppError(10001)`。`handleAnswerChange` 对该写入无 try/catch，异常抛出后其后的 `setTimeout`（远端防抖同步）不会被注册；且提交前 `syncPendingDrafts` 从 Storage 读取待同步项（该条目未落盘），导致该次作答既未同步也未备份，仅存于内存 store，离开页面即丢失。
- **证据/复现**:
  - 阈值与抛错：`storage.ts:11`（`MAX_STORAGE_BYTES = 20 * 1024`）、`:73-75`（超限 `throw new AppError(10001, ...)`）。
  - 写入无保护：`draft.ts:181-189`；调用链 `usePracticeSession.ts:80-92`（`saveDraftToStorage` 在 `setTimeout` 之前）。
  - 数据量大触发：整张练习的单条记录含 `items`+`answers`，50 题 × 简答题 500 字 ≈ 25KB > 20KB。
  - **强度**: 静态推理（阈值与调用顺序可跳转确证；需长卷触发）。
- **影响**: 长练习作答可能出现未捕获异常与静默草稿丢失（本地与远端均无该题）。
- **修复方向**: 将 Storage 写入包 try/catch 并降级（如仅保留核心字段/分片），或提高上限并改为逐题 key；保证失败不影响 store 与远端同步调度。

---

### BUG-PRAC-005
- **级别**: P2
- **切片**: PRAC
- **层**: backend
- **位置**: `backend/app/services/practice.py:661-676`；`backend/app/api/v1/practices.py:418`
- **现象**: 命中幂等缓存的回放分支返回 `PracticeSubmissionResult` 但从不设置 `is_idempotent_replay=True`；API 层 `getattr(result, "is_idempotent_replay", False)` 恒取默认 `False`。响应字段 `is_idempotent_replay` 永远为 false，客户端无法识别回放。
- **证据/复现**: 回放分支构造处 `services/practice.py:661-676` 无该字段；`PracticeSubmissionResult` 定义 `:97-108` 无该属性；API `:418`。schema 声明字段 `schemas/practice.py:515-518`。
- **影响**: 回放语义字段失效（契约不符），不利于前端区分“首次提交/回放”。中间级，不阻断流程。
- **修复方向**: 在 `PracticeSubmissionResult` 增加 `is_idempotent_replay` 并在回放分支置 true，或在回放时直接返回带标记的响应。

### BUG-PRAC-006
- **级别**: P2
- **切片**: PRAC
- **层**: backend
- **位置**: `backend/app/models/practice.py:37-50`；`backend/app/services/practice.py:525,552,595,702`
- **现象**: `PracticeStatus` 枚举仅定义 `not_started/in_progress/partially_graded/completed`，但 service 直接以字面量持久化 `paused`（`:525`、判 `:552`、提交白名单 `:702`）与 `timeout`（`:595`）。状态机契约（枚举/`validate_practice_transition` `models/practice.py:159-204`）无法表达这两个实际状态。
- **证据/复现**: 枚举 4 值（`:47-50`）与字面量使用点（上述行）；`validate_practice_transition` 对 `paused/timeout` 走 `Unknown practice status` 分支返回不可跃迁（`:204`）。service 测试亦以 `"paused"/"timeout"` 断言（`tests/unit/services/test_practice_service.py:411-420`）。
- **影响**: 状态机定义与实际持久化值不一致，依赖枚举的校验/跃迁逻辑对暂停/超时态失效。
- **修复方向**: 将 `PAUSED`、`TIMEOUT` 纳入枚举并统一 service 使用枚举值。

### BUG-PRAC-007
- **级别**: P2
- **切片**: PRAC
- **层**: backend
- **位置**: `backend/app/services/practice.py:469-473`；对照 `backend/tests/unit/api/test_practice_router.py:476-505`
- **现象**: `save_answer` 仅拦截 `COMPLETED` 状态；当练习为 `paused`/`timeout`/`partially_graded` 时仍允许保存作答。路由器测试 `test_save_answer_paused_status_forbidden` 通过 mock service 抛错来“验证”暂停禁止作答，但真实 service 无此拦截，测试未覆盖真实行为。
- **证据/复现**: service 仅 `if practice.status == COMPLETED`（`:469`）；测试通过 `side_effect` 打桩（`test_practice_router.py:486-488`），未调用真实 service；service 测试仅覆盖 completed 拦截（`test_practice_service.py:470-475`）。
- **影响**: 暂停/超时态未真正冻结作答，状态机语义与测试意图不符（数据可能在被视为已归档的练习上继续变更）。
- **修复方向**: 明确各状态的作答白名单并统一在 service 拦截；补充真实 service 的 paused/timeout 用例。

### BUG-PRAC-008
- **级别**: P2
- **切片**: PRAC
- **层**: frontend
- **位置**: `miniprogram/src/stores/practiceStore.ts:155-160,145-153`；`miniprogram/src/subpackages/practice/pages/session/index.vue:202-203`；`miniprogram/src/pages/index/index.vue:92,104`；`miniprogram/src/utils/recentLearning.ts:44-58`
- **现象**: 交卷成功后仅 `clearDraftFromStorage(id)`（清 Storage）+ `practiceStore.clearSession()`（清 sessionId/questions/index），**未清除 `drafts` 中的该练习条目**；`loadDraftFromStorage` 只做 `{...drafts.value, ...saved}` 合并、从不删除。返回首页后 `extractLatestDraftPractice(practiceStore.drafts, ...)` 仍会把已完成练习当作“最近未完成练习”展示。
- **证据/复现**: `clearSession` 不触碰 `drafts`（`practiceStore.ts:155-160`）；`clearDraftFromStorage` 只改 Storage（`draft.ts:206-215`）；首页对 `practiceStore.drafts` 计算 `activePractice`（`index.vue:91-93`）并在 `onShow` 重新 `loadDraftFromStorage()` 合并（`:104,178`）；`recentLearning.ts:51-58` 取 `drafts` 中 `updated_at` 最大者。
- **影响**: 状态未重置/脱节——已交卷练习持续出现在首页“继续练习”入口，点击进入已完成会话。
- **修复方向**: `clearSession` 同步删除当前练习的 draft 条目，或 `loadDraftFromStorage` 以 Storage 为准做覆盖/裁剪。

### BUG-PRAC-009
- **级别**: P2
- **切片**: PRAC
- **层**: frontend
- **位置**: `miniprogram/src/types/practice.ts:29-33`；`miniprogram/src/subpackages/practice/types/draft.ts:25-30`；`miniprogram/src/types/storage.ts:21`；`miniprogram/src/subpackages/practice/utils/draft.ts:188,214`
- **现象**: 同一 Storage key `practice_drafts` 存在两套结构：`AnswerDraft{practice_id,answers,updated_at}` 与 `PracticeDraftRecord{practice_id,items,answers,updated_at}`。storage 白名单类型声明为 `Record<string, AnswerDraft>`（`:21`），而 composable 以 `as unknown as Record<string, never>` 强塞 `PracticeDraftRecord`（`draft.ts:188,214`）；store 的 `syncDraftToStorage` 又写 `AnswerDraft` 结构（`practiceStore.ts:141-143`）。类型系统无法约束，双写会互相覆盖字段。
- **证据/复现**: 三处类型定义与两处强转（行号如上）；两个写入口同日共用 key。
- **影响**: 存储契约不一致/类型漏洞；不同写入方产生结构漂移，消费方仅依赖 `answers` 才侥幸可用。
- **修复方向**: 收敛为单一 draft schema 与单一写入口，移除 `as unknown` 强转。

### BUG-PRAC-010
- **级别**: P2
- **切片**: PRAC
- **层**: cross-layer
- **位置**: `miniprogram/src/types/practice.ts:16`；`backend/app/models/practice.py:47-50`
- **现象**: 前端 `PracticeStatus = 'idle' | 'in_progress' | 'paused' | 'submitted' | 'graded'` 与后端实际状态集 `not_started/in_progress/partially_graded/completed`（及字面量 paused/timeout）无交集映射；`idle/submitted/graded` 后端不产生，`not_started/completed` 前端无法表达。
- **证据/复现**: 两处枚举定义；前端无任何状态归一化函数（全仓搜索无映射）。
- **影响**: 状态判断/展示逻辑与实际值脱节（如按 `submitted`/`graded` 分支永不命中）。
- **修复方向**: 统一状态枚举并增加映射层。

### BUG-PRAC-011
- **级别**: P2
- **切片**: PRAC
- **层**: backend
- **位置**: `backend/app/schemas/practice.py:241-245`；`backend/app/models/practice.py:207-353`；`backend/app/services/practice.py:322-334`
- **现象**: `PracticeDetailResponse.mode`（默认 `"sequential"`）与 `completed_count`（默认 0）在 `Practice` 模型上无对应列/属性，`model_validate` 只能取默认值；创建练习时也未持久化 `mode`（`Practice(...)` 不含 mode）。因此详情响应的 `mode` 恒为 sequential、`completed_count` 恒为 0，与实际组卷模式/已答数无关。
- **证据/复现**: `synchronize_detail_fields` 提取字段列表 `:266-284` 不含 mode/completed_count（model 无属性）；创建实体 `services/practice.py:323-334` 无 mode 参数；model 定义无该列。
- **影响**: 字段返回占位默认值（契约名实不符），前端若据此展示模式/进度将错误。
- **修复方向**: 若需对外暴露则落库/计算，否则从响应契约移除。

### BUG-PRAC-012
- **级别**: P2
- **切片**: PRAC
- **层**: frontend
- **位置**: `miniprogram/src/subpackages/practice/composables/usePracticeSession.ts:86-92,147-153`
- **现象**: 作答后 600ms 防抖远端同步；`cleanupSession`（`onUnload`/`onBeforeUnmount` 调用）直接 `clearTimeout(syncTimeout)`，不 flush 待发送项。若用户在 600ms 内退出，最后一次作答不会即时推送后端（仅本地 Storage 保留，待提交前 `syncPendingDrafts` 或网络恢复才补发）。
- **证据/复现**: `setTimeout` 创建 `:89-91`；清理处 `:147-153`；页面卸载钩子 `session/index.vue:237-246`；补发路径 `syncPendingDrafts` `:114-139`（仅网络变化/交卷触发，`:141-145`、`session/index.vue:196`）。
- **影响**: 题目耗时/作答存在短暂不同步窗口；正常经交卷 `syncPendingDrafts` 可兜底，故影响有限。
- **修复方向**: 卸载前 flush 或改为立即（非防抖）落本地并对关键项限期同步。

### BUG-PRAC-013
- **级别**: P2
- **切片**: PRAC
- **层**: backend
- **位置**: `backend/app/services/practice.py:724-771`（`session.commit()` `:742`，`idempotency.set_result` `:757`）
- **现象**: 交卷在 try 内先 `update_practice_status(COMPLETED)`→`queue.enqueue`→`session.commit()`，之后才写幂等快照 `set_result`。若 commit 成功后 `set_result` 失败（如适配器故障），事务已提交、判题任务已入队，但异常抛出→API 5xx；客户端以同 key 重试时 `get_result` 为空，再进主流程撞上 `status == COMPLETED` 得 400。
- **证据/复现**: 代码顺序如上；异常分支 `:787-790` 仅 rollback（此时已 commit）+ `release_lock`。
- **影响**: 交卷已生效但客户端收到失败且无法幂等回放；错误提示与实际状态不一致。
- **修复方向**: 将幂等快照写入纳入同一事务/提交序列，或提交失败可重试且不暴露 5xx。

### BUG-PRAC-014
- **级别**: P2
- **切片**: PRAC
- **层**: frontend（对照 backend 判题枚举）
- **位置**: `miniprogram/src/subpackages/practice/components/QuestionRenderer.vue:15-74`；`backend/app/core/algorithms/grading.py:114-123`；`backend/app/services/question.py:68-71`
- **现象**: `QuestionRenderer` 分支仅覆盖 `single_choice/multiple_choice/true_false/fill_in_blank/short_answer` 5 类；后端判题枚举还定义 `term_explanation`、`case_analysis`（主观题）。若快照出现这两类，渲染器无任何分支，仅显示题干、无输入控件，作答无法产生。
- **证据/复现**: 渲染分支 `QuestionRenderer.vue:15-74`；判题枚举 7 值 `grading.py:114-123`（`TERM_EXPLANATION`/`CASE_ANALYSIS` `:121,123`）；当前出题白名单仅 4 类（`question.py:68-71`），故属前向兼容缺口。
- **影响**: 非常规主观题题型无作答入口（渲染覆盖不全）。
- **修复方向**: 为未覆盖题型增加兜底文本输入分支，或收紧后端题型白名单保持一致。

### BUG-PRAC-015
- **级别**: P2
- **切片**: PRAC
- **层**: cross-layer
- **位置**: `miniprogram/src/subpackages/practice/composables/usePracticeSession.ts:55,82,103`；`backend/app/schemas/practice.py:232-259`
- **现象**: 前端读取 `res.data.time_elapsed_seconds` 回填计时，但后端 `PracticeDetailResponse` 无该字段（`:232-259`），故每次进入练习计时恒从 0 开始，累计用时未持久化；同时每次作答变更硬编码 `time_spent_seconds: 1`/`duration: 1`（`:103`、`:82`），并非真实耗时，且随每次输入累加，会使后端 `duration_seconds` 与真实用时偏离。
- **证据/复现**: 后端 schema 字段列表无 `time_elapsed_seconds`；前端读取 `:55`；硬编码 `:82,103`。
- **影响**: 计时展示与单题耗时统计不准确/不持久（非崩溃）。
- **修复方向**: 后端补 `time_elapsed_seconds` 或前端本地持久化累计；用真实时间差替代常量 1。

### BUG-PRAC-016
- **级别**: P2
- **切片**: PRAC
- **层**: cross-layer
- **位置**: `miniprogram/src/types/practice.ts:62-66`；`backend/app/services/practice.py:446-450`；`backend/app/models/practice.py:403-408`
- **现象**: 前端 `SaveAnswerPayload.user_answer: string | string[]`，后端 `SaveAnswerDTO.user_answer: str | None`（`services/practice.py:84`）并在 `str(user_answer)` 分支把数组转成 Python 字符串表示（如 `"['A', 'B']"`），`AttemptItem.user_answer` 为 `Text`。多选答案落库为非 JSON 的 repr 字符串。
- **证据/复现**: `:446-450` 强转；模型列 `Text`（`:403-408`）；前端类型允许数组。注：判题 `normalize_objective_token` 以正则提取字母（`core/algorithms/grading.py:272-274`），因此当前不影响多选判分，但存储格式非约定 JSON。
- **影响**: 存储/契约不一致，未来若按 JSON/集合解析作答将出错；跨端读取需额外容错。
- **修复方向**: 统一以 JSON 数组或规范化字符串（如 `"AB"`）双向传输与存储。

### BUG-PRAC-017
- **级别**: P2
- **切片**: PRAC
- **层**: frontend
- **位置**: `miniprogram/src/api/practice.ts`（整文件，共 4 个导出）；对照 `backend/app/api/v1/practices.py:252-341`
- **现象**: 后端提供 `POST /practices/{id}/pause` 与 `/resume`（`:252,298`），前端 `api/practice.ts` 未提供任何调用封装，全仓亦无调用点；暂停/恢复能力在客户端不可达（会话页仅有退出与交卷）。
- **证据/复现**: `api/practice.ts:18-80` 仅 `createPractice/fetchPracticeSession/saveAnswerDraft/submitPractice`；后端路由存在。
- **影响**: 生命周期功能前端缺失（功能不可达），但非崩溃。
- **修复方向**: 按需补前端 API 与交互入口，或确认产品不做暂停/恢复。

---

## 3. 疑似（SR）/ 环境受限（ENV）

- 本切片未发现可归为 SR（真机渲染专属）的确证项；BUG-PRAC-002/014 的渲染问题均为静态可判定契约/分支缺失，未标 SR。
- ENV：本切片未执行工具链命令，无环境受限项。

---

## 4. 计数小结

| 级别 | 数量 | 编号 |
|---|---|---|
| P0 | 1 | PRAC-001 |
| P1 | 3 | PRAC-002, 003, 004 |
| P2 | 13 | PRAC-005, 006, 007, 008, 009, 010, 011, 012, 013, 014, 015, 016, 017 |
| 疑似 SR | 0 | — |
| 环境 ENV | 0 | — |
| **合计** | **17** | — |

**最严重 3 条**：
1. `BUG-PRAC-001`（P0）后端返回 `items`、前端读 `questions` 且无适配层，练习会话题目列表恒为空，PRAC 主流程不可用。
2. `BUG-PRAC-003`（P1）交卷幂等键每次重试重新生成，超时重试非幂等，可能“已交卷却报失败”。
3. `BUG-PRAC-002`（P1）题目选项后端 `content` 与前端 `text` 字段不符，修复 001 后选项正文将空白。

---

## 5. Caveats / Not Found

- 本片未运行任何工具链命令（`pytest`/`pnpm test` 等由父任务统一采集），所有 P1/P2 证据为“静态推理 + 既有单测断言”，已在各条标注强度。
- BUG-PRAC-004 的触发依赖练习体量超过 20KB 阈值，未做运行时复现。
- BUG-PRAC-001/002 在现有前端单测中被 mock 数据掩盖，未失败；故不能据“测试全绿”判定契约一致。
- 未展开 `ok` 项：`core/algorithms/practice.py` 打散算法（边界 `len<=1`/单知识点直接返回）、仓储层 `user_id` 过滤（水平越权阻断）、逐题保存 `duration_seconds` 累加逻辑，静态审阅未发现功能性缺陷。
