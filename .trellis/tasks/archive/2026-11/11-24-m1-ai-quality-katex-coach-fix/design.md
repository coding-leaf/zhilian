# Technical Design: M1 — AI 自主质检、KaTeX 公式渲染器与 502/AI 助教修复

> **对应 PRD**：`prd.md`
> **调研文档**：`../11-24-product-ux-quality-upgrade/research/{01-autonomous-ai-quality-gate,04-math-renderer-evaluation,05-intermittent-errors-and-ui-polish}.md`

---

## 1. AI 自主质检闭环设计（R1）

1. **确定性预检纯函数升级（`backend/app/core/algorithms/question_quality.py`）**：
   - 保持 `app.core.algorithms` 零外部依赖约束（`import-linter` 契约）。
   - 新增 `_strip_latex_commands(text)` 与中文 2-gram + 英文词统一分词（大小写不敏感），修复 `NO_SOURCE` 误杀数学题。
   - 预检结果引入三态严重度：`QualitySeverity = Literal["pass", "soft_flag", "hard_defect"]`：
     - `HARD_DEFECT`：空题干/空答案/空选项/单选多选选项数非法/答案不在选项中/空来源切片/字面重复；
     - `SOFT_FLAG`：低词面重合（数学/改写题常见）、向量相似度 `0.88..0.95` 疑似冲突或近似重复、边界歧义；
     - `PASS`：直接放行，零额外 LLM 成本。
   - `_question_llm_schemas.py` 在校验归一化阶段剥离选项答案前缀（如 `"A. 支持向量"` → `"A"`）。
2. **批量 AI Judge + 定向 Repair（NEW `backend/app/services/_question_quality_judge.py`）**：
   - 输入本批非 `PASS` 题目列表 + 对应来源切片上下文，合并为 **1 次** `llm.generate_structured` 批量裁决（`max_tokens=4096`，避免思考模型截断）：
     - `approve`：仅对 `SOFT_FLAG` 有效（若模型误对 `HARD_DEFECT` 返回 `approve`，代码强制降级为 `reject`）；
     - `repair`：返回修正后的完整题干/选项/答案/解析，**必须重新通过确定性结构校验**才算合格，否则降级为 `reject`；
     - `reject`：直接丢弃。
   - 缺口定向补抽（`_question_generation.py`）：按轮次升温 `0.3 → 0.5 → 0.65`，并在 Prompt 中显式附带「已通过题干摘要（禁止重复）」，只补抽剩余缺口数，不再盲目全量重抽。
3. **终态零 `pending_review` 与历史数据迁移**：
   - `QuestionService` 仅落库合格 `QuestionStatus.AVAILABLE` 题目，不再把 `last_unqualified_questions` 写入 `pending_review`；若整批合格数为 0，异步任务标记 `FAILED` 并附明确可读原因。
   - 新建可逆迁移 `0013_soft_delete_legacy_pending_review_questions.py`：将历史 `status = 'pending_review'` 且 `is_deleted = False` 的记录软删除（`is_deleted = True`），`downgrade` 仅恢复对应迁移标记/条件（保持安全可逆）；`list_question_batches`/`list_questions` 默认过滤 `AVAILABLE`，API 响应维持 `pending_count=0`/`pending_review_count=0` 向后兼容。
   - 前端清理 7 处 `pending_review`/「待审核」展示，彻底去掉人工审题心智负担。

---

## 2. `katex@0.16.x` AST 公式渲染器与自托管字体设计（R2）

1. **依赖与构建**：
   - 在 `miniprogram/package.json` 安装锁定 `katex@0.16.21`（实测 276 KB minified，零 `import()`、零 `\p{}`、`es2018` 安全）。
   - 将 KaTeX 核心 `.woff2` + `.ttf` 字体文件（源自 `node_modules/katex/dist/fonts/`）静态复制到 `backend/app/static/fonts/katex/`，在 `backend/app/main.py` 通过 `StaticFiles` / 专用只读路由挂载 `/static/fonts/katex/` 并附 `Cache-Control: public, max-age=31536000, immutable` 与 CORS 头。
