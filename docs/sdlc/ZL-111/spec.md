# Spec: 判题阈值与匹配算法 (match_and_grade_answer) - 技术契约

- **关联 Intent**: ZL-111
- **主导设计人**: Dev / TechLead
- **当前状态**: In-Review
- **任务评级**: Tier 2 (Single-Module Feature)

---

## 1. 架构流向与设计方案

### 1.1 模块定位与分层边界
判题阈值与匹配算法核是智练自主学习平台练习提交与混合判题主链的核心计算中枢，严格归属于系统五层单向架构矩阵的**纯函数计算核**：
- **物理路径**: `backend/app/core/algorithms/grading.py`
- **分层依赖铁律**:
  - 依赖关系严格单向向下/向内，绝对禁止导入 `fastapi`, `sqlalchemy`, `httpx`, `redis`, `boto3` 等任何 Web 框架、网络库、缓存或 ORM 驱动；
  - 绝对禁止导入上层业务模块 `app/services`、`app/repositories` 以及外部能力层 `app/integrations`；
  - 必须通过 `python3 tooling/check_layers.py --root backend/app` 单向依赖门禁校验（0 违规）；
  - 模块内全量函数具备确定性与无状态特征（Zero I/O、无全局可变变量、不读取系统时钟、不依赖外部环境变量）；
  - 输入参数与输出产物均为不可变原生值对象（`dataclasses.dataclass(frozen=True)`、标准类型 `tuple`、`str`、`float`、`int`、`bool` 等）。
- **与业务模型解耦**:
  - 本模块与 `backend/app/models/practice.py` 中的 `AttemptItem`、`GradingRecord` 及 `backend/app/models/question.py` 中的 `Question` 持久化实体严格解耦；
  - 服务层编排模块 `GradingService` (ZL-123) 与异步 Worker (`worker-grade`) 负责读取用户作答及题目快照转换为不可变数据结构，传入本算法核；
  - 算法核执行计算后输出统一的 `GradingResult`，服务层根据 `requires_llm` 与 `grading_method` 决定是直接固化离线得分（`channel="offline"`, `status="success"`），还是投递至大模型智能判题队列（`channel="ai"`, `status="pending"`）。

### 1.2 核心判题与分流流水线设计

```mermaid
flowchart TD
    Start[输入: user_answer, reference_answer, question_type, rubric, embeddings, config] --> EmptyCheck{作答是否为空/全空白?}
    
    %% 未作答分支
    EmptyCheck -- 是 --> ReturnUnanswered[输出未作答结果: is_answered=False, score=0.0, is_correct=False, requires_llm=False, grading_method=OFFLINE_RULE]
    
    %% 正常分流分支
    EmptyCheck -- 否 --> BranchType{题目类型 question_type}
    
    %% 客观题分支
    subgraph ObjectivePipeline [客观题离线精准判题流水线 (FR-37, FR-38)]
        BranchType -- 单选/多选/判断/填空 --> ObjNorm[答案深度规范化清洗]
        ObjNorm --> ObjType{具体题型}
        ObjType -- 单选题 --> MatchSingle[去除首尾空格/统一大写比对]
        ObjType -- 多选题 --> MatchMulti[字母排序/去重/规范分隔符全量一致比对]
        ObjType -- 判断题 --> MatchTF[中英文真假二值多语态映射归一化比对]
        ObjType -- 填空题 --> MatchBlank[全角转半角/多余空格消除/大小写小写化/数字格式归一/多候选答案比对]
        MatchSingle --> ObjScore[确定对错: 正确得 max_score, 错误得 0.0]
        MatchMulti --> ObjScore
        MatchTF --> ObjScore
        MatchBlank --> ObjScore
        ObjScore --> BuildObjResult[装配 GradingResult: requires_llm=False, grading_method=OFFLINE_RULE]
    end
    
    %% 主观题分支
    subgraph SubjectivePipeline [主观题双阈值与转 AI 决策流水线 (FR-39, FR-40)]
        BranchType -- 名词解释/简答/案例分析等 --> LenCrop[作答长度防御检查: 超过 2000 字符强制截断并记录标记]
        LenCrop --> IdenticalCheck{与参考答案完全一致?}
        IdenticalCheck -- 是 --> FullScore[直接满分: score=max_score, match_score=1.0, requires_llm=False]
        IdenticalCheck -- 否 --> RubricEval[评分细则要点评估: 逐条检测关键词命中率 >= 60% 且分句否定词未命中]
        RubricEval --> SimEval[语义相似度计算: 优先向量余弦; 缺向量降级为实词重合+Jaccard]
        SimEval --> ScoreSynth[匹配度合成: match_score = point_coverage * 0.6 + semantic_sim * 0.4]
        ScoreSynth --> DecisionEngine[4 类转 AI 决策判定引擎 arbitrate_llm_transition]
        
        DecisionEngine --> NeedsLLM{触发转 AI 任一条件?}
        NeedsLLM -- 是 --> BuildLLMResult[装配 GradingResult: requires_llm=True, grading_method=PENDING_LLM, 记录 transition_reason]
        NeedsLLM -- 否 --> ThresholdJudge{match_score 阈值区间}
        ThresholdJudge -- ">= 0.82 (上阈值)" --> GradeCorrect[离线判对: score = round_to_half(max_score * match_score), is_correct=True]
        ThresholdJudge -- "<= 0.45 (下阈值)" --> GradeWrong[离线判错: score = 0.0, is_correct=False]
        GradeCorrect --> BuildSubjResult[装配 GradingResult: requires_llm=False, grading_method=OFFLINE_RULE]
        GradeWrong --> BuildSubjResult
    end
    
    BuildObjResult --> Output[输出不可变 GradingResult]
    BuildLLMResult --> Output
    BuildSubjResult --> Output
    ReturnUnanswered --> Output
```

