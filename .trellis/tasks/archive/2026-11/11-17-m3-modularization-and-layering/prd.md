# M3: 前后端深层解耦与巨型模块拆分

## Goal

在 `M2` 清退死代码并修复跨层 P0 缺陷后，使用高阶推理模型（`Gemini 4 Hydrogen (XHigh)`）对前后端核心巨型模块、越层 SQL/传输耦合及硬编码样式进行结构化拆解，消除千行上帝类与超 300 行 `.vue` 页面，收紧静态圈复杂度与分层依赖门禁。

## Background & Verified Evidence

依据父任务 `research/02`、`03`、`04` 核实：
- **后端分层违规与千行级上帝类（`02`）**：
  - `GradingService`（`services/grading.py:675,822,985`）、`PracticeService`（`services/practice.py:534,540`）、`MaterialService`（`services/material.py:642`）绕过 Repository 直接执行 `select()` / `session.delete()`；
  - `api/v1/practices.py:26` 直接导入 `app.integrations.idempotency.protocol.validate_idempotency_key`；`FolderService`（`services/folder.py:313,322,351`）越级访问 `self.material_service.repo` 并内联实例化 `QuestionRepository`；路由层（`diagnosis.py:310-367`、`questions.py:93,267,396`、`materials.py:723-728`、`folders.py:138-163`）承担了多服务编排与 DTO 拼装；
  - `MaterialService`（`material.py:1201,1274`）与 `PracticeService`（`practice.py:768`）对 ORM 实例动态 monkey-patch 未映射属性（`# type: ignore[attr-defined]` / `# noqa: B010`）；
  - 五大巨型 Service 超千行：`question.py`（1,901L，CC=45）、`material.py`（1,668L）、`diagnosis.py`（1,495L，其中 `generate_diagnosis_report` **417L / CC=73**）、`practice.py`（1,372L，CC=41）、`grading.py`（1,051L），导致 `pyproject.toml:55` 不得不将 `max-complexity` 放宽至 `28`；
  - 跨模块重复：3 处 `_log_metric`、5 处手写指数退避重试循环、3 处重复 `QuestionType` 定义。
- **前端巨型单文件与样式耦合（`03`）**：
  - `miniprogram/src/api/index.ts`（553L）与 `src/types/index.ts`（509L）将全站 8 个域堆砌在单文件中；
  - 6 个 `.vue` 文件突破 300 行上限：`pages/index/index.vue`（906L）、`subpackages/material/pages/course/index.vue`（796L）、`pages/profile/index.vue`（411L）、`components/AiCoachDrawer.vue`（410L）、`subpackages/report/pages/detail/index.vue`（343L）、`subpackages/material/pages/questions/index.vue`（314L）；
  - 3 处独立手写轮询无统一取消机制；`isAnswered`、`flattenTree` 跨文件重复；
  - 样式债：384 处裸 Hex 色值、4 处重复弹窗样式块、0 处 `safe-area-inset-bottom` 底部安全区适配、缺失 `.status-retake_required`/`.badge-retake_required` 样式、23 行违规 Emoji。

## Requirements

- **R1 — 后端分层硬化与公共基建收敛（Track `be-modular`，`XHigh`）**：
  - 将 `GradingService`、`PracticeService`、`MaterialService` 内全部裸 `select()` / `session.delete()` 下沉至 Repository；
  - 消除 `api/v1/practices.py -> app.integrations` 导入并在 `pyproject.toml` 新增 `import-linter` 禁止契约；修复 `FolderService` 依赖注入（直接注入 `MaterialRepository` 与 `QuestionRepository`）；将路由层分页归一化与 DTO 富化下沉；
  - 用显式 Service DTO/返回结构替换 `material.py` 与 `practice.py` 中的 ORM monkey-patch；
  - 抽取统一指标日志辅助函数（`core/logging.py`）、共享指数退避执行器（`integrations/_http_retry.py`）、文档字节解析器（`core/extractors/`）与纯知识树算法（`core/algorithms/knowledge_tree.py`），收敛单一 `QuestionType` 事实源。
- **R2 — 后端巨型 Service 与高圈复杂度函数拆解（Track `be-modular`，`XHigh`）**：
  - 拆解 `DiagnosisService.generate_diagnosis_report`（CC=73 -> 各子函数 CC<=15）及 `QuestionService`、`MaterialService`、`PracticeService`、`GradingService`、`PracticeItemDetailResponse` 等超高复杂度函数/模块，保持原有公开导入路径兼容（通过包或 facade 重导出），并将 `backend/pyproject.toml` 中 `[tool.ruff.lint.mccabe] max-complexity` 从 `28` 收紧至 `<= 18`（目标 `<= 15`）。
- **R3 — 前端按域拆分与超标组件解耦（Track `fe-modular`，`XHigh`）**：
  - 将 `src/types/index.ts` 与 `src/api/index.ts` 按业务域拆分为子模块（保留 `src/types/index.ts` 与 `src/api/index.ts` 聚合 barrel 导出，对外零破坏）；
  - 拆解全部 6 个 >300 行的 `.vue` 页面/组件（抽离子组件与领域 composable），使所有 `.vue` 文件均 `<= 300` 行；
  - 抽取共享可取消轮询器 `src/utils/poller.ts`、知识树扁平化工具 `src/utils/knowledgeTree.ts`、存储键常量 `src/utils/storageKeys.ts` 并消除重复 `isAnswered`。
- **R4 — 前端设计 Token 收敛与交互细节补齐（Track `fe-modular`，`XHigh`）**：
  - 建立共享样式模块（`src/styles/tokens.scss`、`src/styles/modal.scss`），消除 4 处重复弹窗样式，补齐固定底栏 `env(safe-area-inset-bottom)` 与 `retake_required` 徽标样式，清理 23 行违规 Emoji，大幅收敛组件内裸 Hex 字面量至 CSS 变量。

## Acceptance Criteria

- [ ] **AC1**：`backend/app/services/**` 中 `0` 处 `sqlalchemy.select` 导入与 `0` 处 ORM `# type: ignore[attr-defined]` / `# noqa: B010` monkey-patch；`lint-imports` 包含 `api -> integrations` 禁止契约且全部通过。
- [ ] **AC2**：`backend/pyproject.toml` 的 `max-complexity` 下调至 `<= 18`（力争 `15`）且 `ruff check .`、`mypy app`、全量 `pytest`（覆盖率 >=80%）全部通过。
- [ ] **AC3**：`miniprogram/src/**/*.vue` 全部单文件行数 `<= 300` 行；`src/api/` 与 `src/types/` 完成按域模块化拆分。
- [ ] **AC4**：底部操作栏具备 `safe-area-inset-bottom` 适配，已补齐 `retake_required` 状态样式并清理违规 Emoji，`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit` 全绿通过。

## Out of Scope

- 修改后端 HTTP 公开 JSON 响应契约中的历史兼容字段（避免破坏现有集成测试与外部调用）。
- 重写顶层 `docs/DESIGN.md`、`README.md` 与 `.trellis/spec/**`（统一在 `M4` 对照拆分后的最终文件树一次性精准刷新）。
