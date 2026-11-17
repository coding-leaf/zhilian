# 学习全流程重设计与移动端体验重构

## Goal

锚定 **「即时备考（校园期末复习 + 社会考证冲刺，A+B 融合）」** 核心定位，将智练升级为 **「无摩擦导入与干净公式解析 → 基于原文事实的结构化速览卡学习 → 自由可控的后台非阻塞异步出题 → 零依赖富文本作答与可滑动 AI 助教 → 交卷即刻沉淀错题与掌握度的实时学情闭环」**，同时彻底根除蒙版模糊闪烁、AI 助教无法滑动/右裁切、PDF 符号乱码、同名重复考点、生题卡死全站请求、判断题全判 0 分及学情页切回空白等全部根因缺陷。

## Confirmed Repository & Live-DB Facts

详细取证见 `research/01..04.md`：
1. **UI1 视觉与提示冲突**：`miniprogram/src/styles/modal.scss:10,25` 遮罩使用 `backdrop-filter: blur(2px)` 且 6 个浮层共用 `z-index: 999`；`common.scss:47` 底栏有 `blur(10px)` 而 `subpackages/material/questions.scss:154` 无模糊导致切换闪烁；全仓 11 处 `uni.showLoading` 与 `utils/request.ts:16,35,155,165` 自动 `showToast` 抢占单槽位原生提示引发不配对告警。
2. **UI2 AI 助教交互缺陷**：`CoachMessageList` 缺 `virtualHost: true`，`.chat-body`（`CoachMessageList.vue:59-63`）缺 `height: 0; min-height: 0` 导致无法下滑；`App.vue:103` 的 `box-sizing: border-box` 漏掉 `scroll-view` 与 `textarea` 使宽度膨胀至 `814rpx` 裁切右侧气泡；`useCoachChat.ts:26` 跨题目/考点共用单消息列表串台，正文直出裸 `<text>` 未解析 Markdown 与公式。
3. **UI3 PDF 乱码与知识点失焦/重复**：活库 `贝叶斯分类器.pdf` 第 6/7/11 页 `SymbolMT` 缺 `/ToUnicode`，`core/extractors.py:209` 跳过 OCR 且 `ocr_quality.py:44-46` 对 `AB&A&`/`"#$"$` 误判 `gibberish_ratio=0.000`（拖累 `3/9` 题触发 `NO_SOURCE`）；`services/knowledge.py:250,286` 缩批切分缺大纲传递且 `knowledge_tree.py:86-151` 缺归一化同名合并（活库存在 9 组同名重复考点）；`KnowledgePoint` 仅单 `description` 长段落字段。
4. **生题阻塞全站超时**：`backend/app/api/v1/*.py` 中 **66 个路由声明为 `async def`**（含 `questions.py:120`），在主事件循环同步调用 `Session` 与 `httpx.Client`；7 考点串行生成耗时 ~101s 锁死 `uvicorn` 事件循环，拖死首页 `GET /materials`（15s 超时）。
5. **题目排版与判分跨层 Bug**：`_question_llm_schemas.py:67-72` dict 选项漏剥前缀产生 `A. A.`；`session/index.vue:166-172` 判断题提交 `'A'/'B'` 而 `grading.py:91-96` 仅认 `正确/错误/T/F` 致判断题全判 0 分；`schemas/practice.py:461` 多选返回 JSON 串 `'["C"]'` 而 `adapters/practice.ts:61` 未解析致续练丢勾选；`QuestionPreviewCard` 无答案/解析折叠区，`WrongRecordCard.vue:41` 错把题型显示在考点标签。
6. **学情界面空白**：`pages/review/index.vue:195` 与 `QuestionBankSection.vue:122` 仅用 `onMounted` 缺 `onShow`（Tab 页常驻内存切回零请求）且静默吞错；后端 `GradingService` 判完不自动写 `WrongRecord`/`MasteryRecord`（强依赖前端停留报告页调 `POST /diagnosis`）；前端未接入 `GET /mastery` 掌握度接口。

## Resolved Product Decisions & Constraints

