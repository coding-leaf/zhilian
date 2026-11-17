# Implementation Plan — 学习全流程重设计与移动端体验重构

## 1. Pre-Start Checklist

- [x] `prd.md` 已完成收敛检查（已剔除伪造考频与死板预设，锚定即时备考定位与自主后台异步出题）
- [x] `design.md` 已明确 Alembic `0011` 迁移、后台生题队列、PDF 乱码恢复、`<RichContent>` AST 及三波次无碰撞切分
- [x] `implement.jsonl` 与 `check.jsonl` 已注入真实规范与调研文档并通过 `task.py validate`
- [ ] 获得用户对本最终规划摘要的确认后，执行 `task.py start .trellis/tasks/11-17-learning-flow-and-ux-redesign`

## 2. Ordered Wave Execution Checklist

### Wave 1 — 后端解阻塞、异步生题队列、结构化无乱码知识卡与判题即刻沉淀
1. **切出任务分支**：从最新本地 `master` 切出 `feat/exam-prep-flow-redesign`。
2. **`be-async-routes-jobs`（`High`，`share`）**：
   - 将 `backend/app/api/v1/*.py` 全部调用同步 DB/HTTP 的 `async def` 路由改为 `def`（保留纯 `UploadFile.read()` 异步流式读取段或拆为同步包装）；
   - 新增 `QuestionGenerationJob` 模型 + Alembic 迁移 `0011`（合并 `structured_content` 列与 `question_generation_jobs` 表于同一迁移 `0011` 避免双头冲突！）；
   - 实现 `POST /api/v1/questions/jobs`（`202`）、`GET /api/v1/questions/jobs`、`GET /api/v1/questions/jobs/{id}` 及 `app/worker.py` 中的 `generate_questions_job`（含考点受控并发 `ThreadPoolExecutor(max_workers=3)` 与进度回写；`memory` 队列下走后台线程执行）；
   - 在 `POST /api/v1/materials/{id}/parse` 支持 `force: bool = False` 重新解析已 `ready` 讲义。
3. **`be-knowledge-and-grading`（`XHigh`，`share`）**：
   - PDF 乱码检测与清洗：`extractors` 检测缺失 `/ToUnicode` 的符号字体 + `ocr_quality.py` 新增连续 ASCII 符号簇检测；异常页经 OCR / `deepseek-flash` 上下文清洗还原可读公式，剥离 PPT 伪列表符与乱码行；
   - 知识点结构化与去重：跨批大纲注入 + `deduplicate_candidate_points` 前置归一化同名合并 + `structured_content`（`core_summary`, `key_takeaways`, `key_formulas`, `boundary_notes`，严禁生成考频猜测）；
   - 跨层判题与自动学情沉淀修复：`_question_llm_schemas.py` 剥离 dict 选项 `A.` 前缀；`grading.py` 同时兼容 `'正确'/'错误'/'T'/'F'`；`submit_practice` 同步秒判客观题并立即触发 `DiagnosisService.sync_practice_learning_state(..., partial_ok=True)`，RQ `grade_practice` / `regrade_attempt` / `self_evaluate_attempt` 全部挂载自动同步与 `completed` 自动预生成报告；补齐 `QuestionSnapshotDTO.knowledge_point_name`、`WrongRecordItemResponse` 考点名与 `GET /mastery?folder_id=` 筛选。
4. **`verifier-w1`（`High`）**：核验双轨合并、Alembic 迁移一致性门禁、`max-complexity <= 15` 及全套后端 `pytest`。

### Wave 2 — 前端纯净视觉底座、`<RichContent>` 富文本引擎、新版 AI 助教与后台任务条
1. **`fe-visual-coach-taskbar`（`XHigh`，`share`）**：
   - 清除 `modal.scss` 与 `common.scss` 全部 `backdrop-filter`，在 `App.vue` 定义 `--z-*` 层级阶梯并补全 `scroll-view, textarea { box-sizing: border-box; }`；
   - 新建 `src/utils/loadingGuard.ts` 并与 `request.ts` 协同清零 `showLoading` 冲突；
   - 新建 `src/stores/backgroundTask.ts` + `src/components/BackgroundTaskBar.vue`（统一轮询后台解析中的讲义与生成中的出题任务）；
   - 重构 `AiCoachDrawer.vue` + `CoachMessageList.vue`（`virtualHost: true` + 严格 Flex 高度滚动 + `:scroll-into-view` + 按 `question/kp/material/folder` 隔离对话缓存 + 多行输入与复制）。
2. **`fe-richtext-and-adapters`（`XHigh`，`share`）**：
   - 新建零依赖 `src/utils/richText.ts` + `src/components/RichContent.vue`（Markdown + LaTeX 公式上下标/分式/希腊符号 AST 编译）及 Vitest 完备单测；
   - 更新 `src/types/*`、`src/api/modules/*`、`src/api/adapters/*`：接入 `structured_content`、`questions/jobs`、`mastery` 筛选、多选 `user_answer` `JSON.parse` 修复、切片乱码兜底与 `knowledge_point_name`。
3. **`verifier-w2`（`High`）**：核验双轨零冲突、`pnpm lint` / `type-check` / `test:cov`。

### Wave 3 — 全站页面闭环组装（严守单 `.vue <= 300` 行）
1. **`fe-study-and-compose`（`XHigh`，`share`）**：
   - `pages/index`：微信文档 + 拍照/相册双通道上传，上传完自动入队解析，挂载 `<BackgroundTaskBar>`；
   - `subpackages/material/pages/course`：章节折叠分组 + 2 行扫读卡 + 底部结构化精读抽屉（`<RichContent>` 渲染要点/公式/边界说明 + 默认折叠原文切片 + 「重新解析」入口 + 单点去出题）；
   - `subpackages/material/pages/questions`：按章节清晰展示去重考点（不搞死板预设、不强行缩限考点），点击生成走 `POST /questions/jobs` 异步任务流（支持留在当前页看考点生成进度或随时返回看卡片），`QuestionPreviewCard` 支持 `<RichContent>` 与折叠核对答案/解析/采分点。
2. **`fe-practice-and-review`（`XHigh`，`share`）**：
   - `subpackages/practice/pages/session`：`<RichContent>` 题干与选项、判断题提交 `'正确'/'错误'`、多选题数组状态一致、多空填空分格输入、考点徽标展示；
   - `subpackages/report/pages/detail`：`<RichContent>` 解析与 `gradingPoints` 展示，新增「去学情中心」快捷按钮；
   - `pages/review`：注册 `onShow` 实时刷新 + 错误重试态，挂载 `<BackgroundTaskBar>`，升级为「顶部掌握度与薄弱点总览（一键针对薄弱考点去组卷） + 四分段切换（`考点掌握 | 错题本 | 练习记录 | 我的题库`）」，修复 `WrongRecordCard` 考点标签绑定。
3. **`verifier-w3`（`XHigh`）**：核验全部 `.vue <= 300` 行、`0` `backdrop-filter`、全套前后端门禁。

### Wave 4 — 主工作区总装、数据库迁移与微信包重编译
1. 合入主工作区，执行 `task verify` 全量门禁。
2. 执行 `pnpm run build:mp-weixin` 更新 `miniprogram/dist/build/mp-weixin`，并输出更新本地 PostgreSQL 迁移（`uv run alembic upgrade head`）与重建 Docker `worker` 容器的一键命令。

## 3. Validation Commands

```powershell
$env:PYTHONIOENCODING = 'utf-8'
task verify
cd d:\code\Workspace\zhilian\miniprogram; pnpm run build:mp-weixin
```
