"""Unit tests for question quality gate and pending review filter kernel.

Verifies test cases TC-QQ-01 to TC-QQ-35, covering:
- 5 extreme boundaries & anomaly defenses (B-1 ~ B-7)
- 4 quality check decision tables (NO_SOURCE, DUPLICATE, ANSWER_CONFLICT, AMBIGUITY)
- One-vote veto priority arbitration
- Pure functional mathematical and text tools
- Zero external I/O, zero network/database dependencies, 0 mock
"""

import math

import pytest

from app.core.algorithms.question_quality import (
    AMBIGUOUS_TRIGGER_WORDS,
    CONTENT_WORD_PATTERN,
    DEFAULT_CONFLICT_VECTOR_THRESHOLD,
    DEFAULT_DUPLICATE_TEXT_THRESHOLD,
    DEFAULT_DUPLICATE_VECTOR_THRESHOLD,
    DEFAULT_MIN_SOURCE_KEYWORD_RATIO,
    DEFAULT_MIN_STEM_LENGTH,
    MAX_EXISTING_QUESTIONS_WINDOW,
    CandidateQuestion,
    ExistingQuestionReference,
    QualityCheckType,
    QuestionQualityConfig,
    QuestionQualityReport,
    QuestionType,
    UnqualifiedReason,
    calculate_cosine_similarity,
    calculate_text_similarity,
    check_ambiguity,
    check_answer_conflict,
    check_duplication,
    check_source_grounding,
    evaluate_single_question,
    extract_content_words,
    extract_keywords,
    filter_qualified_questions,
)


def _build_candidate(
    question_id: str = "q-001",
    stem: str = "二叉树遍历算法，下列关于前序遍历的描述正确的是",
    question_type: str = QuestionType.SINGLE_CHOICE,
    answer: str = "A",
    options: tuple[dict[str, str], ...] = (
        {"key": "A", "content": "前序遍历先访问根节点"},
        {"key": "B", "content": "中序遍历最后访问根节点"},
        {"key": "C", "content": "后序遍历最先访问根节点"},
        {"key": "D", "content": "层次遍历使用栈结构实现"},
    ),
    source_snippet_ids: tuple[str, ...] = ("snp-01",),
    source_text: str = "二叉树遍历算法，前序遍历首先访问根节点，然后遍历左右子树。",
    embedding: tuple[float, ...] | None = (0.1, 0.2, 0.3, 0.4),
    analysis: str = "前序遍历顺序为根左右",
    created_at_seq: int = 0,
) -> CandidateQuestion:
    """构建标准合格测试候选题目。"""
    return CandidateQuestion(
        question_id=question_id,
        stem=stem,
        question_type=question_type,
        answer=answer,
        options=options,
        source_snippet_ids=source_snippet_ids,
        source_text=source_text,
        embedding=embedding,
        analysis=analysis,
        created_at_seq=created_at_seq,
    )


def _build_existing(
    question_id: str = "ex-001",
    stem: str = "二叉树遍历算法，下列关于前序遍历的描述正确的是",
    question_type: str = QuestionType.SINGLE_CHOICE,
    answer: str = "A",
    options: tuple[dict[str, str], ...] = (
        {"key": "A", "content": "前序遍历先访问根节点"},
        {"key": "B", "content": "中序遍历最后访问根节点"},
        {"key": "C", "content": "后序遍历最先访问根节点"},
        {"key": "D", "content": "层次遍历使用栈结构实现"},
    ),
    embedding: tuple[float, ...] | None = (0.1, 0.2, 0.3, 0.4),
) -> ExistingQuestionReference:
    """构建已有题库历史参考题目。"""
    return ExistingQuestionReference(
        question_id=question_id,
        stem=stem,
        question_type=question_type,
        answer=answer,
        options=options,
        embedding=embedding,
    )


# ==============================================================================
# 1. 基础纯函数数学与文本处理工具测试
# ==============================================================================


def test_calculate_cosine_similarity_normal() -> None:
    """测试余弦相似度：相同向量、正交向量与反向向量。"""
    vector_a = (1.0, 0.0, 0.0)
    vector_b = (1.0, 0.0, 0.0)
    assert math.isclose(calculate_cosine_similarity(vector_a, vector_b), 1.0)

    vector_orthogonal = (0.0, 1.0, 0.0)
    assert math.isclose(calculate_cosine_similarity(vector_a, vector_orthogonal), 0.0)

    vector_opposite = (-1.0, 0.0, 0.0)
    assert math.isclose(calculate_cosine_similarity(vector_a, vector_opposite), -1.0)


def test_calculate_cosine_similarity_edge_cases() -> None:
    """测试余弦相似度边界防御：None、空向量、维度不匹配、零向量。"""
    assert calculate_cosine_similarity(None, (1.0, 2.0)) == 0.0
    assert calculate_cosine_similarity((1.0, 2.0), None) == 0.0
    assert calculate_cosine_similarity((), ()) == 0.0
    assert calculate_cosine_similarity((1.0, 2.0), (1.0,)) == 0.0
    assert calculate_cosine_similarity((0.0, 0.0), (1.0, 2.0)) == 0.0


