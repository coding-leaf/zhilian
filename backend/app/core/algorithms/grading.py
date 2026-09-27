"""判题阈值与匹配算法纯函数计算核。

本模块严格遵循纯函数计算核铁律（无外部 I/O、无网络、无数据库依赖、无状态副作用），
提供客观题规范化秒判、主观题要点与语义向量复合评估、双阈值分流（>= 0.82 离线判对，<= 0.45 离线判错，
中间转 AI）以及 4 类转 AI 决策仲裁流水线。
"""

import enum
import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# ==============================================================================
# 判题阈值与分流决策核心常量
# 严格遵循《概要设计说明书》第 6.5 节与《软件需求规格说明书》FR-37 至 FR-44
# ==============================================================================

# 依据：概要设计说明书第 6.5 节与 FR-40，主观题匹配度上阈值取 0.82
# 达到或超过该值时按离线判对处理，离线判对准确率在测试样本上保持 95% 以上
DEFAULT_UPPER_SIMILARITY_THRESHOLD: float = 0.82
UPPER_SIMILARITY_THRESHOLD: float = DEFAULT_UPPER_SIMILARITY_THRESHOLD

# 依据：概要设计说明书第 6.5 节与 FR-40，主观题匹配度下阈值取 0.45
# 低于或等于该值时按离线判错处理，避免明显错误答案被离线判对
DEFAULT_LOWER_SIMILARITY_THRESHOLD: float = 0.45
LOWER_SIMILARITY_THRESHOLD: float = DEFAULT_LOWER_SIMILARITY_THRESHOLD

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

# 依据：概要设计说明书第 6.5 节，中文关键否定词集合（共 20 个）
CHINESE_NEGATION_WORDS: frozenset[str] = frozenset(
    {
        "不",
        "没",
        "没有",
        "未",
        "非",
        "否",
        "并非",
        "毫无",
        "决不",
        "绝不",
        "莫",
        "勿",
        "毋",
        "甭",
        "未曾",
        "未尝",
        "无",
        "免",
        "拒",
        "缺",
    }
)

# 预编译正则：分句分隔符（界定否定词局部作用域，否定修饰不跨分句传播）
SENTENCE_SPLIT_PATTERN: re.Pattern[str] = re.compile(r"[，。；！？\n;,!?]+")

# 预编译正则：中英文有效实词（连续汉字 >= 2 或连续英文字母 >= 2）
CONTENT_WORD_PATTERN: re.Pattern[str] = re.compile(r"[\u4e00-\u9fa5]{2,}|[a-zA-Z]{2,}")

# 预编译正则：选项与答案两端包裹符号与空白清洗正则
WRAPPING_PUNCTUATION_PATTERN: re.Pattern[str] = re.compile(
    r"^[ ()\[\]{}<>、.:：\t\r\n]+|[ ()\[\]{}<>、.:：\t\r\n]+$"
)

# 依据：FR-37 判断题真假双向归一化映射集合
TRUE_BOOLEAN_VALUES: frozenset[str] = frozenset(
    {"TRUE", "T", "1", "YES", "Y", "对", "正确", "是", "V", "√"}
)
FALSE_BOOLEAN_VALUES: frozenset[str] = frozenset(
    {"FALSE", "F", "0", "NO", "N", "错", "错误", "否", "X", "×"}
)

# 依据：FR-38 填空题多候选等价答案与多空切分预编译正则
BLANK_DELIMITER_PATTERN: re.Pattern[str] = re.compile(r"\s*(?:[;；\n]|&&)\s*")
CANDIDATE_DELIMITER_PATTERN: re.Pattern[str] = re.compile(r"\s*(?:\|\|\||\|\||///|\||\n)\s*")

# 中文单数字到阿拉伯数字映射字典
CHINESE_DIGIT_MAPPING: dict[str, str] = {
    "零": "0",
    "一": "1",
    "二": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
}


class QuestionType(enum.StrEnum):
    """题目类型枚举（严格对齐 FR-20 及后端数据模型）。"""

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
    """判题生效方式与渠道枚举。"""

    OFFLINE_RULE = "OFFLINE_RULE"
    PENDING_LLM = "PENDING_LLM"


