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

from app.core.question_types import QuestionType as QuestionType

# ==============================================================================
# 题目质检门禁核心常量与决策基准
# 严格遵循《概要设计说明书》第 6.4 节与《软件需求规格说明书》FR-24、FR-25、FR-28
# ==============================================================================

# 依据：概要设计说明书第 6.4 节与 FR-24，重复题向量余弦相似度门禁上限为 0.90
# 题干+选项语义向量余弦相似度 >= 0.90 判定为疑似重复 (SOFT_FLAG)，>= 0.95 判定为硬重复 (HARD_DEFECT)
DEFAULT_DUPLICATE_VECTOR_THRESHOLD: float = 0.90
DEFAULT_HARD_DUPLICATE_VECTOR_THRESHOLD: float = 0.95

# 依据：概要设计说明书第 6.4 节与 FR-24，重复题字符级相似度门禁上限为 0.85
# 字符 2-gram Jaccard 相似度 >= 0.85 判定为字面重复题，闭区间拦截
DEFAULT_DUPLICATE_TEXT_THRESHOLD: float = 0.85

# 依据：概要设计说明书第 6.4 节与 FR-24，客观题答案冲突的题干相似度门禁下限为 0.88
# 两道客观题题干相似度 >= 0.88 且答案不同时，按字面/向量强度划分 SOFT_FLAG 或 HARD_DEFECT
DEFAULT_CONFLICT_VECTOR_THRESHOLD: float = 0.88

# 依据：概要设计说明书第 6.4 节与 FR-24，来源片段实词重合率门禁下限为 30% (0.30)
# 题干中实词（中文 2-gram 与英文词）在来源片段中的出现比例 < 0.30 判定为 SOFT_FLAG 交由 AI 裁判复核
DEFAULT_MIN_SOURCE_KEYWORD_RATIO: float = 0.30

# 依据：概要设计说明书第 6.4 节与 FR-24，题干字符数绝对下限为 6 字符
# 题干去空白字符数 < 6 字符判定为表述过短或残缺，直接判为明显歧义
DEFAULT_MIN_STEM_LENGTH: int = 6

# 依据：概要设计说明书第 6.4 节，已有题目比对滑动窗口上限为 500 道
# 超过 500 道时截取最近 500 道题目参与查重与冲突比对，保障单次质检毫秒级响应
MAX_EXISTING_QUESTIONS_WINDOW: int = 500

# 预编译正则：中英文有效实词（长度 >= 2 的连续汉字或连续英文字母）
CONTENT_WORD_PATTERN: re.Pattern[str] = re.compile(r"[\u4e00-\u9fa5]{2,}|[a-zA-Z]{2,}")
_TOKEN_SEGMENT_PATTERN: re.Pattern[str] = re.compile(
    r"[\u4e00-\u9fa5]{2,}|[a-zA-Z]{2,}|[a-zA-Z]\d+"
)
_LATEX_ENV_PATTERN: re.Pattern[str] = re.compile(r"\\(?:begin|end)\{[^}]*\}")
_LATEX_COMMAND_PATTERN: re.Pattern[str] = re.compile(r"\\[a-zA-Z]+\*?")
_LATEX_SYMBOL_PATTERN: re.Pattern[str] = re.compile(r"[\$\{\}\[\]\(\)^_&\\]+")

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


class QualitySeverity(enum.StrEnum):
    """确定性预检三态严重度枚举。"""

    PASS = "pass"  # noqa: S105
    SOFT_FLAG = "soft_flag"
    HARD_DEFECT = "hard_defect"


# 别名以保持与规范命名契约完全兼容
UnqualifiedReason = QualityCheckType


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
    hard_duplicate_vector_threshold: float = DEFAULT_HARD_DUPLICATE_VECTOR_THRESHOLD
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
        if not (0.0 <= self.hard_duplicate_vector_threshold <= 1.0):
            raise ValueError("hard_duplicate_vector_threshold must be between 0.0 and 1.0")
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
    severity: QualitySeverity = QualitySeverity.PASS


