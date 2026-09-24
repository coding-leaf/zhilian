"""掌握度时间衰减与聚合算法纯函数计算核。

本模块严格遵循纯函数计算核铁律（无外部 I/O、无网络、无数据库依赖、零系统时钟调用），
基于艾宾浩斯遗忘定律（半衰期 30 天指数衰减模型）与判题来源置信度加权，
提供单知识点衰减加权聚合、四档掌握度等级映射与多知识点批量汇总流水线。
"""

import enum
import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

# ==============================================================================
# 核心数学与物理常量 (依据《软件需求规格说明书》与 AGENTS.md 规范)
# ==============================================================================

DEFAULT_HALF_LIFE_DAYS: float = 30.0
"""默认记忆衰减半衰期天数 (T_1/2 = 30 天)。依据艾宾浩斯遗忘模型基线。"""

DEFAULT_DECAY_LAMBDA: float = math.log(2.0) / DEFAULT_HALF_LIFE_DAYS
"""衰减常数 lambda = ln(2) / 30.0 ≈ 0.023104906。依据放射性衰变/记忆半衰期微积分方程。"""

SECONDS_PER_DAY: float = 86400.0
"""每日秒数换算常数 (24 * 3600 = 86400)。依据国际单位制时间标准。"""

DEFAULT_WEAK_UPPER_THRESHOLD: float = 0.40
"""薄弱档次上限临界值：[0.0, 0.40) 为 WEAK。依据需求规格说明书与 AGENTS.md。"""

DEFAULT_DEVELOPING_UPPER_THRESHOLD: float = 0.70
"""进阶档次上限临界值：[0.40, 0.70) 为 DEVELOPING，>= 0.70 为 MASTERED。依据需求规格说明书。"""

THRESHOLD_DEVELOPING: float = 0.40
"""进阶中档次判定临界值别名 (0.40 严格归属于 DEVELOPING)。"""

THRESHOLD_MASTERED: float = 0.70
"""掌握档次判定临界值别名 (0.70 严格归属于 MASTERED)。"""

DEFAULT_OFFLINE_RULE_WEIGHT: float = 1.0
"""客观题与离线精确规则匹配判题基础置信权重 (1.0)。依据 AGENTS.md 核心计算核第 5 条。"""

DEFAULT_AI_GRADING_WEIGHT: float = 0.8
"""大语言模型主观题判题基础置信权重 (0.8)。依据 AGENTS.md 核心计算核第 5 条。"""

DEFAULT_SELF_ASSESSMENT_WEIGHT: float = 0.5
"""用户主观自评与申诉复核基础置信权重 (0.5)。依据 AGENTS.md 核心计算核第 5 条。"""

MILLISECOND_TIMESTAMP_THRESHOLD: float = 1e11
"""毫秒时间戳阈值判定界限 (大于 1e11 判定为 13 位毫秒级时间戳)。依据 Unix 时间戳特征。"""


@enum.unique
class MasteryLevel(enum.StrEnum):
    """知识点掌握度四档等级定义。

    严格对齐《软件需求规格说明书》与 AGENTS.md 规范。
    """

    UNLEARNED = "UNLEARNED"  # 未学（无任何作答记录）
    WEAK = "WEAK"  # 薄弱 ([0.0, 0.40))
    DEVELOPING = "DEVELOPING"  # 进阶中 ([0.40, 0.70))
    MASTERED = "MASTERED"  # 掌握 ([0.70, 1.00])


@enum.unique
class GradingSourceType(enum.StrEnum):
    """判分来源类型枚举。

    不同来源具备不同的置信度权重基准。
    """

    OFFLINE_RULE = "OFFLINE_RULE"  # 离线精确规则 / 客观题判分 (权重 1.0)
    LLM_GRADING = "LLM_GRADING"  # AI 大模型主观题判题 (权重 0.8)
    AI_GRADING = "AI_GRADING"  # 别名兼容：AI 判题 (权重 0.8)
    SELF_ASSESSMENT = "SELF_ASSESSMENT"  # 用户主观自评 (权重 0.5)
    APPEAL_REGRADE = "APPEAL_REGRADE"  # 申诉后复核重判 (权重 0.5)
    USER_APPEAL = "USER_APPEAL"  # 别名兼容：用户申诉 (权重 0.5)
    UNKNOWN = "UNKNOWN"  # 未知来源兜底 (权重 0.5)


