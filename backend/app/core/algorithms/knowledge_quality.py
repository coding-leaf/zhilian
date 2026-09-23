"""Knowledge point quality gate algorithm pure functional kernel.

Implements knowledge point quality verification based on quantity range,
hierarchy depth, naming readability, and critical chapter coverage.
Strictly adheres to pure functional kernel constraints
(zero external I/O, zero network/ORM dependencies).
"""

import enum
import re
from collections.abc import Sequence, Set
from dataclasses import dataclass, field
from typing import Any

# ==============================================================================
# 知识点质检门禁核心常量与决策基准
# 严格遵循《概要设计说明书》第 3.4/6.3 节与《软件需求规格说明书》FR-16~18、NFR-22
# ==============================================================================

# 依据：概要设计说明书第 3.4/6.3 节，每 5000 字有效文本对应 1 至 8 个知识点
# 密度下限：5000 / 8 = 625 字符/知识点。字符/知识点 < 625 意味着 5000 字抽取超过 8 个，判为过度拆分
MIN_EFFECTIVE_CHARS_PER_KP: int = 625

# 依据：概要设计说明书第 3.4/6.3 节，每 5000 字有效文本对应 1 至 8 个知识点
# 密度上限：5000 / 1 = 5000 字符/知识点。字符/知识点 > 5000 意味着 5000 字不足 1 个，判为过度粗略
MAX_EFFECTIVE_CHARS_PER_KP: int = 5000

# 依据：概要设计说明书第 3.4/6.3 节，知识片段总数少于 20 个时要求知识点数量不少于 3 个
# 短资料内容集中，必须至少形成三元微型知识结构，防止模型偷懒仅抽取单一宽泛概念
MIN_KP_COUNT_SMALL_DOC: int = 3

# 依据：概要设计说明书第 3.4/6.3 节，单份资料抽取知识点绝对上限为 200 个
# 超过 200 个不仅导致树形可视化严重卡顿，且必然破坏后续考纲聚焦，直接判为过度拆分
MAX_KP_COUNT_ABSOLUTE: int = 200

# 依据：概要设计说明书第 3.4/6.3 节与 FR-16，知识点最大层级深度必须在 2 至 5 之间
# 深度为 1 判为“平铺 (FLAT)”；深度 > 5 判为“嵌套过深 (TOO_DEEP)”
MIN_HIERARCHY_DEPTH: int = 2
MAX_HIERARCHY_DEPTH: int = 5

# 依据：概要设计说明书第 3.4/6.3 节，第 2 层节点数占总数的比例上限为 60% (0.60)
# 超过 60% 表明模型未建立合理的纵深细分体系，产生“伞状横向拥挤”，判为“层级退化 (LAYER_DEGENERATE)”
MAX_LEVEL_2_RATIO: float = 0.60

# 依据：概要设计说明书第 3.4/6.3 节，知识点名称长度字符数区间为 2 至 30 字符
# 单字多为无意义缩略或标点，超过 30 字符多为模型将正文解释误作为标题输出
MIN_NAME_LENGTH: int = 2
MAX_NAME_LENGTH: int = 30

# 依据：概要设计说明书第 3.4/6.3 节，章节片段占比不低于 5% (0.05) 的章节定义为关键章节
# 边界约定：片段占比恰好等于 5.0% 同样纳入关键章节计算
CRITICAL_CHAPTER_SNIPPET_RATIO: float = 0.05

# 依据：概要设计说明书第 3.4/6.3 节，关键章节知识点覆盖率下限为 80% (0.80)
# 必须保证核心章节不被大模型遗漏，覆盖率低于 80% 判为不合格
MIN_CRITICAL_CHAPTER_COVERAGE: float = 0.80

# 依据：概要设计说明书第 3.4/6.3 节与 FR-17，质检不通过时自动重抽上限为 2 次
# 达到 2 次重抽仍不通过时，触发熔断并降级标记 is_low_confidence=True (FR-18/FR-53)
MAX_RE_EXTRACT_ATTEMPTS: int = 2

