# Spec: 题目质检与待处理过滤算法 - 技术契约

- **关联 Intent**: ZL-110
- **主导设计人**: Dev / TechLead
- **当前状态**: In-Review
- **任务评级**: Tier 2 (Single-Module Feature)

---

## 1. 架构流向与设计方案

### 1.1 模块定位与分层防线
题目质检与待处理过滤算法是智练学习平台题目生成主链的核心质检屏障，严格位于智练后端五层单向架构矩阵的**纯函数计算核**：
- **物理路径**: `backend/app/core/algorithms/question_quality.py`
- **分层依赖铁律**:
  - 依赖严格向下/向内，绝对禁止导入 `fastapi`, `sqlalchemy`, `httpx`, `redis`, `boto3` 等 Web 框架、网络库或 ORM 驱动；
  - 绝对禁止导入上层业务模块 `app/services` 与 `app/repositories`；
  - 严格通过 `python3 tooling/check_layers.py --root backend/app` 架构门禁校验（0 违规）；
  - 输入参数与输出报告均为不可变原生数据结构（`dataclasses.dataclass(frozen=True)` 与标准类型 `tuple`、`str`、`float`、`int` 等）。
- **与业务模型解耦**:
  - 本模块与 `backend/app/models/question.py` 中的 `Question`, `QuestionQualityCheck` 持久化实体解耦；
  - 服务层（`question_service`）负责抽取候选题载荷转化为 `CandidateQuestion`，拉取最近通过质检的已有题目摘要为 `ExistingQuestionReference` 传入算法核；
  - 算法核完成判定后返回 `QuestionQualityReport`，服务层依据该报告将合格题目保存为 `available`，将不合格题目写入待处理区（`pending_review`）并关联持久化 `QuestionQualityCheck` 质检记录（FR-25）。

### 1.2 核心数据流与质检流水线
题目质检严格遵循四类一票否决固定执行顺序：`NO_SOURCE` (无来源) $\to$ `DUPLICATE` (重复题) $\to$ `ANSWER_CONFLICT` (答案冲突，仅客观题) $\to$ `AMBIGUITY` (明显歧义)。

```mermaid
flowchart TD
    Start[输入: candidates, existing_questions, config] --> EmptyCheck{candidates 为空?}
    EmptyCheck -- 是 --> ReturnEmpty[返回空报告: qualified=(), unqualified=(), is_degraded=False]
    EmptyCheck -- 否 --> SortBatch[批次按创建序列 created_at_seq 排序]
    SortBatch --> WindowCrop[已有题库截取最近 500 道: existing[:500]]
    WindowCrop --> Loop[遍历候选题目 candidate]

    subgraph Pipeline [四项一票否决流水线 (顺序固定)]
        Check1[1. 无来源检查 check_source_grounding]
        Check1 --> Pass1{通过?}
        Pass1 -- 否 --> Veto1[标记 NO_SOURCE 剔除]
        Pass1 -- 是 --> Check2[2. 重复题检查 check_duplication]
        
        Check2 --> Pass2{通过?}
        Pass2 -- 否 --> Veto2[标记 DUPLICATE 剔除]
        Pass2 -- 是 --> Check3[3. 答案冲突检查 check_answer_conflict]
        
        Check3 --> Pass3{通过? (主观题自动跳过)}
        Pass3 -- 否 --> Veto3[标记 ANSWER_CONFLICT 剔除]
        Pass3 -- 是 --> Check4[4. 明显歧义检查 check_ambiguity]
        
        Check4 --> Pass4{通过?}
        Pass4 -- 否 --> Veto4[标记 AMBIGUITY 剔除]
        Pass4 -- 是 --> Qualified[标记 QUALIFIED 合格]
    end

    Loop --> Check1
    Veto1 --> Collect[归入 unqualified_questions 并记录首位失败原因]
    Veto2 --> Collect
    Veto3 --> Collect
    Veto4 --> Collect
    Qualified --> CollectPass[归入 qualified_questions 并记录全检通过]

    Collect --> NextCheck{还有候选题?}
    CollectPass --> NextCheck
    NextCheck -- 是 --> Loop
    NextCheck -- 否 --> BuildReport[装配不可变 QuestionQualityReport]
    BuildReport --> End[输出报告]
```

