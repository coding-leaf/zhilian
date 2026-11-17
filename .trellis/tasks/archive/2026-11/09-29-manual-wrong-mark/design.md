# 手动标记错题：技术设计

## 核心设计决策

### 决策 1｜`POST /wrong-records`，入参只有 `question_id`

**选择**：在既有错题资源上补创建接口，body `{"question_id": "..."}`。

**为什么不收 `knowledge_point_id`**：知识点归属由题目的 `knowledge_point_id` 唯一决定。
让客户端传，就多了一个「客户端传错 → 错题归到别的考点 → 举一反三练错方向」的失效面，
而它没有任何收益。服务端解析，客户端只表达「哪道题」。

**路由无顺序陷阱**：`POST /wrong-records` 与既有的 `POST /wrong-records/{id}/master`、
`DELETE /wrong-records/{id}` 路径不同、方法也不同，**不存在** A 任务里
`/questions/{id}` 吃掉 `/questions/batches` 那类问题。

**返回形状复用 `WrongRecordItemResponse`**，使前端可以把结果直接 upsert 进列表，
不必为「标记成功」这条路径再拉一次列表。

### 决策 2｜迁移：`practice_id` / `attempt_item_id` 改可空，**不新增 `source` 列**

**选择**：两个字段改 `nullable=True`，用 `practice_id IS NULL` 表示「手工创建」。

**为什么不加 `source` 列**：`source` 与 `practice_id IS NULL` 表达的是**同一件事**。
两个字段表达同一件事，就一定会有漂移的一天（有人只更新其中一个）。
`practice_id IS NULL` 已经是手工记录的定义性特征——它没有练习归属，这就是全部含义。

**为什么不给手工记录造一个「手工练习」行**：那会让它出现在「我的练习」列表与诊断报告里，
污染用户对「我做过几次练习」的认知，且要在多处过滤它。代价远高于改两个约束。

**迁移写法**（依据 `spec/backend/database-guidelines.md`「Migrations」）：
SQLite 兼容必须用 `op.batch_alter_table("wrong_records")`；`downgrade()` 必须可执行
（非空回填用「删除 `practice_id IS NULL` 的行」或回落到一个明确的策略，二者选一并在迁移注释里写明）；
`tests/unit/models/test_migration_model_consistency.py` 是自动闸门。

**注意**：一致性闸门只比对**表名与列名集合**，**不比对可空性**——
所以「模型改了、迁移忘了」这件事它**拦不住**。必须靠
`tests/unit/models/` 里针对性的迁移单测（AC-3）覆盖 `upgrade → downgrade → upgrade` 对称。

### 决策 3｜⚠️ 修掉 `upsert_wrong_record` 的覆盖行为（PRD F3）

**选择**：把 `practice_id` / `attempt_item_id` 的赋值改为**仅在入参非 None 时覆盖**：

```python
# app/repositories/diagnosis.py:420-426 现状 —— 无条件覆盖
record.practice_id = practice_id
record.attempt_item_id = attempt_item_id

# 改为 —— None 不覆盖：手工路径没有归属，无权抹掉判题写下的归属
if practice_id is not None:
    record.practice_id = practice_id
if attempt_item_id is not None:
    record.attempt_item_id = attempt_item_id
```

**为什么用「非 None 不覆盖」而不是加一个 `preserve_scope: bool = False` 开关**：
开关依赖**每个未来调用方都记得传它**，而漏传的后果是**静默销毁判题来源**——
一个靠记忆维持的不变量，在「缺陷不可见」的场景里必然失守。
「非 None 才覆盖」把不变量写在方法自己身上，**无法被忘记**。

**为什么不改 `knowledge_point_id` 的赋值**：`knowledge_point_id` 属于题目，两条路径都传真实值；
题目被编辑后考点变化时，更新它是**正确的**。只有「练习归属」这两个字段是「一旦写下就不该被无资料的一方抹掉」。

**语义声明**：本方法的契约因此变成
「**错题记录的练习归属一旦写下，不会被后续无归属的 upsert 清除**」，
写进 docstring。**该行为变更由 PRD AC-4 的回归测试看守**：
按现状实现时那条测试必须失败。

**评估过的替代方案**：手工路径绕过 `upsert_wrong_record` 另写一个方法。
否决理由：那样两条写入路径的快照构造、`error_count` 累加、`is_mastered` 重置语义
都要维护两份，而其中任何一份漂移都会让「手工错题与判题错题表现不一致」——
正是父任务 XAC-2 要防的。

### 决策 4｜快照构造必须抽出共享函数（**代码复用硬要求**）

**现状**：快照在 `app/services/practice.py:567-586` **内联**构造，11 个键：

```python
snapshot = {
    "stem", "question_type", "options", "answer", "analysis", "explanation",
    "difficulty", "knowledge_point_id", "source_snippet_id", "grading_rubric",
}
```