class TransitionReason(enum.StrEnum):
    """转 AI 判题的 4 类触发原因枚举（严格对齐概要设计说明书第 6.5 节与 FR-40）。"""

    UNCERTAIN_RANGE = "UNCERTAIN_RANGE"
    # 条件 1: 综合匹配度落在不确定过渡区间 (0.45, 0.82)

    NEGATION_INVERSION = "NEGATION_INVERSION"
    # 条件 2: 作答与参考答案在核心分句上存在否定词反转或极性冲突风险

    MULTIPLE_EQUIVALENTS_OR_EMPTY_RUBRIC = "MULTIPLE_EQUIVALENTS_OR_EMPTY_RUBRIC"
    # 条件 3: 题目配置了多个等价表达或评分细则为空，规则无法确定

    ZERO_COVERAGE_HIGH_SIMILARITY = "ZERO_COVERAGE_HIGH_SIMILARITY"
    # 条件 4: 要点覆盖率为 0 但语义相似度高于 0.55，无法严格比对


@dataclass(frozen=True)
class GradingRubricItem:
    """主观题评分细则要点不可变值对象。"""

    point_id: str
    description: str
    weight: float = 1.0
    keywords: tuple[str, ...] = ()
    negation_words: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObjectiveGradingRule:
    """客观题判分规则不可变对象。"""

    case_sensitive: bool = False
    ignore_whitespace: bool = True
    normalize_full_width: bool = True
    normalize_numbers: bool = True
    candidate_delimiters: tuple[str, ...] = ("|", "///", "||", "\n")
    blank_delimiters: tuple[str, ...] = (";", "；", "&&")


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
        """参数边界合法性断言。"""
        if not (0.0 <= self.lower_similarity_threshold < self.upper_similarity_threshold <= 1.0):
            raise ValueError(
                "Must satisfy: 0.0 <= lower_similarity_threshold < "
                "upper_similarity_threshold <= 1.0"
            )
        combined_weight = self.rubric_coverage_weight + self.semantic_similarity_weight
        if not math.isclose(combined_weight, 1.0, abs_tol=1e-5):
            raise ValueError(
                "Sum of rubric_coverage_weight and semantic_similarity_weight must equal 1.0"
            )
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

    score: float
    max_score: float
    is_correct: bool
    is_answered: bool
    requires_llm: bool
    grading_method: GradingMethod
    transition_reason: TransitionReason | None = None
    match_score: float | None = None
    hit_keywords: tuple[str, ...] = ()
    missing_keywords: tuple[str, ...] = ()
    confidence: float = 1.0
    reasoning: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def normalize_objective_token(raw_token: str, question_type: str | QuestionType) -> str:
    """单选题与多选题选项字母规范化。

    单选：大写、去除包裹符号与空格；
    多选：大写、去除多余字符、字母去重并升序排序。

    Args:
        raw_token: 原始作答字符串
        question_type: 题目类型

    Returns:
        str: 规范化后的选项字符串
    """
    if not raw_token or not raw_token.strip():
        return ""

    resolved_type = str(question_type)
    if resolved_type == QuestionType.SINGLE_CHOICE:
        cleaned_token = WRAPPING_PUNCTUATION_PATTERN.sub("", raw_token).upper()
        if len(cleaned_token) == 1 and cleaned_token.isalpha():
            return cleaned_token
        extracted_letters: list[str] = re.findall(r"[a-zA-Z]", raw_token)
        if len(extracted_letters) == 1:
            return str(extracted_letters[0]).upper()
        return "".join(extracted_letters).upper() if extracted_letters else str(cleaned_token)

    extracted_letters = re.findall(r"[a-zA-Z]", raw_token)
    sorted_unique_letters = sorted({letter.upper() for letter in extracted_letters})
    return "".join(sorted_unique_letters)


def normalize_boolean_answer(raw_answer: str) -> bool | None:
    """判断题中英文、数字、符号多语态真假归一化解析。

    Args:
        raw_answer: 用户作答文本

    Returns:
        bool | None: 解析出的布尔真假值，无法识别返回 None
    """
    if not raw_answer or not raw_answer.strip():
        return None
    cleaned_answer = WRAPPING_PUNCTUATION_PATTERN.sub("", raw_answer).upper()
    if cleaned_answer in TRUE_BOOLEAN_VALUES:
        return True
    if cleaned_answer in FALSE_BOOLEAN_VALUES:
        return False
    return None