### 1.3 白盒复杂度控制与函数拆分设计 ($V(G) \le 8$)
为严格遵守《概要设计说明书》第 7.1 节与 AGENTS.md 关于算法核 McCabe 环路复杂度 $V(G) \le 8$ 的上限红线，将题目质检拆解为 8 个无状态独立纯函数：

1. `calculate_cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float` ($V(G) \le 4$):
   - 计算两向量余弦相似度，包含零长度、不同维度与零向量模长兜底防除零。
2. `calculate_text_similarity(text_a: str, text_b: str) -> float` ($V(G) \le 4$):
   - 纯 Python 字符 2-gram Jaccard 相似度计算，文本归一化处理，零第三方依赖。
3. `extract_keywords(text: str) -> list[str]` ($V(G) \le 5$):
   - 提取文本中的中文实词（连续汉字长度 $\ge 2$）与英文单词（长度 $\ge 2$），过滤标点与停用符号。
4. `check_source_grounding(stem: str, source_text: str, source_snippet_ids: Sequence[str], config: QuestionQualityConfig) -> tuple[bool, str | None, float]` ($V(G) \le 5$):
   - 检查切片标识是否存在、来源文本是否为空、题干实词在来源中的重合比例是否达到阈值。
5. `check_duplication(candidate: CandidateQuestion, existing: Sequence[ExistingQuestionReference], prior_candidates: Sequence[CandidateQuestion], config: QuestionQualityConfig) -> tuple[bool, str | None, float | None]` ($V(G) \le 7$):
   - 检查同一批次内前序候选题去重（同题干保留首发），检查与最近 500 道已有题目的向量余弦相似度及字符相似度。
6. `check_answer_conflict(candidate: CandidateQuestion, existing: Sequence[ExistingQuestionReference], config: QuestionQualityConfig) -> tuple[bool, str | None, float | None]` ($V(G) \le 7$):
   - 过滤客观题；针对题干相似度 $\ge 0.88$ 的题目比对标准答案集合（单选/多选/判断二值）。
7. `check_ambiguity(candidate: CandidateQuestion, config: QuestionQualityConfig) -> tuple[bool, str | None]` ($V(G) \le 8$):
   - 检查题干长度 ($\ge 6$)、选项重复、题型特定选项数与正确项数约束、“以上都对/错”逻辑互斥。
8. `filter_qualified_questions(candidates: Sequence[CandidateQuestion], existing_questions: Sequence[ExistingQuestionReference] = (), config: QuestionQualityConfig | None = None) -> QuestionQualityReport` ($V(G) \le 6$):
   - 批次流水线顶层编排核：执行空输入短路、窗口截取、批次去重链式传递、一票否决流水线调度与汇总组装。

---

## 2. API 与数据契约设计

### 2.1 依赖与调用契约
- **运行环境**: Python 3.12+ / 纯标准库。
- **允许导入模块**: `dataclasses`, `enum`, `math`, `re`, `typing`, `collections.abc`。
- **调用方式**: 同步纯函数调用，无副作用，无可变全局状态。

### 2.2 阈值常量体系与决策基准
所有阈值常量均显式注明《概要设计说明书》与《软件需求规格说明书》依据，严禁在业务逻辑中硬编码无依据魔数：

