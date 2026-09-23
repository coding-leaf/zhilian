"""Unit tests for knowledge point quality gate algorithm kernel.

Verifies test cases TC-KP-01 to TC-KP-27, and
full 16-combination decision table DT-KP-01 to DT-KP-16.
Complies with pure functional kernel testing guidelines:
- Zero mock / patch usage
- 100% deterministic assertion
- Full branch and decision coverage
"""

import pytest

from app.core.algorithms.knowledge_quality import (
    CRITICAL_CHAPTER_SNIPPET_RATIO,
    DEFAULT_PLACEHOLDER_WORDS,
    MAX_EFFECTIVE_CHARS_PER_KP,
    MAX_HIERARCHY_DEPTH,
    MAX_KP_COUNT_ABSOLUTE,
    MAX_LEVEL_2_RATIO,
    MAX_NAME_LENGTH,
    MAX_RE_EXTRACT_ATTEMPTS,
    MIN_CRITICAL_CHAPTER_COVERAGE,
    MIN_EFFECTIVE_CHARS_PER_KP,
    MIN_HIERARCHY_DEPTH,
    MIN_KP_COUNT_SMALL_DOC,
    MIN_NAME_LENGTH,
    TRUNCATION_PATTERN,
    CandidateKnowledgePoint,
    ChapterSnippetStat,
    CheckItemCode,
    CheckResult,
    ExtractionContext,
    KnowledgeQualityConfig,
    KnowledgeQualityReport,
    check_chapter_coverage,
    check_hierarchy_depth,
    check_naming_readability,
    check_quantity_range,
    generate_prompt_feedback,
    verify_knowledge_points,
)


def _build_candidate_point(
    name: str = "二叉查找树",
    level: int = 2,
    chapter_title: str = "第一章 树与二叉树",
) -> CandidateKnowledgePoint:
    """辅助构建标准候选知识点对象。"""
    return CandidateKnowledgePoint(
        name=name,
        level=level,
        chapter_title=chapter_title,
        snippet_ids=("snip_01", "snip_02"),
        description="二叉查找树的插入与查找操作",
    )


# ==============================================================================
# 5 大极端边界与独立门禁测试用例 (TC-KP-01 ~ TC-KP-22)
# ==============================================================================


def test_tc_kp_01_total_snippets_zero_boundary() -> None:
    """TC-KP-01: 切片数为 0 边界，跳过质检。"""
    context = ExtractionContext(
        total_snippets=0,
        effective_chars=0,
        chapter_stats=(),
        re_extract_count=0,
    )
    report = verify_knowledge_points([], context)

    assert isinstance(report, KnowledgeQualityReport)
    assert report.is_skipped is True
    assert report.is_qualified is False
    assert report.is_low_confidence is False
    assert report.check_results == ()
    assert "资料无可用知识切片" in report.unqualified_reasons[0]
    assert report.prompt_feedback == ""
    assert "质检跳过" in report.summary


def test_tc_kp_02_candidate_count_zero() -> None:
    """TC-KP-02: 候选知识点数为 0，直接判定数量不合格且不进入比值计算。"""
    config = KnowledgeQualityConfig()
    result = check_quantity_range(
        count=0,
        effective_chars=10000,
        total_snippets=30,
        config=config,
    )

    assert isinstance(result, CheckResult)
    assert result.item_code == CheckItemCode.QUANTITY_RANGE
    assert result.is_passed is False
    assert result.score == 0.0
    assert result.details["count"] == 0
    assert "数量为 0" in (result.reason or "")

    # 主门禁联动验证
    context = ExtractionContext(
        total_snippets=30,
        effective_chars=10000,
        chapter_stats=(),
        re_extract_count=0,
    )
    report = verify_knowledge_points([], context, config)
    assert report.is_qualified is False
    assert report.is_skipped is False


