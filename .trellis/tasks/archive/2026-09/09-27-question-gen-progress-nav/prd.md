# 出题生成进度反馈与生成后跳转闭环

## Goal

让出题过程**可见**（进行中 + 阶段/计时）、**成功后可预期地跳转**到独立题目页、**失败可重试**，解决「原地不动、无进度、无反馈」。

## Requirements

- R1：`QuestionConfigDrawer` 提交后，除按钮 loading 外，展示**阶段文案 + 计时**（前端动画，非真实进度），文案如「检索切片 → 命制题目 → 质检门禁」；提交期间**全表单禁用**防重复提交。
- R2：真实出题耗时可 30s+，需保证请求层超时足够（或可配置）且中途可取消/关闭给出明确状态，不出现「假死」。
- R3：生成**成功**：关闭抽屉 → `uni.navigateTo` 跳转独立题目页（`subpackages/material/pages/questions/index?material_id=<id>`），并提示成功。
- R4：生成**空结果/失败**：不得静默。区分「网络/服务错误」与「质检未通过/空结果」，给出可操作提示与**重试**入口（保留用户已填配置）。
- R5：跳转失败（页面未注册等）需兜底提示，不得无响应。
- R6：移除/收敛知识树页内「生成后本地切 Tab」的旧逻辑，避免与题目页形成**双数据源**（以 `verify-list` 的题目页为唯一结果视图）。

## Acceptance Criteria

- [ ] AC1：点击「开始定制出题」后，界面立即显示进行中状态（阶段文案 + 计时），按钮不可重复点。
- [ ] AC2：成功时自动跳转到题目页并看到本次生成题目。
- [ ] AC3：失败/空结果有明确提示与重试；不再「原地不动」。
- [ ] AC4：跳转与参数正确（`material_id`），与 `verify-list` 页面契约一致。
- [ ] AC5：前端 `lint` / `type-check` / `test:unit` 全绿；补交互单测（进行中/成功跳转/失败重试）。

## Notes

- 依赖：`09-27-question-gen-verify-list`（题目页基座）须先就绪。
- 涉及文件：`subpackages/material/components/QuestionConfigDrawer.vue`、`subpackages/material/pages/knowledge-tree/index.vue`、`utils/request.ts`（超时）。
