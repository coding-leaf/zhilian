"""题目质检与待处理过滤纯函数算法核。

本模块严格遵循纯函数计算核铁律（无外部 I/O、无网络、无数据库依赖、无状态副作用），
提供基于来源片段实词重合度、语义向量及字符相似度去重、客观题答案冲突检测以及明显歧义甄别的
四类一票否决题目质检流水线。
"""

import enum
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

# ==============================================================================
# 题目质检门禁核心常量与决策基准
# 严格遵循《概要设计说明书》第 6.4 节与《软件需求规格说明书》FR-24、FR-25、FR-28
# ==============================================================================

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

# 预编译正则：中英文有效实词（长度 >= 2 的连续汉字或连续英文字母）
CONTENT_WORD_PATTERN: re.Pattern[str] = re.compile(r"[\u4e00-\u9fa5]{2,}|[a-zA-Z]{2,}")

# 预编译正则：布尔真值字符串集合
TRUE_BOOLEAN_VALUES: frozenset[str] = frozenset(
    {"TRUE", "T", "1", "YES", "Y", "对", "正确", "是", "V", "√"}
)

# 预编译正则：布尔假值字符串集合
FALSE_BOOLEAN_VALUES: frozenset[str] = frozenset(
    {"FALSE", "F", "0", "NO", "N", "错", "错误", "否", "X", "×"}
)

# 明显歧义逻辑自相矛盾触发词集合
AMBIGUOUS_TRIGGER_WORDS: frozenset[str] = frozenset(
    {"以上都对", "以上都不对", "以上皆对", "以上皆错", "以上均对", "以上均错"}
)


class QualityCheckType(enum.StrEnum):
    """四类一票否决式质检项类型枚举。"""

    NO_SOURCE = "NO_SOURCE"
    DUPLICATE = "DUPLICATE"
    ANSWER_CONFLICT = "ANSWER_CONFLICT"
    AMBIGUITY = "AMBIGUITY"


# 别名以保持与规范命名契约完全兼容
UnqualifiedReason = QualityCheckType


class QuestionType(enum.StrEnum):
    """题目类型枚举（覆盖 FR-20 规定的七大题型）。"""

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
    }
)


@dataclass(frozen=True)
class CandidateQuestion:
    """待质检的候选题目不可变值对象。"""

    question_id: str
    stem: str
    question_type: str
    answer: str
    options: tuple[dict[str, Any], ...] = ()
    source_snippet_ids: tuple[str, ...] = ()
    source_text: str = ""
    embedding: tuple[float, ...] | None = None
    analysis: str = ""
    created_at_seq: int = 0

    def __post_init__(self) -> None:
        """保障集合属性转化为不可变元组。"""
        if not isinstance(self.options, tuple):
            object.__setattr__(self, "options", tuple(self.options))
        if not isinstance(self.source_snippet_ids, tuple):
            object.__setattr__(self, "source_snippet_ids", tuple(self.source_snippet_ids))
        if self.embedding is not None and not isinstance(self.embedding, tuple):
            object.__setattr__(self, "embedding", tuple(self.embedding))


@dataclass(frozen=True)
class ExistingQuestionReference:
    """同资料下已通过质检的历史参考题目不可变对象。"""

    question_id: str
    stem: str
    question_type: str
    answer: str
    options: tuple[dict[str, Any], ...] = ()
    embedding: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        """保障集合属性转化为不可变元组。"""
        if not isinstance(self.options, tuple):
            object.__setattr__(self, "options", tuple(self.options))
        if self.embedding is not None and not isinstance(self.embedding, tuple):
            object.__setattr__(self, "embedding", tuple(self.embedding))


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
        """校验门禁配置参数合法性。

        Raises:
            ValueError: 当配置参数超出合法边界时抛出。
        """
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

    check_type: QualityCheckType
    is_passed: bool
    reason: str | None = None
    similarity_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SingleQuestionQualityResult:
    """单个候选题目质检综合判定结果。"""

    question_id: str
    is_qualified: bool
    unqualified_type: QualityCheckType | None
    unqualified_reason: str | None
    similarity_score: float | None
    check_items: tuple[QuestionQualityCheckItem, ...]

    def __post_init__(self) -> None:
        """保障检查明细转化为不可变元组。"""
        if not isinstance(self.check_items, tuple):
            object.__setattr__(self, "check_items", tuple(self.check_items))