# 依据：概要设计说明书第 3.4/6.3 节，模板占位词黑名单表
# 命中占位词表明大模型产生模板化灌水输出，命名可读性一票否决
DEFAULT_PLACEHOLDER_WORDS: frozenset[str] = frozenset(
    {
        "知识点",
        "内容一",
        "其他",
        "待补充",
        "未命名",
        "章节一",
        "测试",
    }
)

# 依据：概要设计说明书第 3.4/6.3 节，截断标记预编译正则表达式
# 包含中文/英文省略号结尾（...、…）或未闭合的前括号结尾（(、[、【、(）
TRUNCATION_PATTERN: re.Pattern[str] = re.compile(r"(\.{3,}|…+|[（(\[【]\s*$)")


class CheckItemCode(enum.StrEnum):
    """四项质检门禁检查项枚举。"""

    QUANTITY_RANGE = "quantity_range"  # 知识点数量区间
    HIERARCHY_DEPTH = "hierarchy_depth"  # 层级深度与结构
    NAMING_READABILITY = "naming_readability"  # 命名可读性与占位词
    CHAPTER_COVERAGE = "chapter_coverage"  # 关键章节覆盖率


@dataclass(frozen=True)
class CandidateKnowledgePoint:
    """输入的单个候选知识点（轻量不可变领域对象）。"""

    name: str  # 知识点名称
    level: int = 1  # 层级深度（根节点为 1，支持 1~5）
    chapter_title: str = ""  # 归属章节标题（若有）
    snippet_ids: tuple[str, ...] = ()  # 关联来源片段唯一标识元组
    description: str = ""  # 知识点简述（可选）


@dataclass(frozen=True)
class ChapterSnippetStat:
    """章节知识片段分布统计。"""

    chapter_title: str  # 章节标题
    snippet_count: int  # 该章节包含的切片数量
    snippet_ratio: float  # 切片数占资料切片总数的比例 (0.0 ~ 1.0)


@dataclass(frozen=True)
class ExtractionContext:
    """知识点抽取上下文环境与统计量。"""

    total_snippets: int  # 资料切片总数
    effective_chars: int  # 资料有效清洗字符总数
    chapter_stats: Sequence[ChapterSnippetStat] = ()  # 章节切片分布统计
    re_extract_count: int = 0  # 当前重抽计数（首次抽取为 0，上限 2）


@dataclass(frozen=True)
class KnowledgeQualityConfig:
    """知识点质检门禁可调参数配置。"""

    min_effective_chars_per_kp: int = MIN_EFFECTIVE_CHARS_PER_KP
    max_effective_chars_per_kp: int = MAX_EFFECTIVE_CHARS_PER_KP
    min_kp_count_small_doc: int = MIN_KP_COUNT_SMALL_DOC
    max_kp_count_absolute: int = MAX_KP_COUNT_ABSOLUTE
    min_hierarchy_depth: int = MIN_HIERARCHY_DEPTH
    max_hierarchy_depth: int = MAX_HIERARCHY_DEPTH
    max_level_2_ratio: float = MAX_LEVEL_2_RATIO
    min_name_length: int = MIN_NAME_LENGTH
    max_name_length: int = MAX_NAME_LENGTH
    critical_chapter_snippet_ratio: float = CRITICAL_CHAPTER_SNIPPET_RATIO
    min_critical_chapter_coverage: float = MIN_CRITICAL_CHAPTER_COVERAGE
    max_re_extract_attempts: int = MAX_RE_EXTRACT_ATTEMPTS
    placeholder_words: frozenset[str] = DEFAULT_PLACEHOLDER_WORDS

    def __post_init__(self) -> None:
        """校验配置参数合法性边界。

        Raises:
            ValueError: 当配置参数不在合理合法范围内时抛出。
        """
        if self.min_effective_chars_per_kp <= 0 or self.max_effective_chars_per_kp <= 0:
            raise ValueError("effective chars per KP bounds must be positive")
        if self.min_effective_chars_per_kp > self.max_effective_chars_per_kp:
            raise ValueError("min_effective_chars_per_kp cannot exceed max_effective_chars_per_kp")
        if (
            self.min_kp_count_small_doc < 0
            or self.max_kp_count_absolute < self.min_kp_count_small_doc
        ):
            raise ValueError("invalid KP count constraints")
        if not (1 <= self.min_hierarchy_depth <= self.max_hierarchy_depth):
            raise ValueError("invalid hierarchy depth range")
        if not (0.0 <= self.max_level_2_ratio <= 1.0):
            raise ValueError("max_level_2_ratio must be between 0.0 and 1.0")
        if not (1 <= self.min_name_length <= self.max_name_length):
            raise ValueError("invalid name length constraints")
        if not (0.0 <= self.critical_chapter_snippet_ratio <= 1.0):
            raise ValueError("critical_chapter_snippet_ratio must be between 0.0 and 1.0")
        if not (0.0 <= self.min_critical_chapter_coverage <= 1.0):
            raise ValueError("min_critical_chapter_coverage must be between 0.0 and 1.0")
        if self.max_re_extract_attempts < 0:
            raise ValueError("max_re_extract_attempts must be non-negative")


