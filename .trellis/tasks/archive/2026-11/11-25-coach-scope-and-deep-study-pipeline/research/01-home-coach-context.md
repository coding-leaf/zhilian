# Research: 工作台主界面 AI 助教语境绑定诊断与全局无绑定 + 可选聚焦课程方案

- **Query**: 调查工作台主界面 AI 助教为什么静默绑定到第一个课程（如「软件工程」），盘点全端助教入口与后端能力，设计「主界面全局无绑定助教 + 可选手动聚焦课程」完整前后端契约与改动清单。
- **Scope**: `miniprogram/src/pages/index/**`、`miniprogram/src/components/{AiCoachDrawer,CoachMessageList}.vue`、`miniprogram/src/composables/useCoachChat.ts`、`miniprogram/src/stores/folder.ts`、`miniprogram/src/api/modules/questions.ts`、所有分包助教挂载点；`backend/app/api/v1/questions.py`、`backend/app/schemas/question.py`、`backend/app/services/{question,_coach_context}.py`、`backend/app/integrations/llm/{coach_graph,coach_memory}.py`、`backend/app/integrations/search/{protocol,pgvector,fake}.py`、`backend/app/repositories/{question,knowledge,diagnosis}.py`。
- **Date**: 2026-11-25

---

## 1. 核心结论（根因定位）

经逐行核查源码，工作台主界面不存在硬编码 `folders[0]` 的代码，但存在 **3 个相互强耦合的设计缺陷**，在真实使用中共同造成「打开主界面 AI 助教被迫/静默绑定到第一门课程（如软件工程），且快捷提问错位为“这份资料”」的体验问题：

1. **缺陷 A — 主界面助教语境与讲义列表筛选态强耦合（无独立状态、无抽屉内切换器）**：
   - `miniprogram/src/pages/index/index.vue:92-97` 将 `AiCoachDrawer` 的 `:folder-id` 直接绑定到 `activeFolderDetail?.id`，而 `activeFolderDetail`（`index.vue:147-150`）完全派生自 `folderStore.currentFolderId`（顶部 `FolderFilterBar.vue` 的讲义筛选 Tab）。
   - `miniprogram/src/stores/folder.ts:29-34` 新建课程时会执行 `folders.value.unshift(newFolder)` 并立刻把 `currentFolderId.value = newFolder.id`；此外用户在工作台点过任意课程筛选（例如紧挨「全部讲义」的第一个课程「软件工程」）后，由于 `folderStore` 是全局单例且切 Tab/关闭抽屉均不重置，后续再点右下角悬浮「AI 助教」按钮时就会静默继承该课程，标题仍叫「课程随身助教」，抽屉内没有任何切换或解除绑定的入口。
2. **缺陷 B — 默认「全部讲义（`all`）」与「未分类（`__none__`）」态下主界面助教是“假开放、真死锁”**：
   - 当 `folderStore.currentFolderId` 为初始默认值 `'all'`（`stores/folder.ts:14`）或 `'__none__'` 时，`activeFolderDetail` 为 `null` → `:folder-id="undefined"`。
   - `index.vue:156` 却给用户展示误导性语境文案：「当前处于智练全景工作台，你可以随时询问学习方法、考点定义或复习建议。」
   - 实际上 `useCoachChat.ts:299-305` 返回 `quickPrompts = []`（空白提问区），用户一发消息即被 `useCoachChat.ts:415-422` **本地拦截死拒**：「请先选择一门课程或打开一份讲义，再向助教提问。」——**逼迫用户必须先去选一门课程（通常就是首个课程「软件工程」）才能使用助教**。
   - 根因在后端：`ScopedCoachRequest.validate_scope`（`backend/app/schemas/question.py:430-440`）强制校验 `folder_id` / `material_id` / `knowledge_point_id` **必须且只能传 1 个**，全仓不存在全局/跨课程无绑定助教能力。
3. **缺陷 C — 课程级快捷提问误用讲义级模板**：
   - `useCoachChat.ts:248-252, 303` 将 `ctx.materialId || ctx.folderId` 合并返回 `MATERIAL_QUICK_PROMPTS`，导致在工作台聚焦课程时出现「帮我梳理**这份资料**的核心框架」（课程下可能有多份资料，语义错位）；而无绑定全局态则直接返回空数组 `[]`。

---

## 2. 前端全链路核查：全仓 5 个助教入口矩阵

全仓通过 `rg` 确认只有 **4 个页面挂载了 `AiCoachDrawer`**（构成 **5 个实际入口**）；目前没有独立的「课程详情页」，`pages/review/index.vue` 与 `pages/profile/index.vue` 未挂载助教。