@dataclass(frozen=True)
class QuestionQualityReport:
    """批次题目质检统一产出报告。"""

    qualified_questions: tuple[CandidateQuestion, ...]
    unqualified_questions: tuple[CandidateQuestion, ...]
    results: tuple[SingleQuestionQualityResult, ...]
    is_degraded: bool
    total_candidates: int
    qualified_count: int
    unqualified_count: int
    window_size_used: int

    def __post_init__(self) -> None:
        """保障列表属性转化为不可变元组。"""
        if not isinstance(self.qualified_questions, tuple):
            object.__setattr__(self, "qualified_questions", tuple(self.qualified_questions))
        if not isinstance(self.unqualified_questions, tuple):
            object.__setattr__(self, "unqualified_questions", tuple(self.unqualified_questions))
        if not isinstance(self.results, tuple):
            object.__setattr__(self, "results", tuple(self.results))


# ==============================================================================
# 纯函数数学与文本处理工具 (V(G) <= 6)
# ==============================================================================


def calculate_cosine_similarity(
    vector_a: Sequence[float] | None,
    vector_b: Sequence[float] | None,
) -> float:
    """计算两定长数值向量的余弦相似度。

    Args:
        vector_a: 向量 A 序列，可为 None。
        vector_b: 向量 B 序列，可为 None。

    Returns:
        余弦相似度数值，区间为 [-1.0, 1.0]；若向量缺失、维度不一致或存在零模长则返回 0.0。
    """
    if vector_a is None or vector_b is None:
        return 0.0
    if not vector_a or len(vector_a) != len(vector_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vector_a, vector_b, strict=False))
    norm_product = math.sqrt(sum(a * a for a in vector_a)) * math.sqrt(sum(b * b for b in vector_b))
    if norm_product == 0.0:
        return 0.0

    similarity = dot_product / norm_product
    return max(-1.0, min(1.0, similarity))


def calculate_text_similarity(text_a: str, text_b: str) -> float:
    """纯 Python 计算两段文本的字符级 2-gram Jaccard 相似度。

    Args:
        text_a: 文本 A。
        text_b: 文本 B。

    Returns:
        字符 2-gram Jaccard 相似度，区间为 [0.0, 1.0]。
    """
    normalized_a = "".join(text_a.split())
    normalized_b = "".join(text_b.split())
    if normalized_a == normalized_b:
        return 1.0 if normalized_a else 0.0
    if len(normalized_a) < 2 or len(normalized_b) < 2:
        return 0.0

    grams_a = {normalized_a[index : index + 2] for index in range(len(normalized_a) - 1)}
    grams_b = {normalized_b[index : index + 2] for index in range(len(normalized_b) - 1)}
    union_grams = grams_a | grams_b
    if not union_grams:
        return 0.0

    return len(grams_a & grams_b) / len(union_grams)


def extract_keywords(text: str) -> list[str]:
    """提取文本中长度 >= 2 的中英文实词列表。

    Args:
        text: 待提取实词的文本。

    Returns:
        匹配到的实词列表。
    """
    return CONTENT_WORD_PATTERN.findall(text)


extract_content_words = extract_keywords


# ==============================================================================
# 质检规则辅助函数 (V(G) <= 5)
# ==============================================================================


def _parse_option_keys(answer: str) -> frozenset[str]:
    """从答案字符串中提取大写选项键集合（如 'A, B' -> {'A', 'B'}）。

    Args:
        answer: 答案字符串。

    Returns:
        大写选项键集合。
    """
    cleaned_answer = answer.strip()
    if not cleaned_answer:
        return frozenset()

    tokens = re.split(r"[,;、\s|]+", cleaned_answer)
    result_keys: set[str] = set()
    for token in tokens:
        stripped_token = token.strip().upper()
        if not stripped_token:
            continue
        if stripped_token.isalpha() and len(stripped_token) > 1 and len(tokens) == 1:
            for character in stripped_token:
                result_keys.add(character)
        else:
            result_keys.add(stripped_token)
    return frozenset(result_keys)


def _normalize_boolean_answer(answer: str) -> bool | None:
    """将判断题文本规范化为布尔真假值。

    Args:
        answer: 判断题原始答案文本。

    Returns:
        布尔值；若无法识别为二值格式则返回 None。
    """
    cleaned = answer.strip().upper()
    if cleaned in TRUE_BOOLEAN_VALUES:
        return True
    if cleaned in FALSE_BOOLEAN_VALUES:
        return False
    return None