def normalize_fill_blank_text(text: str) -> str:
    """填空题全角转半角、多余空格消除、大小写统一与数字归一。

    Args:
        text: 待清洗填空文本

    Returns:
        str: 深度清洗后的标准化字符串
    """
    if not text:
        return ""
    # 1. Unicode NFKC 归一化（全角字符与数字转半角）
    normalized_text = unicodedata.normalize("NFKC", text)

    # 2. 中文单数字归一化为阿拉伯数字
    for chinese_digit, arabic_digit in CHINESE_DIGIT_MAPPING.items():
        normalized_text = normalized_text.replace(chinese_digit, arabic_digit)
    normalized_text = re.sub(
        r"(?<![\u4e00-\u9fa5a-zA-Z0-9])十(?![\u4e00-\u9fa5a-zA-Z0-9])", "10", normalized_text
    )

    # 3. 英文小写化与多余空白消除
    normalized_text = normalized_text.lower()
    return re.sub(r"\s+", " ", normalized_text).strip()


def _grade_single_choice(
    user_answer: str,
    reference_answer: str,
    max_score: float,
) -> tuple[bool, float, str]:
    """单选题判分辅助纯函数。"""
    user_token = normalize_objective_token(user_answer, QuestionType.SINGLE_CHOICE)
    reference_token = normalize_objective_token(reference_answer, QuestionType.SINGLE_CHOICE)
    if not user_token or len(user_token) != 1:
        return False, 0.0, "单选题作答格式无效或未作答"
    if user_token == reference_token:
        return True, max_score, "单选题作答正确"
    return False, 0.0, f"单选题作答错误，标准答案为 {reference_token}"


def _grade_multiple_choice(
    user_answer: str,
    reference_answer: str,
    max_score: float,
) -> tuple[bool, float, str]:
    """多选题判分辅助纯函数。"""
    user_token = normalize_objective_token(user_answer, QuestionType.MULTIPLE_CHOICE)
    reference_token = normalize_objective_token(reference_answer, QuestionType.MULTIPLE_CHOICE)
    if not user_token:
        return False, 0.0, "多选题作答格式无效或未作答"
    if user_token == reference_token:
        return True, max_score, "多选题作答正确"
    return False, 0.0, f"多选题作答错误，标准答案为 {reference_token}"


def _grade_true_false(
    user_answer: str,
    reference_answer: str,
    max_score: float,
) -> tuple[bool, float, str]:
    """判断题判分辅助纯函数。"""
    user_boolean = normalize_boolean_answer(user_answer)
    reference_boolean = normalize_boolean_answer(reference_answer)
    if user_boolean is None:
        return False, 0.0, "判断题作答无法解析为有效真假值"
    if reference_boolean is None:
        return False, 0.0, "判断题参考答案格式无效"
    if user_boolean == reference_boolean:
        return True, max_score, "判断题作答正确"
    return False, 0.0, "判断题作答错误"


def _grade_fill_blank(
    user_answer: str,
    reference_answer: str,
    max_score: float,
) -> tuple[bool, float, str]:
    """填空题多空与多候选等价答案判分辅助纯函数。"""
    # 检查是否为多空题（标准答案包含分号或 &&）
    has_multi_blanks = any(delimiter in reference_answer for delimiter in (";", "；", "&&"))

    if has_multi_blanks:
        reference_blanks = [
            blank for blank in BLANK_DELIMITER_PATTERN.split(reference_answer) if blank.strip()
        ]
        user_blanks = [
            blank for blank in BLANK_DELIMITER_PATTERN.split(user_answer) if blank.strip()
        ]
        if len(user_blanks) != len(reference_blanks):
            return (
                False,
                0.0,
                f"填空题作答空数 ({len(user_blanks)}) 与标准答案 ({len(reference_blanks)}) 不一致",
            )

        for user_blank, reference_blank in zip(user_blanks, reference_blanks, strict=True):
            candidate_texts = [
                candidate
                for candidate in CANDIDATE_DELIMITER_PATTERN.split(reference_blank)
                if candidate.strip()
            ]
            user_blank_normalized = normalize_fill_blank_text(user_blank)
            matched = any(
                user_blank_normalized == normalize_fill_blank_text(candidate)
                for candidate in candidate_texts
            )
            if not matched:
                return False, 0.0, "填空题部分空格作答不匹配"
        return True, max_score, "填空题作答正确"

    # 单空题：支持多个候选等价答案 (以 | 或 /// 等分隔)
    candidate_texts = [
        candidate
        for candidate in CANDIDATE_DELIMITER_PATTERN.split(reference_answer)
        if candidate.strip()
    ]
    user_normalized = normalize_fill_blank_text(user_answer)
    matched = any(
        user_normalized == normalize_fill_blank_text(candidate) for candidate in candidate_texts
    )
    if matched:
        return True, max_score, "填空题作答正确"
    return False, 0.0, "填空题作答与标准答案不匹配"


