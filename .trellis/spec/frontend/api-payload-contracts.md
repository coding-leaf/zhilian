# API Payload Contracts（写入类接口的请求体语义）

> **事实源**：`backend/app/schemas/practice.py`、`backend/app/services/practice.py`、`backend/app/api/v1/practices.py`、`miniprogram/src/api/index.ts`、`miniprogram/src/stores/practice.ts`、`miniprogram/src/pages/review/composables/useQuestionBank.ts`
> **最后核对**：2026-09-29
> **核对方式**：逐条读 `services/practice.py` 的 `create_practice` 全路径（**不是读到一半**，见 §7）+ 实测 12 题显式建练习

---

## 1. Scope / Trigger

凡涉及以下任一项，必须先读本文件再动手：

- 调用 `POST /practices`（`apiCreatePractice`），**尤其是传 `question_ids` 的调用方**
- 新增任何"我给一组 id，你按这组建练习"的接口调用
- 改动 `create_practice` 的组卷语义

**背景**：本文件存在的原因是 2026-09-29 的一个真实缺陷。前端勾了 12 道题、界面显示「已选 12 题」，
练习建出来只有 10 题，**没有任何错误信号**。根因是 `question_ids` 的语义被误读为
「就练这些」，而它实际是「候选题目 + 目标题数」。

**为什么单列成文件而不是塞进 `network-contract.md`**：那份管的是网络层（超时、错误分类），
本文件管的是**请求体字段的语义**。两者失败方式不同：网络层失败会报错，请求体语义误读**不会报错**。
后者才是难查的那类。

---

## 2. Signatures

```python
# backend/app/schemas/practice.py::PracticeCreateRequest
title: str                                  # 必填，1..128
material_id: uuid.UUID | None = None        # 缺省时由所选题目资料自动解析
folder_id: uuid.UUID | None = None
knowledge_point_ids: list[uuid.UUID] = []
question_count: int = 10                    # ge=1, le=50  ← 默认值就是陷阱
question_types: list[str] | None = None
question_ids: list[uuid.UUID] | None = None # 显式题目：语义是「候选」，见 §3
mode: str = ...
source_type: str | None = None
```

```typescript
// miniprogram/src/types/index.ts
export interface CreatePracticeParams {
  title?: string          // 注意：后端必填，前端类型却是可选
  material_id?: string; folder_id?: string
  knowledge_point_ids?: string[]; question_ids?: string[]
  question_count?: number // ← 传 question_ids 时必须一起传
  // ...
}
```

---

## 3. Contracts

### 契约 A：`question_ids` 是「候选 + 目标题数」，不是「就练这些」

显式题目路径的分支在 `backend/app/services/practice.py` 的 `create_practice` 里：

```python
if options.question_ids:
    available_questions = [q for q in explicit_questions
                           if q.status == QuestionStatus.AVAILABLE.value]
    ordered_explicit = [q_map[qid] for qid in options.question_ids if qid in q_map]
    if options.mode == PracticeAssemblyMode.RANDOM:
        shuffled = list(ordered_explicit)
        random.shuffle(shuffled)
        selected_questions = shuffled[: options.question_count]     # ← 截断
    else:
        selected_questions = ordered_explicit[: options.question_count]  # ← 截断
```

⇒ **实际进练习的题数 = `min(可用候选数, question_count)`**。

**加粗的理由**：这条不满足时**不报错、不入 details、请求照常 201**。
没有任何信号告诉你少了题。

### 契约 B：`status != available` 的题目被静默丢弃

同一段里的 `available_questions` 过滤（`services/practice.py` 显式路径开头）会丢掉
`pending_review` 的题目，同样**不报错**。所以「候选数」本身也可能小于传入的 id 数。

### 契约 C：`title` 后端必填，前端类型标成可选

`PracticeCreateRequest.title` 是 `min_length=1` 的必填字段，而 `CreatePracticeParams.title`
是 `title?: string`。**前端类型宽松不代表后端可省**；不传会 422。

### 契约 D：`material_id` / `folder_id` 都缺省时会被自动补成「第一道题的资料」

```python
resolved_material_id = options.material_id
if resolved_material_id is None and options.folder_id is None:
    resolved_material_id = scattered_questions[0].material_id
```