def test_tc_kp_03_count_exceeds_absolute_max() -> None:
    """TC-KP-03: 绝对数量超过 200 节点，判为过度拆分。"""
    config = KnowledgeQualityConfig()
    result = check_quantity_range(
        count=201,
        effective_chars=300000,
        total_snippets=100,
        config=config,
    )

    assert result.is_passed is False
    assert result.score == 0.0
    assert "超出单份资料绝对上限" in (result.reason or "")
    assert result.details["count"] == 201
    assert result.details["max_allowed"] == 200


def test_tc_kp_04_small_document_insufficient_count() -> None:
    """TC-KP-04: 短资料 (片段<20) 不足 3 个，判为过粗。"""
    config = KnowledgeQualityConfig()
    result = check_quantity_range(
        count=2,
        effective_chars=2000,
        total_snippets=15,
        config=config,
    )

    assert result.is_passed is False
    assert result.score == 0.0
    assert "低于保底要求" in (result.reason or "")
    assert result.details["count"] == 2


def test_tc_kp_05_small_document_satisfied_count() -> None:
    """TC-KP-05: 短资料 (片段<20) 达到 3 个保底，放宽密度要求通过。"""
    config = KnowledgeQualityConfig()
    # 3 个知识点，1500 字符（密度 500 < 625），但因短资料保底通过
    result = check_quantity_range(
        count=3,
        effective_chars=1500,
        total_snippets=15,
        config=config,
    )

    assert result.is_passed is True
    assert result.score == 1.0
    assert result.details["is_small_doc"] is True


def test_tc_kp_06_density_too_high_over_splitting() -> None:
    """TC-KP-06: 密度超限 (字数/KP < 625)，判为过度拆分。"""
    config = KnowledgeQualityConfig()
    # 5000 字 10 个知识点，平均 500 字/个
    result = check_quantity_range(
        count=10,
        effective_chars=5000,
        total_snippets=25,
        config=config,
    )

    assert result.is_passed is False
    assert result.score == 0.0
    assert "密度过高" in (result.reason or "")
    assert "过度拆分" in (result.reason or "")


def test_tc_kp_07_density_too_low_over_coarse() -> None:
    """TC-KP-07: 密度过低 (字数/KP > 5000)，判为过度粗略。"""
    config = KnowledgeQualityConfig()
    # 20000 字 3 个知识点，平均 6666.7 字/个
    result = check_quantity_range(
        count=3,
        effective_chars=20000,
        total_snippets=25,
        config=config,
    )

    assert result.is_passed is False
    assert result.score == 0.0
    assert "密度过低" in (result.reason or "")
    assert "过度粗略" in (result.reason or "")


def test_tc_kp_08_standard_density_passed() -> None:
    """TC-KP-08: 标准密度通过 (在 625 至 5000 字符/个之间)。"""
    config = KnowledgeQualityConfig()
    # 10000 字 8 个知识点，平均 1250 字/个
    result = check_quantity_range(
        count=8,
        effective_chars=10000,
        total_snippets=25,
        config=config,
    )

    assert result.is_passed is True
    assert result.score == 1.0
    assert result.details["chars_per_kp"] == 1250.0


def test_tc_kp_09_hierarchy_empty_or_all_zeros() -> None:
    """TC-KP-09: 层级全为 0 或空，按平铺回退并判定不通过。"""
    config = KnowledgeQualityConfig()
    result_empty = check_hierarchy_depth([], config)
    assert result_empty.is_passed is False
    assert "平铺" in (result_empty.reason or "")

    result_zeros = check_hierarchy_depth([0, 0, 0], config)
    assert result_zeros.is_passed is False
    assert "平铺" in (result_zeros.reason or "")
    assert result_zeros.details["is_flat"] is True


def test_tc_kp_10_hierarchy_depth_flat() -> None:
    """TC-KP-10: 最大层级为 1 (平铺)，缺乏纵深判定不通过。"""
    config = KnowledgeQualityConfig()
    result = check_hierarchy_depth([1, 1, 1, 1], config)

    assert result.is_passed is False
    assert "缺乏层级划分" in (result.reason or "")
    assert result.details["max_depth"] == 1