| # | 入口场景 | 源码位置 | 传入 Scope Props | 标题 `title` | 语境条 `contextText` | 快捷提问 `quickPrompts` | 后端端点 | `sessionKey` / `thread_id` | `history` 兜底 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **工作台主界面**（悬浮按钮） | `pages/index/index.vue:86-97, 147-157` | `:folder-id="activeFolderDetail?.id"`（`all`/`__none__` 时为 `undefined`） | 写死 `"课程随身助教"` | 有课程：`当前聚焦课程「X」...`<br>无课程：`当前处于智练全景工作台...`（误导） | 有课程：`MATERIAL_QUICK_PROMPTS`（错位）<br>无课程：`[]`（空白） | 有课程：`POST /coach/ask`<br>无课程：**本地拦截拒发** | `folder:<fid>` 或 `global` | **无**（`apiAskScopedCoach` 未传） |
| 2 | **资料详情页**（底栏「讲义助教」） | `subpackages/material/pages/course/index.vue:28-31, 50-56, 149-154` | `:material-id="course.materialId.value"`（`coachPointId` 为 `undefined`） | `讲义助教: <title>` | `当前讲义包含 N 个核心考点...` | `MATERIAL_QUICK_PROMPTS`（3 条） | `POST /coach/ask`（`material_id`） | `mat:<mid>` | 无 |
| 3 | **考点详情弹窗**（「向 AI 助教追问」） | `subpackages/material/components/KnowledgeSnippetModal.vue:111-113` → `course/index.vue:46, 50-56, 137-147` | `:knowledge-point-id="coachPointId"`（`:material-id` 置为 `undefined`） | `考点答疑: <kp.name>` | `当前考点：<name>。概要：<summary>` | `KP_QUICK_PROMPTS`（4 条） | `POST /coach/ask`（`knowledge_point_id`） | `kp:<kpid>` | 无 |
| 4 | **沉浸作答页**（题目区「问助教」） | `subpackages/practice/pages/session/index.vue:34, 45-55, 151-168` | `:question-id` + `:knowledge-point-id` + `:material-id` + `:folder-id` + `:user-answer` + `:grading-points` | `考点答疑 · <kpName>` 或 `本题实时答疑` | `考点：<kpName>。题干：<stem>` | `QUESTION_QUICK_PROMPTS`（4 条） | `POST /questions/{id}/ask-coach`（`questionId` 最高优先级） | `q:<qid>` | **有**（最多 20 条） |
| 5 | **结果/诊断报告页**（逐题卡片「问助教」） | `subpackages/report/pages/detail/index.vue:46, 76-84, 141-153` | `:question-id` + `:knowledge-point-id` + `:user-answer` + `:grading-points` | `考点答疑 · <kpName>` 或 `针对本题答疑` | `考点：<kpName>。题干：<stem>` | `QUESTION_QUICK_PROMPTS`（4 条） | `POST /questions/{id}/ask-coach` | `q:<qid>`（与作答页同题延续） | **有**（最多 20 条） |

### 2.1 `useCoachChat.ts` 会话隔离与持久化机制核查

`miniprogram/src/composables/useCoachChat.ts` 的既有会话隔离设计非常健壮，应保留并扩展：
- **优先级决定 `sessionKey`**（`useCoachChat.ts:226-232`）：`q:<questionId>` > `kp:<knowledgePointId>` > `mat:<materialId>` > `folder:<folderId>` > `global`。
- **多用户 + 多上下文隔离**（`useCoachChat.ts:43-53, 266-268`）：
  - 内存 Map 键：`<userId>:<sessionKey>`；
  - 持久化存储键：`zhilian:coach:history:<userId>:<sessionKey>`；
  - LRU 索引键：`zhilian:coach:lru:<userId>`（上限 `MAX_PERSISTED_SESSIONS = 30`，单会话上限 `MAX_PERSISTED_MESSAGES = 30`）。
- **防串台与孤儿气泡保护**（`useCoachChat.ts:107-121, 374-379, 442-452`）：
  - 发送时捕获 `targetUserId` / `targetKey` / `targetScopedKey`，异步回包写回原会话，切语境不串台；
  - 持久化前 `stripOrphanUserTurns` 剔除尾部无助教回复的孤儿用户气泡；错误气泡仅放内存不落盘，支持 `retryMessage` 无重复气泡重试。

---

## 3. 后端助教端点与 RAG 架构能力盘点

### 3.1 现有端点全量清单（`backend/app/api/v1/`）

核查全部 10 个路由模块后确认，全仓**仅存在 2 个**助教端点（均在 `backend/app/api/v1/questions.py`），**不存在** `/folders/{folder_id}/ask-coach`、`/materials/{material_id}/ask-coach` 或独立 `/diagnosis/...` 助教端点：