### 1.3 白盒复杂度控制与函数拆解 ($V(G) \le 10$)
为严格贯彻《概要设计说明书》第 7.1 节与 `AGENTS.md` 对判题计算核的架构红线要求（判题匹配决策函数 McCabe 环路复杂度 $V(G) \le 10$），本模块将庞大的匹配与判分逻辑拆解为 9 个高内聚、职责单一的纯函数：

1. `normalize_objective_token(raw_token: str, question_type: QuestionType) -> str` ($V(G) \le 5$):
   - 单选题、多选题选项字母规范化（去空格、统一大写、多选题排序去重）。
2. `normalize_boolean_answer(raw_answer: str) -> bool | None` ($V(G) \le 6$):
   - 中英文、数字、符号多语态真假表达映射为二值布尔类型，无法识别返回 `None`。
3. `normalize_fill_blank_text(text: str) -> str` ($V(G) \le 6$):
   - 填空题规范化清洗：首尾空白与内部连续多余空白消除、全角字符与标点转半角、英文字母小写化、中文/阿拉伯数字格式归一。
4. `grade_objective_question(question_type: QuestionType, user_answer: str, reference_answer: str, max_score: float, options: Sequence[dict[str, Any]] = ()) -> tuple[bool, float, str]` ($V(G) \le 8$):
   - 客观题确定性判分流水线，输出 `(is_correct, score, reasoning)`。
5. `calculate_cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float` ($V(G) \le 4$):
   - 纯 Python 高性能向量余弦相似度计算，提供零模长与维度不匹配的防除零保护。
6. `calculate_text_lexical_similarity(user_text: str, reference_text: str) -> float` ($V(G) \le 5$):
   - 缺向量时的纯文本降级相似度计算：连续实词（长度 $\ge 2$）重合率（权重 0.7）与字符 2-gram Jaccard（权重 0.3）加权融合。
7. `detect_negation_inversion(user_text: str, reference_text: str, focus_keywords: Sequence[str] = ()) -> tuple[bool, str | None]` ($V(G) \le 7$):
   - 汉语分句级关键否定词扫描与极性反转冲突检测。
8. `evaluate_subjective_rubric(user_text: str, rubric_items: Sequence[GradingRubricItem]) -> tuple[float, tuple[str, ...], tuple[str, ...], bool]` ($V(G) \le 7$):
   - 评分细则逐条评估：关键词命中率是否 $\ge 60\%$、分句作用域内是否存在否定词、输出命中与遗漏要点。
9. `arbitrate_llm_transition(match_score: float, point_coverage: float, semantic_sim: float, has_negation_inversion: bool, has_multiple_equivalents: bool, rubric_empty: bool, config: GradingConfig) -> tuple[bool, TransitionReason | None]` ($V(G) \le 7$):
   - 4 类转 AI 决策判定核心仲裁函数，严格按照决策表优先级仲裁。
10. `match_and_grade_answer(...) -> GradingResult` ($V(G) \le 8$):
    - 顶层总控入口函数：主客观题分流、未作答短路、长文本截断、流水线调度与结果组装。

---

## 2. API 与数据契约设计

### 2.1 依赖与调用契约
- **运行环境**: Python 3.12+ / 纯标准库。
- **允许导入模块**: `dataclasses`, `enum`, `math`, `re`, `unicodedata`, `typing`, `collections.abc`。
- **并发与时间纯度**: 无可变全局状态，线程安全；不调用任何 I/O 阻塞调用，单次客观题判定延迟 $\le 0.5\text{ms}$，单次主观题纯文本判定延迟 $\le 5\text{ms}$。

### 2.2 阈值常量体系与决策基准
所有阈值常量均强制显式注明《概要设计说明书》与《软件需求规格说明书》依据，严禁业务逻辑硬编码无依据数值：

