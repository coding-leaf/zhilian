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