def test_calculate_text_similarity() -> None:
    """测试字符 2-gram Jaccard 相似度。"""
    assert calculate_text_similarity("二叉树遍历", "二叉树遍历") == 1.0
    assert calculate_text_similarity("", "") == 0.0
    assert calculate_text_similarity("  ", "  ") == 0.0
    assert calculate_text_similarity("二叉树遍历", "二叉树查找") > 0.0
    assert calculate_text_similarity("完全无关", "绝对不同") == 0.0
    assert calculate_text_similarity("a", "b") == 0.0
    assert calculate_text_similarity("a", "a") == 1.0


def test_extract_keywords_and_content_words() -> None:
    """测试实词提取正则：支持中英文实词，过滤单字与标点。"""
    assert CONTENT_WORD_PATTERN.pattern == r"[\u4e00-\u9fa5]{2,}|[a-zA-Z]{2,}"
    assert "以上都对" in AMBIGUOUS_TRIGGER_WORDS
    text = "二叉树（Binary Tree）深度优先遍历算法，包括preorder与inorder！"
    keywords = extract_keywords(text)
    assert "二叉树" in keywords
    assert "Binary" in keywords
    assert "Tree" in keywords
    assert "深度优先遍历算法" in keywords
    assert "preorder" in keywords
    assert "inorder" in keywords

    # extract_content_words 是同义别名
    assert extract_content_words(text) == keywords
    assert extract_keywords("的 在 和 1 2 3 ， 。 ！") == []


# ==============================================================================
# 2. 质检配置合法性校验测试 (B-6)
# ==============================================================================


def test_tc_qq_01_config_validation_success() -> None:
    """TC-QQ-01: 质检配置默认参数及合法赋值校验。"""
    assert UnqualifiedReason is QualityCheckType
    config = QuestionQualityConfig()
    assert config.duplicate_vector_threshold == DEFAULT_DUPLICATE_VECTOR_THRESHOLD
    assert config.duplicate_text_threshold == DEFAULT_DUPLICATE_TEXT_THRESHOLD
    assert config.conflict_vector_threshold == DEFAULT_CONFLICT_VECTOR_THRESHOLD
    assert config.min_source_keyword_ratio == DEFAULT_MIN_SOURCE_KEYWORD_RATIO
    assert config.min_stem_length == DEFAULT_MIN_STEM_LENGTH
    assert config.max_existing_questions_window == MAX_EXISTING_QUESTIONS_WINDOW


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("duplicate_vector_threshold", 1.2),
        ("duplicate_vector_threshold", -0.1),
        ("duplicate_text_threshold", 1.05),
        ("duplicate_text_threshold", -0.01),
        ("conflict_vector_threshold", 2.0),
        ("conflict_vector_threshold", -0.5),
        ("min_source_keyword_ratio", 1.1),
        ("min_source_keyword_ratio", -0.2),
        ("min_stem_length", 0),
        ("min_stem_length", -5),
        ("max_existing_questions_window", 0),
        ("max_existing_questions_window", -10),
    ],
)
def test_tc_qq_02_config_validation_failure(field_name: str, invalid_value: object) -> None:
    """TC-QQ-02: 质检配置非法参数抛出 ValueError 校验 (B-6)。"""
    with pytest.raises(ValueError):
        kwargs: dict[str, object] = {field_name: invalid_value}
        QuestionQualityConfig(**kwargs)  # type: ignore[arg-type]


# ==============================================================================
# 3. 规则 1：无来源检查决策表测试 (check_source_grounding, C1-1 ~ C1-6)
# ==============================================================================


def test_tc_qq_03_source_grounding_c1_1_missing_ids() -> None:
    """TC-QQ-03: C1-1 缺少来源切片标识 -> 不通过 (NO_SOURCE)。"""
    config = QuestionQualityConfig()
    is_valid, reason, ratio = check_source_grounding(
        stem="关于二叉树遍历算法正确的是",
        source_text="二叉树遍历算法介绍",
        source_snippet_ids=(),
        config=config,
    )
    assert is_valid is False
    assert reason == "缺少来源切片标识"
    assert ratio == 0.0


def test_tc_qq_04_source_grounding_c1_2_empty_source_text() -> None:
    """TC-QQ-04: C1-2 来源片段内容为空白 -> 不通过 (NO_SOURCE) (B-3)。"""
    config = QuestionQualityConfig()
    is_valid, reason, ratio = check_source_grounding(
        stem="关于二叉树遍历算法正确的是",
        source_text="   \n\t  ",
        source_snippet_ids=("snp-01",),
        config=config,
    )
    assert is_valid is False
    assert reason == "来源片段内容为空"
    assert ratio == 0.0


def test_tc_qq_05_source_grounding_c1_3_no_keywords_in_stem() -> None:
    """TC-QQ-05: C1-3 题干无有效实词 -> 不通过 (NO_SOURCE)。"""
    config = QuestionQualityConfig()
    is_valid, reason, ratio = check_source_grounding(
        stem="的 了 吗 ？",
        source_text="二叉树遍历算法知识点",
        source_snippet_ids=("snp-01",),
        config=config,
    )
    assert is_valid is False
    assert reason == "题干未包含有效实词"
    assert ratio == 0.0


