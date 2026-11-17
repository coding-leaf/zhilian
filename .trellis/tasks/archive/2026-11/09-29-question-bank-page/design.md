# 题库区块：技术设计

## 核心设计决策

### 决策 1｜新增 `GET /questions/batches` 聚合接口，不做前端拼装

**选择**：后端按 `batch_id` group by 返回批次摘要，分页 `(items, total)`。

**为什么不能在前端分组**：`GET /questions` 的 `page_size` 上限是 100
（`app/api/v1/questions.py:303`）。用户题目数超过一页就要发多次请求、把**全部题目连同题干正文**
拉回本地才能算出批次与题量。批次摘要只需要计数与时间，把题干传一遍是纯浪费，
而且请求数随题目总量线性增长——正是 `spec/backend/database-guidelines.md` 点名禁止的形态。

**实现位置**：`app/api/v1/questions.py` + `QuestionRepository`（聚合查询）+ `QuestionService`（装配）。

**路由注册顺序是硬约束**：`"/questions/{id}"` 注册在 **`app/api/v1/questions.py:198`**，
早于 `"/questions"`（`:287`）。FastAPI 按注册顺序匹配，新路由若挂在 `:198` 之后，
`batches` 会被当成 `{id}` 捕获并按 UUID 解析失败（422）。
**新路由必须注册在 `:198` 之前。**

### 决策 2｜三次批量查询，禁止 N+1

```sql
-- ① 本页批次（聚合 + 排序 + 分页）
SELECT q.batch_id,
       count(*)                                        AS question_count,
       count(*) FILTER (WHERE q.status = 'available')   AS available_count,
       min(q.created_at)                               AS created_at
FROM questions q
WHERE q.user_id = :uid AND q.is_deleted = false
GROUP BY q.batch_id
ORDER BY min(q.created_at) DESC
LIMIT :limit OFFSET :offset;

-- ② 批次数（与 ① 同 WHERE，保证 total 是真实全量）
SELECT count(*) FROM (
  SELECT 1 FROM questions q WHERE q.user_id = :uid AND q.is_deleted = false GROUP BY q.batch_id
) t;

-- ③ 来源批量装配（只针对 ① 这一页的 batch_id）
SELECT DISTINCT q.batch_id, q.material_id, m.title, m.folder_id, f.name
FROM questions q
JOIN materials m ON m.id = q.material_id
LEFT JOIN material_folders f ON f.id = m.folder_id
WHERE q.user_id = :uid AND q.is_deleted = false AND q.batch_id IN :batch_ids;
```

`count(*) FILTER (WHERE ...)` 在 SQLite 与 PostgreSQL 上**不都可用**（SQLite 3.30+ 支持，
但项目测试库版本需实机确认）。**保守写法**：用
`sum(case when q.status = 'available' then 1 else 0 end)`，两库通用。
实现时二选一并核对 `tests/unit/models` 的门禁。

**「排除软删除题目」与「排除软删除资料」是两件事**：③ 用 `JOIN materials` 会丢掉资料已删但题目尚存的批次来源。
用 `LEFT JOIN` 并在装配层给「资料已删除」一个可读标签，与决策 4 的降级一致。

### 决策 3｜三态勾选用「整批 + 增删集」建模，而不是题目 ID 集合

**这是本设计最核心的一条。** 需求与验收之间有一个真实矛盾：

- AC-7（未展开的批次不得预取题目）要求渲染批次行时**不知道**该批次的题目 ID；
- 「全选」这个动作天然需要知道该批次有哪些题目。

若把选择状态建模成「已选题目 ID 的集合」，三态就只能等题目加载完才知道，AC-7 必然被违反。

**选择**：状态按批次分桶，只存「意图」，不存展开结果。

```ts
interface BatchSelectionState {
  /** 整批选中：展开后未单独取消的题目都算入 */
  whole: Set<string>
  /** 逐题勾选：按批次分桶 */
  picked: Map<string, Set<string>>
  /** 在整批选中之上逐题取消：按批次分桶 */
  unpicked: Map<string, Set<string>>
}
```

三态**无需知道任何题目 ID**即可判定：

| 状态 | 判据 |
| --- | --- |
| `all` | `whole.has(b)` 且 `unpicked.get(b)` 为空 |
| `none` | `!whole.has(b)` 且 `picked.get(b)` 为空 |
| `partial` | 其余 |

