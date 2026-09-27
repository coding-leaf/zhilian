"""诊断规则合成算法纯函数计算核。

本模块严格遵循纯函数计算核铁律（无外部 I/O、无网络、无数据库依赖、零系统时钟调用），
针对自适应练习后的学生学情表现与错题证据，提供退步判定、薄弱筛选、
四类认知成因归因与可执行复习建议生成的客观确定性流水线。
"""

import enum
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

__all__ = [
    "BLIND_SPOT_SCORE_THRESHOLD",
    "DEVELOPING_SCORE_THRESHOLD",
    "REGRESSION_DELTA_THRESHOLD",
    "TIME_DECAY_DAYS_THRESHOLD",
    "WEAK_SCORE_THRESHOLD",
    "CauseType",
    "DiagnosisReportResult",
    "KnowledgeEvaluationInput",
    "MistakeEvidence",
    "WeakKnowledgeItem",
    "check_knowledge_regression",
    "check_regression",
    "diagnose_cause_and_advice",
    "evaluate_cause_type",
    "generate_summary_evaluation",
    "is_weak_knowledge",
    "synthesize_diagnosis_report",
]

# ==============================================================================
# 核心阈值常量 (依据《软件需求规格说明书》FR-50/51/53 与教育测量学模型)
# ==============================================================================

REGRESSION_DELTA_THRESHOLD: float = 0.05
"""退步判定临界降幅阈值 (0.05)。依据需求规格说明书 FR-51 与 ROADMAP.md 规范。

历史基线掌握度与当前掌握度的差值 delta >= 0.05 时，严格判定知识点发生显著退步。
"""

WEAK_SCORE_THRESHOLD: float = 0.40
"""严重薄弱档次绝对上限阈值 (0.40)。依据需求规格说明书 FR-50 与掌握度四档分级模型。

当前掌握度得分 < 0.40 的知识点无条件进入薄弱知识点清单。
"""

DEVELOPING_SCORE_THRESHOLD: float = 0.70
"""进阶档次上限门槛阈值 (0.70)。依据需求规格说明书 FR-50。

掌握度处于 [0.40, 0.70) 且在本次练习中产生错题证据的知识点进入薄弱清单；
得分 >= 0.70 即达掌握标杆，正常不进入薄弱清单。
"""

BLIND_SPOT_SCORE_THRESHOLD: float = 0.30
"""概念盲区判定上限阈值 (0.30)。依据需求规格说明书 FR-53 认知归因规范。

当前得分 < 0.30 且存在错题或主客观题均答错，判定对基础概念存在认知盲区。
"""

TIME_DECAY_DAYS_THRESHOLD: float = 30.0
"""遗忘衰减时间门槛天数 (30.0 天)。依据需求规格说明书 FR-53 与艾宾浩斯遗忘曲线半衰期。

距上次练习超过 30 天未复习导致掌握度衰减，归因为长期未练遗忘衰减。
"""


@enum.unique
class CauseType(enum.StrEnum):
    """诊断规则归因成因类型枚举。"""

    CONCEPT_BLIND_SPOT = "CONCEPT_BLIND_SPOT"  # 概念盲区
    CARELESS_MISTAKE = "CARELESS_MISTAKE"  # 细节/粗心失误
    CONCEPT_CONFUSION = "CONCEPT_CONFUSION"  # 概念易混淆（含否定词反转）
    TIME_DECAY_FORGOTTEN = "TIME_DECAY_FORGOTTEN"  # 长期未练遗忘衰减
    UNKNOWN = "UNKNOWN"  # 未知/待深入分析


@dataclass(frozen=True)
class MistakeEvidence:
    """错题证据不可变实体。

    Attributes:
        question_id: 题目全局唯一标识符。
        question_brief: 题干核心摘要（已脱敏，不含敏感全文）。
        user_answer: 用户作答摘要/选项。
        correct_answer: 正确答案摘要/选项。
        knowledge_id: 所属知识点标识符。
        is_negation_inversion: 是否属于否定词反转/反向限定词错误。
    """

    question_id: str
    question_brief: str
    user_answer: str
    correct_answer: str
    knowledge_id: str
    is_negation_inversion: bool = False