def grade_objective_question(
    question_type: str | QuestionType,
    user_answer: str,
    reference_answer: str,
    max_score: float = 1.0,
    options: Sequence[dict[str, Any]] = (),
) -> tuple[bool, float, str]:
    """客观题秒判流水线，输出确定性判分结果。

    Args:
        question_type: 客观题目类型
        user_answer: 用户作答文本
        reference_answer: 标准参考答案
        max_score: 满分分值
        options: 选项列表（保留备用）

    Returns:
        tuple[bool, float, str]: (is_correct, score, reasoning)
    """
    resolved_type = str(question_type)
    if resolved_type == QuestionType.SINGLE_CHOICE:
        return _grade_single_choice(user_answer, reference_answer, max_score)
    if resolved_type == QuestionType.MULTIPLE_CHOICE:
        return _grade_multiple_choice(user_answer, reference_answer, max_score)
    if resolved_type == QuestionType.TRUE_FALSE:
        return _grade_true_false(user_answer, reference_answer, max_score)
    if resolved_type == QuestionType.FILL_IN_BLANK:
        return _grade_fill_blank(user_answer, reference_answer, max_score)
    return False, 0.0, f"不支持的客观题类型: {question_type}"


def calculate_cosine_similarity(
    vector_a: Sequence[float] | None,
    vector_b: Sequence[float] | None,
) -> float:
    """计算两定长向量的余弦相似度。

    提供零模长与维度不匹配的防除零保护。

    Args:
        vector_a: 第一个向量序列，支持 None
        vector_b: 第二个向量序列，支持 None

    Returns:
        float: 裁剪在 [0.0, 1.0] 区间的余弦相似度值
    """
    if vector_a is None or vector_b is None:
        return 0.0
    if len(vector_a) != len(vector_b) or len(vector_a) == 0:
        return 0.0
    dot_product = 0.0
    norm_a_sq = 0.0
    norm_b_sq = 0.0
    for a_val, b_val in zip(vector_a, vector_b, strict=True):
        dot_product += a_val * b_val
        norm_a_sq += a_val * a_val
        norm_b_sq += b_val * b_val
    if norm_a_sq <= 0.0 or norm_b_sq <= 0.0:
        return 0.0
    cosine = dot_product / (math.sqrt(norm_a_sq) * math.sqrt(norm_b_sq))
    return max(0.0, min(1.0, cosine))


def calculate_text_lexical_similarity(
    user_text: str,
    reference_text: str,
) -> float:
    """计算作答与参考答案的纯文本降级语义相似度。

    结合实词（长度 >= 2）重合率（权重 0.7）与字符 2-gram Jaccard 相似度（权重 0.3）。

    Args:
        user_text: 用户作答文本
        reference_text: 参考答案文本

    Returns:
        float: 裁剪在 [0.0, 1.0] 区间的文本相似度
    """
    if not user_text.strip() or not reference_text.strip():
        return 0.0

    # 1. 连续实词提取与召回率
    reference_words = set(CONTENT_WORD_PATTERN.findall(reference_text.lower()))
    user_words = set(CONTENT_WORD_PATTERN.findall(user_text.lower()))
    if not reference_words:
        word_overlap = 0.0
    else:
        shared_words = reference_words.intersection(user_words)
        word_overlap = len(shared_words) / len(reference_words)

    # 2. 字符 2-gram Jaccard 相似度
    user_compact = "".join(user_text.split()).lower()
    reference_compact = "".join(reference_text.split()).lower()
    if user_compact == reference_compact:
        jaccard_similarity = 1.0
    elif len(user_compact) < 2 or len(reference_compact) < 2:
        jaccard_similarity = 0.0
    else:
        user_grams = {user_compact[index : index + 2] for index in range(len(user_compact) - 1)}
        reference_grams = {
            reference_compact[index : index + 2] for index in range(len(reference_compact) - 1)
        }
        union_grams = user_grams.union(reference_grams)
        intersection_grams = user_grams.intersection(reference_grams)
        jaccard_similarity = len(intersection_grams) / len(union_grams)

    similarity = 0.7 * word_overlap + 0.3 * jaccard_similarity
    return max(0.0, min(1.0, similarity))


