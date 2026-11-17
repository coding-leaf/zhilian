# M2: 废代码废依赖清退与跨层P0快修

## Goal

在 `M1` 单主干治理基线上，通过前后端双轨隔离工作树（`workspace: "share"`）并行消除全部已核实的死依赖、死页面、零调用兼容别名与隐藏重复路由，并一次性修复跨层原文切片页码静默失配（P0）、后端生产依赖错置（P0）、DI Session 泄漏（P0）及 LangGraph 双重调用（P0）。

## Background & Verified Evidence

依据父任务 `research/02`、`03`、`04` 核实：
- **后端 P0 隐患与死资产（`02`）**：
  - `backend/pyproject.toml:34-36` 将 5 处生产代码导入的 `httpx` 错放在 `dev` 可选依赖；`agent_graph.py:15` 未使用的 `langchain-core` `RunnableConfig` 可直接移除；
  - 7 个 `backend/app/api/deps/{diagnosis,folder,grading,knowledge,material,practice,question}.py` 重复 54 行模板且 fallback 分支 `container.session_factory()` 未关闭造成连接泄漏，`api/deps/__init__.py:14` 从 `knowledge` 错导 `get_db_session`；
  - `backend/app/services/knowledge.py:373-388` 在 `run_structured_agent_workflow` 抛错时二次调用 `self.llm.generate_structured`（重复执行同一 LangGraph），`question.py:876-881` 绕过 `LLMProtocol.generate_structured`；
  - 确认零业务调用（`app=0`）的符号：隐藏重复路由 `GET /api/v1/mastery/overview`（`api/v1/diagnosis.py:202-208`）、3 个异常类（`MaterialParseError`、`KnowledgePointQualityError`、`QuestionQualityCheckError`）、Service 别名/未使用方法（`AuthService.revoke_user_tokens/delete_user_account/user_repository`、`KnowledgeService.get_knowledge_point/get_snippets_by_point/get_points_by_snippet`、`PracticeService.timeout_practice`、`QuestionService.get_question_detail`、`materials.py:191 run_parse_material_background`、`MasteryRecordList` 字典下标兼容垫片）、`AppContainer` 的 `registry` 与 9 个 `get_*_service` 别名、`AttemptItemDetailResponse` 别名及 20+ 个 `app=0` 的 Repository 重复别名方法。
- **跨层与前端 P0/P1 缺陷及死资产（`03`、`04`）**：
  - **P0 原文切片页码静默 Bug**：`miniprogram/src/types/index.ts:109-150` 与 `miniprogram/src/subpackages/material/pages/course/index.vue:73,132-133` 读取不存在的 `page_number`/`similarity`/`key_phrases`，后端 `SnippetSourceResponse`（`schemas/knowledge.py:66-78`）实返 `page_index`、`chapter_title`、`is_low_confidence`；
  - `miniprogram/package.json` 含 7 个零引用依赖（`wot-design-uni` + `pages.json:4-6` `easycom`、`unocss`、`@unocss/vite`、`@unocss/preset-uno`、`prettier`、`eslint-plugin-prettier`、`eslint-config-prettier`）；
  - 死页面 `miniprogram/src/subpackages/material/pages/upload/index.vue`（及 `pages.json:61-66` 路由注册）；
  - 11 个零外部消费 Store 成员（`practiceStore.{latestDiagnosis,askCoach,flushDrafts,retryDraft}`、`materialStore.{isUploading,questions,generateQuestions,currentKnowledgeTree,activeSnippets}`、`folderStore.{currentFolderKnowledgePoints,isLoading}`）、`useQuestionCompose.restoreQuestion`、`apiGetDiagnosisReport`、字符串重载分支，以及 `ApiResponse`、`AnswerPayload`、`wrongSnapshotOptions`、`groupCounts`、`resolveGradingStatusText`、`isSelectableForRegrade` 等死导出；
  - `profile/index.vue:89,136` 直调底层 `uploadFile` 并直接覆写 `authStore.user`；`apiCreatePractice`（`api/index.ts:366-375`）丢弃 `POST /practices` 完整响应再多余请求一次 `GET /practices/{id}`；`CreatePracticeParams.title` 可选与后端必填失配，`stores/practice.ts:233` 与 `questions/index.vue:286` 未显式传 `question_count` / 50 题上限保护。

## Requirements