def test_tc_kp_11_hierarchy_depth_too_deep() -> None:
    """TC-KP-11: 最大层级超过 5 (嵌套过深)，判定不通过。"""
    config = KnowledgeQualityConfig()
    result = check_hierarchy_depth([1, 2, 3, 4, 5, 6], config)

    assert result.is_passed is False
    assert "嵌套过深" in (result.reason or "")
    assert result.details["max_depth"] == 6


def test_tc_kp_12_hierarchy_level_2_ratio_exactly_sixty_percent() -> None:
    """TC-KP-12: 第 2 层节点占比恰好等于 60%，判定通过。"""
    config = KnowledgeQualityConfig()
    # 10 个节点，第 2 层 6 个 (60.0%)，第 1 层 1 个，第 3 层 3 个
    levels = [1, 2, 2, 2, 2, 2, 2, 3, 3, 3]
    result = check_hierarchy_depth(levels, config)

    assert result.is_passed is True
    assert result.score == 1.0
    assert result.details["max_depth"] == 3
    assert result.details["level_2_ratio"] == 0.60


def test_tc_kp_13_hierarchy_level_2_ratio_exceeds_sixty_percent() -> None:
    """TC-KP-13: 第 2 层节点占比超过 60%，判为层级退化 (横向堆积)。"""
    config = KnowledgeQualityConfig()
    # 10 个节点，第 2 层 7 个 (70.0%)
    levels = [1, 2, 2, 2, 2, 2, 2, 2, 3, 3]
    result = check_hierarchy_depth(levels, config)

    assert result.is_passed is False
    assert "层级退化" in (result.reason or "")
    assert result.details["level_2_ratio"] == 0.70


def test_tc_kp_14_naming_all_single_char() -> None:
    """TC-KP-14: 名称全为单字 (长度 1)，判定不合格。"""
    config = KnowledgeQualityConfig()
    names = ["树", "图", "栈"]
    result = check_naming_readability(names, config)

    assert result.is_passed is False
    assert "3 处知识点名称不合规" in (result.reason or "")


def test_tc_kp_15_naming_all_over_length() -> None:
    """TC-KP-15: 名称全超过 30 字符，判定不合格。"""
    config = KnowledgeQualityConfig()
    names = ["A" * 31, "这是一个非常长非常长非常长非常长非常长非常长超标的知识点名称"]
    result = check_naming_readability(names, config)

    assert result.is_passed is False
    assert "2 处知识点名称不合规" in (result.reason or "")


def test_tc_kp_16_naming_contains_placeholder_words() -> None:
    """TC-KP-16: 包含模板占位词 (如“知识点”、“内容一”等)，判定不合格。"""
    config = KnowledgeQualityConfig()
    names = ["重点知识点解析", "第1小节内容一", "待补充说明", "其他相关概念"]
    result = check_naming_readability(names, config)

    assert result.is_passed is False
    assert "包含占位词黑名单" in (result.reason or "")


def test_tc_kp_17_naming_truncation_ellipsis() -> None:
    """TC-KP-17: 包含截断标记 (中文/英文省略号结尾)，判定不合格。"""
    config = KnowledgeQualityConfig()
    names = ["二叉搜索树的查找...", "平衡二叉树旋转…"]
    result = check_naming_readability(names, config)

    assert result.is_passed is False
    assert "截断" in (result.reason or "")