def detect_sentence_negation(
    sentence: str,
    negation_words: frozenset[str] = CHINESE_NEGATION_WORDS,
) -> bool:
    """检测单个分句中是否存在关键否定词。

    Args:
        sentence: 待检测分句文本
        negation_words: 否定词集合

    Returns:
        bool: 是否存在否定词
    """
    return any(negation_word in sentence for negation_word in negation_words)


def _extract_reference_keywords(reference_text: str) -> tuple[str, ...]:
    """从参考答案文本中提取用于否定词比对的候选关键词元组。"""
    candidate_keywords: set[str] = set()
    for block in re.findall(r"[\u4e00-\u9fa5]+", reference_text):
        if len(block) >= 2:
            for index in range(len(block) - 1):
                candidate_keywords.add(block[index : index + 2])
    for english_word in re.findall(r"[a-zA-Z]{2,}", reference_text):
        candidate_keywords.add(english_word)
    return tuple(candidate_keywords)


def detect_negation_inversion(
    user_text: str,
    reference_text: str,
    focus_keywords: Sequence[str] = (),
) -> tuple[bool, str | None]:
    """分句级否定词极性反转冲突检测。

    Args:
        user_text: 用户作答文本
        reference_text: 参考答案文本
        focus_keywords: 核心采分关键词序列（若为空则自动从参考答案提取）

    Returns:
        tuple[bool, str | None]: (是否存在否定词极性反转, 冲突诊断信息)
    """
    user_clauses = [clause for clause in SENTENCE_SPLIT_PATTERN.split(user_text) if clause.strip()]
    reference_clauses = [
        clause for clause in SENTENCE_SPLIT_PATTERN.split(reference_text) if clause.strip()
    ]

    keywords_to_check = (
        focus_keywords if focus_keywords else _extract_reference_keywords(reference_text)
    )

    for keyword in keywords_to_check:
        user_clause_matches = [clause for clause in user_clauses if keyword in clause]
        if not user_clause_matches:
            continue

        reference_clause_matches = [clause for clause in reference_clauses if keyword in clause]
        reference_has_negation = any(
            detect_sentence_negation(clause) for clause in reference_clause_matches
        )

        for user_clause in user_clause_matches:
            user_has_negation = detect_sentence_negation(user_clause)
            if user_has_negation and not reference_has_negation:
                return True, f"检测到作答包含与参考答案极性冲突的否定词修饰 (分句: {user_clause})"

    return False, None


# 别名以保持与检查规范契约命名兼容
check_negation_inversion = detect_negation_inversion


def _evaluate_rubric_item(
    item: GradingRubricItem,
    user_text: str,
    user_clauses: list[str],
) -> tuple[bool, list[str], list[str], bool]:
    """单条评分要点关键词命中与分句否定词抑制判定。"""
    item_hit_keywords = [keyword for keyword in item.keywords if keyword in user_text]
    hit_ratio = len(item_hit_keywords) / len(item.keywords)
    if hit_ratio < DEFAULT_KEYWORD_HIT_RATIO_THRESHOLD:
        return False, [], list(item.keywords), False

    combined_negation_words = CHINESE_NEGATION_WORDS.union(item.negation_words)
    clause_negated = any(
        any(keyword in clause for keyword in item_hit_keywords)
        and any(negation_word in clause for negation_word in combined_negation_words)
        for clause in user_clauses
    )

    if clause_negated:
        return False, [], list(item.keywords), True

    missing_keywords = [keyword for keyword in item.keywords if keyword not in item_hit_keywords]
    return True, item_hit_keywords, missing_keywords, False


