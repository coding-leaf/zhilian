# 手动标记错题：执行计划

## 前置检查（开工前必做）

- [ ] `python ./.trellis/scripts/task.py current` 确认活动任务是本任务。
- [ ] 确认 `09-29-question-bank-page` 已交付题目行动作位（**第 8 步依赖它**）。
      若它尚未完成，后端与前端契约层（第 1–7 步）**可以先做并可独立验证**。
- [ ] 读 `spec/backend/database-guidelines.md`（迁移、可空性、CAS、枚举持久化）与
      `spec/backend/quality-guidelines.md`（禁止模式）。
- [ ] `uv run alembic heads` 与 `uv run alembic current` 记录开工前的迁移链状态（改完要能对上）。

## 后端

### 1. 先抽出共享快照构造器（**纯重构，行为必须不变**）

- [ ] 把 `app/services/practice.py:567-586` 内联的 11 键快照字典抽成
      `build_question_snapshot(question) -> dict[str, Any]`，就近放在
      `validate_question_snapshot` 同址（`app/models/practice.py`）。
- [ ] `PracticeService.create_practice` 改为调用它；**键与值逐一对齐，不加不减**。
- [ ] `uv run lint-imports` 确认分层允许；不允许则退到 `app/core/`（以它的结论为准）。
- [ ] **先跑一次既有测试确认零回归**，再往下做。这一步单独提交，便于出事后回滚定位。

### 2. `ErrorType.MANUAL`（`app/models/practice.py:105-112`）

- [ ] 新增 `MANUAL = "manual"`，注释写明**它是来源标记不是错因归因**，
      未来做归因分布统计时必须排除。

### 3. 迁移：`practice_id` / `attempt_item_id` 改可空

- [ ] 模型两处改 `nullable=True`（`app/models/practice.py:839-851`）。
- [ ] 新建迁移 `0NNN_wrong_record_optional_practice_scope.py`，`upgrade()` 用
      `op.batch_alter_table("wrong_records")` 放宽两列（SQLite 兼容）。
- [ ] **`downgrade()` 必须显式处理手工记录**：写明策略（推荐删除 `practice_id IS NULL` 的行，
      在注释里说明理由），**不得让它在 NOT NULL 约束上直接失败**。
- [ ] `uv run alembic upgrade head`，并 `uv run alembic current` == `uv run alembic heads`。
- [ ] 迁移单测覆盖 `upgrade → downgrade → upgrade` 对称（对齐 `tests/unit/models/` 既有写法）。

> ⚠️ `tests/unit/models/test_migration_model_consistency.py` 只比对**表名与列名**，
> **不比对可空性**——它拦不住「模型改了、迁移忘了」。上面的对称单测是唯一保障。

### 4. 修 `upsert_wrong_record` 的覆盖行为（**PRD F3，本任务最高风险点**）

- [ ] **先写会失败的回归测试**（AC-4）：造一条带真实 `practice_id`/`attempt_item_id` 的错题记录，
      再以 `practice_id=None` / `attempt_item_id=None` 调 `upsert_wrong_record`，
      断言两个字段**仍为原值**、`error_count` 已累加、`is_mastered` 已重置。
      **按现状实现时这条测试必须失败**——跑一次确认它真的失败，再改代码。
- [ ] 把 `app/repositories/diagnosis.py:420-426` 的两个无条件赋值改为「非 None 才覆盖」。
- [ ] `knowledge_point_id` 的赋值**保持不变**（决策 3）。
- [ ] 更新 docstring，写入新契约：「练习归属一旦写下，不会被无归属的 upsert 清除」。
- [ ] 跑判题相关既有测试，确认判题路径行为不变。

### 5. 创建接口

- [ ] `app/schemas/diagnosis.py` 增 `WrongRecordCreateRequest`（仅 `question_id`）。
- [ ] `DiagnosisService` 增 `mark_question_as_wrong(user_id, question_id)`：
  - [ ] 查题目并校验属于当前用户、未软删除；不存在或越权 → 既有的 not-found 语义。
  - [ ] 取 `question.knowledge_point_id` 作为归属。
  - [ ] `build_question_snapshot(question)` → `validate_question_snapshot`；
        **不通过则抛错且不写库**，`details` 带 `question_id` 与原因。
  - [ ] 调 `upsert_wrong_record(..., practice_id=None, attempt_item_id=None,
        error_type=ErrorType.MANUAL.value)`。
  - [ ] `commit()`（service 层持有事务，路由层不开事务）。
