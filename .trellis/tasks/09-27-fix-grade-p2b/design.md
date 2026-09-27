# 技术设计：GRADE 切片 P2-B 修复

## 1. 背景与根因分析

### BUG-GRADE-009: 得分舍入算法采用银行家舍入导致 0.5 边界偏低
- **代码位置**：`backend/app/core/algorithms/grading.py:791-795`
- **根因分析**：
  代码实现为 `rounded_score = round(raw_score / unit) * unit`。Python 3 内置 `round` 采用银行家舍入（round-half-to-even）。当 `raw_score / unit` 落在 `k.5` 且 `k` 为偶数时，会舍入向偶数 `k`，导致实际是 round-down 而非注释中声明的 `half-up`（四舍五入）。
  例如 `raw_score = 9.25, unit = 0.5`，`raw_score / unit = 18.5`。由于 18 是偶数，`round(18.5)` 结果为 18，最终得分为 `9.0`。但在标准的 half-up 0.5 粒度下，`9.25` 应舍入为 `9.5`。
- **修复方案**：
  在 `backend/app/core/algorithms/grading.py` 实现确定性的 half-up 舍入函数 `round_half_up(value: float, unit: float = 0.5) -> float`。可采用 `decimal.Decimal`配合 `ROUND_HALF_UP` 模式（或 `math.floor(val / unit + 0.5) * unit`，考虑浮点精度 Decimal 更安全严谨）。

### BUG-GRADE-010: LLM 判分未按 0.5 粒度舍入
- **代码位置**：`backend/app/services/grading.py:461-464` 与 `824-826`
- **根因分析**：
  在主观题首次 AI 评分 `_grade_with_llm` 及重新判题 `regrade_attempt` 中，对大模型解析得到的分数处理为：
  `final_score = min(item.max_score, max(0.0, float(output.score)))`
  未对其进行 `SCORE_ROUNDING_UNIT`（0.5 分）粒度舍入。而大模型输出的可能为任意浮点数（如 7.3 或 8.24），导致落库分值与系统离线判题的 0.5 粒度不一致。
- **修复方案**：
  在 `backend/app/services/grading.py` 引入/调用 `round_half_up`，在取得并 clamp 分数后，统一做 `round_half_up(final_score, SCORE_ROUNDING_UNIT)` 处理。

### BUG-GRADE-011: `SelfEvaluateRequest.is_correct` 契约字段被丢弃
- **代码位置**：`backend/app/schemas/grading.py:25-28`、`backend/app/api/v1/grading.py:66-74`、`backend/app/services/grading.py:60-67, 599-612`
- **根因分析**：
  `SelfEvaluateRequest` 中定义了 `is_correct: bool | None = None`，但 `SelfEvaluateDTO` 中未声明该字段。路由层 `api/v1/grading.py` 在实例化 `SelfEvaluateDTO` 时仅传递了 `attempt_item_id`、`score`、`feedback`，丢弃了 `is_correct`。服务层内部只能按 `score > 0` 强行推导对错，导致前端或客户端显式指定的自评正误状态无法生效。
- **修复方案**：
  1. 在 `SelfEvaluateDTO` 中添加 `is_correct: bool | None = None`；
  2. 路由层透传 `is_correct=request.is_correct`；
  3. 服务层 `self_evaluate_attempt` 中，若 `dto.is_correct is not None` 则直接采纳，否则回退为 `eval_score > 0`。

### BUG-GRADE-012: 自评弹窗渲染嵌套评分细则为原始 JSON
- **代码位置**：`miniprogram/src/subpackages/report/components/SelfGradeModal.vue:187-196`
- **根因分析**：
  自评弹窗的 `rubricEntries` 直接使用 `Object.entries(props.rubric)`。后端的评分细则结构规范通常为：
  `{ points: [{ point_id: "p1", description: "...", weight: 2.0 }], total_score: 10 }` 或 `dimensions: [...]`。
  此时 `Object.entries` 会把 key 解析为 `points`，value 解析为数组，随后进入 `JSON.stringify(v)`，用户在 UI 上看到的是冗长难懂的 JSON 字符串。
- **修复方案**：
  重构 `rubricEntries`：
  检测 `props.rubric` 是否包含 `points` 或 `dimensions` 数组。若包含，遍历该数组，将其格式化为：
  `label: "要点 " + index (或带分值，如 "要点 1 (2分)")`，`text: item.description`。
  若不含则保持平铺键值对或字符串兼容逻辑，保证向下兼容。

