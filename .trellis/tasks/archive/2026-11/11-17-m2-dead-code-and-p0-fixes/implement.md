# Implementation Plan — M2: 废代码废依赖清退与跨层P0快修

## 1. Execution Steps

1. **Step 0（Coordinator）**：在 `M1` 通过 `task verify` 后，创建包含当前工作树完整状态的临时快照引用 `refs/swarm-opt/m1-base`，激活任务 `task.py start .trellis/tasks/11-17-m2-dead-code-and-p0-fixes`。
2. **Step 1A（`be-hygiene`，`High`，`workspace: "share"`）**：
   - `git reset --hard refs/swarm-opt/m1-base`；
   - 修复 `pyproject.toml`（`httpx` 移入 `dependencies`，移除直接 `langchain-core` 依赖及 `agent_graph.py` 未使用 `RunnableConfig`）；
   - 实现 `api/deps/_factory.py` 重构 7 个 `deps/*.py` 并修正 `deps/__init__.py`（兼容 `test_deps_supplemental.py`）；
   - 修复 `KnowledgeService._extract_batch_points` 双重 LangGraph 调用并统一 `QuestionService` 走 `self.llm.generate_structured`；
   - 修复 `tests/unit/cli/test_doctor.py` 中对本地 `.env` `ZHILIAN_STORAGE__ENDPOINT_URL` / `ZHILIAN_REDIS__REDIS_URL` 未隔离导致 `task verify` 卡死的问题；
   - 确保 `PracticeService.create_practice` 与 `get_practice` 均完整附带 `source_snippet`；
   - 清理 `GET /api/v1/mastery/overview` 及已核实 `app=0` 的死异常类、Service/Container/Schema/Repo 死别名，同步清理对应死单测；
   - 跑通后端全套门禁（`ruff format/check`、`mypy app`、`lint-imports`、`pytest --cov=app --cov-branch --cov-fail-under=80`）。
3. **Step 1B（`fe-hygiene`，`High`，`workspace: "share"`，与 1A 并行）**：
   - `git reset --hard refs/swarm-opt/m1-base`；
   - 核实后端 `page_index` 0/1-based 语义，对齐 `types/index.ts` 与 `course/index.vue` 切片页码/章节展示并补 Vitest 测试；
   - 移除 `package.json` 7 个无用包并更新 `pnpm-lock.yaml`，删除 `pages.json` 的 `wd-*` `easycom` 与 `upload/index` 页面及 `upload/index.vue`；
   - 封装 `apiUploadAvatar` + `authStore.updateAvatar` 改造 `profile/index.vue`；优化 `apiCreatePractice` 单次往返，收紧 `CreatePracticeParams.title` 与 `MAX_PRACTICE_QUESTIONS = 50`；
   - 清理无消费 Store 成员、死 API/Composable/类型/视图辅助导出，复用 `optionDisplayText`；
   - 跑通前端全套门禁（`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit`）。
4. **Step 2（`verifier-m2`，`High`）**：双轨独立审查后唤醒 `@coordinator`。
5. **Step 3（Coordinator）**：合入主工作区（保持未提交）、固定 `refs/swarm-opt/m2-base`、销毁临时 worker，无缝衔接 `M3`。

## 2. Validation Commands

```powershell
$env:PYTHONIOENCODING = 'utf-8'
task verify
```