@dataclass(frozen=True)
class AttemptRecord:
    """单次作答与判分记录不可变实体。

    Attributes:
        record_id: 作答记录唯一标识符。
        knowledge_id: 所属知识点标识符。
        score: 单题得分比例，归一化范围 [0.0, 1.0]。
        source: 判分来源类型（GradingSourceType 或其字符串）。
        answered_at_timestamp: 作答提交时的秒级或毫秒级 Unix 时间戳。
    """

    record_id: str
    knowledge_id: str
    score: float
    source: GradingSourceType | str
    answered_at_timestamp: float


MasteryAttemptInput = AttemptRecord
"""单次作答与判分记录实体别名，对齐契约规范。"""


@dataclass(frozen=True)
class MasteryAlgorithmConfig:
    """掌握度衰减算法配置不可变参数。

    Attributes:
        half_life_days: 记忆半衰期天数，默认 30.0 天。
        source_weights: 来源置信度自定义字典映射。
        weak_upper_threshold: 薄弱上限临界值，默认 0.40。
        developing_upper_threshold: 进阶上限临界值，默认 0.70。
    """

    half_life_days: float = DEFAULT_HALF_LIFE_DAYS
    source_weights: dict[str, float] | None = None
    weak_upper_threshold: float = DEFAULT_WEAK_UPPER_THRESHOLD
    developing_upper_threshold: float = DEFAULT_DEVELOPING_UPPER_THRESHOLD

    def __post_init__(self) -> None:
        """配置参数边界安全断言。

        Raises:
            ValueError: 当 half_life_days <= 0 或阈值不满足 0.0 <= weak < developing <= 1.0 时抛出。
        """
        if self.half_life_days <= 0.0:
            raise ValueError("half_life_days must be positive")
        if not (0.0 <= self.weak_upper_threshold < self.developing_upper_threshold <= 1.0):
            raise ValueError(
                "Must satisfy: 0.0 <= weak_upper_threshold < developing_upper_threshold <= 1.0"
            )


@dataclass(frozen=True)
class MasteryAggregationItem:
    """单个知识点的掌握度聚合结果。

    Attributes:
        knowledge_id: 知识点唯一标识符。
        mastery_score: 衰减加权后的掌握度综合得分，截断在 [0.0, 1.0]，保留 4 位小数。
        mastery_level: 映射的四档掌握度等级。
        effective_attempts_count: 参与聚合计算的有效作答总条数。
        raw_average_score: 未经过时间衰减加权的算术平均分（用于基线对照）。
        decayed_weight_sum: 衰减后的权重累计总和。
        last_practiced_timestamp: 该知识点最近一次作答的秒级时间戳（无记录为 None）。
    """

    knowledge_id: str
    mastery_score: float
    mastery_level: MasteryLevel
    effective_attempts_count: int
    raw_average_score: float
    decayed_weight_sum: float
    last_practiced_timestamp: float | None


@dataclass(frozen=True)
class MasteryScoreResult:
    """多知识点批量聚合汇总产物。

    Attributes:
        items: 知识点 ID 到聚合结果项的只读映射。
        overall_mastery_score: 全局宏观掌握度总分（各知识点掌握度得分的算术平均值）。
        evaluated_at_timestamp: 本次评估计算所采用的基准秒级时间戳。
        total_records_processed: 参与处理的总作答记录条数。
    """

    items: dict[str, MasteryAggregationItem]
    overall_mastery_score: float
    evaluated_at_timestamp: float
    total_records_processed: int = 0

    def __init__(
        self,
        items: dict[str, MasteryAggregationItem] | None = None,
        overall_mastery_score: float | None = None,
        evaluated_at_timestamp: float = 0.0,
        total_records_processed: int = 0,
        *,
        knowledge_mastery_map: dict[str, MasteryAggregationItem] | None = None,
        overall_score: float | None = None,
    ) -> None:
        """初始化批量聚合汇总结果，兼容多风格命名属性。

        Args:
            items: 知识点映射字典。
            overall_mastery_score: 全局宏观掌握度得分。
            evaluated_at_timestamp: 评估基准时间戳。
            total_records_processed: 处理的记录总数。
            knowledge_mastery_map: 命名别名（与 items 等价）。
            overall_score: 命名别名（与 overall_mastery_score 等价）。
        """
        resolved_items = items if items is not None else (knowledge_mastery_map or {})
        resolved_score = (
            overall_mastery_score
            if overall_mastery_score is not None
            else (overall_score if overall_score is not None else 0.0)
        )
        object.__setattr__(self, "items", resolved_items)
        object.__setattr__(self, "overall_mastery_score", resolved_score)
        object.__setattr__(self, "evaluated_at_timestamp", evaluated_at_timestamp)
        object.__setattr__(self, "total_records_processed", total_records_processed)

    @property
    def knowledge_mastery_map(self) -> dict[str, MasteryAggregationItem]:
        """兼容别名属性：获取知识点映射字典。"""
        return self.items

    @property
    def overall_score(self) -> float:
        """兼容别名属性：获取全局掌握度总分。"""
        return self.overall_mastery_score