```python
# 依据：概要设计说明书第 6.4 节与 FR-24，重复题向量余弦相似度门禁上限为 0.90
# 题干+选项语义向量余弦相似度 >= 0.90 判定为语义重复题，闭区间拦截
DEFAULT_DUPLICATE_VECTOR_THRESHOLD: float = 0.90

# 依据：概要设计说明书第 6.4 节与 FR-24，重复题字符级相似度门禁上限为 0.85
# 字符 2-gram Jaccard 相似度 >= 0.85 判定为字面重复题，闭区间拦截
DEFAULT_DUPLICATE_TEXT_THRESHOLD: float = 0.85

# 依据：概要设计说明书第 6.4 节与 FR-24，客观题答案冲突的题干相似度门禁下限为 0.88
# 当两道客观题题干相似度 >= 0.88 且标准答案集合不一致时，判定为答案冲突，闭区间拦截
DEFAULT_CONFLICT_VECTOR_THRESHOLD: float = 0.88

# 依据：概要设计说明书第 6.4 节与 FR-24，来源片段实词重合率门禁下限为 30% (0.30)
# 题干中实词（长度>=2的中英文词）在来源片段中的出现比例 < 0.30 判定为脱离资料的幻觉题目
DEFAULT_MIN_SOURCE_KEYWORD_RATIO: float = 0.30

# 依据：概要设计说明书第 6.4 节与 FR-24，题干字符数绝对下限为 6 字符
# 题干去空白字符数 < 6 字符判定为表述过短或残缺，直接判为明显歧义
DEFAULT_MIN_STEM_LENGTH: int = 6

# 依据：概要设计说明书第 6.4 节，已有题目比对滑动窗口上限为 500 道
# 超过 500 道时截取最近 500 道题目参与查重与冲突比对，保障单次质检毫秒级响应
MAX_EXISTING_QUESTIONS_WINDOW: int = 500
```

### 2.3 数据结构设计 (DTO)

```python
import enum
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


class QualityCheckType(enum.StrEnum):
    """四类一票否决式质检项类型枚举（对齐 backend/app/models/question.py）。"""

    NO_SOURCE = "NO_SOURCE"  # 无来源题目 (无片段或实词重合率<0.30)
    DUPLICATE = "DUPLICATE"  # 重复题 (向量相似度>=0.90或字符相似度>=0.85)
    ANSWER_CONFLICT = "ANSWER_CONFLICT"  # 答案冲突 (题干相似度>=0.88但标准答案不同)
    AMBIGUITY = "AMBIGUITY"  # 明显歧义 (题干过短/选项冲突/答案不合规)


class QuestionType(enum.StrEnum):
    """题目类型枚举（覆盖 FR-20 规定的七大题型）。"""

    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    FILL_IN_BLANK = "fill_in_blank"
    TERM_EXPLANATION = "term_explanation"
    SHORT_ANSWER = "short_answer"
    CASE_ANALYSIS = "case_analysis"


@dataclass(frozen=True)
class CandidateQuestion:
    """待质检的候选题目（不可变值对象）。"""

    question_id: str  # 候选题临时唯一标识或 UUID
    stem: str  # 题干内容全文
    question_type: str  # 题型枚举字符串 (QuestionType)
    answer: str  # 标准答案（如 'A', 'A,B', 'true', '答案文本'）
    options: tuple[dict[str, Any], ...] = ()  # 选项列表 [{'key': 'A', 'content': '...'}]
    source_snippet_ids: tuple[str, ...] = ()  # 关联来源片段 ID 元组
    source_text: str = ""  # 关联来源片段原文拼接文本
    embedding: tuple[float, ...] | None = None  # 1024 维定长语义向量（可选）
    analysis: str = ""  # 解析说明（可选）
    created_at_seq: int = 0  # 批次内生成顺序序号（越小越早）


@dataclass(frozen=True)
class ExistingQuestionReference:
    """同资料下已通过质检的历史参考题目（不可变参考对象）。"""

    question_id: str  # 历史题目主键 UUID
    stem: str  # 历史题干全文
    question_type: str  # 历史题型 (QuestionType)
    answer: str  # 历史标准答案
    options: tuple[dict[str, Any], ...] = ()  # 历史选项列表
    embedding: tuple[float, ...] | None = None  # 历史题目语义向量


@dataclass(frozen=True)
class QuestionQualityConfig:
    """题目质检门禁可配置参数。"""

    duplicate_vector_threshold: float = DEFAULT_DUPLICATE_VECTOR_THRESHOLD
    duplicate_text_threshold: float = DEFAULT_DUPLICATE_TEXT_THRESHOLD
    conflict_vector_threshold: float = DEFAULT_CONFLICT_VECTOR_THRESHOLD
    min_source_keyword_ratio: float = DEFAULT_MIN_SOURCE_KEYWORD_RATIO
    min_stem_length: int = DEFAULT_MIN_STEM_LENGTH
    max_existing_questions_window: int = MAX_EXISTING_QUESTIONS_WINDOW

    def __post_init__(self) -> None:
        """参数合法性断言防线。"""
        if not (0.0 <= self.duplicate_vector_threshold <= 1.0):
            raise ValueError("duplicate_vector_threshold must be between 0.0 and 1.0")
        if not (0.0 <= self.duplicate_text_threshold <= 1.0):
            raise ValueError("duplicate_text_threshold must be between 0.0 and 1.0")
        if not (0.0 <= self.conflict_vector_threshold <= 1.0):
            raise ValueError("conflict_vector_threshold must be between 0.0 and 1.0")
        if not (0.0 <= self.min_source_keyword_ratio <= 1.0):
            raise ValueError("min_source_keyword_ratio must be between 0.0 and 1.0")
        if self.min_stem_length <= 0:
            raise ValueError("min_stem_length must be positive")
        if self.max_existing_questions_window <= 0:
            raise ValueError("max_existing_questions_window must be positive")


@dataclass(frozen=True)
class QuestionQualityCheckItem:
    """单项质检检查明细记录。"""

    check_type: QualityCheckType  # 检查项类型
    is_passed: bool  # 该项是否通过
    reason: str | None = None  # 未通过原因
    similarity_score: float | None = None  # 相似度度量分值
    metadata: dict[str, Any] = field(default_factory=dict)  # 诊断元数据


@dataclass(frozen=True)
class SingleQuestionQualityResult:
    """单个候选题目质检综合判定结果。"""

    question_id: str  # 题目标识
    is_qualified: bool  # 是否合格（一票否决）
    unqualified_type: QualityCheckType | None  # 首位未通过检查项类型（合格为 None）
    unqualified_reason: str | None  # 剔除原因文本（合格为 None）
    similarity_score: float | None  # 触发拦截时的最高相似度
    check_items: tuple[QuestionQualityCheckItem, ...]  # 四项检查流水线明细


@dataclass(frozen=True)
class QuestionQualityReport:
    """批次题目质检统一产出报告。"""

    qualified_questions: tuple[CandidateQuestion, ...]  # 质检合格保留题目集（进可用题库）
    unqualified_questions: tuple[CandidateQuestion, ...]  # 质检未通过题目集（进待处理区）
    results: tuple[SingleQuestionQualityResult, ...]  # 逐题评估结论序列
    is_degraded: bool  # 是否发生向量不可用降级为字符比对
    total_candidates: int  # 候选题目总数
    qualified_count: int  # 合格题目数量
    unqualified_count: int  # 剔除题目数量
    window_size_used: int  # 实际使用的已有题库比对窗口大小
```