```python
# ==============================================================================
# 判题阈值与分流决策核心常量
# 严格遵循《概要设计说明书》第 6.5 节与《软件需求规格说明书》FR-37 至 FR-44
# ==============================================================================

# 依据：概要设计说明书第 6.5 节与 FR-40，主观题匹配度上阈值取 0.82
# 达到或超过该值时按离线判对处理，离线判对准确率在测试样本上保持 95% 以上
DEFAULT_UPPER_SIMILARITY_THRESHOLD: float = 0.82

# 依据：概要设计说明书第 6.5 节与 FR-40，主观题匹配度下阈值取 0.45
# 低于或等于该值时按离线判错处理，避免明显错误答案被离线判对
DEFAULT_LOWER_SIMILARITY_THRESHOLD: float = 0.45

# 依据：概要设计说明书第 6.5 节，主观题合成公式中要点覆盖率权重取 0.60
DEFAULT_RUBRIC_COVERAGE_WEIGHT: float = 0.60

# 依据：概要设计说明书第 6.5 节，主观题合成公式中语义相似度权重取 0.40
DEFAULT_SEMANTIC_SIMILARITY_WEIGHT: float = 0.40

# 依据：概要设计说明书第 6.5 节，单条要点中关键词命中的下限比例为 60% (0.60)
DEFAULT_KEYWORD_HIT_RATIO_THRESHOLD: float = 0.60

# 依据：概要设计说明书第 6.5 节与 FR-40 第四类转 AI 条件
# 要点覆盖率为 0 但语义相似度高于 0.55 时判定为无法严格匹配，必须转 AI
DEFAULT_ZERO_COVERAGE_HIGH_SIMILARITY_THRESHOLD: float = 0.55

# 依据：概要设计说明书第 6.5 节，主观题作答文本最大截断字符数取 2000
MAX_SUBJECTIVE_ANSWER_LENGTH: int = 2000

# 依据：概要设计说明书第 6.5 节，得分舍入粒度为 0.5 分 (half-up)
SCORE_ROUNDING_UNIT: float = 0.5

# 依据：概要设计说明书第 6.5 节，中文关键否定词集（用于极性反转及要点否定抑制）
CHINESE_NEGATION_WORDS: frozenset[str] = frozenset(
    {
        "不", "没", "没有", "未", "非", "否", "并非", "毫无", "决不", "绝不",
        "莫", "勿", "毋", "甭", "未曾", "未尝", "无", "免", "拒", "缺",
    }
)

# 预编译正则：分句分隔符（用于界定否定词作用域，否定修饰不跨分句传播）
SENTENCE_SPLIT_PATTERN: re.Pattern[str] = re.compile(r"[，。；！？\n;,!?]+")

# 预编译正则：中英文有效实词（连续汉字 >= 2 或连续英文字母 >= 2）
CONTENT_WORD_PATTERN: re.Pattern[str] = re.compile(r"[\u4e00-\u9fa5]{2,}|[a-zA-Z]{2,}")
```

### 2.3 数据结构设计 (DTO)

