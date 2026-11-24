# Research: AI 做题答疑 / 聊天多轮对话上下文与会话历史链路排查

- **Query**: 排查「AI 做题答疑 / 聊天多轮对话上下文与会话历史链路」，定位用户在题目问答区域追问「我刚开始问的什么」时 AI 仅能看到当前最新一条消息及当前题目信息、看不到更早历史消息的根因。
- **Scope**: `miniprogram/src/**`、`miniprogram/tests/useCoachChat.spec.ts`、`backend/app/api/v1/questions.py`、`backend/app/schemas/question.py`、`backend/app/services/question.py`、`backend/app/container.py`、`backend/app/integrations/llm/{coach_graph,coach_memory,agent_graph,openai,protocol}.py`、`backend/app/models/**`
- **Date**: 2026-11-18

---

## 1. 核心结论与根因定位

用户反馈的题目答疑现象（AI 回复「我这边只看得到你这一条消息哦——就是你做题时那道关于降维的选择题……你选了 A，答案是 A，做对啦。所以更早的对话内容我这里没有」并附带 2-3 条推荐追问建议）完全符合当前代码行为。**根本原因在于系统存在两条分叉的助教链路，而题目级答疑链路从前端传参、API Schema 到后端服务实现均是完全无状态（Stateless）的单轮请求**：

1. **直接根因（题目级答疑链路无状态设计）**：
   - **前端分支丢失历史/会话标识**：做题页与结果报告页挂载 `AiCoachDrawer.vue` 时传入了 `questionId`。`useCoachChat.ts` 在 `sendMessage()` 中检测到 `ctx.questionId` 存在时（`miniprogram/src/composables/useCoachChat.ts:139-153`），走 `apiAskQuestionCoach()`（`POST /questions/{id}/ask-coach`），**仅发送 `{ user_prompt, user_answer, grading_points }`**，既没有传前端本地维护的 `sessionHistories`，也没有传 `thread_id` / `session_id` / `conversation_id`（`miniprogram/tests/useCoachChat.spec.ts:188-197` 甚至显式测试并锁定了“题目端点不发送 `thread_id`”这一行为）。
   - **后端题目答疑接口不收、不存、不读历史**：`AskCoachRequest`（`backend/app/schemas/question.py:312-317`）与 `QuestionService.ask_coach()`（`backend/app/services/question.py:1591-1654`）既没有 `thread_id`/`history` 入参，也未读写注入到 `QuestionService` 的 `self.memory_store`（`CoachSessionMemory`），更没有数据库对话表。每次请求都只根据数据库查出的题目静态字段 + `user_answer` + `grading_points` + **当前最新一条 `user_prompt`**，拼装 `[system, user]` 两条 `LLMMessage` 直接调 LLM。
2. **对比链路（范围级课程/讲义/考点答疑 `POST /coach/ask`）**：
   - 当不传 `questionId`（工作台随身助教、讲义/考点助教）时，`useCoachChat.ts:164-174` 调用 `apiAskScopedCoach()`（`POST /coach/ask`）并传递 `thread_id: targetKey`（如 `kp:<id>`、`mat:<id>`、`folder:<id>`）。
   - 后端 `QuestionService.ask_scoped_coach()`（`backend/app/services/question.py:1735-1816`）会按 `f"{user_id}:{scope.key}:{thread_id}"` 读写 `CoachSessionMemory`（Redis Key `zhilian:coach:memory:*` 或进程内 LRU，**仅保留最近 6 轮、24h TTL**），并通过 `coach_graph.py` 将历史摘要拼入 prompt（同时在 `coach_graph.py` 走 RAG 检索）。
3. **跨页面持久化缺失（次要/结构性问题）**：
   - 前端 `useCoachChat.ts:58` 的 `sessionHistories` 是组件局部内存中的 `ref<Map<string, CoachMessage[]>>`，未落 Pinia 也未落 `uni.setStorageSync`；页面卸载（如从练习页 `uni.redirectTo` 跳到报告页）或关闭小程序后，前端气泡历史也会清空。
   - 后端 `backend/app/models/` 中没有任何对话历史表（未落 PostgreSQL）。

---

## 2. 前端对话与传参链路（`miniprogram/`）

### 2.1 页面挂载点与参数传递

全仓共有 4 个页面挂载了统一的 `AiCoachDrawer.vue` 抽屉组件，分为两类场景：

