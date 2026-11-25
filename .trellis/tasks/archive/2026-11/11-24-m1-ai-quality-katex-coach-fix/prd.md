# PRD: M1 — AI 自主质检零待审核、KaTeX 公式渲染器与 502/AI 助教报错根治

> **父任务**：`11-24-product-ux-quality-upgrade`
> **任务目录**：`.trellis/tasks/11-24-m1-ai-quality-katex-coach-fix`
> **优先级**：P0

---

## 1. 目标与用户价值

一次攻克真机反馈中最影响可用性的 3 大硬伤：
1. **彻底取消学生端「待审核」人工审题**，根治中文数学题 2/3 被误杀的正则缺陷，建立 AI 全自动质检/自修/重抽/淘汰闭环；
2. **用成熟 `katex@0.16.x` AST 渲染器 + 自有 FastAPI 字体托管替代易碎手写公式转化器**，彻底消除 `\[...\]` 裸露源码与 `平面 + = 0$` 吞变量问题；
3. **根治 `aliyun` 实测 502（`deepseek-flash` 思考模型 token 截断）与 AI 助教孤儿气泡、内置快捷提问拒答及未登录 401 风暴**。

---

## 2. 需求清单与实证根因映射

### R1：AI 自主质检闭环 + 彻底消除学生端「待审核」（图 1 & 图 6）

| ID | 级别 | 现状与精确锚点 | 目标行为 |
|---|---|---|---|
| **R1.1** | P0 | `backend/app/core/algorithms/question_quality.py:47,522-534` `CONTENT_WORD_PATTERN` 无中文分词且把 LaTeX 命令计入英文分母，导致中文数学题重叠率 `<0.30` 被大量误杀 `NO_SOURCE`；`:32,615-633` 窄考点向量 `>=0.88` 因选项字母不同误报 `ANSWER_CONFLICT`；`_question_llm_schemas.py:104-115` 未剥离 `"A. 内容"` 前缀。 | 修复预检纯函数：清洗 LaTeX 命令、中文改 2-gram + 大小写不敏感匹配、规整选项答案前缀；输出三态 `PASS / SOFT_FLAG / HARD_DEFECT`（数学重合低、向量 0.88–0.95 疑似冲突/重复降为 `SOFT_FLAG`，仅结构缺陷/空来源/字面重复为 `HARD_DEFECT`）。 |
| **R1.2** | P0 | `_question_generation.py:339-408` 低温 `0.3` 盲目全量重抽无修复；`question.py:489-503,998-1013` 耗尽重试后直接把不合格题落库 `status=pending_review` 暴露给学生。 | 新增 `backend/app/services/_question_quality_judge.py`：对 `SOFT_FLAG`/`HARD_DEFECT` 合并 1 次结构化 AI Judge/Repair 调用，输出 `approve`（仅允许 `SOFT_FLAG`）/ `repair`（原地修复并重过确定性结构校验）/ `reject`（丢弃）；缺口按轮次提温 `0.3 → 0.5 → 0.65` 并带「已通过题干避重」定向补抽；**终态严禁写入 `pending_review`**，仅落库合格 `available` 题；整批 0 合格题时异步任务直接标 `failed` 并返回清晰提示。 |
| **R1.3** | P0 | 存量库含旧 `pending_review` 题，前端 7 处组件/工具展示「待审核」徽章、计数与提示。 | 新增可逆 Alembic 迁移 `0013_soft_delete_legacy_pending_review_questions.py` 将存量 `pending_review` 软删除（`is_deleted=True`）；`list_question_batches`/`list_questions` 默认过滤 `available`（响应保留 `pending_count=0`/`pending_review_count=0` 兼容）；前端移除 `QuestionReadyCard.vue`、`QuestionBatchRow.vue`、`QuestionBankQuestionRow.vue`、`questionBatch.ts`、`useQuestionCompose.ts`、`useBatchPracticeLaunch.ts`、`questionBank.scss` 全部「待审核」展示。 |

### R2：引入 `katex@0.16.x` AST 渲染器 + 自托管字体替代手写转化器（图 4）

