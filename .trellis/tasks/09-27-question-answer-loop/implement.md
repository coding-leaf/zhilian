# 实施计划：前端·出题→答题闭环

## 顺序清单

- [ ] 1. `src/types/question.ts`：`QuestionGenerateRequest`（`material_id?`、`folder_id?`）、`QuestionListQueryParams.folder_id?`、`QuestionGenerateResponse` 三字段可选。
- [ ] 2. `src/types/practice.ts`：`PracticeSession.material_id?`+`folder_id?`、`RawPracticeSession.folder_id?`、`CreatePracticePayload`（`material_id?`、`knowledge_point_ids?`、`folder_id?`）、`AnswerDraft.folder_id?`。
- [ ] 3. `src/components/course/CourseGenerateDrawer.vue`：出题配置 + `generateQuestions({folder_id,...})` + 错误分类/重试/提交禁用 + `success` emit。
- [ ] 4. `src/subpackages/material/pages/course/index.vue`：新增「智能出题」按钮与抽屉接线；成功后跳题目列表(`folder_id`)。
- [ ] 5. `src/subpackages/material/pages/questions/index.vue`：兼容 `folder_id`；空态范围引导；吸底「开始答题」→ `createPractice` → 跳答题页。
- [ ] 6. 复用/新增吸底操作栏组件（`PracticeStartBar.vue` 或复用 `BottomActionBar`）。
- [ ] 7. 单测：drawer、questions 页（folder 解析/开始答题/禁用）、createPractice 接线。
- [ ] 8. 前端全门禁绿。

## 验证命令（`miniprogram/`）

```
pnpm run lint
pnpm run type-check
pnpm run test:unit
pnpm run build:mp-weixin
```

## 评审门禁

- [ ] 四门禁全绿。
- [ ] 单资料出题/组卷零回归。
- [ ] `createPractice` 有调用点与单测。
- [ ] 导航参数统一且带 `fail` 兜底；组件 ≤300 行；零 Emoji。
- [ ] 前端出题→答题导航契约写入 `.trellis/spec/frontend/quality-guidelines.md`。

## 风险与回滚

- `material_id` 放宽可能影响既有消费方 → 运行时 `?? ''` 兜底并回归 `recentLearning`/报告读取。
- 真机 E2E 依赖真实后端与 LLM；无真机时以单测 + 编译产物间接验证，标注「待真机确认」。
- 回滚：前端改动可独立回退；后端字段可空、向后兼容。
