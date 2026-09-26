# 清理旧框架残留与工作区代码质量优化 - 技术设计 (design.md)

## 1. 背景与现状

在引入 Trellis 规范前，仓库中存在一套自研的 SDLC 辅助工具集（包括根目录 `task.py`、`Taskfile.yml`、`tooling/`、`.agents/skills/`、`.opencode/agent/` 以及 `docs/sdlc/`）。
旧方案尝试自己造轮子管理任务状态与代理分工，但维护繁琐且与新接入的 Trellis 体系发生命名与认知冲突（如 Trellis 官方脚本路径为 `./.trellis/scripts/task.py`，而根目录存在一个执行 Taskfile 的 `task.py`）。
此外，本地测试产生的 SQLite 数据库和缓存未被 `.gitignore` 充分覆盖，导致 Git 工作区有大量的脏文件提示。

## 2. 边界与清理方案 (Boundaries & Cleanup)

### 2.1 文件分类与处置策略

| 路径 / 模块 | 性质 | 处置策略 | 理由 |
|---|---|---|---|
| `./task.py` (根目录) | 旧 SDLC 入口 | **删除** | 严重干扰 Trellis 的 `.trellis/scripts/task.py`，容易误触发旧逻辑 |
| `./Taskfile.yml` | 任务文件 | **保留或重构** | 仅作为本地命令快捷方式，如果保留，通过标准 `task` 命令或专用脚本触发，不以 `task.py` 命名 |
| `./tooling/*.py` | 旧 SDLC 自研工具 | **确认删除** | 功能已由 Trellis 规范与子代理原生替代 |
| `./tests/test_*.py` (根目录) | 旧 SDLC 工具测试 | **确认删除** | 针对被删除工具的单测，已无意义 |
| `.agents/skills/*` (旧 SDLC) | 旧自研技能定义 | **确认删除** | Trellis 有完整的 `.trellis/` 与 `.opencode/` 技能体系 |
| `.opencode/agent/*`, `commands/*` | 旧自研代理命令 | **确认删除** | Trellis 自动生成了 `.opencode/agents/` |
| `docs/legacy_sdlc/` | 历史任务与设计归档 | **保留并提交** | 作为历史经验备查，已移入 `legacy_sdlc` |
| `backend/zhilian_dev.db` 等 | 本地开发数据库/缓存 | **Git 忽略** | 完善根目录及 backend 的 `.gitignore` |

### 2.2 门禁与验证策略

清理后，日常工程门禁明确划分为：
1. **后端验证命令（在 `backend/` 下运行）**：
   - 格式检查：`uv run ruff format --check .`
   - 代码风格与错误：`uv run ruff check .`
   - 类型检查：`uv run mypy app`
   - 架构依赖约束：`uv run lint-imports`（若配置了 import-linter）
   - 单元测试与覆盖率：`uv run pytest tests`
2. **前端验证命令（在 `miniprogram/` 下运行）**：
   - 代码风格：`pnpm run lint`
   - 类型检查：`pnpm run type-check`
   - 单元测试：`pnpm run test:unit`
3. **全局便捷验证（可选辅助）**：
   - 可在 `Taskfile.yml` 中保留 `task verify`，或通过 Trellis 规范要求在各子包中独立执行，拒绝根目录再用同名 `task.py`。

### 2.3 兼容性与回滚策略 (Rollback & Compatibility)

- 核心业务代码（`backend/app/` 与 `miniprogram/src/`）在本次清理中不进行破坏性修改，保持 100% 测试通过。
- 历史文档全部保留在 `docs/legacy_sdlc/`，若有过去的设计细节需查阅，随时可检索。
- 删除操作均通过 Git 记录，可单次完整 revert。