```python
import enum
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


class QuestionType(enum.StrEnum):
    """题目类型枚举（严格对齐 FR-20 及 backend/app/models/question.py）。"""

    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    FILL_IN_BLANK = "fill_in_blank"
    TERM_EXPLANATION = "term_explanation"
    SHORT_ANSWER = "short_answer"
    CASE_ANALYSIS = "case_analysis"


# 客观题类型集合
OBJECTIVE_QUESTION_TYPES: frozenset[str] = frozenset(
    {
        QuestionType.SINGLE_CHOICE,
        QuestionType.MULTIPLE_CHOICE,
        QuestionType.TRUE_FALSE,
        QuestionType.FILL_IN_BLANK,
    }
)

# 主观题类型集合
SUBJECTIVE_QUESTION_TYPES: frozenset[str] = frozenset(
    {
        QuestionType.TERM_EXPLANATION,
        QuestionType.SHORT_ANSWER,
        QuestionType.CASE_ANALYSIS,
    }
)


class GradingMethod(enum.StrEnum):
    """判题生效方式/渠道枚举（对齐 FR-43 及 backend/app/models/practice.py）。"""

    OFFLINE_RULE = "OFFLINE_RULE"  # 离线确定性判分完成 (客观题秒判 / 主观题高置信度双阈值判定)
    PENDING_LLM = "PENDING_LLM"    # 触发转 AI 条件，待大模型智能判题处理


class TransitionReason(enum.StrEnum):
    """转 AI 判题的 4 类触发原因枚举（严格对齐《概要设计说明书》6.5 节与 FR-40）。"""

    UNCERTAIN_RANGE = "UNCERTAIN_RANGE"
    # 条件 1: 综合匹配度落在不确定区间 (0.45, 0.82)

    NEGATION_INVERSION = "NEGATION_INVERSION"
    # 条件 2: 作答与参考答案在核心分句上存在否定词反转/极性冲突风险

    MULTIPLE_EQUIVALENTS_OR_EMPTY_RUBRIC = "MULTIPLE_EQUIVALENTS_OR_EMPTY_RUBRIC"
    # 条件 3: 题目配置了多个等价表达或评分细则为空，规则无法确定

    ZERO_COVERAGE_HIGH_SIMILARITY = "ZERO_COVERAGE_HIGH_SIMILARITY"
    # 条件 4: 要点覆盖率为 0 但语义相似度高于 0.55，无法严格比对


@dataclass(frozen=True)
class GradingRubricItem:
    """主观题评分细则要点不可变值对象。"""

    point_id: str  # 要点唯一标识 (如 'pt-01')
    description: str  # 要点描述文本
    weight: float = 1.0  # 该要点分值权重 (必须 > 0)
    keywords: tuple[str, ...] = ()  # 核心采分关键词元组 (至少命中 60%)
    negation_words: tuple[str, ...] = ()  # 该要点互斥否定词集合


@dataclass(frozen=True)
class GradingConfig:
    """判题与分流决策可配置参数不可变对象。"""

    upper_similarity_threshold: float = DEFAULT_UPPER_SIMILARITY_THRESHOLD
    lower_similarity_threshold: float = DEFAULT_LOWER_SIMILARITY_THRESHOLD
    rubric_coverage_weight: float = DEFAULT_RUBRIC_COVERAGE_WEIGHT
    semantic_similarity_weight: float = DEFAULT_SEMANTIC_SIMILARITY_WEIGHT
    keyword_hit_ratio_threshold: float = DEFAULT_KEYWORD_HIT_RATIO_THRESHOLD
    zero_coverage_high_similarity_threshold: float = DEFAULT_ZERO_COVERAGE_HIGH_SIMILARITY_THRESHOLD
    max_answer_length: int = MAX_SUBJECTIVE_ANSWER_LENGTH
    score_rounding_unit: float = SCORE_ROUNDING_UNIT

    def __post_init__(self) -> None:
        """参数合法性边界防御断言。"""
        if not (0.0 <= self.lower_similarity_threshold < self.upper_similarity_threshold <= 1.0):
            raise ValueError("Must satisfy: 0.0 <= lower_similarity_threshold < upper_similarity_threshold <= 1.0")
        if not math.isclose(self.rubric_coverage_weight + self.semantic_similarity_weight, 1.0, abs_tol=1e-5):
            raise ValueError("Sum of rubric_coverage_weight and semantic_similarity_weight must equal 1.0")
        if not (0.0 < self.keyword_hit_ratio_threshold <= 1.0):
            raise ValueError("keyword_hit_ratio_threshold must be in (0.0, 1.0]")
        if not (0.0 <= self.zero_coverage_high_similarity_threshold <= 1.0):
            raise ValueError("zero_coverage_high_similarity_threshold must be in [0.0, 1.0]")
        if self.max_answer_length <= 0:
            raise ValueError("max_answer_length must be positive")
        if self.score_rounding_unit <= 0:
            raise ValueError("score_rounding_unit must be positive")


@dataclass(frozen=True)
class GradingResult:
    """判题匹配算法统一产出不可变结果报告（FR-37 至 FR-44）。"""

    score: float  # 本次判题得出分值 (0.0 <= score <= max_score)
    max_score: float  # 题目总满分分值 (默认 1.0)
    is_correct: bool  # 是否判为正确 (若转 AI 暂标 False 或最终由 AI 裁定)
    is_answered: bool  # 用户是否有效作答 (空白/未填为 False)
    requires_llm: bool  # 是否需要转 AI 判题
    grading_method: GradingMethod  # 判题渠道: OFFLINE_RULE 或 PENDING_LLM
    transition_reason: TransitionReason | None = None  # 转 AI 触发原因 (若未转 AI 为 None)
    match_score: float | None = None  # 综合匹配度得分 (0.0 ~ 1.0)
    hit_keywords: tuple[str, ...] = ()  # 命中的细则采分关键词元组
    missing_keywords: tuple[str, ...] = ()  # 遗漏的核心采分关键词元组
    confidence: float = 1.0  # 判题置信度评分 (0.0 ~ 1.0)
    reasoning: str = ""  # 判定依据与诊断原因文本说明
    details: dict[str, Any] = field(default_factory=dict)  # 扩展元数据 (如截断标记、各要点明细等)
```

### 2.4 核心函数契约签名

```python
def match_and_grade_answer(
    question_type: str | QuestionType,
    user_answer: str,
    reference_answer: str,
    max_score: float = 1.0,
    options: Sequence[dict[str, Any]] = (),
    grading_rubric: Sequence[GradingRubricItem | dict[str, Any]] = (),
    user_embedding: Sequence[float] | None = None,
    reference_embedding: Sequence[float] | None = None,
    has_multiple_equivalents: bool = False,
    config: GradingConfig | None = None,
) -> GradingResult:
    """判题匹配与双阈值分流主控纯函数。

    Args:
        question_type: 题目类型（QuestionType 枚举或对应合法字符串）
        user_answer: 用户作答原文
        reference_answer: 标准参考答案原文
        max_score: 该题目满分分值（必须 > 0.0，默认 1.0）
        options: 客观选择题选项列表（含 key 和 content）
        grading_rubric: 主观题评分细则要点序列（RubricItem 或结构化字典）
        user_embedding: 用户答案 1024 维定长语义向量（可选）
        reference_embedding: 参考答案 1024 维定长语义向量（可选）
        has_multiple_equivalents: 是否标记了存在多个等价表达（FR-40 条件 3）
        config: 判题算法与阈值配置对象，缺省使用默认配置

    Returns:
        GradingResult: 包含得分、对错判定、转 AI 标记与明细的不可变结果对象

    Raises:
        ValueError: 当 max_score <= 0、question_type 非法或配置参数无效时抛出
    """
```

---

