# Research: Issue 1 — UI模糊 & AI助教字体太大、太长、太生硬

- **Query**: Investigate "UI模糊,而且这个ai助教字体太大,太长,太生硬" across frontend UI/CSS/rendering (`miniprogram/src/`) and backend AI Coach prompts/responses (`backend/app/`).
- **Scope**:
  - `miniprogram/src/components/{AiCoachDrawer,CoachMessageList,RichContent}.vue`, `miniprogram/src/utils/richText.ts`, `miniprogram/src/composables/useCoachChat.ts`, `miniprogram/src/styles/*.scss`, `miniprogram/src/{App.vue,manifest.json,pages.json}`, `miniprogram/vite.config.ts`, `miniprogram/dist/`
  - `backend/app/api/v1/questions.py`, `backend/app/services/question.py`, `backend/app/integrations/llm/{coach_graph.py,openai.py,protocol.py,agent_graph.py}`, `backend/app/schemas/question.py`, `backend/app/core/config.py`
  - Recent git history (`git log -n 10 --oneline`)
- **Date**: 2026-11-17

---

## Findings

### 1. 「UI模糊」成因与现状核实

1. **历史 `backdrop-filter: blur(2px)` 已在最新提交 `d422efe` 移除，但需核对编译产物与真机/开发者工具缓存**
   - 在 `d422efe` (`2026-11-17 22:24:21`, `feat(frontend): add zero-blur z-index system, RichContent AST, context-scoped coach, and background task bar`) 之前，`miniprogram/src/styles/modal.scss` 对 `.modal-overlay` 与 `.sheet-overlay` 设置了 `backdrop-filter: blur(2px);`，且 `miniprogram/src/App.vue` 中 `--color-bar-bg` 为 `rgba(255, 255, 255, 0.95)`。
   - 当前源码 `miniprogram/src/styles/modal.scss:1-28` 与 `miniprogram/src/App.vue:92-96` 已改为纯色/半透遮罩（`--color-overlay: rgba(28, 25, 23, 0.45)`, `--color-bar-bg: #FFFFFF`），移除了 `backdrop-filter`；`miniprogram/dist/dev/mp-weixin` 与 `miniprogram/dist/build/mp-weixin` 当前 `.wxss` 中也已无 `backdrop-filter` 或 `blur(`。
   - 唯一保留的 `transform` 仅为纯 CSS 对勾旋转：`miniprogram/src/styles/tokens.scss:48` (`transform: rotate(-45deg);`)，全仓无 `scale(...)`、无 `filter:`、无 `zoom`、无 `<canvas>`。

2. **当前源码中仍会导致视觉发虚/模糊的渲染因素**
   - **Windows/Chromium 端字体灰度抗锯齿 (`App.vue:111-112`)**：
     - `page` 全局声明了 `-webkit-font-smoothing: antialiased;`（同时编译进了 `miniprogram/dist/dev/mp-weixin/app.wxss:96`）。
     - 在 Windows 微信开发者工具（Chromium 内核）及 PC 端微信小程序（非 2x Retina 屏）上，`-webkit-font-smoothing: antialiased` 会关闭 ClearType 次像素渲染，导致浅纸底色（`#F7F5F0` / `#FFFFFF`）上的深墨文字与浅灰副文本（`#78716C` / `#A8A29E`）笔画发虚、对比度偏软。
   - **微信 `<rich-text>` 节点内联 `rpx` 与未固定基础库/配置 (`richText.ts:21-38`, `manifest.json:7`, `pages.json`)**：
     - `miniprogram/src/utils/richText.ts:21-38` 直接在 `<rich-text :nodes>` 的内联 `style` 字符串中使用 `rpx`（如 `margin:14rpx 0 8rpx`, `padding:12rpx 18rpx`, `border-left:6rpx solid ...`, `codeBlockInner` 的 `font-size:24rpx`）。这些字符串不经过 Vite/PostCSS 处理，依赖微信原生 `<rich-text>` 运行时解析；且 `miniprogram/dist/dev/mp-weixin/project.config.json:15` 中 `"libVersion": ""` 未锁定基础库版本，`"style": "v2"` 与 Skyline 渲染器均未启用。
     - `miniprogram/src/manifest.json:7` 设置 `"transformPx": false`；样式中的 `1px` 边框（如 `AiCoachDrawer.vue:136,141,156,171,175`、`modal.scss:46,55`）与大扩散半径阴影（`App.vue:98-100`: `--shadow-sheet: 0 -12rpx 36rpx rgba(28, 25, 23, 0.12)`、`--shadow-modal: 0 12rpx 36rpx rgba(28, 25, 23, 0.14)`）在低 DPR 模拟器缩放下也会显得边缘不够锐利。