| 场景 | 页面文件:行号 | 传入 `AiCoachDrawer` 的核心上下文 Props | 触发的后端端点 |
| :--- | :--- | :--- | :--- |
| 做题页题目答疑 | `miniprogram/src/subpackages/practice/pages/session/index.vue:44-54` | `questionId`、`knowledgePointId`、`materialId`、`folderId`、`userAnswer`、`gradingPoints` | `POST /questions/{id}/ask-coach`（因 `questionId` 优先） |
| 报告页逐题答疑 | `miniprogram/src/subpackages/report/pages/detail/index.vue:72-80` | `questionId`、`knowledgePointId`、`userAnswer`、`gradingPoints` | `POST /questions/{id}/ask-coach`（因 `questionId` 优先） |
| 讲义/考点助教 | `miniprogram/src/subpackages/material/pages/course/index.vue:50-56` | `materialId`（讲义级）或 `knowledgePointId`（考点级），无 `questionId` | `POST /coach/ask` |
| 工作台课程助教 | `miniprogram/src/pages/index/index.vue:92-97` | `folderId`，无 `questionId` | `POST /coach/ask` |

在题目答疑场景下（如做题页 `session/index.vue:15-17,33,173-176` 点击 `PracticeQuestionBody.vue` 的「问助教」胶囊，或在报告页 `detail/index.vue:44,128-140` 点击 `AttemptResultCard` 的 `@coach`），`AiCoachDrawer` 均会拿到 `questionId`。

### 2.2 本地会话状态维护（`AiCoachDrawer.vue` + `useCoachChat.ts`）

- `miniprogram/src/components/AiCoachDrawer.vue:2` 使用 `v-if="visible"` 控制遮罩渲染，组件脚本在宿主页面存活期间不会销毁；`AiCoachDrawer.vue:85-102` 调用 `useCoachChat(...)`。
- `miniprogram/src/composables/useCoachChat.ts`:
  - **Session Key 生成**（lines 27-33）：`buildCoachSessionKey(ctx)` 按优先级生成 `q:${ctx.questionId}` > `kp:${ctx.knowledgePointId}` > `mat:${ctx.materialId}` > `folder:${ctx.folderId}` > `'global'`。
  - **本地历史存储**（line 58）：`const sessionHistories = ref<Map<string, CoachMessage[]>>(new Map())`。这是一个**仅存在于组件 `setup` 作用域内的内存 Map**，既不写入 Pinia store，也不写入 `uni.setStorageSync`。
  - **UI 渲染**（lines 69-71、`CoachMessageList.vue:24-62`）：`messageList` 读取 `sessionHistories.value.get(sessionKey.value) ?? []`。因此**同一页面实例内**切换题目或关闭重开抽屉时，UI 上仍能看到之前的气泡，给人“这是一个连续多轮对话”的直观感受；但一旦页面跳转卸载（如 `session/index.vue:200` 交卷后 `uni.redirectTo` 到 `report/pages/detail/index`）或重启小程序，前端气泡历史也会全部丢失。
  - **推荐追问点击**（`CoachMessageList.vue:41-50`、`AiCoachDrawer.vue:33`、`useCoachChat.ts:108-110`）：点击 `msg.suggestions` 会调用 `setInputQuery(suggestion)` 填入输入框（用户再点发送），这也是截图下方出现「降维还有别的好处吗」等追问词的来源。

### 2.3 发送消息请求分支（关键断点）

`useCoachChat.ts::sendMessage`（lines 120-193）：
1. 本地追加当前用户输入气泡：`appendMessage(targetKey, { id: nextId(), role: 'user', content: query })`（line 131）。
2. **分支 1 — 题目问答（`if (ctx.questionId)`，lines 139-153）**：
   - 调用 `apiAskQuestionCoach(ctx.questionId, query, ctx.userAnswer, ctx.gradingPoints)`（`miniprogram/src/api/modules/questions.ts:127-144`）。
   - 实际 HTTP 请求为 `POST /questions/${questionId}/ask-coach`，请求体固定为：
     ```ts
     {
       user_prompt: userPrompt,
       user_answer: userAnswer,
       grading_points: gradingPoints,
     }
     ```
   - **未传递** `sessionHistories` 中的历史消息（`history`/`messages`），也**未传递** `thread_id` / `session_id` / `conversation_id`（即使此时 `session/index.vue` 同样给 `AiCoachDrawer` 传了 `materialId` 和 `folderId`，因 `if (ctx.questionId) ... return` 提前返回，根本不会走 `/coach/ask`）。
