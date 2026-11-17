<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->

## Quality Gates

Run the full gate before reporting any work complete:

```
task verify          # backend + frontend
task verify-backend  # ruff format/check, mypy (strict), import-linter, pytest (>=80% cov)
task verify-frontend # eslint, vue-tsc typecheck, vitest
```

Equivalent raw commands when the `task` runner is unavailable:

```
cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest tests --cov=app --cov-branch --cov-fail-under=80
cd miniprogram && pnpm run lint && pnpm run type-check && pnpm run test:unit
```

Auto-format: `task format` (ruff format + ruff check --fix; eslint --fix).

Toolchain notes:

- Backend runtime lives in `backend/.venv` (Python 3.13); all backend tooling runs through `uv run`.
- `mypy` and `ruff` CLI are the single source of truth for backend diagnostics.
- The `pyright` editor LSP is pinned to `backend/.venv` via `backend/pyrightconfig.json` (typeCheckingMode=basic) for in-editor feedback only; it does not replace the CLI gate.
- Frontend tooling runs through `pnpm` inside `miniprogram/`.
- **不要经由 WSL / Linux 容器跑后端或前端命令**。本项目在 Windows 上开发，
  `uv run` / `pnpm` / `task` 直接用宿主 shell 跑即可；绕道 WSL 启一套 Ubuntu 再执行
  宿主命令既慢又容易失败。控制台的编码问题（`lint-imports` 撞 GBK）已由 `Taskfile.yml`
  里的 `PYTHONIOENCODING: utf-8` 解决 —— **不要为了绕开它去启 WSL，也不要用
  `--junitxml=` 之类的临时手段另找取证通道**；命令的输出直接看即可。
- **`tests/unit/core/algorithms/` 下有一组墙钟阈值断言**（200ms / 50ms / 20ms / 100ms 等）。
  跑全量套件时 CPU 争用会让其中 2–4 个失败，**单独跑全部通过**。
  这是既有的测试设计问题，与你本次改动无关：**不要把它当成自己引入的回归去追，
  也不要为了让它变绿去放宽阈值**——那是把测试改到通过，不是修问题。

## Trellis + Antigravity 协同规范 (Workflow & Subagents)

- **`no_task` 调查约束与一次模型确认**：非简单问答时，不在任务确认前由主会话深入翻源码或查 Bug 撑爆上下文；先一次性确认「是否建 Trellis 任务 + 手动指明子代理 `model`」（确定一次后整场会话自动复用，不自作主张默认挑模型）；
- **Phase 1 适度委派调研与文档约束**：1–2 个已知小文件可直接看，多文件排查、调用链追踪与查 Bug 优先委派研究子代理或只读 `Swarm` 落盘 `{TASK_DIR}/research/*.md`（主会话读摘要）；收敛 `prd.md`（复杂任务补齐 `design.md`、`implement.md` 与 `jsonl`）并在 `task.py start` 前确认执行方式（`Swarm` / `Subagent` / `Inline`）；
- **Phase 2 自由编排与上下文自动注入**：按任务需要灵活选用 **原生 `Swarm`**（完全遵循内置 `swarm` 技能自由决定代理数量、多角色分工、`tasks`/`n` 分片池、多 Verifier、`#channel`、`monitor`、中途动态 `add`/`fork` 及 Worker 自招 Helper）、**`Subagent`**（`trellis-implement` -> `trellis-check`）或 **`Inline`**；`.agent/hooks.json` 自动向所有子代理与 Swarm 成员注入绝对路径工件与 `jsonl` 规范，子代理严禁修改 `.trellis/**` 或擅自 `git commit`/`push`，`share` 分支验证后合并回主工作区待提交；
- **Phase 3 质量门禁与文档沉淀**：执行当前项目 `.trellis/spec/` 与上方 Quality Gates 约定的离线构建/Lint/测试质量门禁（`task verify`，即 `task verify-backend` + `task verify-frontend`，在宿主 Windows shell 直接执行勿走 WSL），通过 `trellis-update-spec` 将新经验/踩坑沉淀回 `.trellis/spec/`，再在主会话确认 `git commit`、执行 `/trellis-finish-work` 归档任务并记录会话日志。