def evaluate_subjective_rubric(
    user_text: str,
    rubric_items: Sequence[GradingRubricItem],
) -> tuple[float, tuple[str, ...], tuple[str, ...], bool]:
    """评分细则逐条评估：关键词命中率、分句否定词抑制、输出命中与遗漏要点。

    Args:
        user_text: 用户作答文本
        rubric_items: 评分细则要点序列

    Returns:
        tuple[float, tuple[str, ...], tuple[str, ...], bool]:
            (point_coverage, hit_keywords, missing_keywords, has_negation_inversion)
    """
    if not rubric_items:
        return 0.0, (), (), False

    user_clauses = [clause for clause in SENTENCE_SPLIT_PATTERN.split(user_text) if clause.strip()]
    total_weight = sum(item.weight for item in rubric_items)
    if total_weight <= 0.0:
        total_weight = float(len(rubric_items))

    hit_weight = 0.0
    hit_keywords_list: list[str] = []
    missing_keywords_list: list[str] = []
    any_negation_inversion = False

    for item in rubric_items:
        if not item.keywords:
            continue

        is_hit, item_hits, item_missing, is_negated = _evaluate_rubric_item(
            item, user_text, user_clauses
        )
        if is_negated:
            any_negation_inversion = True
        if is_hit:
            hit_weight += item.weight
            hit_keywords_list.extend(item_hits)
        missing_keywords_list.extend(item_missing)

    point_coverage = max(0.0, min(1.0, hit_weight / total_weight))
    return (
        point_coverage,
        tuple(hit_keywords_list),
        tuple(missing_keywords_list),
        any_negation_inversion,
    )


def arbitrate_llm_transition(
    match_score: float,
    point_coverage: float,
    semantic_similarity: float,
    has_negation_inversion: bool,
    has_multiple_equivalents: bool,
    rubric_empty: bool,
    config: GradingConfig,
) -> tuple[bool, TransitionReason | None]:
    """4 类转 AI 决策判定核心仲裁函数。

    严格执行以下优先级仲裁：
    1. 优先级 1 (条件 2): 否定词反转风险 -> NEGATION_INVERSION
    2. 优先级 2 (条件 3): 多等价表达或细则缺失 -> MULTIPLE_EQUIVALENTS_OR_EMPTY_RUBRIC
    3. 优先级 3 (条件 4): 要点覆盖率为 0 且相似度 > 0.55 -> ZERO_COVERAGE_HIGH_SIMILARITY
    4. 优先级 4 (条件 1): 综合匹配度落在开区间 (0.45, 0.82) -> UNCERTAIN_RANGE

    Args:
        match_score: 综合匹配得分
        point_coverage: 要点覆盖率
        semantic_similarity: 语义相似度
        has_negation_inversion: 是否检测到否定词反转
        has_multiple_equivalents: 是否配置多个等价表达
        rubric_empty: 评分细则是否为空
        config: 判题配置

    Returns:
        tuple[bool, TransitionReason | None]: (是否需要转 AI, 转 AI 原因枚举)
    """
    # 优先级 1: 否定词反转风险
    if has_negation_inversion:
        return True, TransitionReason.NEGATION_INVERSION

    # 优先级 2: 多等价表达或评分细则缺失
    if has_multiple_equivalents or rubric_empty:
        return True, TransitionReason.MULTIPLE_EQUIVALENTS_OR_EMPTY_RUBRIC

    # 优先级 3: 实词要点缺失但相似度较高
    if (
        point_coverage == 0.0
        and semantic_similarity > config.zero_coverage_high_similarity_threshold
    ):
        return True, TransitionReason.ZERO_COVERAGE_HIGH_SIMILARITY

    # 优先级 4: 不确定过渡区间 (0.45, 0.82)
    if config.lower_similarity_threshold < match_score < config.upper_similarity_threshold:
        return True, TransitionReason.UNCERTAIN_RANGE

    return False, None


def _prepare_truncated_answer(
    user_answer: str,
    max_length: int,
) -> tuple[str, dict[str, Any]]:
    """主观题超长作答防御截断处理。"""
    original_length = len(user_answer)
    if original_length > max_length:
        return user_answer[:max_length], {"is_truncated": True, "original_length": original_length}
    return user_answer, {}


def _parse_rubric_items(
    grading_rubric: Sequence[GradingRubricItem | dict[str, Any]],
) -> list[GradingRubricItem]:
    """主观题评分细则规范化解析。"""
    normalized_items: list[GradingRubricItem] = []
    for rubric_entry in grading_rubric:
        if isinstance(rubric_entry, GradingRubricItem):
            normalized_items.append(rubric_entry)
        else:
            normalized_items.append(
                GradingRubricItem(
                    point_id=str(rubric_entry.get("point_id", "")),
                    description=str(rubric_entry.get("description", "")),
                    weight=float(rubric_entry.get("weight", 1.0)),
                    keywords=tuple(rubric_entry.get("keywords", ())),
                    negation_words=tuple(rubric_entry.get("negation_words", ())),
                )
            )
    return normalized_items