---

## 3. 决策表与四级质检判定规则 (Decision Tables)

### 3.1 规则 1：无来源检查 (`check_source_grounding`)
- **判定逻辑**:
  1. `source_snippet_ids` 为空元组/列表 $\to$ 判定不通过 (`NO_SOURCE`)，原因："缺少来源切片标识"；
  2. `source_text.strip()` 为空文本 $\to$ 判定不通过 (`NO_SOURCE`)，原因："来源片段内容为空"；
  3. 从题干提取实词（长度 $\ge 2$ 的连续中文词与英文单词）：
     - 若提取出的实词列表为空 $\to$ 题干过短或无实词，重合率计为 0.0，判定不通过 (`NO_SOURCE`)；
     - 计算在 `source_text` 中出现的实词比例 $R = \text{命中实词数} / \text{题干实词总数}$；
     - 若 $R < \text{config.min\_source\_keyword\_ratio}$ (0.30) $\to$ 判定不通过 (`NO_SOURCE`)，原因："题干实词在来源片段重合率不足 30.0%"；
     - 若 $R \ge 0.30$ $\to$ 通过。

| 条件组合 | 来源切片ID存在 | 来源文本非空 | 题干实词数 $\ge 1$ | 命中重合率 $R$ | 判定结论 | 原因描述 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **C1-1** | 否 | - | - | - | 不通过 (`NO_SOURCE`) | 缺少来源切片标识 |
| **C1-2** | 是 | 否 (空串/空白) | - | - | 不通过 (`NO_SOURCE`) | 来源片段内容为空 |
| **C1-3** | 是 | 是 | 否 | 0.00 | 不通过 (`NO_SOURCE`) | 题干未包含有效实词 |
| **C1-4** | 是 | 是 | 是 | $R < 0.30$ | 不通过 (`NO_SOURCE`) | 题干实词重合率低于 30.0% |
| **C1-5** | 是 | 是 | 是 | $R = 0.30$ (临界) | 通过 | 无 (合格) |
| **C1-6** | 是 | 是 | 是 | $R > 0.30$ | 通过 | 无 (合格) |