def test_tc_qq_06_source_grounding_c1_4_low_ratio() -> None:
    """TC-QQ-06: C1-4 实词重合率低于 30.0% -> 不通过 (NO_SOURCE)。"""
    config = QuestionQualityConfig()
    # 构造实词集合：操作系统 进程调度 虚拟内存 页面置换 文件系统 (5个词)
    # 来源只出现 1 个词 (操作系统) -> 1/5 = 20% < 30%
    stem = "操作系统 进程调度 虚拟内存 页面置换 文件系统"
    source_text = "这是关于操作系统的教材"
    is_valid, reason, ratio = check_source_grounding(
        stem=stem,
        source_text=source_text,
        source_snippet_ids=("snp-01",),
        config=config,
    )
    assert is_valid is False
    assert "重合率不足 30.0%" in (reason or "")
    assert ratio == pytest.approx(0.20)


def test_tc_qq_07_source_grounding_c1_5_boundary_ratio() -> None:
    """TC-QQ-07: C1-5 实词重合率恰好等于 30.0% 临界闭区间 -> 通过 (B-5)。"""
    config = QuestionQualityConfig(min_source_keyword_ratio=0.30)
    # 构造 10 个实词，来源恰好包含 3 个
    # 词：二叉树 堆排序 快速排序 冒泡排序 插入排序 希尔排序 归并排序 基数排序 拓扑排序 关键路径
    words = [
        "二叉树",
        "堆排序",
        "快速排序",
        "冒泡排序",
        "插入排序",
        "希尔排序",
        "归并排序",
        "基数排序",
        "拓扑排序",
        "关键路径",
    ]
    stem = " ".join(words)
    source_text = "二叉树 堆排序 快速排序"
    is_valid, reason, ratio = check_source_grounding(
        stem=stem,
        source_text=source_text,
        source_snippet_ids=("snp-01",),
        config=config,
    )
    assert is_valid is True
    assert reason is None
    assert ratio == pytest.approx(0.30)


def test_tc_qq_08_source_grounding_c1_6_high_ratio() -> None:
    """TC-QQ-08: C1-6 实词重合率高于 30.0% -> 通过。"""
    config = QuestionQualityConfig()
    stem = "二叉树 前序遍历 算法 根节点"
    source_text = "二叉树的前序遍历算法中根节点首先被访问。"
    is_valid, reason, ratio = check_source_grounding(
        stem=stem,
        source_text=source_text,
        source_snippet_ids=("snp-01",),
        config=config,
    )
    assert is_valid is True
    assert reason is None
    assert ratio >= 0.30


# ==============================================================================
# 4. 规则 2：重复题检查决策表测试 (check_duplication, C2-1 ~ C2-8)
# ==============================================================================


def test_tc_qq_09_duplication_c2_1_batch_duplicate() -> None:
    """TC-QQ-09: C2-1 同批次前序题干完全重复（去空白后） -> 不通过 (DUPLICATE) (B-2)。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(question_id="q-002", stem="二叉树遍历算法 正确的是")
    prior = _build_candidate(question_id="q-001", stem="二叉树遍历算法正确的是")
    is_valid, reason, score, is_degraded = check_duplication(
        candidate=candidate,
        existing=(),
        prior_candidates=(prior,),
        config=config,
    )
    assert is_valid is False
    assert reason == "同批次内题干完全重复（保留首发题目）"
    assert score == 1.0
    assert is_degraded is False


def test_tc_qq_10_duplication_c2_2_vector_similarity_exceeded() -> None:
    """TC-QQ-10: C2-2 双方有向量且余弦相似度 >= 0.90 -> 不通过 (DUPLICATE)。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(stem="题目A", embedding=(1.0, 0.0))
    existing = _build_existing(stem="题目B", embedding=(0.95, 0.3122))  # cos ~ 0.95
    is_valid, reason, score, is_degraded = check_duplication(
        candidate=candidate,
        existing=(existing,),
        prior_candidates=(),
        config=config,
    )
    assert is_valid is False
    assert reason == "与已有题目语义向量相似度超限"
    assert score is not None and score >= 0.90
    assert is_degraded is False


def test_tc_qq_11_duplication_c2_3_vector_similarity_boundary() -> None:
    """TC-QQ-11: C2-3 余弦相似度恰好为 0.90 闭区间边界 -> 不通过 (DUPLICATE) (B-5)。"""
    config = QuestionQualityConfig()
    # 构造精确 cos = 0.90
    candidate = _build_candidate(stem="题目A", embedding=(1.0, 0.0))
    existing = _build_existing(stem="题目B", embedding=(0.90, math.sqrt(1 - 0.90**2)))
    is_valid, reason, score, is_degraded = check_duplication(
        candidate=candidate,
        existing=(existing,),
        prior_candidates=(),
        config=config,
    )
    assert is_valid is False
    assert reason == "与已有题目语义向量相似度超限"
    assert score is not None and math.isclose(score, 0.90, abs_tol=1e-5)
    assert is_degraded is False