1. **`POST /api/v1/questions/{id}/ask-coach`**（`backend/app/api/v1/questions.py:377-411` → `QuestionService.ask_coach`，`backend/app/services/question.py:1990-2059`）
   - 能力：结合题干、答案解析、教材原文切片、学生作答（未作答时启用防剧透引导）、`thread_id` + `history` 冷启动兜底；
   - 记忆键：`{user_id}:question:{question_id}:{effective_thread}`（`CoachSessionMemory`，Redis 优先 + 进程内 LRU 降级，默认 12 轮 / 24h TTL）；
   - 连接池安全：LLM 调用前主动 `session.commit()` 释放只读事务连接（`question.py:2047-2048`）。

2. **`POST /api/v1/coach/ask`**（`backend/app/api/v1/questions.py:414-433` → `QuestionService.ask_scoped_coach`，`backend/app/services/question.py:2140-2226`）
   - 入参 `ScopedCoachRequest`（`backend/app/schemas/question.py:416-440`）：`folder_id` / `material_id` / `knowledge_point_id` 强制三选一、`user_prompt`、`thread_id`（**缺少 `history` 兜底**）；
   - 范围解析 `_resolve_coach_scope`（`question.py:2061-2138`）：
     - `folder_id`：查 `FolderRepository.get_by_id` + `QuestionRepository.list_current_versions_for_folder` + `KnowledgeRepository.list_by_folder_scope`（过滤 `current_version_id`）；
     - `material_id`：查 `MaterialRepository.get_material_by_id(..., exclude_archived_folder=True)` + `KnowledgeRepository.list_by_material_id`；
     - `knowledge_point_id`：查 `KnowledgeRepository.get_by_id` + 校验归属资料未删未归档且为当前版本 + `get_snippets_for_point` 作为 `allowed_snippet_ids` 白名单；
     - 无任何 ID 时直接 `raise ValueError("必须指定答疑范围")`。
   - 空资料硬短路（`question.py:2165-2166`）：`if not scope.material_ids: return ScopedCoachResponse(reply="当前范围没有已解析完成的资料，暂时无法依据资料回答。")`。
   - RAG 图编排（`backend/app/integrations/llm/coach_graph.py:488-768`）：
     - `route_intent`（确定性分类）：`chitchat` / `noise` / `overview`（正则命中且有 `overview_context`） / `detail_qa`；
     - `detail_qa` 路径：`retrieve_and_rerank` → `check_evidence`（无候选或精排分低于 `rewrite_threshold` 且未改写过 → `rewrite_query` 重试一次）→ 命中则 `generate_grounded` + `verify_citations`，未命中则 `honest_fallback`（死拒："这份资料里暂时没找到能可靠回答这个问题的依据..."）。
   - 系统提示词特征（`coach_graph.py:453-480`）：严格闭卷 RAG（"只根据给定资料回答"），不具备通用学科兜底回答能力。

### 3.2 扩展全局模式前发现的 2 个高危后端隐患

1. **隐患 1 — 多资料检索存在 O(N) Embedding + SQL 性能炸弹**：
   - `backend/app/integrations/llm/coach_graph.py:340-352` 的 `_search_pool` 对 `state["material_ids"]` 逐个循环调用 `search.search(query=..., material_id=material_id, version_id=expected_version)`。
   - `PgvectorHybridSearchAdapter.search`（`backend/app/integrations/search/pgvector.py:284`）每次调用都会请求一次外部 `embed_query(query)` API + 执行一次向量/关键词 SQL 检索。若用户在全局模式下有 15~30 份就绪讲义，单次提问会触发 **15~30 次外部 Embedding 调用**，极易触发微信小程序 **60 秒 `networkTimeout` 超时断连**。
2. **隐患 2 — 直接对 `search.search(material_id=None)` 检索会泄露已删/归档/历史版本切片**：
   - `PgvectorHybridSearchAdapter._recall_snippets`（`pgvector.py:211-218`）仅过滤 `MaterialSnippet.user_id == user_id` 以及可选的 `material_id`、`version_id`、`allowed_snippet_ids`，**并未 join `Material` / `MaterialFolder`**。
   - 若全局检索简单传 `material_id=None, version_id=None`，会召回软删除资料（`is_deleted=True`）、归档课程下资料（`archived_at IS NOT NULL`）、解析失败资料及已被重解析覆盖的旧版 `MaterialVersion` 切片！
   - **正解**：在 `SearchOptions`（`backend/app/integrations/search/protocol.py:41-61`）新增可选白名单字段 `allowed_version_ids: tuple[uuid.UUID, ...] | None = None`，由 `QuestionService` 通过一条租户+未删+未归档+READY SQL 解析出用户全部合法 `current_version_id` 集合传入；`PgvectorHybridSearchAdapter._recall_snippets` 追加 `MaterialSnippet.version_id.in_(allowed_version_ids)`（`FakeSearchAdapter` 同步支持），将全局及多资料课程检索从 **N 次 Embedding + N 次 SQL 降为 1 次 Embedding + 1 次 SQL**，且 100% 阻断脏切片泄露。

