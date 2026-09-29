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
