# Research: 只读 Bug 审计切片 QGEN（题目生成/审核/编辑）

- **Query**: 全量只读 bug 审计 — 切片 QGEN 前后端同片核对
- **Scope**: mixed（内部代码静态审阅 + 跨层契约核对；未做真机验证）
- **Date**: 2026-09-27
- **审计范围**:
  - 后端：`backend/app/services/question.py`、`backend/app/api/v1/questions.py`、`backend/app/repositories/question.py`、`backend/app/schemas/question.py`、`backend/app/core/algorithms/question_quality.py`
  - 前端：`miniprogram/src/api/question.ts`、`subpackages/material/pages/questions/index.vue`、`components/Question{Card,AuditDrawer,ConfigDrawer,EditDrawer,RetakeDrawer}.vue`、`utils/{questionGeneration,copywriting}.ts`、`composables/{useGenerationProgress,useMaterialPolling}.ts`、`src/types/question.ts`

> 说明：所有条目均为**只读静态审阅**结论，无仓库改动。证据强度标注见每条「证据/复现」。

---

## 1. 功能 Bug 清单

### BUG-QGEN-001 — 选项字段契约不一致，客观题选项渲染为空

| 字段 | 内容 |
|---|---|
| ID | BUG-QGEN-001 |
| 级别 | **P1** |
| 切片 | QGEN |
| 层 | cross-layer |
| 位置 | 后端：`backend/app/services/question.py:564`、`backend/app/services/question.py:945-963`、`backend/app/schemas/question.py:76`、`backend/app/models/question.py`（options 列注释 `[{'key': 'A', 'content': '...'}]`）；前端：`miniprogram/src/types/question.ts:9-12`、`miniprogram/src/subpackages/material/components/QuestionCard.vue:14`、`QuestionCard.vue:59-61` |
| 现象 | 后端题目 `options` 元素为 `{key, content}`，前端 `QuestionOption` 与渲染均使用 `{key, text}`（`option.text`），导致真实接口返回的选项文本无法渲染（选项列表每项只剩 key，文本为空）。 |
| 证据/复现 | 静态跨层：`convert_llm_items_to_candidates` 对 `LLMQuestionOptionItem`（字段 `key`/`content`，见 `services/question.py:134-139`）调用 `opt.model_dump()`（`:564`），落库/响应保持 `content`；前端 `QuestionCard.vue:14` 绑定 `option.text`。后端全部测试夹具使用 `content`（如 `backend/tests/unit/services/test_question_service.py:362`、`test_question_router.py:113`、`test_question_repo.py:133`）；前端测试夹具使用 `text`（`miniprogram/tests/unit/components/QuestionCard.spec.ts:14-17`、`tests/unit/pages/questionList.spec.ts:17-20`），两端夹具各用一套字段，测试因此同时通过而掩盖真实契约错位。证据强度：**静态强（含双侧测试夹具佐证）**。 |
| 影响 | 所有客观题（单选/多选/判断）在题目列表卡片中选项正文为空，用户无法阅读选项；编辑/审核抽屉亦不展示选项。核心出题结果不可用。 |
| 修复方向 | 统一字段命名：后端响应统一输出 `text` 或在 `QuestionDetailResponse` 增加字段别名（`content` → `text`）；或前端在 api 层/类型层将 `content` 归一为 `text`。需同步 `QuestionUpdateRequest.options` 入参契约。 |

---

### BUG-QGEN-002 — 出题数量上限前后端不一致（前端 50 / 后端 20）