def test_tc_kp_18_naming_truncation_unclosed_brackets_and_valid_pairs() -> None:
    """TC-KP-18: 未闭合括号结尾判不合格；成对闭合括号合法通过。"""
    config = KnowledgeQualityConfig()

    # 1. 异常截断样本（末尾未闭合括号）
    invalid_names = [
        "动态规划基本概念(",
        "贪心算法策略（",
        "回溯法遍历[",
        "分治算法核心思想【",
    ]
    invalid_result = check_naming_readability(invalid_names, config)
    assert invalid_result.is_passed is False
    assert "截断" in (invalid_result.reason or "")

    # 2. 正常成对括号样本（不应被误杀）
    valid_names = [
        "快速傅里叶变换(FFT)",
        "动态规划（DP）",
        "深度优先搜索[DFS]",
        "知识图谱【KG】",
    ]
    valid_result = check_naming_readability(valid_names, config)
    assert valid_result.is_passed is True
    assert valid_result.score == 1.0


def test_tc_kp_19_chapter_ratio_exactly_five_percent() -> None:
    """TC-KP-19: 切片占比恰好等于 5.0%，纳入关键章节计算。"""
    config = KnowledgeQualityConfig()
    stats = [
        ChapterSnippetStat(chapter_title="第一章", snippet_count=5, snippet_ratio=0.05),
        ChapterSnippetStat(chapter_title="第二章", snippet_count=95, snippet_ratio=0.95),
    ]
    # 覆盖两个关键章节
    result = check_chapter_coverage({"第一章", "第二章"}, stats, config)
    assert result.is_passed is True
    assert result.details["critical_chapters"] == ["第一章", "第二章"]


def test_tc_kp_20_chapter_coverage_exactly_eighty_percent() -> None:
    """TC-KP-20: 关键章节覆盖率恰好等于 80%，判定通过。"""
    config = KnowledgeQualityConfig()
    stats = [
        ChapterSnippetStat(chapter_title=f"第{i}章", snippet_count=20, snippet_ratio=0.20)
        for i in range(1, 6)
    ]
    # 5 个关键章节覆盖 4 个，覆盖率 80.0%
    covered = {"第1章", "第2章", "第3章", "第4章"}
    result = check_chapter_coverage(covered, stats, config)

    assert result.is_passed is True
    assert result.score == 1.0
    assert result.details["coverage_ratio"] == 0.80


def test_tc_kp_21_chapter_coverage_below_eighty_percent() -> None:
    """TC-KP-21: 关键章节覆盖率低于 80%，判定不通过并列出遗漏章节。"""
    config = KnowledgeQualityConfig()
    stats = [
        ChapterSnippetStat(chapter_title=f"第{i}章", snippet_count=20, snippet_ratio=0.20)
        for i in range(1, 6)
    ]
    # 5 个关键章节覆盖 3 个，覆盖率 60.0%
    covered = {"第1章", "第2章", "第3章"}
    result = check_chapter_coverage(covered, stats, config)

    assert result.is_passed is False
    assert result.score == 0.0
    assert "低于门禁要求" in (result.reason or "")
    assert result.details["missing_chapters"] == ["第4章", "第5章"]


def test_tc_kp_22_single_chapter_or_no_chapters() -> None:
    """TC-KP-22: 无分章资料或所有章节切片比例均低于 5%，默认 100% 覆盖通过。"""
    config = KnowledgeQualityConfig()

    # 1. 完全无章节统计
    result_empty = check_chapter_coverage(set(), (), config)
    assert result_empty.is_passed is True
    assert result_empty.details["critical_chapters_count"] == 0

    # 2. 存在章节但切片占比均 < 5%
    tiny_stats = [
        ChapterSnippetStat(chapter_title=f"碎片段{i}", snippet_count=1, snippet_ratio=0.01)
        for i in range(10)
    ]
    result_tiny = check_chapter_coverage(set(), tiny_stats, config)
    assert result_tiny.is_passed is True


# ==============================================================================
# 自适应提示词与熔断降级测试用例 (TC-KP-24 ~ TC-KP-26)
# ==============================================================================