def normalize_timestamp(timestamp: float) -> float:
    """归一化时间戳为秒级浮点数。

    若输入为 13 位毫秒时间戳（数值大于 1e11），则自动除以 1000.0 转换为秒级。

    Args:
        timestamp: 待转换的时间戳（秒或毫秒）。

    Returns:
        float: 转换后的秒级时间戳。
    """
    if timestamp > MILLISECOND_TIMESTAMP_THRESHOLD:
        return timestamp / 1000.0
    return float(timestamp)


def calculate_time_decay_factor(
    answered_at: float = 0.0,
    evaluated_at: float = 0.0,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    *,
    answered_at_timestamp: float | None = None,
    evaluated_at_timestamp: float | None = None,
) -> float:
    """计算基于半衰期的艾宾浩斯时间衰减因子。

    依据记忆半衰期动力学公式：decay_factor = 2 ** (-delta_days / half_life_days)
    当 delta_days 为 0 天时，衰减因子为 1.0；
    当 delta_days 为 30 天且半衰期为 30 天时，衰减因子恰好为 0.5；
    若作答时间晚于评估时间（未来时间戳），防御性钳制时间差为 0.0 天，返回 1.0；
    若 half_life_days <= 0.0，防御性回退至默认半衰期 30.0 天。

    Args:
        answered_at: 作答发生时的 Unix 时间戳（支持秒或毫秒）。
        evaluated_at: 掌握度评估基准 Unix 时间戳（支持秒或毫秒）。
        half_life_days: 记忆衰减半衰期天数，默认 30.0 天。
        answered_at_timestamp: 关键字别名，优先级高于 answered_at。
        evaluated_at_timestamp: 关键字别名，优先级高于 evaluated_at。

    Returns:
        float: 衰减因子，范围区间为 (0.0, 1.0]。
    """
    effective_answered = answered_at_timestamp if answered_at_timestamp is not None else answered_at
    effective_evaluated = (
        evaluated_at_timestamp if evaluated_at_timestamp is not None else evaluated_at
    )

    answered_seconds = normalize_timestamp(effective_answered)
    evaluated_seconds = normalize_timestamp(effective_evaluated)

    effective_half_life = half_life_days if half_life_days > 0.0 else DEFAULT_HALF_LIFE_DAYS

    delta_days = max(0.0, (evaluated_seconds - answered_seconds) / SECONDS_PER_DAY)
    decay_factor = math.pow(2.0, -delta_days / effective_half_life)
    return float(decay_factor)