---

### 2. 「AI助教字体太大」的前端排版根因

1. **`CoachMessageList.vue` 对助手主回复未传入 `compact`**
   - `miniprogram/src/components/CoachMessageList.vue:27`:
     `<RichContent v-else :content="msg.content" />`（未传 `compact`），而紧邻其下的延伸提示 `CoachMessageList.vue:31` 传了 `compact`（`<RichContent :content="msg.prompt" compact muted />`）。
   - 全仓其他内容型富文本消费点（`AttemptResultCard.vue:25,35,41,48,56,64,71,80`、`QuestionPreviewCard.vue:26,40,45,54,66`、`ReportSummaryCard.vue:38,54,57`、`KnowledgeSnippetModal.vue:41,68,111`）均使用 `compact`。
   - `miniprogram/src/components/RichContent.vue:27-39` 尺寸定义：
     - 默认 `.rich-content`: **`font-size: 28rpx; line-height: 1.65;`**
     - 紧凑 `.rich-content.compact`: **`font-size: 24rpx; line-height: 1.55;`**

2. **Markdown 标题在 `28rpx` 基线基础上进一步 `em` 放大 (`richText.ts:40-45`)**
   - `HEADING_SIZES` 相对 `28rpx` 放大倍数：
     - `h1`: `1.18em`（约 **`33.0rpx`**）
     - `h2`: `1.12em`（约 **`31.4rpx`**）
     - `h3`: `1.06em`（约 **`29.7rpx`**）
     - `h4`: `1.02em`（约 **`28.6rpx`**）
   - 叠加 `STYLES.headingBase`（`line-height:1.45; margin:14rpx 0 8rpx;`, `richText.ts:22`）、`STYLES.paragraph`（`margin:0 0 10rpx 0; line-height:1.65;`, `richText.ts:23`）、`STYLES.listItem`（`line-height:1.6;`, `richText.ts:25`）。

3. **抽屉内字号层级倒挂 & 气泡窄宽度加剧垂直拉长**
   - `AiCoachDrawer.vue` 周边控件字号明显更克制：
     - 标题 `.coach-name`: `30rpx` (`AiCoachDrawer.vue:146`)
     - 副标题 `.coach-desc`: `22rpx` (`AiCoachDrawer.vue:148`)
     - 语境条 `.context-text`: `22rpx` (`AiCoachDrawer.vue:163`)
     - 输入框 `.chat-textarea`: `26rpx`, `line-height: 1.45` (`AiCoachDrawer.vue:176`)
     - 快捷提问 `.quick-chip`: `24rpx` (`CoachMessageList.vue:126`)
     - 追问建议 `.suggestion-item`: `23rpx` (`CoachMessageList.vue:159`)
     - 来源摘录 `.source-excerpt`: `22rpx` (`CoachMessageList.vue:163`)
   - 但对话气泡正文（`.msg-text` 用户 `28rpx` @ `CoachMessageList.vue:143`，助手 `RichContent` `28rpx` + 标题 `29.7~33rpx`）与标题接近、显著大于输入框(`26rpx`)和快捷芯片(`24rpx`)。
   - 抽屉容器高度 `78vh`（`max-height: 82vh`, `AiCoachDrawer.vue:129`），`.chat-inner` 水平 padding `28rpx`（`CoachMessageList.vue:121`），`.msg-bubble` 为 `max-width: 82%; padding: 20rpx 24rpx; line-height: 1.55;`（`CoachMessageList.vue:132-135`）。在较窄气泡（有效文本宽约 ~`520rpx`）中渲染 `28~33rpx` 字号与 `1.65` 行高，视觉上显得臃肿、占满屏幕；在宽屏/PC 微信下 `rpx` 等比放大后尤为明显。