### BUG-GRADE-013: 重批理由长度契约前后端不一致
- **代码位置**：`miniprogram/src/subpackages/report/components/RegradeModal.vue:37, 43` 与 `backend/app/schemas/grading.py:72-76`
- **根因分析**：
  前端 `RegradeModal.vue` 将 `textarea` 的 `:maxlength` 设置为 200，并显示 `{{ localReason.length }} / 200`。
  后端 `RegradeRequest.reason` 的 `max_length` 为 500。
  这导致用户在输入 201-500 字的合法重批理由时在前端直接被截断无法输入。
- **修复方案**：
  将前端 `RegradeModal.vue` 中的 `maxlength` 调整为 500，字数提示对齐为 `{{ localReason.length }} / 500`。

### BUG-GRADE-016: 整卷判题先失效旧记录再判题，异常时丢失生效记录
- **代码位置**：`backend/app/services/grading.py:317-318, 372-380`
- **根因分析**：
  在 `_grade_attempt_item` 中，第一步即执行：
  `self.grading_repo.set_records_non_final_by_attempt_id(item.id, user_id=user_id)`
  随后才解析快照并调用 `match_and_grade_answer`。如果题目快照异常（如 `question_type` 为空或非法）导致算法层抛出 `ValueError`，未被捕获，整卷判题流程崩溃。此时旧的生效记录已经被置为 `is_final = False`，数据库中该题目处于“没有最终生效记录”的中间脏状态。
- **修复方案**：
  1. 调整操作次序：判题操作先执行算法（并准备好判题结果对象），在即将落库新记录前才执行 `set_records_non_final_by_attempt_id`，保证原子性；
  2. 增加异常防护：在 `_grade_attempt_item` 调用算法核时增加 `try...except Exception` 兜底；当遇到意外算法错误时，不中断整卷，而是记录错误并安全降级为 `pending_regrade`（或记录判错失败），防止整卷判题雪崩。

---

## 2. 契约设计与跨层一致性

### 2.1 后端 DTO 与 Schema 契约
- `SelfEvaluateDTO`（`services/grading.py`）：
  ```python
  @dataclass(frozen=True)
  class SelfEvaluateDTO:
      attempt_item_id: uuid.UUID
      score: float
      feedback: str | None = None
      is_correct: bool | None = None  # 新增附加可选字段
  ```
- `SelfEvaluateRequest`（`schemas/grading.py`）：已有 `is_correct: bool | None = None`，无需变动，契约对齐。

### 2.2 前端细则解析契约
- `RubricEntry`：`{ label: string; text: string }`
  支持三类细则入参：
  1. 结构化细则：`{ points: [{ description: string, weight?: number, score?: number }], ... }`
  2. 键值对细则：`{ "要点1": "描述..." }`
  3. 纯文本细则：`"评分说明文本"`

### 2.3 前端重判理由契约
- 最大长度由 200 上调至 500，最小长度保持 2（与业务校验规则一致）。

---

## 3. 兼容性与回滚策略

1. **向下兼容**：
   - `SelfEvaluateDTO.is_correct` 为可选字段，默认 `None` 时行为完全与旧代码（按 `score > 0` 判定）一致。
   - `round_half_up` 默认粒度为 `0.5`，符合概要设计说明书规范。
   - 前端细则支持多种数据形态，旧数据或纯文本细则表现不受影响。
2. **回滚方案**：
   - 算法与服务层舍入函数改动无数据库 schema 依赖，可随时回退代码。
   - 失效记录顺序调整为代码流程次序调整，不影响已持久化的数据状态。

---

## 4. 影响文件清单

- 后端核心算法：`backend/app/core/algorithms/grading.py`
- 后端服务：`backend/app/services/grading.py`
- 后端 API 路由：`backend/app/api/v1/grading.py`
- 前端自评弹窗组件：`miniprogram/src/subpackages/report/components/SelfGradeModal.vue`
- 前端重判弹窗组件：`miniprogram/src/subpackages/report/components/RegradeModal.vue`
- 测试文件：
  - `backend/tests/unit/core/algorithms/test_grading.py`
  - `backend/tests/unit/services/test_grading_service.py`
  - `backend/tests/unit/api/test_grading_router.py`
  - `miniprogram/tests/unit/report/gradingModals.spec.ts`
