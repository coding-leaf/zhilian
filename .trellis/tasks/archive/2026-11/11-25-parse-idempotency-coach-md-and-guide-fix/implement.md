# Implementation Plan: 11-25-parse-idempotency-coach-md-and-guide-fix

## 执行分组与文件所有权（零重叠并行）

### Track A (`parse-and-guide-backend`): 解析幂等 + 考前精讲异步高优队列
- `backend/app/integrations/queue/protocol.py`
- `backend/app/integrations/queue/rq_adapter.py`
- `backend/app/integrations/queue/memory.py`
- `backend/app/services/material.py`
- `backend/app/services/_study_guide.py`
- `backend/app/services/knowledge.py`
- `backend/app/schemas/knowledge.py`
- `backend/app/api/v1/knowledge.py`
- `backend/app/worker.py`
- 测试：
  - `backend/tests/unit/services/test_parse_idempotency.py` (新增)
  - `backend/tests/unit/services/test_study_guide_service.py` (扩展异步入队、失败态与高优队列单测)

### Track B (`deleted-material-filter-backend`): 已删资料在学情 Tab 全链路过滤
- `backend/app/repositories/diagnosis.py`
- `backend/app/repositories/question.py`
- `backend/app/repositories/collection.py`
- 测试：
  - `backend/tests/unit/repositories/test_deleted_material_visibility.py` (新增，覆盖 Mastery / WrongRecord / WrongGroups / QuestionBatches / Questions / GroupedSummary / Collections 均排除已删资料，且 `Practice` 历史记录与 `list_questions_by_ids` 保持可读)
  - 按需更新受旧策略影响的现有单测（若存在）

### Track C (`frontend-coach-parse-guide-ux`): 前端防双击 + 助教 Markdown + 考前精讲轮询 UX
- `miniprogram/src/utils/richTextCore.ts`
- `miniprogram/src/utils/richText.ts`
- `miniprogram/src/components/CoachMessageList.vue`
- `miniprogram/src/components/AiCoachDrawer.vue`
- `miniprogram/src/stores/backgroundTask.ts`
- `miniprogram/src/subpackages/material/composables/useCourseDetail.ts`
- `miniprogram/src/subpackages/material/components/MaterialCourseHeader.vue`
- `miniprogram/src/subpackages/material/pages/course/index.vue`
- `miniprogram/src/types/knowledge.ts`
- `miniprogram/src/api/adapters/knowledge.ts`
- `miniprogram/src/subpackages/material/pages/knowledge/index.vue`
- 测试：
  - `miniprogram/tests/richText.spec.ts` (扩展 `---` / H5-H6 / 含 `*` 加粗 / `+ ` / 缩进列表 / 删除线 / 链接测试)
  - `miniprogram/tests/backgroundTaskStore.spec.ts` (或新增 `parseIdempotency.spec.ts` 验证在途请求合并)
  - `miniprogram/tests/knowledgeAdapter.spec.ts` (扩展 `failed` + `error_message` 适配测试)

### Track D (`verifier`, `gemini-4-neon-high`, 只读): 独立全量门禁与契约验收
- 主工作区合入 Track A/B/C 后运行：
  - `task verify-backend`（如遇已知 algorithms 墙钟并发抖动，单独重跑验证）
  - `cd miniprogram && pnpm run lint && pnpm run type-check && pnpm run test:unit && pnpm run build:mp-weixin`
  - 审核 `.vue <= 300` 行、零裸 Hex、零 Emoji、零 `span` WXSS 警告及 AC-1~AC-5。
