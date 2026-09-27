# 修复 GRADE 切片 P2-B：算法舍入粒度、自评契约与判题事务安全

## Goal

修复只读审计清单 GRADE 切片第 2 批（P2-B）共 6 条缺陷：
1. BUG-GRADE-009：得分舍入银行家舍入（round-half-to-even）导致 0.5 边界少给分，需对齐声明的 half-up 0.5 粒度；
2. BUG-GRADE-010：LLM 主观题判分与重判分未按 0.5 粒度统一舍入，与离线判分路径出现粒度漂移；
3. BUG-GRADE-011：`SelfEvaluateRequest.is_correct` 契约字段被路由层/DTO 静默丢弃；
4. BUG-GRADE-012：自评弹窗 `rubricEntries` 将嵌套细则（`points`/`dimensions`）直接 `JSON.stringify` 呈现给用户；
5. BUG-GRADE-013：重判理由长度前后端契约不对齐（前端 200 字，后端 500 字）；
6. BUG-GRADE-016：整卷判题在调用算法前过早将旧记录置为非最终（`is_final=False`），算法异常时导致该题无生效记录。

注：`BUG-GRADE-015`（判题列表模板空指针）经前序复核确认模板具备守卫不成立，已显式撤销，不得纳入本次修复范围。

## 需求来源

上游审计 `09-27-read-only-bug-audit`（归档于 `archive/2026-09/09-27-read-only-bug-audit/research/slice-GRADE.md`）：

| ID | 级别 | 层 | 一句话 |
|---|---|---|---|
| BUG-GRADE-009 | P2 | backend algorithm | 常量注释声明 half-up 0.5，但实现使用 Python `round`（银行家舍入），在 `k.5` 偶数边界少给 0.5 分 |
| BUG-GRADE-010 | P2 | backend service | LLM 判题与重判分仅做 `min/max` 截断，未应用 0.5 粒度舍入，与离线路径存在分值粒度不一致 |
| BUG-GRADE-011 | P2 | cross-layer | `SelfEvaluateRequest.is_correct` 被 `SelfEvaluateDTO` 和路由丢弃，客户端显式传参失效 |
| BUG-GRADE-012 | P2 | frontend component | `SelfGradeModal` 对 `grading_rubric` 的 `points/dimensions` 渲染出 `[object Object]` 或原始 JSON 字符串 |
| BUG-GRADE-013 | P2 | cross-layer | 重批理由前端限制 200 字，后端 schema 允许 500 字，两端校验边界不一致导致合法长理由被截断 |
| BUG-GRADE-016 | P2 | backend service | `_grade_attempt_item` 先失效旧记录再调用判分算法，若算法异常抛错中断，旧记录已被置非最终且无生效记录 |

## Requirements

### 功能要求
1. **GRADE-009（算法 half-up 0.5 舍入）**：
   - 在 `backend/app/core/algorithms/grading.py` 实现统一的 half-up 舍入辅助函数（基于 `decimal.Decimal` 与 `ROUND_HALF_UP` 或等价确定性数学公式）。
   - 离线主观题得分计算按 `score_rounding_unit`（默认 0.5）做真正的 half-up 四舍五入，确保如 `raw_score=9.25` 时在 `unit=0.5` 下稳定得到 `9.5`（而非 Python 银行家舍入的 `9.0`）。
2. **GRADE-010（LLM 判分与重判 0.5 粒度收敛）**：
   - 在 `backend/app/services/grading.py` 的 `_grade_with_llm` 以及 `regrade_attempt` 两个路径中，在获取 `output.score` 并 clamp 到 `[0.0, item.max_score]` 后，统一按 `SCORE_ROUNDING_UNIT`（0.5 分）应用 half-up 舍入，保证全链路分值均为 0.5 整数倍。
3. **GRADE-011（自评 is_correct 透传与生效）**：
   - `SelfEvaluateDTO` 增加附加可选字段 `is_correct: bool | None = None`。
   - `api/v1/grading.py` 路由在构建 `SelfEvaluateDTO` 时透传 `request.is_correct`。
   - `GradingService.self_evaluate_attempt` 优先采用用户显式指定的 `dto.is_correct`；仅当其为 `None` 时，回退到既有的 `score > 0` 判定。