| 字段 | 内容 |
|---|---|
| ID | BUG-QGEN-002 |
| 级别 | **P2** |
| 切片 | QGEN |
| 层 | cross-layer |
| 位置 | 前端：`miniprogram/src/subpackages/material/components/QuestionConfigDrawer.vue:32-62`（文案 `1 到 50`、`clampCount` 上限 50）、`QuestionConfigDrawer.vue:196-200`、`miniprogram/src/subpackages/material/utils/tree.ts:145-147`（`validateQuestionConfig` 允许 1~50）；后端：`backend/app/schemas/question.py:46`（`count: ge=1 le=20`）、`backend/app/services/question.py:79-80`（`count` 1~20） |
| 现象 | 用户在配置抽屉只能看到/被允许选择 1~50 题，但后端 `count` 硬上限为 20；选择 21~50 时请求被 Pydantic 校验拒绝。 |
| 证据/复现 | 静态跨层：`validateQuestionConfig` 与步进器允许 50；`QuestionGenerateRequest.count` 为 `le=20`。后端测试 `backend/tests/unit/services/test_question_service.py:1094` 明确 `GenerateQuestionsOptions(count=21)` 抛 `ValueError`。运行时后果：`RequestValidationError` → HTTP 422 + `code=10001/message="请求参数校验失败"`（`backend/app/main.py:102-112`），前端 `request.ts:269-276` 抛 `AppError(10001,"请求参数校验失败")`，抽屉 toast「请求参数校验失败」。证据强度：**静态强（后端测试佐证）**。 |
| 影响 | 正常路径下选择 >20 题必然失败，且错误文案为通用参数错误，用户无法得知真实上限。 |
| 修复方向 | 二选一并保持两端一致：前端上限改为 20；或后端放宽 `count` 上限并同步 `distribute_count` 与 `GenerateQuestionsOptions` 校验。 |

---

### BUG-QGEN-003 — 删除原因以请求体发送，后端按 Query 读取（原因永久丢失）

| 字段 | 内容 |
|---|---|
| ID | BUG-QGEN-003 |
| 级别 | **P2** |
| 切片 | QGEN |
| 层 | cross-layer |
| 位置 | 前端：`miniprogram/src/api/question.ts:94-103`（`deleteQuestion` 传 `data: { reason }`）；后端：`backend/app/api/v1/questions.py:285`（`reason: Annotated[str | None, Query(...)]`） |
| 现象 | 前端在 DELETE 请求体携带 `reason`，后端将其声明为查询参数，`uni.request` 的 `data` 对非 GET 走请求体，后端 `reason` 实际读到 `None`，删除审计日志原因丢失（写入 `QuestionAuditLog.reason=None`）。 |
| 证据/复现 | 静态跨层：前端 `deleteQuestion(questionId,'用户手动删除')`（`pages/questions/index.vue:145`）→ `data:{reason}`；后端签名 `reason ... Query(...)`。后端自身测试通过 `params={"reason": ...}` 传递（`backend/tests/unit/api/test_question_router.py:510-524`），证明实现期望 query 而非 body。证据强度：**静态推理（中，依赖 uni.request data 语义）**。 |
| 影响 | 软删除题的审计原因不落库；用户在前端填写的删除说明不可追溯。 |
| 修复方向 | 前端改为 query 参数（如 `deleteQuestion` 拼接 `?reason=`）或后端改为 `Body`/`Query` 双兼容；同步调整前端 api 测试断言。 |

---

### BUG-QGEN-004 — 质检记录前端类型字段与后端响应不一致

| 字段 | 内容 |
|---|---|
| ID | BUG-QGEN-004 |
| 级别 | **P2** |
| 切片 | QGEN |
| 层 | cross-layer |
| 位置 | 前端：`miniprogram/src/types/question.ts:88-92`（`QuestionQualityCheck{rule_code,passed,message}`）、`:106`；后端：`backend/app/schemas/question.py:88-101`（`QuestionQualityCheckResponse{check_type,is_passed,reason,similarity_score,check_metadata}`）、`backend/app/models/question.py`（QuestionQualityCheck 列名） |
| 现象 | `QuestionGenerateResponse.quality_checks` 元素前端声明为 `rule_code/passed/message`，后端实际返回 `check_type/is_passed/reason`，字段名完全对不上。 |
| 证据/复现 | 静态跨层：后端响应模型与方法体测试一致使用 `check_type`（`backend/tests/unit/api/test_question_router.py:228,582`、`test_question_repo.py:380-387`）。前端全仓仅 `types/question.ts` 定义该类型，未见运行时消费（grep `rule_code|quality_checks` 仅命中类型定义与响应声明），故当前为潜在类型漏洞。证据强度：**静态强（后端测试佐证，前端未消费）**。 |
| 影响 | 一旦前端接入质检明细展示（如拦截原因、相似度），将读取到 `undefined`；且类型系统给出虚假安全感。 |
| 修复方向 | 将前端 `QuestionQualityCheck` 字段对齐为 `check_type/is_passed/reason/similarity_score/check_metadata`。 |

---

### BUG-QGEN-005 — offset 分页 + 本地删除后「加载更多」会跳过题目