## 3. 客观题规则化判题契约 (FR-37, FR-38)

客观题判分完全断网运行，零外部调用，直接得出最终得分（正确得 `max_score`，错误得 `0.0`），`requires_llm = False`，`grading_method = GradingMethod.OFFLINE_RULE`。

### 3.1 单项选择题 (SINGLE_CHOICE)
1. **标准化规则**:
   - 提取答案中的英文字母（A-Z），忽略两端与内部空格，统一转大写；
   - 若提取结果非单字母（如为空或多于一个字母），判定为格式无效或错误；
2. **判定逻辑**: 标准化后的 `user_answer == reference_answer` 判为正确得满分，否则 0 分。

### 3.2 多项选择题 (MULTIPLE_CHOICE)
1. **标准化规则**:
   - 提取所有选项字母字符，过滤逗号（`,`、`，`）、分号（`;`、`；`）、斜杠、空格等一切标点；
   - 统一转大写，去重并按字典序字母升序排列拼装为紧凑字符串（例如 `"b, a, B"` $\to$ `"AB"`，`"c; a; b"` $\to$ `"ABC"`）；
2. **判定逻辑**: 用户选项排序集合必须与参考答案排序集合**完全一致**（$100\%$ 一致性）方判对得满分，漏选、错选、多选均得 0 分。

### 3.3 判断题 (TRUE_FALSE)
1. **真假双向归一化映射字典**:
   - 正向真值集合 (`True`): `{"TRUE", "T", "1", "YES", "Y", "对", "正确", "是", "V", "√"}`
   - 负向假值集合 (`False`): `{"FALSE", "F", "0", "NO", "N", "错", "错误", "否", "X", "×"}`
2. **判定逻辑**:
   - 分别将 `user_answer` 与 `reference_answer` 映射为 `bool`；
   - 若用户作答无法解析在上述两集合内，则判为错误得 0 分；
   - 二者解析出的布尔值一致判对得满分，否则 0 分。

### 3.4 填空题 (FILL_IN_BLANK) 深度规范化与多候选支持
依据 FR-38，填空题比对前必须执行 4 步规范化清洗：
1. **全角转半角 (Unicode NFKC + 手工映射)**:
   - 全角英文字母、全角数字转半角；
   - 全角标点符号转半角（如 `，` $\to$ `,`, `（` $\to$ `(`, `）` $\to$ `)` 等）；
2. **空白处理**: 去除首尾空白，并将内部连续的多个空白（空格、Tab、换行）压缩为一个半角空格；
3. **大小写统一**: 英文字符统一转换为全小写；
4. **数字格式归一**: 中文小写数字（零一二三四五六七八九十）与阿拉伯数字互转对齐（统一映射为阿拉伯数字序列）；
5. **多等价候选答案与多空判定**:
   - 支持单个填空题配置多个等价答案（以 `|`、`///`、`||` 或换行符分隔）；
   - 用户作答规范化后只要与参考答案中**任一候选答案**完全匹配，即判为正确；
   - 对于多空题（标准答案以分号或 `&&` 区分各空），用户作答按相应分隔符拆解逐空比对，全空正确得满分。

---

## 4. 主观题双阈值与语义要点评估 (FR-39, FR-40)

主观题（名词解释、简答题、案例分析）采用两阶段混合判题模型，先在纯函数核执行离线匹配与要点计算，再执行双阈值与 4 类转 AI 决策判定。

### 4.1 长度限制与防御性截断
- 若 `len(user_answer) > 2000` 字符（`MAX_SUBJECTIVE_ANSWER_LENGTH`），直接截取前 2000 个字符参与后续匹配；
- 在输出的 `GradingResult.details` 中记录 `{"is_truncated": True, "original_length": ...}`。

### 4.2 评分细则 (Rubric) 与分句否定词反转评估
1. **关键词命中率计算**:
   - 针对评分细则中的每一条要点 $R_i$，提取其定义的关键词集合 $K_i$；
   - 计算用户作答中命中的关键词数量 $H_i = |\{k \in K_i \mid k \in \text{user\_text}\}|$；
   - 要点关键词命中率 $r_i = H_i / |K_i|$；若 $r_i \ge 0.60$（`DEFAULT_KEYWORD_HIT_RATIO_THRESHOLD`），初步视为命中；
2. **否定词局部作用域抑制 (Negative Inhibition)**:
   - 汉语否定修饰词通常受限于分句边界。将用户答案按 `，。；！？\n;,!?` 切分为独立分句；
   - 若命中的关键词所在的具体分句中，存在否定词集合中的词汇（如“不支持”、“未实现”、“并非”），则该关键词所在的分句极性发生反转；
   - **否定词反转判定**: 若要点关键词命中但该分句同时出现否定词，**该要点判定取反（不计入命中）**，并记入遗漏要点；同时在主控上下文标记 `has_negation_inversion = True`；
3. **要点覆盖率合成**:
   - 命中要点的权重之和除以全部要点权重之和：$\text{point\_coverage} = \frac{\sum_{i \in \text{hit}} w_i}{\sum_{i} w_i}$；
   - 若评分细则为空，$\text{point\_coverage} = 0.0$，同时标记 `rubric_empty = True`。