def _normalize_objective_answer(question_type: str, answer: str) -> frozenset[str] | bool | None:
    """归一化客观题答案集合以供冲突比对。

    Args:
        question_type: 题目类型。
        answer: 标准答案文本。

    Returns:
        归一化后的答案对象。
    """
    if question_type == QuestionType.TRUE_FALSE:
        return _normalize_boolean_answer(answer)
    return _parse_option_keys(answer)


def _calculate_stem_similarity(
    candidate: CandidateQuestion,
    existing_question: ExistingQuestionReference,
) -> tuple[float, bool]:
    """计算候选题与已有题题干相似度并返回降级标识。

    Args:
        candidate: 候选题目。
        existing_question: 已有题目。

    Returns:
        (相似度分值, 是否发生向量缺失降级)。
    """
    if candidate.embedding is not None and existing_question.embedding is not None:
        similarity = calculate_cosine_similarity(candidate.embedding, existing_question.embedding)
        return similarity, False

    text_similarity = calculate_text_similarity(candidate.stem, existing_question.stem)
    return text_similarity, True


def _check_batch_duplication(
    candidate: CandidateQuestion,
    prior_candidates: Sequence[CandidateQuestion],
) -> bool:
    """校验候选题干是否与同批次前序题干完全一致。

    Args:
        candidate: 当前候选题。
        prior_candidates: 同批次前序已处理候选题。

    Returns:
        若题干重复返回 True，否则返回 False。
    """
    candidate_stem = "".join(candidate.stem.split())
    return any(candidate_stem == "".join(prior.stem.split()) for prior in prior_candidates)


def _check_stem_and_options_structure(
    candidate: CandidateQuestion,
    config: QuestionQualityConfig,
) -> tuple[bool, str | None]:
    """校验题干长度与选项内容是否重复。

    Args:
        candidate: 候选题目。
        config: 质检配置。

    Returns:
        (是否通过, 错误原因)。
    """
    if len(candidate.stem.strip()) < config.min_stem_length:
        return False, f"题干长度小于 {config.min_stem_length} 字符"

    if candidate.options:
        contents = [str(option.get("content", "")).strip() for option in candidate.options]
        if len(contents) != len(set(contents)):
            return False, "选项存在重复内容"

    return True, None


def _check_multiple_choice_rules(
    candidate: CandidateQuestion,
) -> tuple[bool, str | None]:
    """校验多选题选项总数与答案格式。

    Args:
        candidate: 候选题目。

    Returns:
        (是否通过, 错误原因)。
    """
    keys = _parse_option_keys(candidate.answer)
    option_count = len(candidate.options)
    if option_count < 3:
        return False, "多选题选项总数少于 3 项"
    if len(keys) < 2:
        return False, "多选题正确答案少于 2 项"
    if len(keys) >= option_count:
        return False, "多选题正确答案包含全量选项"
    return True, None


def _check_type_specific_rules(
    candidate: CandidateQuestion,
) -> tuple[bool, str | None]:
    """校验特定题型的选项数与答案格式。

    Args:
        candidate: 候选题目。

    Returns:
        (是否通过, 错误原因)。
    """
    if candidate.question_type == QuestionType.SINGLE_CHOICE:
        keys = _parse_option_keys(candidate.answer)
        if len(keys) != 1:
            return False, "单选题正确答案数不为 1"
        return True, None

    if candidate.question_type == QuestionType.MULTIPLE_CHOICE:
        return _check_multiple_choice_rules(candidate)

    if candidate.question_type == QuestionType.TRUE_FALSE:
        if _normalize_boolean_answer(candidate.answer) is None:
            return False, "判断题答案非二值格式"
        return True, None

    if not candidate.answer.strip():
        return False, "参考答案内容为空"

    return True, None