---

## 4. 目标方案设计：主界面全局无绑定助教 + 可选手动聚焦课程

### 4.1 产品交互与状态解耦原则

1. **彻底解耦工作台筛选与助教语境**：
   - 工作台讲义筛选继续使用 `folderStore.currentFolderId`；
   - 主界面 AI 助教拥有独立的页面态 `coachFocusedFolderId`（`ref<string | undefined>(undefined)`），**默认永远为 `undefined`（全局学习模式）**，绝不随 `folderStore.currentFolderId` 或新建课程动作静默绑定到第一门课或任何单门课。
   - 若用户已聚焦某课程，随后在工作台把该课程归档/删除，自动通过 `watch` / `computed` 安全回落为 `undefined`（全局模式）。
2. **清晰的语境栏与一键切换体验（适配微信真机红线）**：
   - 在 `AiCoachDrawer.vue` 头部下方，当传入 `selectableFolders` 时渲染轻量子组件 `CoachScopeSelector.vue`：
     - **模式提示条**：
       - 全局模式：`全局学习模式（未限定课程 · 支持全库检索与通用答疑）`
       - 聚焦课程：`聚焦课程「<课程名>」· 仅检索本课程 <N> 份就绪资料`
     - **一键切换胶囊条**（采用 `scroll-view scroll-x` 横滑胶囊，与 `FolderFilterBar.vue` 视觉同源，**不使用原生 `<picker>`**，规避 `position: fixed` 抽屉内原生弹层与 `<textarea :fixed="true">` 冲突及嵌套弹窗层级问题）：
       - 首个固定胶囊：`全部资料（全局）`
       - 后续胶囊：当前用户全部未归档课程（`selectableFolders`），可展示就绪资料数角标；点击即时切换 `coachFocusedFolderId`，同步切换独立对话流与快捷提问。
   - **其他 4 个入口（讲义 / 考点 / 作答 / 报告）**不传 `selectableFolders`，继续保持原固定 `context-bar` 展示，零回归、零视觉噪音。
3. **分语境精准快捷提问**（`miniprogram/src/composables/useCoachChat.ts`）：
   - `questionId` → `QUESTION_QUICK_PROMPTS`（不变）
   - `knowledgePointId` → `KP_QUICK_PROMPTS`（不变）
   - `materialId` → `MATERIAL_QUICK_PROMPTS`（保留「帮我梳理这份资料的核心框架」等讲义专属语术）
   - `folderId` → **新增 `FOLDER_QUICK_PROMPTS`**：
     - `梳理这门课程的核心知识脉络`
     - `这门课有哪些高频易混概念？`
     - `总结这门课的关键公式与适用条件`
   - 无绑定全局态（`global`）→ **新增 `GLOBAL_QUICK_PROMPTS`**：
     - `帮我规划今天复习重点`
     - `汇总我最近的薄弱考点`
     - `直接解答学习概念问题`
     - `帮我梳理跨课程高频易错点`

---

### 4.2 后端 API 与编排契约设计（完全向后兼容）

#### A. 复用并升级 `POST /api/v1/coach/ask`（无需新增分裂路由）

- **请求体 `ScopedCoachRequest`**（`backend/app/schemas/question.py`）：
  ```python
  CoachScopeKind = Literal["global", "folder", "material", "knowledge_point"]

  class ScopedCoachRequest(BaseModel):
      scope: CoachScopeKind | None = Field(
          default=None,
          description="显式答疑范围；不传且三类 ID 均为空时默认 global",
      )
      folder_id: uuid.UUID | None = None
      material_id: uuid.UUID | None = None
      knowledge_point_id: uuid.UUID | None = None
      user_prompt: str = Field(min_length=1, max_length=1000)
      thread_id: str | None = Field(default=None, min_length=1, max_length=128)
      history: list[AskCoachHistoryItem] | None = Field(
          default=None,
          max_length=24,
          description="可选前端兜底历史消息（服务端记忆为空时冷启动恢复）",
      )
  ```
