# Start Session (Antigravity)

> [!IMPORTANT]
> **Step 0 — Hook Fast-Exit Guard:** In Antigravity, `.agent/hooks.json` (`session-start` and `pre-invocation`) automatically injects `<trellis-session-context>` and `<workflow-state>`. If both are already present in this conversation AND the user did **not** explicitly invoke `/start` or `/trellis-start` to reload status, **STOP immediately** and follow `<workflow-state>` directly (do NOT dump `.trellis/workflow.md`).

---

## Step 1: Current state (Manual / Fallback Reload)

Identity, git status, current task, active tasks, journal location:

```powershell
python -X utf8 ./.trellis/scripts/get_context.py
```

If this output includes a line beginning `Trellis update available:`, copy the full line verbatim when summarizing session context. Do not shorten operational command hints.

## Step 2: Workflow overview

Compact Phase Index, request triage rules, and planning artifact contract:

```powershell
python -X utf8 ./.trellis/scripts/get_context.py --mode phase --platform antigravity
```

Full guide lives in `.trellis/workflow.md` (fetch only single steps on demand).

## Step 3: Guideline indexes

Discover packages + spec layers:

```powershell
python -X utf8 ./.trellis/scripts/get_context.py --mode packages
```

> [!CAUTION]
> Read `.trellis/spec/<package>/<layer>/index.md` ONLY after entering Phase 1 planning (`trellis-brainstorm` / child researchers) or coding — **never** during `no_task` triage.

## Step 4: Route & Enforce User-Specified Model Rule

From Step 1 or `<workflow-state>`, route by current task state:

- **No active task (`Status: no_task`)**:
  - **Investigation restraint**: Before task creation is confirmed, do not dive into multi-file code reading, broad searches, or inline bug debugging in the main session (quick orientation only when genuinely trivial).
  - **Simple conversation / trivial task**: ask only whether this turn should create a Trellis task (if user says no, handle directly without Trellis).
  - **Non-trivial bug / feature / audit / refactor**: ask in **one combined prompt** for:
    1. Consent to create a Trellis task (`task.py create`), AND
    2. **Child-agent `model`** to use (never silently guess; once specified once by the user, reuse it across all child agents, Swarm workers, and helpers in this session without re-asking).
- **Active task status `planning`**: stay in Phase 1 (`trellis-brainstorm`), keeping main context lean by delegating multi-file exploration / bug localization to child researchers writing `{TASK_DIR}/research/*.md`. Fetch single-step detail on demand via:
  ```powershell
  python -X utf8 ./.trellis/scripts/get_context.py --mode phase --step 1.X --platform antigravity
  ```
- **Active task status `in_progress`**: Phase 2 step `2.1`. Fetch step detail:
  ```powershell
  python -X utf8 ./.trellis/scripts/get_context.py --mode phase --step 2.1 --platform antigravity
  ```

> [!CAUTION]
> **Hard Redline — One-Time User-Specified Model:** Every child agent (`trellis-research`, `trellis-implement`, `trellis-check`, and `swarm` workers/helpers) **MUST** use a `model` specified by the user. If the user has not specified `model` yet in this session, **ask once first** — never guess a default, and always pass `Model` explicitly on `invoke_subagent` (in `swarm`, omit `model` only when matching the current session model per user choice or for `monitor`/`narrator`). Once specified once, reuse freely across all child agents, dynamic `add`/`fork` scaling, and worker helpers without re-asking.

---

## Skill & Agent Routing (Antigravity Quick Reference)

| User intent / Phase | Tool / Skill / Agent |
|---|---|
| New feature / unclear requirements | `trellis-brainstorm` |
| Bug localization / cross-layer or history audit | Child `swarm` researchers (`workspace:"inherit"`) or `invoke_subagent(TypeName="trellis-research", Model=<user-tier>)` writing `{TASK_DIR}/research/*.md` |
| Multi-agent / parallel / adversarial / exact-model Phase 2 | Native `swarm` skill (any worker count, verifier/channel/monitor, dynamic `add`/`fork`, worker helpers — `.agent/hooks.json` auto-injects specs) |
| Single-track Phase 2 execution (`inherit`/`flash_lite`/`flash`/`pro`) | `Subagent`: `trellis-implement` -> `trellis-check` via `invoke_subagent` with explicit `Model` |
| Small / straightforward Inline Phase 2 | `trellis-before-dev` -> edit -> `trellis-check` skill |
| Stuck / fixed same bug multiple times | `trellis-break-loop` |
| Learned something worth capturing | `trellis-update-spec` |
| Wrap up after Phase 3.4 commits | `/trellis-finish-work` |