def _check_logic_contradiction(
    candidate: CandidateQuestion,
) -> tuple[bool, str | None]:
    """校验题干或选项中是否存在'以上都对/错'自相矛盾词。

    Args:
        candidate: 候选题目。

    Returns:
        (是否通过, 错误原因)。
    """
    stem_has_trigger = any(trigger in candidate.stem for trigger in AMBIGUOUS_TRIGGER_WORDS)
    if stem_has_trigger:
        return False, "存在'以上都对/错'且与其他选项逻辑冲突"

    trigger_keys = {
        str(option.get("key", "")).strip().upper()
        for option in candidate.options
        if any(trigger in str(option.get("content", "")) for trigger in AMBIGUOUS_TRIGGER_WORDS)
    }

    if trigger_keys:
        answer_keys = _parse_option_keys(candidate.answer)
        if len(answer_keys) > 1 or candidate.question_type == QuestionType.MULTIPLE_CHOICE:
            return False, "存在'以上都对/错'且与其他选项逻辑冲突"

    return True, None


# ==============================================================================
# 四项一票否决独立纯函数 (V(G) <= 8)
# ==============================================================================


def check_source_grounding(
    stem: str,
    source_text: str,
    source_snippet_ids: Sequence[str],
    config: QuestionQualityConfig,
) -> tuple[bool, str | None, float]:
    """校验题干是否具备切片来源且实词重合率达标 (NO_SOURCE)。

    Args:
        stem: 题干全文。
        source_text: 来源切片拼接原文。
        source_snippet_ids: 来源切片标识序列。
        config: 质检配置。

    Returns:
        (是否通过, 失败原因描述, 实词重合率分值)。
    """
    if not source_snippet_ids:
        return False, "缺少来源切片标识", 0.0
    if not source_text.strip():
        return False, "来源片段内容为空", 0.0

    keywords = extract_keywords(stem)
    if not keywords:
        return False, "题干未包含有效实词", 0.0

    unique_keywords = set(keywords)
    hit_count = sum(1 for word in unique_keywords if word in source_text)
    ratio = hit_count / len(unique_keywords)
    if ratio < config.min_source_keyword_ratio:
        return (
            False,
            f"题干实词在来源片段重合率不足 {config.min_source_keyword_ratio * 100:.1f}%",
            ratio,
        )

    return True, None, ratio


def check_duplication(
    candidate: CandidateQuestion,
    existing: Sequence[ExistingQuestionReference],
    prior_candidates: Sequence[CandidateQuestion],
    config: QuestionQualityConfig,
) -> tuple[bool, str | None, float | None, bool]:
    """校验候选题目是否在批次内或同已有题库重复 (DUPLICATE)。

    Args:
        candidate: 候选题目。
        existing: 已有历史参考题目。
        prior_candidates: 同批次前序候选题序列。
        config: 质检配置。

    Returns:
        (是否通过, 失败原因描述, 最高相似度分值, 是否发生向量缺失降级)。
    """
    if _check_batch_duplication(candidate, prior_candidates):
        return False, "同批次内题干完全重复（保留首发题目）", 1.0, False

    max_similarity: float = 0.0
    is_degraded = False

    for existing_question in existing:
        if candidate.embedding is not None and existing_question.embedding is not None:
            vector_similarity = calculate_cosine_similarity(
                candidate.embedding, existing_question.embedding
            )
            max_similarity = max(max_similarity, vector_similarity)
            if vector_similarity >= config.duplicate_vector_threshold:
                return False, "与已有题目语义向量相似度超限", vector_similarity, is_degraded
        else:
            is_degraded = True

        text_similarity = calculate_text_similarity(candidate.stem, existing_question.stem)
        max_similarity = max(max_similarity, text_similarity)
        if text_similarity >= config.duplicate_text_threshold:
            return False, "与已有题目字符相似度超限", text_similarity, is_degraded

    similarity_score = max_similarity if max_similarity > 0.0 else None
    return True, None, similarity_score, is_degraded


