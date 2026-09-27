# 执行计划：DIAG 读侧 P1 修复

## 前置

- 任务：`09-27-fix-diag-read-p1`（父：`09-27-fullstack-bug-audit-and-fix`）。
- 权威契约见 `design.md` §2；证据见归档 `archive/2026-09/09-27-read-only-bug-audit/research/slice-DIAG.md`。

## 执行清单（有序）

### Step 1 — 失败回归（红）
- [ ] 1.1 前端：新增 `tests/unit/api/diagnosisAdapter.spec.ts`，以后端形态夹具（`weak_knowledge_points` + `score_rate` + `mastery_after`，**无**前端字段）断言适配后 `weak_points` 非空、`overall_score`/`mastery_rate` 非零。
- [ ] 1.2 后端：`test_diagnosis_service.py` 新增 `get_user_mastery_overview(material_id=None)` 聚合全部知识点的断言（当前恒 0 → 红）。
- [ ] 1.3 后端：`test_diagnosis.py`（算法）退步用例断言 `score_delta` 为负且 `is_regressed` 为真（当前为正 → 红）。
- [ ] 1.4 运行测试确认新增断言红。

### Step 2 — DIAG-001/002 实现（前端适配层）
- [ ] 2.1 新增 `src/api/adapters/diagnosis.ts`（`adaptDiagnosisReport`，规则见 design §2.1）。
- [ ] 2.2 `src/api/diagnosis.ts::fetchDiagnosisReport` 接入适配（其余报告接口如被消费一并接入）。
- [ ] 2.3 前端适配测试转绿；旧夹具（已含前端字段）幂等通过。

### Step 3 — DIAG-007 实现（后端掌握度全景）
- [ ] 3.1 `KnowledgeRepository.list_all_by_user_id(user_id)` 新增（无上限）。
- [ ] 3.2 `DiagnosisService.get_user_mastery_overview` 支持 `material_id=None` 分支。
- [ ] 3.3 路由移除 `# type: ignore[arg-type]`；`_log_metric` target_id 兼容 None。
- [ ] 3.4 后端测试转绿；带 material_id 路径零回归。

### Step 4 — DIAG-008 实现（退步符号统一）
- [ ] 4.1 `check_regression` 改为 `current - previous`、`is_regressed = score_delta <= -threshold`；docstring 更新。
- [ ] 4.2 排序调整为“最弱 + 降幅最大优先”（符号翻转后等价）。
- [ ] 4.3 更新受影响算法测试；前端 `formatScoreDelta` 不改。
- [ ] 4.4 后端测试转绿。

### Step 5 — 全门禁
- [ ] 5.1 后端：`uv run ruff format --check .` + `ruff check .` + `mypy app` + `lint-imports` + `pytest`。
- [ ] 5.2 前端：`pnpm run lint` + `pnpm run type-check` + `pnpm run test:unit`。
- [ ] 5.3 逐条关闭 BUG-DIAG-001/002/007/008。

## 验证命令

```bash
# 后端（workdir=backend）
uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest tests
# 前端（workdir=miniprogram）
pnpm run lint && pnpm run type-check && pnpm run test:unit
```

## 评审门禁

- Gate A：3 组回归断言先红后绿。
- Gate B：后端五项 + 前端三项全绿；派发 `trellis-check` 复核契约、聚合分支与符号一致性。

## 回滚点

- 适配层为新增模块，移除接入即回滚。
- `material_id=None` 为新增分支。
- `check_regression` 符号复位即可回到旧行为（测试同步复位）。