已选题数同样无需展开——批次摘要里的 `available_count` 就够：

```
selectedCount = Σ_{b ∈ whole} (available_count[b] − |unpicked[b]|) + Σ_b |picked[b]|
```

**代价**：`whole` 批次的题目 ID 要到**点击「立即开练」时**才解析（按 `batch_id` 拉一次
`GET /questions?batch_id=X&review_status=available`，翻页直到 `collected.length >= total`，
复用 `src/pages/review/index.vue:150-160` 既有的 `MAX_PAGES` 循环写法）。
这发生在用户已明确要开练之后，不是渲染路径，可接受。

### 决策 4｜承决策 3：**只有 `available` 的题目可选**

**选择**：`pending_review` 的题目在区块内**可见但不可勾选**，标「待审核」徽标。

**这条不是 UI 偏好，是为了把 PRD 的 F5 从「运行时检测」变成「结构上不可能」。**

`app/services/practice.py:441-443` 在显式题目路径上只保留 `status == available` 的题，
**被丢弃的题不报错、不入 details，请求照常成功**。如果允许勾选待审核题目，
「界面说 20 题、练习里 15 题」就是必然结果，而它**没有任何错误信号**可供归因。

只允许勾选 `available` 之后：

- 「已选 N 题」与进入练习的题数**恒等**，AC-9 由结构保证，不靠额外校验；
- 用户仍能看到待审核的题目确实存在（正面回答「题目在哪里」），并知道它为什么不能练。

**残留竞态**：从「点击开练」到「练习创建」之间题目可能被删除或转状态。
解析出的可用数若小于界面显示数，**必须告知并让用户确认**，不得静默按少的创建。

> **更正（2026-09-29，check 阶段实测）**：PRD F3 断言「显式 `question_ids` 路径不按
> `question_count` 截断」**是错的**。`app/services/practice.py` 的显式路径实际是
> `selected_questions = ordered_explicit[: options.question_count]`（RANDOM 模式先打乱再截断），
> 而 `PracticeCreateRequest.question_count` 默认 **10**。实测（12 题显式建练习，
> 不传 `question_count`）落库只有 **10 题**，且无任何错误信号。
> ⇒ 「已选题数 == 练习题数」**不是结构保证**：前端必须在 `POST /practices` 里显式传
> `question_count = 实际要练的题数`（`useQuestionBank.startPractice`）。
> 又因 `question_count` 是 `ge=1, le=50`，单次练习上限 50 题：超过时**先告知再按 50 题创建**，
> 不得静默截断。

### 决策 5｜状态放页面本地 composable，不进 Pinia store

**选择**：新增 `src/pages/review/composables/useQuestionBank.ts`，不新增 store。

**依据 `spec/frontend/state-management.md` 的判据**：提升到全局 store 的条件是「跨页面/跨步骤共享」。
批次列表、分页游标、展开集合、勾选集合全部只在题库区块内有意义，**没有任何第二个页面读它**。
R5 需要的只是**标签推导**，那是纯函数，不是状态。

**反例排除**：`materialStore` 已有 `questions` / `loadQuestions`，但它承载的是
「当前资料的题目」这一随 `currentMaterial` 走、随上下文重置的状态
（`spec/frontend/state-management.md::Server State` 的「重置语义」）。
题库是跨资料、跨批次的全局视图，**两套生命周期不同**，混进同一 store 会让其中一套的重置语义出错。
故新增独立 composable，并**保持 store 清单仍为 5 个**。

### 决策 6｜标签推导抽成共享纯函数，跨批次练习的标题显式构造

**标签推导**放 `src/utils/questionBatch.ts`（仓库主流做法：
`spec/frontend/state-management.md` 明示派生逻辑抽 `src/**/utils/*.ts` 纯函数）。
R5 的核对出题页**必须 import 同一个函数**，不得另写一套口径——两处口径漂移会产生
「核对页说的批次和题库页说的不是同一个」这类不可归因的缺陷。

推导规则（输入为批次摘要，**不依赖题目正文**）：

| 维度 | 规则 |
| --- | --- |
| 时间 | `created_at` 格式化为 `M月D日 HH:mm`；跨年补年份 |
| 来源 | 该批次 `sources` **只有一份资料** → 资料名；**多份资料同属一个课程** → 课程名；**多份资料跨课程** → 「N 份资料」；资料已删除 → 「来源已删除」 |
| 题量 | `available_count` 题（`pending_review_count > 0` 时补「· N 题待审核」） |