def test_tc_kp_24_feedback_first_attempt() -> None:
    """TC-KP-24: 首次未通过 (re_extract_count=0) 生成针对性原因与降低片段至20提示。"""
    failed_result = CheckResult(
        item_code=CheckItemCode.QUANTITY_RANGE,
        is_passed=False,
        score=0.0,
        reason="知识点抽取密度过高",
    )
    feedback = generate_prompt_feedback([failed_result], re_extract_count=0)

    assert "【知识点质检未通过】" in feedback
    assert "知识点抽取密度过高" in feedback
    assert "已自动降低单批片段数至 20 个" in feedback


def test_tc_kp_25_feedback_second_attempt() -> None:
    """TC-KP-25: 二次未通过 (re_extract_count=1) 追加硬性数量与命名规范约束。"""
    failed_result = CheckResult(
        item_code=CheckItemCode.NAMING_READABILITY,
        is_passed=False,
        score=0.0,
        reason="发现包含占位词",
    )
    feedback = generate_prompt_feedback([failed_result], re_extract_count=1)

    assert "【严格规范】" in feedback
    assert "4 至 16 字符" in feedback
    assert "2~5 级" in feedback


def test_tc_kp_26_re_extract_limit_fuse_and_downgrade() -> None:
    """TC-KP-26: 重抽达到 2 次上限仍不通过，触发熔断降级标记 is_low_confidence=True。"""
    context = ExtractionContext(
        total_snippets=30,
        effective_chars=10000,
        chapter_stats=(),
        re_extract_count=2,  # 达上限 2
    )
    # 传入不合格候选点（如最大深度为 1 的平铺数据）
    flat_points = [
        _build_candidate_point(f"概念{i}", level=1, chapter_title="章") for i in range(10)
    ]
    report = verify_knowledge_points(flat_points, context)

    assert report.is_qualified is False
    assert report.is_low_confidence is True
    assert "熔断降级" in report.summary
    assert "标记为低可信度" in report.summary
    assert "已采用本次结果降级处理" in report.prompt_feedback


def test_tc_kp_27_config_validation_defensive_bounds() -> None:
    """TC-KP-27: 配置参数合法性防御校验，非法边界抛出 ValueError。"""
    with pytest.raises(ValueError, match="effective chars per KP bounds must be positive"):
        KnowledgeQualityConfig(min_effective_chars_per_kp=0)

    with pytest.raises(ValueError, match="cannot exceed max_effective_chars_per_kp"):
        KnowledgeQualityConfig(min_effective_chars_per_kp=6000, max_effective_chars_per_kp=5000)

    with pytest.raises(ValueError, match="invalid KP count constraints"):
        KnowledgeQualityConfig(min_kp_count_small_doc=-1)

    with pytest.raises(ValueError, match="invalid hierarchy depth range"):
        KnowledgeQualityConfig(min_hierarchy_depth=6, max_hierarchy_depth=5)

    with pytest.raises(ValueError, match=r"max_level_2_ratio must be between 0\.0 and 1\.0"):
        KnowledgeQualityConfig(max_level_2_ratio=1.5)

    with pytest.raises(ValueError, match="invalid name length constraints"):
        KnowledgeQualityConfig(min_name_length=40, max_name_length=30)

    with pytest.raises(ValueError, match="critical_chapter_snippet_ratio must be between"):
        KnowledgeQualityConfig(critical_chapter_snippet_ratio=1.2)

    with pytest.raises(ValueError, match="min_critical_chapter_coverage must be between"):
        KnowledgeQualityConfig(min_critical_chapter_coverage=-0.1)

    with pytest.raises(ValueError, match="max_re_extract_attempts must be non-negative"):
        KnowledgeQualityConfig(max_re_extract_attempts=-1)


# ==============================================================================
# 16 组全排列决策表矩阵 (DT-KP-01 ~ DT-KP-16)
# ==============================================================================


