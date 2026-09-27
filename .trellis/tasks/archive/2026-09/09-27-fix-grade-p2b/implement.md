# 执行计划：GRADE 切片 P2-B 修复

## 前置条件与规范
- 对应任务：`09-27-fix-grade-p2b`。
- 遵循零 `any`、import-linter 分层规则、测试先红后绿原则。
- 范围严格限制在 BUG-GRADE-009, 010, 011, 012, 013, 016。

---

## 执行清单（有序步骤）

### Step 1 — 编写失败回归测试（红）
- [x] 1.1 **GRADE-009**：新增 `TestHalfUpScoreRounding`（`round_half_up(9.25, 0.5)==9.5`、`7.25→7.5`、离线构造器 raw=9.25→9.5）。旧实现银行家舍入得 9.0/7.0（已实测确认）。
- [x] 1.2 **GRADE-010**：新增 LLM 首次判分 7.3→7.5、8.24→8.0、重判 7.3→7.5 断言；同步修正既有重判用例 4.8→5.0。
- [x] 1.3 **GRADE-011**：服务层显式 `is_correct=False/True` 覆盖与缺省 `score>0` 回退断言；路由层 `dto.is_correct is False` 透传断言。
- [x] 1.4 **GRADE-012**：自评弹窗嵌套 `points` / `dimensions` 用例，断言要点标签+分值与无 `point_id`/JSON 噪音。
- [x] 1.5 **GRADE-013**：重判弹窗断言 `maxlength=500`、`300 / 500` 计数与 >200 字可提交。
- [x] 1.6 **GRADE-016**：算法抛异常时整卷不崩溃、原记录不丢失、唯一生效记录（安全降级 pending）断言。

### Step 2 — 后端算法与服务层修复（绿）
- [x] 2.1 **GRADE-009**：
  - 在 `backend/app/core/algorithms/grading.py` 实现 `round_half_up(value, unit=SCORE_ROUNDING_UNIT)`（Decimal + ROUND_HALF_UP）。
  - `_build_subjective_offline_result` 改用 `round_half_up(raw_score, unit)`。
- [x] 2.2 **GRADE-010**：
  - `_grade_with_llm` 与 `regrade_attempt` 的 clamp 后分值统一 `round_half_up(..., SCORE_ROUNDING_UNIT)`。
- [x] 2.3 **GRADE-011**：
  - `SelfEvaluateDTO` 增加 `is_correct: bool | None = None`。
  - `api/v1/grading.py` 透传 `request.is_correct`。
  - `self_evaluate_attempt` 优先采纳 `dto.is_correct`，为空回退 `score > 0`。
- [x] 2.4 **GRADE-016**：
  - 取消入口处提前失效；改为「算法完成/即将落库新记录前」才 `set_records_non_final_by_attempt_id`。
  - `match_and_grade_answer`（含快照解析）加 `try...except Exception`，异常记录告警并安全降级为 `pending_regrade`，不丢原记录、不中断整卷。

### Step 3 — 前端组件修复（绿）
- [x] 3.1 **GRADE-012**：
  - `SelfGradeModal.vue` 重写 `rubricEntries`：解析 `{ points: [...] }` / `{ dimensions: [...] }`，格式化 `要点 N（X分）` 与描述；平铺/字符串/嵌套对象优雅回退，去除 `total_score` 与原始 JSON。
- [x] 3.2 **GRADE-013**：
  - `RegradeModal.vue` `:maxlength="500"`，字数展示 `x / 500`。

### Step 4 — 全量门禁校验与收尾
- [x] 4.1 后端门禁全绿：`ruff format --check` / `ruff check` / `mypy app` / `lint-imports` / `pytest`（1212 passed）。
- [x] 4.2 前端门禁全绿：`pnpm run lint` / `pnpm run type-check` / `pnpm run test:unit`（544 passed，59 files）。
- [x] 4.3 所有修复项先红后绿（旧实现实测：`round(9.25/0.5)*0.5=9.0`；`round(7.25/0.5)*0.5=7.0`；LLM 7.3 原样落库）。

---

## 验证命令

```bash
# 后端门禁 (工作目录 backend)
uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest tests

# 前端门禁 (工作目录 miniprogram)
pnpm run lint && pnpm run type-check && pnpm run test:unit
```

## 评审门禁
- Gate A: 各 Bug 回归测试先红后绿。
- Gate B: 后端 mypy/ruff/lint-imports 全绿，前端 eslint/vue-tsc/vitest 全绿。
- Gate C: 契约字段在跨层传递中无类型截断与丢失。

## 回滚点
- 009/010: 舍入函数还原为原生 round。
- 011: DTO 字段回退为可选不传递。
- 012/013: 前端组件模板与属性复位。
- 016: 还原 `_grade_attempt_item` 的调用顺序。