3. **分支 2 — 范围问答（lines 155-181）**：
   - 仅当 `ctx.questionId` 为空时进入，调用 `apiAskScopedCoach`（`POST /coach/ask`），请求体为 `{ ...scopePayload, user_prompt: query, thread_id: targetKey }`（lines 170-174），传入了 `thread_id`。

---

## 3. 后端聊天 API 与会话历史加载链路（`backend/`）

### 3.1 数据库持久化核查

搜索 `backend/app/models/` 与 `backend/app/repositories/` 确认：**项目中没有任何用于存储 AI 助教对话记录、消息历史或会话 Thread 的数据库 ORM 表**（`models/` 下仅有 `user.py`、`material.py`、`knowledge.py`、`question.py`、`practice.py`、`base.py`）。

### 3.2 题目级答疑接口：`POST /api/v1/questions/{id}/ask-coach`

- **路由入口**：`backend/app/api/v1/questions.py:335-367`（`ask_coach`）
  - 接收 `id: uuid.UUID` 和 `payload: AskCoachRequest`。
  - 调用 `question_service.ask_coach(question_id=id, user_id=user.id, user_prompt=payload.user_prompt, user_answer=payload.user_answer, grading_points=payload.grading_points)`。
- **请求/响应 Schema**：`backend/app/schemas/question.py:312-330`
  - `AskCoachRequest` 仅定义 3 个字段：`user_prompt`、`user_answer`、`grading_points`。**没有 `thread_id`、`session_id` 或 `history` 字段**。
  - `AskCoachResponse` 仅定义 `reply` 与 `suggestions`（无 `sources`）。
- **服务层实现**：`backend/app/services/question.py:1591-1654`（`QuestionService.ask_coach`）
  - 通过 `self.question_repo.get_question_by_id(question_id, user_id)`（line 1614）鉴权并加载题目。
  - **完全没有加载或写入任何历史消息**：虽然 `AppContainer.create_question_service`（`backend/app/container.py:74-76,230-242`）在初始化 `QuestionService` 时注入了 `memory_store=self.coach_memory`（`CoachSessionMemory` 单例），但 `QuestionService.ask_coach()` 方法内部**完全没有引用 `self.memory_store`**，也没有调用 `coach_graph` 或 `search_adapter`。

### 3.3 对比：范围级答疑接口 `POST /api/v1/coach/ask`

- **路由入口**：`backend/app/api/v1/questions.py:370-389`（`ask_scoped_coach`）
- **请求 Schema**：`ScopedCoachRequest`（`backend/app/schemas/question.py:333-357`）包含可选 `thread_id: str | None`。
- **服务层与会话记忆加载**：`QuestionService.ask_scoped_coach`（`backend/app/services/question.py:1735-1816`）
  - 构造租户+范围+线程隔离键：`memory_key = f"{user_id}:{scope.key}:{thread_id}"`（line 1764）。
  - 调用 `self.memory_store.load(memory_key)`（line 1769）读取历史轮次，并将本轮 `(user_prompt, result.reply)` 通过 `self.memory_store.append(...)`（line 1802）回写。
- **`CoachSessionMemory` 实现**（`backend/app/integrations/llm/coach_memory.py:21-145`）：
  - **窗口限制**：`DEFAULT_MAX_TURNS = 6`（仅保留最近 6 轮），且单轮文本会截断（`user` 截断至 500 字符，`assistant` 截断至 800 字符，lines 24-25）。
  - **存储介质**：优先使用 Redis（Key `zhilian:coach:memory:{thread_key}`，TTL 24 小时 `DEFAULT_TTL_SECONDS = 86400`）；若未配置 Redis 或 Redis 异常，降级为进程内 `OrderedDict` LRU（上限 `DEFAULT_MAX_LOCAL_THREADS = 512`，多 Worker/进程重启即丢失）。
  - **LangGraph Checkpointer**：`coach_graph.py:675,734-736` 每次 `run_coach_graph` 都新建 `MemorySaver()`，仅用于单次图执行内部流转，不承担跨请求记忆（`coach_graph.py:19-21` 注释已说明）。

---

## 4. Prompt 拼装与 LLM 调用链路（`backend/`）

### 4.1 题目级答疑 Prompt 拼装（`QuestionService.ask_coach`）

在 `backend/app/services/question.py:1618-1654` 中，每次调用均按以下固定模板构建 **仅 2 条消息** 的列表：

1. **System Message**（lines 1618-1626, 1644）：
   - 角色设定与输出篇幅规范（150~250 字，先结论后 2~3 条要点，给出 2~3 条不超过 15 字的 `suggestions`）。
