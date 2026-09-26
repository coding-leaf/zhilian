# Journal - coding-leaf (Part 1)

> AI development session journal
> Started: 2026-09-26

---

## 2026-09-26 - 清理旧框架残留与工作区代码质量优化 (cleanup-legacy-sdlc-and-optimize)

- **背景**: 旧自研 SDLC 框架废弃卸载后，工作区残留大量已失效的脚本（根目录 `task.py` 严重干扰 Trellis 的 `.trellis/scripts/task.py`）、`tooling/`、旧 skills 及未被 gitignore 覆盖的缓存文件。
- **清理动作**:
  - 彻底移除根目录冲突的 `task.py`。
  - 清理并暂存删除旧 SDLC 脚本（`tooling/*.py`）、单测（根目录 `tests/test_*.py`）及废弃技能/prompt。
  - 完善 `.gitignore`（忽略 `*.db`, `.coverage.*`, `.ruff_cache/`, `.mypy_cache/`, `.pytest_cache/`, `.import_linter_cache/`）。
  - 将历史 SDLC 规范与任务完整移入 `docs/legacy_sdlc/` 备查。
  - 完善 `.trellis/spec/backend/quality-guidelines.md` 与 `.trellis/spec/frontend/quality-guidelines.md`，替换原有占位符，固化项目工程门禁标准。
- **验证成果**:
  - 后端通过 `ruff format`、`ruff check`、`mypy`、`lint-imports`（5 contracts kept）、`pytest`（1080 passed, 覆盖率 94.39%）。
  - 前端通过 `eslint`、`vue-tsc`、`vitest`（410 passed）。