@pytest.mark.parametrize(
    (
        "rule_id",
        "c1_pass",
        "c2_pass",
        "c3_pass",
        "c4_pass",
        "expected_qualified",
        "expected_failed_codes",
    ),
    [
        ("DT-KP-01", True, True, True, True, True, ()),
        ("DT-KP-02", True, True, True, False, False, (CheckItemCode.CHAPTER_COVERAGE,)),
        ("DT-KP-03", True, True, False, True, False, (CheckItemCode.NAMING_READABILITY,)),
        (
            "DT-KP-04",
            True,
            True,
            False,
            False,
            False,
            (CheckItemCode.NAMING_READABILITY, CheckItemCode.CHAPTER_COVERAGE),
        ),
        ("DT-KP-05", True, False, True, True, False, (CheckItemCode.HIERARCHY_DEPTH,)),
        (
            "DT-KP-06",
            True,
            False,
            True,
            False,
            False,
            (CheckItemCode.HIERARCHY_DEPTH, CheckItemCode.CHAPTER_COVERAGE),
        ),
        (
            "DT-KP-07",
            True,
            False,
            False,
            True,
            False,
            (CheckItemCode.HIERARCHY_DEPTH, CheckItemCode.NAMING_READABILITY),
        ),
        (
            "DT-KP-08",
            True,
            False,
            False,
            False,
            False,
            (
                CheckItemCode.HIERARCHY_DEPTH,
                CheckItemCode.NAMING_READABILITY,
                CheckItemCode.CHAPTER_COVERAGE,
            ),
        ),
        ("DT-KP-09", False, True, True, True, False, (CheckItemCode.QUANTITY_RANGE,)),
        (
            "DT-KP-10",
            False,
            True,
            True,
            False,
            False,
            (CheckItemCode.QUANTITY_RANGE, CheckItemCode.CHAPTER_COVERAGE),
        ),
        (
            "DT-KP-11",
            False,
            True,
            False,
            True,
            False,
            (CheckItemCode.QUANTITY_RANGE, CheckItemCode.NAMING_READABILITY),
        ),
        (
            "DT-KP-12",
            False,
            True,
            False,
            False,
            False,
            (
                CheckItemCode.QUANTITY_RANGE,
                CheckItemCode.NAMING_READABILITY,
                CheckItemCode.CHAPTER_COVERAGE,
            ),
        ),
        (
            "DT-KP-13",
            False,
            False,
            True,
            True,
            False,
            (CheckItemCode.QUANTITY_RANGE, CheckItemCode.HIERARCHY_DEPTH),
        ),
        (
            "DT-KP-14",
            False,
            False,
            True,
            False,
            False,
            (
                CheckItemCode.QUANTITY_RANGE,
                CheckItemCode.HIERARCHY_DEPTH,
                CheckItemCode.CHAPTER_COVERAGE,
            ),
        ),
        (
            "DT-KP-15",
            False,
            False,
            False,
            True,
            False,
            (
                CheckItemCode.QUANTITY_RANGE,
                CheckItemCode.HIERARCHY_DEPTH,
                CheckItemCode.NAMING_READABILITY,
            ),
        ),
        (
            "DT-KP-16",
            False,
            False,
            False,
            False,
            False,
            (
                CheckItemCode.QUANTITY_RANGE,
                CheckItemCode.HIERARCHY_DEPTH,
                CheckItemCode.NAMING_READABILITY,
                CheckItemCode.CHAPTER_COVERAGE,
            ),
        ),
    ],
)
def test_tc_kp_23_decision_table_16_combinations(
    rule_id: str,
    c1_pass: bool,
    c2_pass: bool,
    c3_pass: bool,
    c4_pass: bool,
    expected_qualified: bool,
    expected_failed_codes: tuple[CheckItemCode, ...],
) -> None:
    """TC-KP-23: 16 组全排列决策表矩阵测试，验证四项一票否决与仅全通合格。"""
    config = KnowledgeQualityConfig()

    # 1. 构造 C1 数量特征
    # 正常资料 total_snippets=30, effective_chars=10000
    # 若通过: count=8 (密度 1250); 若失败: count=25 (密度 400 < 625 过度拆分)
    count = 8 if c1_pass else 25

    # 2. 构造 C2 层级特征
    # 若通过: 深度为 3, level 2 占比 <= 0.6; 若失败: 深度为 1 (平铺)
    if c2_pass:
        # 8 个节点: [1, 2, 3, 3, 2, 3, 2, 3] (level 2 占比 3/8 = 37.5%)
        # 25 个节点: [1] + [2]*10 + [3]*14 (level 2 占比 10/25 = 40%)
        level_2_quota = count // 3
        levels = [1] + [2] * level_2_quota + [3] * (count - 1 - level_2_quota)
    else:
        levels = [1] * count

    # 3. 构造 C3 命名特征
    # 若通过: 合法命名; 若失败: 插入带有占位词的非法命名
    names = [f"二叉树遍历算法{i}" for i in range(count)]
    if not c3_pass:
        names[0] = "待补充"  # 触发模板占位词黑名单

    # 4. 构造 C4 章节特征
    # 2 个关键章节: "第一章", "第二章" (各占 50%)
    chapter_stats = (
        ChapterSnippetStat(chapter_title="第一章", snippet_count=15, snippet_ratio=0.50),
        ChapterSnippetStat(chapter_title="第二章", snippet_count=15, snippet_ratio=0.50),
    )
    # 若通过: 覆盖两章; 若失败: 仅覆盖第一章 (覆盖率 50% < 80%)
    if c4_pass:
        chapters = ["第一章" if i % 2 == 0 else "第二章" for i in range(count)]
    else:
        chapters = ["第一章"] * count

    points = [
        CandidateKnowledgePoint(
            name=names[i],
            level=levels[i],
            chapter_title=chapters[i],
            snippet_ids=(f"s_{i}",),
        )
        for i in range(count)
    ]

    context = ExtractionContext(
        total_snippets=30,
        effective_chars=10000,
        chapter_stats=chapter_stats,
        re_extract_count=0,
    )

    report = verify_knowledge_points(points, context, config)

    assert report.is_qualified is expected_qualified, f"Rule {rule_id} qualified assertion failed"
    actual_failed_codes = tuple(r.item_code for r in report.check_results if not r.is_passed)
    assert actual_failed_codes == expected_failed_codes, (
        f"Rule {rule_id} expected failed items {expected_failed_codes} "
        f"but got {actual_failed_codes}"
    )


