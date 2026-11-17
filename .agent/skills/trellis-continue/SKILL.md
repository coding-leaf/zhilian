---
name: trellis-continue
description: "Resume an active Trellis task ONLY when the user explicitly asks to continue/resume prior task work or when <workflow-state> is missing. Do NOT auto-load when Status: no_task."
---

# Continue Current Task (Antigravity)

1. **Guard**: If `<workflow-state>` already shows `Status: no_task` and the user did **not** explicitly ask to inspect dormant tasks on disk, **STOP** — there is no active task to continue.
2. **Inspect Active Task**:
   ```powershell
   python -X utf8 ./.trellis/scripts/get_context.py
   ```
3. **Route by `status` + Artifact Presence**:
   - `status=planning` + no `prd.md` → **1.1** (load `trellis-brainstorm`).
   - `status=planning` + `prd.md` only → lightweight tasks go to **1.4** review; complex tasks return to **1.1** to add `design.md` + `implement.md`.
   - `status=planning` + complex artifacts complete + `implement.jsonl` / `check.jsonl` empty or seed-only → **1.3** (curate manifests unless pure Inline lightweight).
   - `status=planning` + required artifacts + manifests ready → **1.4**: before running `task.py start`, obtain explicit user confirmation on: (1) Phase 2 formation (`Swarm` vs `Subagent` vs `Inline`), AND (2) **user-specified child-agent `model`** (once per session if using `Swarm`/`Subagent`).
   - `status=in_progress` + implementation not started → **2.1**.
   - `status=in_progress` + implementation done, not yet checked → **2.2**.
   - `status=in_progress` + check passed → **3.3** (`trellis-update-spec`) → **3.4** (commit) → `/trellis-finish-work`.
4. **One-Time Resume Model Guard**: When resuming a `planning` or `in_progress` task in a new session where the user has **not yet specified** the child-agent `model`, **ask once BEFORE dispatching** — never silently guess. Once specified once, reuse that `model` freely across all parallel subagents, Swarm workers, mid-flight `add`/`fork` additions, and worker-spawned helpers without re-asking.
5. **Load Only the Needed Step**:
   ```powershell
   python -X utf8 ./.trellis/scripts/get_context.py --mode phase --step <X.Y> --platform antigravity
   ```
