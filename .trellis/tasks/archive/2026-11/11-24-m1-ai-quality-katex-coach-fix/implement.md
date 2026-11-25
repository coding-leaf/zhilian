# Implementation Plan: M1 — AI 自主质检、KaTeX 公式渲染器与 502/AI 助教修复

> **推荐 Phase 2 执行编排**：**原生 `Swarm` 3 路无冲突并行开发（独立 `share` 工作区，全部 `gemini-4-neon-high`）**。
> **前置准备（主会话在派发 M1-B 前执行）**：在 `miniprogram/` 安装 `katex@0.16.21`（`pnpm add katex@0.16.21`）并将字体复制到 `backend/app/static/fonts/katex/`，确保所有 `share` 工作区通过 `node_modules` junction 立即可用。

---

## 1. 无冲突文件边界（File Ownership）

### Track M1-A (`impl-m1-ai-quality`, `gemini-4-neon-high`, `workspace: "share"`)
- Backend:
  - `backend/app/core/algorithms/question_quality.py`
  - `backend/app/services/_question_llm_schemas.py`
  - NEW `backend/app/services/_question_quality_judge.py`
  - `backend/app/services/_question_generation.py`
  - `backend/app/services/question.py`（含 `ask_coach` `max_tokens=4096` 一并放宽，避免与 M1-C 踩文件！）
  - `backend/app/repositories/question.py`（如默认过滤 `AVAILABLE` 需要）
  - NEW `backend/migrations/versions/0013_soft_delete_legacy_pending_review_questions.py`
  - Related backend tests (`test_question_quality*`, `test_question_service*`, `test_async_question_job*`, NEW `test_migration_0013*`)
- Frontend (仅限清除「待审核」展示):
  - `miniprogram/src/subpackages/material/components/QuestionReadyCard.vue`
  - `miniprogram/src/subpackages/material/composables/useQuestionCompose.ts`
  - `miniprogram/src/pages/review/components/{QuestionBatchRow,QuestionBankQuestionRow}.vue`
  - `miniprogram/src/pages/review/composables/useBatchPracticeLaunch.ts`
  - `miniprogram/src/pages/review/questionBank.scss`
  - `miniprogram/src/utils/questionBatch.ts`
  - Related frontend tests (`questionBatch.spec.ts`, `questionBank.spec.ts`, `studyAndComposeFlow.spec.ts`)

### Track M1-B (`impl-m1-katex-math`, `gemini-4-neon-high`, `workspace: "share"`)
- Backend:
  - `backend/app/main.py`（挂载 `/static/fonts/katex/` 只读静态字体路由 + `immutable` 缓存头）
  - `backend/tests/unit/test_katex_static_fonts.py`（NEW）
- Frontend:
  - NEW `miniprogram/src/utils/katexRichText.ts`
  - NEW `miniprogram/src/utils/katexFonts.ts`
  - NEW `miniprogram/src/styles/katex-mp.scss`
  - `miniprogram/src/utils/richText.ts`
  - `miniprogram/src/utils/richTextMath.ts` & `latexSymbols.ts`（退役清理或仅留轻量兜底）
  - `miniprogram/src/components/RichContent.vue`
  - `miniprogram/src/App.vue`
  - Related frontend tests (`richText.spec.ts`, NEW `katexRichText.spec.ts`, `lifecycleAndDebounce.spec.ts` 若涉及 `App.vue`)

### Track M1-C (`impl-m1-coach-errors`, `gemini-4-neon-high`, `workspace: "share"`)
- Backend:
  - `backend/app/workflows/coach_graph.py`
  - `backend/app/integrations/llm/agent_graph.py`
  - Related backend tests (`test_coach_graph*`, `test_agent_graph*` / NEW `test_coach_thinking_resilience.py`)
- Frontend:
  - `miniprogram/src/composables/useCoachChat.ts`
  - `miniprogram/src/utils/request.ts`, `miniprogram/src/utils/requestError.ts`
  - `miniprogram/src/pages/review/index.vue`
  - `miniprogram/src/components/BackgroundTaskBar.vue`
  - `miniprogram/src/pages/index/composables/useMaterialUpload.ts`
  - Related frontend tests (`useCoachChat.spec.ts`, `requestResilience.spec.ts`, `requestFailure.spec.ts`, `backgroundTask.spec.ts`)

---

## 2. 合并、门禁与上线验收

1. 合入 M1-A / M1-B / M1-C 至主工作区。
2. 宿主 Windows PowerShell 运行全量门禁与编译产物校验：
   - `task verify-backend`
   - `cd miniprogram && pnpm run lint && pnpm run type-check && pnpm run test:cov && pnpm run build:mp-weixin`
   - 核验 `dist/build/mp-weixin` 主包 `< 900 KB`、0 处非法动态 `import()` / `PATCH` / `[disabled]` / `\p{}`。
3. 更新 `.trellis/spec/`（沉淀 KaTeX 字体托管与 AI 自主质检规范），分批提交推送 `origin` 并 `git push aliyun HEAD:deploy`（自动跑迁移 `0013` 与重启服务）。