- **严格校验矩阵（防静默回退到第一门课）**：
  1. `id_count = sum(x is not None for x in (folder_id, material_id, knowledge_point_id))`；若 `id_count > 1` → 422（`"不能同时指定多个答疑范围"`）。
  2. 若 `scope == "global"`：要求 `id_count == 0`，否则 422（`"全局模式不能携带课程/资料/考点标识"`）。
  3. 若 `scope == "folder"`：要求 `folder_id is not None`，否则 422（`"课程模式必须指定 folder_id"` —— **绝不静默取第一门课**）。
  4. 若 `scope == "material"`：要求 `material_id is not None`，否则 422。
  5. 若 `scope == "knowledge_point"`：要求 `knowledge_point_id is not None`，否则 422。
  6. 若 `scope is None`：
     - `id_count == 0` → 归一化为 `scope = "global"`；
     - `id_count == 1` → 按所传 ID 自动归一化为对应 `scope`（完全兼容现有调用方与测试；注：现有单测 `test_no_scope_raises_value_error` 需明确测试显式契约或区分 `scope="folder"` 缺 ID 场景）。

- **响应体 `ScopedCoachResponse`**（向后兼容增量字段）：
  ```python
  class ScopedCoachResponse(AskCoachResponse):
      sources: list[CoachSourceResponse] = Field(default_factory=list)
      mode: Literal["grounded", "overview", "study_profile", "general", "chitchat", "fallback"] | None = None
  ```
  前端可据此在气泡上做轻量来源提示（例如 `mode === 'general'` 时显示「通用学习解答」，有 `sources` 时显示「参考讲义 (N)」）。

#### B. 全局模式后端数据准备与双轨 RAG 流程

1. **新增仓储查询**：
   - `QuestionRepository.list_ready_current_versions_for_user(user_id: uuid.UUID) -> dict[uuid.UUID, uuid.UUID]`（`backend/app/repositories/question.py`）：
     - `select(Material.id, Material.current_version_id).outerjoin(MaterialFolder, Material.folder_id == MaterialFolder.id)`
     - `where(Material.user_id == user_id, Material.is_deleted.is_(False), Material.status == MaterialStatus.READY.value, Material.current_version_id.is_not(None), (Material.folder_id.is_(None)) | (MaterialFolder.archived_at.is_(None)))`
     - 严格包含「未归档课程的就绪资料 + 未分类就绪资料」，排除软删、未就绪与已归档课程资料。
   - 在 `QuestionService.__init__` 新增 `self.diagnosis_repo = DiagnosisRepository(session)`（已核对 `backend/pyproject.toml` 6 条 `import-linter` 契约，`app.services -> app.repositories` 完全合规）。
2. **新增全局学习画像拼装**（`backend/app/services/_coach_context.py`）：
   - `build_global_study_context(folders, materials_count, weak_points, recent_points, max_chars=2800) -> str | None`：
     - 汇总用户课程清单（课程名 + 就绪资料数 + 考点数）；
     - 汇总薄弱考点 Top 8（通过 `DiagnosisRepository.list_mastery_records_by_user(user_id)` 按 `mastery_score` 升序筛选 `< 0.6` 或薄弱 `< 0.4`，并关联 `KnowledgePoint.name` 与所属课程/讲义名，标出掌握度与练习/答对次数）；
     - 汇总待巩固/代表性知识点，供「规划今天复习重点」「汇总最近薄弱考点」直接作答。
   - **连接池红线**：所有 DB 只读查询完成后，在调用 `run_coach_graph`（Embedding / Rerank / LLM）前保持既有 `self.session.commit()` 释放连接。
3. **检索单次化改造**（`backend/app/integrations/search/{protocol,pgvector,fake}.py` + `coach_graph.py`）：
   - `SearchOptions` 新增 `allowed_version_ids: tuple[uuid.UUID, ...] | None = None`。
   - `PgvectorHybridSearchAdapter._recall_snippets`：当 `allowed_version_ids is not None` 时追加 `MaterialSnippet.version_id.in_(allowed_version_ids)`（空 tuple 直接短路返回空结果）；`FakeSearchAdapter.search` 同步过滤 `c.version_id in allowed_version_set`。
   - `coach_graph._search_pool`：当 `len(state["material_ids"]) > 1` 且提供了 `material_versions` 时，提取 `tuple(sorted(set(material_versions.values()), key=str))` 传给 `SearchOptions.allowed_version_ids`，执行 **1 次 `search.search(query=query, user_id=..., material_id=None, version_id=None, options=...)`**，再在返回集上校验 `item.material_id in material_versions and item.version_id == material_versions[item.material_id]`。