def check_answer_conflict(
    candidate: CandidateQuestion,
    existing: Sequence[ExistingQuestionReference],
    config: QuestionQualityConfig,
) -> tuple[bool, str | None, float | None, bool]:
    """校验客观题在题干高度相似时标准答案是否发生冲突 (ANSWER_CONFLICT)。

    主观题与填空题自动跳过此检查。

    Args:
        candidate: 候选题目。
        existing: 已有历史参考题目。
        config: 质检配置。

    Returns:
        (是否通过, 失败原因描述, 最高相似度分值, 是否发生向量缺失降级)。
    """
    if candidate.question_type not in OBJECTIVE_QUESTION_TYPES:
        return True, None, None, False

    candidate_answer = _normalize_objective_answer(candidate.question_type, candidate.answer)
    max_similarity: float = 0.0
    is_degraded = False

    for existing_question in existing:
        if existing_question.question_type not in OBJECTIVE_QUESTION_TYPES:
            continue

        stem_similarity, item_degraded = _calculate_stem_similarity(candidate, existing_question)
        if item_degraded:
            is_degraded = True
        max_similarity = max(max_similarity, stem_similarity)

        if stem_similarity >= config.conflict_vector_threshold:
            # 答案冲突仅在「同一答案域」内比对：判断题答案域为布尔，选择题答案域为
            # 选项键集合，二者跨类型比较永不相等（如 True != frozenset({'A'})），
            # 若强行比对会把题型不同的近似题误判为一票否决的答案冲突。
            candidate_is_true_false = candidate.question_type == QuestionType.TRUE_FALSE
            existing_is_true_false = existing_question.question_type == QuestionType.TRUE_FALSE
            if candidate_is_true_false != existing_is_true_false:
                continue

            existing_answer = _normalize_objective_answer(
                existing_question.question_type, existing_question.answer
            )
            if candidate_answer != existing_answer:
                return (
                    False,
                    "题干高度相似但客观题标准答案冲突",
                    stem_similarity,
                    is_degraded,
                )

    similarity_score = max_similarity if max_similarity > 0.0 else None
    return True, None, similarity_score, is_degraded


def check_ambiguity(
    candidate: CandidateQuestion,
    config: QuestionQualityConfig,
) -> tuple[bool, str | None]:
    """校验题目题干长度、选项重复、题型结构与自相矛盾词 (AMBIGUITY)。

    Args:
        candidate: 候选题目。
        config: 质检配置。

    Returns:
        (是否通过, 失败原因描述)。
    """
    is_structure_valid, structure_reason = _check_stem_and_options_structure(candidate, config)
    if not is_structure_valid:
        return False, structure_reason

    is_type_valid, type_reason = _check_type_specific_rules(candidate)
    if not is_type_valid:
        return False, type_reason

    return _check_logic_contradiction(candidate)


# ==============================================================================
# 质检编排与批次主入口 (V(G) <= 6)
# ==============================================================================


def evaluate_single_question(
    candidate: CandidateQuestion,
    existing: Sequence[ExistingQuestionReference],
    prior_candidates: Sequence[CandidateQuestion],
    config: QuestionQualityConfig,
) -> tuple[SingleQuestionQualityResult, bool]:
    """按四类一票否决固定顺序调度单题质检流水线。

    执行流水线：NO_SOURCE -> DUPLICATE -> ANSWER_CONFLICT -> AMBIGUITY。
    首个不通过项立即短路否决，并产出诊断明细。

    Args:
        candidate: 候选题目。
        existing: 已有历史参考题目。
        prior_candidates: 同批次前序候选题序列。
        config: 质检配置。

    Returns:
        (单题评估结果对象, 是否发生向量缺失降级)。
    """
    # 1. 无来源检查 (NO_SOURCE)
    is_source_valid, source_reason, source_ratio = check_source_grounding(
        candidate.stem,
        candidate.source_text,
        candidate.source_snippet_ids,
        config,
    )
    item_source = QuestionQualityCheckItem(
        check_type=QualityCheckType.NO_SOURCE,
        is_passed=is_source_valid,
        reason=source_reason,
        similarity_score=source_ratio,
    )
    if not is_source_valid:
        return (
            SingleQuestionQualityResult(
                question_id=candidate.question_id,
                is_qualified=False,
                unqualified_type=QualityCheckType.NO_SOURCE,
                unqualified_reason=source_reason,
                similarity_score=None,
                check_items=(item_source,),
            ),
            False,
        )

    # 2. 重复题检查 (DUPLICATE)
    is_dup_valid, dup_reason, dup_similarity, dup_degraded = check_duplication(
        candidate, existing, prior_candidates, config
    )
    item_dup = QuestionQualityCheckItem(
        check_type=QualityCheckType.DUPLICATE,
        is_passed=is_dup_valid,
        reason=dup_reason,
        similarity_score=dup_similarity,
    )
    if not is_dup_valid:
        return (
            SingleQuestionQualityResult(
                question_id=candidate.question_id,
                is_qualified=False,
                unqualified_type=QualityCheckType.DUPLICATE,
                unqualified_reason=dup_reason,
                similarity_score=dup_similarity,
                check_items=(item_source, item_dup),
            ),
            dup_degraded,
        )

    # 3. 答案冲突检查 (ANSWER_CONFLICT)
    is_conflict_valid, conflict_reason, conflict_similarity, conflict_degraded = (
        check_answer_conflict(candidate, existing, config)
    )
    overall_degraded = dup_degraded or conflict_degraded
    item_conflict = QuestionQualityCheckItem(
        check_type=QualityCheckType.ANSWER_CONFLICT,
        is_passed=is_conflict_valid,
        reason=conflict_reason,
        similarity_score=conflict_similarity,
    )
    if not is_conflict_valid:
        return (
            SingleQuestionQualityResult(
                question_id=candidate.question_id,
                is_qualified=False,
                unqualified_type=QualityCheckType.ANSWER_CONFLICT,
                unqualified_reason=conflict_reason,
                similarity_score=conflict_similarity,
                check_items=(item_source, item_dup, item_conflict),
            ),
            overall_degraded,
        )

    # 4. 明显歧义检查 (AMBIGUITY)
    is_ambiguity_valid, ambiguity_reason = check_ambiguity(candidate, config)
    item_ambiguity = QuestionQualityCheckItem(
        check_type=QualityCheckType.AMBIGUITY,
        is_passed=is_ambiguity_valid,
        reason=ambiguity_reason,
        similarity_score=None,
    )
    if not is_ambiguity_valid:
        return (
            SingleQuestionQualityResult(
                question_id=candidate.question_id,
                is_qualified=False,
                unqualified_type=QualityCheckType.AMBIGUITY,
                unqualified_reason=ambiguity_reason,
                similarity_score=None,
                check_items=(item_source, item_dup, item_conflict, item_ambiguity),
            ),
            overall_degraded,
        )

    # 全检合格通过
    return (
        SingleQuestionQualityResult(
            question_id=candidate.question_id,
            is_qualified=True,
            unqualified_type=None,
            unqualified_reason=None,
            similarity_score=None,
            check_items=(item_source, item_dup, item_conflict, item_ambiguity),
        ),
        overall_degraded,
    )


