# 审计子任务执行计划

## 前置

- 任务：`09-27-read-only-bug-audit`（父：`09-27-fullstack-bug-audit-and-fix`）。
- 阶段：Planning 完成 → 经用户评审 → `task.py start` 后进入执行。
- 只读约束：除 `research/` 外不得改动仓库文件。

## 执行清单（有序）

### Stage A — 工具链基线
- [ ] A1. 采集后端基线：`uv run ruff format --check .` → `ruff check .` → `mypy app` → `lint-imports` → `pytest --cov --cov-branch --cov-fail-under=80`（workdir=`backend`），保存原始输出。
- [ ] A2. 采集前端基线：`pnpm run lint` → `pnpm run type-check` → `pnpm run test:unit`（workdir=`miniprogram`），保存原始输出。
- [ ] A3. 写入 `research/toolchain-baseline.md`；对失败项判定：产品 bug / ENV / 既有技术债，并标注。
- [ ] A4. 复核 `import pytest` LSP 误报：以 `uv run pytest` 实际结果为准。

### Stage B — 分层静态审阅
- [ ] B1. 后端：`repositories/` 事务与查询、`services/` 业务规则与异常、`api/` 路由与依赖注入、`schemas/` 契约、`core/algorithms/` 纯函数边界。
- [ ] B2. 前端：`stores/*Store.ts` 状态与副作用、`api/*` 请求封装、组件 props/emit 与条件渲染、`composables/`、`utils/`、页面生命周期与状态重置。
- [ ] B3. 逐项定位 `file:line` 并尝试用现有测试/最小推理复现。

### Stage C — 垂直切片跨层核对（6 片）
- [ ] C1. AUTH：后端 auth/security ↔ `api/auth.ts` ↔ `userStore` ↔ 登录页。
- [ ] C2. MAT：material/knowledge/search ↔ `api/material.ts` ↔ `materialStore` ↔ 素材页。
- [ ] C3. QGEN：question/question_quality ↔ `api/question.ts` ↔ 生成/审核/编辑组件。
- [ ] C4. PRAC：practice ↔ `api/practice.ts` ↔ `practiceStore`/草稿 ↔ 作答页。
- [ ] C5. GRADE：grading ↔ 评分组件（自评/重批）↔ 结果渲染。
- [ ] C6. DIAG：diagnosis ↔ `api/diagnosis.ts` ↔ `reportStore` ↔ 报告/错题本页。
- [ ] C7. 每片结论写入 `research/cross-layer-matrix.md`。

### Stage D — 非功能性普查
- [ ] D1. 识别重复实现/多套能力（排除已验证的 re-export shim）。
- [ ] D2. 识别未引用导出/死代码。
- [ ] D3. 写入 `research/code-smells.md`（`SMELL-*` 编号）。

### Stage E — 汇总与门禁
- [ ] E1. 汇总 `research/bug-ledger.md`：统一编号、分级、证据、`file:line`、修复方向。
- [ ] E2. 生成统计矩阵：切片 × 级别 计数；ENV / 疑似单列。
- [ ] E3. 自检：每条功能性发现均有证据；P2 均满足客观边界；无主观 UX 混入。
- [ ] E4. 向用户提交清单，进入评审门禁，等待确认后再派生修复子任务。

## 验证命令（本任务自身）

只读审计无代码改动，验证以"制品完整性 + 命令可重跑"为准：
```
# 制品存在性
ls .trellis/tasks/09-27-read-only-bug-audit/research/
# 清单编号唯一性抽查
rg -o "BUG-[A-Z]+-[0-9]+" research/bug-ledger.md | sort | uniq -d   # 期望为空
```

## 评审门禁

- Gate 1（本任务完成前）：清单已覆盖 6 切片、证据齐全、无主观项混入 → 用户确认。
- Gate 2（进入修复前）：`task.py start` 由用户批准后执行；修复子任务按切片创建。

## 回滚点

- 若清单被用户判定"覆盖不足" → 返回 Stage B/C 补充，不进入修复。
- 若发现审计需改业务代码才能确证 → 记录为"需复现环境"项，不越界修改。

## 与父任务/修复子的依赖

- 依赖：无前置子任务；本任务是全链路第一环。
- 被依赖：所有修复子任务均依赖本任务的 `bug-ledger.md` 确认结果。