def test_tc_qq_12_duplication_c2_4_text_similarity_exceeded() -> None:
    """TC-QQ-12: C2-4 双方有向量但向量不超限，字符相似度 >= 0.85 -> 不通过 (DUPLICATE)。"""
    config = QuestionQualityConfig()
    # 向量正交 (cos = 0.0)，但题干几乎相同
    candidate = _build_candidate(stem="二叉树遍历算法分析与实现方案", embedding=(1.0, 0.0))
    existing = _build_existing(stem="二叉树遍历算法分析与实现方案详解", embedding=(0.0, 1.0))
    is_valid, reason, score, is_degraded = check_duplication(
        candidate=candidate,
        existing=(existing,),
        prior_candidates=(),
        config=config,
    )
    assert is_valid is False
    assert reason == "与已有题目字符相似度超限"
    assert score is not None and score >= 0.85
    assert is_degraded is False


def test_tc_qq_13_duplication_c2_6_pass() -> None:
    """TC-QQ-13: C2-6 向量与字符相似度均低于阈值 -> 通过。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(stem="关系型数据库索引机制", embedding=(1.0, 0.0))
    existing = _build_existing(stem="二叉平衡树的旋转调整", embedding=(0.0, 1.0))
    is_valid, reason, _score, is_degraded = check_duplication(
        candidate=candidate,
        existing=(existing,),
        prior_candidates=(),
        config=config,
    )
    assert is_valid is True
    assert reason is None
    assert is_degraded is False


def test_tc_qq_14_duplication_c2_7_missing_vector_degraded_exceeded() -> None:
    """TC-QQ-14: C2-7 向量缺失降级且字符相似度超限 -> 不通过并标记降级 (B-4)。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(stem="二叉树遍历算法分析与实现方案", embedding=None)
    existing = _build_existing(stem="二叉树遍历算法分析与实现方案详解", embedding=None)
    is_valid, reason, _score, is_degraded = check_duplication(
        candidate=candidate,
        existing=(existing,),
        prior_candidates=(),
        config=config,
    )
    assert is_valid is False
    assert reason == "与已有题目字符相似度超限"
    assert is_degraded is True


def test_tc_qq_15_duplication_c2_8_missing_vector_degraded_pass() -> None:
    """TC-QQ-15: C2-8 向量缺失降级且字符相似度未超限 -> 通过并标记降级 (B-4)。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(stem="关系型数据库事务特性", embedding=None)
    existing = _build_existing(stem="二叉树深度优先搜索算法", embedding=None)
    is_valid, reason, _score, is_degraded = check_duplication(
        candidate=candidate,
        existing=(existing,),
        prior_candidates=(),
        config=config,
    )
    assert is_valid is True
    assert reason is None
    assert is_degraded is True


# ==============================================================================
# 5. 规则 3：答案冲突检查决策表测试 (check_answer_conflict, C3-1 ~ C3-5)
# ==============================================================================


def test_tc_qq_16_conflict_c3_1_subjective_question_skipped() -> None:
    """TC-QQ-16: C3-1 主观题与填空题自动跳过答案冲突检查。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(
        stem="请简述二叉树前序遍历过程",
        question_type=QuestionType.SHORT_ANSWER,
        answer="先访问根节点",
    )
    existing = _build_existing(
        stem="请简述二叉树前序遍历过程",
        question_type=QuestionType.SHORT_ANSWER,
        answer="完全不同的答案表述",
    )
    is_valid, reason, _score, _is_degraded = check_answer_conflict(
        candidate=candidate,
        existing=(existing,),
        config=config,
    )
    assert is_valid is True
    assert reason is None


def test_tc_qq_17_conflict_c3_2_similarity_below_threshold() -> None:
    """TC-QQ-17: C3-2 客观题题干相似度低于 0.88 -> 通过。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(
        stem="关于快速排序下列说法正确的是",
        embedding=(1.0, 0.0),
        answer="A",
    )
    existing = _build_existing(
        stem="关于冒泡排序下列说法正确的是",
        embedding=(0.5, 0.5),
        answer="B",
    )
    is_valid, reason, _score, _is_degraded = check_answer_conflict(
        candidate=candidate,
        existing=(existing,),
        config=config,
    )
    assert is_valid is True
    assert reason is None


def test_tc_qq_18_conflict_c3_3_answers_consistent() -> None:
    """TC-QQ-18: C3-3 客观题题干相似度 >= 0.88 且答案一致 -> 通过。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(
        stem="下列关于二叉树性质描述正确的是",
        embedding=(1.0, 0.0),
        answer="A, B",
        question_type=QuestionType.MULTIPLE_CHOICE,
    )
    existing = _build_existing(
        stem="下列关于二叉树性质描述正确的是",
        embedding=(1.0, 0.0),
        answer="B, A",  # 无序比较
        question_type=QuestionType.MULTIPLE_CHOICE,
    )
    is_valid, reason, _score, _is_degraded = check_answer_conflict(
        candidate=candidate,
        existing=(existing,),
        config=config,
    )
    assert is_valid is True
    assert reason is None


