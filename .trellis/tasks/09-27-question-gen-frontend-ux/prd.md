# 出题体验前端闭环与可核验（父任务）

## 1. 背景与原始诉求（Source Requirement Set）

用户实机反馈（原文摘录）：

1. 「有知识树了，点击生题，会**原地留着不会跳转**，也**不知道生题进度**」；
2. 「**知识树太少了吧**？感觉生成的不咋好？」（→ 另开任务，不在本父任务范围）；
3. 「感觉**很多跳转逻辑有问题**」；
4. 「我还**确认不了生题效果**」。

## 2. 范围（Scope）

本父任务统筹**前端出题交互闭环**，拆为 3 个可独立验收的子任务：

| 子任务 | 目录 | 目标 |
|---|---|---|
| 生题效果可核验 | `09-27-question-gen-verify-list` | 新增独立「题目列表」页，从后端持久加载，作为跳转目标与核验入口（**基座，先行**） |
| 出题进度与跳转闭环 | `09-27-question-gen-progress-nav` | 生成过程前端进度反馈；成功后跳转题目页；失败可重试；防重复提交（依赖前者） |
| 多选考点生效 | `09-27-question-gen-multi-kp` | 后端扩展支持多考点 + 前端多选真实生效（独立） |

**排序约束**：`verify-list`（题目页基座）→ `progress-nav`（跳转到该页）；`multi-kp` 可与前者并行。

## 3. 非目标（Non-goals）

- 不做知识树节点数量/出题质量调优（**另开后端任务**）。
- 不改现有对外 REST 的**响应结构**（多考点仅新增**可选请求字段**，向后兼容）。
- 不引入真实异步任务/进度查询接口（本任务进度反馈为**前端动画/阶段文案**）。
- 不改数据库表结构。

## 4. 约束（Constraints）

- 遵循前端 quality-guidelines（单文件 ≤ 300 行、零 Emoji、`listData` 与全局 Store 隔离、`onShow` 保活等）。
- 后端须过 `ruff`/`format`/`mypy`/`lint-imports`(5 kept)/`pytest`；前端须过 `lint`/`type-check`/`test:unit`。
- 保持既有 material 状态语义与长轮询契约不被破坏。

## 5. 跨子任务验收标准（Cross-child Acceptance Criteria）

- [ ] AC-P1：知识树页选择 N 个考点 → 生成 → 产出覆盖这 N 个考点的题目（多考点真实生效）。
- [ ] AC-P2：生成过程中用户能明确看到「进行中 + 阶段/计时」，且按钮防重复提交。
- [ ] AC-P3：生成成功后**跳转到独立题目页**并展示结果；返回/重进资料仍能看到已生成题目（持久化）。
- [ ] AC-P4：题目页可作为核验入口（列表、预览题干/答案、编辑/删除/修改痕迹入口可用）。
- [ ] AC-P5：失败/空结果有明确可操作提示（重试），不再「原地不动」。
- [ ] AC-P6：门禁全绿（前后端）。

## 6. 待澄清（Open Questions）

- OQ-1（**需用户给具体复现**）：「很多跳转逻辑有问题」的具体路径：哪个页面点哪个按钮 → 期望跳哪 → 实际如何。
- OQ-2：题目页放置位置（建议 `subpackages/material/pages/questions/index`）与标题命名，待 design 确认。
- OQ-3：多考点时题量如何在各考点间分配（均分/按权重），待 design 确认。

## 7. 集成评审（Integration Review）— 已完成

**端到端路径（代码层已闭环）**：
知识树多选 N 考点 → 生成（进行中面板：阶段文案+计时，全表单禁用）→ 后端按考点均分出题并聚合 → 成功 → 跳转独立题目页（`material_id`，fail 兜底）→ 题目页从后端持久加载并支持编辑/删除/痕迹 → 退出重进仍在（`onShow` 重拉）。

**跨子任务验收结果**

| AC | 结果 | 证据 |
|---|---|---|
| AC-P1 多考点真实覆盖 | ✅ 单元/API 层已断言 | `test_question_multi_kp.py`（分配/聚合/覆盖集合/fail-fast）、`test_question_router.py`（多考点路由） |
| AC-P2 进度可见 + 防重复 | ✅ | `QuestionConfigDrawer` 进行中面板 + 单测（连点仅 1 次请求） |
| AC-P3 成功后跳题目页 + 持久化 | ✅ | 跳转单测 + 题目页 `fetchQuestionList` 持久加载单测 |
| AC-P4 题目页可核验 | ✅ | `questionList.spec.ts`（渲染/空态/删除更新/参数解析） |
| AC-P5 失败/空结果可重试 | ✅ | 单测：空结果留抽屉提示、网络/业务错误分类 |
| AC-P6 门禁全绿 | ✅ | 后端 1130 passed / 5 contracts kept；前端 54 文件 / 444 passed |

**子任务归档**：`verify-list`、`progress-nav`、`multi-kp` 均已归档（`archive/2026-09/`）。
**提交**：`95f89bf`(verify-list) → `48fb3cc`(progress-nav) → `3fce14f`(multi-kp)。

**待用户真机确认（本父任务外）**：
- AC6 真实链路多考点覆盖（需真实 Provider，CLI 未扩展多考点；建议真机验证）。
- OQ-1：「跳转逻辑有问题」的具体复现（用户未提供，未针对性修复；已统一分包导航参数契约为 `material_id`）。
- 非本任务遗留：前端题量上限 50 vs 后端 `count le=20` 不一致（输入 >20 会 422）；知识树节点数量/出题质量（另开后端任务）。

## Notes

- 知识树节点数量与出题质量 → 独立后端任务（本父任务外）。
- 相关规范：`.trellis/spec/frontend/quality-guidelines.md`、`.trellis/spec/backend/quality-guidelines.md`。
