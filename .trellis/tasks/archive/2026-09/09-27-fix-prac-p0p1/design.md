# 修复设计：PRAC 切片 P0+P1

## 1. 边界与原则

- 本任务为**前端适配与健壮性修复**，不改后端对外契约（后端响应模型 `items[].question_snapshot` 为契约真名）。
- 契约权威：`.trellis/spec/backend/quality-guidelines.md` 场景「Backend↔Frontend Response Field-Name Contract Pinning」。
- 适配集中**一处**，所有 PRAC 消费者复用，禁止各组件各写一套映射。

## 2. 真实契约（已核实）

后端 `PracticeDetailResponse` / `PracticeCreateResponse`：
```
{ practice_id, id, title, material_id, mode, status, total_count, question_count,
  completed_count, total_score, max_score, source_type, source_report_id,
  created_at, submitted_at, completed_at,
  items: [ PracticeItemDetailResponse ] }        # 注意：不是 questions

PracticeItemDetailResponse = {
  attempt_item_id, id, question_id, order_index (>=1), status,
  user_answer, time_spent_seconds, duration_seconds, is_answered,
  score, max_score,
  question_snapshot: { stem, question_type, options:[{key, content}],
                       answer, explanation, analysis, source_snippet_id,
                       source_snippet_ids, difficulty, grading_rubric } }
```

前端消费期望（`QuestionRenderer.vue:93-94,124-125`）：
```
question = { id, question_type, stem, options?: [{ key, text }], order_index, ... }
```

**错位点**：`items`→`questions`（PRAC-001）、`content`→`text`（PRAC-002）。

## 3. 方案设计

### 3.1 PRAC-001 + PRAC-002：响应适配层（新增）

新增 `miniprogram/src/api/adapters/practice.ts`：

```ts
// 契约权威：后端 items[].question_snapshot（见 backend/app/schemas/practice.py:143-179,84-125）
export function adaptPracticeItem(item: RawPracticeItem): QuestionItem
export function adaptPracticeSession(raw: RawPracticeSession, fallback?: Partial<PracticeSession>): PracticeSession
```

映射表：

| 前端字段 | 来源 | 规则 |
|---|---|---|
| `id` | `item.question_id ?? item.attempt_item_id` | `question_id` 为空时回退 `attempt_item_id`（保证 `v-for :key` 唯一） |
| `question_type` | `snapshot.question_type` | 原样 |
| `stem` | `snapshot.stem` | 原样 |
| `options` | `snapshot.options` | 逐项 `{ key, text: o.content }`；`content` 缺失回退 `o.text ?? ''` |
| `answer`/`analysis`/`difficulty`/`grading_rubric`/`source_snippet_id` | `snapshot.*` | 原样透传，缺失时给安全默认 |
| `order_index` | `item.order_index` | 原样 |
| 顶层 `questions` | `raw.items` 映射结果 | 按 `order_index` 升序 |
| 兼容 | 若 `raw.items` 不存在但 `raw.questions` 存在 | 直接使用 `raw.questions`（仅兼容旧 mock，不作为真实路径） |

**集成点**（覆盖全部消费者，集中适配）：
- `src/api/practice.ts`：`createPractice` / `fetchPracticeSession` 返回值经 `adaptPracticeSession` 归一化 → 类型上的 `PracticeSession.questions` 成为可靠契约。
- `ContinuePracticeBar.vue:136`（消费 `createPractice`）、`usePracticeSession.ts:54`（消费 `fetchPracticeSession`）因此自动获得 `questions`。
- 同步放宽 `types/practice.ts`：`PracticeSession` 增加可选 `items?: RawPracticeItem[]`（仅作原始透传，前端消费统一走 `questions`）。

**测试夹具改造**（关键，消除双侧假绿）：
- `tests/unit/practice/practiceSession.spec.ts`、`tests/unit/api/practice.spec.ts` 的 mock 夹具改为真实后端结构（`items[].question_snapshot`），断言适配后 `questions` 非空且 `options[0].text` 来自 `content`。

