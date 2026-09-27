# 技术设计：DIAG 切片 P2-A 修复（009-015）

## 1. 背景与根因定位

### BUG-DIAG-009：mastered_count 与 learning_count 恒 0
- **定位**：`backend/app/schemas/diagnosis.py:307-353`。
- **根因**：`_sync_fields` 声明为 `@model_validator(mode="before")` 并且内部仅对 `isinstance(data, dict)` 成立时执行键值同步。当路由返回 `UserMasteryOverviewDTO` 时，Pydantic `from_attributes` 模式将数据对象直接送入校验器，`data` 为非 dict 类型，跳过了 `before` 校验器；而在 `_sync_after` (`mode="after"`) 中，仅同步了 `overall_score`、`total_points` 和 `weak_knowledge_points`，漏掉了 `mastered_count <-> proficient_count` 和 `basic_count -> learning_count`。
- **影响**：前端小程序与接口消费的 `mastered_count`（精通数）和 `learning_count`（学习中数）恒为 0，看板四档分布失效。

### BUG-DIAG-010：error_type 过滤后置与枚举不一致
- **定位**：`backend/app/api/v1/diagnosis.py:329-330`、`miniprogram/src/subpackages/report/components/WrongRecordFilterBar.vue:133-134`、`miniprogram/src/subpackages/report/utils/wrongBookFormat.ts:23-40`。
- **根因**：
  1. 后端路由在 `diagnosis_service.list_wrong_records` 返回分页列表后，才执行 `records = [r for r in records if getattr(r, "error_type", None) == error_type]`。如果该页内无匹配项则返回空列表，且 `total_count` 依然是未过滤前的总数或被重算为截断条数，导致分页紊乱与总数失真。
  2. 前端界面定义的筛选项值为 `incomplete` 和 `deviation`，而后端 `ErrorType` 枚举定义为 `incomplete_expression` 和 `question_misreading`。前后端筛选项取值完全错位，导致前端发出的筛选条件在后端永远无法匹配。
- **影响**：用户筛选错误类型时产生假空数据、分页翻页混乱。

### BUG-DIAG-011：question_type 过滤后端未支持
- **定位**：`backend/app/api/v1/diagnosis.py:270-282`、`backend/app/repositories/diagnosis.py:494-521`。
- **根因**：前端错题本筛选组件 `WrongRecordFilterBar` 支持按单选/多选/判断等题型过滤并向 API 传递 `question_type`，但后端 FastAPI 路由未声明 `question_type` Query 参数，且仓储层的 SQL 语句未包含题目快照中的题型过滤条件。FastAPI 默认静默忽略未声明的查询参数，导致题型筛选完全不生效。
- **影响**：用户无法按题目类型筛选错题。

### BUG-DIAG-012：material_id 过滤的 1000 条硬编码截断
- **定位**：`backend/app/services/diagnosis.py:1133-1148`。
- **根因**：在根据 `material_id` 过滤错题时，Service 实现采用 `list_wrong_records(limit=1000, offset=0)` 在应用内存中拉取前 1000 条错题，再通过 Python 列表推导式匹配 `material_point_id_set`，最后进行切片 `[effective_offset:effective_offset + effective_limit]`。当用户错题超过 1000 条时，超过部分被永久截断，无法分页查看。
- **影响**：数据量较大时数据静默丢失，且全量拉取带来内存与性能瓶颈。

### BUG-DIAG-013：删除错题响应字段不一致
- **定位**：`miniprogram/src/api/diagnosis.ts:119-126`、`backend/app/schemas/diagnosis.py:486-494`。
- **根因**：前端接口定义泛型为 `ApiResponse<{ id: string; removed: boolean; message: string }>` 并读取 `res.data.removed`；而后端响应模型 `DeleteWrongRecordResponse` 仅有 `id: uuid.UUID`、`success: bool` 和 `message: str`，缺少 `removed` 字段。
- **影响**：前端在消费删除接口时 `res.data.removed` 恒为 `undefined`，无法做确定性结果判定。

### BUG-DIAG-014：报告详情页生命周期双重加载
- **定位**：`miniprogram/src/subpackages/report/pages/detail/index.vue:270-286`。
- **根因**：页面在 `onMounted` 与 `onLoad` 中均读取 `pid`，并无条件调用 `loadReportData(pid)`。在小程序运行时，页面打开会先后触发 `onLoad` 和 `onMounted`，导致同一份报告和练习详情被并发请求 2 次。
- **影响**：产生重复网络请求，浪费带宽，且存在后发先至的竞态覆盖风险。