2. **User Message**（lines 1627-1642, 1645）按顺序拼接 `context_parts`：
   - `【题干】\n{question.stem}`
   - `【题目类型】\n{question.question_type}`
   - `【标准答案】\n{question.answer}`
   - `【选项】\n{json.dumps(question.options, ensure_ascii=False)}`（若 `question.options` 非空）
   - `【解析】\n{question.analysis}`（若 `question.analysis` 非空）
   - `【学生作答】\n{user_answer}`（若 `user_answer` 非空）
   - `【采分点/关键词】\n{', '.join(grading_points)}`（若 `grading_points` 非空）
   - `【学生追问】\n{user_prompt}`（**仅包含本次最新这一条输入**）
3. **LLM 调用与序列化**：
   - `self.llm.generate_structured(messages=[system, user], response_model=AskCoachResponse, options=LLMOptions(temperature=0.65, max_tokens=900))`（lines 1649-1653）。
   - 经 `OpenAICompatibleLLMAdapter.generate_structured` -> `run_structured_agent_workflow`（`backend/app/integrations/llm/agent_graph.py:57-107`）注入 `submit_structured_output` Tool Schema -> `OpenAICompatibleLLMAdapter.generate`（`backend/app/integrations/llm/openai.py:170-203`）通过 `_serialize_message` 原样发往 `{base_url}/chat/completions`。
   - **关键缺失**：`messages` 数组中没有任何历史 `user` / `assistant` 消息，也没有教材 RAG 原文切片（`source_snippet` 也未注入）。

这精确解释了用户截图中的 AI 回复内容：
- AI 能说出题干（`【题干】`）、学生选了 A（`【学生作答】`）、标准答案是 A（`【标准答案】`）、并给出推荐追问（`suggestions`），同时诚实回答「我这边只看得到你这一条消息哦……更早的对话内容我这里没有」——因为发往 LLM 的请求体里确实只有这一条包含了题目上下文 + 最新提问 `「我刚开始问的什么」` 的 `user` 消息。

### 4.2 对比：范围级答疑 Prompt 拼装（`coach_graph.py`）

在 `backend/app/integrations/llm/coach_graph.py` 中，历史消息的处理方式为：
- `_format_history(history, max_turns=6)`（lines 275-280）把最近最多 6 轮拼成文本块 `【此前对话（用于理解指代，事实仍只依据资料）】\n学生：...\n助教：...`（单条 user 截断 300 字，assistant 截断 400 字）。
- 在 `generate_overview`（line 492）、`rewrite_query`（line 559）、`generate_grounded`（line 605）中，将该文本块作为前缀拼入单条 `LLMMessage(role="user", ...)`，而非多条原生的 `user`/`assistant` 对话消息；同时 `_augment_followup_query`（lines 283-287）在追问文本 `<= 16` 字时拼上上一轮提问以辅助向量/关键词检索。
- 此外，系统提示词 `_GROUNDED_SYSTEM_PROMPT`（lines 416-429）明确约束「6. 若有此前对话，请据此理解「那」「这个条件」等指代，但事实仍只依据资料；」。

---

## 5. Files Found

