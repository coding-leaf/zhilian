# Git Branch & Workspace Hygiene Audit (`11-17-repo-refactor-git-hygiene`)

> Audit Date: 2026-11-17 | Read-Only Audit on Branch `chore/workspace-configs` (`d223cb5`) | Host: Windows `pwsh`

## Executive Summary

- **Trunk & Divergence Crisis**: Trunk is `master` (`0c301fa`, 2026-10-03). Two long-lived branches have diverged ahead of `master` with **overlapping file edits**: `origin/dev` (**+22/-0** ahead, 21 unique commits including `midterm-baseline-2026-10-04`, `pyjwt` security bump, BUG-01/02/03 fixes, `diff-cover` gates) and local `chore/workspace-configs` (**+3/-0** ahead, **+2** ahead of `origin/chore/workspace-configs`), which unexpectedly carries a full P1-4 backend+frontend feature commit (`5f9fa5f`).
- **Branch Counts (13 Local + 11 Remote + `origin/HEAD`)**:
  - **Ancestor-Merged (`Delete`)**: **10** local branches + **8** remote branches (`0` unlanded commits; 0 squash-merges detected).
  - **Active / Unmerged (`Merge/Salvage` or `Keep`)**: `master` (`Keep`), `origin/dev` (`Merge/Salvage` to trunk), `chore/workspace-configs` + `origin/chore/workspace-configs` (`Merge/Salvage` split by concern), `codex/frontend-vertical-slices` (`Archive-Tag & Delete` or `Merge/Salvage` 1 doc commit).
- **Working Tree Dirty State**: Current branch `chore/workspace-configs` has **4 pre-existing dirty paths** from the 2026-11-17 Antigravity Trellis upgrade (`M .trellis/.template-hashes.json`, `M .trellis/workflow.md`, `M AGENTS.md`, `?? .agent/` [56 untracked files]) plus the newly created `?? .trellis/tasks/11-17-repo-refactor-git-hygiene/`. One stale linked worktree exists at `.worktrees/frontend-vertical-slices`. Stash is empty (`0`).
- **Workspace Config Redundancies**: **6** coexisting AI tool config directories (`.agent/`, `.agents/`, `.claude/`, `.codex/`, `.opencode/` with 3,667 `node_modules` files, `.pi/`), a stray `%SystemDrive%/` Windows cache directory, an empty orphan `backend/.trellis/`, a WSL-only `sync_to_host.sh` violating `AGENTS.md`, missing `.editorconfig` / `.pre-commit-config.yaml`, and **9 stale `09-29-*` task directories** in `.trellis/tasks/`.
- **Recommended Governance Model**: Single-trunk (`master`) + short-lived `feat|fix|refactor|chore|docs/<task-or-issue>-<slug>` branches (squash/PR merge + `--delete-branch`), strict **one-branch-one-purpose** rule (no feature commits on `chore/*`), explicit worktree/Swarm `share` cleanup SOP, and curated `.trellis/spec/` + `.gitignore` hygiene.

---

## 1. Current Working Tree, Worktrees & Stashes

### 1.1 Working Tree Dirty State (`git status --short` on `chore/workspace-configs`)

| Path | Git Status | Origin & Exact Diff Summary |
| --- | --- | --- |
| `.trellis/.template-hashes.json` | ` M` | Modified (`+89/-40` lines, CRLF warning). Updates `.trellis/config.yaml` hash, drops `.trellis/workflow.md` hash, updates 19 `.trellis/scripts/common/__pycache__/*.cpython-311.pyc` hashes, and adds **46** `.agent/**` template hashes. |
| `.trellis/workflow.md` | ` M` | Modified (`+117/-40` lines). Separates `[Antigravity]` out of `[codex-inline, Kilo, ...]` into dedicated `[workflow-state:*-antigravity]` blocks and `[Antigravity]` Phase 1.3/1.4/2.1/2.2 Swarm/Subagent/Inline choreography (`no_task-antigravity`, `planning-antigravity`, `in_progress-antigravity`). |
| `AGENTS.md` | ` M` | Modified (`+7/-0` lines, CRLF warning). Appends `## Trellis + Antigravity 协同规范 (Workflow & Subagents)` (`L442-447`). |
| `.agent/` | `??` | Untracked directory (**56 files**, 12 skills, `hooks.json`, `hooks/trellis_agy_hook.py`, `plugins/trellis-agy/**`, `workflows/*.md`, `.agent/.gitignore`). Generated on `2026-11-17 16:03` for Antigravity Trellis integration. |
| `.trellis/tasks/11-17-repo-refactor-git-hygiene/` | `??` | **Current task** created on `2026-11-17 16:09` (`prd.md`, `task.json`, `implement.jsonl`, `check.jsonl`, plus `research/*.md`). |

