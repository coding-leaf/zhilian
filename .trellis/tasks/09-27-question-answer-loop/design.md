# 技术设计：前端·出题→答题闭环

> 上位契约：父任务 `design.md` §4.2、§4.3；依赖 C2 后端接口与 C3 课程页。

## 1. 类型契约（`src/types/`）

### 1.1 `question.ts`
- `QuestionGenerateRequest`：`material_id?: string`（改可选）；新增 `folder_id?: string`。
- `QuestionListQueryParams`：新增 `folder_id?: string`。
- `QuestionGenerateResponse`：`material_id?`、`version_id?`、`knowledge_point_id?` 改可选（后端 folder 范围返回 null）。
- `RawQuestionGenerateResponse` 同步可选（若为独立类型）。

### 1.2 `practice.ts`
- `RawPracticeSession`：`material_id?`（已有可选）+ 新增 `folder_id?: string | null`。
- `PracticeSession`：`material_id?: string`（改可选）+ 新增 `folder_id?: string | null`。
- `CreatePracticePayload`：`material_id?: string`（改可选）；`knowledge_point_ids?: string[]`（改可选，folder 范围可空）；新增 `folder_id?: string`。
- `AnswerDraft`：新增 `folder_id?: string`（草稿元数据，可选）。

> 后端 `PracticeDetailResponse`/`QuestionGenerateResponse` 的 `material_id` 已放开为可空（C2 迁移 0006），前端类型必须同步，避免 TS 断言与实际返回不符。

## 2. API（透传，无需改签名）

- `generateQuestions(payload)` / `fetchQuestionList(params)` / `createPractice(payload)` 已对 `payload`/`params` 做泛型透传；仅类型扩展即可让 `folder_id` 流通。
- 适配器 `adapters/question.adaptQuestionItem` 对缺失 `material_id` 已用 `?? ''` 兜底；`adapters/practice` 同理，folder 范围不崩。

## 3. 页面与组件

| 变更 | 文件 | 说明 |
|---|---|---|
| 改 | `subpackages/material/pages/course/index.vue` | 新增「智能出题」按钮 → 打开 `CourseGenerateDrawer`；成功后跳题目列表(folder_id) |
| 新增 | `components/course/CourseGenerateDrawer.vue` | 出题配置：题量(1~20)/题型多选/难度；提交调 `generateQuestions({folder_id,...})`；进行中禁用、错误分类提示 |
| 改 | `subpackages/material/pages/questions/index.vue` | 兼容 `folder_id`；空态引导；新增吸底「开始答题」 |
| 新增 | `components/course/PracticeStartBar.vue`（或复用 BottomActionBar） | 课程范围「开始答题」吸底操作栏 |
| 复用 | `components/practice/*` + `subpackages/practice/pages/session` | 答题与判题展示，无需改结构 |

## 4. 关键数据流

```
课程详情(course?folder_id)
  → [智能出题] CourseGenerateDrawer
       → POST /questions/generate { folder_id, count, question_types, difficulty }
       → 成功: navigateTo questions/index?folder_id=<id>
  → 题目列表 questions?folder_id
       → GET /questions?folder_id=  (分页)
       → [开始答题] POST /practices { folder_id, question_count, question_types, mode }
            → practiceStore.initSession(id, res.data.questions, { title, folder_id })
            → navigateTo /subpackages/practice/pages/session/index?id=<id>
  → 答题 → 交卷 → 判题（客观秒判 / 主观 LLM / 降级自评）→ 报告
```

- 「开始答题」题量：`question_count = Math.min(total, 20)`（`total` 为课程可用题数）；`total===0` 时禁用并提示先出题。
- `createPractice` 返回的 `PracticeSession.id` 用于跳转；`questions` 用于 `initSession`（与 `ContinuePracticeBar` 一致）。

## 5. 出题配置（`CourseGenerateDrawer`）

- 字段：`count`（默认 10，1~20）、`question_types`（默认单选/多选/判断/简答）、`difficulty`（默认 3）。
- 提交：`generateQuestions({ folder_id, count, difficulty, question_types })`（不传 `knowledge_point_ids`，交后端用课程缺省范围）。
- 错误处理：空结果/业务错误/网络错误分类提示，可重试；提交中禁用防重复。
- 成功后 `emit('success', folderId)` 由课程页跳转。

## 6. 单资料零回归

- 题目列表与出题配置在未传 `folder_id` 时保持既有 `material_id` 行为；`QuestionConfigDrawer`（知识树单资料出题）不改。

## 7. 测试

- `types`：folder 范围 payload 构造正确（`folder_id` 存在、`knowledge_point_ids` 可空）。
- `CourseGenerateDrawer`：默认值、提交调用参数、成功 emit、错误重试、提交禁用。
- `questions/index`：`folder_id` 解析与 `material_id` 兜底；「开始答题」调用 `createPractice` 且跳转 URL 正确（带 `id`）；`total===0` 禁用。
- `createPractice` 接线断言（不再是零调用）。
- 门禁：`lint`/`type-check`/`test:unit`/`build:mp-weixin`。

## 8. 风险

- `QuestionGenerateResponse.material_id` 变可空可能影响既有消费方（知识树出题结果）→ 类型放宽为可选，运行时保持 `?? ''` 兜底，零回归。
- `PracticeSession.material_id` 变可选可能影响 `recentLearning`/报告页读取 → 检查并对空值容错。
- 真机 E2E 依赖 C1/C2 后端与真实 LLM（出题）；无真机时以编译产物 + 单测 + 后端 smoke 间接验证，并在交付说明标注「待真机确认」。