@dataclass(frozen=True)
class CheckResult:
    """单项检查结果评估（不可变值对象）。"""

    item_code: CheckItemCode  # 质检项枚举代码
    is_passed: bool  # 单项是否通过
    score: float  # 得分（1.0 为通过，0.0 为未通过）
    reason: str | None = None  # 未通过具体原因（包含量化指标）
    suggestion: str | None = None  # 针对性整改建议
    details: dict[str, Any] = field(default_factory=dict)  # 结构化量化指标


@dataclass(frozen=True)
class KnowledgeQualityReport:
    """知识点质检门禁统一产出报告。"""

    is_qualified: bool  # 整体是否达到门禁要求（一票否决）
    is_skipped: bool  # 是否因极端边界（如无内容）跳过质检
    is_low_confidence: bool  # 是否达重抽上限触发低可信度降级标记
    re_extract_count: int  # 当前已重抽次数
    check_results: tuple[CheckResult, ...]  # 四项检查明细元组
    unqualified_reasons: tuple[str, ...]  # 全部未通过原因列表
    prompt_feedback: str  # 指导下一次抽取或记录的重抽提示词段落
    summary: str  # 综合评价摘要


def check_quantity_range(
    count: int,
    effective_chars: int,
    total_snippets: int,
    config: KnowledgeQualityConfig,
) -> CheckResult:
    """校验候选知识点数量是否符合体量区间。

    规则：
    1. 候选数量 count == 0: 立即判不合格 (score=0.0)，不进入比值计算；
    2. count > config.max_kp_count_absolute (200): 判为过度拆分；
    3. total_snippets < 20: 判定是否达到保底数 min_kp_count_small_doc (3)；
       若达到则直接通过（放宽密度限制以规避短资料策略冲突）；未达到则判不合格；
    4. 针对正常资料 (total_snippets >= 20)，按
       [min_effective_chars_per_kp, max_effective_chars_per_kp]
       校验密度：effective_chars / count。若过密判过度拆分，过疏判过度粗略；否则通过。

    Args:
        count: 候选知识点数量。
        effective_chars: 资料有效清洗字符总数。
        total_snippets: 资料知识切片总数。
        config: 知识点质检配置对象。

    Returns:
        CheckResult: 数量区间检查结果。
    """
    if count == 0:
        return CheckResult(
            item_code=CheckItemCode.QUANTITY_RANGE,
            is_passed=False,
            score=0.0,
            reason="候选知识点数量为 0，未抽取到有效内容",
            suggestion="请检查资料内容完整性并重新组织提示词进行抽取",
            details={"count": 0},
        )

    if count > config.max_kp_count_absolute:
        return CheckResult(
            item_code=CheckItemCode.QUANTITY_RANGE,
            is_passed=False,
            score=0.0,
            reason=(
                f"知识点数量为 {count} 个，超出单份资料绝对上限 "
                f"{config.max_kp_count_absolute} 个（过度拆分）"
            ),
            suggestion="知识点颗粒度过细，请合并次要细节，聚焦核心考点",
            details={"count": count, "max_allowed": config.max_kp_count_absolute},
        )

    if total_snippets < 20:
        if count < config.min_kp_count_small_doc:
            return CheckResult(
                item_code=CheckItemCode.QUANTITY_RANGE,
                is_passed=False,
                score=0.0,
                reason=(
                    f"短资料知识点数量为 {count} 个，低于保底要求 "
                    f"{config.min_kp_count_small_doc} 个"
                ),
                suggestion="短资料需至少形成基本三元结构，请补充关键概念",
                details={
                    "count": count,
                    "total_snippets": total_snippets,
                    "min_required": config.min_kp_count_small_doc,
                },
            )
        return CheckResult(
            item_code=CheckItemCode.QUANTITY_RANGE,
            is_passed=True,
            score=1.0,
            details={"count": count, "total_snippets": total_snippets, "is_small_doc": True},
        )

    chars_per_kp = effective_chars / count
    if chars_per_kp < config.min_effective_chars_per_kp:
        return CheckResult(
            item_code=CheckItemCode.QUANTITY_RANGE,
            is_passed=False,
            score=0.0,
            reason=(
                f"知识点抽取密度过高（平均 {chars_per_kp:.1f} 字符/个），"
                f"低于下限 {config.min_effective_chars_per_kp} 字符/个（过度拆分）"
            ),
            suggestion="抽取知识点过多，请提高聚合度，合并同类知识点",
            details={
                "count": count,
                "effective_chars": effective_chars,
                "chars_per_kp": chars_per_kp,
            },
        )

    if chars_per_kp > config.max_effective_chars_per_kp:
        return CheckResult(
            item_code=CheckItemCode.QUANTITY_RANGE,
            is_passed=False,
            score=0.0,
            reason=(
                f"知识点抽取密度过低（平均 {chars_per_kp:.1f} 字符/个），"
                f"高于上限 {config.max_effective_chars_per_kp} 字符/个（过度粗略）"
            ),
            suggestion="知识点抽取过于粗略，请更深入细化各章节考点",
            details={
                "count": count,
                "effective_chars": effective_chars,
                "chars_per_kp": chars_per_kp,
            },
        )

    return CheckResult(
        item_code=CheckItemCode.QUANTITY_RANGE,
        is_passed=True,
        score=1.0,
        details={"count": count, "effective_chars": effective_chars, "chars_per_kp": chars_per_kp},
    )