---

### 3. 「AI助教回复太长、太生硬」的后端 Prompt 与参数根因

后端存在两条 AI 助教调用链（`backend/app/api/v1/questions.py:335-388`），均通过 `self.llm.generate_structured(...)` 调用大模型（默认配置 `LLMSettings.model = "qwen-max"`, `backend/app/core/config.py:278`；`OpenAICompatibleLLMAdapter`, `backend/app/integrations/llm/openai.py:49,179-189`）：

1. **题目级助教：`POST /api/v1/questions/{id}/ask-coach`**
   - 入口：`backend/app/api/v1/questions.py:335-367` -> `QuestionService.ask_coach` (`backend/app/services/question.py:1576-1634`)。
   - System Prompt (`backend/app/services/question.py:1603-1606`)：
     > `"你是一位耐心的专业 AI 助教。请结合给出的题目题干、标准答案、解析与学生追问，为学生提供通俗生动、逻辑严密、循序渐进的答疑解析，引导学生掌握核心考点并给出延伸思考建议。"`
   - Schema (`backend/app/schemas/question.py:320-325`)：`AskCoachResponse(reply: str, suggestions: list[str])`，其中 `reply` 描述为 `"AI 助教通俗生动的深度解析内容"`。
   - LLM Options (`backend/app/services/question.py:1627`)：`LLMOptions(temperature=0.7)`，**未设置 `max_tokens`**（保持 `None`）。
   - **问题**：无篇幅/字数上限、无移动端分段/对话口吻约束、无禁止「一、二、三、/长篇大论」格式约束；`reply` 描述为“深度解析内容”，诱导模型输出教科书式长篇分点解析。

2. **范围级助教（课程/资料/知识点）：`POST /api/v1/coach/ask`**
   - 入口：`backend/app/api/v1/questions.py:370-388` -> `QuestionService.ask_scoped_coach` (`backend/app/services/question.py:1636-1717`) -> `answer_with_course_evidence` (`backend/app/integrations/llm/coach_graph.py:125-154`)。
   - 检索上下文 (`coach_graph.py:42-77`)：最多取 `8` 条切片（`[:8]`），每条截断到 `800` 字符（`item.content[:800]`），合计最高 ~`6400` 字讲义片段拼入 User Prompt。知识点作用域还会拼接前缀 `f"关于知识点「{point.name}」：{user_prompt}"`（`backend/app/services/question.py:1684`）。
   - System Prompt (`backend/app/integrations/llm/coach_graph.py:85-90`)：
     > `"你是课程助教。只根据给定资料回答，不足以回答就明确说明。citation_ids 只能选给定切片 ID，不得编造来源。"`
   - Schema (`coach_graph.py:17-20`)：`CoachDraft(reply: str, suggestions: list[str], citation_ids: list[uuid.UUID])`。
   - LLM Options (`coach_graph.py:98`)：**`LLMOptions(temperature=0.2)`，同样未设置 `max_tokens`**。
   - **问题**：
     1. Prompt 极其简短，只强调“只根据给定资料回答”，没有任何语气（口语化/亲和力/先给结论再展开）、篇幅（如 150~250 字内、短段落）或结构约束。
     2. `temperature=0.2` 极低温度叠加大量原始讲义/教材切片，使模型倾向于机械复述/汇编讲义大纲（如 `一、... 1. ... 2. ...`），呈现强烈的学术八股与生硬感，且因 `max_tokens=None` 毫无长度收敛。
     3. 前端传来的 `quickPrompts`（如 `"用大白话解释这个考点"`、`useCoachChat.ts:35-53`）若遇到 `0.2` 温度与“严格按给定资料”指令，仍容易输出带多层编号的密集讲义综述而非通俗短答。

---

## Files Found

