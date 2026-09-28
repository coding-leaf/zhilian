# 5d7a2f3 前端学习闭环审查

## 审查依据

- 业务提交 `5d7a2f3`，归档提交 `61b9ee1`，归档任务 `09-28-frontend-ui-redesign/prd.md` 的 AC-1 至 AC-7。
- 当前 `miniprogram/` 产品代码与该业务提交一致；工作区其他未提交改动未纳入本次结论。
- 这是静态代码与自动化门禁审查，未在微信真机或连接实际 LLM 的环境跑端到端流程。

## 验收结果

| 验收项 | 结论 | 证据 |
| --- | --- | --- |
| AC-1 个人信息 | 基本实现 | `pages/profile/index.vue` 可编辑昵称和头像 URL，`stores/auth.ts` 调用 `PUT /users/me`；头像只能填写 URL，没有图片选取/上传。 |
| AC-2 课程与上传 | 部分实现 | 首页可新建文件夹并以 `folder_id` 上传；`folderStore` 有重命名、归档 action，但页面没有对应操作入口。 |
| AC-3 解析与知识树 | 未实现可用闭环 | 后端状态为 `pending/parsing/ready/failed`，前端只判断 `WAITING/PROCESSING/PARSED/FAILED`，因此手动解析、状态反馈、知识树入口均失效。 |
| AC-4 多考点多题型组卷 | 部分实现 | 配置、生成请求可发出，但返回题目是 `question_type` 和对象选项，预览按 `type` 和字符串选项读取；练习详情响应也无法被会话页消费。 |
| AC-5 作答、评分、复查 | 未实现可用闭环 | 练习响应为 `items[].question_snapshot`，前端读取 `questions`；诊断报告只含汇总字段，前端等待不存在的 `details`。 |
| AC-6 错题再生 | 未实现 | 报告页依赖不存在的 `details`；报告/错题页调用再生方法时未传 `folderId/materialId`，后端生成请求要求至少一个范围，返回 422。 |
| AC-7 AI 助教 | 未实现预期 | 题目助教响应字段读取错误；课程/知识点助教只返回固定模板文本，不调用 AI 或检索资料。 |

## 主要缺陷与修复

1. **P0 练习会话必为空。** `stores/practice.ts:23,46-58` 把 `POST/GET /practices` 结果当成 `questions` 数组，实际契约为 `PracticeDetailResponse.items[].question_snapshot` (`backend/app/schemas/practice.py:423,455`)。增加 API 边界映射，生成含 `attempt_item_id/question_id/question_type/options/user_answer` 的前端卷面模型；新建和续练共用映射，再用真实后端响应测试题目渲染、作答恢复与交卷。
2. **P0 报告永远加载不成。** `stores/diagnosis.ts:17` 只接受 `report.details`，实际 `DiagnosisReportResponse` 没有此字段 (`backend/app/schemas/diagnosis.py:172-210`)；报告页还读取不存在的 `score/total_score/accuracy/weaknesses`。诊断汇总与 `GET /practices/{id}` 的作答项、错题记录组合成页面视图模型；按后端真实判题状态等待 `completed`，处理 `partially_graded`，再启用复查与错题重练。`stores/practice.ts:84-88` 交卷后立即触发诊断也会在判题未完成时失败，应改为状态轮询后生成或查询报告。
3. **P0 资料状态完全不匹配。** `backend/app/models/material.py:34-41` 定义小写状态，`pages/index/index.vue:114-127`、`subpackages/material/pages/course/index.vue:19-75`、`stores/material.ts:57` 使用大写状态。按后端值统一类型和 UI 状态机，覆盖 `retake_required`；以 `ready` 作为知识树/组卷入口条件。上传接口当前还自动排队解析 (`backend/app/api/v1/materials.py:195-265`)，如产品仍要求“手动开始”，需调整后端上传调度或明确改动验收预期。
4. **P1 再生题请求缺少必填范围。** `stores/practice.ts:115-130` 可传空 `folderId/materialId`；报告和错题页面均只传知识点 IDs (`subpackages/report/pages/detail/index.vue:283`、`pages/review/index.vue:128,145`)，违反 `QuestionGenerateRequest` 的范围校验 (`backend/app/schemas/question.py:46-57`)。从练习详情、错题快照补齐范围；若错题跨课程，按课程或资料分组生成，或者后端正式支持仅考点 ID 的授权出题。
5. **P1 题目和助教字段错位。** `backend/app/schemas/question.py:87-111,273-277` 使用 `question_type`、对象选项、`analysis`、助教 `reply/suggestions`；前端 `types/index.ts:111-126,193-198` 和 `components/AiCoachDrawer.vue:122` 使用其他字段。建立单一映射器，统一题目预览/答题选项 key 和文本、助教回显；增加真实响应契约测试。
6. **P1 课程助教是固定文案。** `components/AiCoachDrawer.vue:127-135` 在没有 `questionId` 时拼接静态答复，没有使用提问进行推理，也没有教材检索。要满足 AC-7，应增加受课程/资料范围约束的后端答疑接口，传 `folder_id/material_id/knowledge_point_id`，检索该范围切片并返回真实回复；未接通时界面应明确提示不可用。
7. **P1 答案可能丢失。** `stores/practice.ts:68-88` 逐键输入时并发保存草稿且吞掉错误，交卷不等待写入完成；最后一次输入可能晚于提交到达后端。为同题草稿做顺序化/去抖和失败提示，交卷前 `await` 所有待写入并以稳定幂等键提交，测试慢网络与重试。
8. **P2 功能入口缺口。** `stores/folder.ts:42-54` 的重命名/归档未被 UI 调用；`pages/review/index.vue:59` 读取 `item.question?.stem`，后端只给 `question_snapshot` (`backend/app/schemas/diagnosis.py:407`)，错题题干恒为占位文字。补课程操作入口，并映射错题快照。个人中心头像目前是 URL 输入，若要满足常规“编辑头像”体验，需要可选取图片的上传/托管流程。
9. **部署风险。** `utils/request.ts:1` 固定 `http://localhost:8000/api/v1`；真机的 localhost 指向手机自身。应使用环境配置的可访问 HTTPS API 地址，并配置微信合法请求域名。

## 建议实施顺序

先统一前后端契约并增加响应映射测试（资料、题目、练习、诊断、助教）；再修复解析入口、完整组卷作答、判题等待与报告组合；随后补错题再生范围、课程助教服务和草稿可靠性；最后补课程管理入口与真机验收。每个阶段用真实后端 DTO 示例做契约测试，再走一次“上传至课程 → 解析 → 选考点生成 → 答题交卷 → 诊断复查 → 错题再练 → AI 追问”的端到端用例。

## 门禁证据

- `task verify-frontend` 通过：ESLint、vue-tsc、Vitest；仅 2 个前端单测，均未覆盖 API 契约或页面流程。
- `task verify` 未通过：后端 Ruff 检出 `app/schemas/practice.py:134` SIM102 和 `tests/unit/services/test_question_service.py:1423` I001，后续步骤因此未由该命令执行。
- 单独执行后端 `mypy app` 通过、`lint-imports` 5/5 契约通过、`pytest tests --cov=app --cov-branch --cov-fail-under=80` 通过：1327 tests，覆盖率 91.82%。
