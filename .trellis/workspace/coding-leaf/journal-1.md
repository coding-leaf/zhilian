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

---

## 2026-09-26 - 资料列表为空/解析进度/鉴权画像修复 (fix-material-and-auth)

- **背景**: 用户实机反馈三大端到端缺陷——「全部」标签返回空、上传后解析无进度提示、怀疑登录授权丢态。
- **根因**:
  - 列表页在 `all` 标签传 `status=undefined`，后端 `Material.status == status` 恒假导致空结果；`ready` 因精确匹配才可见。
  - 列表页与首页共享 Store，分页结果全量覆盖首页概览切片；且只在 `onMounted` 加载，二级返回白屏。
  - 冷启动只恢复 `auth_tokens`，`profile` 受 3-key 白名单限制未持久化，导致「已登录却显示未登录」假象。
- **实现**:
  - 前后端双向清洗空状态参数；Service 统一状态语义（`parsing`→`pending+parsing`、`ready/completed`→`ready`、`retake_required`→空）。
  - 响应新增 `parse_status`/`progress_percentage`；卡片展示进度并提供手动【开始解析/重新解析】按钮 + 自适应退避轮询。
  - `userStore.hydrateProfile()` 在 `onLaunch`/`onShow`/登录后静默水合画像；列表页 `listData` 与全局 Store 隔离，`onShow` 保活。
  - 修复质检阶段发现的 N+1：`selectinload(Material.versions)` 批量预加载，列表版本查询 O(N)→固定 1 次（实测 3 条 SQL）。
- **遗留（新任务范围）**: 「待重拍」Tab 恒空——后端 `MaterialStatus` 无 `retake_required` 状态，需模型层改造才能真正支持。
- **验证成果**:
  - 后端 `ruff`/`format`/`mypy`(109 files)/`lint-imports`(5 kept)/`pytest`（1090 passed）。
  - 前端 `lint`/`type-check` 全绿、`vitest`（52 files / 424 passed）。
  - 提交 `86bc24e`；规范沉淀《Material Status Filter & Parse Progress Contract》写入前端 quality-guidelines。


