# 修复仓储层 DML rowcount 类型缺口并沉淀规范

## Goal

消除 `task verify-backend` 的 mypy strict 报错（4 条，集中在 2 行），并把「条件更新后取 `rowcount` 必须经 `isinstance(result, CursorResult)` 兜底」这条既有约定写进后端规范，避免同类缺口在下次新增 CAS / 批量更新时重现。

## Background

`uv run mypy app` 在 HEAD (`c1d329d`) 上报：

```
app/repositories/material.py:619: error: Returning Any from function declared to return "bool"  [no-any-return]
app/repositories/material.py:619: error: "Result[Any]" has no attribute "rowcount"  [attr-defined]
app/repositories/practice.py:208: error: Returning Any from function declared to return "bool"  [no-any-return]
app/repositories/practice.py:208: error: "Result[Any]" has no attribute "rowcount"  [attr-defined]
```

已核实的根因（本任务排查结论，非推测）：

- **上游类型标注缺口**：`.venv` 的 SQLAlchemy 2.0.54 中 `Session.execute` 只有两个重载（`.venv/Lib/site-packages/sqlalchemy/orm/session.py:2289` 起）：`TypedReturnsRows[_T] -> Result[_T]` 与 `Executable -> Result[Any]`。`Update`/`Delete` 不是 `TypedReturnsRows` 子类，只能命中后者，静态类型为 `Result[Any]`，而 `rowcount` 只定义在 `CursorResult` 上。
- `reveal_type(session.execute(update(...)))` 实测为 `sqlalchemy.engine.result.Result[Any]`；`.execution_options(synchronize_session="fetch")` 与否结果相同（曾被怀疑为诱因，已证伪）。
- **上游曾有过该重载**：系统 Python 的 SQLAlchemy 2.0.38 中存在 `execute(statement: UpdateBase) -> CursorResult[Any]`，2.0.54 已无（`grep CursorResult .venv/.../orm/session.py` 零命中）。
- **运行时无缺陷**：实测 `session.execute(update(...).execution_options(synchronize_session="fetch"))` 返回对象 `isinstance(res, CursorResult) is True`，`.rowcount` 真实可用。故这是纯类型标注缺口，不是运行时 bug。
- **4 条错误 = 2 处 × 2 条**：`attr-defined` 之后属性访问退化为 `Any`，在 `strict`（`warn_return_any`）下连带报 `no-any-return`。
- **为何只有这 2 处**：仓库另有 7 处同类操作已用兜底写法（`grading.py:206`、`knowledge.py:294/317/343`、`material.py:747`、`question.py:555`、`user.py:150`，2026-09-24 与 09-26 引入）；commit `15a621e`（09-29）新增的两个 CAS 方法直接写 `result.rowcount == 1`，未沿用该写法。

涉及的两个方法均为并发 compare-and-swap 的状态跃迁入口，返回值语义是「本次调用是否赢得跃迁」：

- `backend/app/repositories/material.py::MaterialRepository.try_transition_version_status`（消费方 `app/services/material.py:813`、`app/services/material.py:1454`）
- `backend/app/repositories/practice.py::PracticeRepository.try_transition_status`（消费方 `app/services/practice.py:1359`）

## Requirements

- 两处 `return result.rowcount == 1` 改为仓库既有兜底写法：`count = result.rowcount if isinstance(result, CursorResult) else 0` + `return count == 1`；`practice.py` 补 `from sqlalchemy.engine import CursorResult` 导入（`material.py` 已导入）。
- **返回值语义不得改变**：CAS 成功仍为 `True`，被并发抢先 / 未命中 `from_status` 仍为 `False`。运行时结果确为 `CursorResult`，故兜底分支不会改变既有行为。
- 在后端数据库规范中沉淀该约定与根因，位置以「事实源可核对」为准：`.trellis/spec/backend/database-guidelines.md` 的 Query Patterns 与 Common Mistakes 两节。
- 规范同步更新「最后核对」日期与 `.trellis/spec/backend/index.md` 索引行。

## Acceptance Criteria

- [ ] AC-1：`uv run mypy app` 无报错（134 source files）。
- [ ] AC-2：`task verify-backend` 全绿（ruff format/check、mypy strict、import-linter、pytest ≥80% 覆盖）。
- [ ] AC-3：两处改动的运行时语义与改前一致（CAS 赢/输两态返回值不变），不引入静默失败路径。
- [ ] AC-4：`.trellis/spec/backend/database-guidelines.md` 记录「DML 后取 `rowcount` 必须 isinstance 兜底」的 Wrong/Correct 对照与根因（含 SQLAlchemy 版本依据），并更新日期；`index.md` 索引同步。

## Out of Scope

- 上游 SQLAlchemy 的类型标注缺陷（不在本仓库可控范围，仅记录版本事实）。
- 给这两个 CAS 方法改写成 `RETURNING` / 其它跃迁实现（涉及语义变更，另开任务）。
- 仓储层其它 `.rowcount` 站点的重构（7 处已符合约定，无需改动）。
