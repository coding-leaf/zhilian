# 执行计划：GRADE 切片 P2-B 修复

## 前置条件与规范
- 对应任务：`09-27-fix-grade-p2b`。
- 遵循零 `any`、import-linter 分层规则、测试先红后绿原则。
- 范围严格限制在 BUG-GRADE-009, 010, 011, 012, 013, 016。

---

## 执行清单（有序步骤）

### Step 1 — 编写失败回归测试（红）
- [ ] 1.1 **GRADE-009**：在 `backend/tests/unit/core/algorithms/test_grading.py` 新增偶数边界 `k.5` 舍入用例（如 raw_score 9.25, unit 0.5 舍入应得 9.5，当前银行家舍入得 9.0 → 红）。
- [ ] 1.2 **GRADE-010**：在 `backend/tests/unit/services/test_grading_service.py` 补充 LLM 判题和重判分非 0.5 粒度断言（Mock LLM 返回 7.3 分，断言落库 score 应为 7.5 → 红）。
- [ ] 1.3 **GRADE-011**：在 `backend/tests/unit/api/test_grading_router.py` 和 `test_grading_service.py` 增加显式传递 `is_correct=False`（即使 score=5.0）或 `is_correct=True`（即使 score=0.0）断言 `grading_metadata["is_correct"]` 正确反映传入值（当前被丢弃 → 红）。
- [ ] 1.4 **GRADE-012**：在 `miniprogram/tests/unit/report/gradingModals.spec.ts` 增加自评弹窗接收嵌套 `points` 细则对象用例，断言渲染出要点标签和分值说明，且不包含原始 JSON 字符串（当前包含 JSON → 红）。
- [ ] 1.5 **GRADE-013**：在 `miniprogram/tests/unit/report/gradingModals.spec.ts` 增加重判弹窗支持超过 200 字且不超过 500 字输入的断言，验证 maxlength 为 500（当前为 200 → 红）。
- [ ] 1.6 **GRADE-016**：在 `backend/tests/unit/services/test_grading_service.py` 增加算法执行异常时旧生效记录保护测试，验证若算法抛出异常，原生效记录 `is_final` 仍为 True 或安全降级且不崩溃整卷（当前先失效旧记录 → 红）。

### Step 2 — 后端算法与服务层修复（绿）
- [ ] 2.1 **GRADE-009**：
  - 在 `backend/app/core/algorithms/grading.py` 实现 `round_half_up(value: float, unit: float = 0.5) -> float`。
  - 在 `_build_subjective_offline_result` 中将 `round(raw_score / unit) * unit` 替换为 `round_half_up(raw_score, unit)`。
- [ ] 2.2 **GRADE-010**：
  - 在 `backend/app/services/grading.py` 的 `_grade_with_llm` 及 `regrade_attempt` 中，对最终分值应用 `round_half_up(raw_score, SCORE_ROUNDING_UNIT)`。
- [ ] 2.3 **GRADE-011**：
  - 在 `backend/app/services/grading.py` 的 `SelfEvaluateDTO` 添加 `is_correct: bool | None = None`。
  - 在 `backend/app/api/v1/grading.py` 的 `self_evaluate` 接口将 `request.is_correct` 透传至 `SelfEvaluateDTO`。
  - 在 `GradingService.self_evaluate_attempt` 中支持 `dto.is_correct` 覆盖默认推导规则。
- [ ] 2.4 **GRADE-016**：
  - 在 `backend/app/services/grading.py` 的 `_grade_attempt_item` 中，将 `set_records_non_final_by_attempt_id` 移至算法计算完成之后、创建新生效记录之前。
  - 对算法核调用 `match_and_grade_answer` 增加异常捕获，若发生非预期异常，记录告警并安全降级处理（保留原生效记录或降级 pending）。

### Step 3 — 前端组件修复（绿）
- [ ] 3.1 **GRADE-012**：
  - 在 `miniprogram/src/subpackages/report/components/SelfGradeModal.vue` 升级 `rubricEntries`：支持结构化 `{ points: [...] }` 与 `{ dimensions: [...] }` 展开格式化。
- [ ] 3.2 **GRADE-013**：
  - 在 `miniprogram/src/subpackages/report/components/RegradeModal.vue` 将 `textarea` 的 `:maxlength` 设置为 500，字数展示改为 `500`。

### Step 4 — 全量门禁校验与收尾
- [ ] 4.1 运行后端全量校验门禁：
  - `uv run ruff format --check .`
  - `uv run ruff check .`
  - `uv run mypy app`
  - `uv run lint-imports`
  - `uv run pytest tests`
- [ ] 4.2 运行前端全量校验门禁：
  - `pnpm run lint`
  - `pnpm run type-check`
  - `pnpm run test:unit`
- [ ] 4.3 确认所有修复项先红后绿。

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