def check_hierarchy_depth(
    levels: Sequence[int],
    config: KnowledgeQualityConfig,
) -> CheckResult:
    """校验知识点层级深度与节点分布。

    规则：
    1. levels 为空或全为 0: 按平铺 (FLAT, depth=1) 处理，判不合格；
    2. 最大深度 < 2: 判为平铺 (FLAT)；
    3. 最大深度 > 5: 判为嵌套过深 (TOO_DEEP)；
    4. 第 2 层节点数占比 > 60%: 判为层级退化 (LAYER_DEGENERATE)；
    5. 否则通过。

    Args:
        levels: 各候选知识点的层级深度列表。
        config: 知识点质检配置对象。

    Returns:
        CheckResult: 层级深度检查结果。
    """
    if not levels or all(level <= 0 for level in levels):
        return CheckResult(
            item_code=CheckItemCode.HIERARCHY_DEPTH,
            is_passed=False,
            score=0.0,
            reason="知识点层级全空或全为0，结构退化为平铺",
            suggestion="请划分章、节、考点层级，建立具有纵深的树形知识体系",
            details={"max_depth": 1, "is_flat": True},
        )

    normalized_levels = [level if level > 0 else 1 for level in levels]
    max_depth = max(normalized_levels)

    if max_depth < config.min_hierarchy_depth:
        return CheckResult(
            item_code=CheckItemCode.HIERARCHY_DEPTH,
            is_passed=False,
            score=0.0,
            reason=(
                f"知识点最大层级深度为 {max_depth} 级，缺乏层级划分"
                f"（要求 {config.min_hierarchy_depth}~{config.max_hierarchy_depth} 级）"
            ),
            suggestion="当前知识点完全平铺，请组织至少2级以上的层级归属关系",
            details={"max_depth": max_depth, "issue": "flat"},
        )

    if max_depth > config.max_hierarchy_depth:
        return CheckResult(
            item_code=CheckItemCode.HIERARCHY_DEPTH,
            is_passed=False,
            score=0.0,
            reason=(
                f"知识点最大层级深度为 {max_depth} 级，嵌套过深"
                f"（要求 {config.min_hierarchy_depth}~{config.max_hierarchy_depth} 级）"
            ),
            suggestion="树形层级嵌套过深，建议裁剪至5级以内",
            details={"max_depth": max_depth, "issue": "too_deep"},
        )

    level_2_count = sum(1 for level in normalized_levels if level == 2)
    level_2_ratio = level_2_count / len(normalized_levels)

    if level_2_ratio > config.max_level_2_ratio:
        return CheckResult(
            item_code=CheckItemCode.HIERARCHY_DEPTH,
            is_passed=False,
            score=0.0,
            reason=(
                f"第2层节点占比为 {level_2_ratio:.1%}，超过上限 "
                f"{config.max_level_2_ratio:.0%}（层级退化）"
            ),
            suggestion="第2层知识点横向过度堆积，请进一步下钻拆分或提升抽象度",
            details={
                "max_depth": max_depth,
                "level_2_ratio": level_2_ratio,
                "issue": "layer_degenerate",
            },
        )

    return CheckResult(
        item_code=CheckItemCode.HIERARCHY_DEPTH,
        is_passed=True,
        score=1.0,
        details={"max_depth": max_depth, "level_2_ratio": level_2_ratio},
    )