@dataclass(frozen=True)
class SingleQuestionQualityResult:
    """单个候选题目质检综合判定结果。"""

    question_id: str
    is_qualified: bool
    unqualified_type: QualityCheckType | None
    unqualified_reason: str | None
    similarity_score: float | None
    check_items: tuple[QuestionQualityCheckItem, ...]
    severity: QualitySeverity = QualitySeverity.PASS

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


def strip_latex_commands(text: str) -> str:
    """剥离 LaTeX 环境、命令名与定界符号，保留语义词与自然语言正文。

    Args:
        text: 原始含公式文本。

    Returns:
        清洗后的纯文本。
    """
    cleaned = _LATEX_ENV_PATTERN.sub(" ", text)
    cleaned = _LATEX_COMMAND_PATTERN.sub(" ", cleaned)
    return _LATEX_SYMBOL_PATTERN.sub(" ", cleaned)


def extract_keywords(text: str) -> list[str]:
    """提取文本中的中文 2-gram 与大小写归一化英文实词。

    先剥离 LaTeX 命令，防止 ``\\mathbf``、``\\frac`` 等语法名污染实词分母；
    对连续汉字采用 2-gram 切分，对英文与字母数字标记统一转为小写。

    Args:
        text: 待提取实词的文本。

    Returns:
        匹配到的实词列表。
    """
    cleaned = strip_latex_commands(text)
    tokens: list[str] = []
    for match in _TOKEN_SEGMENT_PATTERN.finditer(cleaned):
        segment = match.group(0)
        if "\u4e00" <= segment[0] <= "\u9fa5":
            tokens.extend(segment[index : index + 2] for index in range(len(segment) - 1))
        else:
            tokens.append(segment.lower())
    return tokens


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


def _evaluate_batch_duplication(
    candidate: CandidateQuestion,
    prior_candidates: Sequence[CandidateQuestion],
    config: QuestionQualityConfig,
) -> tuple[bool, str | None, float | None, QualitySeverity, dict[str, Any]]:
    """对同批次前序题目执行字面与语义向量查重。"""
    if _check_batch_duplication(candidate, prior_candidates):
        return (
            False,
            "同批次内题干完全重复（保留首发题目）",
            1.0,
            QualitySeverity.HARD_DEFECT,
            {},
        )

    hard_vec_thr = max(config.duplicate_vector_threshold, config.hard_duplicate_vector_threshold)
    soft_hit: tuple[str, float, dict[str, Any]] | None = None
    for prior in prior_candidates:
        text_sim = calculate_text_similarity(candidate.stem, prior.stem)
        if text_sim >= config.duplicate_text_threshold:
            return (
                False,
                "同批次内题干字符相似度超限",
                text_sim,
                QualitySeverity.HARD_DEFECT,
                {"matched_question_id": prior.question_id, "matched_stem": prior.stem},
            )
        if candidate.embedding is not None and prior.embedding is not None:
            vec_sim = calculate_cosine_similarity(candidate.embedding, prior.embedding)
            meta = {"matched_question_id": prior.question_id, "matched_stem": prior.stem}
            if vec_sim >= hard_vec_thr:
                return (
                    False,
                    "同批次内语义向量相似度超限",
                    vec_sim,
                    QualitySeverity.HARD_DEFECT,
                    meta,
                )
            if vec_sim >= config.duplicate_vector_threshold and (
                soft_hit is None or vec_sim > soft_hit[1]
            ):
                soft_hit = ("同批次内语义向量相似度超限", vec_sim, meta)

    if soft_hit is not None:
        return False, soft_hit[0], soft_hit[1], QualitySeverity.SOFT_FLAG, soft_hit[2]
    return True, None, None, QualitySeverity.PASS, {}