### BUG-DIAG-015：错题筛选重置双重触发
- **定位**：`miniprogram/src/subpackages/report/components/WrongRecordFilterBar.vue:213-220`、`miniprogram/src/subpackages/report/pages/wrong-book/index.vue:8-9,204-212`。
- **根因**：`WrongRecordFilterBar` 的 `handleReset()` 中依次执行了 `emit('reset')` 和 `emitChange()`（后者触发 `emit('filter-change', ...)`）。而在父组件 `wrong-book/index.vue` 中，同时监听了 `@reset="handleResetFilters"` 和 `@filter-change="handleFilterChange"`，两处处理函数内部均调用了 `loadData(1, true)`。
- **影响**：单次重置操作触发 2 次后端列表请求。

---

## 2. 契约设计与跨层一致性

### 2.1 后端 `UserMasteryOverviewResponse` 档次映射口径（schemas/diagnosis.py）
- 档次映射口径：
  - `mastered_count`：对应已精通/掌握知识点数量，与 `proficient_count` 双向同步。
  - `learning_count`：对应学习中/待巩固基础知识点数量，与 `basic_count` 保持一致。
  - `weak_count`：薄弱知识点数量。
  - `unlearned_count`：未学知识点数量。
- 校验器修正：
  在 `@model_validator(mode="after")` 中补齐同步：
  ```python
  if self.mastered_count != 0 and self.proficient_count == 0:
      self.proficient_count = self.mastered_count
  elif self.proficient_count != 0 and self.mastered_count == 0:
      self.mastered_count = self.proficient_count

  if self.basic_count != 0 and self.learning_count == 0:
      self.learning_count = self.basic_count
  elif self.learning_count != 0 and self.basic_count == 0:
      self.basic_count = self.learning_count
  ```
  在 `mode="before"` 中同样确保对于 dict 类型的 `basic_count <-> learning_count` 双向同步。

### 2.2 错题列表查询参数与仓储下推契约（api/v1/diagnosis.py、services/diagnosis.py、repositories/diagnosis.py）
- API 层：
  - 增加 Query 参数：`question_type: Annotated[str | None, Query(description="题目类型过滤")] = None`。
  - 标准化 `error_type` 入参：支持 `incomplete_expression`、`question_misreading`、`conceptual`、`unanswered`，同时容忍前端旧值 `incomplete`（映射为 `incomplete_expression`）和 `deviation`（映射为 `question_misreading`）。
  - 将 `error_type` 与 `question_type` 透传给 `DiagnosisService.list_wrong_records`。
- Service 层：
  - `list_wrong_records` 增加 `error_type: str | None = None` 与 `question_type: str | None = None` 参数。
  - 移除 `api/v1/diagnosis.py` 的后置 Python 列表切片过滤，将过滤全量下推给仓储。
- Repository 层：
  - `DiagnosisRepository.list_wrong_records` 与 `DiagnosisRepository.count_wrong_records` 接收 `material_id`、`error_type`、`question_type`。
  - 当指定 `material_id` 时，通过与 `KnowledgePoint` 进行关联（`select(WrongRecord).join(KnowledgePoint, WrongRecord.knowledge_point_id == KnowledgePoint.id).where(KnowledgePoint.material_id == material_id)`）在 SQL 层完成过滤与分页。
  - 当指定 `error_type` 时，增加 `WrongRecord.error_type == error_type` 过滤。
  - 当指定 `question_type` 时，利用 JSONB/快照字段匹配 `WrongRecord.question_snapshot["question_type"].as_string() == question_type` 或数据库适配方式过滤。
  - `count_wrong_records` 保持完全一致的 WHERE 条件，保证 `total` 真实准确。

### 2.3 前端枚举对齐与兼容（WrongRecordFilterBar.vue、wrongBookFormat.ts）
- 筛选项与视觉映射规范化：
  - `incomplete_expression`：标签“表述不全”。
  - `question_misreading`：标签“审题偏差”。
  - `conceptual`：标签“概念性错误”。
  - `unanswered`：标签“未作答”。
- 兼容逻辑：在 `getErrorTypeInfo` 中，若入参为 `incomplete` 则回退至 `incomplete_expression` 样式；若为 `deviation` 则回退至 `question_misreading` 样式，保证老版本数据与新枚举无缝兼容。

### 2.4 后端 `DeleteWrongRecordResponse` 附加可选字段（schemas/diagnosis.py）
- 字段契约更新：
  ```python
  class DeleteWrongRecordResponse(BaseModel):
      id: uuid.UUID = Field(..., description="移除的错题记录主键 UUID")
      success: bool = Field(default=True, description="是否成功移除")
      removed: bool = Field(default=True, description="是否成功移除 (契约对齐字段)")
      message: str = Field(default="错题记录已成功移除", description="操作结果文案")
  ```