def _inspect_name_issues(name: str, config: KnowledgeQualityConfig) -> list[str]:
    """检查单个知识点名称的规范缺陷。

    Args:
        name: 待检查知识点名称。
        config: 知识点质检配置对象。

    Returns:
        list[str]: 发现的缺陷描述列表。
    """
    issues: list[str] = []
    stripped = name.strip()
    length = len(stripped)
    if length < config.min_name_length or length > config.max_name_length:
        issues.append(
            f"长度 {length} 字符超出规范区间 {config.min_name_length}~{config.max_name_length}"
        )
    if any(placeholder in stripped for placeholder in config.placeholder_words):
        issues.append("包含占位词黑名单")
    if TRUNCATION_PATTERN.search(stripped):
        issues.append("包含省略号或未闭合括号截断")
    return issues


def check_naming_readability(
    names: Sequence[str],
    config: KnowledgeQualityConfig,
) -> CheckResult:
    """校验知识点名称长度、占位词与截断痕迹。

    规则：
    1. names 为空: 判不合格；
    2. 针对每个名称校验：
       a. 长度是否在 [min_name_length, max_name_length] (2~30) 之间；
       b. 是否包含模板占位词 (如“知识点”、“内容一”等)；
       c. 是否命中省略号或未闭合括号截断正则；
    3. 收集违规条目，若违规数量 > 0 则整体判不合格，并输出首批违规样本。

    Args:
        names: 候选知识点名称序列。
        config: 知识点质检配置对象。

    Returns:
        CheckResult: 命名可读性检查结果。
    """
    if not names:
        return CheckResult(
            item_code=CheckItemCode.NAMING_READABILITY,
            is_passed=False,
            score=0.0,
            reason="知识点名称列表为空",
            suggestion="未提供任何知识点名称，请检查抽取输出",
            details={"names_count": 0},
        )

    all_violations: list[str] = []
    for name in names:
        issues = _inspect_name_issues(name, config)
        if issues:
            all_violations.append(f"「{name}」({', '.join(issues)})")

    if all_violations:
        return CheckResult(
            item_code=CheckItemCode.NAMING_READABILITY,
            is_passed=False,
            score=0.0,
            reason=(
                f"发现 {len(all_violations)} 处知识点名称不合规: {'; '.join(all_violations[:3])}"
            ),
            suggestion="知识点名称应在2~30字符内，避免模板占位词与末尾截断痕迹",
            details={"violations_count": len(all_violations), "samples": all_violations[:5]},
        )

    return CheckResult(
        item_code=CheckItemCode.NAMING_READABILITY,
        is_passed=True,
        score=1.0,
        details={"total_checked": len(names)},
    )