### 3.2 PRAC-003：交卷幂等键持久化复用

- 新增 `src/subpackages/practice/utils/submitKey.ts`（或并入 `utils/draft.ts`）：
  - `getOrCreateSubmitKey(practiceId): string` —— 从 Storage 读取 `practice_submit_keys[practiceId]`，无则 `generateIdempotencyKey()` 生成并写入。
  - `clearSubmitKey(practiceId): void` —— 交卷确认成功/明确终态后清除该 key。
- 改造 `pages/session/index.vue:197`：交卷时使用 `getOrCreateSubmitKey(practiceId)` 而非每次新建。
- 生命周期：
  - 首次交卷 → 生成并持久化。
  - 超时/网络错误重试 → 复用同一 key（后端 `services/practice.py:650-676` 命中回放）。
  - 收到成功或明确业务终态（已完成 400 等不可重试态）→ `clearSubmitKey`。
- 存储 key 常量与 `MAX_STORAGE` 无关（单 key 极小），失败不影响主流程（写入失败时退化为内存复用当前会话，需 try/catch）。

### 3.3 PRAC-004：草稿写入降级

- `utils/draft.ts:181-189` 的 `saveDraftToStorage`（或等价函数）外层包 `try/catch`：
  - 捕获 `storage.setItem` 抛出的 `AppError(10001)`（超 `MAX_STORAGE_BYTES`）。
  - 降级策略：**不 rethrow**；记录警告（`console.warn` 或项目既有日志，禁止敏感数据）；确保调用方继续执行远端同步调度。
- `usePracticeSession.ts:80-92`：确保 `saveDraftToStorage` 失败**不阻断**其后的 `setTimeout` 远端同步注册；store 内状态保持不变。
- （可选加强）对超大作答，仅持久化核心字段或改用逐题 key —— 本任务至少保证"失败可降级、不丢当前状态、远端仍同步"。

## 4. 影响面与兼容

| 文件 | 变更类型 |
|---|---|
| `src/api/adapters/practice.ts` | 新增 |
| `src/api/practice.ts` | 接入适配 |
| `src/types/practice.ts` | 增加可选 `items`；保持 `questions` 为消费契约 |
| `src/subpackages/practice/utils/submitKey.ts` | 新增 |
| `src/subpackages/practice/pages/session/index.vue` | 交卷用持久化 key |
| `src/subpackages/practice/utils/draft.ts` | 写入降级 |
| `src/subpackages/practice/composables/usePracticeSession.ts` | 保证同步调度不被破坏 |
| `tests/unit/practice/*.spec.ts`、`tests/unit/api/practice.spec.ts` | 夹具改真实契约 + 回归断言 |

- 后端零改动 → 后端门禁应保持绿（验收复核）。
- 兼容：适配层对缺失字段给安全默认，避免运行时 `undefined`。

## 5. 验证 & 回归

新增回归测试（先红后绿）：
1. `adaptPracticeSession`：输入真实 `items[].question_snapshot` → `questions` 长度正确、`question_type`/`stem` 正确、`options[0].text === 'A的正文'`（来自 `content`）。
2. `usePracticeSession.loadPractice`：mock 真实后端响应 → store.questions 非空。
3. `getOrCreateSubmitKey`：同一 practiceId 两次调用返回相同 key；`clearSubmitKey` 后重新生成。
4. 交卷重试：连续两次 `submitPractice` 携带同一 `Idempotency-Key`。
5. 草稿降级：mock `storage.setItem` 抛 `AppError(10001)` → 不抛出、store 状态保留、远端同步仍被调度（spy 断言）。

门禁：前端 `pnpm run lint` + `type-check` + `test:unit`；后端五项确认不退化。

## 6. 回滚点

- 适配层为新增独立模块，回滚即移除接入点；PRAC-003/004 为局部改动，可单独回退。
- 若发现后端实际另有字段别名，先回到本设计第 2 节核对，不擅改前端类型规避。