@dataclass(frozen=True)
class KnowledgeEvaluationInput:
    """单个知识点评估输入不可变实体。

    Attributes:
        knowledge_id: 知识点全局唯一标识符。
        knowledge_title: 知识点名称。
        current_score: 当前计算掌握度得分 [0.0, 1.0]。
        previous_score: 历史掌握度基线得分 [0.0, 1.0]，若无历史记录为 None。
        days_since_last_practice: 距上一次练习的天数，若首次练习或未记录为 None。
        has_subjective_mistake: 本次练习是否存在主观题错题。
        has_objective_mistake: 本次练习是否存在客观题错题。
    """

    knowledge_id: str
    knowledge_title: str
    current_score: float
    previous_score: float | None = None
    days_since_last_practice: float | None = None
    has_subjective_mistake: bool = False
    has_objective_mistake: bool = False


@dataclass(frozen=True)
class WeakKnowledgeItem:
    """薄弱或退步知识点诊断明细实体。

    Attributes:
        knowledge_id: 知识点标识符。
        knowledge_title: 知识点名称。
        current_score: 当前掌握度得分。
        previous_score: 历史基线得分，无历史记录为 None。
        score_delta: 分数变化值 (current_score - previous_score)，降幅为负。
        is_regressed: 是否判定为显著退步 (score_delta <= -0.05)。
        cause_type: 归因成因类型枚举。
        cause_explanation: 成因详细解释文本。
        actionable_advice: 针对该薄弱点的可执行提升建议。
        associated_mistakes: 强绑定的错题证据列表（若无本次错题则为空列表）。
    """

    knowledge_id: str
    knowledge_title: str
    current_score: float
    previous_score: float | None
    score_delta: float
    is_regressed: bool
    cause_type: CauseType
    cause_explanation: str
    actionable_advice: str
    associated_mistakes: list[MistakeEvidence] = field(default_factory=list)


@dataclass(frozen=True)
class DiagnosisReportResult:
    """诊断报告规则合成全局结果不可变实体。

    Attributes:
        report_id: 诊断报告唯一标识符。
        overall_score: 全局综合平均掌握度得分 [0.0, 1.0]。
        weak_points: 薄弱知识点清单（按得分升序、变化量升序即降幅最大在前排列）。
        regressed_points: 显著退步知识点预警清单（按变化量升序即降幅最大在前排列）。
        mastered_points_count: 达到掌握标准 (score >= 0.70) 的知识点总数。
        total_points_evaluated: 评估的知识点总数。
        summary_evaluation: 全局客观评价总结。
        suggested_review_actions: 基于成因归集去重的有序复习行动清单。
    """

    report_id: str
    overall_score: float
    weak_points: list[WeakKnowledgeItem]
    regressed_points: list[WeakKnowledgeItem]
    mastered_points_count: int
    total_points_evaluated: int
    summary_evaluation: str
    suggested_review_actions: list[str]


def check_regression(
    current_score: float,
    previous_score: float | None,
    threshold: float = REGRESSION_DELTA_THRESHOLD,
) -> tuple[bool, float]:
    """判定知识点掌握度是否发生显著退步。

    Args:
        current_score: 当前掌握度得分。
        previous_score: 历史掌握度基线得分，若为首次评估或无历史记录为 None。
        threshold: 触发退步判定的最小降幅阈值，默认 0.05。

    Returns:
        tuple[bool, float]: (是否显著退步, 分数变化值保留4位小数)。
            score_delta = current_score - previous_score，负数为掌握度下降（退步）。
            若 previous_score 为 None，变化量为 0.0 且判定为 False。
    """
    if previous_score is None:
        return False, 0.0
    score_delta = round(current_score - previous_score, 4)
    return score_delta <= -threshold, score_delta