### 1.2 Ignored & Stray Local Artifacts (`git status --ignored -s`)

- `%SystemDrive%/` (`!!` because all 4 files inside are `*.db` matched by `.gitignore:23`): contains `ProgramData/Microsoft/Windows/Caches/{45F7E5DD-...,6AF0698E-...,DDF571F2-...}.db` and `cversions.2.db` (~990 KB total). Created literally as `%SystemDrive%` at repo root by a Windows/WSL tool failing to expand the env var.
- `.pi/` (4 files, ignored via `.gitignore:32`): local goal-ledger state (`.pi/goals/archived/goal_2026102702521215_mvplqnbj-8xe28x.md`, etc.).
- `delivery_lab5_6/` (17 files, ignored via `.gitignore:35`): local lab 5/6 markdown/docx/screenshot outputs and `build_docx.py`.
- `backend/.coverage` (1.05 MB), `backend/zhilian_dev.db` (557 KB), `backend/.env`, `backend/.venv/`, `backend/.*_cache/`, `miniprogram/dist/`, `.opencode/node_modules/` (3,667 files), `.pytest_cache/`, `.ruff_cache/`: standard ignored local runtime/build artifacts.

### 1.3 Worktrees, Stashes & Tags

- **Worktrees (`git worktree list --porcelain`)**: **2** entries:
  1. `D:/code/Workspace/zhilian` — `HEAD d223cb59ba341dd17c051d3f277c4c4b8dc3ae0f` (`refs/heads/chore/workspace-configs`)
  2. `D:/code/Workspace/zhilian/.worktrees/frontend-vertical-slices` — `HEAD 51604a4414b92727b5d29fa56d5d294b095c68b8` (`refs/heads/codex/frontend-vertical-slices`). Status inside this worktree is clean (0 modified/untracked files), 1,052 files on disk.
- **Stashes (`git stash list`)**: Empty (`0` stashes).
- **Tags (`git tag -l`)**: **2** tags:
  1. `backup/session-2026-09-28-before-trellis` -> `cf848f5` (2026-09-28, reachable from `master`)
  2. `midterm-baseline-2026-10-04` -> `3e16826` (2026-10-04, reachable **ONLY from `remotes/origin/dev`**, NOT on `master`!).

---

## 2. Complete Git Branch Inventory & Classification

**Trunk reference**: `master` (`0c301fa`, 2026-10-03, `Merge pull request #7 from coding-leaf/dev`). `origin/HEAD -> origin/master`.  
**Tracking note**: `git branch -vv` currently shows **no `[gone]` upstreams** because none of the pushed `origin/*` branches have been pruned/deleted on GitHub yet. Three local branches (`codex/frontend-ui-loop-repair`, `codex/frontend-vertical-slices`, `worktree-agent-a2180bf64392d93fc`) have no `remote`/`merge` tracking ref (only `.vscode-merge-base=origin/master` in `.git/config`).  
**Squash-merge verification**: Every non-ancestor branch (`origin/dev`, `chore/workspace-configs`, `origin/chore/workspace-configs`, `codex/frontend-vertical-slices`) was tested with `git cherry master <branch>` AND `git ls-tree` / `git diff` against `master`; **none** are squash-merged (`git cherry` reports `+` for all unique commits).

