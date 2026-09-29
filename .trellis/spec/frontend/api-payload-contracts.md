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

---

## Scenario: 手动标记错题（`POST /wrong-records` 及其取消分道）

### 1. Scope / Trigger

调用 `POST /wrong-records` 标记/取消错题时；或改动 `upsert_wrong_record` 的字段赋值时。

### 2. Signatures

```python
# backend/app/schemas/diagnosis.py::WrongRecordCreateRequest
question_id: uuid.UUID          # 仅此一个字段

# POST   /wrong-records                -> 201 WrongRecordItemResponse
# POST   /wrong-records/{id}/master    -> 切换「已掌握」（既有）
# DELETE /wrong-records/{id}           -> 彻底移除（既有）
```

### 3. Contracts

**契约 A：创建请求只收 `question_id`。** 知识点归属由题目自身唯一决定，服务端从
`Question.knowledge_point_id` 解析。让客户端传 `knowledge_point_id` 只会多一个
「归错考点 → 举一反三练错方向」的失效面，没有收益。

**契约 B：「无练习归属」是手工记录的定义性特征。** `practice_id IS NULL` 即手工创建。
**不另设 `source` 列** —— 两个字段表达同一件事必然漂移。

**契约 C（后端不变量）：错题记录的练习归属一旦写下，不会被后续无归属的 upsert 清除。**

```python
# backend/app/repositories/diagnosis.py::upsert_wrong_record 更新分支
if practice_id is not None:            # 手工路径传 None，无权抹掉判题写下的真实来源
    record.practice_id = practice_id
if attempt_item_id is not None:
    record.attempt_item_id = attempt_item_id
```

用「非 None 才覆盖」而**不是**加一个 `preserve_scope: bool = False` 开关：
开关依赖每个未来调用方都记得传它，漏传的后果是**静默销毁判题来源**；
一个靠记忆维持的不变量，在「缺陷不可见」的场景里必然失守。

**契约 D：取消标记按来源分道，绝不删除判题记录。**

| 记录来源 | 判据 | 行为 |
| --- | --- | --- |
| 手工 | `practice_id == null` | 调 `DELETE /wrong-records/{id}` 移除 |
| 判题 | `practice_id` 非空 | **不删除**；引导到 `POST /wrong-records/{id}/master`（已掌握） |

判题记录是真实作答历史，删掉它会让「已消灭错题」等既有统计失去依据。

**契约 E：`error_type = "manual"` 是来源标记，不是错因归因。**
既有四个成员（`conceptual` / `incomplete_expression` / `question_misreading` / `unanswered`）
是 FR-55 的四因归因；`manual` 表达的是记录来源，两者不同维度。
**未来做归因分布统计时必须排除它。**

### 4. Validation & Error Matrix

| 条件 | 结果 |
| --- | --- |
| 题目不存在 / 属他人 / 已软删除 | not found（与既有 not-found 同语义），**不写库** |
| 快照校验不通过（`stem`/`question_type`/`answer` 为空，或选择题 `options` < 2） | 报错，**不写库** |
| 对已有错题记录的题目重复标记 | 幂等更新：仍只有一条（`uq_wrong_records_user_question`），`error_count` 累加，`is_mastered` 重置 |
| 同一题既是判题错题又被手工标记 | 允许；**保留**判题归属，累加计数 |

### 5. Good/Base/Bad Cases

- **Good**：服务端用共享的 `build_question_snapshot` 构造快照 → `validate_question_snapshot`
  → 不通过就抛错不落库 → 再 `upsert_wrong_record(practice_id=None, attempt_item_id=None,
  error_type=ErrorType.MANUAL.value)`。
- **Base**：前端「已标记」状态按 `question_id` 反查错题列表回显；在途禁用按钮。
- **Bad**：手工路径另写一份快照构造。前端**完全**从 `question_snapshot` 渲染错题
  （见 `network-contract`/适配器约定：禁止读不存在的 `question.stem`），
  两份形状 = 手工错题与判题错题在界面上长得不一样。

### 6. Tests Required

- 重复标记 → 仍一条 + `error_count` 累加（幂等）。
- **判题归属不被抹掉**：先由判题路径写入带 `practice_id` 的记录，再手工标记，
  断言 `practice_id` / `attempt_item_id` **仍为原值**。按旧的覆盖行为实现时该用例必须失败。
- 快照不合法 → 报错且**库中无新增**。
- 越权/软删除题目 → not found。
- 手工错题进入再生题范围：断言「按 `is_mastered=False` 且 `knowledge_point_id` 非空收集出的
  考点集合」包含该题考点。**不要**据此声称该考点真的被练到（见下）。
- 取消分道：手工记录走 DELETE 且不碰 master 接口；判题记录不删、改走 master。

### 7. Wrong vs Correct

#### Wrong —— 无条件覆盖归属，静默销毁判题来源

```python
record.practice_id = practice_id          # 手工路径传 None -> 判题归属被抹成 NULL
record.attempt_item_id = attempt_item_id # 无报错、无信号，数据已损坏
```

#### Correct —— 无归属的一方无权清除已写下的归属

```python
if practice_id is not None:
    record.practice_id = practice_id
if attempt_item_id is not None:
    record.attempt_item_id = attempt_item_id
```

### 已知边界（不要越过）

「举一反三」当前**不回传 `question_count`**，而后端显式题目路径按它切片（默认 10）。
所以「手工错题的知识点进入了再生题范围」**不等于**「该考点被练到了」：
考点一旦排在第 11 位之后，对应题目不会进练习，而覆盖率仍按全部生成题目声明。
该缺陷归 `09-29-question-bank-tab`（R6 / AC-9），修好前不要用它推导「已覆盖」。
