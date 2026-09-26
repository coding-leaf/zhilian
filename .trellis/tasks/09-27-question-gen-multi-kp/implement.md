# Implement Plan: 多选考点生效

> 执行原则：后端命令在 `backend/` 下用 `uv run`；前端在 `miniprogram/` 下用 `pnpm`。禁止 Git Commit（收尾阶段统一提交）。

## Stage 1：纯函数与分配规则（可先做，无副作用）
- [ ] 在 `app/services/question.py`（或 `app/core/algorithms`）新增纯函数 `distribute_count(total: int, n: int) -> list[int]`（均分 + 余数前置 + 每项 >=1）。
- [ ] 单测 `tests/unit/services/test_question_multi_kp.py`：`distribute_count(6,3)=[2,2,2]`、`(7,3)=[3,2,2]`、`(2,3)=[1,1,1]`、`(1,1)=[1]`。
- 验证：`uv run pytest tests/unit/services/test_question_multi_kp.py`

## Stage 2：Schema 扩展（向后兼容）
- [ ] `QuestionGenerateRequest` 增 `knowledge_point_ids: list[uuid.UUID] = Field(default_factory=list, ...)`。
- [ ] `QuestionGenerateResponse` 增 `knowledge_point_ids: list[uuid.UUID] = Field(default_factory=list, ...)`。
- [ ] 单测：旧 payload（无该字段）解析成功；新 payload 解析成功。
- 验证：`uv run mypy app && uv run pytest tests/unit`

## Stage 3：服务编排（评审门 A）
- [ ] `QuestionService.generate_questions_for_knowledge_points(user_id, material_id, version_id, knowledge_point_ids, options)`：
  - 计算分配；逐考点调用 `generate_questions`；聚合为结果对象（含 `knowledge_point_ids`）。
- [ ] 单测（mock 仓储/LLM 或复用现有 fixture）：2~3 考点 → 断言调用次数、各考点题量、聚合计数、题目覆盖集合、`knowledge_point_id`（旧字段）= 首个。
- **评审门 A**：人工确认分配与聚合语义、异常语义后再继续。

## Stage 4：API 路由接线
- [ ] `generate_questions` 路由：`payload.knowledge_point_ids` 非空且 >1 → 调多考点编排；否则走原单考点分支。
- [ ] 响应映射：填充 `knowledge_point_ids` 与聚合列表；旧字段不变。
- [ ] API 单测：多考点请求 + 旧单考点请求（不回归）。
- 验证：`uv run pytest tests`

## Stage 5：前端联动（评审门 B）
- [ ] `miniprogram/src/types/question.ts`：`QuestionGenerateRequest` 增可选 `knowledge_point_ids`。
- [ ] `QuestionConfigDrawer.vue`：提交传 `knowledge_point_ids: selectedKnowledgeIds`，并按 `total < N` 提示。
- [ ] 单测：`tests/unit/components/QuestionConfigDrawer.spec.ts` 断言 payload 含全部已选考点。
- 验证：`pnpm run lint && pnpm run type-check && pnpm run test:unit`
- **评审门 B**：人工确认端到端多考点行为。

## Stage 6：真实链路验证（可选）
- [ ] 通过 CLI/脚本对同一资料勾选多考点生成，核对返回题目 `knowledge_point_id` 覆盖集合。
- [ ] 记录证据 JSON 到任务目录。

## 全量门禁（每 Stage 收尾必跑）
```bash
# backend/
uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run lint-imports && uv run pytest tests
# miniprogram/
pnpm run lint && pnpm run type-check && pnpm run test:unit
```

## 回滚点
- 移除新增可选字段 + 多考点分支即可；无 DB 迁移、无破坏性变更。

## 风险
- 多考点 = 多次 LLM 调用，耗时与费用随考点数线性增长（前端需配合 `progress-nav` 的进度反馈）。
- 若 `total < N` 的“每考点至少 1 题”策略与用户预期不符，需在评审门确认（可改为“仅取前 N 个考点各 1 题”）。