跨资料组卷（例如跨批次练习）因此会带上一个**只代表其中一份资料**的归属标签。
显式题目路径**不校验**题目是否属于该资料，所以不会失败——但那条练习在列表里的观感取决于 `title`，
调用方应给出可辨认的标题。

---

## 4. Validation & Error Matrix

| 条件 | 结果 |
| --- | --- |
| `question_ids` 有值，其中**全部**不可用/越权 | `PracticeEmptyQuestionsError`（400 / 40012），details 带 `requested_ids` |
| `question_ids` 有值，其中**部分**不可用 | **静默丢弃**，按可用的那些建练习，201 |
| `question_ids` 数 > `question_count` | **静默截断**到 `question_count`，201 |
| `question_count` > 50 | Pydantic 422（`le=50`） |
| `question_count` = 0 | Pydantic 422（`ge=1`） |
| `title` 缺失/空 | Pydantic 422 |
| 相同 `Idempotency-Key` 并发 | `IdempotencyConflictError`（409 / 30017）。**该路径没有幂等键就不会去重** |

---

## 5. Good/Base/Bad Cases

- **Good**：传 `question_ids` 时**同时**传 `question_count = question_ids.length`，
  且建练习前把「服务端此刻可用的题目集合」与「界面显示的题数」比对，不一致就**先告知再创建**。
  `useQuestionBank.startPractice` 即此写法。
- **Base**：只按考点抽题（不传 `question_ids`），此时 `question_count` 是**抽题目标数**，
  语义与字段名一致，按需传即可。
- **Bad**：`apiCreatePractice({ title, question_ids })` —— 依赖默认 `question_count=10`。
  12 题变 10 题，无任何信号。**这正是 2026-09-29 缺陷的形态**，
  且当时 `src/stores/practice.ts::regenerateFromWrongPoints` 也是这么写的（同一根因的第二处）。

---

## 6. Tests Required

断言点必须落在**实际题数**上，不能只断言「创建成功」：

- 传 N 个可用 id（N > 10）且**显式**传 `question_count = N` → 断言练习实际含 **N** 题。
- 传 N 个可用 id 且**不传** `question_count` → 断言实际含 **10** 题
  （把默认值陷阱钉成测试，而不是留给下一个人踩）。
- 传的 id 里混入一个 `pending_review` → 断言它**不在**练习里，且**调用方感知到了差异**。
- 覆盖率的断言必须与**实际进入练习的题目集合**对齐，不能用「生成出来的题目集合」代替。
  否则会出现「声明覆盖了某考点，而那道题根本没进练习」。

---

## 7. Wrong vs Correct

#### Wrong —— 把 `question_ids` 当「就练这些」，依赖默认 `question_count`

```typescript
// 界面：已选 12 题
// 结果：练习 10 题，无报错
const session = await apiCreatePractice({
  title: '跨批次练习',
  question_ids: questionIds,
})
```

#### Correct —— 显式传目标题数，并在创建前对齐两侧

```typescript
const planned = questionIds.length          // 与界面显示同源
const session = await apiCreatePractice({
  title: `跨批次练习 · ${batchCount} 个批次 ${planned} 题`,
  question_ids: questionIds,
  question_count: planned,                  // ← 不传就等于放弃这个不变量
})
// 且：创建前比对「服务端可用集合」与 planned，任一方向不一致都先告知
```

---

## Common Mistakes

- **只读函数的一半就下结论**。本条契约最初被判为「不截断」，成因是读到
  `ordered_explicit = [...]` 就停了，而截断恰好在**下一行**（`[: options.question_count]`）。
  这个误判被写进了 PRD 的「已确认事实」并据此设计了实现。
  **判别方法**：断言一个函数的契约前，把该分支读到 `else:` 或函数结尾，
  不要读到「答案看起来已经清楚」为止。
- **以为"没有报错"等于"没有发生"**：本节两条契约（截断、状态过滤）都是**静默**的。
- **前端类型可选就以为后端可省**：`title?` 在后端是必填（契约 C）。
- **只看一个调用点**：同一根因可能存在于多个调用方。修 `question_count` 时要
  `git grep -n "question_ids"` 把全部调用方看一遍。