def check_knowledge_regression(
    current_score: float,
    previous_score: float | None,
    threshold: float = REGRESSION_DELTA_THRESHOLD,
) -> tuple[bool, float]:
    """判定知识点掌握度是否发生显著退步（check_regression 强类型别名）。

    Args:
        current_score: 当前掌握度得分。
        previous_score: 历史掌握度基线得分。
        threshold: 触发退步判定的最小降幅阈值，默认 0.05。

    Returns:
        tuple[bool, float]: (是否显著退步, 分数变化值)，负数为退步。
    """
    return check_regression(current_score, previous_score, threshold=threshold)


def is_weak_knowledge(
    current_score: float,
    mistake_count: int,
    weak_threshold: float = WEAK_SCORE_THRESHOLD,
    developing_threshold: float = DEVELOPING_SCORE_THRESHOLD,
) -> bool:
    """判定知识点是否应纳入薄弱知识点清单。

    Args:
        current_score: 当前掌握度得分。
        mistake_count: 本次练习中该知识点关联的错题数量。
        weak_threshold: 严重薄弱上限阈值，默认 0.40。
        developing_threshold: 进阶档次上限门槛，默认 0.70。

    Returns:
        bool: 若属于薄弱知识点返回 True，否则返回 False。
    """
    if current_score < weak_threshold:
        return True
    return current_score < developing_threshold and mistake_count > 0


def _is_concept_confusion(mistakes: Sequence[MistakeEvidence]) -> bool:
    """判定是否满足概念易混淆成因（Rank 1）。"""
    return any(m.is_negation_inversion for m in mistakes)


def _is_concept_blind_spot(
    input_item: KnowledgeEvaluationInput,
    mistakes: Sequence[MistakeEvidence],
) -> bool:
    """判定是否满足概念盲区成因（Rank 2）。"""
    has_both = input_item.has_subjective_mistake and input_item.has_objective_mistake
    if has_both:
        return True
    return input_item.current_score < BLIND_SPOT_SCORE_THRESHOLD and len(mistakes) > 0


def _is_careless_mistake(
    input_item: KnowledgeEvaluationInput,
    mistakes: Sequence[MistakeEvidence],
) -> bool:
    """判定是否满足细节/粗心失误成因（Rank 3）。"""
    if input_item.previous_score is None:
        return False
    if input_item.previous_score < DEVELOPING_SCORE_THRESHOLD:
        return False
    if input_item.current_score < WEAK_SCORE_THRESHOLD:
        return False
    return (
        len(mistakes) > 0 or input_item.has_subjective_mistake or input_item.has_objective_mistake
    )


def _is_time_decay_forgotten(
    input_item: KnowledgeEvaluationInput,
    mistakes: Sequence[MistakeEvidence],
    score_delta: float,
) -> bool:
    """判定是否满足艾宾浩斯遗忘衰减成因（Rank 4）。"""
    if (
        input_item.days_since_last_practice is not None
        and input_item.days_since_last_practice >= TIME_DECAY_DAYS_THRESHOLD
    ):
        return True
    return score_delta <= -REGRESSION_DELTA_THRESHOLD and len(mistakes) == 0