1. **严禁伪造「考频/高频」标签与定死组卷方向**（用户明确否决）：
   - 严禁从单份讲义中臆造无事实依据的「高频必考/考频权重」标签；知识点仅展示严格源于原文的结构化内容与基于真实作答计算的掌握度档位（`未练 / 薄弱 / 基本掌握 / 熟练`）；
   - 不设强行框定用户的「闪电速刷/期末大题」死板预设模式，也不在解析后未经请求自动偷跑预生成题目；保持用户对考点范围（按章节清晰去重展示）、题型与题量的完全自主控制。
2. **全面启用后台非阻塞异步生题**：点击生成题目后立即创建异步后台任务（`202` + `job_id`），通过全站紧凑后台任务进度条实时反馈进度，支持用户在后台出题期间自由返回首页或继续阅读知识速览卡，完成后一键跳转预览/开练。
3. **子代理模型策略**：常规波次/核验使用 `gemini-4-hydrogen-high`，复杂多模块重构/富文本 AST 与页面重设计使用 `gemini-4-hydrogen-xhigh`。

## Requirements

- **R1 — 全站路由解阻塞与后台异步生题引擎（Backend + Task Bar）**：
  - 将 `backend/app/api/v1/*.py` 中所有调用同步 `Session` / 同步 `httpx` 的 `async def` 路由改为 `def`（线程池并发），确保耗时请求绝不卡死 `uvicorn` 事件循环。
  - 新增 `QuestionGenerationJob` 持久化模型（Alembic 迁移 `0011`）与 RQ 队列任务 `generate_questions_job`（Worker 内按考点受控并发 `max_workers=3` 提速），新增 `POST /api/v1/questions/jobs`（返回 `202` + `job_id`）与 `GET /api/v1/questions/jobs` / `GET /api/v1/questions/jobs/{job_id}` 进度查询接口（保留原 `POST /questions/generate` 同步兼容契约供既有单测/CLI 使用）。
  - 前端新增全局 `useBackgroundTaskStore` 与吸顶紧凑 `<BackgroundTaskBar>`，统一跟踪「资料后台解析中」与「题目后台生成中（X/Y 考点）」，跨页面可见且完成即提供「去查看 / 去核对开练」一键直达。
- **R2 — PDF 公式乱码修复与结构化知识速览卡（Backend + Course UI）**：
  - `core/extractors/` 与 `ocr_quality.py` 增加 PDF 页级 `/ToUnicode` 缺失检测及连续 ASCII 数学符号簇（如 `AB&A&`、`"#$"$`）乱码判定；命中异常页时自动渲染页面图像交由百度 OCR + `deepseek-flash` 上下文清洗还原为干净文本/标准公式，清洗 PPT 伪列表符；讲义页支持手动触发「重新解析」以刷新历史乱码资料。
  - `knowledge_points` 表新增向后兼容的 `structured_content`（JSON：`core_summary` 一句话核心定义、`key_takeaways` 3~4 条原文要点、`key_formulas` 公式/判据列表、`boundary_notes` 原文提及的适用条件/易混边界——无则留空，严禁编造考频）；抽取流水线注入跨批章节大纲并在 `deduplicate_candidate_points` 前置归一化同名合并，彻底消灭同名重复考点。
  - 移动端课程页（`course/index.vue`）重构为：`章节折叠分组 → 紧凑扫读卡（考点名 + 真实掌握度胶囊 + <=2 行核心定义 + [展开速览] / [练此考点]） → 底部精读抽屉（<RichContent> 渲染要点/公式/边界说明 + 默认折叠的页码原文切片 + 问助教/去出题）`；同时修复 `useMaterialUpload.ts` 支持微信文档 + 拍照/相册双入口并在上传后自动触发解析。