# ==============================================================================
# 常量与默认值完整性测试
# ==============================================================================


def test_constants_and_defaults_integrity() -> None:
    """验证算法常量定义与规范完全对齐。"""
    assert MIN_EFFECTIVE_CHARS_PER_KP == 625
    assert MAX_EFFECTIVE_CHARS_PER_KP == 5000
    assert MIN_KP_COUNT_SMALL_DOC == 3
    assert MAX_KP_COUNT_ABSOLUTE == 200
    assert MIN_HIERARCHY_DEPTH == 2
    assert MAX_HIERARCHY_DEPTH == 5
    assert MAX_LEVEL_2_RATIO == 0.60
    assert MIN_NAME_LENGTH == 2
    assert MAX_NAME_LENGTH == 30
    assert CRITICAL_CHAPTER_SNIPPET_RATIO == 0.05
    assert MIN_CRITICAL_CHAPTER_COVERAGE == 0.80
    assert MAX_RE_EXTRACT_ATTEMPTS == 2
    assert "知识点" in DEFAULT_PLACEHOLDER_WORDS
    assert "测试" in DEFAULT_PLACEHOLDER_WORDS
    assert TRUNCATION_PATTERN is not None


def test_naming_empty_names() -> None:
    """补充测试：命名检查输入空序列。"""
    result = check_naming_readability([], KnowledgeQualityConfig())
    assert result.is_passed is False
    assert result.score == 0.0
    assert "列表为空" in (result.reason or "")