| ID | 级别 | 现状与精确锚点 | 目标行为 |
|---|---|---|---|
| **R2.1** | P0 | `miniprogram/src/utils/richText.ts:115-153,313-337` 未在行内解析 `\[...\]` 且块级仅认严格行首行尾；`$...$` 缺 `\$` 转义与跨软换行保护致 `平面 + = 0$` 吞变量；`richTextMath.ts` 将 `\frac` 压扁为 `(a)/(b)`。 | 安装锁定 `katex@0.16.21`，新增 `miniprogram/src/utils/katexRichText.ts`（`katex.__renderToDomTree` → `<rich-text>` `RichTextNode[]` 适配器，含 `SvgNode` `xmlns`+编码保护与异常纯文本降级）；重构 `richText.ts` 公式定界符扫描（块级 `$$...$$`/`\[...\]`/`\begin{env}`/`` ```latex ``，行内 `$...$` 含 `\$` 转义/`\(...\)`/行中 `\[...\]`，优先级高于 Markdown `_`/`*`）；退役 `richTextMath.ts` 手写转换，保持 `<RichContent />` 外部 Props 100% 不变。 |
| **R2.2** | P0 | WXSS 禁止本地 `url()`，第三方 CDN 不稳且 Android base64-woff2 有解码兼容坑。 | 新增裁剪版 `miniprogram/src/styles/katex-mp.scss`（0 CDN `@font-face`、0 非法 WXSS 选择器、0 裸 Hex，通过 `mpWeixinCompatGuard.spec.ts`），在 `App.vue` 全局引入并在 `RichContent.vue` 启用 `styleIsolation: 'apply-shared'`；在 FastAPI `main.py` 挂载 `/static/fonts/katex/` 只读静态字体目录（CORS + `immutable` 缓存），前端 `katexFonts.ts` 在 `App.vue::onLaunch` 静默调用 `wx.loadFontFace({ global: true })`（带本地缓存与非 HTTPS 静默跳过）。 |

### R3：根治 `aliyun` 实测 502 报错、AI 助教拒答/孤儿气泡与未登录 401（图 5）

| ID | 级别 | 现状与精确锚点 | 目标行为 |
|---|---|---|---|
| **R3.1** | P0 | `aliyun` 跑思考模型 `deepseek-flash`，而 `coach_graph.py:565`（`max_tokens=120`）、`:498,609`（`900`）与 `question.py:1968`（`900`）预算过小被思考 token 吃干导致截断 JSON 触发 **502 `LLMResponseFormatError`**；`agent_graph.py:210-218` 修复重试缺 schema 且 `:329` 把原始异常串透出前端 Toast。 | 放宽助教 `max_tokens`（路由/意图 `2048`，答疑生成 `4096`）；`coach_graph.py` 的 `generate_overview`/`generate_grounded` 增补结构化解析失败时的纯文本降级兜底（绝不因 JSON 格式直接 502）；`agent_graph.py` 异常文案脱敏不透出底层堆栈/英文异常串。 |
| **R3.2** | P1 | `useCoachChat.ts:353` 立即持久化用户气泡却在 `:122,162,295` 丢弃 `error: true` 助手气泡，导致 502 后重进出现孤儿提问（图 5）；内置快捷提问（`:222-233`）未命中 `_OVERVIEW_PATTERN` 被 `bge-reranker` 拒答；短噪声 `"111!"` 浪费整套 RAG。 | `useCoachChat.ts` 发送失败时保留可点击重试的错误提示气泡（或成对处理避免孤儿提问）并阻断 `isThinking` 期间并发双发；扩展 `_OVERVIEW_PATTERN` 覆盖「关键适用条件/总结/核心要点/易错点」等内置快捷提问；对纯数字/标点/极短无意义噪声（如 `"111!"`）直接友好引导回复，不浪费 RAG+改写。 |
| **R3.3** | P1 | `review/index.vue:165-179`、`BackgroundTaskBar.vue:51-53`、`useMaterialUpload.ts:153` 缺 `authStore.isLoggedIn()` 守卫，未登录触发 38+ 次 401；`request.ts:370-386` 对空 token 也走刷新/401；`requestError.ts:29` `LONG_REQUEST_TIMEOUT_MS=90000` 超出微信 60s 上限。 | 补齐 3 处 `authStore.isLoggedIn()` 守卫；`request.ts` 仅在本次请求确实携带了旧 token 且有 `refresh_token` 时走单飞刷新，避免空 token 401 误刷新；`LONG_REQUEST_TIMEOUT_MS` 收敛至 `60_000` 与微信上限一致。 |

---

## 3. 验收标准

1. **R1**：中文 SVM 数学题单测在确定性预检不再被 `NO_SOURCE`/`ANSWER_CONFLICT` 误杀；AI Judge `approve`/`repair`/`reject` 闭环与提温避重单测通过；新出题 100% 仅产出 `available`（0 `pending_review`）；迁移 `0013` 升级/降级对称通过；前端零「待审核」文案/徽章。
2. **R2**：图 4 全部公式（`\[ \min_{\vec{\alpha}} \frac{1}{2} \sum ... \]`、`$\vec{w}^T \vec{x} + b = 0$`、`\$5`、`\sqrt`、`pmatrix`、`cases`、非法残缺 LaTeX）经 `katexRichText` 单测全通过且零原样源码泄漏；`pnpm run build:mp-weixin` 主包 `< 900 KB`、`mpWeixinCompatGuard.spec.ts` 全绿；FastAPI `/static/fonts/katex/` 返回 200 + `immutable` 缓存头。
3. **R3**：思考模型预算下 `coach_graph` 不再截断 502，结构化失败优雅降级；内置快捷提问命中概览/成功回答；`"111!"` 不触发 RAG 直接友好引导；`useCoachChat` 失败不产生孤儿用户气泡；未登录不触发后台 401 风暴；`task verify-backend` 与 `task verify-frontend` 全绿。

---

## 4. 不在范围（已切分至 M2 / M3）

- 学情页课程联动过滤与 `QuestionCollection` 题目收纳归类 → **M2**
- PDF/PPT 智能去噪切片与复习级知识点卡片重构 → **M2**
- 全站学术纸感 UI 视觉精修 → **M3**