def test_tc_qq_19_conflict_c3_4_answers_conflict_boundary() -> None:
    """TC-QQ-19: C3-4 题干相似度恰好为 0.88 且答案不同 -> 不通过 (ANSWER_CONFLICT) (B-5)。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(
        stem="关于二叉树遍历算法正确的是",
        embedding=(1.0, 0.0),
        answer="A",
    )
    existing = _build_existing(
        stem="关于二叉树遍历算法正确的是",
        embedding=(0.88, math.sqrt(1 - 0.88**2)),
        answer="C",
    )
    is_valid, reason, score, _is_degraded = check_answer_conflict(
        candidate=candidate,
        existing=(existing,),
        config=config,
    )
    assert is_valid is False
    assert reason == "题干高度相似但客观题标准答案冲突"
    assert score is not None and math.isclose(score, 0.88, abs_tol=1e-5)


def test_tc_qq_20_conflict_true_false_boolean() -> None:
    """TC-QQ-20: 判断题二值答案归一化比对（对 vs 错 冲突）。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(
        stem="二叉树中每个节点的度数最大为二",
        embedding=(1.0, 0.0),
        question_type=QuestionType.TRUE_FALSE,
        answer="正确",
    )
    existing = _build_existing(
        stem="二叉树中每个节点的度数最大为二",
        embedding=(1.0, 0.0),
        question_type=QuestionType.TRUE_FALSE,
        answer="错误",
    )
    is_valid, reason, _score, _is_degraded = check_answer_conflict(
        candidate=candidate,
        existing=(existing,),
        config=config,
    )
    assert is_valid is False
    assert reason == "题干高度相似但客观题标准答案冲突"


# ==============================================================================
# 6. 规则 4：明显歧义检查决策表测试 (check_ambiguity, C4-1 ~ C4-5)
# ==============================================================================


def test_tc_qq_21_ambiguity_c4_1_short_stem() -> None:
    """TC-QQ-21: C4-1 题干长度小于 6 字符 -> 不通过 (AMBIGUITY)。"""
    config = QuestionQualityConfig(min_stem_length=6)
    candidate = _build_candidate(stem="二叉树？")
    is_valid, reason = check_ambiguity(candidate, config)
    assert is_valid is False
    assert "题干长度小于 6 字符" in (reason or "")


def test_tc_qq_22_ambiguity_c4_2_duplicate_options() -> None:
    """TC-QQ-22: C4-2 选项存在重复内容 -> 不通过 (AMBIGUITY)。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(
        options=(
            {"key": "A", "content": "前序遍历"},
            {"key": "B", "content": "中序遍历"},
            {"key": "C", "content": "前序遍历"},  # 重复内容
            {"key": "D", "content": "后序遍历"},
        )
    )
    is_valid, reason = check_ambiguity(candidate, config)
    assert is_valid is False
    assert reason == "选项存在重复内容"


def test_tc_qq_23_ambiguity_c4_3_single_choice_multiple_answers() -> None:
    """TC-QQ-23: C4-3 单选题正确答案不为 1 项 -> 不通过 (AMBIGUITY)。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(
        question_type=QuestionType.SINGLE_CHOICE,
        answer="A, B",
    )
    is_valid, reason = check_ambiguity(candidate, config)
    assert is_valid is False
    assert reason == "单选题正确答案数不为 1"


def test_tc_qq_24_ambiguity_c4_3_multiple_choice_constraints() -> None:
    """TC-QQ-24: 多选题选项与答案约束（少于3项/少于2项/包含全量）。"""
    config = QuestionQualityConfig()

    # 选项少于 3 项
    cand_options_few = _build_candidate(
        question_type=QuestionType.MULTIPLE_CHOICE,
        options=({"key": "A", "content": "A1"}, {"key": "B", "content": "B1"}),
        answer="A, B",
    )
    is_valid, reason = check_ambiguity(cand_options_few, config)
    assert is_valid is False
    assert reason == "多选题选项总数少于 3 项"

    # 答案少于 2 项
    cand_answers_few = _build_candidate(
        question_type=QuestionType.MULTIPLE_CHOICE,
        options=(
            {"key": "A", "content": "A1"},
            {"key": "B", "content": "B1"},
            {"key": "C", "content": "C1"},
        ),
        answer="A",
    )
    is_valid, reason = check_ambiguity(cand_answers_few, config)
    assert is_valid is False
    assert reason == "多选题正确答案少于 2 项"

    # 答案包含全量选项
    cand_answers_all = _build_candidate(
        question_type=QuestionType.MULTIPLE_CHOICE,
        options=(
            {"key": "A", "content": "A1"},
            {"key": "B", "content": "B1"},
            {"key": "C", "content": "C1"},
        ),
        answer="A, B, C",
    )
    is_valid, reason = check_ambiguity(cand_answers_all, config)
    assert is_valid is False
    assert reason == "多选题正确答案包含全量选项"


def test_tc_qq_25_ambiguity_c4_3_true_false_invalid_boolean() -> None:
    """TC-QQ-25: 判断题答案非二值格式 -> 不通过 (AMBIGUITY)。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(
        question_type=QuestionType.TRUE_FALSE,
        answer="也许吧",
    )
    is_valid, reason = check_ambiguity(candidate, config)
    assert is_valid is False
    assert reason == "判断题答案非二值格式"


def test_tc_qq_26_ambiguity_c4_3_empty_subjective_answer() -> None:
    """TC-QQ-26: 填空题/主观题参考答案为空 -> 不通过 (AMBIGUITY)。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(
        question_type=QuestionType.FILL_IN_BLANK,
        answer="   ",
    )
    is_valid, reason = check_ambiguity(candidate, config)
    assert is_valid is False
    assert reason == "参考答案内容为空"