def _calculate_semantic_similarity(
    user_text: str,
    reference_text: str,
    user_embedding: Sequence[float] | None,
    reference_embedding: Sequence[float] | None,
) -> float:
    """计算主观题语义相似度（优先向量余弦，缺向量降级为纯文本融合）。"""
    has_valid_embeddings = (
        user_embedding is not None
        and reference_embedding is not None
        and len(user_embedding) == len(reference_embedding)
        and len(user_embedding) > 0
    )
    if has_valid_embeddings:
        return calculate_cosine_similarity(user_embedding, reference_embedding)
    return calculate_text_lexical_similarity(user_text, reference_text)


def round_half_up(value: float, unit: float = SCORE_ROUNDING_UNIT) -> float:
    """确定性 half-up（四舍五入）分粒度舍入纯函数。

    基于 ``decimal.Decimal`` 与 ``ROUND_HALF_UP``，避免 Python 内置 ``round``
    的银行家舍入（round-half-to-even）在 ``k.5`` 偶数边界处向下舍入导致少给分。
    例如 ``round_half_up(9.25, 0.5) == 9.5``，而 ``round(9.25 / 0.5) * 0.5 == 9.0``。

    Args:
        value: 待舍入的原始分值。
        unit: 舍入粒度（默认 0.5 分，必须为正）。

    Returns:
        float: 舍入到 unit 整数倍的分值；unit <= 0 时原样返回 value。
    """
    if unit <= 0:
        return value
    value_decimal = Decimal(str(value))
    unit_decimal = Decimal(str(unit))
    rounded_units = (value_decimal / unit_decimal).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(rounded_units * unit_decimal)


def _build_subjective_offline_result(
    match_score: float,
    max_score: float,
    config: GradingConfig,
    hit_keywords: tuple[str, ...],
    missing_keywords: tuple[str, ...],
    details: dict[str, Any],
) -> GradingResult:
    """组装主观题离线判对或离线判错的确定性报告。"""
    if match_score >= config.upper_similarity_threshold:
        raw_score = max_score * match_score
        unit = config.score_rounding_unit
        final_score = min(max_score, max(0.0, round(round_half_up(raw_score, unit), 4)))
        return GradingResult(
            score=final_score,
            max_score=max_score,
            is_correct=True,
            is_answered=True,
            requires_llm=False,
            grading_method=GradingMethod.OFFLINE_RULE,
            match_score=round(match_score, 4),
            hit_keywords=hit_keywords,
            missing_keywords=missing_keywords,
            confidence=0.9,
            reasoning="作答综合匹配度达到离线判对阈值",
            details=details,
        )

    return GradingResult(
        score=0.0,
        max_score=max_score,
        is_correct=False,
        is_answered=True,
        requires_llm=False,
        grading_method=GradingMethod.OFFLINE_RULE,
        match_score=round(match_score, 4),
        hit_keywords=hit_keywords,
        missing_keywords=missing_keywords,
        confidence=0.9,
        reasoning="作答综合匹配度低于离线判错阈值",
        details=details,
    )


