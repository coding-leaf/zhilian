# Spec: 判题编排、异步分流与自评/重判服务 - 技术契约

- **关联 Intent**: ZL-123
- **主导设计人**: Dev
- **当前状态**: Approved

---

## 1. 架构流向与设计方案

`GradingService` 遵循智练五层单向架构依赖矩阵，位于 `app/services` 层。作为系统核心业务编排者与唯一允许开启事务的层，协调 `GradingRepository`、`PracticeRepository`，调用纯函数算法核 `match_and_grade_answer`（判题阈值与匹配）与状态机跃迁决策纯函数 `transition_practice_status`，并通过 `LLMProtocol` 与 `run_structured_agent_workflow` 执行主观题结构化打分。

```mermaid
flowchart TD
    subgraph Caller[调用方: 异步 Worker / 业务 Service]
        direction TB
        GradeReq["grade_practice(user_id, practice_id)"]
        SelfReq["self_evaluate_attempt(user_id, SelfEvaluateDTO)"]
        RegradeReq["regrade_attempt(user_id, RegradeAttemptDTO)"]
    end

    subgraph GradingService[app/services/grading.py - GradingService]
        direction TB
        subgraph GradeFlow[整卷判题流水线]
            G1["1. 检索 Practice 及 AttemptItem 列表，校验归属与状态"]
            G2["2. 逐题遍历作答项 (AttemptItem)"]
            GCheckUnans{"用户是否已作答?"}
            GZero["标记未答: score=0, is_correct=False, is_answered=False\n生成 GradingRecord (channel=OFFLINE, status=SUCCESS, is_final=True)"]
            
            GAlgo["3. 调用纯函数 match_and_grade_answer\n(传入题型、用户作答、快照参考答案与细则)"]
            GMethodCheck{"requires_llm?"}
            
            GOffline["离线秒判成功: 更新 AttemptItem.score, is_correct\n生成 GradingRecord (channel=OFFLINE, status=SUCCESS, is_final=True)"]
            
            GLLMCall["4. 构造 LLM 提示词，调用 run_structured_agent_workflow\n(timeout=20s, 单次重试)"]
            GLLMResult{"LLM 调用是否成功?"}
            
            GAISucc["AI 打分成功: 解析各采分点得分与评语\n更新 AttemptItem.score, is_correct\n生成 GradingRecord (channel=AI, status=SUCCESS, is_final=True)"]
            
            GAIFail["降级容灾 (FR-42 严禁判错):\n生成 GradingRecord (channel=AI, status=PENDING_REGRADE, is_final=True)\n标记该题存在 pending_regrade"]
            
            GSummary["5. 计算全卷已判总分 Practice.total_score\n调用 transition_practice_status 更新状态:\n- 存在 pending_regrade -> PARTIALLY_GRADED\n- 全卷判完且无待重判 -> COMPLETED"]
        end

        subgraph SelfEvalFlow[用户主观题自评流程 (FR-44)]
            SE1["1. 校验练习与作答项归属 (user_id)，验证分值范围 [0, max_score]"]
            SE2["2. 校验题型: 仅主观题允许自评 (客观题抛出 GradingNotAllowedError 40014)"]
            SE3["3. 调用 GradingRepository.update_final_flag 将前序记录置为 is_final=False"]
            SE4["4. 创建新的 GradingRecord (channel=USER_SELF, status=SUCCESS, is_final=True)"]
            SE5["5. 更新 AttemptItem 得分与 is_correct; 重新汇总 Practice.total_score"]
            SE6["6. 检查是否存在剩余 pending_regrade，若无且已全判则跃迁至 COMPLETED"]
        end

        subgraph RegradeFlow[主观题异步重判流程 (FR-42)]
            RG1["1. 检索作答项，校验状态必须为 PENDING_REGRADE 或已交卷"]
            RG2["2. 重新调用大模型结构化评分工作流 (timeout=20s)"]
            RG3{"重判是否成功?"}
            RGSucc["3. 将原记录 is_final=False，新建 GradingRecord (channel=AI, status=SUCCESS, is_final=True)\n更新 AttemptItem 分数并重新计算全卷状态"]
            RGFail["保持 pending_regrade 状态，记录失败原因，不破坏原有记录"]
        end
    end

    subgraph Repositories[app/repositories]
        direction TB
        GRepo["GradingRepository (强制 user_id 过滤，零跨层)"]
        PRepo["PracticeRepository (查询与更新练习状态、总分)"]
    end

    subgraph PureAlgorithm[app/core/algorithms]
        MatchAlgo["match_and_grade_answer() (V(G) <= 10, 100% 分支覆盖)"]
        StateAlgo["transition_practice_status() (两阶段状态机防错)"]
    end

    subgraph Integrations[app/integrations]
        LLMGateway["LLMProtocol / run_structured_agent_workflow (20s 超时降级)"]
    end

    GradeReq --> G1
    G1 --> PRepo
    G1 --> G2
    G2 --> GCheckUnans
    GCheckUnans -- "否 (未答)" --> GZero
    GCheckUnans -- "是 (已答)" --> GAlgo
    GZero --> GRepo
    GAlgo --> MatchAlgo
    GAlgo --> GMethodCheck
    GMethodCheck -- "False (客观题/确定性规则)" --> GOffline
    GOffline --> GRepo
    GMethodCheck -- "True (转 AI)" --> GLLMCall
    GLLMCall --> LLMGateway
    GLLMCall --> GLLMResult
    GLLMResult -- "成功" --> GAISucc
    GAISucc --> GRepo
    GLLMResult -- "超时/限流/解析失败" --> GAIFail
    GAIFail --> GRepo
    GZero --> GSummary
    GOffline --> GSummary
    GAISucc --> GSummary
    GAIFail --> GSummary
    GSummary --> StateAlgo
    GSummary --> PRepo

    SelfReq --> SE1
    SE1 --> PRepo
    SE1 --> SE2
    SE2 --> SE3
    SE3 --> GRepo
    SE3 --> SE4
    SE4 --> GRepo
    SE4 --> SE5
    SE5 --> PRepo
    SE5 --> SE6
    SE6 --> StateAlgo
    SE6 --> PRepo

    RegradeReq --> RG1
    RG1 --> GRepo
    RG1 --> RG2
    RG2 --> LLMGateway
    RG2 --> RG3
    RG3 -- "成功" --> RGSucc
    RG3 -- "失败" --> RGFail
    RGSucc --> GRepo
    RGSucc --> PRepo
```

