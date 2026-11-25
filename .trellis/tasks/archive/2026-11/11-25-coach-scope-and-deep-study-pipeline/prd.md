# PRD: 主界面全局助教语境重构、视觉/小模型语义切片与两阶段考前精讲笔记

> **任务**：`11-25-coach-scope-and-deep-study-pipeline`
> **调研依据**：
> - `research/01-home-coach-context.md`
> - `research/02-semantic-chunking-and-deep-study-guide.md`
> **分支**：`feat/coach-scope-and-deep-study`（基于最新 `origin/master`）

## 1. 背景与目标

基于真机二次实测反馈（工作台主界面助教截图 + 讲义考点弹窗第 7 页截图），解决 3 项核心体验与架构短板（M3 纯 UI 视觉精修按用户要求继续暂缓）：

1. **工作台主界面 AI 助教语境错位**：主界面未选课程却静默锁死首个课程，切「全部课程」时甚至本地弹窗拒发请求；课程模式下错用讲义快捷提问「帮我梳理这份资料的核心框架」。
2. **PDF/PPT 切片无乱码但公式散架、被劈成无用残片**：PyMuPDF 拆碎二维分式，现有 VLM 触发器漏检正常字体 PPT 公式页，`is_heading_block` 误把 `ω^T x_i + b` 判成章节标题导致单页被劈成 3 块废片；同时线上 `PaddleOCR-VL-1.5` 存在协议错配与全页 PNG 预渲染内存隐患。
3. **知识点总结过浅，无法用于考前复习**：单阶段批量抽树把 40 页切出 33 个碎点（受 `MAX_LEVEL_2_RATIO=0.60` 反向惩罚）且每考点仅剩 150~250 token，注定只能输出干瘪提纲。

## 2. 功能需求与验收标准

### 2.1 主界面全局助教与安全多资料检索（Thread 1）
- **R1.1 后端统一 Scope 契约**：`POST /api/v1/coach/ask` 支持 `scope: Literal["global", "folder", "material", "knowledge_point"]`（三 ID 全空且未传 `scope` 默认 `"global"`；显式 `scope="folder"` 缺 `folder_id` 返回 422 绝不回退首课）并支持 `history` 冷启动兜底。
- **R1.2 1 次 Embedding 安全跨资料检索**：在 `SearchOptions` 新增 `allowed_version_ids` 白名单，`pgvector` 与内存检索器同步支持，彻底消除多资料 `O(N)` 外部 Embedding 调用与已删/归档/旧版切片泄露风险。
- **R1.3 全局学习上下文与通用兜底**：新增 `build_global_study_context`（聚合用户就绪讲义与薄弱考点）；全局模式下优先全库检索，无直接教材出处时走 `generate_general` 通用学科解答（`cited=[]`，严禁编造教材来源）。
- **R1.4 前端主界面解耦与胶囊切换**：工作台抽离 `useHomeCoach.ts`（默认 `coachFocusedFolderId = undefined` 即全局模式，不绑死 `folderStore.currentFolderId`）；新增 `CoachScopeSelector.vue` 横向胶囊切换「全部资料·全局」或具体课程；严格区分全局 / 课程 / 讲义三套快捷提问。

### 2.2 视觉重建与 `deepseek-flash` 语义打标切片（Thread 2）
- **R2.1 高召回 VLM 触发 + 协议适配 + 省内存渲染**：
  - `extractors.py` 新增 `is_slide_layout` 与 `has_math_expression_layout`（PPT 含希腊字母/数学符/`drawings >= 4` 或孤立公式块/上下堆叠分式即进 VLM；清晰封面/目录/致谢跳过 VLM）。
  - `VLMSettings` 新增 `prompt_style` (`auto | general_markdown | paddleocr_vl`)、`image_format="jpeg"`、`jpeg_quality=85`、`max_image_edge=1440`；按实测结果精确适配 `PaddleOCR-VL-1.5`。
  - `transcribe_dirty_pages_with_vlm` 改为滚动批渲染（每批 `<= 6` 页 JPEG 用完即释放），保护 `aliyun` 1.7 GiB RAM。