def _handle_subjective_grading(
    user_answer: str,
    reference_answer: str,
    max_score: float,
    grading_rubric: Sequence[GradingRubricItem | dict[str, Any]],
    user_embedding: Sequence[float] | None,
    reference_embedding: Sequence[float] | None,
    has_multiple_equivalents: bool,
    config: GradingConfig,
) -> GradingResult:
    """主观题双阈值与转 AI 判定流水线。"""
    processed_user_answer, details = _prepare_truncated_answer(
        user_answer, config.max_answer_length
    )

    # 完全一致快速通道
    if processed_user_answer.strip() == reference_answer.strip():
        return GradingResult(
            score=max_score,
            max_score=max_score,
            is_correct=True,
            is_answered=True,
            requires_llm=False,
            grading_method=GradingMethod.OFFLINE_RULE,
            match_score=1.0,
            confidence=1.0,
            reasoning="作答与参考答案完全一致，直接判定满分",
            details=details,
        )

    # 评分细则要点评估
    normalized_rubric_items = _parse_rubric_items(grading_rubric)
    rubric_empty = len(normalized_rubric_items) == 0
    point_coverage, hit_keywords, missing_keywords, rubric_negation = evaluate_subjective_rubric(
        processed_user_answer, normalized_rubric_items
    )

    # 全局与分句否定词反转检测
    inversion_detected, _ = detect_negation_inversion(
        processed_user_answer,
        reference_answer,
        focus_keywords=hit_keywords if hit_keywords else (),
    )
    has_negation_inversion = rubric_negation or inversion_detected

    # 语义相似度与匹配度合成
    semantic_similarity = _calculate_semantic_similarity(
        processed_user_answer, reference_answer, user_embedding, reference_embedding
    )
    combined_score = (
        point_coverage * config.rubric_coverage_weight
        + semantic_similarity * config.semantic_similarity_weight
    )
    match_score = max(0.0, min(1.0, combined_score))

    # 4 类转 AI 决策判定
    requires_llm, transition_reason = arbitrate_llm_transition(
        match_score=match_score,
        point_coverage=point_coverage,
        semantic_similarity=semantic_similarity,
        has_negation_inversion=has_negation_inversion,
        has_multiple_equivalents=has_multiple_equivalents,
        rubric_empty=rubric_empty,
        config=config,
    )

    if requires_llm:
        reason_text = transition_reason.value if transition_reason else "待大模型判定"
        return GradingResult(
            score=0.0,
            max_score=max_score,
            is_correct=False,
            is_answered=True,
            requires_llm=True,
            grading_method=GradingMethod.PENDING_LLM,
            transition_reason=transition_reason,
            match_score=round(match_score, 4),
            hit_keywords=hit_keywords,
            missing_keywords=missing_keywords,
            confidence=0.5,
            reasoning=f"触发转 AI 判题条件: {reason_text}",
            details=details,
        )

    return _build_subjective_offline_result(
        match_score=match_score,
        max_score=max_score,
        config=config,
        hit_keywords=hit_keywords,
        missing_keywords=missing_keywords,
        details=details,
    )


def _resolve_question_type(question_type: str | QuestionType) -> QuestionType:
    """校验并解析题目类型。"""
    if isinstance(question_type, QuestionType):
        return question_type
    if isinstance(question_type, str):
        try:
            return QuestionType(question_type)
        except ValueError as error:
            raise ValueError(f"Invalid question_type: {question_type}") from error
    raise ValueError(f"Invalid question_type: {question_type}")


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
        question_type: 题目类型（QuestionType 枚举或合法题型字符串）
        user_answer: 用户作答原文
        reference_answer: 标准参考答案原文
        max_score: 该题目满分分值（必须 > 0.0）
        options: 客观选择题选项列表
        grading_rubric: 主观题评分细则要点序列
        user_embedding: 用户答案定长语义向量（可选）
        reference_embedding: 参考答案定长语义向量（可选）
        has_multiple_equivalents: 是否标记了存在多个等价表达
        config: 判题算法与阈值配置对象，缺省使用默认配置

    Returns:
        GradingResult: 包含得分、对错判定、转 AI 标记与明细的不可变结果对象

    Raises:
        ValueError: 当 max_score <= 0 或 question_type 非法时抛出
    """
    if max_score <= 0.0:
        raise ValueError("max_score must be positive")

    resolved_question_type = _resolve_question_type(question_type)
    resolved_config = config if config is not None else GradingConfig()

    # 未作答前置短路
    if not user_answer or not user_answer.strip():
        return GradingResult(
            score=0.0,
            max_score=max_score,
            is_correct=False,
            is_answered=False,
            requires_llm=False,
            grading_method=GradingMethod.OFFLINE_RULE,
            match_score=0.0,
            confidence=1.0,
            reasoning="用户未作答或作答内容为空",
        )

    # 客观题离线秒判流水线
    if resolved_question_type in OBJECTIVE_QUESTION_TYPES:
        is_correct, score, reasoning = grade_objective_question(
            resolved_question_type,
            user_answer,
            reference_answer,
            max_score=max_score,
            options=options,
        )
        return GradingResult(
            score=score,
            max_score=max_score,
            is_correct=is_correct,
            is_answered=True,
            requires_llm=False,
            grading_method=GradingMethod.OFFLINE_RULE,
            match_score=1.0 if is_correct else 0.0,
            confidence=1.0,
            reasoning=reasoning,
        )

    # 主观题双阈值与转 AI 判定流水线
    return _handle_subjective_grading(
        user_answer=user_answer,
        reference_answer=reference_answer,
        max_score=max_score,
        grading_rubric=grading_rubric,
        user_embedding=user_embedding,
        reference_embedding=reference_embedding,
        has_multiple_equivalents=has_multiple_equivalents,
        config=resolved_config,
    )