---

## 2. API 与数据契约设计

### 2.1 仓储层契约 (`GradingRepository`)
位于 `backend/app/repositories/grading.py`，全量方法强制输入 `user_id: uuid.UUID`：
- `create_record(record: GradingRecord, user_id: uuid.UUID) -> GradingRecord`
- `batch_create_records(records: Sequence[GradingRecord], user_id: uuid.UUID) -> list[GradingRecord]`
- `get_record_by_id(record_id: uuid.UUID, user_id: uuid.UUID) -> GradingRecord | None`
- `list_records_by_attempt_item(attempt_item_id: uuid.UUID, user_id: uuid.UUID) -> list[GradingRecord]`
- `get_final_record_for_attempt(attempt_item_id: uuid.UUID, user_id: uuid.UUID) -> GradingRecord | None`
- `list_final_records_by_practice(practice_id: uuid.UUID, user_id: uuid.UUID) -> list[GradingRecord]`
- `update_final_flag(attempt_item_id: uuid.UUID, user_id: uuid.UUID, is_final: bool) -> int` (原子切换)
- `count_pending_regrade(practice_id: uuid.UUID, user_id: uuid.UUID) -> int`

### 2.2 服务层契约 (`GradingService`)
位于 `backend/app/services/grading.py`：

```python
@dataclass(frozen=True)
class SelfEvaluateDTO:
    """用户自主评分请求对象。"""
    attempt_item_id: uuid.UUID
    score: float
    feedback: str | None = None

@dataclass(frozen=True)
class RegradeAttemptDTO:
    """单题重新判题请求对象。"""
    attempt_item_id: uuid.UUID

@dataclass(frozen=True)
class PracticeGradingSummary:
    """整卷判题结果汇总。"""
    practice_id: uuid.UUID
    status: str
    total_score: float
    max_score: float
    total_items: int
    graded_items: int
    pending_regrade_count: int
    records: list[GradingRecord]

@dataclass(frozen=True)
class LLMGradingRubricEvaluation(BaseModel):
    """LLM 结构化判题采分点响应 Schema。"""
    point_id: str
    score: float
    reason: str

@dataclass(frozen=True)
class LLMGradingOutput(BaseModel):
    """LLM 结构化判题响应 Schema。"""
    score: float
    confidence: float
    feedback: str
    hit_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    evaluations: list[LLMGradingRubricEvaluation] = Field(default_factory=list)
```

- `grade_practice(user_id: uuid.UUID, practice_id: uuid.UUID) -> PracticeGradingSummary`
- `self_evaluate_attempt(user_id: uuid.UUID, dto: SelfEvaluateDTO) -> GradingRecord`
- `regrade_attempt(user_id: uuid.UUID, dto: RegradeAttemptDTO) -> GradingRecord`