def test_tc_qq_27_ambiguity_c4_4_contradiction_trigger_words() -> None:
    """TC-QQ-27: C4-4 '以上都对/错'在多选或多答案中自相矛盾 -> 不通过 (AMBIGUITY)。"""
    config = QuestionQualityConfig()

    # 多选题包含“以上都对”
    candidate_multi = _build_candidate(
        question_type=QuestionType.MULTIPLE_CHOICE,
        options=(
            {"key": "A", "content": "选项A内容"},
            {"key": "B", "content": "选项B内容"},
            {"key": "C", "content": "以上都对"},
        ),
        answer="A, B",
    )
    is_valid, reason = check_ambiguity(candidate_multi, config)
    assert is_valid is False
    assert reason == "存在'以上都对/错'且与其他选项逻辑冲突"

    # 题干包含“以上均对”
    candidate_stem = _build_candidate(
        stem="关于下列说法以上均对的是哪一项",
    )
    is_valid, reason = check_ambiguity(candidate_stem, config)
    assert is_valid is False
    assert reason == "存在'以上都对/错'且与其他选项逻辑冲突"


def test_tc_qq_28_ambiguity_c4_5_valid_pass() -> None:
    """TC-QQ-28: C4-5 结构完整合规题目 -> 通过。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate()
    is_valid, reason = check_ambiguity(candidate, config)
    assert is_valid is True
    assert reason is None


# ==============================================================================
# 7. 一票否决优先级仲裁测试 (evaluate_single_question)
# ==============================================================================


def test_tc_qq_29_priority_no_source_over_all() -> None:
    """TC-QQ-29: 同时命中四项缺陷时，首位裁定为 NO_SOURCE 且短路后续。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(
        stem="过短",  # 命中 AMBIGUITY
        source_snippet_ids=(),  # 命中 NO_SOURCE
    )
    prior = _build_candidate(stem="过短")  # 命中 DUPLICATE
    result, _is_degraded = evaluate_single_question(
        candidate=candidate,
        existing=(),
        prior_candidates=(prior,),
        config=config,
    )
    assert result.is_qualified is False
    assert result.unqualified_type == QualityCheckType.NO_SOURCE
    assert result.unqualified_reason == "缺少来源切片标识"
    # 短路：只有一项检查明细
    assert len(result.check_items) == 1
    assert result.check_items[0].check_type == QualityCheckType.NO_SOURCE