### 4.3 综合语义相似度计算
1. **向量余弦相似度 (优先路径)**:
   - 若传入了合法且非全零的 `user_embedding` 与 `reference_embedding`（维度一致）：
     $$\text{semantic\_sim} = \frac{\mathbf{u} \cdot \mathbf{v}}{\|\mathbf{u}\| \|\mathbf{v}\|}$$
   - 结果裁剪至 $[0.0, 1.0]$ 区间；
2. **纯文本降级相似度 (缺向量兜底)**:
   - 若无向量，采用双重文本相似度加权：
     - 实词重合度 $S_{\text{word}}$：提取长度 $\ge 2$ 的实词，计算用户答案实词在参考答案中的召回率；
     - 字符 2-gram Jaccard 相似度 $S_{\text{jaccard}}$：
       $$S_{\text{jaccard}} = \frac{|\text{grams}(u) \cap \text{grams}(v)|}{|\text{grams}(u) \cup \text{grams}(v)|}$$
     - $\text{semantic\_sim} = 0.7 \times S_{\text{word}} + 0.3 \times S_{\text{jaccard}}$。

### 4.4 匹配度合成公式与双阈值区间定义
依据《概要设计说明书》第 6.5 节：
$$\text{match\_score} = \text{point\_coverage} \times 0.60 + \text{semantic\_sim} \times 0.40$$

**双阈值区间与开闭约定**:
- $\text{match\_score} \ge 0.82$（恰等于上阈值属于离线判对区间）：
  - 若未触发任何转 AI 条件，**离线判对**；
  - 得分按题目分值乘以匹配度并按 0.5 粒度四舍五入：
    $$\text{score} = \frac{\text{round}(\text{max\_score} \times \text{match\_score} \times 2)}{2}$$
  - `is_correct = True`，`requires_llm = False`，`grading_method = OFFLINE_RULE`；
- $\text{match\_score} \le 0.45$（恰等于下阈值属于离线判错区间）：
  - 若未触发特定转 AI 疑点，**离线判错**；
  - 得分 $\text{score} = 0.0$；
  - `is_correct = False`，`requires_llm = False`，`grading_method = OFFLINE_RULE`；
- $0.45 < \text{match\_score} < 0.82$（开区间）：
  - 属于不确定过渡区间，直接触发**条件 1** 转 AI 判题。

---

## 5. 4 类转 AI 决策表与条件组合覆盖矩阵 (FR-40)

转 AI 决策是防范主观题误判的核心屏障。纯函数决策仲裁函数 `arbitrate_llm_transition` 严格执行以下优先级决策表：

### 5.1 4 类转 AI 决策规则表

| 优先级 | 转 AI 条件类型 | 触发逻辑定义 | 业务与安全依据 | 仲裁产物 (`TransitionReason`) |
| :--- | :--- | :--- | :--- | :--- |
| **P1** | **条件 2: 否定词反转风险** | `has_negation_inversion == True`（作答分句中出现与要点互斥的否定词，或全局否定极性反转） | 表面字面高度相似但语义完全反转，严禁离线判对，必须交由 LLM 甄别反义 | `NEGATION_INVERSION` |
| **P2** | **条件 3: 多等价表达或细则缺失** | `has_multiple_equivalents == True` 或 `rubric_empty == True` | 存在多种正确答案变体规则无法覆盖，或缺少量化细则无法离线评估 | `MULTIPLE_EQUIVALENTS_OR_EMPTY_RUBRIC` |
| **P3** | **条件 4: 实词要点缺失但高相似** | `point_coverage == 0.0` 且 `semantic_sim > 0.55` | 疑似套话、抄题干或空话，表面相似度高但采分点未命中，规则无法断定 | `ZERO_COVERAGE_HIGH_SIMILARITY` |
| **P4** | **条件 1: 不确定过渡区间** | $0.45 < \text{match\_score} < 0.82$ | 既非极高置信度正确，亦非明显错误，属于模型擅长的模糊推理区间 | `UNCERTAIN_RANGE` |

只要上述 4 类条件满足任一，立即判定：
- `requires_llm = True`；
- `grading_method = GradingMethod.PENDING_LLM`；
- `score = 0.0`（等待 AI 给出建议分值与修正，不提前判分）；
- 记录首个命中的 `TransitionReason`。

### 5.2 决策条件判定矩阵与覆盖设计