def evaluate_cause_type(
    input_item: KnowledgeEvaluationInput,
    mistakes: Sequence[MistakeEvidence],
    score_delta: float,
) -> tuple[CauseType, str, str]:
    """根据作答表现与指标执行认知成因规则优先级匹配并生成建议。

    仲裁优先级规则：
    Rank 1: 概念混淆 (CONCEPT_CONFUSION) - 错题中包含否定词反转限定
    Rank 2: 概念盲区 (CONCEPT_BLIND_SPOT) - 分数 < 0.30 且有错题，或主客观题均答错
    Rank 3: 粗心失误 (CARELESS_MISTAKE) - 历史掌握良好 (>=0.70) 且当前未彻底崩盘 (>=0.40)
    Rank 4: 遗忘衰减 (TIME_DECAY_FORGOTTEN) - 超过 30 天未练或无错题退步
    Fallback: 未知成因 (UNKNOWN)

    Args:
        input_item: 知识点评估输入信息。
        mistakes: 该知识点关联的错题列表。
        score_delta: 掌握度变化值 (current_score - previous_score)，负数为降幅。

    Returns:
        tuple[CauseType, str, str]: (成因枚举, 归因解释文本, 可执行复习建议)。
    """
    if _is_concept_confusion(mistakes):
        return (
            CauseType.CONCEPT_CONFUSION,
            "检测到题干否定词或反向限定条件理解倒置，对对立/相似概念边界界定不清。",
            "建立正反概念对比卡片，审题时圈注“不属于”、“错误”、“唯独”等否定限定词。",
        )

    if _is_concept_blind_spot(input_item, mistakes):
        return (
            CauseType.CONCEPT_BLIND_SPOT,
            "当前掌握度极低且发生多处实质性错误，对基础概念与核心原理存在认知盲区。",
            "暂停该知识点题海训练，完整重读教材核心定义与例题推导，完成精讲学习后再练。",
        )

    if _is_careless_mistake(input_item, mistakes):
        return (
            CauseType.CARELESS_MISTAKE,
            "历史掌握扎实，当前失误主要系审题疏漏、计算笔误或细节遗漏所致。",
            "保持做题节奏，审题时标划核心约束条件，提交作答前预留 30 秒执行复查。",
        )

    if _is_time_decay_forgotten(input_item, mistakes, score_delta):
        explanation = (
            "【证据来源：历史掌握度低/时间衰减】本次练习暂无直接错题样本，依据历史累计掌握度判定。"
            if len(mistakes) == 0
            else "距上次练习已超过 30 天，受艾宾浩斯遗忘曲线影响，知识点掌握度自然衰退。"
        )
        return (
            CauseType.TIME_DECAY_FORGOTTEN,
            explanation,
            "遵循艾宾浩斯间隔记忆法，开启 3 组针对性变式巩固练习，快速激活长期记忆。",
        )

    fallback_explanation = (
        "【证据来源：历史掌握度低/时间衰减】本次练习暂无直接错题样本，依据历史累计掌握度判定。"
        if len(mistakes) == 0
        else "答题表现未呈现典型规则特征，需累积更多样本进一步诊断。"
    )
    return (
        CauseType.UNKNOWN,
        fallback_explanation,
        "保持常态化自适应练习，后续系统将根据作答样本持续深化归因。",
    )


def diagnose_cause_and_advice(
    input_item: KnowledgeEvaluationInput,
    mistakes: Sequence[MistakeEvidence],
    score_delta: float,
) -> tuple[CauseType, str, str]:
    """根据作答表现与指标执行认知成因规则优先级匹配并生成建议（evaluate_cause_type 强类型别名）。

    Args:
        input_item: 知识点评估输入信息。
        mistakes: 该知识点关联的错题列表。
        score_delta: 掌握度变化值 (current_score - previous_score)，负数为降幅。

    Returns:
        tuple[CauseType, str, str]: (成因枚举, 归因解释文本, 可执行复习建议)。
    """
    return evaluate_cause_type(input_item, mistakes, score_delta)


def generate_summary_evaluation(
    overall_score: float,
    total_count: int,
    weak_count: int,
    regressed_count: int,
) -> str:
    """生成学情诊断报告的全局客观评价总结文本。

    Args:
        overall_score: 全局综合平均掌握度得分 [0.0, 1.0]。
        total_count: 评估的知识点总数。
        weak_count: 薄弱知识点总数。
        regressed_count: 显著退步知识点总数。

    Returns:
        str: 客观结构化学情评价总结文本。
    """
    if total_count == 0:
        return "本次评估无有效知识点数据，暂未生成学情诊断。"

    if weak_count == 0 and regressed_count == 0:
        return (
            f"本次练习综合得分 {overall_score:.2f}。全部评估知识点均达到掌握标准，"
            "未发现薄弱或退步知识点，学情表现优异，请继续保持！"
        )

    return (
        f"本次练习综合得分 {overall_score:.2f}，共评估 {total_count} 个知识点，"
        f"发现 {weak_count} 个薄弱知识点，{regressed_count} 个显著退步知识点。"
        "建议优先攻克薄弱与退步项，加强变式巩固。"
    )