def check_chapter_coverage(
    covered_chapters: Set[str],
    chapter_stats: Sequence[ChapterSnippetStat],
    config: KnowledgeQualityConfig,
) -> CheckResult:
    """校验资料关键章节覆盖率。

    规则：
    1. 提取 snippet_ratio >= config.critical_chapter_snippet_ratio (0.05) 的章节作为关键章节；
    2. 若无关键章节（无分章或单一整体）: 视为 100% 覆盖通过；
    3. 统计关键章节中被 covered_chapters 命中的比例；
    4. 若 coverage_ratio < config.min_critical_chapter_coverage (0.80):
       判为覆盖率不足，输出遗漏章节；否则通过。

    Args:
        covered_chapters: 候选知识点已覆盖的章节名称集合。
        chapter_stats: 资料章节切片统计分布。
        config: 知识点质检配置对象。

    Returns:
        CheckResult: 章节覆盖率检查结果。
    """
    critical_chapters = [
        stat.chapter_title.strip()
        for stat in chapter_stats
        if stat.snippet_ratio >= config.critical_chapter_snippet_ratio
    ]

    if not critical_chapters:
        return CheckResult(
            item_code=CheckItemCode.CHAPTER_COVERAGE,
            is_passed=True,
            score=1.0,
            details={"critical_chapters_count": 0, "coverage_ratio": 1.0},
        )

    covered_critical = [chapter for chapter in critical_chapters if chapter in covered_chapters]
    coverage_ratio = len(covered_critical) / len(critical_chapters)

    if coverage_ratio < config.min_critical_chapter_coverage:
        missing = [chapter for chapter in critical_chapters if chapter not in covered_chapters]
        return CheckResult(
            item_code=CheckItemCode.CHAPTER_COVERAGE,
            is_passed=False,
            score=0.0,
            reason=(
                f"关键章节覆盖率为 {coverage_ratio:.1%}，低于门禁要求 "
                f"{config.min_critical_chapter_coverage:.0%}，遗漏章节: {', '.join(missing[:3])}"
            ),
            suggestion="请针对遗漏章节重点补充抽取候选知识点",
            details={
                "critical_chapters": critical_chapters,
                "covered_critical": covered_critical,
                "missing_chapters": missing,
                "coverage_ratio": coverage_ratio,
            },
        )

    return CheckResult(
        item_code=CheckItemCode.CHAPTER_COVERAGE,
        is_passed=True,
        score=1.0,
        details={
            "critical_chapters": critical_chapters,
            "covered_critical": covered_critical,
            "coverage_ratio": coverage_ratio,
        },
    )


