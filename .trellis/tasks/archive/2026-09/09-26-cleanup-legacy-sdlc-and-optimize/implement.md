# 清理旧框架残留与工作区代码质量优化 - 执行方案 (implement.md)

## Ordered Checklist

- [ ] **Step 1: 清理根目录旧自研入口与冲突文件**
  - 删除根目录下容易与 Trellis 冲突的 `task.py`。
  - 检查根目录下是否有其它临时脚本（如 `sync_to_host.sh`，核实用途并决定保留或清理）。
  - *验证命令*：`Test-Path task.py` 返回 `False`。

- [ ] **Step 2: 完善 .gitignore 规则**
  - 检查并更新 `.gitignore`，确保添加：
    - `*.db`, `*.sqlite3`
    - `.coverage`, `htmlcov/`
    - `.ruff_cache/`, `.mypy_cache/`, `.pytest_cache/`, `.import_linter_cache/`
  - 验证 `git status`，确保上述本地临时文件不再显示为未跟踪或脏文件。

- [ ] **Step 3: 整理 Git 暂存区与删除旧 SDLC 残留文件**
  - 暂存并确认删除旧自研脚本与对应测试：
    - `tooling/` 下的旧 SDLC 脚本
    - `tests/` 下的旧 SDLC 脚本单测
    - `.agents/skills/` 下旧技能
    - `.opencode/agent/` 和 `.opencode/commands/` 下旧配置
  - 确认 `docs/legacy_sdlc/` 归档文件状态正常。

- [ ] **Step 4: 全量质量门禁基线复验 (Baseline Verification)**
  - 后端门禁：
    ```bash
    cd backend
    uv run ruff format --check .
    uv run ruff check .
    uv run mypy app
    uv run pytest tests
    ```
  - 前端门禁：
    ```bash
    cd miniprogram
    pnpm run lint
    pnpm run type-check
    pnpm run test:unit
    ```

- [ ] **Step 5: 提交前审查与 Spec 反哺更新**
  - 检查 `git status`，确认仅保留必要的新增、修改与已删除项。
  - 使用 `trellis-update-spec` 或记录开发日志，明确工作区命令标准。

## Rollback Points

- 若发现删除了误判的必要工具，可通过 `git checkout HEAD -- <path>` 随时恢复对应文件。