| Path | Role |
| :--- | :--- |
| `miniprogram/src/components/AiCoachDrawer.vue` | AI 助教抽屉组件（全局统一入口，接收 `questionId`/范围 props） |
| `miniprogram/src/components/CoachMessageList.vue` | 聊天气泡列表、快捷提问、追问建议（`suggestions`）与参考来源渲染 |
| `miniprogram/src/composables/useCoachChat.ts` | 对话状态机与请求路由：内存 `sessionHistories` Map；按 `questionId` 分支调用不同后端 API |
| `miniprogram/src/api/modules/questions.ts` | `apiAskQuestionCoach`（不传历史/线程 ID）与 `apiAskScopedCoach`（传 `thread_id`） |
| `miniprogram/src/types/question.ts` | `ScopedCoachParams`（含 `thread_id?: string`） |
| `miniprogram/src/types/diagnosis.ts` | `AskCoachResponse` 与 `CoachSource` 类型定义 |
| `miniprogram/src/subpackages/practice/pages/session/index.vue` | 做题页挂载 `AiCoachDrawer`，传入 `questionId` 等题目上下文 |
| `miniprogram/src/subpackages/practice/components/PracticeQuestionBody.vue` | 做题页题目体右上角「问助教」触发按钮 |
| `miniprogram/src/subpackages/report/pages/detail/index.vue` | 报告详情页挂载 `AiCoachDrawer`，传入 `questionId` 等题目上下文 |
| `miniprogram/src/subpackages/material/pages/course/index.vue` | 讲义详情页挂载 `AiCoachDrawer`（无 `questionId`，走范围助教） |
| `miniprogram/src/pages/index/index.vue` | 首页工作台挂载 `AiCoachDrawer`（无 `questionId`，走课程范围助教） |
| `miniprogram/tests/useCoachChat.spec.ts` | 前端助教单测（第 188-197 行显式断言题目端点不发送 `thread_id`） |
| `backend/app/api/v1/questions.py` | 路由定义：`POST /questions/{id}/ask-coach`（line 335）与 `POST /coach/ask`（line 370） |
| `backend/app/schemas/question.py` | `AskCoachRequest`（无会话/历史字段）与 `ScopedCoachRequest`（有 `thread_id`） |
| `backend/app/services/question.py` | `QuestionService.ask_coach`（无状态单轮，未用 `memory_store`）与 `ask_scoped_coach`（使用 `memory_store` + `coach_graph`） |
| `backend/app/container.py` | `AppContainer.coach_memory`（`CoachSessionMemory` 单例初始化并注入 `QuestionService`） |
| `backend/app/integrations/llm/coach_memory.py` | `CoachSessionMemory`（Redis / 进程内 LRU 滑动窗口记忆，6 轮、24h TTL） |
| `backend/app/integrations/llm/coach_graph.py` | 范围助教 LangGraph 工作流（历史注入、短追问扩写、RAG 检索与引用校验） |
| `backend/app/integrations/llm/agent_graph.py` | `run_structured_agent_workflow`（结构化 Tool Call 自愈包装） |
| `backend/app/integrations/llm/openai.py` | `OpenAICompatibleLLMAdapter`（序列化 `LLMMessage` 列表至 `/chat/completions`） |
| `backend/tests/unit/services/test_coach_scoped.py` | `ask_scoped_coach` 多轮 `thread_id` 记忆测试 |
| `backend/tests/unit/services/test_question_service.py` | `QuestionService.ask_coach` 单元测试（lines 1487-1560） |

---

## 6. Relevant `.trellis/spec/` Files

- `.trellis/spec/frontend/index.md`
- `.trellis/spec/frontend/component-guidelines.md`
- `.trellis/spec/frontend/network-contract.md`
- `.trellis/spec/backend/index.md`
- `.trellis/spec/backend/directory-structure.md`
- `.trellis/spec/guides/cross-layer-thinking-guide.md`

---

## 7. Caveats / Open Questions

1. **原有测试契约显式锁定了无 `thread_id` 行为**：`miniprogram/tests/useCoachChat.spec.ts:188-197` 存在专门用例 `does not send thread_id on the question-scoped coach endpoint`，若为 `ask-coach` 接入 `thread_id` 或 `history`，需同步更新前端类型、API 调用及该测试契约。
2. **多轮历史边界与持久化策略选择**：
   - 若仅复用 `CoachSessionMemory`（Redis / 内存 LRU），题目答疑将受限于 **6 轮滑动窗口 + 24h TTL**（`coach_memory.py:21-22`），且当用户追问「我刚开始问的什么」时，超过 6 轮的早期消息仍会被裁剪，无 Redis 时服务重启也会丢失；前端在页面销毁后仍无法从服务端恢复历史气泡。
   - 若需要跨页面刷新/重进后仍可回看历史气泡及完整多轮记忆，需评估是否新增会话/消息持久化表或接口，或者由前端携带完整/窗口裁剪后的 `history` 并在本地按 `userId + questionId` 持久化。
3. **题目答疑缺少 RAG 原文依据**：`QuestionService.ask_coach()` 目前只读取题目表字段（`stem`/`options`/`answer`/`analysis`），既未注入 `question.source_snippet_id` 对应讲义片段，也未走 RAG 检索；当用户在题目中追问延伸概念（如「降维还有别的好处吗」）时，模型完全依赖自身预训练参数回答，无法给出教材依据来源。
4. **做题页 vs 报告页会话隔离键**：两页传入 `useCoachChat` 的 `buildCoachSessionKey` 均为 `q:${questionId}`，若未来接入服务端 `CoachSessionMemory`，需确认同题在「做题中（无答案/作答中）」与「交卷后（已判题）」是否应共享同一 `thread_id`，以及是否允许做题中请求把标准答案提前泄漏给前端答疑（注意：`ask_coach` 当前 line 1630 无条件把 `【标准答案】` 拼进了 LLM 上下文，即使在做题未交卷阶段也是如此）。