| Branch | Scope | Tip Hash & Date | Author | Ahead / Behind `master` | Ancestor of `master`? | `git cherry` vs `master` (`+` unlanded / `-` equiv) | Unique Unlanded Work Summary | Recommended Action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `master` | Local | `0c301fa` (2026-10-03) | 夏空 | `0 / 0` | Yes (Trunk) | `0 / 0` | Trunk (`Merge PR #7 from coding-leaf/dev`). | **Keep** |
| `origin/master` | Remote | `0c301fa` (2026-10-03) | 夏空 | `0 / 0` | Yes (Trunk) | `0 / 0` | Remote trunk; matches local `master`. | **Keep** |
| `origin/dev` | Remote | `10bdd91` (2026-10-04) | hennessy9684 | `+22 / -0` (21 non-merge commits) | **No** | `21 / 0` | `af1df09` (`diff-cover` + T0 coverage gates in `Taskfile.yml` & `verify.yml`), `fe7c6e1` (`pyjwt` 2.15.1 security fix), `3331ccf`/`f6826fc` (BUG-01/02/03 fixes in `errors.py` & `practice.py`), 9 new backend test files (`91%->93%`), 4 `docs/*规范.md`, `中期质量检查/` updates, tag `midterm-baseline-2026-10-04` (`3e16826`). Overlaps with `chore/workspace-configs` on 19 files (`.gitignore`, `10-03-midterm-*`, `.trellis/workspace/lls/*`). | **Merge/Salvage** (land into `master` via PR or cherry-pick/merge, then delete `dev`) |
| `chore/workspace-configs` | Local (HEAD) | `d223cb5` (2026-10-27) | coding-leaf | `+3 / -0` (`+2` vs `origin/chore/workspace-configs`) | **No** | `3 / 0` | 3 commits: (1) `02c0840` adds `.claude/` (53 files), `opencode.json`, `.gitignore` (`.pi/`, `.worktrees/`), archives 7 tasks, updates `lls` journal; (2) `5f9fa5f` **P1-4 feature/fix** `fix(profile)` (24 files, +890/-76 lines across backend materials API/repo/schema/service, miniprogram profile card/composable/API/types, tests, `.trellis/spec/backend/material-statistics.md`); (3) `d223cb5` ignores `delivery_lab5_6/`. Plus 4 uncommitted dirty paths (`.agent/`, `AGENTS.md`, `workflow.md`, `.template-hashes.json`). | **Merge/Salvage** (split `5f9fa5f` P1-4 fix & workspace/Antigravity config cleanup onto clean PRs after `origin/dev` reconciliation, then `Delete`) |
| `origin/chore/workspace-configs` | Remote | `02c0840` (2026-10-03) | coding-leaf | `+1 / -0` | **No** | `1 / 0` | Contains `02c0840` only (`.claude/`, `opencode.json`, `.gitignore`, 7 archived tasks, `lls` journal). Overlaps 19 paths with `origin/dev`. | **Merge/Salvage** (reconcile `02c0840` with `origin/dev`, then `Delete`) |
| `codex/frontend-vertical-slices` | Local (Worktree) | `51604a4` (2026-09-28) | coding-leaf | `+1 / -77` | **No** | `1 / 0` | 1 doc/planning commit (`+287` lines): `docs/user-journey-slices.md` (121 lines, J1-J8 vertical slices), `miniprogram/src/modules/learning-journey/README.md` (15 lines), `.trellis/spec/frontend/directory-structure.md` (+5 lines), `.trellis/tasks/09-28-frontend-vertical-slices/` (7 files). Verified absent from `master` & `origin/dev`. | **Archive-Tag & Delete** (or cherry-pick `docs/user-journey-slices.md` if still desired, remove worktree `.worktrees/frontend-vertical-slices`, then `Delete`) |
| `worktree-agent-a2180bf64392d93fc` | Local | `53c7d30` (2026-09-28) | coding-leaf | `0 / -77` | **Yes** | `0 / 0` | None (`53c7d30` is ancestor of `master`). Leftover agent worktree branch. | **Delete** |
| `codex/frontend-ui-loop-repair` | Local | `90eed7f` (2026-09-29) | coding-leaf | `0 / -64` | **Yes** | `0 / 0` | None (`90eed7f` is ancestor of `master`). | **Delete** |
| `feat/question-bank-tab` | Local | `98eb87d` (2026-09-29) | coding-leaf | `0 / -19` | **Yes** | `0 / 0` | None (landed in `master`). | **Delete** |
| `origin/feat/question-bank-tab` | Remote | `98eb87d` (2026-09-29) | coding-leaf | `0 / -19` | **Yes** | `0 / 0` | None (landed in `master`). | **Delete** |
| `feat/material-delete-entry` | Local | `e1d7710` (2026-09-29) | coding-leaf | `0 / -18` | **Yes** | `0 / 0` | None (landed in `master`). | **Delete** |
| `origin/feat/material-delete-entry` | Remote | `e1d7710` (2026-09-29) | coding-leaf | `0 / -18` | **Yes** | `0 / 0` | None (landed in `master`). | **Delete** |
| `feature/ZL-143-lab3-delivery` | Local | `31e9b71` (2026-09-29) | coding-leaf | `0 / -14` | **Yes** | `0 / 0` | None (merged via PR #1 `623d00f`). | **Delete** |
| `origin/feature/ZL-143-lab3-delivery` | Remote | `31e9b71` (2026-09-29) | coding-leaf | `0 / -14` | **Yes** | `0 / 0` | None (merged via PR #1 `623d00f`). | **Delete** |
| `feature/ZL-143-branch-protection-note` | Local | `5b231e4` (2026-09-29) | coding-leaf | `0 / -12` | **Yes** | `0 / 0` | None (merged via PR #2 `0ad0b40`). | **Delete** |
| `origin/feature/ZL-143-branch-protection-note` | Remote | `5b231e4` (2026-09-29) | coding-leaf | `0 / -12` | **Yes** | `0 / 0` | None (merged via PR #2 `0ad0b40`). | **Delete** |
| `feature/ZL-143-lab3-screenshots` | Local | `5cd6926` (2026-09-29) | coding-leaf | `0 / -10` | **Yes** | `0 / 0` | None (merged via PR #3 `43b5085`). | **Delete** |
| `origin/feature/ZL-143-lab3-screenshots` | Remote | `5cd6926` (2026-09-29) | coding-leaf | `0 / -10` | **Yes** | `0 / 0` | None (merged via PR #3 `43b5085`). | **Delete** |
| `feature/ZL-143-sync-task-status` | Local | `893b29e` (2026-09-29) | coding-leaf | `0 / -8` | **Yes** | `0 / 0` | None (merged via PR #4 `bc2abab`). | **Delete** |
| `origin/feature/ZL-143-sync-task-status` | Remote | `893b29e` (2026-09-29) | coding-leaf | `0 / -8` | **Yes** | `0 / 0` | None (merged via PR #4 `bc2abab`). | **Delete** |
| `feature/ZL-144-question-bank-autoload` | Local | `1e5811b` (2026-09-29) | coding-leaf | `0 / -6` | **Yes** | `0 / 0` | None (merged via PR #5 `e1cef6d`). | **Delete** |
| `origin/feature/ZL-144-question-bank-autoload` | Remote | `1e5811b` (2026-09-29) | coding-leaf | `0 / -6` | **Yes** | `0 / 0` | None (merged via PR #5 `e1cef6d`). | **Delete** |
| `feature/ZL-145-record-findings` | Local | `4ad70bc` (2026-09-29) | coding-leaf | `0 / -4` | **Yes** | `0 / 0` | None (merged via PR #6 `3392409`). | **Delete** |
| `origin/feature/ZL-145-record-findings` | Remote | `4ad70bc` (2026-09-29) | coding-leaf | `0 / -4` | **Yes** | `0 / 0` | None (merged via PR #6 `3392409`). | **Delete** |

---

## 3. Workspace & Root Config Hygiene Findings

### P0 — Critical Divergence & Mixed-Concern Commits

1. **Two unmerged branches (`origin/dev` and `chore/workspace-configs`) have diverged from `master` with 19 overlapping paths**
   - Evidence: `git rev-list --left-right --count master...origin/dev` (`0 / 22`), `git rev-list --left-right --count master...chore/workspace-configs` (`0 / 3`).
   - Both `origin/dev` (`d3ca63c`, `1c86cc2`, `c53626f`, `af1df09`) and `chore/workspace-configs` (`02c0840`) independently modified `.gitignore`, `.trellis/workspace/lls/index.md`, `.trellis/workspace/lls/journal-1.md`, and archived `.trellis/tasks/archive/2026-10/10-03-midterm-{ci-baseline,quality-prep}/task.json` with conflicting `"branch": "dev"` vs `"branch": "master"` and conflicting `lls/journal-1.md` Session 1 entries!
   - Meanwhile, `origin/dev` holds critical bugfixes (`BUG-01/02/03`), `pyjwt 2.15.1` security patch, `diff-cover` CI gates, and tag `midterm-baseline-2026-10-04` (`3e16826`), while `chore/workspace-configs` holds P1-4 `fix(profile)` (`5f9fa5f`, unpushed) and workspace/Antigravity config changes.

2. **Feature/bugfix code (`5f9fa5f`) committed onto a `chore/*` branch and left unpushed locally**
   - Evidence: Commit `5f9fa5f` on `chore/workspace-configs` (`2026-10-27`) modifies 24 files (+890/-76 lines) across `backend/app/api/v1/materials.py`, `backend/app/repositories/material.py`, `backend/app/schemas/material.py`, `backend/app/services/material.py`, `miniprogram/src/pages/profile/**`, `.trellis/spec/backend/material-statistics.md`, and unit tests. It was never pushed (`origin/chore/workspace-configs` is stuck at `02c0840`), creating risk of silent loss or accidental discard during branch cleanup.

### P1 — Multi-Platform AI Config Bloat, Stale Tasks & Tooling Drift

3. **6 Coexisting AI Agent Config Directories & 3,667 `node_modules` Files in `.opencode/`**
   - Evidence: Repo root contains `.agent/` (56 files, 12 skills, untracked), `.agents/` (46 files, 12 skills, tracked), `.claude/` (53 tracked files + 1 gitignored `settings.local.json`, 9 skills, tracked only on `chore/workspace-configs`), `.codex/` (8 files, tracked), `.opencode/` (55 tracked files + 3 untracked npm files + **3,667 files** inside `.opencode/node_modules/`), and `.pi/` (4 files, gitignored).
   - Impact: Duplicates `trellis-*` skills/references across 4 directories (`.agent`, `.agents`, `.claude`, `.opencode`), bloats filesystem searches/IDE indexing, and `.trellis/.template-hashes.json` currently tracks `.opencode` (56 entries), `.trellis` (50), `.agents` (46), `.agent` (46), `.codex` (8), `AGENTS.md` (1) — **including 19 `.trellis/scripts/common/__pycache__/*.cpython-311.pyc` binary hash entries**!

4. **9 Unarchived / Stale Task Directories Under `.trellis/tasks/`**
   - Evidence: `.trellis/tasks/` contains 9 `09-29-*` directories alongside `11-17-repo-refactor-git-hygiene`:
     - `09-29-fix-learning-stats`: `task.json` has `"status": "completed"`, `"completedAt": "2026-10-04"`, `"branch": "chore/workspace-configs"`, yet was never archived into `.trellis/tasks/archive/2026-10/`.
     - `09-29-fix-llm-thinking-mode` (`status: "planning"`) & `09-29-material-delete-entry` (`status: "planning"`): Code already landed on `master` (`d0e759b` and `e1d7710`), tasks never updated/archived.
     - `09-29-question-bank-page` & `09-29-manual-wrong-mark` (`status: "in_progress"`): Delivered on `feat/question-bank-tab` (`74220aa`, `7ceef10`) and merged into `master`; parent `09-29-question-bank-tab` notes milestone partial completion (`status: "planning"`).
     - `09-29-field-test-fix-batch-1` (parent), `09-29-fix-parse-stuck`, `09-29-fix-qgen-feedback`: still open in `planning`.

5. **WSL-Only Script & Documentation Contradictions (`sync_to_host.sh` vs `AGENTS.md`)**
   - Evidence: Root `sync_to_host.sh` (`L1-9`) uses `#!/usr/bin/env bash` and `/mnt/d/zhilian-mp` (WSL mount path), directly contradicting `AGENTS.md` (`L47-51`: "不要经由 WSL / Linux 容器跑后端或前端命令").
   - `.github/CODEOWNERS` (`L12`) and `docs/团队分工.md` (`L67`) reference `.pre-commit-config.yaml`, which does not exist in the repo. `.editorconfig` and `.vscode/` are also absent, while `git diff` warns `CRLF will be replaced by LF` on `.trellis/.template-hashes.json` and `AGENTS.md` despite `.gitattributes` specifying `* text=auto eol=lf`.

6. **Stray `%SystemDrive%/` Directory, Empty `backend/.trellis/`, and Orphan Linked Worktree**
   - Evidence: `d:\code\Workspace\zhilian\%SystemDrive%\ProgramData\Microsoft\Windows\Caches\*.db` (~990 KB) sits at repo root (masked from `git status` only by `.gitignore:23` `*.db`).
   - `d:\code\Workspace\zhilian\backend\.trellis\tasks\09-27-read-only-bug-audit\research` is a completely empty nested directory (0 files) left behind when `trellis` was mistakenly invoked with `cwd=backend/`.
   - `.worktrees/frontend-vertical-slices` (1,052 files) is pinned to stale branch `codex/frontend-vertical-slices` (`51604a4`, 77 commits behind `master`).

### P2 — Minor Root Clutter & Config Debt

7. **Root & Docs Organizational Sprawl**
   - Root contains `opencode.json`, `sonar-project.properties` (with placeholder `ORGANIZATION-KEY` / `PROJECT-KEY` while `.github/workflows/verify.yml` skips Sonar when `SONAR_TOKEN` is unset), and Chinese-named folder `中期质量检查/` (11 tracked files) separate from `docs/` (146 tracked files, of which 127 are in `docs/legacy_sdlc/`).
   - `.gitattributes` (`L23`) and `.trellis/workflow.md` (`L144`) contain upstream Trellis template links to `.trellis/spec/cli/backend/*`, which does not exist in this repository.
   - `docs/开发过程文档.md` (`L245`, `L262`) documents `master` single-trunk + `feature/ZL-<id>-<slug>` + merge commits, yet `origin/dev` was subsequently created and used for midterm quality work without closing the loop back to `master`.

---

## 4. Proposed Git Branch & Workspace Governance Specification

### 4.1 Branching Model & Naming Convention

- **Single Trunk**: `master` is the **sole long-lived integration & protected branch** (retire `dev` after merging `origin/dev` into `master`; aligns with `docs/开发过程文档.md` §6 and `.github/workflows/verify.yml` which only triggers on `master`).
- **Short-Lived Task Branches**: All non-trivial work branches off latest `origin/master` and merges back via GitHub PR with **required `verify` status checks** + **auto-delete branch on merge**:
  - Format: `<type>/<scope-or-id>-<short-kebab-desc>`
  - Allowed `<type>`: `feat/` (new feature), `fix/` (bug fix), `refactor/` (restructure/cleanup), `chore/` (tooling/workspace/deps), `docs/` (documentation/specs only).
  - **Strict One-Branch-One-Purpose Rule**: Never commit `feat/` or `fix/` code onto a `chore/` or `docs/` branch (prevents incidents like `5f9fa5f` on `chore/workspace-configs`).
- **Prohibited Branch Prefixes**: Do not create `codex/*` or lingering `worktree-agent-*` branches; AI tool sessions must either work on the user's active task branch or clean up temporary Swarm/worktree branches before task completion.

### 4.2 Worktree & Antigravity Swarm `share` Lifecycle Rules

1. **Worktree Location**: All manual git worktrees live exclusively under `.worktrees/<branch-slug>/` (gitignored via `.gitignore:67`). Never invoke `trellis` CLI inside `backend/` or `miniprogram/` (always run from repo root so `backend/.trellis/` cannot be recreated).
2. **Swarm `workspace:"share"` / `"branch"` Discipline**:
   - Authors in parallel Swarm waves work in isolated `share` workspaces.
   - **Pre-Kill Landing Gate**: Before calling `swarm{action:"kill", name}`, the Coordinator MUST land verified diffs into the main workspace (via `git merge --squash <worker-branch>` + `git reset HEAD`, or `git show -p --format= <commit> | git apply` for stacked milestones) and delete any temporary `refs/swarm-opt/*` refs.
   - **Zero-Orphan Policy**: No `worktree-agent-*` branches or `.worktrees/*` directories may remain after `task.py archive`.

### 4.3 Immediate Branch & Workspace Cleanup SOP (Execution Order for Phase 2)

1. **Backup Tagging**: Create an archive tag `archive/codex-frontend-vertical-slices` on `51604a4` (or salvage `docs/user-journey-slices.md` if desired), then run `git worktree remove .worktrees/frontend-vertical-slices`.
2. **Reconcile & Land Diverged Branches**:
   - Land `origin/dev` (`10bdd91`) into `master` (or a dedicated integration branch off `master`) FIRST, resolving `中期质量检查/` + `Taskfile.yml` (`diff-cover`) + `BUG-01/02/03` + `pyjwt`.
   - Cherry-pick/extract `5f9fa5f` (`fix(profile)` P1-4) onto a clean `fix/profile-learning-stats` branch rebased on the new trunk, and run `task verify`.
   - Land cleaned workspace/Antigravity config changes (`02c0840` minus conflicting `10-03-midterm-*` overwrites, plus `d223cb5` + `.agent/` + `AGENTS.md` + `.trellis/workflow.md`) on a clean `chore/workspace-hygiene` branch.
3. **Prune Merged Branches**: Delete all **10** ancestor-merged local branches (`git branch -d ...`) and **8** ancestor-merged remote branches (`git push origin --delete ...`), then `git fetch --prune`. After `origin/dev` and `chore/workspace-configs` land, delete them locally and on `origin` as well.
4. **Workspace Filesystem Cleanup**:
   - Remove literal `%SystemDrive%/` directory and empty `backend/.trellis/` directory.
   - Decide & standardize active AI platform directories (keep `.agent/` + `.agents/` + `.trellis/` for Antigravity/Codex; evaluate removing unused `.claude/`, `.opencode/` + `opencode.json` + `.opencode/node_modules/`, or explicitly document supported platforms and exclude `.opencode/node_modules/`).
   - Replace/remove WSL-only `sync_to_host.sh` with a Windows `pwsh` script or `Taskfile.yml` task.
   - Add `.editorconfig` enforcing `lf` line endings (`end_of_line = lf`) to eliminate CRLF/LF git diff noise.
   - Archive already-landed `09-29-*` tasks (`09-29-fix-learning-stats`, `09-29-fix-llm-thinking-mode`, `09-29-material-delete-entry`, `09-29-question-bank-page`, `09-29-manual-wrong-mark`) after verifying their code status.

### 4.4 Pre-Work & Finish-Work Checklist (Tailored to Trellis + Antigravity)

- **Pre-Work (Phase 1)**:
  - Run `git status --short` and `git branch -vv` from **repo root** (`d:\code\Workspace\zhilian`).
  - Ensure `HEAD` is on a clean, purpose-matched branch off latest `master` (never start new feature work on `chore/*` or dirty workspace).
  - Keep `.trellis/tasks/<task>/` artifacts (`prd.md`, `design.md`, `implement.md`, `implement.jsonl`, `check.jsonl`) curated before `task.py start`.
- **Finish-Work (Phase 3)**:
  - Run `task verify` (`verify-backend` + `verify-frontend`) directly in Windows `pwsh` (`$env:PYTHONIOENCODING='utf-8'`; never WSL).
  - Verify `git worktree list` shows only the primary repo root and `git branch` has no orphan worker branches.
  - Run `trellis-update-spec` if conventions changed, commit via Phase 3.4 batched review, then run `/trellis-finish-work` (`task.py archive` + `add_session.py`) so no completed task stays unarchived in `.trellis/tasks/`.

---

## Discovered `.trellis/spec/` Paths (For `implement.jsonl` / `check.jsonl`)

- `D:/code/Workspace/zhilian/.trellis/spec/guides/index.md`
- `D:/code/Workspace/zhilian/.trellis/spec/guides/code-reuse-thinking-guide.md`
- `D:/code/Workspace/zhilian/.trellis/spec/guides/cross-layer-thinking-guide.md`
- `D:/code/Workspace/zhilian/.trellis/spec/backend/index.md`
- `D:/code/Workspace/zhilian/.trellis/spec/backend/material-statistics.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/index.md`
- `D:/code/Workspace/zhilian/.trellis/spec/frontend/directory-structure.md`
- `D:/code/Workspace/zhilian/.trellis/workflow.md`