- **R3 — 零糊屏视觉底座、`<RichContent>` 富文本、统一题卡与 AI 助教重设计（Frontend + Cross-Layer）**：
  - 移除 `modal.scss` 与 `common.scss` 全部 `backdrop-filter` 模糊滤镜，采用温润纸白实色面板 + 暖墨半透遮罩 + `--z-*` 分级变量（`sticky < bottom-bar < fab < sheet < coach < modal`）；实现 `loadingGuard` 引用计数卫士并与 `request.ts` `silentToast` 联动，100% 消除毛玻璃闪烁与 `showLoading` 配对告警。
  - 实现零第三方依赖 `src/utils/richText.ts` + `<RichContent>` 组件（编译标题、加粗、列表、行内代码、公式块、`sub`/`sup` 上下标、`\frac` 与常用希腊/数学符号为小程序原生 `<rich-text :nodes>` 安全节点）。
  - 修复全部 4 项题目与判题跨层缺陷：(1) `_question_llm_schemas.py` 剥离 dict 选项重复 `A.` 前缀；(2) `session/index.vue` 判断题提交 `'正确'`/`'错误'`（兼容后端判分）；(3) `adapters/practice.ts` 解析多选 JSON 数组修复续练丢勾选；(4) 多空填空分格输入、`QuestionSnapshotDTO` 补 `knowledge_point_name`、`QuestionPreviewCard` 增加答案/解析/采分点折叠核对区、`WrongRecordCard` 修正考点名展示。
  - 重构 `AiCoachDrawer` + `CoachMessageList`：补齐小程序组件 `options: { virtualHost: true }`、`.chat-body` 严格 Flex 高度约束与 `:scroll-into-view` 自动滚底；在 `App.vue` 补齐 `scroll-view, textarea { box-sizing: border-box; }` 根除右侧气泡越界裁切；按 `questionId / knowledgePointId / materialId / folderId` 独立隔离对话历史，接入 `<RichContent>` 渲染并支持多行自适应输入与一键复制。
- **R4 — 交卷快慢分离即刻沉淀与 `onShow` 四分段学情中心（Backend + Review UI）**：
  - 后端 `submit_practice` 当场同步秒判全部客观题并立即调用 `DiagnosisService.sync_practice_learning_state(..., partial_ok=True)` 写入客观错题与掌握度；主观题由 RQ Worker 精批完成后自动追平错题、掌握度并预生成 `DiagnosisReport`（即使提前退出结果页也 100% 落库）。
  - 重构 `pages/review/index.vue`：注册 `onShow` 自动刷新与明确错误重试态，接入 `GET /api/v1/mastery`（支持课程筛选），打造「顶部掌握度与薄弱考点总览（支持一键针对薄弱考点进入组卷） + 四分段视图（`考点掌握 | 错题本 | 练习记录 | 我的题库`）」。

## Acceptance Criteria

- [ ] **AC1（非阻塞与零超时）**：`backend/app/api/v1/*.py` 同步 IO 路由全部改为 `def`；在出题页发起 7 考点多题型后台异步生题后立即切回首页/学情页，`GET /materials` 等接口 `< 500ms` 正常响应，顶部任务条实时展示出题进度并在完成后可一键跳转开练。
- [ ] **AC2（无乱码结构化知识卡与零重复）**：PDF 含缺失 `/ToUnicode` 公式页经解析后无 `AB&A&`/`"#$"$` 乱码；同名考点 100% 合并去重；`course/index` 以章节分组展示无虚构考频标签的结构化速览卡与可折叠原文切片。
- [ ] **AC3（纯净视觉、可滑富文本助教与准确判题）**：全站 `.vue`/`.scss` `0` 处 `backdrop-filter`，控制台 `0` 条 `showLoading` 不配对告警；`AiCoachDrawer` 可顺滑上下滚动、右侧气泡零裁切、Markdown 与公式经 `<RichContent>` 正常渲染；判断题作答可正常满分判对，多选题中断续练不丢已选项，选项无 `A. A.` 重复前缀。
- [ ] **AC4（交卷即沉淀与实时学情）**：交卷后无需死等报告页，切入「学情」Tab（触发 `onShow`）即刻展示最新掌握度总览、错题本、练习记录与题库分段数据。
- [ ] **AC5（工程红线与质量门禁）**：全部 `.vue` 单文件保持 `<= 300` 行，后端 `max-complexity = 15`，宿主 Windows `pwsh` 下 `task verify` 全绿且 `pnpm run build:mp-weixin` 成功产出最新微信包。

## Out of Scope

- 臆造无讲义依据的「历年真题考频/押题概率」。
- 修改底部 3-Tab（`工作台 / 学情 / 我的`）顶层导航数量。
- 未经授权推送远端 Git 分支。