def _check_stem_and_options_structure(
    candidate: CandidateQuestion,
    config: QuestionQualityConfig,
) -> tuple[bool, str | None]:
    """校验题干长度与选项内容是否重复或为空。

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
        if any(not content for content in contents):
            return False, "选项内容不能为空"
        if len(contents) != len(set(contents)):
            return False, "选项存在重复内容"

    return True, None


def _extract_valid_option_keys(options: Sequence[dict[str, Any]]) -> set[str]:
    """提取题目选项集合中的有效选项字母键。"""
    return {
        str(option.get("key", "")).strip().upper()
        for option in options
        if str(option.get("key", "")).strip()
    }


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
    option_keys = _extract_valid_option_keys(candidate.options)
    if option_keys and not keys.issubset(option_keys):
        return False, "多选题正确答案不在选项列表内"
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
        if len(candidate.options) < 2:
            return False, "单选题选项总数少于 2 项"
        keys = _parse_option_keys(candidate.answer)
        if len(keys) != 1:
            return False, "单选题正确答案数不为 1"
        option_keys = _extract_valid_option_keys(candidate.options)
        if option_keys and not keys.issubset(option_keys):
            return False, "单选题正确答案不在选项列表内"
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


def _source_grounding_severity(
    source_snippet_ids: Sequence[str],
    source_text: str,
    is_passed: bool,
) -> QualitySeverity:
    """判定来源检查未通过时的严重度分级。"""
    if is_passed:
        return QualitySeverity.PASS
    if not source_snippet_ids or not source_text.strip():
        return QualitySeverity.HARD_DEFECT
    return QualitySeverity.SOFT_FLAG


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

    normalized_source = strip_latex_commands(source_text).lower()
    unique_keywords = set(keywords)
    hit_count = sum(1 for word in unique_keywords if word in normalized_source)
    ratio = hit_count / len(unique_keywords)
    if ratio < config.min_source_keyword_ratio:
        return (
            False,
            f"题干实词在来源片段重合率不足 {config.min_source_keyword_ratio * 100:.1f}%",
            ratio,
        )

    return True, None, ratio


def _evaluate_duplication(
    candidate: CandidateQuestion,
    existing: Sequence[ExistingQuestionReference],
    prior_candidates: Sequence[CandidateQuestion],
    config: QuestionQualityConfig,
) -> tuple[bool, str | None, float | None, bool, QualitySeverity, dict[str, Any]]:
    """校验候选题目是否在批次内或同已有题库重复并返回三态严重度与匹配参考元数据。"""
    batch_valid, batch_reason, batch_score, batch_severity, batch_meta = (
        _evaluate_batch_duplication(candidate, prior_candidates, config)
    )
    if batch_severity == QualitySeverity.HARD_DEFECT:
        return batch_valid, batch_reason, batch_score, False, batch_severity, batch_meta

    hard_vec_thr = max(config.duplicate_vector_threshold, config.hard_duplicate_vector_threshold)
    max_similarity: float = batch_score if batch_score is not None else 0.0
    is_degraded = False
    soft_hit: tuple[str, float, dict[str, Any]] | None = (
        (batch_reason or "同批次内语义向量相似度超限", batch_score, batch_meta)
        if batch_severity == QualitySeverity.SOFT_FLAG and batch_score is not None
        else None
    )

    for existing_question in existing:
        ref_meta = {
            "matched_question_id": existing_question.question_id,
            "matched_stem": existing_question.stem,
            "matched_answer": existing_question.answer,
        }
        if candidate.embedding is not None and existing_question.embedding is not None:
            vec_sim = calculate_cosine_similarity(candidate.embedding, existing_question.embedding)
            max_similarity = max(max_similarity, vec_sim)
            if vec_sim >= hard_vec_thr:
                return (
                    False,
                    "与已有题目语义向量相似度超限",
                    vec_sim,
                    is_degraded,
                    QualitySeverity.HARD_DEFECT,
                    ref_meta,
                )
            if vec_sim >= config.duplicate_vector_threshold and (
                soft_hit is None or vec_sim > soft_hit[1]
            ):
                soft_hit = ("与已有题目语义向量相似度超限", vec_sim, ref_meta)
        else:
            is_degraded = True

        text_sim = calculate_text_similarity(candidate.stem, existing_question.stem)
        max_similarity = max(max_similarity, text_sim)
        if text_sim >= config.duplicate_text_threshold:
            return (
                False,
                "与已有题目字符相似度超限",
                text_sim,
                is_degraded,
                QualitySeverity.HARD_DEFECT,
                ref_meta,
            )

    if soft_hit is not None:
        return False, soft_hit[0], soft_hit[1], is_degraded, QualitySeverity.SOFT_FLAG, soft_hit[2]

    similarity_score = max_similarity if max_similarity > 0.0 else None
    return True, None, similarity_score, is_degraded, QualitySeverity.PASS, {}


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
    is_valid, reason, similarity_score, is_degraded, _severity, _meta = _evaluate_duplication(
        candidate, existing, prior_candidates, config
    )
    return is_valid, reason, similarity_score, is_degraded


def _evaluate_answer_conflict(
    candidate: CandidateQuestion,
    existing: Sequence[ExistingQuestionReference],
    config: QuestionQualityConfig,
) -> tuple[bool, str | None, float | None, bool, QualitySeverity, dict[str, Any]]:
    """校验客观题在题干高度相似时标准答案是否发生冲突并返回三态严重度。"""
    if candidate.question_type not in OBJECTIVE_QUESTION_TYPES:
        return True, None, None, False, QualitySeverity.PASS, {}

    candidate_answer = _normalize_objective_answer(candidate.question_type, candidate.answer)
    hard_vec_thr = max(config.conflict_vector_threshold, config.hard_duplicate_vector_threshold)
    max_similarity: float = 0.0
    is_degraded = False
    soft_hit: tuple[float, dict[str, Any]] | None = None

    for existing_question in existing:
        if existing_question.question_type not in OBJECTIVE_QUESTION_TYPES:
            continue

        stem_similarity, item_degraded = _calculate_stem_similarity(candidate, existing_question)
        if item_degraded:
            is_degraded = True
        max_similarity = max(max_similarity, stem_similarity)

        if stem_similarity < config.conflict_vector_threshold:
            continue

        candidate_is_tf = candidate.question_type == QuestionType.TRUE_FALSE
        existing_is_tf = existing_question.question_type == QuestionType.TRUE_FALSE
        if candidate_is_tf != existing_is_tf:
            continue

        existing_answer = _normalize_objective_answer(
            existing_question.question_type, existing_question.answer
        )
        if candidate_answer == existing_answer:
            continue

        text_sim = calculate_text_similarity(candidate.stem, existing_question.stem)
        ref_meta = {
            "matched_question_id": existing_question.question_id,
            "matched_stem": existing_question.stem,
            "matched_answer": existing_question.answer,
        }
        if (
            item_degraded
            or text_sim >= config.duplicate_text_threshold
            or stem_similarity >= hard_vec_thr
        ):
            return (
                False,
                "题干高度相似但客观题标准答案冲突",
                stem_similarity,
                is_degraded,
                QualitySeverity.HARD_DEFECT,
                ref_meta,
            )
        if soft_hit is None or stem_similarity > soft_hit[0]:
            soft_hit = (stem_similarity, ref_meta)

    if soft_hit is not None:
        return (
            False,
            "题干高度相似但客观题标准答案冲突",
            soft_hit[0],
            is_degraded,
            QualitySeverity.SOFT_FLAG,
            soft_hit[1],
        )

    similarity_score = max_similarity if max_similarity > 0.0 else None
    return True, None, similarity_score, is_degraded, QualitySeverity.PASS, {}


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
    is_valid, reason, similarity_score, is_degraded, _severity, _meta = _evaluate_answer_conflict(
        candidate, existing, config
    )
    return is_valid, reason, similarity_score, is_degraded


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
    """按四类质检固定顺序调度单题预检流水线并输出三态严重度。

    执行流水线：NO_SOURCE -> DUPLICATE -> ANSWER_CONFLICT -> AMBIGUITY。
    遇到 HARD_DEFECT 立即短路否决；遇到 SOFT_FLAG 继续完成后续检查以确保
    结构性 HARD_DEFECT 不会被软标记掩盖。

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
    source_severity = _source_grounding_severity(
        candidate.source_snippet_ids, candidate.source_text, is_source_valid
    )
    item_source = QuestionQualityCheckItem(
        check_type=QualityCheckType.NO_SOURCE,
        is_passed=is_source_valid,
        reason=source_reason,
        similarity_score=source_ratio,
        metadata={"severity": source_severity.value},
        severity=source_severity,
    )
    if source_severity == QualitySeverity.HARD_DEFECT:
        return (
            SingleQuestionQualityResult(
                question_id=candidate.question_id,
                is_qualified=False,
                unqualified_type=QualityCheckType.NO_SOURCE,
                unqualified_reason=source_reason,
                similarity_score=None,
                check_items=(item_source,),
                severity=QualitySeverity.HARD_DEFECT,
            ),
            False,
        )

    # 2. 重复题检查 (DUPLICATE)
    is_dup_valid, dup_reason, dup_similarity, dup_degraded, dup_severity, dup_meta = (
        _evaluate_duplication(candidate, existing, prior_candidates, config)
    )
    item_dup = QuestionQualityCheckItem(
        check_type=QualityCheckType.DUPLICATE,
        is_passed=is_dup_valid,
        reason=dup_reason,
        similarity_score=dup_similarity,
        metadata={**dup_meta, "severity": dup_severity.value},
        severity=dup_severity,
    )
    if dup_severity == QualitySeverity.HARD_DEFECT:
        return (
            SingleQuestionQualityResult(
                question_id=candidate.question_id,
                is_qualified=False,
                unqualified_type=QualityCheckType.DUPLICATE,
                unqualified_reason=dup_reason,
                similarity_score=dup_similarity,
                check_items=(item_source, item_dup),
                severity=QualitySeverity.HARD_DEFECT,
            ),
            dup_degraded,
        )

    # 3. 答案冲突检查 (ANSWER_CONFLICT)
    (
        is_conflict_valid,
        conflict_reason,
        conflict_similarity,
        conflict_degraded,
        conflict_severity,
        conflict_meta,
    ) = _evaluate_answer_conflict(candidate, existing, config)
    overall_degraded = dup_degraded or conflict_degraded
    item_conflict = QuestionQualityCheckItem(
        check_type=QualityCheckType.ANSWER_CONFLICT,
        is_passed=is_conflict_valid,
        reason=conflict_reason,
        similarity_score=conflict_similarity,
        metadata={**conflict_meta, "severity": conflict_severity.value},
        severity=conflict_severity,
    )
    if conflict_severity == QualitySeverity.HARD_DEFECT:
        return (
            SingleQuestionQualityResult(
                question_id=candidate.question_id,
                is_qualified=False,
                unqualified_type=QualityCheckType.ANSWER_CONFLICT,
                unqualified_reason=conflict_reason,
                similarity_score=conflict_similarity,
                check_items=(item_source, item_dup, item_conflict),
                severity=QualitySeverity.HARD_DEFECT,
            ),
            overall_degraded,
        )

    # 4. 明显歧义检查 (AMBIGUITY)
    is_ambiguity_valid, ambiguity_reason = check_ambiguity(candidate, config)
    ambiguity_severity = QualitySeverity.PASS if is_ambiguity_valid else QualitySeverity.HARD_DEFECT
    item_ambiguity = QuestionQualityCheckItem(
        check_type=QualityCheckType.AMBIGUITY,
        is_passed=is_ambiguity_valid,
        reason=ambiguity_reason,
        similarity_score=None,
        metadata={"severity": ambiguity_severity.value},
        severity=ambiguity_severity,
    )
    all_items = (item_source, item_dup, item_conflict, item_ambiguity)
    if ambiguity_severity == QualitySeverity.HARD_DEFECT:
        return (
            SingleQuestionQualityResult(
                question_id=candidate.question_id,
                is_qualified=False,
                unqualified_type=QualityCheckType.AMBIGUITY,
                unqualified_reason=ambiguity_reason,
                similarity_score=None,
                check_items=all_items,
                severity=QualitySeverity.HARD_DEFECT,
            ),
            overall_degraded,
        )

    soft_item = next(
        (item for item in all_items if item.severity == QualitySeverity.SOFT_FLAG), None
    )
    if soft_item is not None:
        return (
            SingleQuestionQualityResult(
                question_id=candidate.question_id,
                is_qualified=False,
                unqualified_type=soft_item.check_type,
                unqualified_reason=soft_item.reason,
                similarity_score=soft_item.similarity_score,
                check_items=all_items,
                severity=QualitySeverity.SOFT_FLAG,
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
            check_items=all_items,
            severity=QualitySeverity.PASS,
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