### 2.3 异常与错误码定义
在 `backend/app/core/errors.py` 中登记统一继承自 `AppError`：
- `AttemptItemNotFoundError` (错误码 `40013`, HTTP `404`): 作答题目明细不存在或无权访问；
- `GradingNotAllowedError` (错误码 `40014`, HTTP `400`): 判题或自评不合法（客观题不允许自评、打分超上限或状态非法）；
- `GradingExecutionError` (错误码 `40015`, HTTP `500`): 判题流水线执行严重异常。

---

## 3. 可测性设计 (Design for Testability)

### 3.1 独立纯函数计算核
- `match_and_grade_answer`: 独立于 I/O 与数据库，对单选、多选、判断、填空、主观题双阈值比对进行纯函数白盒验证；
- `transition_practice_status`: 状态机跃迁决策纯函数，根据当前状态、待重判标志、全卷判完标志返回目标状态（`PARTIALLY_GRADED` 或 `COMPLETED`）。

### 3.2 外部依赖与 Mock 策略
- **LLM 网关解耦**: 通过 `FakeLLMAdapter` 内存假实现进行驱动；支持预设返回、时延模拟与故障注入（模拟 `LLMTimeoutError` 触发 20s 超时降级与 `LLMResponseFormatError`）；
- **数据库隔离**: 单测使用独立 SQLite 内存数据库，验证事务回滚、`user_id` 越权过滤阻断与原子切换。

---

## 4. 替代方案与权衡考量 (Alternatives Considered & Trade-offs)

### 4.1 方案对比
- **方案 A：单题覆盖模式 (In-place Update)**
  在 `AttemptItem` 上直接覆写 `score`、`feedback`，不额外记录历史。
  *缺陷*：破坏审计链，用户自评后无法追溯最初 AI 判题与评分依据，违反 FR-41 与 FR-43。
- **方案 B：独立流水审计表 + `is_final` 生效指针 (已采纳)**
  每次判题（离线、AI、用户自评、重判）均插入独立的 `GradingRecord` 实体，通过 `is_final=True` 标定当前生效裁定。
  *优势*：具备完整审计追溯能力，精确统计置信度与各渠道打分偏离，支持多阶段异步重试。

### 4.2 LLM 超时策略权衡
- **直接判错 vs. 标记待重新判题**：若大模型调用超时直接记 0 分或判错，严重损害学习体验与学情真实性。遵照 FR-42 与《LEADER_ALIGNMENT.md》技术决策 1，严格标记为 `PENDING_REGRADE` 并阻断诊断报告生成，确保结论可信。

---

## 5. 动态风险核验与回滚预案 (Risk & Rollback Verification)

* [x] **Files**: 新增 `app/repositories/grading.py`, `app/services/grading.py`, `tests/unit/repositories/test_grading_repo.py`, `tests/unit/services/test_grading_service.py`；修改 `app/core/errors.py` 与各层 `__init__.py`。
* [x] **API**: 不直接增加对外路由，仅暴露领域服务与仓储接口，契约向后兼容。
* [x] **Schema**: 使用已有 `grading_records`, `attempt_items`, `practices` 表结构，无需执行数据库迁移。
* [x] **Auth**: 全量 SQL 与服务编排强制校验 `user_id`，越权访问抛出 `404` 或 `400`。
* [x] **Deps**: 仅依赖项目内部已有的纯函数与适配器，零新增第三方依赖。
* [x] **Migration & Rollback**: 若服务异常，可回滚服务代码；`GradingRecord` 为只增审计表，不破坏原有答卷数据。
* [x] **Blast Radius**: 影响判题调度与答卷状态机流转；通过两阶段状态机隔绝未决答卷对掌握度与报告的影响。

**回滚与故障应急策略**:
- 若判题服务异常中断，未完成判题的练习保持在 `IN_PROGRESS` 或 `PARTIALLY_GRADED` 状态，可通过重新投递 `grading_jobs` 队列任务幂等重试；
- 若大模型大面积超时，整卷主观题全部降级为 `pending_regrade`，系统提示用户可稍后重试或手动自评，核心业务主流程不发生崩溃。

---

## 6. 阶段准出签批 (Gate 2 Sign-off)
- [x] 架构流向与 API 契约已冻结
- [x] 替代方案已完成推演与权衡
- [x] 7 维风险已核验且具备明确回滚预案
- **审查结论**: Approved
- **签批人 / 日期**: Architect / 2026-09-24 14:15