2. **KaTeX → `RichTextNode[]` 适配器（`miniprogram/src/utils/katexRichText.ts`）**：
   - 使用 `katex.__renderToDomTree(expr, { displayMode, output: 'html', throwOnError: false, strict: false, trust: false })` 将公式编译为 DOM 节点树，再递归映射为微信小程序 `<rich-text>` 支持的 `RichTextNode[]`（`span` / `img` + `class` / `style` / `src`）。
   - 对 `SvgNode`（`\sqrt`、`\overrightarrow` 等）强制补全 `xmlns="http://www.w3.org/2000/svg"` 并编码为 `data:image/svg+xml;charset=utf-8,...`（确保 `#` 转 `%23`）；任意异常捕获并降级为可读纯文本节点，绝不白屏。
3. **定界符扫描升级（`miniprogram/src/utils/richText.ts`）**：
   - 数学解析优先级高于 Markdown `_` / `*`：
     - 块级：`$$...$$`、`\[...\]`（支持行首/行中/闭合后紧跟中文标点如 `\]。`）、裸 `\begin{...}...\end{...}`、以及 `` ```latex `` 代码围栏；
     - 行内：`$...$`（处理 `\$` 转义与 `$5` 货币防误判，支持跨软换行合并）、`\(...\)`、行内 `\[...\]`。
   - 保留现有 `richTextTable.ts` GFM 表格与 `isGarbledSnippetText` 逻辑；退役脆弱的 `richTextMath.ts` / `latexSymbols.ts` 手写转换。
4. **WXSS 样式与字体加载**：
   - 新增 `miniprogram/src/styles/katex-mp.scss`（从 `katex.min.css` 裁剪清洗：去除第三方 `@font-face`、去除 `:not(...)`/`[...]`/`*`/裸 Hex/本地 `url()`，全部颜色走 `currentColor` 或 `var(--color-*)`，100% 通过 `mpWeixinCompatGuard.spec.ts`）。
   - `App.vue` 全局引入 `katex-mp.scss` 并在 `onLaunch` 调用 `initKatexFonts()`；`RichContent.vue` 配置 `defineOptions({ options: { virtualHost: true, styleIsolation: 'apply-shared' } })`（外部 Props 零改动）。
   - `miniprogram/src/utils/katexFonts.ts`：从 `API_BASE_URL` 推导自有字体前缀 `/static/fonts/katex/`，在真机 HTTPS 或可用环境下通过 `wx.loadFontFace({ global: true })` 静默加载并本地缓存（非 HTTPS/Vitest 环境静默跳过零报错）。

---

## 3. 502 根治、AI 助教与 401 守卫设计（R3）

1. **思考模型预算与降级（`backend/app/workflows/coach_graph.py`、`integrations/llm/agent_graph.py`、`services/question.py`）**：
   - `coach_graph.py`：`classify_intent` / `rewrite_query` 放宽 `max_tokens=2048`；`generate_overview` / `generate_grounded` 与 `question.py::ask_coach` 放宽 `max_tokens=4096`。
   - 在 `generate_overview` / `generate_grounded` 捕获 `LLMResponseFormatError` 后自动降级为一次普通文本 `llm.generate(...)` 并封装为合法响应对象，消除结构化解析波动导致的 502。
   - `agent_graph.py`：在修复重试提示中附带目标 JSON schema 字段说明；抛出 `LLMResponseFormatError` 时返回脱敏友好中文提示，禁止将原始 Pydantic/Python 异常拼接进对外 `message`。
2. **快捷提问命中与短噪声短电路（`coach_graph.py`）**：
   - 扩充 `_OVERVIEW_PATTERN` 覆盖「适用条件」「关键条件」「总结」「概括」「易错点」「重难点」「梳理」「核心考点」等内置快捷提问。
   - 对纯数字/标点/重复字符短噪声（如 `"111!"`、`"???"`、`len(cleaned) <= 2` 且非有效术语）在路由层直接返回温和引导话术（附当前资料推荐提问），不走 Embedding + Rerank + Query Rewrite。
3. **前端孤儿气泡修复与未登录 401 守卫**：
   - `useCoachChat.ts`：当 `isThinking.value === true` 时阻止并发双发；请求失败时在持久化历史中移除未获答复的孤儿用户气泡（或在 UI 保留带「重试」按钮的成对失败态，重进时不残留悬空用户消息）。
   - `pages/review/index.vue`、`BackgroundTaskBar.vue`、`useMaterialUpload.ts` 补齐 `authStore.isLoggedIn()` 守卫。
   - `request.ts` & `requestError.ts`：`LONG_REQUEST_TIMEOUT_MS = 60_000`；无旧 token 时不触发无意义的 `/auth/refresh` 刷新竞争。