def _index_mistakes_by_knowledge(
    mistakes: Sequence[MistakeEvidence],
) -> dict[str, list[MistakeEvidence]]:
    """按知识点 ID 对错题证据建立索引映射，保障 O(1) 检索。

    Args:
        mistakes: 本次练习收集的错题证据列表。

    Returns:
        dict[str, list[MistakeEvidence]]: 知识点 ID 到对应错题证据列表的映射字典。
    """
    mistakes_by_knowledge: dict[str, list[MistakeEvidence]] = defaultdict(list)
    for mistake in mistakes:
        mistakes_by_knowledge[mistake.knowledge_id].append(mistake)
    return mistakes_by_knowledge


def _clamp_score(score: float | None) -> float | None:
    """将分数值安全钳制到 [0.0, 1.0] 区间。"""
    if score is None:
        return None
    return max(0.0, min(1.0, score))


def _build_weak_knowledge_item(
    item: KnowledgeEvaluationInput,
    current_score: float,
    previous_score: float | None,
    item_mistakes: Sequence[MistakeEvidence],
    score_delta: float,
    is_regressed: bool,
) -> WeakKnowledgeItem:
    """构建归因分析后的薄弱或退步知识点明细实体。

    Args:
        item: 原始知识点评估输入信息。
        current_score: 钳制在 [0.0, 1.0] 的当前得分。
        previous_score: 钳制在 [0.0, 1.0] 的历史基线得分，或 None。
        item_mistakes: 该知识点关联的错题列表。
        score_delta: 掌握度变化值 (current_score - previous_score)，负数为降幅。
        is_regressed: 是否判定为显著退步。

    Returns:
        WeakKnowledgeItem: 包含归因成因与提升建议的实体。
    """
    clamped_item = KnowledgeEvaluationInput(
        knowledge_id=item.knowledge_id,
        knowledge_title=item.knowledge_title,
        current_score=current_score,
        previous_score=previous_score,
        days_since_last_practice=item.days_since_last_practice,
        has_subjective_mistake=item.has_subjective_mistake,
        has_objective_mistake=item.has_objective_mistake,
    )
    cause_type, explanation, advice = evaluate_cause_type(clamped_item, item_mistakes, score_delta)
    return WeakKnowledgeItem(
        knowledge_id=item.knowledge_id,
        knowledge_title=item.knowledge_title,
        current_score=current_score,
        previous_score=previous_score,
        score_delta=score_delta,
        is_regressed=is_regressed,
        cause_type=cause_type,
        cause_explanation=explanation,
        actionable_advice=advice,
        associated_mistakes=list(item_mistakes),
    )


def _diagnose_knowledge_items(
    evaluated_knowledge_items: Sequence[KnowledgeEvaluationInput],
    mistakes_by_knowledge: dict[str, list[MistakeEvidence]],
) -> tuple[list[WeakKnowledgeItem], list[WeakKnowledgeItem], int, float]:
    """遍历知识点评估项执行掌握度钳制、退步判定、薄弱筛选与归因。

    Args:
        evaluated_knowledge_items: 被评估知识点的掌握度表现输入序列。
        mistakes_by_knowledge: 按知识点索引的错题字典。

    Returns:
        tuple[list[WeakKnowledgeItem], list[WeakKnowledgeItem], int, float]:
            (薄弱项列表, 退步预警项列表, 达标知识点总数, 钳制得分总和)。
    """
    weak_points: list[WeakKnowledgeItem] = []
    regressed_points: list[WeakKnowledgeItem] = []
    mastered_count = 0
    clamped_scores_sum = 0.0

    for item in evaluated_knowledge_items:
        current_score = max(0.0, min(1.0, item.current_score))
        previous_score = _clamp_score(item.previous_score)
        clamped_scores_sum += current_score

        item_mistakes = mistakes_by_knowledge.get(item.knowledge_id, [])
        is_regressed, score_delta = check_regression(current_score, previous_score)
        is_weak = is_weak_knowledge(current_score, len(item_mistakes))

        if current_score >= DEVELOPING_SCORE_THRESHOLD:
            mastered_count += 1

        if not (is_weak or is_regressed):
            continue

        weak_item = _build_weak_knowledge_item(
            item=item,
            current_score=current_score,
            previous_score=previous_score,
            item_mistakes=item_mistakes,
            score_delta=score_delta,
            is_regressed=is_regressed,
        )
        if is_weak:
            weak_points.append(weak_item)
        if is_regressed:
            regressed_points.append(weak_item)

    return weak_points, regressed_points, mastered_count, clamped_scores_sum


