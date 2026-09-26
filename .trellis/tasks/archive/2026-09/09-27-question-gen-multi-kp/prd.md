# 多选考点生效（后端扩展 + 前端联动）

## Goal

用户在知识树页勾选 N 个考点后点击生成，必须**真实覆盖这 N 个考点**出题；修复「只发送第一个考点、其余被静默丢弃」的缺陷。

## Requirements

- R1（后端）：`QuestionGenerateRequest` 新增**可选** `knowledge_point_ids: list[uuid.UUID]`；保留 `knowledge_point_id` 以向后兼容。二者关系：优先 `knowledge_point_ids`；若仅给 `knowledge_point_id` 则退化为单考点。
- R2（后端）：新增服务编排：按考点**均分题量**（余数前置、每考点至少 1 题）逐个调用现有 `generate_questions`，聚合成一个结果返回；任一考点失败按现有异常语义抛出（不做静默吞错）。
- R3（后端）：`QuestionGenerateResponse` **仅新增可选** `knowledge_point_ids: list[uuid.UUID]`（附加字段，向后兼容，不破坏既有字段与顺序）；`qualified_questions` 等聚合列表包含全部考点题目（每题的 `knowledge_point_id` 标明归属）。
- R4（前端）：`QuestionGenerateRequest` 类型新增可选 `knowledge_point_ids`；`QuestionConfigDrawer` 提交时传**全部已选考点**（不再只取 `[0]`）。
- R5：题量分配规则与 UI 提示一致（如「N 个考点，共 M 题」），避免用户误解。
- R6：越权/不存在考点仍按现有租户校验拒绝（`KnowledgeNotFoundError`）。

## Acceptance Criteria

- [ ] AC1：勾选 3 个考点、请求 6 题 → 返回题目覆盖 3 个不同 `knowledge_point_id`（各 2 题）。
- [ ] AC2：请求题量小于考点数（如 2 考点 1 题）时行为明确（每考点至少 1 题 → 共 2 题），并在 UI/文档说明。
- [ ] AC3：仅传 `knowledge_point_id`（旧客户端）行为完全不变（向后兼容，现有测试不回归）。
- [ ] AC4：响应新增 `knowledge_point_ids` 为附加字段，既有字段与语义不变。
- [ ] AC5：后端 `ruff`/`format`/`mypy`/`lint-imports`(5 kept)/`pytest` 全绿；前端 `lint`/`type-check`/`test:unit` 全绿。
- [ ] AC6：真实链路可用 CLI 或接口验证多考点覆盖（记录证据）。

## Notes

- 涉及：`backend/app/schemas/question.py`、`backend/app/api/v1/questions.py`、`backend/app/services/question.py`；前端 `types/question.ts`、`components/QuestionConfigDrawer.vue`。
- 详细设计见 `design.md`，执行见 `implement.md`。
