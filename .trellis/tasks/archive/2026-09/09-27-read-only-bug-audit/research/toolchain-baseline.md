# 工具链基线（Stage A）

采集时间：2026-09-27
环境：Windows / Python 3.12.13 / uv 0.12.1 / pnpm 12.4.1 / `go-task` 未安装（直调底层命令）
说明：`pytest` 使用 `tests` 全量（含 integration，均走 in-memory fake）。

## 后端（workdir = `backend/`）

| # | 命令 | 结果 | EXIT |
|---|---|---|---|
| A1a | `uv run ruff format --check .` | `216 files already formatted` | 0 |
| A1b | `uv run ruff check .` | `All checks passed!` | 0 |
| A1c | `uv run mypy app` | `Success: no issues found in 125 source files` | 0 |
| A1d | `uv run lint-imports` | `Contracts: 5 kept, 0 broken.`（五层单向架构 5 契约全 KEPT） | 0 |
| A1e | `uv run pytest tests --cov=app --cov-branch --cov-fail-under=80` | `1130 passed`；覆盖率 `91.92%`（≥80% 达标） | 0 |

**结论**：后端工具链八项无失败，无 P0/P1/P2 由工具链直接暴露。缺陷须由静态审阅与跨层核对产出。

覆盖率关注点（低于 90% 的模块，供后续静态审阅聚焦，非 bug 本身）：
- `app/api/deps/db.py` 50%、`app/services/auth.py` 76%、`app/cli/commands/practice.py` 33%、`app/cli/commands/question.py` 42%、`app/cli/commands/grading.py` 55%、`app/cli/commands/db.py` 57%、`app/cli/commands/material.py` 63%、`app/schemas/diagnosis.py` 80%、`app/api/deps/auth.py` 82%、`app/services/question.py` 84%、`app/api/v1/practices.py` 84%、`app/api/v1/materials.py` 88%。
- 其中 `app/services/auth.py`(76%)、`app/schemas/diagnosis.py`(80%) 为业务核心，覆盖率偏低值得静态复核。

## 前端（workdir = `miniprogram/`）

| # | 命令 | 结果 | EXIT |
|---|---|---|---|
| A2a | `pnpm run lint` | 无输出（eslint 通过） | 0 |
| A2b | `pnpm run type-check` | `vue-tsc --noEmit` 通过 | 0 |
| A2c | `pnpm run test:unit` | `54 passed` 文件 / `452 passed` 用例 / 16.39s | 0 |

**结论**：前端三项门禁全绿，无 P0/P1/P2 由工具链直接暴露。

### 非缺陷噪声（记录，不计入清单）
- **LSP 误报（ENV）**：编辑器 LSP 报 `backend/tests/**` 中 `import pytest` 无法解析；实测 `uv run pytest` 全绿，判定为 LSP 解释器配置问题，非产品 bug。
- **Vue 组件解析警告（ENV/测试环境）**：vitest(happy-dom) 输出大量 `Failed to resolve component: wd-icon / wd-loading / wd-tag / scroll-view / slider`。`wd-*` 来自 wot-design-uni（easycom/全局注册），`scroll-view`/`slider` 为 uni-app 内置组件，测试环境未注册，故为测试环境噪声，非渲染 bug。真机侧需人工验证（见 design.md 疑似项规则）。
- **Sass 弃用警告（ENV）**：`legacy-js-api` deprecated，属 sass 版本升级提示，非功能缺陷。

## 基线总体判定

| 维度 | 状态 |
|---|---|
| 后端 8 项工具链 | ✅ 全绿 |
| 前端 3 项工具链 | ✅ 全绿 |
| 由工具链直接暴露的功能性 bug | 0 |
| 后续取证路径 | 静态审阅 + 6 切片跨层核对（Stage B/C） |