- **R2.2 确定性标题止血 + `deepseek-flash` 8 页滑窗语义打标切片**：
  - `is_heading_block` 彻底禁止所有数学运算/关系符与希腊字母，收紧为显式章节号或页顶 22% 纯中文标题。
  - 新增 `core/algorithms/semantic_chunking.py` 与 `services/_semantic_chunker.py`：8 页滑窗 Zero-Rewrite 轻量打标（`topic_title`, `is_substantive`, `merge_with_prev`, `needs_formula_repair`, `repaired_markdown`），将跨页推导聚合成完整逻辑单元（上限 1400 字，保留 `page_number..page_end`），单批失败自动静默回退确定性切片。

### 2.3 收敛考点树 + 懒生成永久缓存考前精讲笔记（Thread 3）
- **R3.1 Stage 1 收敛 2 层考试级考点树**：
  - 常规单章（`<= 28,000` 字）改为 One-Shot 全局单次建树，产出 **8~15 个考试级核心考点**（干净 2 层树）+ 轻量预览卡；超长文档按大章分批后轻量归并。
  - 修复 `knowledge_quality.py` 中 `MAX_LEVEL_2_RATIO=0.60` 反向惩罚 2 层树的问题，密度调整为 `1000~4500` 字/考点，向量去重阈值调为 `0.86`。
- **R3.2 Stage 2 考前精讲笔记（懒生成 + 永久缓存 + 一键整章预热）**：
  - Alembic 迁移 `0015_kp_study_guide` 在 `knowledge_points` 新增 `study_guide`（JSON/JSONB）、`study_guide_generated_at`、`study_guide_version`（列表查询 `defer` + `has_study_guide: bool` 零拖慢，重解析自动清理）。
  - Redis / 内存单飞锁 + 短事务边界 + 单考点独享 `max_tokens=6144`（`tool_choice="auto"`），产出结构化 9 要素考前精讲（含考法定位、严谨定义、符号表、核心公式、逐步推导、1~2 道典型例题与分步解答、易混概念对比、高频避坑、30 秒速记锚点）。
  - 端点：`GET /knowledge/{kp_id}/study-guide`、`POST /knowledge/{kp_id}/study-guide/generate`、`POST /materials/{material_id}/study-guides/prewarm`、`GET /materials/{material_id}/study-guides/status`；整章预热复用 RQ `zhilian` 队列（`prewarm_study_guides`）+ DB 计数 + Redis 进度（零新增 Job 表）。
- **R3.3 前端独立全屏「考点精讲页」（清晰分段，绝不一股脑塞一屏）**：
  - 新建 `subpackages/material/pages/knowledge/index.vue`（及拆分视图组件，全部 `<= 260` 行），通过清晰分段 Tab 分职责呈现：**精讲笔记 | 典型例题 | 对比与避坑 | 教材原文**；首次点开未生成时即刻展示 Stage 1 预览并触发懒生成（60s 超时），支持「重新生成」、底部「针对此考点出题 / 向 AI 助教追问」。
  - 讲义详情页展示「已精讲」角标与「一键预生成本章精讲」按钮，并接入 `BackgroundTaskBar`。

## 3. 质量门禁
- 后端：`task verify-backend`（`ruff` + `mypy --strict` + `lint-imports` + `pytest --cov=app --cov-branch --cov-fail-under=80` + `0015` 迁移对称与模型一致性）。
- 前端：`eslint` + `vue-tsc` + `vitest`（含 `mpWeixinCompatGuard.spec.ts`）+ `pnpm run build:mp-weixin`（0 `span` 警告，所有 `.vue <= 300` 行，0 裸 Hex，0 Emoji，0 `PATCH`）。
