# Implementation Plan: 主界面全局助教、视觉语义切片与两阶段考前精讲笔记

## 执行编排（分职责 Swarm + Overview Plan）
- **线程分组（写入 Swarm `plan.json`）**：
  1. `t-coach-scope`（`coach-backend` + `coach-frontend`）
  2. `t-doc-chunking`（`doc-pipeline`）
  3. `t-study-guide`（`guide-backend` + `guide-frontend`）
  4. `t-verify`（`verifier` 独立跨层核验 + `monitor` 防卡顿）
- **模型约定**：5 位实现 Worker 均用 `gemini-4-hydrogen-high`（`workspace:"share"`）；`verifier` 用 `gemini-4-neon-high`（`workspace:"inherit"`）；`monitor` 沿用默认模型。
- **合入红线**：每个 Worker 严禁触碰范围外文件、`.trellis/**` 或执行 `git commit`/`push`；主会话逐轨道仅复制显式拥有文件合入后由 `verifier` 独立复核并执行全量离线门禁 `task verify-backend` + 前端 `lint`/`type-check`/`test:unit`/`build:mp-weixin`。

## 分轨道验证清单
- `coach-backend`：`ruff` + `mypy` + `lint-imports` + `pytest tests/unit/services/test_coach_scoped.py tests/unit/integrations/llm/test_coach_graph.py`
- `coach-frontend`：`eslint` + `vue-tsc` + `vitest`（含 `useCoachChat.spec.ts`, `homeCoachScope.spec.ts`, `mpWeixinCompatGuard.spec.ts`）
- `doc-pipeline`：`ruff` + `mypy` + `lint-imports` + `pytest tests/unit/core/algorithms/test_semantic_chunking.py tests/unit/core/algorithms/test_ocr_quality.py tests/unit/core/algorithms/test_material_chunking.py tests/unit/core/test_extractors.py tests/unit/core/test_extractors_pymupdf.py tests/unit/services/test_material_pipeline_vlm.py`
- `guide-backend`：`ruff` + `mypy` + `lint-imports` + `pytest tests/unit/models tests/unit/core/algorithms/test_knowledge_quality.py tests/unit/core/algorithms/test_knowledge_tree.py tests/unit/services/test_knowledge_service.py tests/unit/services/test_study_guide_service.py`
- `guide-frontend`：`eslint` + `vue-tsc` + `vitest`（含 `studyGuidePage.spec.ts`, `knowledgeReviewCard.spec.ts`, `mpWeixinCompatGuard.spec.ts`）+ `.vue <= 300` 行核验