| 字段 | 内容 |
|---|---|
| ID | BUG-QGEN-005 |
| 级别 | **P2** |
| 切片 | QGEN |
| 层 | frontend |
| 位置 | `miniprogram/src/subpackages/material/pages/questions/index.vue:100-107`（合并去重）、`:117-121`（`handleLoadMore` 翻页）、`:138-154`（删除后本地 `filter` 且 `total - 1`） |
| 现象 | 列表用 `page/page_size`（后端转 `offset`）分页。已加载第 1 页后删除其中 1 题，再点「加载更多」时后端数据集已整体前移，第 2 页 offset 对应的第 1 条（原索引 20）被跳过，用户看到少 1 题，需刷新才恢复。 |
| 证据/复现 | 推理链：删除前共 25 题、已加载 0~19；删除第 1 页某题后剩 24 题，原索引 20 前移至 19；`handleLoadMore` 请求 `page=2` → `offset=20`，返回新索引 20~23（原 21~24），原索引 20 → 新索引 19 永不被加载；本地合并仅按 id 去重，无法回补。证据强度：**静态推理（中）**。 |
| 影响 | 删除后再翻页会出现题目漏显示（状态不一致），用户误以为题目丢失。 |
| 修复方向 | 删除后重置到第 1 页重新拉取；或改游标分页（按 `created_at/id` 游标）；或删除后从本地补齐。 |

---

### BUG-QGEN-006 — 判断题与选择题题干相似时答案冲突误判

| 字段 | 内容 |
|---|---|
| ID | BUG-QGEN-006 |
| 级别 | **P2** |
| 切片 | QGEN |
| 层 | backend |
| 位置 | `backend/app/core/algorithms/question_quality.py:346-358`（`_normalize_objective_answer`）、`:609-635`（`check_answer_conflict`，跨题型遍历已有客观题且仅比较归一化答案是否相等） |
| 现象 | 答案冲突检查对所有客观题不区分题型归一化后直接比较：判断题答案为布尔（`True/False`），选择题答案为选项键集合（如 `{'A'}`）。当一道判断题与一道选择题题干相似度 ≥ 0.88（未达 0.85 字符/0.90 向量去重阈值）时，二者归一化答案永不相等，会被判为「题干高度相似但客观题标准答案冲突」而一票否决。 |
| 证据/复现 | 推理链：`_normalize_objective_answer` 对 `TRUE_FALSE` 返回 `bool|None`，其余返回 `frozenset[str]`；`check_answer_conflict` 仅 `candidate_answer != existing_answer` 即冲突，未限制同题型。相似区间 0.88~0.90 未被 DUPLICATE 拦截，会落入冲突检查。证据强度：**静态推理（中）**。 |
| 影响 | 跨题型近似题目被误判冲突，合格题被降入 `pending_review`，降低出题产出率。 |
| 修复方向 | 冲突检查限定为同题型（或同答案域）比较；跨题型不参与答案冲突判定。 |

---

### BUG-QGEN-007 — 多考点生成非原子，中途失败遗留部分已入库题目

| 字段 | 内容 |
|---|---|
| ID | BUG-QGEN-007 |
| 级别 | **P1** |
| 切片 | QGEN |
| 层 | backend |
| 位置 | `backend/app/services/question.py:1048-1146`（`generate_questions_for_knowledge_points` 循环逐考点调用）、`:1002-1013`（单考点内部 `begin_nested()` + `session.commit()`） |
| 现象 | 多考点编排按考点循环调用 `generate_questions`，而后者每次自行 `commit()`。若第 N 个考点生成失败（如 `MissingSourceSnippetError`），前 N-1 个考点的题目已提交入库，但 API 直接抛异常返回失败；用户重试会重复生成（依赖去重窗口）。 |
| 证据/复现 | 静态推理：多考点循环无跨考点统一事务；单考点在 `services/question.py:1005-1010` 显式提交。文档字符串宣称「fail-fast 抛出既有异常，不做静默降级」，但未声明已生成数据的处理；失败路径下数据库已存在部分记录。证据强度：**静态强（代码路径明确，无测试覆盖失败中间态）**。 |
| 影响 | 用户看到失败但部分题目已存在，状态不一致；重试可能产生重复或超出预期数量。 |
| 修复方向 | 多考点统一在外层事务内提交（全成或全滚），或改用单事务批量落库；失败时回滚本批次并向前端返回明确部分结果语义。 |

---

