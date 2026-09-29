# 手动标记错题：把已有题目记入错题本

> **本任务是 `09-29-question-bank-tab` 的子任务**，入口挂在 `09-29-question-bank-page`
> 交付的题库区块的题目行上。**排期上必须在它之后**（后端部分可先行）。

## Goal

让用户能把**题库里已有的题目**手动标记为错题——不需要先在 App 里做过这道题。

并让这些手工错题**自动进入既有的「举一反三」再生题闭环**，使「根据错题再次生题」覆盖
用户在纸上、别处做错的题，而不只是 App 里判过分的题。

**用户价值**：用户原话「最好还能记录手动错题，根据错题再次生题」。当前错题本**只能**由判题写入，
所以它在用户没在 App 里做错过题时是空的——而用户显然有 App 之外做错的题。

## 需求源与已确认决策

- 用户口述 3：「最好还能记录手动错题，根据错题再次生题」
- 已确认决策：形态是**标记已有题目**（轻），**不是**手打外部题目（题干/答案录入表单）。
  这决定了 `question_id` 一定存在，且**不需要**任何录入界面。

## 已确认事实（含证据锚点）

### F1｜错题表有三列非空约束，手工错题没有对应的现实

`app/models/practice.py:810-878`：`knowledge_point_id`、`practice_id`、`attempt_item_id`
**都是 `nullable=False`**，且都有指向各自表的外键。`question_id` 已经可空
（`nullable=True` + `ondelete="SET NULL"`）。

手工标记的错题**不是任何一次练习的产物**，所以 `practice_id` / `attempt_item_id` 在现实中不存在。
`knowledge_point_id` 则可以从题目取到（非空，`app/models/question.py` 的 `knowledge_point_id`）。

### F2｜`(user_id, question_id)` 有联合唯一键

`app/models/practice.py:907-908`：`UniqueConstraint("user_id", "question_id", name="uq_wrong_records_user_question")`。
所以「标记一道已经有错题记录的题」不是插入而是**更新**，
`DiagnosisRepository.upsert_wrong_record`（`app/repositories/diagnosis.py:370-432`）已实现该语义。

### F3｜⚠️ `upsert_wrong_record` 的更新分支会**覆盖** `practice_id`/`attempt_item_id`

`app/repositories/diagnosis.py:420-426`：

```python
record.error_count += 1
record.is_mastered = False
record.mastered_at = None
record.knowledge_point_id = knowledge_point_id
record.practice_id = practice_id          # ← 无条件覆盖
record.attempt_item_id = attempt_item_id  # ← 无条件覆盖
```

**这是本任务最容易造成数据损坏的一处。** 一道题若已经由判题写入过错题记录（带真实
`practice_id`/`attempt_item_id`），用户再从题库手工标记一次，这次调用会把它俩**抹成 NULL**——
判题来源被静默破坏，且没有任何错误信号。

**必须处理**：手工路径不得覆盖已有的非空归属。见 design.md 决策 3。

### F4｜前端完全靠 `question_snapshot` 渲染错题

`src/api/adapters/wrong.ts:22-24` 的注释是硬约定：
「错题题干只来自后端下发的 question_snapshot，**禁止读不存在的 `question.stem`**」。
`WrongRecordCard.vue` 的所有字段都取自快照。

**推论（好消息）**：只要服务端为手工错题构造出**合法快照**，它在错题本里就与判题错题
**渲染完全一致**，前端一行都不用改。父任务的 XAC-2 由此天然成立。

快照的合法性门槛由 `app/models/practice.py:118-168` 的 `validate_question_snapshot` 定义：
`stem` 非空、`question_type` 非空、`answer` 非空；单选/多选还要求 `options` 是
**≥2 项且每项含 `key` 与 `content`** 的列表。

### F5｜既有错题路由的完整形状