4. **`coach_graph.py` 全局模式双轨路由（仅当 `allow_general_fallback=True` 时生效）**：
   - `CoachGraphConfig` 或 `run_coach_graph` 新增参数：`allow_general_fallback: bool = False`、`study_profile_context: str | None = None`。
   - **单课程 / 单资料 / 单考点**（`allow_general_fallback=False`）：行为 100% 保持原闭卷 RAG 契约（无证据走 `honest_fallback`）。
   - **全局模式**（`allow_general_fallback=True`）：
     - `chitchat` / `noise`：全局助教口吻（介绍支持「全库资料检索、薄弱考点复习规划、通用学习概念答疑」），推荐话题优先薄弱考点名称，否则返回全局默认建议。
     - `study_plan` / `overview`（命中「复习重点 / 复习计划 / 薄弱考点 / 错题 / 学情 / 总结课程」等词）：走 `generate_study_plan`（复用 `generate_overview` 风格 + 专属 `_GLOBAL_STUDY_PLAN_PROMPT`），严格基于 `study_profile_context` 输出今日复习重点与薄弱考点清单；若用户暂无资料/练习记录，则诚实告知当前库为空并给出通用学习建议。
     - `detail_qa`（具体概念/题目/知识点提问）：
       - 若 `material_ids` 非空：先执行单次全库混合检索 + 精排（至多一次改写）；若命中高质量证据 → `generate_grounded` + `verify_citations`（返回带 `sources` 引用切片的答案，点击可跳对应讲义）。
       - 若 `material_ids` 为空，或全库检索+改写后无满足阈值的讲义证据 → 路由至 **`generate_general`** 节点（使用 `_GLOBAL_GENERAL_SYSTEM_PROMPT`）：不死拒，直接用清晰、有条理的助教口吻解答通用学科概念/方法，同时首句或末尾轻提示「以上结合通用学科知识解答（当前资料库暂无直接对应讲义）」，`cited=[]` 严禁虚构任何来源切片。
5. **会话记忆隔离与冷启动兜底**：
   - `memory_key = f"{user_id}:{scope.key}:{thread_id}"`：
     - 全局：`{user_id}:global:global`（或前端传的 `thread_id`）；
     - 聚焦课程：`{user_id}:folder:{folder_id}:folder:{folder_id}`；
   - `ask_scoped_coach` 复用 `ask_coach` 的 `_load_question_history` 思路（可抽公共方法 `_load_coach_history`），当 Redis/内存记忆为空且前端传入 `history` 时冷启动恢复并回填 `memory_store`。

---

### 4.3 前端改动设计与微信红线/行数门禁核对

#### A. 文件行数与拆分策略（严守 `.vue <= 300` 行）

| 文件 | 当前行数 | 改造策略 | 预估行数 |
|---|---|---|---|
| `miniprogram/src/pages/index/index.vue` | 286 行 | 抽离 `pages/index/composables/useHomeCoach.ts` 管理 `showCoachDrawer` / `coachFocusedFolderId` / `coachTitle` / `coachContextText`；`index.vue` 仅传 props 给 `AiCoachDrawer`，净减少约 10 行 | ~276 行（`<= 300`） |
| `miniprogram/src/components/AiCoachDrawer.vue` | 185 行 | 接入 `CoachScopeSelector.vue`，透传 `selectableFolders` / `activeFolderId` / `modeLabel` 与 `@select-folder` 事件；新增约 25 行 | ~210 行（`<= 300`） |
| **新建** `miniprogram/src/components/CoachScopeSelector.vue` | 新建 | `virtualHost: true`，展示当前模式条（全局学习模式 / 聚焦课程）+ `scroll-view scroll-x` 胶囊选择器（「全部资料·全局」+ 各课程）；全用 `var(--color-*)` Token | ~140 行（`<= 300`） |
| **新建** `miniprogram/src/pages/index/composables/useHomeCoach.ts` | 新建 | 管理主界面助教独立聚焦状态（默认 `undefined` 即全局），监听 `folderStore.folders` 防止归档课程悬空 | ~65 行 |
| `miniprogram/src/composables/useCoachChat.ts` | 472 行 | 新增 `FOLDER_QUICK_PROMPTS` / `GLOBAL_QUICK_PROMPTS`；移除 `415-422` 本地死拒，改为发 `{ scope: 'global', user_prompt, thread_id, history }`；所有 scoped 调用补传 `history` | ~495 行（`.ts`） |
| `miniprogram/src/types/question.ts` & `diagnosis.ts` | 202 / 116 行 | `ScopedCoachParams` 增加 `scope?: CoachScopeKind` 与 `history?: AskCoachHistoryItem[]`；`AskCoachResponse` 增加可选 `mode?: string` | 小幅增量 |
| `miniprogram/src/api/modules/questions.ts` | 207 行 | `apiAskScopedCoach` 保持 `POST /coach/ask`（`timeout: LONG_REQUEST_TIMEOUT_MS`） | 几乎无变化 |