| Path | Role |
| --- | --- |
| `miniprogram/src/components/AiCoachDrawer.vue` | AI 助教底部抽屉壳层（`78vh`、header/context-bar/footer `26rpx`） |
| `miniprogram/src/components/CoachMessageList.vue` | 消息列表与气泡（`max-width: 82%`；第 27 行 `<RichContent>` 未传 `compact`） |
| `miniprogram/src/components/RichContent.vue` | 富文本容器（默认 `28rpx`/`1.65`，`compact` 为 `24rpx`/`1.55`） |
| `miniprogram/src/utils/richText.ts` | Markdown + LaTeX AST 编译器（`HEADING_SIZES` 1.02–1.18em；节点内联 style 含 `rpx`） |
| `miniprogram/src/composables/useCoachChat.ts` | 助教上下文路由（`/questions/{id}/ask-coach` vs `/coach/ask`）与快捷提问预设 |
| `miniprogram/src/styles/modal.scss` | 共享浮层与底抽屉样式（已在 `d422efe` 去除 `backdrop-filter: blur(2px)`） |
| `miniprogram/src/App.vue` | 全局 Design Tokens（含 `-webkit-font-smoothing: antialiased` 与 `--shadow-*`） |
| `miniprogram/src/manifest.json` | 小程序工程配置（`transformPx: false`） |
| `miniprogram/src/pages.json` | 页面路由与全局窗口样式 |
| `miniprogram/vite.config.ts` | UniApp Vite 构建配置 |
| `backend/app/api/v1/questions.py` | 助教路由 `/questions/{id}/ask-coach` (L336) 与 `/coach/ask` (L371) |
| `backend/app/services/question.py` | `ask_coach` (L1576-1634, prompt L1603-1606, `temp=0.7`, 无 `max_tokens`) 与 `ask_scoped_coach` (L1636-1717) |
| `backend/app/integrations/llm/coach_graph.py` | LangGraph 资料溯源助教（`generate` L73-100, prompt L87-90, `temp=0.2`, 无 `max_tokens`, 8x800 切片） |
| `backend/app/schemas/question.py` | `AskCoachRequest` / `AskCoachResponse` / `ScopedCoachRequest` / `ScopedCoachResponse` (L312-395) |
| `backend/app/integrations/llm/openai.py` | OpenAI/DashScope 适配器（默认 `qwen-max`；仅当 `options.max_tokens is not None` 时传 `max_tokens`） |
| `backend/app/core/config.py` | `LLMSettings` 默认模型 `qwen-max` (L277-280) |

---

## Relevant `.trellis/spec/` Files

- `miniprogram` 前端规范：
  - `.trellis/spec/frontend/index.md`
  - `.trellis/spec/frontend/component-guidelines.md`
  - `.trellis/spec/frontend/quality-guidelines.md`
  - `.trellis/spec/frontend/api-payload-contracts.md`
- `backend` 后端规范：
  - `.trellis/spec/backend/index.md`
  - `.trellis/spec/backend/directory-structure.md`
  - `.trellis/spec/backend/quality-guidelines.md`
  - `.trellis/spec/backend/error-handling.md`
- 跨层思考指南：
  - `.trellis/spec/guides/cross-layer-thinking-guide.md`

---

## Caveats / Open Questions

1. **构建产物时效**：`miniprogram/dist/build/mp-weixin`（`22:16`）与 `miniprogram/dist/dev/mp-weixin`（`22:21`）时间戳略早于提交 `d422efe`（`22:24:21`），尽管当前 `dist/` `.wxss` 已无 `backdrop-filter`，仍需确认微信开发者工具是否加载了最新编译产物以及模拟器显示缩放比例（如 <100% 缩放也会导致整体界面发糊）。
2. **`<rich-text>` `rpx` 实测行为**：`richText.ts` 内联 `style` 中的 `rpx` 单位在不同微信基础库版本下解析表现建议在真机与开发者工具复核；若需跨端稳定，需评估是否改用 `em`/`px` 或缩小基准字号。
3. **跨页面 `RichContent` 复用影响**：`RichContent.vue` 同时被题目题干、解析、知识点定义与 AI 助教消息复用；若只缩小助教气泡字号，优先在 `CoachMessageList.vue` 传 `compact`（或专用紧凑档）而避免误伤题干正文字号。
4. **LLM 调用与 `max_tokens`**：`coach_graph.py` 与 `question.py` 走 `generate_structured`（内部含 Pydantic 校验 + `agent_graph.py` Tool Call / JSON 输出），若后续增加 `max_tokens`，需留足 JSON 字段与 `suggestions` / `citation_ids` 的开销，避免被截断触发校验失败。