### 3.2 规则 2：重复题检查 (`check_duplication`)
- **比对范围**:
  1. 同批次前序候选题序列 `prior_candidates`（处理批次内重复）；
  2. 已有题库历史参考列表 `existing[:MAX_EXISTING_QUESTIONS_WINDOW]`（截取最近 500 道）。
- **判定逻辑**:
  1. **批次内同题干去重**: 若题干去除空白后与任一前序题干完全一致，判定不通过 (`DUPLICATE`)，原因："同批次内题干完全重复（保留首发题目）"；
  2. **向量相似度比对**: 若当前题目与比对题目均有向量，计算余弦相似度 $S_{vec}$；
     - 若 $S_{vec} \ge \text{config.duplicate\_vector\_threshold}$ (0.90) $\to$ 判定不通过 (`DUPLICATE`)，原因："与已有题目语义向量相似度超限"；
  3. **字符相似度比对**: 计算 2-gram Jaccard 相似度 $S_{txt}$；
     - 若 $S_{txt} \ge \text{config.duplicate\_text\_threshold}$ (0.85) $\to$ 判定不通过 (`DUPLICATE`)，原因："与已有题目字符相似度超限"；
  4. **降级标志**: 若存在候选题目或已有题目缺少向量，跳过向量余弦计算，仅依赖字符相似度比对，并在报告中标记 `is_degraded = True`。

| 条件组合 | 批次内同题干重复 | 向量可用性 | 向量相似度 $S_{vec}$ | 字符相似度 $S_{txt}$ | 判定结论 | 降级标记 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **C2-1** | 是 | - | - | - | 不通过 (`DUPLICATE`) | 不变 |
| **C2-2** | 否 | 双方均有向量 | $S_{vec} \ge 0.90$ | - | 不通过 (`DUPLICATE`) | False |
| **C2-3** | 否 | 双方均有向量 | $S_{vec} = 0.90$ (临界) | - | 不通过 (`DUPLICATE`) | False |
| **C2-4** | 否 | 双方均有向量 | $S_{vec} < 0.90$ | $S_{txt} \ge 0.85$ | 不通过 (`DUPLICATE`) | False |
| **C2-5** | 否 | 双方均有向量 | $S_{vec} < 0.90$ | $S_{txt} = 0.85$ (临界) | 不通过 (`DUPLICATE`) | False |
| **C2-6** | 否 | 双方均有向量 | $S_{vec} < 0.90$ | $S_{txt} < 0.85$ | 通过 | False |
| **C2-7** | 否 | 向量缺失 | 不可用 | $S_{txt} \ge 0.85$ | 不通过 (`DUPLICATE`) | True |
| **C2-8** | 否 | 向量缺失 | 不可用 | $S_{txt} < 0.85$ | 通过 | True |

### 3.3 规则 3：答案冲突检查 (`check_answer_conflict`)
- **生效范围**: 仅对**客观题**生效（`single_choice`, `multiple_choice`, `true_false`）；主观题（`term_explanation`, `short_answer`, `case_analysis`）与填空题自动跳过此检查并直接通过。
- **判定逻辑**:
  1. 遍历已有题目中同属于客观题的记录；
  2. 计算题干相似度 $S_{stem}$（优先向量余弦，向量缺失则用字符相似度）；
  3. 若 $S_{stem} \ge \text{config.conflict\_vector\_threshold}$ (0.88)：
     - 比对标准答案集合：
       - 选择题：解析选项键集合（如 "A, B" $\to$ `{'A', 'B'}`），无序比对；
       - 判断题：二值归一比对（True/False, 对/错, 1/0）；
     - 若答案集合不一致 $\to$ 判定不通过 (`ANSWER_CONFLICT`)，原因："题干高度相似但客观题标准答案冲突"；
  4. 若无相似度 $\ge 0.88$ 的题目，或所有相似题目的标准答案完全一致 $\to$ 通过。