| 用例类别 | match_score | point_cov | sem_sim | 否定词反转 | 多等价/无细则 | 转 AI? | 判定渠道 | 期望输出得分/状态 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **TC-D-01: 上阈值离线判对** | 0.85 | 0.90 | 0.80 | False | False | **False** | OFFLINE_RULE | `score=0.85/1.0`, 正确 |
| **TC-D-02: 恰等上阈值(0.82)** | 0.82 | 0.80 | 0.85 | False | False | **False** | OFFLINE_RULE | `score=0.82/1.0` (round to 0.8或0.5) |
| **TC-D-03: 下阈值离线判错** | 0.30 | 0.20 | 0.40 | False | False | **False** | OFFLINE_RULE | `score=0.0`, 错误 |
| **TC-D-04: 恰等下阈值(0.45)** | 0.45 | 0.40 | 0.50 | False | False | **False** | OFFLINE_RULE | `score=0.0`, 错误 |
| **TC-D-05: 条件 1 (区间内 0.65)**| 0.65 | 0.60 | 0.70 | False | False | **True** | PENDING_LLM | `UNCERTAIN_RANGE` |
| **TC-D-06: 条件 1 边界 (0.4501)**| 0.4501 | 0.40 | 0.50 | False | False | **True** | PENDING_LLM | `UNCERTAIN_RANGE` |
| **TC-D-07: 条件 1 边界 (0.8199)**| 0.8199 | 0.80 | 0.84 | False | False | **True** | PENDING_LLM | `UNCERTAIN_RANGE` |
| **TC-D-08: 条件 2 (高分带否定词)**| 0.88 | 0.0 (抑制)| 0.85 | **True** | False | **True** | PENDING_LLM | `NEGATION_INVERSION` |
| **TC-D-09: 条件 3 (多等价表达)** | 0.85 | 1.00 | 0.80 | False | **True** | **True** | PENDING_LLM | `MULTIPLE_EQUIVALENTS...` |
| **TC-D-10: 条件 3 (评分细则为空)**| 0.36 | 0.00 | 0.90 | False | **细则空** | **True** | PENDING_LLM | `MULTIPLE_EQUIVALENTS...` |
| **TC-D-11: 条件 4 (0覆盖+相似0.60)**| 0.24 | 0.00 | 0.60 | False | False | **True** | PENDING_LLM | `ZERO_COVERAGE_HIGH_SIMILARITY`|
| **TC-D-12: 0覆盖+低相似(0.40)**  | 0.16 | 0.00 | 0.40 | False | False | **False** | OFFLINE_RULE | `score=0.0`, 离线判错 |

---

## 6. 可测性设计 (Design for Testability)

### 6.1 纯函数计算核无 Mock 特性
- 本模块中全部核心计算函数均为确定性纯函数，不产生任何网络、磁盘或数据库 I/O；
- 单元测试运行在 `tests/conftest.py` 开启的外部网络绝对阻断环境下，0 外部请求，执行速度毫秒级；
- 测试用例无需 Mock 任何外部组件，全部通过构造特定输入入参验证物理输出。

### 6.2 关键边界测试用例规划 (Test Suite Matrix)

```
tests/unit/core/algorithms/test_grading.py
├── TestObjectiveGrading (客观题规范化与离线判分)
│   ├── test_single_choice_normalization_and_match (大小写/空格/无效字母)
│   ├── test_multiple_choice_sort_and_exact_match (乱序/重复/标点逗号分号/漏选多选)
│   ├── test_true_false_multilingual_mapping (True/False/对/错/1/0/V/X/√/×/非法字符)
│   └── test_fill_in_blank_normalization (全角转半角/多空格/数字中文归一/多候选答案)
├── TestSubjectiveThresholdBoundaries (主观题双阈值边界值测试)
│   ├── test_exact_upper_threshold_082_offline_correct (恰等于 0.82 离线判对)
│   ├── test_exact_lower_threshold_045_offline_wrong (恰等于 0.45 离线判错)
│   ├── test_transition_open_interval_boundaries (0.45001 与 0.81999 转 AI)
│   └── test_score_half_rounding (0.5 粒度四舍五入核算)
├── TestNegationInversionPair (成对否定词反转专项用例)
│   ├── test_paired_positive_vs_negative_polarity (成对输入仅差一个“不”字，得分方向严格相反或转 AI)
│   └── test_clause_scope_negation_isolation (跨分句否定词不传播用例)
├── TestArbitrateLLMTransitionDecisionTable (4 类转 AI 决策表全组合覆盖)
│   ├── test_condition_1_uncertain_range
│   ├── test_condition_2_negation_inversion
│   ├── test_condition_3_multiple_equivalents_and_empty_rubric
│   └── test_condition_4_zero_coverage_high_similarity
└── TestExtremeInputsAndSafety (极限输入与鲁棒性防御)
    ├── test_empty_or_whitespace_answer_unanswered (未作答判定)
    ├── test_answer_exceeding_2000_chars_truncated (超长作答截断)
    ├── test_zero_vector_and_dimension_mismatch (向量异常容错)
    └── test_invalid_max_score_and_config_raises (非法参数报错防御)
```

### 6.3 成对否定词反转专项用例设计 (Pairwise Negation Inversion)
为满足 `AGENTS.md` 中“成对测试否定词反转专项用例（仅否定词不同时得分方向严格相反），条件组合覆盖”的硬性红线要求：
- **正向用例 A**:
  - 参考答案: `"关系型数据库支持事务的 ACID 特性"`
  - 用户作答 A: `"关系型数据库完全支持事务的 ACID 特性"`
  - 预期: `point_coverage = 1.0`，无否定词，`match_score >= 0.82`，离线判对得满分。