def test_tc_qq_30_priority_duplicate_over_conflict() -> None:
    """TC-QQ-30: 来源合格但同时命中 DUPLICATE 与 CONFLICT，裁定为 DUPLICATE。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(
        stem="二叉树遍历算法，下列关于前序遍历描述正确的是",
        embedding=(1.0, 0.0),
        answer="A",
    )
    existing = _build_existing(
        stem="二叉树遍历算法，下列关于前序遍历描述正确的是",
        embedding=(1.0, 0.0),  # cos = 1.0 >= 0.90 -> DUPLICATE
        answer="B",  # cos = 1.0 >= 0.88 且答案不同 -> CONFLICT
    )
    result, _is_degraded = evaluate_single_question(
        candidate=candidate,
        existing=(existing,),
        prior_candidates=(),
        config=config,
    )
    assert result.is_qualified is False
    assert result.unqualified_type == QualityCheckType.DUPLICATE
    assert len(result.check_items) == 2


# ==============================================================================
# 8. 批次质检入口与极端边界测试 (filter_qualified_questions, B-1, B-2, B-7)
# ==============================================================================


def test_tc_qq_31_b1_empty_candidates() -> None:
    """TC-QQ-31: B-1 候选题为空集合输入 -> 返回全空报告，无异常。"""
    report = filter_qualified_questions(candidates=())
    assert isinstance(report, QuestionQualityReport)
    assert report.total_candidates == 0
    assert report.qualified_count == 0
    assert report.unqualified_count == 0
    assert report.qualified_questions == ()
    assert report.unqualified_questions == ()
    assert report.results == ()
    assert report.is_degraded is False
    assert report.window_size_used == 0


def test_tc_qq_32_b2_batch_duplicate_sequence() -> None:
    """TC-QQ-32: B-2 批次内同题干重复，按 created_at_seq 保留首发题目。"""
    # 构造 3 道题，第 1 道与第 3 道题干相同
    q1 = _build_candidate(question_id="q-1", created_at_seq=1)
    q2 = _build_candidate(
        question_id="q-2", created_at_seq=2, stem="二叉树遍历算法，红黑树性质正确的是"
    )
    q3 = _build_candidate(question_id="q-3", created_at_seq=3)

    report = filter_qualified_questions(candidates=(q3, q1, q2))
    assert report.total_candidates == 3
    assert report.qualified_count == 2
    assert report.unqualified_count == 1

    # 首发 q1 合格，q2 合格，q3 被剔除且类型为 DUPLICATE
    qualified_ids = {q.question_id for q in report.qualified_questions}
    assert qualified_ids == {"q-1", "q-2"}
    unqualified = report.unqualified_questions[0]
    assert unqualified.question_id == "q-3"

    res_q3 = next(r for r in report.results if r.question_id == "q-3")
    assert res_q3.unqualified_type == QualityCheckType.DUPLICATE
    assert res_q3.unqualified_reason == "同批次内题干完全重复（保留首发题目）"


def test_tc_qq_33_b7_sliding_window_crop() -> None:
    """TC-QQ-33: B-7 传入 600 道已有题目，截取最近 500 道参与比对。"""
    config = QuestionQualityConfig(max_existing_questions_window=500)
    existing_list = [
        _build_existing(question_id=f"ex-{i}", stem=f"历史题干描述内容序号为 {i}")
        for i in range(600)
    ]
    candidate = _build_candidate()
    report = filter_qualified_questions(
        candidates=(candidate,),
        existing_questions=existing_list,
        config=config,
    )
    assert report.window_size_used == 500


def test_tc_qq_34_b4_overall_degraded_flag() -> None:
    """TC-QQ-34: B-4 向量不可用降级标注在报告中正确传递。"""
    candidate = _build_candidate(embedding=None)
    existing = _build_existing(embedding=None)
    report = filter_qualified_questions(
        candidates=(candidate,),
        existing_questions=(existing,),
    )
    assert report.is_degraded is True


def test_tc_qq_35_all_qualified_report() -> None:
    """TC-QQ-35: 批次全量题目质检合格通过报告。"""
    q1 = _build_candidate(question_id="q-1", created_at_seq=1)
    q2 = _build_candidate(
        question_id="q-2",
        created_at_seq=2,
        stem="关系型数据库事务，描述正确的是",
        source_text="关系型数据库事务具备ACID四大特性，包括原子性、一致性、隔离性与持久性。",
        analysis="ACID四大特性",
    )
    report = filter_qualified_questions(candidates=(q1, q2))
    assert report.total_candidates == 2
    assert report.qualified_count == 2
    assert report.unqualified_count == 0
    assert len(report.qualified_questions) == 2
    assert len(report.unqualified_questions) == 0
    assert all(r.is_qualified for r in report.results)
    assert all(len(r.check_items) == 4 for r in report.results)


# ==============================================================================
# 9. 完备性与分支覆盖扩展测试 (TC-QQ-36 ~ TC-QQ-43)
# ==============================================================================


def test_tc_qq_36_dto_immutability_and_tuple_coercion() -> None:
    """TC-QQ-36: DTO 传入 list 时自动转化为不可变 tuple。"""
    candidate = CandidateQuestion(
        question_id="q-list",
        stem="二叉树遍历算法，测试列表转换",
        question_type=QuestionType.SINGLE_CHOICE,
        answer="A",
        options=[{"key": "A", "content": "选项A"}],  # type: ignore[arg-type]
        source_snippet_ids=["snp-1", "snp-2"],  # type: ignore[arg-type]
        embedding=[0.1, 0.2],  # type: ignore[arg-type]
    )
    assert isinstance(candidate.options, tuple)
    assert isinstance(candidate.source_snippet_ids, tuple)
    assert isinstance(candidate.embedding, tuple)

    existing = ExistingQuestionReference(
        question_id="ex-list",
        stem="二叉树遍历算法，测试列表转换",
        question_type=QuestionType.SINGLE_CHOICE,
        answer="A",
        options=[{"key": "A", "content": "选项A"}],  # type: ignore[arg-type]
        embedding=[0.1, 0.2],  # type: ignore[arg-type]
    )
    assert isinstance(existing.options, tuple)
    assert isinstance(existing.embedding, tuple)


def test_tc_qq_37_conflict_stem_similarity_fallback_and_non_objective() -> None:
    """TC-QQ-37: 答案冲突检查中遇到已有题为非客观题跳过，以及无向量降级分支。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(
        stem="二叉树遍历算法，测试无向量冲突降级",
        embedding=None,
        answer="A",
    )
    existing_non_objective = _build_existing(
        question_id="ex-subjective",
        stem="二叉树遍历算法，测试无向量冲突降级",
        question_type=QuestionType.SHORT_ANSWER,
        embedding=None,
    )
    existing_objective_conflict = _build_existing(
        question_id="ex-conflict",
        stem="二叉树遍历算法，测试无向量冲突降级",
        question_type=QuestionType.SINGLE_CHOICE,
        answer="B",
        embedding=None,
    )

    is_valid, reason, score, is_degraded = check_answer_conflict(
        candidate=candidate,
        existing=(existing_non_objective, existing_objective_conflict),
        config=config,
    )
    assert is_valid is False
    assert reason == "题干高度相似但客观题标准答案冲突"
    assert is_degraded is True
    assert score is not None and score >= 0.88