def resolve_source_weight(
    source: GradingSourceType | str,
    custom_weights: dict[str, float] | None = None,
) -> float:
    """解析判分来源的基础置信权重。

    规则匹配：
    - OFFLINE_RULE: 1.0
    - LLM_GRADING / AI_GRADING: 0.8
    - SELF_ASSESSMENT / APPEAL_REGRADE / USER_APPEAL: 0.5
    - 其他未知渠道: 0.5

    若提供 custom_weights 字典且包含该渠道，则优先采用自定义权重。

    Args:
        source: 判分来源类型枚举或字符串。
        custom_weights: 可选的自定义权重映射字典。

    Returns:
        float: 基础置信度权重值。
    """
    source_name = source.value if isinstance(source, GradingSourceType) else str(source)
    normalized_source = source_name.strip().upper()

    if custom_weights:
        if source_name in custom_weights:
            return float(custom_weights[source_name])
        if normalized_source in custom_weights:
            return float(custom_weights[normalized_source])

    if normalized_source == GradingSourceType.OFFLINE_RULE.value:
        return DEFAULT_OFFLINE_RULE_WEIGHT
    if normalized_source in (
        GradingSourceType.LLM_GRADING.value,
        GradingSourceType.AI_GRADING.value,
    ):
        return DEFAULT_AI_GRADING_WEIGHT
    if normalized_source in (
        GradingSourceType.SELF_ASSESSMENT.value,
        GradingSourceType.APPEAL_REGRADE.value,
        GradingSourceType.USER_APPEAL.value,
    ):
        return DEFAULT_SELF_ASSESSMENT_WEIGHT
    return DEFAULT_SELF_ASSESSMENT_WEIGHT


def determine_mastery_level(
    score: float = 0.0,
    has_records: bool = True,
    weak_threshold: float = DEFAULT_WEAK_UPPER_THRESHOLD,
    developing_threshold: float = DEFAULT_DEVELOPING_UPPER_THRESHOLD,
    *,
    mastery_score: float | None = None,
) -> MasteryLevel:
    """根据掌握度得分与作答状态确定四档掌握度等级。

    规则：
    - has_records 为 False: UNLEARNED
    - score < weak_threshold (0.40): WEAK
    - score < developing_threshold (0.70): DEVELOPING (0.40 严格属于 DEVELOPING)
    - score >= developing_threshold: MASTERED (0.70 严格属于 MASTERED)

    Args:
        score: 掌握度综合得分 [0.0, 1.0]。
        has_records: 是否存在有效作答记录。
        weak_threshold: 薄弱档次上限阈值，默认 0.40。
        developing_threshold: 进阶档次上限阈值，默认 0.70。
        mastery_score: 关键字别名，优先级高于 score。

    Returns:
        MasteryLevel: 判定的掌握度等级枚举值。
    """
    if not has_records:
        return MasteryLevel.UNLEARNED

    effective_score = mastery_score if mastery_score is not None else score
    if effective_score < weak_threshold:
        return MasteryLevel.WEAK
    if effective_score < developing_threshold:
        return MasteryLevel.DEVELOPING
    return MasteryLevel.MASTERED


def aggregate_single_knowledge(
    knowledge_id: str,
    records: Sequence[AttemptRecord],
    evaluated_at_timestamp: float,
    config: MasteryAlgorithmConfig | None = None,
) -> MasteryAggregationItem:
    """聚合单个知识点的作答历史并计算衰减掌握度。

    Args:
        knowledge_id: 知识点全局唯一标识符。
        records: 该知识点的作答记录序列。
        evaluated_at_timestamp: 评估基准 Unix 秒级或毫秒级时间戳。
        config: 算法配置参数，若为空则采用默认参数。

    Returns:
        MasteryAggregationItem: 单知识点掌握度聚合项。
    """
    if not records:
        return MasteryAggregationItem(
            knowledge_id=knowledge_id,
            mastery_score=0.0,
            mastery_level=MasteryLevel.UNLEARNED,
            effective_attempts_count=0,
            raw_average_score=0.0,
            decayed_weight_sum=0.0,
            last_practiced_timestamp=None,
        )

    half_life_days = config.half_life_days if config else DEFAULT_HALF_LIFE_DAYS
    custom_weights = config.source_weights if config else None
    weak_threshold = config.weak_upper_threshold if config else DEFAULT_WEAK_UPPER_THRESHOLD
    developing_threshold = (
        config.developing_upper_threshold if config else DEFAULT_DEVELOPING_UPPER_THRESHOLD
    )

    norm_evaluated_at = normalize_timestamp(evaluated_at_timestamp)

    weighted_score_sum = 0.0
    decayed_weight_sum = 0.0
    raw_score_sum = 0.0
    latest_practiced_timestamp: float | None = None

    for record in records:
        clamped_score = max(0.0, min(1.0, float(record.score)))
        record_seconds = normalize_timestamp(record.answered_at_timestamp)

        if latest_practiced_timestamp is None or record_seconds > latest_practiced_timestamp:
            latest_practiced_timestamp = record_seconds

        decay_factor = calculate_time_decay_factor(
            answered_at=record_seconds,
            evaluated_at=norm_evaluated_at,
            half_life_days=half_life_days,
        )
        source_weight = resolve_source_weight(record.source, custom_weights=custom_weights)
        effective_weight = source_weight * decay_factor

        weighted_score_sum += clamped_score * effective_weight
        decayed_weight_sum += effective_weight
        raw_score_sum += clamped_score

    if decayed_weight_sum <= 0.0:
        final_score = 0.0
        level = MasteryLevel.UNLEARNED
    else:
        raw_mastery = weighted_score_sum / decayed_weight_sum
        clamped_mastery = max(0.0, min(1.0, raw_mastery))
        final_score = round(clamped_mastery, 4)
        level = determine_mastery_level(
            final_score,
            has_records=True,
            weak_threshold=weak_threshold,
            developing_threshold=developing_threshold,
        )

    raw_average_score = round(raw_score_sum / len(records), 4)

    return MasteryAggregationItem(
        knowledge_id=knowledge_id,
        mastery_score=final_score,
        mastery_level=level,
        effective_attempts_count=len(records),
        raw_average_score=raw_average_score,
        decayed_weight_sum=round(decayed_weight_sum, 6),
        last_practiced_timestamp=latest_practiced_timestamp,
    )