def generate_prompt_feedback(
    results: Sequence[CheckResult],
    re_extract_count: int,
) -> str:
    """根据未通过原因与当前重抽轮次，自适应生成提示词增强补充文本。

    规则：
    1. 若全部通过，返回空字符串；
    2. 轮次 0: 拼接具体未通过原因，提示降低单批片段数至 20；
    3. 轮次 1: 追加硬性数量区间与命名规范约束（4~16 字符，无编号）；
    4. 轮次 >= 2: 输出最终降级说明文案。

    Args:
        results: 各项检查结果序列。
        re_extract_count: 当前已重抽次数。

    Returns:
        str: 生成的自适应提示词反馈文本。
    """
    unpassed = [r for r in results if not r.is_passed]
    if not unpassed:
        return ""

    if re_extract_count >= 2:
        return (
            "资料知识结构经多次抽取仍未达到质量门禁标准，已采用本次结果降级处理，"
            "标记低可信度并在报告中提示。"
        )

    reasons_text = "；".join(r.reason for r in unpassed if r.reason)
    if re_extract_count == 0:
        return (
            f"【知识点质检未通过】原因：{reasons_text}。"
            "请针对上述缺陷重新梳理知识树，已自动降低单批片段数至 20 个以提升抽取精度。"
        )

    return (
        f"【知识点质检未通过】原因：{reasons_text}。"
        "【严格规范】1. 知识点总数必须适中；"
        "2. 知识点名称长度必须在 4 至 16 字符之间且严禁包含编号（如 1.1、一、）与占位词；"
        "3. 最大层级必须划分至 2~5 级。"
    )


def verify_knowledge_points(
    knowledge_points: Sequence[CandidateKnowledgePoint],
    context: ExtractionContext,
    config: KnowledgeQualityConfig | None = None,
) -> KnowledgeQualityReport:
    """执行知识点质检门禁统一校验。

    Args:
        knowledge_points: 大模型抽取的候选知识点序列。
        context: 抽取上下文（切片总数、有效字数、章节统计、重抽计数）。
        config: 可选配置，未传则采用系统标准默认配置。

    Returns:
        KnowledgeQualityReport: 包含四项评估结果、一票否决结论与提示词反馈的不可变报告。
    """
    active_config = config if config is not None else KnowledgeQualityConfig()

    if context.total_snippets == 0:
        skipped_reason = "资料无可用知识切片，跳过质检"
        return KnowledgeQualityReport(
            is_qualified=False,
            is_skipped=True,
            is_low_confidence=False,
            re_extract_count=context.re_extract_count,
            check_results=(),
            unqualified_reasons=(skipped_reason,),
            prompt_feedback="",
            summary="质检跳过：资料无可用知识切片",
        )

    count = len(knowledge_points)
    levels = [point.level for point in knowledge_points]
    names = [point.name for point in knowledge_points]
    covered_chapters = {
        point.chapter_title.strip() for point in knowledge_points if point.chapter_title.strip()
    }

    r1 = check_quantity_range(count, context.effective_chars, context.total_snippets, active_config)
    r2 = check_hierarchy_depth(levels, active_config)
    r3 = check_naming_readability(names, active_config)
    r4 = check_chapter_coverage(covered_chapters, context.chapter_stats, active_config)
    results = (r1, r2, r3, r4)

    unpassed = [r for r in results if not r.is_passed]
    is_qualified = len(unpassed) == 0
    unqualified_reasons = tuple(r.reason for r in unpassed if r.reason)
    is_low_confidence = (not is_qualified) and (
        context.re_extract_count >= active_config.max_re_extract_attempts
    )
    prompt_feedback = generate_prompt_feedback(results, context.re_extract_count)

    if is_qualified:
        summary = "知识点质检门禁通过：数量、层级、命名与章节覆盖率均符合标准"
    elif is_low_confidence:
        failed_items = ", ".join(r.item_code.value for r in unpassed)
        summary = f"知识点质检未通过并熔断降级：未通过项包括 {failed_items}，标记为低可信度"
    else:
        failed_items = ", ".join(r.item_code.value for r in unpassed)
        summary = f"知识点质检未通过：未通过项包括 {failed_items}"

    return KnowledgeQualityReport(
        is_qualified=is_qualified,
        is_skipped=False,
        is_low_confidence=is_low_confidence,
        re_extract_count=context.re_extract_count,
        check_results=results,
        unqualified_reasons=unqualified_reasons,
        prompt_feedback=prompt_feedback,
        summary=summary,
    )