**选择**：抽出 `build_question_snapshot(question) -> dict[str, Any]`，
`PracticeService.create_practice` 与手工标记路径**共用**。就近放在
`validate_question_snapshot` 同址（`app/models/practice.py`）——构造器与校验器是
「不变量 + 构造」成对关系，拆到两个模块正是两份形状漂移的开始。
若 `uv run lint-imports` 判定该模块不可被 services 依赖，则退到 `app/core/`，
**以 lint-imports 的结论为准**。

**为什么这是硬要求而不是风格偏好**：前端**完全**从 `question_snapshot` 渲染错题
（`src/api/adapters/wrong.ts:22-24` 的注释是硬约定：「禁止读不存在的 `question.stem`」）。
两份快照形状 = 手工错题与判题错题**在界面上长得不一样**，
而父任务 XAC-2 要求的正是「两条来源渲染一致」。**这是它唯一的实现保障。**

**校验不可省**：构造后必须调 `validate_question_snapshot`，不通过则抛错、
**不写库**。依据 `app/models/practice.py:118-168`：`stem` / `question_type` / `answer` 非空，
单选与多选还要求 `options` 为 ≥2 项、每项含 `key` 与 `content`。
一道 `answer` 为空的题目被标成错题、界面上渲染成空白，比拒绝标记糟得多。

### 决策 5｜`ErrorType` 增 `MANUAL` 成员，并在注释中声明它**不是归因**

**选择**：`app/models/practice.py:105-112` 增 `MANUAL = "manual"`。

**理由**：`error_type` 是 `nullable=False`，手工记录必须有一个值；
而 `spec/backend/database-guidelines.md` 明令「枚举以字面量持久化：状态值必须取自
`enum.StrEnum` 成员，不得硬编码字符串」。所以只能是新增成员。

**语义代价与缓解**：既有四个成员都是**错因归因**（FR-55 四类一票否决），
而 `MANUAL` 表达的是**记录来源**，两者不同维度。缓解手段是在枚举里写明：

```python
MANUAL = "manual"  # 手工标记来源标记，**不是错因归因**；未来做归因分布统计时必须排除
```

**已核查的两项安全性**（PRD F6）：前端从不渲染 `error_type`；`normalize_error_type`
对未识别值原样透传、不静默回退为全量。**新增取值在现有代码里零影响。**

### 决策 6｜取消标记复用既有 `DELETE`，并对有来源的记录改道

| 记录来源 | 判据 | 「取消标记」的行为 |
| --- | --- | --- |
| 手工 | `practice_id IS NULL` | 调既有 `DELETE /wrong-records/{id}` 移除 |
| 判题 | `practice_id` 非空 | **不删除**；引导到既有 `POST /wrong-records/{id}/master`（「已掌握」） |

**为什么不一律删除**：判题产生的错题记录是**真实作答历史**，
删掉它会让「已消灭错题」等既有统计失去依据。而「已掌握」正是为这个处境设计的语义
（`app/models/practice.py:864-868` 的 `is_mastered` / `mastered_at`）。

**前端要补的暴露**：`DELETE /wrong-records/{id}` 后端已存在，
但 `src/api/index.ts` **从未暴露它**（无对应函数），本任务补上。

### 决策 7｜入口是「切换」而不是「单向标记」，并在题库里回显状态

- 入口放在题库区块的题目行动作位（`09-29-question-bank-page` 预留），
  已标记的题目显示为已标记态，点击即取消（走决策 6 的分支）。
- **回显是必需的**：没有回显，用户无法区分「标记没生效」与「已经标记过了」，
  会重复点击——而重复点击走的是 upsert 累加，`error_count` 会虚高。
- 请求在途时禁用按钮（既有的 `isGenerating` / `isSubmitting` 式做法），
  避免双击造成「标记 + 取消」两次往返。

## 兼容性与回滚

- **唯一的破坏性改动是可空性迁移**：`wrong_records.practice_id` / `attempt_item_id`
  从 NOT NULL 放宽为 NULL。放宽**不会使任何既有数据失效**，既有行保持原值。
- **回滚**：`downgrade()` 需要把 NULL 收回非空。**必须显式决定策略并在迁移里写明**——
  手工错题（NULL）在回滚时无处安放，推荐直接删除这些行（它们的存在本身依赖新能力），
  并把这个选择写进迁移注释，而不是让 `downgrade` 在 NOT NULL 约束上直接失败。
- **`upsert_wrong_record` 的行为变更**（决策 3）影响判题路径——但该路径**总是传真实的
  `practice_id`/`attempt_item_id`**，所以对它是**行为不变的**。变更只对「传 None 的调用方」生效，
  而今天就只有新增的手工路径是这种调用方。AC-4 的回归测试同时看守这两侧。
- **`ErrorType` 新增成员**是纯增量：已有数据的取值不变，前端不消费该字段。