### BUG-QGEN-008 — 请求模型允许空 `question_types`（无至少一项校验）

| 字段 | 内容 |
|---|---|
| ID | BUG-QGEN-008 |
| 级别 | **P2** |
| 切片 | QGEN |
| 层 | backend |
| 位置 | `backend/app/schemas/question.py:48-56`（`question_types: list[str]`，仅默认值非空，无 `min_length` 校验）；消费点 `backend/app/services/question.py:508`（`', '.join(question_types)`） |
| 现象 | 显式传 `question_types: []` 可通过 Pydantic 校验，提示词「期望生成题型」为空字符串，模型无题型约束；前端虽以 `validateQuestionConfig` 拦截空题型，但 API 未做服务端校验。 |
| 证据/复现 | 静态：schema 无 `min_length`/validator；`GenerateQuestionsOptions` 亦不校验 `question_types` 非空（`services/question.py:64-84` 仅校验 count/difficulty/max_retries）。证据强度：**静态强（代码明确）**。 |
| 影响 | 非 UI 调用方（或未来入口）可提交空题型，生成结果题型不可控，质检与统计口径受影响。 |
| 修复方向 | 在 `QuestionGenerateRequest`/`GenerateQuestionsOptions` 增加 `question_types` 非空（及取值属于 `QuestionType`）校验。 |

---

## 2. 跨层契约核对小结（QGEN）

| 契约点 | 后端 | 前端 | 结论 |
|---|---|---|---|
| 生成入参 `material_id/version_id/knowledge_point_id(s)/count/difficulty/question_types/max_retries` | `schemas/question.py:16-59` | `types/question.ts:35-44`、`QuestionConfigDrawer` | 字段名一致；`count` 上限不一致（BUG-QGEN-002）；`question_types` 非空校验缺失（BUG-QGEN-008） |
| 生成响应 `batch_id/.../qualified_questions/pending_questions/quality_checks` | `schemas/question.py:104-129` | `types/question.ts:94-107` | 顶层字段一致；`quality_checks` 元素字段不一致（BUG-QGEN-004）；`qualified_questions[].options` 字段不一致（BUG-QGEN-001） |
| 列表 `items/total/limit/offset` | `schemas/question.py:149-155` | `types/common.ts:13-18` `PageResult` | 通过 |
| 详情 `QuestionDetailResponse` | `schemas/question.py:62-85` | `types/question.ts:14-33` | 字段名一致；`options` 子结构不一致（BUG-QGEN-001） |
| 更新 `PUT /questions/{id}` body | `schemas/question.py:158-173` | `api/question.ts:76-85` | 通过（`reason`/`edit_reason` 兼容） |
| 更新响应 | `QuestionDetailResponse` | `api/question.ts` 返回 `QuestionItem` | 通过 |
| 删除 `DELETE /questions/{id}` | `api/v1/questions.py:275-310`，`reason` 为 Query | `api/question.ts:94-103`，`reason` 在 body | **不一致**（BUG-QGEN-003） |
| 审计 `GET /questions/{id}/edit-logs` → `question_id/logs[]` | `schemas/question.py:188-211` | `types/question.ts:62-80` | 通过（`action/changed_fields/before_payload/after_payload/reason/created_at` 对齐） |
| 质检记录 `GET /materials/{id}/quality-checks` | `schemas/question.py:217-223` | 无前端 api/类型消费 | 未接入（仅类型声明，见 BUG-QGEN-004） |
| 错误码 `40003/40004/40007/40009` | `core/errors.py` | `utils/error.ts` 错误码表缺这些键，但文案由后端 message 覆盖 | 生成路径可用；表缺失属非功能项（见 caveats） |

---

## 3. 重点主题逐项结论