#### B. 会话缓存 Key 隔离验证

- 主界面默认全局：`ctx = { scopeMode: 'global' }`（无 `folderId`）→ `sessionKey = 'global'` → 存储 `zhilian:coach:history:<userId>:global` → 后端 `thread_id = 'global'`、`memory_key = <userId>:global:global`。
- 主界面手动切换聚焦「软件工程」：`ctx = { folderId: '<se-id>' }` → `sessionKey = 'folder:<se-id>'` → 存储 `zhilian:coach:history:<userId>:folder:<se-id>` → 后端 `thread_id = 'folder:<se-id>'`、`memory_key = <userId>:folder:<se-id>:folder:<se-id>`。
- 切换瞬间 `useCoachChat` 的 `watch([activeUserId, sessionKey])` 自动加载对应历史；若全局态正在请求中而用户切到「软件工程」，`targetScopedKey` 保证回包仍落入 `global` 历史不污染课程会话；清空按钮仅清当前 `sessionKey`。

#### C. 微信小程序红线逐项核对

- **零原生 `<picker>` 嵌套**：使用 `scroll-view scroll-x` 胶囊条替代下拉菜单/原生 `<picker>`，避免与 `AiCoachDrawer` 内 `<textarea :fixed="true">` 产生原生层级冲突；
- **零动态 `import()` / 零 `PATCH` / 零 Web-only API**：全部通过现有 `POST /coach/ask` 走 `request.ts`；
- **零非法 WXSS 选择器 / 零裸 Hex / 零 Emoji**：`CoachScopeSelector.vue` 严禁使用 `[disabled]`、`*`、`:deep()`，所有颜色走 `var(--color-*)`；
- **按钮 `:loading` 必配 `:disabled`**、`<button>` 重置 `&::after { border: none; }`；
- **超时控制**：单次全局检索优化（1 次 Embedding + 1 次 SQL）确保后端耗时远低于微信小程序 60s `networkTimeout` 上限。

---

## 5. Files Found

| Path | Role |
|---|---|
| `miniprogram/src/pages/index/index.vue` | 工作台主页；当前将 `AiCoachDrawer` 的 `:folder-id` 强耦合到 `activeFolderDetail?.id`（`L92-97, L147-157`） |
| `miniprogram/src/pages/index/components/FolderFilterBar.vue` | 顶部课程筛选胶囊条，操控 `folderStore.currentFolderId` |
| `miniprogram/src/stores/folder.ts` | 课程状态仓库；默认 `'all'`，`createFolder` 会置顶并切到新建课程（`L14, L29-34`） |
| `miniprogram/src/components/AiCoachDrawer.vue` | 全端共用助教抽屉组件（185 行）；需接入可选语境选择器 |
| `miniprogram/src/components/CoachMessageList.vue` | 助教消息流与空态快捷提问芯片渲染（168 行） |
| `miniprogram/src/composables/useCoachChat.ts` | 助教状态机、会话 Key/LRU 持久化、快捷提问分发与无 scope 本地死拒拦截（`L226-252, L299-305, L415-434`） |
| `miniprogram/src/api/modules/questions.ts` | `apiAskQuestionCoach` 与 `apiAskScopedCoach`（`L171-207`） |
| `miniprogram/src/types/question.ts` | `AskCoachParams`、`ScopedCoachParams` 类型契约（`L105-127`） |
| `miniprogram/src/types/diagnosis.ts` | `AskCoachResponse`、`CoachSource` 响应类型（`L76-87`） |
| `miniprogram/src/subpackages/material/pages/course/index.vue` | 讲义助教 + 考点助教双入口挂载页（`L50-56, L137-154`） |
| `miniprogram/src/subpackages/material/components/KnowledgeSnippetModal.vue` | 考点弹窗「向 AI 助教追问」触发入口（`L111-113`） |
| `miniprogram/src/subpackages/practice/pages/session/index.vue` | 沉浸作答页实时题目助教入口（`L45-55, L151-168`） |
| `miniprogram/src/subpackages/report/pages/detail/index.vue` | 诊断报告页逐题助教入口（`L76-84, L141-153`） |
| `backend/app/api/v1/questions.py` | 仅有的 2 个助教路由：`POST /questions/{id}/ask-coach`（`L377-411`）与 `POST /coach/ask`（`L414-433`） |
| `backend/app/schemas/question.py` | `ScopedCoachRequest`（当前强制三选一校验 `L416-440`）与 `ScopedCoachResponse`（`L512-513`） |
| `backend/app/services/question.py` | `QuestionService.ask_coach`（`L1990-2059`）、`_resolve_coach_scope`（`L2061-2138`）、`ask_scoped_coach`（`L2140-2226`） |
| `backend/app/services/_coach_context.py` | 结构化知识点概览与推荐话题纯内存拼装（`L1-71`）；待新增全局学习画像拼装 |
| `backend/app/integrations/llm/coach_graph.py` | Adaptive + Corrective RAG 图编排与系统提示词（`L255-888`）；待增单次多版本检索与全局双轨兜底 |
| `backend/app/integrations/llm/coach_memory.py` | 助教多轮滑动窗口记忆（Redis + 内存 LRU，`L1-147`） |
| `backend/app/integrations/search/protocol.py` | `SearchOptions` 与 `SearchProtocol`（`L40-108`）；待增 `allowed_version_ids` |
| `backend/app/integrations/search/pgvector.py` | `_recall_snippets` 向量+关键词召回（`L192-244`）；待支持 `allowed_version_ids` |
| `backend/app/integrations/search/fake.py` | 测试用假检索适配器（`L94-156`）；待同步支持 `allowed_version_ids` |
| `backend/app/repositories/question.py` | `list_current_versions_for_folder`（`L589-606`）；待增 `list_ready_current_versions_for_user` |
| `backend/app/repositories/diagnosis.py` | `list_mastery_records_by_user`（`L182-199`）与 `list_weak_knowledge_point_ids`（`L614-624`） |
| `backend/app/container.py` | `AppContainer.create_question_service` 依赖装配（`L257-269`） |