`app/api/v1/diagnosis.py`：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/wrong-records` | 列表（`:265-266`） |
| `POST` | `/wrong-records/{id}/master` | 切换已掌握（`:369-370`） |
| `DELETE` | `/wrong-records/{id}` | 彻底移除（`:413-414`，服务层 `remove_wrong_record`） |

**没有创建接口**——这是本任务要补的唯一缺口。
`DELETE` 已存在但**前端从未暴露**（`src/api/index.ts` 无对应函数），取消标记时要补。

### F6｜`ErrorType` 的四个成员全部是「错因归因」

`app/models/practice.py:105-112`：`CONCEPTUAL` / `INCOMPLETE_EXPRESSION` /
`QUESTION_MISREADING` / `UNANSWERED`，注释原文「四类一票否决归因（需求 FR-55）」。

手工标记**没有错因**——用户只是知道「这题我不会」。所以手工记录需要一个不属于归因体系的值，
而 `error_type` 是 `nullable=False`（`app/models/practice.py:853-856`）。

**已核查的两项安全性**：
- 前端**从不渲染 `error_type`**（全仓 grep 只命中 `types/index.ts:416` 与
  `adapters/wrong.ts:13` 两处 `error_type?: string` 类型声明），新增取值零 UI 影响。
- `normalize_error_type`（`app/services/diagnosis.py:150-174`）对**未识别值原样透传**
  （设计意图写明「杜绝静默回退为全量」），所以新增取值不会被过滤查询静默丢掉。

### F7｜「举一反三」会自动覆盖手工错题，**无需改代码**

`practiceStore.regenerateFromWrongPoints`（`src/stores/practice.ts:200-208`）接收的是
**知识点 ID 列表**，而不是错题记录 ID。手工错题的 `knowledge_point_id` 取自题目、是非空的真实值，
所以它会**自动进入**既有的再生题范围。

**这条要验证而不是假设**（见 AC-6）：它是「根据错题再次生题」对本需求成立的全部理由。

### F8｜⚠️ 但「举一反三」当前会**静默截断**，使 F7 的覆盖声明不可信

在 `09-29-question-bank-page` 的 check 阶段查实的一条既有缺陷，**直接卡住本任务的 AC-6**：

`src/stores/practice.ts:231-239` 里：

```ts
const coverage = computeKnowledgeCoverage(generated, knowledgePointIds)   // ← 按「全部生成题目」算
const session = await apiCreatePractice({
  title: '错题巩固练习',
  question_ids: generated.map((question) => question.id),                 // ← 没传 question_count
  source_type: 'wrong_record',
})
```

而后端显式题目路径的语义是**「候选题目 + 目标题数」而不是「就练这些」**：
`app/services/practice.py:473` 会执行 `ordered_explicit[: options.question_count]`，
而 `question_count` 默认 **10**（`app/schemas/practice.py:70-75`，`ge=1, le=50`）。

**后果**：用户有 >10 个错题知识点时，生成 20 道题覆盖 20 个考点，练习里只装前 10 道——
而 `coverage` 是按全部 20 道算的，于是界面会**声称某些考点已覆盖，而对应题目根本没进练习**。
`generated` 与「实际进入练习的题目」是两个不同的集合，覆盖率却只按前者声明。

**归属**：这是 `09-29-question-bank-tab`（C，持有错题区块与举一反三）范围内的既有缺陷，
**不在本任务实现**。但它决定了本任务 AC-6 的验证方式（见下）。

**对本任务的约束**：

- AC-6 只验证 **F7 的机制**——手工错题的知识点出现在再生题的 `knowledge_point_ids` 里。
  这是本任务能独立验证的部分。
- **不得**用「举一反三跑通了」当作「手工错题被覆盖到了」的证据——
  在当前截断缺陷下，这两件事不是一回事。
- F8 修复后（由 C 负责），AC-6 应能升级为端到端断言。收口时核对 C 的状态并在此登记。

## Requirements

### R1 — 创建接口

- 新增错题创建接口，入参为 `question_id`（**不含** `knowledge_point_id`：由服务端从题目解析，
  避免客户端指定错误归属）。
- 服务端必须：解析题目的 `knowledge_point_id`、校验题目属于当前用户且未被软删除、
  构造并**校验**题目快照（F4）。
- 快照校验不通过时必须**失败并说明原因**，不得写入一条渲染不出来的错题。

### R2 — 放宽非空约束（迁移）

- `practice_id` / `attempt_item_id` 改为可空，使「手工错题没有练习归属」这一现实能被表达。
- 迁移必须对称（`upgrade` / `downgrade` 都可执行），SQLite 下用 `op.batch_alter_table(...)`。
- **`practice_id IS NULL` 即「手工创建」**，不另加 `source` 列——两个字段表达同一件事会漂移。

### R3 — 不得覆盖已有的判题归属（F3）

- 手工标记一道已有判题错题记录的题时，**必须保留**原有的 `practice_id` / `attempt_item_id`。
- 语义上仍应视为「又一次答错」：`error_count` 累加、`is_mastered` 重置为未掌握。

### R4 — 取消标记

- 手工记录（`practice_id IS NULL`）可被**取消**，走既有 `DELETE /wrong-records/{id}`，
  并把它暴露到前端。
- 有判题来源的记录**不得**用删除来「取消标记」——那会销毁真实作答历史。
  此时界面应引导到既有的「已掌握」动作。

### R5 — 入口与状态回显

- 入口在题库区块的题目行动作位（由 `09-29-question-bank-page` 预留）。
- 已标记的题目在题库里**必须能看出已标记**（并可直接取消）。否则用户会重复标记、或以为没生效。
- 标记/取消失败必须可见反馈与重试。

### R6 — 手工错题进入举一反三（验证，非实现）

- 手工错题必须能被「举一反三」覆盖（F7）。
- **若实测发现不能覆盖，那是本任务必须修的缺陷**，不是可以记录的已知限制——
  用户要的是「根据错题再次生题」，覆盖不到就等于这个需求没做。

## Out of Scope

- **不做手打外部题目**（题干/答案/选项录入表单）：用户已明确选「标记已有题目」。
  它需要放宽更多约束并新增录入界面，是另一个量级的工作。
- **不改判题链路**：手工标记不参与任何判分。
- **不做错题的批量标记/批量取消**：MVP 单题操作；真需要再说。
- **不改「已掌握」的语义**（`POST /wrong-records/{id}/master`）：它已存在且可用。
- **不新增学习指标**：手工错题计入既有错题数与错题列表，不引入新的统计口径。

## Acceptance Criteria

- [ ] **AC-1** 创建接口存在；入参只有 `question_id`；对已有错题记录的题目重复调用是**幂等更新**
      （累加 `error_count`、重置 `is_mastered`），不产生第二条记录（F2 的唯一键）。
- [ ] **AC-2** 服务端构造的快照通过 `validate_question_snapshot`；快照不合法时接口返回明确错误，
      **且数据库里没有新增记录**。
- [ ] **AC-3** 迁移使 `practice_id` / `attempt_item_id` 可空；`upgrade → downgrade → upgrade` 对称
      （`tests/unit/models/` 的迁移一致性闸门通过）。
- [ ] **AC-4** **F3 回归测试**：先由判题路径写入一条带 `practice_id` 的错题记录，
      再走手工标记；**断言 `practice_id` / `attempt_item_id` 未被置空**。
      该测试在按 `:420-426` 的现有覆盖行为实现时必须失败。
- [ ] **AC-5** 手工错题在错题本里渲染与判题错题一致（题干、题型、选项、答案、解析齐全，
      `WrongRecordCard` 无需改动）。
- [ ] **AC-6** **举一反三覆盖手工错题**：手工作出一条错题后，走一次「举一反三」，
      断言生成请求的 `knowledge_point_ids` **包含**该题的知识点。
      **注意边界（见 F8）**：本条只验证「手工错题进入了再生题范围」这一机制；
      在当前 `question_count` 静默截断缺陷下，它**不能**推出「该考点真的被练到了」。
      不要用「举一反三跑通了」替代本条断言。
- [ ] **AC-7** 取消标记：手工记录可取消且记录被移除；有判题来源的记录取消入口被引导到「已掌握」
      而非删除。
- [ ] **AC-8** 入口可用且已标记状态可回显；标记/取消失败有可见反馈与重试。
- [ ] **AC-9** `task verify` 全绿；`mypy` strict 下所有原先假定 `practice_id`/`attempt_item_id`
      非空的站点都已正确处理（**这是发现隐藏假设的主要手段，不是需要绕过的障碍**）。
- [ ] **AC-10** 既有错题相关用例零回归。

## Notes

- **本任务的真实风险不是「加一个接口」，而是 F3 和 AC-9 这两条。**
  F3 是一个会**静默**破坏判题来源的覆盖行为；AC-9 之所以写进验收，
  是因为把两个字段改可空之后，`mypy` strict 会把所有「假定它非空」的地方逼出来——
  那些地方就是潜在的空指针，让类型检查器把它们找完，比人工审查可靠。
- **成本判断**：一次迁移 + 一个接口 + 一个动作按钮 + 前端暴露两个既有接口。
  **它比看起来轻，但比另外两个任务重**——因为它是唯一要动数据库的那个。
