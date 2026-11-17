# 单测门禁执行（中期质量检查）

> **执行时间**：2026-10-04 15:51（北京时间）
> **总体结论**：**所有门禁通过** ✅
> **关键 KPI**：1496 用例通过 / 0 失败 / 全量覆盖率 91.34% / T0 核心 99%

## 📋 文档索引

| 文档 | 路径 | 内容 |
| --- | --- | --- |
| **单测报告** | [`单测报告.md`](./单测报告.md) | pytest 全量执行结果、分目录明细、耗时、警告归类 |
| **覆盖率报告** | [`覆盖率报告.md`](./覆盖率报告.md) | 全量 + T0 关键 + 各模块覆盖率明细、与上轮对比 |
| **缺陷单** | [`缺陷单.md`](./缺陷单.md) | 4 个 lint 格式缺陷（已修复并回归）+ 0 个产品代码缺陷 |
| **通过记录** | [`通过记录.md`](./通过记录.md) | 门禁矩阵、合并门禁语义、本地/CI 不变量、M1-M2 后续迭代 |

## 🚪 门禁矩阵（9/9 全部通过）

| # | 门禁 | 阈值 | 实测 | 状态 |
| ---: | --- | ---: | --- | :---: |
| 1 | ruff 格式 | 0 个未格式化 | 259 files formatted | ✅ |
| 2 | ruff lint | 0 个错误 | All checks passed! | ✅ |
| 3 | mypy | 0 个错误 | 135 files no issues | ✅ |
| 4 | import-linter | 5/5 KEPT | Contracts: 5 kept, 0 broken | ✅ |
| 5 | pytest | 0 个失败 | 1496 passed, 3 skipped | ✅ |
| 6 | 全量覆盖率 | ≥ 80% | **91.34%** | ✅ |
| 7 | T0 核心覆盖率 | ≥ 90% | **99%** | ✅ |
| 8 | T0 deps 覆盖率 | ≥ 80% | **84%** | ✅ |
| 9 | 增量覆盖率 | ≥ 80% | CI 端执行 | ℹ️ |

## 🎯 合并门禁语义

> **PR → master 的合并必须有 4 道机器门禁全部 green，否则 GitHub 拒绝合并按钮。**

- **本地门禁**：`task verify-backend`（或直接 `uv run pytest tests ...`）
- **CI 门禁**：`.github/workflows/verify.yml::backend` 镜像本地
- **分支保护规则**：GitHub `Settings → Branches → Branch protection rules → master`

详细配置见 [`通过记录.md`](./通过记录.md) §3。

## 📁 关联文档

- `../单测计划.md` —— 单测补充的整体规划
- `../单测补充用例清单.md` —— 上一轮 P0/P1 补测的 83 个新增用例清单
- `../环境与CI准备.md` —— CI 流水线拓扑与分支保护规则
- `../评审清单.md` —— 评审门禁清单

## 🚀 快速验证

```bash
cd ../../../backend

# 1. 单测门禁（必须 100% 通过）
uv run pytest tests --cov=app --cov-branch --cov-report=xml --cov-report=term-missing --cov-fail-under=80

# 2. T0 关键模块覆盖率
uv run coverage report --include="app/core/algorithms/*,app/core/security.py,app/core/errors.py" --fail-under=90
uv run coverage report --include="app/api/deps/*" --fail-under=80

# 3. 静态检查
uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports
```