# 单知识点聚合函数别名兼容
aggregate_single_knowledge_mastery = aggregate_single_knowledge


def aggregate_mastery_scores(
    records: Sequence[AttemptRecord],
    evaluated_at_timestamp: float,
    knowledge_ids: Sequence[str] | None = None,
    config: MasteryAlgorithmConfig | None = None,
) -> MasteryScoreResult:
    """顶层入口：批量聚合所有知识点的历史作答记录。

    流水线逻辑：
    1. 归一化评估基准时间戳；
    2. 若指定 knowledge_ids 白名单，仅保留白名单内的作答记录，
       并为未作答的白名单知识点补全 UNLEARNED 项；
    3. 按 knowledge_id 分组聚合计算；
    4. 计算宏观全局掌握度总分（各知识点掌握度得分算术均值）；
    5. 装配并返回不可变 MasteryScoreResult。

    Args:
        records: 包含多知识点的全量作答记录序列。
        evaluated_at_timestamp: 评估基准 Unix 秒级或毫秒级时间戳。
        knowledge_ids: 可选的知识点白名单序列。
        config: 算法全局配置项。

    Returns:
        MasteryScoreResult: 批量聚合产物，含各知识点详情及全局总分。
    """
    norm_evaluated_at = normalize_timestamp(evaluated_at_timestamp)
    total_records_processed = len(records)

    if not records and knowledge_ids is None:
        return MasteryScoreResult(
            items={},
            overall_mastery_score=0.0,
            evaluated_at_timestamp=norm_evaluated_at,
            total_records_processed=0,
        )

    allowed_id_set = set(knowledge_ids) if knowledge_ids is not None else None
    grouped_records: dict[str, list[AttemptRecord]] = defaultdict(list)

    for record in records:
        if allowed_id_set is None or record.knowledge_id in allowed_id_set:
            grouped_records[record.knowledge_id].append(record)

    target_knowledge_ids: Sequence[str]
    if knowledge_ids is not None:
        target_knowledge_ids = knowledge_ids
    else:
        target_knowledge_ids = sorted(grouped_records.keys())

    items: dict[str, MasteryAggregationItem] = {}
    for knowledge_id in target_knowledge_ids:
        item_records = grouped_records.get(knowledge_id, [])
        item = aggregate_single_knowledge(
            knowledge_id=knowledge_id,
            records=item_records,
            evaluated_at_timestamp=norm_evaluated_at,
            config=config,
        )
        items[knowledge_id] = item

    if items:
        overall_score = round(
            sum(item.mastery_score for item in items.values()) / len(items),
            4,
        )
    else:
        overall_score = 0.0

    return MasteryScoreResult(
        items=items,
        overall_mastery_score=overall_score,
        evaluated_at_timestamp=norm_evaluated_at,
        total_records_processed=total_records_processed,
    )