- **R1 — 后端 P0 修复与依赖修正（Track `be-hygiene`）**：
  - 将 `httpx>=0.27.0` 移至 `backend/pyproject.toml` 的 `[project].dependencies`，移除 `agent_graph.py` 未使用的 `langchain-core` `RunnableConfig` 导入与 `pyproject.toml` 直接声明（保留 `bandit`/`pip-audit` 手工安全工具）。
  - 新建 `backend/app/api/deps/_factory.py` 统一使用 `with container.get_session()` 管理 fallback Session，重构 7 个 `api/deps/*.py` 消除泄漏与重复，修正 `api/deps/__init__.py` 从 `app.api.deps.db` 导出 `get_db_session`。
  - 移除 `KnowledgeService._extract_batch_points` 的重复 LangGraph fallback 分支，并将 `KnowledgeService` 与 `QuestionService.generate_questions` 统一收敛到 `self.llm.generate_structured(...)`。
  - 修复 `backend/tests/unit/cli/test_doctor.py`（及 `tests/conftest.py` 环境隔离）：在离线单测中显式隔离 `ZHILIAN_STORAGE__ENDPOINT_URL` 与 `ZHILIAN_REDIS__REDIS_URL`，杜绝本地存在 `backend/.env` 时触发真实 `boto3`/TCP 超时卡死 `task verify`。
- **R2 — 后端零调用符号与重复路由清退（Track `be-hygiene`）**：
  - 删除隐藏重复路由 `GET /api/v1/mastery/overview`（**严格保留其余 25 个后端业务扩展路由**）。
  - 删除已确认 `app=0` 的 3 个异常类、Service/Container/Schema 兼容别名及 Repository 重复别名方法，并同步更新或移除仅测试已删除死别名的冗余单测断言。
- **R3 — 前端跨层 P0 修复与接口契约收敛（Track `fe-hygiene`）**：
  - 对齐 `KnowledgeSnippet` / `KnowledgeTreeNode` / `KnowledgePointDetail`（`src/types/index.ts`）与 `course/index.vue` 模板至后端真实字段（`page_index`、`chapter_title`、`is_low_confidence`），移除死分支 `key_phrases` / `similarity`，并补充适配器/组件单测验证真实页码渲染。
  - 在 `src/api/index.ts` 新增 `apiUploadAvatar` 并在 `authStore` 封装 `updateAvatar`，消除 `profile/index.vue` 对 `utils/request` 的越层直调。
  - 优化 `apiCreatePractice` 直接复用 `POST /practices` 返回的详情（确认 `create_practice` 与 `get_practice` 均补齐 `source_snippet`，若后端 `create_practice` 缺 `source_snippet` 则在 `be-hygiene` 同步对齐或保留安全兜底）；将 `CreatePracticeParams.title` 收紧为必填并在所有 `question_ids` 调用点统一 `MAX_PRACTICE_QUESTIONS = 50` 截断与显式 `question_count`。
- **R4 — 前端死依赖、死页面与死导出清退（Track `fe-hygiene`）**：
  - 从 `miniprogram/package.json` 移除 7 个零引用包并更新 `pnpm-lock.yaml`，删除 `pages.json` 中 `wot-design-uni` `easycom` 规则与 `upload/index` 页面注册，删除 `src/subpackages/material/pages/upload/index.vue`。
  - 清理已核实的零外部消费 Store 状态/方法、`useQuestionCompose.restoreQuestion`、`apiGetDiagnosisReport`、字符串重载分支及死类型/未用视图辅助函数（`optionDisplayText` 改为在 3 个选项渲染组件中复用或清理）。

## Acceptance Criteria

- [ ] **AC1**：`backend/pyproject.toml` 中 `httpx` 位于 `[project].dependencies`；7 个 `api/deps/*.py` 复用 `_factory.py` 且零未关闭 `session_factory()`；`knowledge.py` 与 `question.py` 不再直接导入 `run_structured_agent_workflow`。
- [ ] **AC2**：`GET /api/v1/mastery/overview` 及清单内 `app=0` 的后端死别名/异常类已移除，其余 25 个后端扩展路由保持完好。
- [ ] **AC3**：`miniprogram/package.json` 已移除 7 个无用包，`upload/index.vue` 与 `apiGetDiagnosisReport` 已删除，`profile/index.vue` 零 `@/utils/request` 直接导入。
- [ ] **AC4**：`course/index.vue` 原文切片真实展示 `page_index`（如第 3 页显示「第 3 页」而非恒定「第 1 页」），并有 Vitest 用例覆盖。
- [ ] **AC5**：宿主 Windows `pwsh` 下 `task verify`（`task verify-backend` + `task verify-frontend`）全绿通过。

## Out of Scope

- 拆分千行级 Service 或超 300 行 `.vue` 页面、重构 SCSS 设计 Token（归属 `M3`）。
- 重写 `docs/DESIGN.md`、`README.md` 与 `.trellis/spec/**`（归属 `M4`）。