- [ ] `app/api/v1/diagnosis.py` 增 `POST /wrong-records`，返回 `WrongRecordItemResponse`。
- [ ] 确认 `GET /wrong-records` 的响应里该条记录字段齐全（含装配后的 material/folder）。

### 6. 后端测试

- [ ] 幂等更新：对已有记录的题目重复标记 → 仍只有 1 条，`error_count` 累加（AC-1）。
- [ ] 快照不合法（如 `answer` 为空）→ 接口报错且**库中无新增**（AC-2）。
- [ ] 手工记录 `practice_id` / `attempt_item_id` 为 NULL，`error_type == "manual"`。
- [ ] 租户隔离：不能标记他人题目。
- [ ] **AC-6 举一反三覆盖**：手工作出一条错题后，断言按错题聚合出的知识点集合
      **包含**该题的知识点。这是 FR「根据错题再次生题」对手工错题成立的全部理由。
- [ ] 取消标记的具体分支（手工可删、判题记录不被删除）。

**后端验证命令**

```bash
cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest tests --cov=app --cov-branch --cov-fail-under=80
```

### 7. 让 `mypy` strict 把隐藏假设找完（**AC-9，不要绕过**）

- [ ] 跑 `uv run mypy app`，逐个处理所有原先假定 `practice_id` / `attempt_item_id`
      **非空**的站点。这些就是放宽约束后新出现的空指针面。
- [ ] **禁止用 `cast()` 或 `# type: ignore` 让它们闭嘴**：那只是让检查器不说话，
      运行时该炸还是炸。按 `spec/backend/database-guidelines.md` 的取向，
      类型检查器在这里是**发现工具**，不是障碍。

## 前端

### 8. 契约与动作

- [ ] `src/api/index.ts` 增 `apiMarkQuestionWrong(questionId)`（POST）。
- [ ] `src/api/index.ts` 补 `apiDeleteWrongRecord(recordId)`——
      `DELETE /wrong-records/{id}` 后端早就存在但前端**从未暴露**。
- [ ] `src/api/adapters/wrong.ts` 增创建响应的适配（复用既有 `adaptWrongRecord`）。
- [ ] 题目行动作位（来自 `09-29-question-bank-page`）实现「记入错题 / 取消标记」切换：
  - [ ] 已标记题目回显已标记态（**必需**，否则用户会重复点、`error_count` 虚高）。
  - [ ] 取消时按决策 6 分道：手工记录走删除；判题记录引导到「已掌握」，**不删**。
  - [ ] 请求在途禁用按钮，失败给可见反馈与重试。
- [ ] 用例：标记成功后本地状态回显、取消分支按来源正确分道。

### 9. 门禁

```bash
task verify   # 后端 + 前端
```

- [ ] `task verify` 退出码 0。
- [ ] 既有错题 / 判题 / 学情相关用例零回归。

## 风险点与回滚

| 风险 | 症状 | 处理 |
| --- | --- | --- |
| **忘了修 F3 的覆盖行为** | 手工标记一条判题错题，其练习归属被**静默**抹成 NULL | AC-4 回归测试先写并确认它失败 |
| 用 `cast()` 压掉 mypy 报错 | 放宽约束后新出现的空指针面被掩盖 | AC-9 明确禁止；逐站点处理 |
| 迁移只改模型没写迁移 | 一致性闸门**查不出可空性**，运行时才炸 | 迁移对称单测 + `alembic current` 自查 |
| `downgrade` 在 NOT NULL 上失败 | 回滚不可用 | 迁移里显式决定手工记录的去向并注释 |
| 快照另写一份 | 手工错题的选项/解析在界面上与判题错题不一致 | 决策 4：强制共用 `build_question_snapshot` |
| 双击重复标记 | `error_count` 虚高 | 在途禁用 + 已标记态回显 |

**回滚**：后端可单独回滚（撤接口 + `alembic downgrade`）。**注意 `downgrade` 会删除手工错题行**
（决策见 design.md），这是设计选择而非缺陷。前端动作位回滚 = 撤掉按钮，不影响其余功能。
