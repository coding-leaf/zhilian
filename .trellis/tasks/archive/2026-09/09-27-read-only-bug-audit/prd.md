# 全量只读审计：前后端 bug 总清单

## Goal

以工具链实测 + 静态审阅为双重证据，按垂直功能切片全量扫描 `backend/` 与 `miniprogram/`，产出一份**统一分级（P0/P1/P2）的 bug 总清单**，每条附可复现证据与 `file:line`，供用户确认后分批进入修复。

## Requirements

### 必须做
1. **工具链实测基线**（记录原始命令与输出）：
   - 后端：`uv run ruff format --check .`、`uv run ruff check .`、`uv run mypy app`、`uv run lint-imports`、`uv run pytest tests --cov=app --cov-branch --cov-fail-under=80`
   - 前端：`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit`
2. **分层静态审阅**（前后端各自）：
   - 后端：repository / service / api 三层逻辑、契约（schema）一致性、事务与并发、错误处理、算法纯函数（`core/algorithms`）。
   - 前端：store（Pinia 状态与副作用）、api 层、组件逻辑与 props/emit 契约、composable、utils、页面生命周期与状态重置。
3. **跨层一致性核对**（垂直切片核心）：后端 API（路径/字段/错误码）↔ 前端 `src/api/*` ↔ store ↔ 组件消费，逐切片核对。
4. **重复造轮子/死代码普查**：识别同一能力多实现、未被引用的导出、废弃 shim、重复工具函数；**仅记录**并单列。
5. **分级**：按 P0/P1/P2 定义（见 `design.md`）给每条发现定级，附证据与复现路径。
6. **清单制品**：写入本任务 `research/`（如 `research/bug-ledger.md`），并在其中按垂直切片分组。

### 约束
- **只读**：不修改任何业务代码、不跑会改动仓库状态的命令。
- 工具链失败若由**环境**（缺依赖/无法解析解释器）导致，须标注"环境受限"，不直接判定为产品 bug。
- 前端真机/开发者工具专属问题标为"疑似，待人工验证"，不当作已证实 bug。
- 非功能性发现与功能性 bug 分区呈现，不混排。

### 交付边界
- 本子任务**只产出清单与证据**，不做任何修复。
- 清单完成后进入评审门禁，等待用户确认；确认后由父任务派生修复子任务。

## Acceptance Criteria

- [ ] 后端 5 项工具链命令全部执行并记录结果（含失败原文与环境受限标注）。
- [ ] 前端 3 项工具链命令全部执行并记录结果。
- [ ] 覆盖全部 6 个垂直切片的跨层一致性核对，每片给出结论（通过/发现问题）。
- [ ] `research/bug-ledger.md` 存在，且每条发现含：编号、级别、切片、层、`file:line`、证据/复现、影响、修复建议方向。
- [ ] 非功能性发现独立成节（`research/code-smells.md` 或清单内分节），不与功能性 bug 混合计数。
- [ ] 统计摘要：各切片 × 各级别的问题数量矩阵，以及"环境受限/疑似"项单列。
- [ ] 清单内部编号唯一且可被后续修复子任务逐条引用关闭。

## Notes

- 本任务为父任务 `09-27-fullstack-bug-audit-and-fix` 的审计子任务；修复子任务在其完成并经用户确认后创建。
- 证据以"命令可重跑、位置可跳转"为准，避免无法复现的断言。