def filter_qualified_questions(
    candidates: Sequence[CandidateQuestion],
    existing_questions: Sequence[ExistingQuestionReference] = (),
    config: QuestionQualityConfig | None = None,
) -> QuestionQualityReport:
    """批次题目质检与待处理过滤主入口纯函数。

    对输入候选题目执行窗口裁剪、批次保序、同批次查重及四项一票否决质检，
    将合格题目与不合格题目分别归入报告集合。

    Args:
        candidates: 待质检候选题目序列。
        existing_questions: 同资料已入库题目参考序列。
        config: 质检配置参数；若为 None 则使用默认配置。

    Returns:
        不可变 QuestionQualityReport 质检报告对象。
    """
    effective_config = config if config is not None else QuestionQualityConfig()
    if not candidates:
        return QuestionQualityReport(
            qualified_questions=(),
            unqualified_questions=(),
            results=(),
            is_degraded=False,
            total_candidates=0,
            qualified_count=0,
            unqualified_count=0,
            window_size_used=0,
        )

    cropped_existing = existing_questions[: effective_config.max_existing_questions_window]
    window_size_used = len(cropped_existing)
    sorted_candidates = sorted(candidates, key=lambda question: question.created_at_seq)

    prior_candidates: list[CandidateQuestion] = []
    qualified_questions: list[CandidateQuestion] = []
    unqualified_questions: list[CandidateQuestion] = []
    results: list[SingleQuestionQualityResult] = []
    is_any_degraded = False

    for candidate in sorted_candidates:
        result, is_degraded = evaluate_single_question(
            candidate, cropped_existing, prior_candidates, effective_config
        )
        if is_degraded:
            is_any_degraded = True
        results.append(result)
        if result.is_qualified:
            qualified_questions.append(candidate)
        else:
            unqualified_questions.append(candidate)
        prior_candidates.append(candidate)

    return QuestionQualityReport(
        qualified_questions=tuple(qualified_questions),
        unqualified_questions=tuple(unqualified_questions),
        results=tuple(results),
        is_degraded=is_any_degraded,
        total_candidates=len(candidates),
        qualified_count=len(qualified_questions),
        unqualified_count=len(unqualified_questions),
        window_size_used=window_size_used,
    )