- 前端 `api/diagnosis.ts` 响应类型保持兼容：
  `ApiResponse<{ id: string; success: boolean; removed: boolean; message: string }>`。

### 2.5 前端生命周期与事件防重设计
- **DIAG-014**：
  在 `detail/index.vue` 中，统一以 `onLoad` 获取参数并触发 `loadReportData`；在组件内增加 `hasLoaded` 标志位。`onMounted` 中仅当尚未加载过（例如开发环境或某些嵌入测试环境未触发 `onLoad`）且 `pid` 存在时才执行兜底加载，彻底避免单次打开重复执行 2 次。
- **DIAG-015**：
  在 `WrongRecordFilterBar.vue` 中，重置动作的核心是将内部筛选重置为默认值并通过 `emitChange()` 通知父组件最新的空筛选状态。从 `handleReset` 中移除无参的 `emit('reset')`，或者父组件 `wrong-book/index.vue` 仅监听 `@filter-change` 处理列表加载，移除 `@reset` 导致的二次 `loadData`。

---

## 3. 影响文件清单

### 后端文件
- `backend/app/schemas/diagnosis.py`（UserMasteryOverviewResponse 校验器同步、DeleteWrongRecordResponse 新增 removed 字段）
- `backend/app/api/v1/diagnosis.py`（增加 question_type 参数、规范化 error_type 并透传 Service、移除后置切片过滤）
- `backend/app/services/diagnosis.py`（list_wrong_records 透传 material_id/error_type/question_type 至仓储，彻底移除 1000 截断）
- `backend/app/repositories/diagnosis.py`（list_wrong_records 与 count_wrong_records 下推 material_id、error_type、question_type 过滤）
- 测试用例：
  - `backend/tests/unit/schemas/test_diagnosis_schemas.py`（补充 DTO 对象转换后 mastered_count/learning_count 断言、DeleteWrongRecordResponse 字段断言）
  - `backend/tests/unit/api/test_diagnosis_router.py`（补充 question_type 与 error_type 过滤 API 测试）
  - `backend/tests/unit/services/test_diagnosis_service.py`（补充 material_id/error_type/question_type 下推与分页测试）
  - `backend/tests/unit/repositories/test_diagnosis_repo.py`（补充仓储层 material_id join、error_type、question_type 过滤测试）

### 前端文件
- `miniprogram/src/types/report.ts`（规范 WrongRecordQueryParams、DeleteWrongRecordResponse 类型）
- `miniprogram/src/api/diagnosis.ts`（更新 deleteWrongRecord 响应泛型与参数定义）
- `miniprogram/src/subpackages/report/components/WrongRecordFilterBar.vue`（更新 error_type 枚举取值，消除 handleReset 重复触发）
- `miniprogram/src/subpackages/report/utils/wrongBookFormat.ts`（对齐 getErrorTypeInfo 标准枚举与兼容映射）
- `miniprogram/src/subpackages/report/pages/detail/index.vue`（增加防重加载保护，避免 onLoad 与 onMounted 双重请求）
- `miniprogram/src/subpackages/report/pages/wrong-book/index.vue`（避免 reset 与 filter-change 导致的重复 loadData）
- 测试用例：
  - `miniprogram/tests/unit/report/reportDetailPage.spec.ts`（断言页面初始化仅触发一次数据加载）
  - `miniprogram/tests/unit/report/wrongBookPage.spec.ts`（断言重置筛选仅触发一次数据请求）
  - `miniprogram/tests/unit/wrongBook/wrongBookFormat.spec.ts`（断言新旧错误类型枚举解析）

---

## 4. 兼容性与回滚策略

- **向后兼容**：
  - `DeleteWrongRecordResponse` 保留了原有的 `success` 字段，新增的 `removed` 字段为纯增量，现有测试与前端旧代码均不受破坏。
  - 前端错误类型展示函数 `getErrorTypeInfo` 保留对 `incomplete` 与 `deviation` 的 switch-case 支持，存量快照或旧缓存数据依然可以正确展示徽章。
  - 掌握度 `UserMasteryOverviewResponse` 档次同步不修改数据存储结构，仅对输出响应补齐映射，不影响既有业务。
- **回滚方案**：
  - 若仓储层的快照题型 JSON 查询在个别环境（如特定 SQLite 版本）出现兼容性异常，可回退该查询条件为应用层安全匹配；其他改动相互独立，可单项回滚。