| 条件组合 | 题目是否为客观题 | 存在题干相似度 $S \ge 0.88$ 的已有题 | 标准答案是否一致 (无序集合) | 判定结论 |
| :--- | :--- | :--- | :--- | :--- |
| **C3-1** | 否 (主观题/填空题) | - | - | 跳过并直接通过 |
| **C3-2** | 是 | 否 ($S < 0.88$) | - | 通过 |
| **C3-3** | 是 | 是 ($S \ge 0.88$) | 是 (答案完全一致) | 通过 |
| **C3-4** | 是 | 是 ($S = 0.88$ 临界) | 否 (答案冲突) | 不通过 (`ANSWER_CONFLICT`) |
| **C3-5** | 是 | 是 ($S > 0.88$) | 否 (答案冲突) | 不通过 (`ANSWER_CONFLICT`) |

### 3.4 规则 4：明显歧义检查 (`check_ambiguity`)
- **判定逻辑**:
  1. **题干长度检查**: `len(stem.strip()) < config.min_stem_length` (6) $\to$ 判定不通过 (`AMBIGUITY`)，原因："题干长度小于 6 字符"；
  2. **选项内容重复检查**: 对于包含选项的题目，去除各选项前后空白后，若存在重复内容（`len(contents) != len(set(contents))`）$\to$ 判定不通过 (`AMBIGUITY`)，原因："选项存在重复内容"；
  3. **单选题约束**: 正确选项键数 $\ne 1$ $\to$ 判定不通过 (`AMBIGUITY`)，原因："单选题正确答案数不为 1"；
  4. **多选题约束**:
     - 选项总数 $< 3$ $\to$ 判定不通过 (`AMBIGUITY`)，原因："多选题选项总数少于 3 项"；
     - 正确选项键数 $< 2$ $\to$ 判定不通过 (`AMBIGUITY`)，原因："多选题正确答案少于 2 项"；
     - 正确选项键数 $\ge$ 选项总数 $\to$ 判定不通过 (`AMBIGUITY`)，原因："多选题正确答案包含全量选项"；
  5. **判断题约束**: 答案无法归一为标准布尔二值 $\to$ 判定不通过 (`AMBIGUITY`)，原因："判断题答案非二值格式"；
  6. **填空/主观题约束**: 答案为空或纯空白 $\to$ 判定不通过 (`AMBIGUITY`)，原因："参考答案内容为空"；
  7. **逻辑自相矛盾词检查**: 题干或选项中包含“以上都对”、“以上都不对”、“以上皆对”、“以上均错”且同时存在其它正确选项 $\to$ 判定不通过 (`AMBIGUITY`)，原因："存在'以上都对/错'且与其他选项逻辑冲突"。

| 条件组合 | 题干长度 $\ge 6$ | 选项内容无重复 | 题型特定结构合规 | 互斥词逻辑自洽 | 判定结论 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **C4-1** | 否 ($< 6$) | - | - | - | 不通过 (`AMBIGUITY`) |
| **C4-2** | 是 | 否 (有重复选项) | - | - | 不通过 (`AMBIGUITY`) |
| **C4-3** | 是 | 是 | 否 (如多选单选答案违规) | - | 不通过 (`AMBIGUITY`) |
| **C4-4** | 是 | 是 | 是 | 否 (命中"以上都对"冲突) | 不通过 (`AMBIGUITY`) |
| **C4-5** | 是 | 是 | 是 | 是 | 通过 |

### 3.5 一票否决优先级仲裁矩阵
当一道候选题目同时触发多项缺陷时，严格按 **`NO_SOURCE` (1) $\to$ `DUPLICATE` (2) $\to$ `ANSWER_CONFLICT` (3) $\to$ `AMBIGUITY` (4)** 裁定唯一首选剔除类型：

| 触发缺陷项组合 | 最终裁定 `unqualified_type` | 仲裁依据说明 |
| :--- | :--- | :--- |
| 无来源 + 重复 + 冲突 + 歧义 | `NO_SOURCE` | 来源脱靶为首要阻断条件 |
| 重复 + 冲突 + 歧义 | `DUPLICATE` | 重复题库冗余优先于内容逻辑缺陷 |
| 冲突 + 歧义 | `ANSWER_CONFLICT` | 知识对立打架优先于单题表述歧义 |
| 仅歧义 | `AMBIGUITY` | 单题表述不自洽 |
| 全通过 | `None` (合格) | 题目准入可用题库 |