def _collect_review_actions(items: list[WeakKnowledgeItem]) -> list[str]:
    """汇总薄弱与退步知识点的可执行复习建议并去重保持序。

    Args:
        items: 薄弱与退步知识点明细列表。

    Returns:
        list[str]: 去重且保持优先序的针对性复习行动建议列表。
    """
    review_actions: list[str] = []
    seen_actions: set[str] = set()
    for diagnosed_item in items:
        advice = diagnosed_item.actionable_advice
        if advice not in seen_actions:
            seen_actions.add(advice)
            review_actions.append(advice)

    if not review_actions:
        return ["保持常态化复习节奏，定期进行自适应测验以巩固长期记忆。"]

    return review_actions


def synthesize_diagnosis_report(
    report_id: str,
    evaluated_knowledge_items: Sequence[KnowledgeEvaluationInput],
    mistakes: Sequence[MistakeEvidence] = (),
) -> DiagnosisReportResult:
    """综合合成学情诊断报告纯函数。

    对输入的知识点评估表现与错题证据执行退步判定、薄弱筛选、成因归因与建议生成。

    Args:
        report_id: 诊断报告唯一标识符。
        evaluated_knowledge_items: 被评估知识点的掌握度表现输入序列。
        mistakes: 本次练习收集到的错题证据列表（可选，默认为空）。

    Returns:
        DiagnosisReportResult: 不可变诊断报告聚合对象。

    Raises:
        ValueError: 当 report_id 为空或空白字符串时抛出。
    """
    if not report_id or not report_id.strip():
        raise ValueError("report_id cannot be empty or blank")

    if not evaluated_knowledge_items:
        return DiagnosisReportResult(
            report_id=report_id,
            overall_score=0.0,
            weak_points=[],
            regressed_points=[],
            mastered_points_count=0,
            total_points_evaluated=0,
            summary_evaluation="本次评估无有效知识点数据，暂未生成学情诊断。",
            suggested_review_actions=["暂无针对性建议，请完成练习后查看诊断报告。"],
        )

    mistakes_by_knowledge = _index_mistakes_by_knowledge(mistakes)
    weak_points, regressed_points, mastered_count, clamped_scores_sum = _diagnose_knowledge_items(
        evaluated_knowledge_items, mistakes_by_knowledge
    )

    weak_points.sort(key=lambda x: (x.current_score, x.score_delta))
    regressed_points.sort(key=lambda x: (x.score_delta, x.current_score))

    total_count = len(evaluated_knowledge_items)
    overall_score = round(clamped_scores_sum / total_count, 4)
    summary_evaluation = generate_summary_evaluation(
        overall_score, total_count, len(weak_points), len(regressed_points)
    )
    suggested_review_actions = _collect_review_actions(weak_points + regressed_points)

    return DiagnosisReportResult(
        report_id=report_id,
        overall_score=overall_score,
        weak_points=weak_points,
        regressed_points=regressed_points,
        mastered_points_count=mastered_count,
        total_points_evaluated=total_count,
        summary_evaluation=summary_evaluation,
        suggested_review_actions=suggested_review_actions,
    )