**多资料分支是必须的**：`generate_questions_for_folder`（`app/services/question.py:1198-1277`）
按 `(material_id, version_id)` 分组却只生成一个 `batch_id`，所以课程级出题产生的批次**天然跨资料**。
按资料名标注的实现在这条路径上会给出错误信息（PRD AC-4 专门盯这条）。

**练习标题**：`POST /practices` 的 `title` 是必填（`app/schemas/practice.py:52-57`，`min_length=1`），
且跨批次练习会带上 `scattered_questions[0].material_id` 这个只代表其中一份资料的归属
（`app/services/practice.py:590-593`，PRD F6）。因此标题必须由前端构造为可辨认的形态，
例如 `跨批次练习 · 3 个批次 24 题`，**不得留空或落成 UUID 式字符串**——它是「我的练习」
与诊断报告里唯一可读的标识。

## 前端契约

**新增纯函数模块 `src/utils/questionBatch.ts`**（无副作用、无网络、可单测）：

```ts
export interface BatchSource {
  materialId: string
  materialTitle: string | null
  folderId: string | null
  folderName: string | null
}

export interface QuestionBatchSummary {
  batchId: string | null            // null = 未分批的历史题目
  questionCount: number
  availableCount: number
  pendingReviewCount: number
  createdAt: string
  sources: BatchSource[]
}

/** 批次可读标签；题库区块与核对出题页共用，禁止第二份实现。 */
export function describeBatchLabel(batch: QuestionBatchSummary): string

export type BatchCheckState = 'all' | 'partial' | 'none'

/** 三态判定：只依赖 counts 与选择意图，不需要题目 ID 列表。 */
export function resolveBatchCheckState(
  batchId: string | null,
  selection: BatchSelectionState,
): BatchCheckState

/** 已选题数：只依赖 counts 与选择意图，与「实际进入练习的题数」恒等（决策 4）。 */
export function countSelectedQuestions(
  batches: QuestionBatchSummary[],
  selection: BatchSelectionState,
): number
```

`batchId: string | null` 是刻意保留的：`batch_id IS NULL` 的历史题目（PRD AC-5）
必须能作为一个分组存在，用 `null` 而不是伪造 ID。**因此所有以 batchId 为键的 Map/Set
都必须能装 `null`**——TS 的 `Set<string>` 装不了，实现时要么用哨兵常量要么让类型为 `string | null`。
这条是 AC-5 的实现前提。

**新增 composable `src/pages/review/composables/useQuestionBank.ts`**：持有
`batches` / `selection` / `expanded` / `isLoading` / `loadError` / 每批次已加载题目，
暴露 `loadBatches` / `toggleBatch` / `toggleQuestion` / `expandBatch` / `startPractice`。

**新增 API**：`src/api/index.ts` 增 `apiListQuestionBatches(params)`。
类型放置遵守 `spec/frontend/type-safety.md`：**view 类型**（`QuestionBatchSummary` 等）
进 `src/types/index.ts`，**`Wire*` 原始载荷类型留在 adapter 文件内**
（与既有 `adaptQuestion` 同址），归一化在适配器里完成，不在组件里断言 payload 字段。

> 本设计初稿曾写「`Wire*` 进 `types/index.ts`」，与上述 spec 相冲突，**已按 spec 更正**。
> 该 spec 的理由是 wire 形状描述「后端 JSON 的实际字段名与可空性」、view 类型描述
> 「页面消费的规范模型」，二者字段名有意不同，混址会让归一化边界消失。


**错误契约**：失败分类走 `src/utils/requestError.ts` 的 `RequestError` / `RequestErrorKind`
（`spec/frontend/state-management.md` 明示这是 store/composable 可 import 的叶子模块）。

## 兼容性与回滚

- **纯新增，无迁移、无数据变更**。回滚 = 撤掉新接口与新组件，既有页面不受影响。
- 新接口独立于 `GET /questions`，**不改既有响应形状**，故无契约破坏。
- 路由注册顺序（决策 1）是唯一会影响既有接口的改动点：若顺序放错，
  `/questions/batches` 会 422 而不是错误匹配到 `/questions/{id}`，
  **表现为新功能 404/422 而非既有功能损坏**，回滚边界清晰。
- 前端新增文件全部是新增，`pages/review/index.vue` 只在父任务挂载区块时改一行模板与一处 import。