---

## 4. 可测性设计与测试矩阵 (Design for Testability)

### 4.1 核心可测性原则
1. **零外部依赖**: 算法核脱离数据库连接、网络环境与外部模型单独执行（满足 NFR-22）；
2. **纯函数确定性**: 相同输入在任何机器、任何时刻执行必须产出 100% 确定且完全相同的结果；
3. **零 Mock 替身**: 纯函数核内部逻辑严禁使用 Mock/Patch 打桩，全部测试通过构造具体数据对象执行真实计算。

### 4.2 5 大边界与异常防御测试矩阵

| 边界场景 | 测试输入构造 | 预期断言 | 对应规则 |
| :--- | :--- | :--- | :--- |
| **B-1: 空候选题集合** | `candidates = ()` | 返回 `total_candidates=0`, `qualified=()`, `unqualified=()`, 不抛异常 | 边界防御 1 |
| **B-2: 批次内同题干重复** | 3 道题中第 1 道与第 3 道题干完全相同 (`created_at_seq` 为 1 和 3) | 第 1 道通过（若其他项合格），第 3 道被判定为 `DUPLICATE` | 边界防御 2 |
| **B-3: 来源片段文本为空** | `source_text = "   "`, `source_snippet_ids = ("snp-1",)` | 判定为 `NO_SOURCE`，原因明确指出来源内容为空 | 边界防御 3 |
| **B-4: 向量缺失优雅降级** | 候选题与已有题 `embedding=None` | 跳过向量余弦比对，执行字符 2-gram 相似度，`report.is_degraded == True` | 边界防御 4 |
| **B-5: 阈值闭区间临界值** | 相似度恰好为 `0.9000` (重复)、`0.8800` (冲突)、重合率恰好为 `0.3000` | $0.90$ 触发重复拦截，$0.88$ 触发冲突拦截，$0.30$ 判定重合率合格 | 边界防御 5 |
| **B-6: 非法阈值配置校验** | 传入 `duplicate_vector_threshold = 1.2` 或 `-0.1` | 初始化 `QuestionQualityConfig` 抛出 `ValueError` | 异常防御 6 |
| **B-7: 滑动窗口截断超限** | 已有题目 600 道，传入质检 | 仅比对最近 500 道，`report.window_size_used == 500` | 性能窗口约束 |

### 4.3 覆盖率与白盒质量门槛
- **测试文件**: `backend/tests/core/algorithms/test_question_quality.py`
- **行覆盖率 (Line Coverage)**: $\ge 95\%$
- **分支覆盖率 (Branch Coverage)**: $\ge 90\%$
- **判定覆盖率 (Decision/MCC Coverage)**: 100%（全覆盖决策表中全部条件组合分支）
- **圈复杂度**: 所有拆分纯函数 McCabe $V(G) \le 8$

---

## 5. 替代方案与权衡考量 (Alternatives Considered & Trade-offs)

### 5.1 方案比选：纯函数算法核 vs 服务层混杂 SQL 查询
- **评估方案**: 在 `QuestionService` 中直接执行 SQL `SELECT ... WHERE embedding <=> :vec < 0.1` 并完成判定。
- **采纳方案**: 提取为独立的**纯函数计算核** (`backend/app/core/algorithms/question_quality.py`)。
- **权衡理由**:
  - 需求 NFR-22 与概要设计第 6.4/7.1 节明确要求核心质检算法脱离数据库和网络单独可测；
  - 若混杂在服务层中，每次单元测试必须启动数据库容器或构造庞大的 ORM Session Mock，无法做到毫秒级极速反馈；
  - 纯函数计算核保证输入与输出完全解耦，未来支持在客户端或边缘 Worker 中复用。