---

## 6. Relevant `.trellis/spec/` Files（候选加入 `implement.jsonl` / `check.jsonl`）

- `.trellis/spec/backend/directory-structure.md`（同步 `def` 路由红线、6 条 `import-linter` 分层边界、Service/Repository 职责边界）
- `.trellis/spec/backend/database-guidelines.md`（短事务/外部 LLM 调用前 `session.commit()` 释放连接池契约）
- `.trellis/spec/backend/quality-guidelines.md`（`max-complexity = 15`、`mypy --strict`、`ruff`、coverage `>= 80%`）
- `.trellis/spec/frontend/index.md`（`.vue <= 300` 行门禁、零裸 Hex、零 Emoji、安全区适配、助教双端点约定）
- `.trellis/spec/frontend/mp-weixin-compatibility.md`（微信兼容红线：零原生 `<picker>` 嵌套冲突、`<textarea :fixed="true">`、禁用 WXSS 选择器、`LONG_REQUEST_TIMEOUT_MS = 60000`）
- `.trellis/spec/frontend/network-contract.md`（`request.ts`、`RequestError`、`silentToast` 与超时契约）
- `.trellis/spec/guides/cross-layer-thinking-guide.md`（`ScopedCoachRequest` / `ScopedCoachResponse` 跨层字段一致性核对）

---

## 7. Caveats / Open Questions

1. **后端既有单测语义同步**：`backend/tests/unit/services/test_coach_scoped.py:659`（`test_no_scope_raises_value_error`）当前断言不传任何 scope ID 会抛 `ValueError`。升级后需明确区分：不传任何 ID 且 `scope=None` 或 `scope="global"` 进入全局模式；而传 `scope="folder"` 且 `folder_id=None`（或 `id_count > 1`、`scope="global"` 却带了 `folder_id`）仍严格抛校验错误/422，并补充相应单测。
2. **工作台切换筛选 Tab 时助教是否自动跟随**：本方案明确推荐**默认完全不跟随**（主界面点开悬浮助教永远默认全局模式，只有在助教抽屉内手动点选课程胶囊才聚焦该课程），彻底根除“用户在首页看某个文件夹时无意绑死助教”的错位；若产品后续希望“在工作台筛选了某门课后，于抽屉内提示一个轻按钮『快速切到当前浏览课程「X」』”，也可作为零侵入增强，但不应默认静默绑定。
3. **全局模式引用切片跳转**：全局模式命中资料切片返回 `sources` 时，现有 `AiCoachDrawer.vue:120-124` 的 `openSource(materialId)` 已通过 `safeNavigateTo('/subpackages/material/pages/course/index?id=...')` 支持跨课程直达任意来源讲义，无需额外改动路由。
4. **多资料/全局检索的 `version_ids` 上限**：若极端用户拥有数百份就绪资料，建议在 `list_ready_current_versions_for_user` 按 `Material.updated_at.desc()` 取合理上限（如 100 份）或直接让 PostgreSQL `IN (...)` 走索引，并在 SQLite 单测环境保持全量兼容。