- **多知识点生成参数拼装**：前端同时提交 `knowledge_point_id`(首位) + `knowledge_point_ids`（`QuestionConfigDrawer.vue:287-288`），后端优先列表（`api/v1/questions.py:106-111`），字段拼装正确；分配规则与前端 `distributionHint` 一致（`services/question.py:386-407` vs `QuestionConfigDrawer.vue:185-194`）。问题在 `count` 上限（BUG-QGEN-002）与多考点非原子（BUG-QGEN-007）。
- **题型/分值校验**：后端质检核校验单/多选选项数与答案格式、判断题二值、主观题非空（`question_quality.py:423-473`）；`grading_rubric` 归一化较完整（`services/question.py:176-249`）。发现跨题型答案冲突误判（BUG-QGEN-006）与入参空题型未校验（BUG-QGEN-008）。
- **生成进度状态机与轮询生命周期**：`useGenerationProgress` 重复 `start` 前 `stop` 清理、`onUnmounted` 兜底（`useGenerationProgress.ts:60-94`），`QuestionConfigDrawer` 在 `finally` 中 `stopProgress`（`:306-309`）；`useMaterialPolling` 退避、终态终止、超时熔断、卸载清理齐全（`useMaterialPolling.ts:74-187`）。**未发现功能性缺陷**。
- **审核/编辑抽屉 props/emit 与草稿同步**：`QuestionEditDrawer` watch `[question, isOpen]` 在打开/换题时重置草稿、关闭时保留（`:105-116`）；`QuestionAuditDrawer` 在 `questionId` 变化或打开时重载（`:100-108`）；父页仅绑定 `@close`/`:visible`，emit 的 `update:visible` 无 v-model 绑定但由父显式置 false，行为一致。**未发现功能性缺陷**。
- **乐观更新与回滚**：删除为「确认 → await → 成功才本地移除」（`questions/index.vue:142-151`），无乐观更新；编辑成功后按 id 替换列表项（`:133-136`）。删除后翻页存在漏项（BUG-QGEN-005）。
- **列表分页去重**：合并按 id 去重（`:105-106`），`hasMore` 依据 `listData.length < total`（`:88`）；结构性漏项见 BUG-QGEN-005。
- **题目去重与质量门限边界**：阈值常量与题面一致（向量 0.90 / 字符 0.85 / 冲突 0.88 / 实词 0.30 / 最短 6 字符，`question_quality.py:20-42`）；`max_existing_questions_window=500`（`:42`）。边界比较均为闭区间，与注释一致；跨题型冲突见 BUG-QGEN-006。
- **错误码映射**：生成失败经 `AppError` 文案优先，业务错误展示后端 message（`questionGeneration.ts:56-62`）；422 统一映射为 `10001/请求参数校验失败`（`main.py:102-112`）。无独立功能性错误码 bug。

---

## 4. Caveats / Not Found

- **未做真机验证**：本切片无渲染/交互类「疑似（SR）」条目；BUG-QGEN-001 为字段名错位，静态即可确证，非渲染专属问题。
- **环境受限（ENV）**：本切片未运行工具链命令（由其他切片统一采集基线）；以上结论全部来自静态审阅与既有测试夹具，无 ENV 条目。
- **非功能性（不计入本文件计数）**：
  - 后端 `api/v1/questions.py` 文档字符串将 `MaterialNotFoundError` 标为 `40010`，实现实为 `40004`（`core/errors.py:751-782`）；纯文档不一致。
  - 前端 `QuestionType`/`QuestionCard.formatQuestionType` 未覆盖后端 `term_explanation`/`case_analysis`，UI 亦不生成这两类；回退原样显示枚举值。
  - `useQuestionQuality` 类型字段（BUG-QGEN-004）在接入前不会被运行时消费。
  - `QuestionGenerateResponse.knowledge_point_id` 在多考点场景取首位考点（`api/v1/questions.py:133`），前端未消费。
- **未确认/待实测**：BUG-QGEN-003 依赖 `uni.request` 对 DELETE `data` 的处理语义（是否可能被拼进 query），建议以一次真实请求抓包或后端请求日志确认；BUG-QGEN-005/006 为推理链结论，可通过最小复现测试确证。

---

## 5. 计数小结

| 级别 | 数量 | ID |
|---|---|---|
| P0 | 0 | — |
| P1 | 2 | BUG-QGEN-001, BUG-QGEN-007 |
| P2 | 6 | BUG-QGEN-002, BUG-QGEN-003, BUG-QGEN-004, BUG-QGEN-005, BUG-QGEN-006, BUG-QGEN-008 |
| 疑似（SR） | 0 | — |
| 环境受限（ENV） | 0 | — |
| **合计** | **8** | — |

- 按层：backend 2（007, 008）；frontend 2（005, 003前端侧）；cross-layer 4（001, 002, 003, 004）。
- 证据强度分布：静态强 5（001, 002, 004, 007, 008）；静态推理（中）3（003, 005, 006）。
- 非功能性另计（不计入上表）：3 项（见 §4）。