### 5.2 方案比选：纯 Python 字符 N-gram vs 引入外部分词分词库 (Jieba)
- **评估方案**: 引入 `jieba` 进行中文分词与 TF-IDF 关键词抽取。
- **采纳方案**: 采用**纯 Python 正则表达式与连续字符 2-gram Jaccard 相似度**。
- **权衡理由**:
  - `jieba` 初始化需加载数十兆词典文件，产生冷启动耗时与内存开销，且违背算法核“零外部依赖、极速轻量”的原则；
  - 题干长度通常在 10~200 字之间，连续 2-gram 字符片段重合度对重复题与字面雷同的捕获灵敏度极高（测试验证效果等价或更严格）；
  - 满足 AGENTS.md 依赖最小化要求，规避额外的供应链漏洞与维护成本。

### 5.3 方案比选：短路阻断 vs 完整收集四项结果
- **评估方案**: 一道题目在无来源失败后立即退出后续三项检查。
- **采纳方案**: 保留流水线短路与记录结构解耦：流水线严格按一票否决固定顺序记录首要失败原因，同时记录单题检查结果对象，保障诊断元数据可追溯。
- **权衡理由**:
  - 满足概要设计第 6.4 节“一道题同时命中多个条件时原因取顺序最靠前的一项”；
  - 节省不必要的向量距离计算算力开销。

---

## 6. 7 维动态风险扫描与回滚隔离预案 (Risk & Rollback Verification)

### 6.1 7 维动态风险评估矩阵

| 风险维度 | 评估结果 | 影响说明与控制对策 |
| :--- | :--- | :--- |
| **1. Affected Files** | 低 (3 个文件) | 仅涉及 `question_quality.py`, `__init__.py` 及对应单元测试文件，跨模块广度为 0。 |
| **2. Public API** | 无 (0 变动) | 纯底层算法核，无 HTTP API 契约变更。 |
| **3. Data Schema** | 无 (0 变动) | `Question`, `QuestionQualityCheck` 实体已在 ZL-105 预先就绪，无需数据库迁移。 |
| **4. Auth & Security**| 无安全隐患 | 纯函数无鉴权与多租户状态侵入；日志脱敏遵循 8 要素，不泄露题干与答案原文。 |
| **5. Dependencies** | 零新增 (0 外部依赖)| 仅使用 Python 标准库，不引入任何新第三方 package。 |
| **6. Rollback** | 极低 (无状态回滚) | 纯函数核不持久化状态，若有缺陷可直接通过 Git Revert 回滚代码，无数据迁移包袱。 |
| **7. Blast Radius** | 极低 (受控沙箱) | 算法运行在独立纯函数调用栈，异常通过合法类型返回，不影响主服务进程生命周期。 |

- **变更分级判定**: 本变更影响范围高度收敛于 `app/core/algorithms` 纯算法计算核，7 维风险全部为低或无，准确评定为 **Tier 2 (Single-Module Feature)**，无需触发 Tier 3 升级。

### 6.2 待处理区 (pending_review) 隔离与回滚策略
1. **数据隔离防线**:
   - 算法核输出的 `unqualified_questions` 在服务层持久化时强制标记 `status = QuestionStatus.PENDING_REVIEW`；
   - 组卷接口与练习模块通过联合索引 `ix_questions_user_mat_ver_status` 严格过滤 `status == 'available'`，被拦截题目物理隔绝于学生答题流；
   - 掌握度聚合算法（`aggregate_mastery_scores`）强制排除 `pending_review` 题目，防止脏数据污染诊断分析。
2. **算法故障应急与参数回滚**:
   - 所有门禁阈值均通过 `QuestionQualityConfig` 注入，若线上出现误杀率偏高，可通过配置系统即时调整 `duplicate_vector_threshold` 或 `min_source_keyword_ratio`，无需重新打包构建发布代码；
   - 待处理区保留完整 `QuestionQualityCheck` 检查项与剔除原因，支持人工管理端对拦截题目进行一键复核或放行编辑。

---

## 7. 阶段准出签批 (Gate 2 Sign-off)
- [x] 架构流向与核心纯函数契约已冻结
- [x] 5 大边界、四项一票否决决策表与测试矩阵齐备
- [x] 7 维风险已核验且确定评级为 Tier 2
- **审查结论**: Accepted
- **签批人 / 日期**: TechLead、SecLead / 2026-09-23

