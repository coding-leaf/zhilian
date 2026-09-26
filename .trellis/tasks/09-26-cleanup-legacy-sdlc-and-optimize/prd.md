# 清理旧框架残留与工作区代码质量优化 PRD

## Goal

彻底清理根目录及各模块中已被废弃的自研 SDLC 框架遗留文件、脚本和配置，消除与 Trellis 框架（如 `task.py`）命名冲突，完善 `.gitignore` 防止临时文件污染工作区，并确立基于 Trellis 的前后端质量门禁基线。

## Requirements

1. **废弃自研 SDLC 框架残留清理**：
   - 移除根目录下与 Trellis 冲突的 `task.py`。
   - 确认并提交删除已废弃的自研 SDLC 脚本及测试：`tooling/`（`check_layers.py`, `check_sdlc_integrity.py`, `extract_doc.py`, `subagent_stats.py`, `task_cli.py`）及根目录 `tests/`（`test_extract_doc.py`, `test_subagent_stats.py`, `test_task_cli.py`）。
   - 移除已废弃的旧代理配置：`.agents/skills/`（`bug-fix`, `pr-review-gate`, `sdlc-workflow`, `subagent-stats`）及 `.opencode/agent/`、`.opencode/commands/` 下旧版 prompt。
   - 保持 `docs/legacy_sdlc/` 纯粹归档状态，移出核心活动区。
2. **根目录任务与门禁规范**：
   - 提供明确、无冲突的工作区级命令或指导（不侵占 `task.py` 命名），确保开发者和 AI 能统一运行后端与前端的测试与格式化。
3. **环境与忽略规则优化（.gitignore）**：
   - 将工作区产生的本地开发数据库（如 `backend/zhilian_dev.db`）、覆盖率报告（`backend/.coverage`）、Python/Ruff/Pytest 临时缓存等规范化纳入忽略规则，保持 `git status` 清爽。
4. **验证基线建立（Baseline Verification）**：
   - 后端验证通过：`uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy app`、`uv run pytest tests`。
   - 前端验证通过：`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit`。

## Acceptance Criteria

- [ ] 根目录不再存在旧自研 `task.py`，避免与 `.trellis/scripts/task.py` 产生混淆与冲突。
- [ ] 所有已标记删除的旧 SDLC 脚本、agent 规则、工具测试均在 Git 中妥善清理和提交。
- [ ] `.gitignore` 配置完善，`zhilian_dev.db`、`.coverage`、临时缓存不再显示为未跟踪或脏文件。
- [ ] 后端通过全量 Ruff（check + format）、Mypy、Pytest 检查，无报错。
- [ ] 前端通过全量 ESLint、vue-tsc、Vitest 单元测试，无报错。
- [ ] 工作区恢复整洁健康，符合 Trellis 标准规范。