4. **GRADE-012（自评弹窗细则结构化友好展示）**：
   - 前端 `SelfGradeModal.vue` 升级 `rubricEntries` 计算属性：支持解析后端规范的 `{ points: [...], total_score }` 与 `{ dimensions: [...], total_score }` 结构。
   - 对要点列表提取每个要点的描述、分值/权重（如 `要点1（2分）: 描述`），若为纯键值对或字符串则优雅回退，避免展示原始 JSON 或 `{"point_id": ...}` 噪音。
5. **GRADE-013（重批理由字数上限对齐）**：
   - 前端 `RegradeModal.vue` 的 `textarea` `maxlength` 由 200 调整为 500，字数统计同步调整为 `/ 500`，与后端 `RegradeRequest.reason` 的 `max_length=500` 完全对齐。
6. **GRADE-016（判题事务与生效记录保护）**：
   - 调整 `_grade_attempt_item` 逻辑顺序：先完成算法打分 `match_and_grade_answer`（及可能抛出的异常），成功产出判题结果后再将旧记录置为非最终（`set_records_non_final_by_attempt_id`），最后持久化新最终记录。
   - 对 `match_and_grade_answer` 增加局部防御与降级：若因快照格式或未知题型抛出异常，捕获并记录告警，安全降级生成 `pending_regrade` 记录，保证整卷判题不中断，原记录不丢失。

### 约束
- 契约权威：后端 `schemas/grading.py`（`SelfEvaluateRequest`、`RegradeRequest`）。
- 兼容性：所有 DTO 与请求/响应变更遵循“附加可选、默认旧行为”原则；前端对后端旧格式细则兼容。
- 代码质量与安全：严禁新增 `any`（Python 与 TypeScript）；守分层架构与 import-linter；前端夹具字段名逐字取自后端。
- 门禁全绿：后端 `ruff format`、`ruff check`、`mypy app`、`lint-imports`、`pytest`；前端 `lint`、`type-check`、`test:unit`。

### 不在范围内
- BUG-GRADE-015 已于前序审计复核确认不成立（有模板守卫），不予改动。
- GRADE 其余切片（P1 已完成，P2-A 即 003-008 属单独切片）。

## Acceptance Criteria

- [ ] **GRADE-009**：算法针对偶数倍 `.25` 边界数值（如 9.25 在 0.5 粒度下）断言得到 9.5（half-up），而非银行家舍入的 9.0。
- [ ] **GRADE-010**：LLM 首次判分与重判分（如模型返回 7.3 或 8.24）落库后为 0.5 倍数（7.5 或 8.0）。
- [ ] **GRADE-011**：客户端请求 `POST /api/v1/grading/self-evaluate` 携带 `score=0.0, is_correct=True`（或 `score=5.0, is_correct=False`）时，生成记录的 `grading_metadata["is_correct"]` 与传入值严格一致。
- [ ] **GRADE-012**：前端 `SelfGradeModal` 传入包含 `points` 或 `dimensions` 的细则对象时，渲染出要点描述和分值标签，不含 JSON 字符串或 `[object Object]`。
- [ ] **GRADE-013**：前端 `RegradeModal` 支持输入至多 500 字，字数计数器展示 `x / 500`，超过 200 字且小于等于 500 字可正常提交。
- [ ] **GRADE-016**：单题判分算法若出现异常抛错，不会在无新记录生成前使既有生效记录失效；整卷判题具备防线，不因个别脏题目快照崩溃整卷。
- [ ] 后端门禁全绿：`ruff format --check`、`ruff check`、`mypy app`、`lint-imports`、`pytest`。
- [ ] 前端门禁全绿：`pnpm run lint`、`pnpm run type-check`、`pnpm run test:unit`。

## Notes

- 撤销项登记：`BUG-GRADE-015`（判题列表模板空指针）为已撤销/误报，原因见前序审计证据。
- 相关证据已在当前分支 `HEAD` 验证，根因均已确认。