- **反向配对用例 B**:
  - 参考答案: `"关系型数据库支持事务的 ACID 特性"`
  - 用户作答 B: `"关系型数据库不支持事务的 ACID 特性"`
  - 差异: 仅多出一个关键否定词 `"不"`，修饰核心谓词 `"支持"`；
  - 预期: 分句内触发否定词抑制，要点判定为未命中，且标记否定词反转风险；触发转 AI 条件 2（`requires_llm = True`, `transition_reason = NEGATION_INVERSION`）或得分归零，**绝不允许判定为离线正确或给予满分**。

### 6.4 白盒度量与覆盖率门禁
- **代码覆盖率要求**:
  - `backend/app/core/algorithms/grading.py`: **行覆盖率 100%，分支覆盖率 $\ge 95\%$**；
- **McCabe 复杂度要求**:
  - `match_and_grade_answer`: $V(G) \le 8$；
  - `grade_objective_question`: $V(G) \le 8$；
  - `arbitrate_llm_transition`: $V(G) \le 7$；
  - `evaluate_subjective_rubric`: $V(G) \le 7$；
  - 全模块函数均严格满足 $V(G) \le 10$。

---

## 7. 替代方案与权衡考量 (Alternatives Considered & Trade-offs)

### 7.1 全量 LLM 判题 vs 离线规则+双阈值分流
- **替代方案**: 将所有客观题与主观题无条件投递至大语言模型网关统一判题。
- **权衡与否决原因**:
  - 成本与延迟灾难：选择题、判断题本可在 1 毫秒内通过规则精准判定，全量调用 LLM 将导致单次交卷耗时激增 5~15 秒，消耗高昂 Token 费用；
  - 幻觉不可控：LLM 在客观题严格比对中偶现幻觉（如把选项 B 当作 A）；
  - 架构决策：采用离线规则承担客观题，双阈值（$\ge 0.82$ 与 $\le 0.45$）过滤大部分主观题两极化作答，仅将不确定区间与反转疑点交由 LLM 处理，可减少 $70\%$ 以上的主观题 LLM 调用量。

### 7.2 全文纯向量余弦 vs 要点覆盖率 (0.6) + 向量相似度 (0.4) 复合匹配
- **替代方案**: 仅依赖作答与参考答案的 Embedding 向量余弦相似度。
- **权衡与否决原因**:
  - 向量模型对“否定修饰词”（如“不”、“无”、“未”）极不敏感，仅多一个“不”字的句子在稠密向量空间中的余弦相似度通常仍高达 0.88 以上，极易造成严重误判；
  - 架构决策：遵循《概要设计说明书》第 6.5 节，引入要点关键词覆盖率（权重 0.6）与分句否定词抑制，配合向量余弦相似度（权重 0.4），彻底解决向量模型的语义极性盲区。

---

## 8. 动态风险核验与回滚预案 (Risk & Rollback Verification)

### 8.1 7 大风险维度动态扫描清单

| 维度 | 影响分析与扫描结论 |
| :--- | :--- |
| **1. Files** | 纯增量文件：新增 `backend/app/core/algorithms/grading.py` 与 `backend/tests/unit/core/algorithms/test_grading.py`。不修改任何已有代码文件。 |
| **2. API** | 无对外 API 契约变更。本模块为纯函数计算核，上层 API 将在 ZL-129 与 ZL-130 中消费。 |
| **3. Schema** | 无数据库模型或表结构改动。数据完全内存化流动。 |
| **4. Auth** | 纯函数计算核不触碰用户身份、凭证及鉴权逻辑，不产生水平越权风险。 |
| **5. Deps** | 零新增三方依赖。完全使用 Python 3.12+ 原生标准库，`pip-audit --strict` 扫描 0 风险。 |
| **6. Rollback** | 极低回滚成本。由于纯粹为新增独立算法文件，发生任何问题直接删除新增文件即可完全回滚，无残留状态。 |
| **7. Blast Radius** | 爆炸半径严格收敛于 `backend/app/core/algorithms/grading.py`，不影响既有资料解析、知识点抽取及已上线的数据模型。 |

### 8.2 确认 Change Tier 评级准确性
- 本任务涉及单一算法模块的新增与测试覆盖，无跨域耦合，无数据持久化迁移，确认评级为 **Tier 2 (Single-Module Feature)** 合理且准确。

### 8.3 回滚与故障应急策略
- 若后续集成或门禁出现异常阻断，使用 Git 直接丢弃该特性分支未合并提交：
  `git checkout develop && git branch -D feature/ZL-111-grading-algorithm`；
- 因无数据库变更和对外发布变更，回滚操作无需任何数据迁移降级或停机窗口。

---

## 9. 阶段准出签批 (Gate 2 Sign-off)

- [x] 架构流向与纯函数契约已冻结（输入、输出与 DTO 严格不可变）
- [x] 替代方案已完成推演与权衡（复合加权与分句否定词抑制）
- [x] 4 类转 AI 决策表与条件组合覆盖矩阵已完整定义
- [x] 7 维风险已核验且具备明确零成本回滚预案
- **审查结论**: Pending (待人类技术负责人确认签批)
- **签批人 / 日期**: [待人类签批] / 2026-09-23