def test_tc_qq_38_evaluate_single_question_conflict_veto() -> None:
    """TC-QQ-38: evaluate_single_question 触发 ANSWER_CONFLICT 一票否决与 3 项明细。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(
        stem="二叉树遍历算法，单题冲突否决测试",
        embedding=(1.0, 0.0),
        answer="A",
    )
    existing_same_stem = _build_existing(
        stem="二叉树遍历算法，不同表述题目",
        embedding=(0.89, math.sqrt(1 - 0.89**2)),  # cos = 0.89 >= 0.88, < 0.90 (不触发重复)
        answer="B",  # 触发冲突
    )
    result, _is_degraded = evaluate_single_question(
        candidate=candidate,
        existing=(existing_same_stem,),
        prior_candidates=(),
        config=config,
    )
    assert result.is_qualified is False
    assert result.unqualified_type == QualityCheckType.ANSWER_CONFLICT
    assert len(result.check_items) == 3


def test_tc_qq_39_evaluate_single_question_ambiguity_veto() -> None:
    """TC-QQ-39: evaluate_single_question 触发 AMBIGUITY 否决与 4 项明细。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(
        stem="二叉树遍历算法，单题歧义否决测试",
        options=(
            {"key": "A", "content": "相同选项内容"},
            {"key": "B", "content": "相同选项内容"},
        ),
    )
    result, _is_degraded = evaluate_single_question(
        candidate=candidate,
        existing=(),
        prior_candidates=(),
        config=config,
    )
    assert result.is_qualified is False
    assert result.unqualified_type == QualityCheckType.AMBIGUITY
    assert len(result.check_items) == 4


def test_tc_qq_40_single_choice_trigger_word_valid() -> None:
    """TC-QQ-40: 单选题中选项包含'以上都对'但正确答案仅为该项本身时，逻辑自洽通过。"""
    config = QuestionQualityConfig()
    candidate = _build_candidate(
        stem="二叉树遍历算法，下列选项均成立的是",
        question_type=QuestionType.SINGLE_CHOICE,
        options=(
            {"key": "A", "content": "前序遍历访问根"},
            {"key": "B", "content": "中序遍历访问左"},
            {"key": "C", "content": "以上都对"},
        ),
        answer="C",  # 只有 1 个答案，不冲突
    )
    is_valid, reason = check_ambiguity(candidate, config)
    assert is_valid is True
    assert reason is None


def test_tc_qq_41_other_question_types_empty_answer() -> None:
    """TC-QQ-41: 名词解释与案例分析题标准答案为空拦截。"""
    config = QuestionQualityConfig()
    cand_term = _build_candidate(
        question_type=QuestionType.TERM_EXPLANATION,
        answer="",
    )
    is_valid, reason = check_ambiguity(cand_term, config)
    assert is_valid is False
    assert reason == "参考答案内容为空"

    cand_case = _build_candidate(
        question_type=QuestionType.CASE_ANALYSIS,
        answer="   ",
    )
    is_valid, reason = check_ambiguity(cand_case, config)
    assert is_valid is False
    assert reason == "参考答案内容为空"


def test_tc_qq_42_parse_option_keys_variations() -> None:
    """TC-QQ-42: 测试选项答案解析：空字符串、无分隔符多字符、分隔符混用。"""
    from app.core.algorithms.question_quality import _parse_option_keys

    assert _parse_option_keys("") == frozenset()
    assert _parse_option_keys("   ") == frozenset()
    assert _parse_option_keys("ABCD") == frozenset({"A", "B", "C", "D"})
    assert _parse_option_keys("A; B、 C | D") == frozenset({"A", "B", "C", "D"})


def test_tc_qq_43_report_list_coercion() -> None:
    """TC-QQ-43: QuestionQualityReport 传入 list 自动转为不可变 tuple。"""
    cand = _build_candidate()
    result, _ = evaluate_single_question(cand, (), (), QuestionQualityConfig())
    report = QuestionQualityReport(
        qualified_questions=[cand],  # type: ignore[arg-type]
        unqualified_questions=[],  # type: ignore[arg-type]
        results=[result],  # type: ignore[arg-type]
        is_degraded=False,
        total_candidates=1,
        qualified_count=1,
        unqualified_count=0,
        window_size_used=0,
    )
    assert isinstance(report.qualified_questions, tuple)
    assert isinstance(report.unqualified_questions, tuple)
    assert isinstance(report.results, tuple)


def test_tc_qq_44_final_coverage_branches() -> None:
    """TC-QQ-44: 覆盖单题结果列表转换、无选项题目结构校验及主观题非空通过分支。"""
    from app.core.algorithms.question_quality import (
        QuestionQualityCheckItem,
        SingleQuestionQualityResult,
        _parse_option_keys,
    )

    item = QuestionQualityCheckItem(check_type=QualityCheckType.NO_SOURCE, is_passed=True)
    res = SingleQuestionQualityResult(
        question_id="q-res",
        is_qualified=True,
        unqualified_type=None,
        unqualified_reason=None,
        similarity_score=None,
        check_items=[item],  # type: ignore[arg-type]
    )
    assert isinstance(res.check_items, tuple)

    # 主观题有答案且无选项
    cand_valid_subjective = _build_candidate(
        question_type=QuestionType.SHORT_ANSWER,
        options=(),
        answer="这是标准参考答案内容",
    )
    is_valid, reason = check_ambiguity(cand_valid_subjective, QuestionQualityConfig())
    assert is_valid is True
    assert reason is None

    # 分隔符连续出现
    assert _parse_option_keys("A,,,B;;;C") == frozenset({"A", "B", "C"})
