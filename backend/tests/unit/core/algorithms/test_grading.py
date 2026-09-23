"""Unit tests for grading threshold and answer matching pure algorithm kernel.

Verifies:
- Objective question normalization and offline grading (single choice, multiple choice,
  true/false multilingual mapping, fill-in-blank normalization & multi-candidate/multi-blank)
- Subjective question double threshold boundaries (0.45 offline wrong, 0.82 offline correct,
  open interval (0.45, 0.82) transition to AI)
- Pairwise negation inversion tests (polarity reversal causes AI transition / score zero)
- 4 categories of LLM transition arbitration decision table (TC-D-01 to TC-D-12)
- Extreme inputs, robustness defenses & performance benchmarks
- Zero external I/O, zero network/database dependencies, 0 mock
"""

import math
import time

import pytest

from app.core.algorithms.grading import (
    CHINESE_NEGATION_WORDS,
    DEFAULT_KEYWORD_HIT_RATIO_THRESHOLD,
    DEFAULT_LOWER_SIMILARITY_THRESHOLD,
    DEFAULT_RUBRIC_COVERAGE_WEIGHT,
    DEFAULT_SEMANTIC_SIMILARITY_WEIGHT,
    DEFAULT_UPPER_SIMILARITY_THRESHOLD,
    DEFAULT_ZERO_COVERAGE_HIGH_SIMILARITY_THRESHOLD,
    LOWER_SIMILARITY_THRESHOLD,
    MAX_SUBJECTIVE_ANSWER_LENGTH,
    SCORE_ROUNDING_UNIT,
    UPPER_SIMILARITY_THRESHOLD,
    GradingConfig,
    GradingMethod,
    GradingResult,
    GradingRubricItem,
    ObjectiveGradingRule,
    QuestionType,
    TransitionReason,
    arbitrate_llm_transition,
    calculate_cosine_similarity,
    calculate_text_lexical_similarity,
    check_negation_inversion,
    detect_negation_inversion,
    detect_sentence_negation,
    evaluate_subjective_rubric,
    grade_objective_question,
    match_and_grade_answer,
    normalize_boolean_answer,
    normalize_fill_blank_text,
    normalize_objective_token,
)


class TestObjectiveGrading:
    """客观题规范化与离线判分测试套件 (FR-37, FR-38)。"""

    def test_constants_and_aliases(self) -> None:
        """测试核心常量与别名定义一致性。"""
        assert DEFAULT_UPPER_SIMILARITY_THRESHOLD == 0.82
        assert UPPER_SIMILARITY_THRESHOLD == 0.82
        assert DEFAULT_LOWER_SIMILARITY_THRESHOLD == 0.45
        assert LOWER_SIMILARITY_THRESHOLD == 0.45
        assert DEFAULT_RUBRIC_COVERAGE_WEIGHT == 0.60
        assert DEFAULT_SEMANTIC_SIMILARITY_WEIGHT == 0.40
        assert DEFAULT_KEYWORD_HIT_RATIO_THRESHOLD == 0.60
        assert DEFAULT_ZERO_COVERAGE_HIGH_SIMILARITY_THRESHOLD == 0.55
        assert MAX_SUBJECTIVE_ANSWER_LENGTH == 2000
        assert SCORE_ROUNDING_UNIT == 0.5
        assert "不" in CHINESE_NEGATION_WORDS
        assert "并非" in CHINESE_NEGATION_WORDS

    def test_direct_helper_functions(self) -> None:
        """直接测试规范化辅助纯函数。"""
        assert normalize_objective_token("(A)", QuestionType.SINGLE_CHOICE) == "A"
        assert normalize_objective_token("第1题: (A)", QuestionType.SINGLE_CHOICE) == "A"
        assert normalize_objective_token("", QuestionType.SINGLE_CHOICE) == ""
        assert normalize_objective_token("B, A", QuestionType.MULTIPLE_CHOICE) == "AB"
        assert normalize_boolean_answer("正确") is True
        assert normalize_boolean_answer("错误") is False
        assert normalize_boolean_answer("") is None
        assert normalize_fill_blank_text("１２３") == "123"
        assert normalize_fill_blank_text("") == ""
        assert detect_sentence_negation("这是不对的") is True
        assert detect_sentence_negation("这是对的") is False

    def test_single_choice_normalization_and_match(self) -> None:
        """测试单选题大小写转换、首尾空白与包裹符号规范化清洗。"""
        # (A) -> A
        result_paren = match_and_grade_answer(
            question_type=QuestionType.SINGLE_CHOICE,
            user_answer="(A)",
            reference_answer="A",
            max_score=2.0,
        )
        assert result_paren.is_correct is True
        assert result_paren.score == 2.0
        assert result_paren.requires_llm is False
        assert result_paren.grading_method == GradingMethod.OFFLINE_RULE

        # [b] -> B
        result_bracket = match_and_grade_answer(
            question_type=QuestionType.SINGLE_CHOICE,
            user_answer=" [b] ",
            reference_answer="B",
        )
        assert result_bracket.is_correct is True
        assert result_bracket.score == 1.0

        # C. -> C
        result_dot = match_and_grade_answer(
            question_type=QuestionType.SINGLE_CHOICE,
            user_answer="C.",
            reference_answer="C",
        )
        assert result_dot.is_correct is True
        assert result_dot.score == 1.0

        # D、 -> D
        result_pause = match_and_grade_answer(
            question_type=QuestionType.SINGLE_CHOICE,
            user_answer="D、",
            reference_answer="D",
        )
        assert result_pause.is_correct is True
        assert result_pause.score == 1.0

    def test_single_choice_invalid_token_and_wrong(self) -> None:
        """测试单选题无效格式输入与错误选项判定。"""
        # 输入两个字母判定无效
        result_invalid = match_and_grade_answer(
            question_type=QuestionType.SINGLE_CHOICE,
            user_answer="AB",
            reference_answer="A",
        )
        assert result_invalid.is_correct is False
        assert result_invalid.score == 0.0

        # 选项不匹配
        result_wrong = match_and_grade_answer(
            question_type=QuestionType.SINGLE_CHOICE,
            user_answer="B",
            reference_answer="A",
        )
        assert result_wrong.is_correct is False
        assert result_wrong.score == 0.0

    def test_multiple_choice_sort_and_punctuation(self) -> None:
        """测试多选题乱序输入、多余字符过滤与去重升序拼装。"""
        # 乱序与小写："b, a, B" -> "AB"
        result_comma = match_and_grade_answer(
            question_type=QuestionType.MULTIPLE_CHOICE,
            user_answer="b, a, B",
            reference_answer="AB",
            max_score=3.0,
        )
        assert result_comma.is_correct is True
        assert result_comma.score == 3.0

        # 分号分隔与乱序："c; a; b" -> "ABC"
        result_semicolon = match_and_grade_answer(
            question_type=QuestionType.MULTIPLE_CHOICE,
            user_answer="c; a; b",
            reference_answer="A; B; C",
        )
        assert result_semicolon.is_correct is True
        assert result_semicolon.score == 1.0

        # 斜杠分隔与逆序："D / C / B / A" -> "ABCD"
        result_slash = match_and_grade_answer(
            question_type=QuestionType.MULTIPLE_CHOICE,
            user_answer="D / C / B / A",
            reference_answer="ABCD",
        )
        assert result_slash.is_correct is True
        assert result_slash.score == 1.0

    def test_multiple_choice_partial_or_over_selected(self) -> None:
        """测试多选题漏选、多选与错选一票否决得 0 分。"""
        # 漏选
        result_under = match_and_grade_answer(
            question_type=QuestionType.MULTIPLE_CHOICE,
            user_answer="AB",
            reference_answer="ABC",
        )
        assert result_under.is_correct is False
        assert result_under.score == 0.0

        # 多选
        result_over = match_and_grade_answer(
            question_type=QuestionType.MULTIPLE_CHOICE,
            user_answer="ABCD",
            reference_answer="ABC",
        )
        assert result_over.is_correct is False
        assert result_over.score == 0.0

        # 完全错误
        result_none = match_and_grade_answer(
            question_type=QuestionType.MULTIPLE_CHOICE,
            user_answer="D",
            reference_answer="ABC",
        )
        assert result_none.is_correct is False
        assert result_none.score == 0.0

        # 无字母非空字符
        result_no_letters = match_and_grade_answer(
            question_type=QuestionType.MULTIPLE_CHOICE,
            user_answer="123",
            reference_answer="AB",
        )
        assert result_no_letters.is_correct is False
        assert result_no_letters.score == 0.0

    def test_true_false_multilingual_mapping(self) -> None:
        """测试判断题多语态真假表达归一化映射。"""
        positive_samples = ("True", "TRUE", "T", "1", "YES", "Y", "对", "正确", "是", "V", "√")
        for sample in positive_samples:
            result = match_and_grade_answer(
                question_type=QuestionType.TRUE_FALSE,
                user_answer=sample,
                reference_answer="True",
            )
            assert result.is_correct is True, f"Failed for positive sample: {sample}"
            assert result.score == 1.0

        negative_samples = (
            "False",
            "FALSE",
            "F",
            "0",
            "NO",
            "N",
            "错",
            "错误",
            "否",
            "X",
            "×",
        )
        for sample in negative_samples:
            result = match_and_grade_answer(
                question_type=QuestionType.TRUE_FALSE,
                user_answer=sample,
                reference_answer="False",
            )
            assert result.is_correct is True, f"Failed for negative sample: {sample}"
            assert result.score == 1.0

    def test_true_false_mismatch_and_unrecognized(self) -> None:
        """测试判断题真假不一致与无法解析的异常输入。"""
        result_mismatch = match_and_grade_answer(
            question_type=QuestionType.TRUE_FALSE,
            user_answer="对",
            reference_answer="错",
        )
        assert result_mismatch.is_correct is False
        assert result_mismatch.score == 0.0

        result_unrecognized = match_and_grade_answer(
            question_type=QuestionType.TRUE_FALSE,
            user_answer="也许吧",
            reference_answer="True",
        )
        assert result_unrecognized.is_correct is False
        assert result_unrecognized.score == 0.0

        result_bad_reference = match_and_grade_answer(
            question_type=QuestionType.TRUE_FALSE,
            user_answer="True",
            reference_answer="未定义",
        )
        assert result_bad_reference.is_correct is False
        assert result_bad_reference.score == 0.0

    def test_fill_in_blank_normalization_and_equivalent_candidates(self) -> None:
        """测试填空题全半角标点、数字归一化与多等价候选答案。"""
        # 全角数字转半角
        result_fullwidth = match_and_grade_answer(
            question_type=QuestionType.FILL_IN_BLANK,
            user_answer="１２３",
            reference_answer="123",
        )
        assert result_fullwidth.is_correct is True
        assert result_fullwidth.score == 1.0

        # 中文数字转阿拉伯数字
        result_chinese_num = match_and_grade_answer(
            question_type=QuestionType.FILL_IN_BLANK,
            user_answer="一二三",
            reference_answer="123",
        )
        assert result_chinese_num.is_correct is True
        assert result_chinese_num.score == 1.0

        # 中文单独数字 "十" 转 "10"
        result_ten = match_and_grade_answer(
            question_type=QuestionType.FILL_IN_BLANK,
            user_answer="十",
            reference_answer="10",
        )
        assert result_ten.is_correct is True
        assert result_ten.score == 1.0

        # 多候选答案比对 (以 | 分隔)
        result_candidate_pipe = match_and_grade_answer(
            question_type=QuestionType.FILL_IN_BLANK,
            user_answer="传输控制协议",
            reference_answer="TCP/IP | 传输控制协议",
        )
        assert result_candidate_pipe.is_correct is True
        assert result_candidate_pipe.score == 1.0

        # 多候选答案比对 (以 /// 分隔)
        result_candidate_slash = match_and_grade_answer(
            question_type=QuestionType.FILL_IN_BLANK,
            user_answer="tcp/ip",
            reference_answer="TCP/IP /// 传输控制协议",
        )
        assert result_candidate_slash.is_correct is True

        # 不匹配
        result_candidate_wrong = match_and_grade_answer(
            question_type=QuestionType.FILL_IN_BLANK,
            user_answer="HTTP",
            reference_answer="TCP/IP | 传输控制协议",
        )
        assert result_candidate_wrong.is_correct is False
        assert result_candidate_wrong.score == 0.0

    def test_fill_in_blank_multi_blanks(self) -> None:
        """测试多空填空题（分号或换行分隔各空）。"""
        reference = "TCP/IP | 传输控制协议 ; UDP | 用户数据报协议"

        # 两空完全正确
        result_correct = match_and_grade_answer(
            question_type=QuestionType.FILL_IN_BLANK,
            user_answer="TCP/IP ; UDP",
            reference_answer=reference,
            max_score=2.0,
        )
        assert result_correct.is_correct is True
        assert result_correct.score == 2.0

        # 换行分隔两空
        result_newline = match_and_grade_answer(
            question_type=QuestionType.FILL_IN_BLANK,
            user_answer="传输控制协议\n用户数据报协议",
            reference_answer=reference,
            max_score=2.0,
        )
        assert result_newline.is_correct is True
        assert result_newline.score == 2.0

        # 空数不匹配
        result_mismatch_count = match_and_grade_answer(
            question_type=QuestionType.FILL_IN_BLANK,
            user_answer="TCP/IP",
            reference_answer=reference,
        )
        assert result_mismatch_count.is_correct is False
        assert result_mismatch_count.score == 0.0

        # 部分空错误
        result_partial_wrong = match_and_grade_answer(
            question_type=QuestionType.FILL_IN_BLANK,
            user_answer="TCP/IP ; HTTP",
            reference_answer=reference,
        )
        assert result_partial_wrong.is_correct is False
        assert result_partial_wrong.score == 0.0


class TestSubjectiveThresholdBoundaries:
    """主观题双阈值边界值与分流决策测试套件 (FR-39, FR-40)。"""

    def test_d01_upper_threshold_offline_correct(self) -> None:
        """TC-D-01: match_score = 0.85 >= 0.82 离线判对得高分。"""
        # point_coverage=0.90, semantic_sim=0.80 -> 0.90*0.6 + 0.80*0.4 = 0.86 >= 0.82
        rubric = (
            GradingRubricItem(
                point_id="p1",
                description="ACID特性",
                weight=1.0,
                keywords=("原子性", "一致性", "隔离性", "持久性"),
            ),
        )
        # 提供高相似度向量 (cosine approx 0.85)
        vec_user = (1.0, 0.5, 0.2, 0.1)
        vec_ref = (1.0, 0.48, 0.22, 0.09)

        result = match_and_grade_answer(
            question_type=QuestionType.SHORT_ANSWER,
            user_answer="事务具有原子性、一致性、隔离性与持久性四大核心特征。",
            reference_answer="事务必须满足原子性、一致性、隔离性和持久性（ACID）。",
            max_score=10.0,
            grading_rubric=rubric,
            user_embedding=vec_user,
            reference_embedding=vec_ref,
        )
        assert result.requires_llm is False
        assert result.grading_method == GradingMethod.OFFLINE_RULE
        assert result.is_correct is True
        assert result.match_score is not None
        assert result.match_score >= DEFAULT_UPPER_SIMILARITY_THRESHOLD
        assert result.score > 8.0

    def test_d02_exact_upper_threshold_boundary(self) -> None:
        """TC-D-02: 恰好等于上阈值 0.8200 属于离线判对区间。"""
        config = GradingConfig(
            upper_similarity_threshold=0.82,
            lower_similarity_threshold=0.45,
            rubric_coverage_weight=0.60,
            semantic_similarity_weight=0.40,
        )
        # arbitrate_llm_transition 直接验证
        requires_llm, reason = arbitrate_llm_transition(
            match_score=0.82,
            point_coverage=0.80,
            semantic_similarity=0.85,
            has_negation_inversion=False,
            has_multiple_equivalents=False,
            rubric_empty=False,
            config=config,
        )
        assert requires_llm is False
        assert reason is None

    def test_d03_lower_threshold_offline_wrong(self) -> None:
        """TC-D-03: match_score = 0.30 <= 0.45 离线判错得 0 分。"""
        rubric = (
            GradingRubricItem(
                point_id="p1",
                description="ACID特性",
                weight=1.0,
                keywords=("原子性", "一致性", "隔离性", "持久性"),
            ),
        )
        result = match_and_grade_answer(
            question_type=QuestionType.SHORT_ANSWER,
            user_answer="今天天气很好适合出门散步喝咖啡。",
            reference_answer="事务必须满足原子性、一致性、隔离性和持久性（ACID）。",
            max_score=10.0,
            grading_rubric=rubric,
        )
        assert result.requires_llm is False
        assert result.grading_method == GradingMethod.OFFLINE_RULE
        assert result.is_correct is False
        assert result.score == 0.0

    def test_d04_exact_lower_threshold_boundary(self) -> None:
        """TC-D-04: 恰好等于下阈值 0.4500 属于离线判错区间。"""
        config = GradingConfig(
            upper_similarity_threshold=0.82,
            lower_similarity_threshold=0.45,
        )
        requires_llm, reason = arbitrate_llm_transition(
            match_score=0.45,
            point_coverage=0.40,
            semantic_similarity=0.50,
            has_negation_inversion=False,
            has_multiple_equivalents=False,
            rubric_empty=False,
            config=config,
        )
        assert requires_llm is False
        assert reason is None

    def test_d05_condition_1_uncertain_range_middle(self) -> None:
        """TC-D-05: match_score = 0.65 处于不确定开区间 (0.45, 0.82)，转 AI。"""
        config = GradingConfig()
        requires_llm, reason = arbitrate_llm_transition(
            match_score=0.65,
            point_coverage=0.60,
            semantic_similarity=0.70,
            has_negation_inversion=False,
            has_multiple_equivalents=False,
            rubric_empty=False,
            config=config,
        )
        assert requires_llm is True
        assert reason == TransitionReason.UNCERTAIN_RANGE

    def test_d06_condition_1_lower_open_boundary(self) -> None:
        """TC-D-06: 边界值 0.4501 落在开区间 (0.45, 0.82) 内，转 AI。"""
        config = GradingConfig()
        requires_llm, reason = arbitrate_llm_transition(
            match_score=0.4501,
            point_coverage=0.40,
            semantic_similarity=0.50,
            has_negation_inversion=False,
            has_multiple_equivalents=False,
            rubric_empty=False,
            config=config,
        )
        assert requires_llm is True
        assert reason == TransitionReason.UNCERTAIN_RANGE

    def test_d07_condition_1_upper_open_boundary(self) -> None:
        """TC-D-07: 边界值 0.8199 落在开区间 (0.45, 0.82) 内，转 AI。"""
        config = GradingConfig()
        requires_llm, reason = arbitrate_llm_transition(
            match_score=0.8199,
            point_coverage=0.80,
            semantic_similarity=0.84,
            has_negation_inversion=False,
            has_multiple_equivalents=False,
            rubric_empty=False,
            config=config,
        )
        assert requires_llm is True
        assert reason == TransitionReason.UNCERTAIN_RANGE

    def test_score_half_rounding(self) -> None:
        """测试 0.5 分粒度四舍五入正确核算。"""
        # match_score 0.82, max_score 10.0 -> raw 8.2 -> round to 8.0
        rubric = (
            GradingRubricItem(
                point_id="p1",
                description="desc",
                weight=1.0,
                keywords=("核心要点",),
            ),
        )
        result = match_and_grade_answer(
            question_type=QuestionType.SHORT_ANSWER,
            user_answer="作答包含核心要点并进行了阐述",
            reference_answer="标准答案必须包含核心要点",
            max_score=10.0,
            grading_rubric=rubric,
            user_embedding=(1.0, 0.0),
            reference_embedding=(1.0, 0.0),
        )
        # 验证得分舍入为 0.5 的倍数
        assert result.score % 0.5 == 0.0


class TestNegationInversionPair:
    """成对否定词反转专项用例测试套件 (AGENTS.md 硬性门槛)。"""

    def test_pairwise_positive_polarity(self) -> None:
        """TC-PAIR-01: 正向作答：'关系型数据库完全支持事务的 ACID 特性' 离线判对满分。"""
        reference = "关系型数据库支持事务的 ACID 特性"
        user_positive = "关系型数据库完全支持事务的 ACID 特性"
        rubric = (
            GradingRubricItem(
                point_id="p1",
                description="支持 ACID 特性",
                weight=1.0,
                keywords=("支持", "事务", "ACID", "特性"),
            ),
        )

        result_positive = match_and_grade_answer(
            question_type=QuestionType.SHORT_ANSWER,
            user_answer=user_positive,
            reference_answer=reference,
            max_score=5.0,
            grading_rubric=rubric,
        )
        assert result_positive.is_correct is True
        assert result_positive.requires_llm is False
        assert result_positive.grading_method == GradingMethod.OFFLINE_RULE
        assert result_positive.score > 0.0

    def test_pairwise_negative_polarity(self) -> None:
        """TC-PAIR-02: 反向配对：增加关键否定词触发否定词反转，绝不离线判对。"""
        reference = "关系型数据库支持事务的 ACID 特性"
        user_negative = "关系型数据库不支持事务的 ACID 特性"
        rubric = (
            GradingRubricItem(
                point_id="p1",
                description="支持 ACID 特性",
                weight=1.0,
                keywords=("支持", "事务", "ACID", "特性"),
            ),
        )

        result_negative = match_and_grade_answer(
            question_type=QuestionType.SHORT_ANSWER,
            user_answer=user_negative,
            reference_answer=reference,
            max_score=5.0,
            grading_rubric=rubric,
        )
        assert isinstance(result_negative, GradingResult)
        # 核心铁律：绝对禁止离线判对！必须转 AI (NEGATION_INVERSION) 或判错 0 分
        assert result_negative.is_correct is False
        if result_negative.requires_llm:
            assert result_negative.transition_reason == TransitionReason.NEGATION_INVERSION
        else:
            assert result_negative.score == 0.0

    def test_clause_scope_negation_isolation(self) -> None:
        """TC-PAIR-03: 跨分句否定词隔离：否定词位于另一独立分句且不修饰采分点时不误判。"""
        user_mixed = "虽然系统不支持热插拔；但完全支持事务的 ACID 特性！"
        rubric = (
            GradingRubricItem(
                point_id="p1",
                description="支持事务的 ACID 特性",
                weight=1.0,
                keywords=("事务", "ACID", "特性"),
            ),
        )
        point_coverage, hit_keywords, _missing_keywords, has_negation = evaluate_subjective_rubric(
            user_mixed, rubric
        )
        assert point_coverage == 1.0
        assert "ACID" in hit_keywords
        assert has_negation is False

    def test_detect_negation_inversion_direct(self) -> None:
        """直接测试 detect_negation_inversion 纯函数与别名 check_negation_inversion。"""
        # 反转存在
        inversion, message = detect_negation_inversion(
            user_text="该方案并不满足高可用需求",
            reference_text="该方案满足高可用需求",
            focus_keywords=("满足", "高可用"),
        )
        assert inversion is True
        assert message is not None
        assert "否定词修饰" in message

        # 别名测试
        alias_inversion, _ = check_negation_inversion(
            user_text="该方案并不满足高可用需求",
            reference_text="该方案满足高可用需求",
        )
        assert alias_inversion is True

        # 反转不存在
        no_inversion, _ = detect_negation_inversion(
            user_text="该方案充分满足高可用需求",
            reference_text="该方案满足高可用需求",
            focus_keywords=("满足", "高可用"),
        )
        assert no_inversion is False

        # 单字符中文参考文本（不产生 >= 2 的中文词块）
        single_char_inversion, _ = detect_negation_inversion(
            user_text="不用",
            reference_text="用",
        )
        assert single_char_inversion is False


class TestArbitrateLLMTransitionDecisionTable:
    """4 类转 AI 决策表全组合覆盖测试套件 (Spec 5.1 & Plan 5.1)。"""

    def setup_method(self) -> None:
        self.config = GradingConfig()

    def test_d08_condition_2_negation_inversion_high_sim(self) -> None:
        """TC-D-08: 高相似度但存在否定词反转，强制触发优先级 1 (NEGATION_INVERSION)。"""
        requires_llm, reason = arbitrate_llm_transition(
            match_score=0.88,
            point_coverage=0.0,
            semantic_similarity=0.85,
            has_negation_inversion=True,
            has_multiple_equivalents=False,
            rubric_empty=False,
            config=self.config,
        )
        assert requires_llm is True
        assert reason == TransitionReason.NEGATION_INVERSION

    def test_d09_condition_3_multiple_equivalents(self) -> None:
        """TC-D-09: 存在多个等价表达，触发优先级 2 (MULTIPLE_EQUIVALENTS_OR_EMPTY_RUBRIC)。"""
        requires_llm, reason = arbitrate_llm_transition(
            match_score=0.85,
            point_coverage=1.00,
            semantic_similarity=0.80,
            has_negation_inversion=False,
            has_multiple_equivalents=True,
            rubric_empty=False,
            config=self.config,
        )
        assert requires_llm is True
        assert reason == TransitionReason.MULTIPLE_EQUIVALENTS_OR_EMPTY_RUBRIC

    def test_d10_condition_3_empty_rubric(self) -> None:
        """TC-D-10: 评分细则为空，触发优先级 2 (MULTIPLE_EQUIVALENTS_OR_EMPTY_RUBRIC)。"""
        requires_llm, reason = arbitrate_llm_transition(
            match_score=0.36,
            point_coverage=0.00,
            semantic_similarity=0.90,
            has_negation_inversion=False,
            has_multiple_equivalents=False,
            rubric_empty=True,
            config=self.config,
        )
        assert requires_llm is True
        assert reason == TransitionReason.MULTIPLE_EQUIVALENTS_OR_EMPTY_RUBRIC

    def test_d11_condition_4_zero_cov_high_sim(self) -> None:
        """TC-D-11: 要点覆盖为 0 且相似度 > 0.55，触发优先级 3 (ZERO_COVERAGE_HIGH_SIMILARITY)。"""
        requires_llm, reason = arbitrate_llm_transition(
            match_score=0.24,
            point_coverage=0.00,
            semantic_similarity=0.60,
            has_negation_inversion=False,
            has_multiple_equivalents=False,
            rubric_empty=False,
            config=self.config,
        )
        assert requires_llm is True
        assert reason == TransitionReason.ZERO_COVERAGE_HIGH_SIMILARITY

    def test_d12_zero_cov_low_sim_offline_wrong(self) -> None:
        """TC-D-12: 要点覆盖为 0 且语义相似度 0.40 <= 0.55，不满足转 AI 条件，离线判错。"""
        requires_llm, reason = arbitrate_llm_transition(
            match_score=0.16,
            point_coverage=0.00,
            semantic_similarity=0.40,
            has_negation_inversion=False,
            has_multiple_equivalents=False,
            rubric_empty=False,
            config=self.config,
        )
        assert requires_llm is False
        assert reason is None

    def test_priority_arbitration_order(self) -> None:
        """测试 4 类转 AI 条件严格遵循优先级仲裁。"""
        # 同时满足 P1(否定词反转) 与 P2(多等价) -> P1 胜出
        _, reason_p1 = arbitrate_llm_transition(
            match_score=0.88,
            point_coverage=0.0,
            semantic_similarity=0.85,
            has_negation_inversion=True,
            has_multiple_equivalents=True,
            rubric_empty=False,
            config=self.config,
        )
        assert reason_p1 == TransitionReason.NEGATION_INVERSION

        # 同时满足 P2(多等价) 与 P3(0覆盖高相似) -> P2 胜出
        _, reason_p2 = arbitrate_llm_transition(
            match_score=0.24,
            point_coverage=0.0,
            semantic_similarity=0.60,
            has_negation_inversion=False,
            has_multiple_equivalents=True,
            rubric_empty=False,
            config=self.config,
        )
        assert reason_p2 == TransitionReason.MULTIPLE_EQUIVALENTS_OR_EMPTY_RUBRIC

        # 同时满足 P3(0覆盖高相似) 与 P4(不确定区间) -> P3 胜出
        # 构造 point_coverage=0, semantic_sim=0.70 (>0.55), match_score=0.28 (若为0.50在区间内)
        _, reason_p3 = arbitrate_llm_transition(
            match_score=0.50,
            point_coverage=0.0,
            semantic_similarity=0.70,
            has_negation_inversion=False,
            has_multiple_equivalents=False,
            rubric_empty=False,
            config=self.config,
        )
        assert reason_p3 == TransitionReason.ZERO_COVERAGE_HIGH_SIMILARITY


class TestExtremeInputsAndSafety:
    """极限输入与鲁棒性防御测试套件。"""

    def test_empty_or_whitespace_unanswered(self) -> None:
        """TC-DEF-01: 作答为空字符串或纯空白时立即短路标记未作答。"""
        for empty_text in ("", "   ", "\t\n"):
            result = match_and_grade_answer(
                question_type=QuestionType.SHORT_ANSWER,
                user_answer=empty_text,
                reference_answer="标准答案",
            )
            assert result.is_answered is False
            assert result.is_correct is False
            assert result.score == 0.0
            assert result.requires_llm is False
            assert result.grading_method == GradingMethod.OFFLINE_RULE

    def test_answer_exceeding_2000_chars_truncated(self) -> None:
        """TC-DEF-02: 主观题作答超过 2000 字符安全截断并打标。"""
        long_answer = "知识点内容" * 500  # 2500 字符
        result = match_and_grade_answer(
            question_type=QuestionType.TERM_EXPLANATION,
            user_answer=long_answer,
            reference_answer="知识点内容",
        )
        assert result.details.get("is_truncated") is True
        assert result.details.get("original_length") == 2500

    def test_exact_match_full_score_fast_path(self) -> None:
        """测试作答与参考答案完全一致快速满分通道。"""
        result = match_and_grade_answer(
            question_type=QuestionType.CASE_ANALYSIS,
            user_answer="  完全一致的标准作答文本  ",
            reference_answer="完全一致的标准作答文本",
            max_score=15.0,
        )
        assert result.is_correct is True
        assert result.score == 15.0
        assert result.match_score == 1.0
        assert result.requires_llm is False
        assert result.grading_method == GradingMethod.OFFLINE_RULE

    def test_cosine_similarity_edge_cases(self) -> None:
        """TC-DEF-03: 向量余弦相似度边界防御（None、维度不匹配、全零向量）。"""
        assert calculate_cosine_similarity(None, (1.0, 2.0)) == 0.0
        assert calculate_cosine_similarity((1.0, 2.0), None) == 0.0
        assert calculate_cosine_similarity((), ()) == 0.0
        assert calculate_cosine_similarity((1.0, 2.0), (1.0, 2.0, 3.0)) == 0.0
        assert calculate_cosine_similarity((0.0, 0.0), (0.0, 0.0)) == 0.0
        assert calculate_cosine_similarity((1.0, 0.0), (0.0, 1.0)) == 0.0

        # 正交与平行
        unit_a = (1.0, 0.0, 0.0)
        unit_b = (1.0, 0.0, 0.0)
        assert math.isclose(calculate_cosine_similarity(unit_a, unit_b), 1.0)

    def test_lexical_similarity_edge_cases(self) -> None:
        """测试文本降级相似度边界（空文本、短文本与完全一致）。"""
        assert calculate_text_lexical_similarity("", "参考答案") == 0.0
        assert calculate_text_lexical_similarity("用户答案", "") == 0.0
        assert calculate_text_lexical_similarity("abc", "abc") == 1.0
        assert calculate_text_lexical_similarity("a", "b") == 0.0

    def test_invalid_grading_config_raises(self) -> None:
        """TC-DEF-04: 非法配置参数边界校验防御。"""
        # lower >= upper
        with pytest.raises(ValueError, match=r"0\.0 <= lower_similarity_threshold"):
            GradingConfig(lower_similarity_threshold=0.85, upper_similarity_threshold=0.80)

        # 权重和 != 1.0
        with pytest.raises(ValueError, match="Sum of rubric_coverage_weight"):
            GradingConfig(rubric_coverage_weight=0.5, semantic_similarity_weight=0.6)

        # 关键词命中阈值非法
        with pytest.raises(ValueError, match="keyword_hit_ratio_threshold"):
            GradingConfig(keyword_hit_ratio_threshold=0.0)
        with pytest.raises(ValueError, match="keyword_hit_ratio_threshold"):
            GradingConfig(keyword_hit_ratio_threshold=1.5)

        # 0覆盖阈值非法
        with pytest.raises(ValueError, match="zero_coverage_high_similarity_threshold"):
            GradingConfig(zero_coverage_high_similarity_threshold=-0.1)

        # 长度上限非法
        with pytest.raises(ValueError, match="max_answer_length must be positive"):
            GradingConfig(max_answer_length=0)

        # 舍入单位非法
        with pytest.raises(ValueError, match="score_rounding_unit must be positive"):
            GradingConfig(score_rounding_unit=0.0)

    def test_invalid_max_score_and_question_type_raises(self) -> None:
        """TC-DEF-05: 非法满分值与题型枚举校验防御。"""
        with pytest.raises(ValueError, match="max_score must be positive"):
            match_and_grade_answer(
                question_type=QuestionType.SINGLE_CHOICE,
                user_answer="A",
                reference_answer="A",
                max_score=0.0,
            )

        with pytest.raises(ValueError, match="Invalid question_type"):
            match_and_grade_answer(
                question_type="invalid_question_type",
                user_answer="A",
                reference_answer="A",
            )

        with pytest.raises(ValueError, match="Invalid question_type"):
            match_and_grade_answer(
                question_type=12345,  # type: ignore[arg-type]
                user_answer="A",
                reference_answer="A",
            )

    def test_rubric_with_dict_and_custom_options(self) -> None:
        """测试评分细则支持字典传入与客观测题未受支持类型防御。"""
        dict_rubric = [
            {
                "point_id": "pt-01",
                "description": "说明概念",
                "weight": 2.0,
                "keywords": ("概念", "要点"),
            }
        ]
        result = match_and_grade_answer(
            question_type=QuestionType.SHORT_ANSWER,
            user_answer="作答充分说明了概念和核心要点内容",
            reference_answer="说明概念和要点",
            grading_rubric=dict_rubric,
            user_embedding=(1.0, 0.5),
            reference_embedding=(1.0, 0.5),
        )
        assert result.is_correct is True
        assert "概念" in result.hit_keywords
        assert "要点" in result.hit_keywords

        # grade_objective_question 传入不受支持的题型
        is_correct, score, reasoning = grade_objective_question(
            question_type="unsupported_type",
            user_answer="A",
            reference_answer="A",
        )
        assert is_correct is False
        assert score == 0.0
        assert "不支持的客观题类型" in reasoning

    def test_rubric_zero_weight_and_empty_keywords(self) -> None:
        """测试评分细则权重为0及要点无关键词的容错分支。"""
        rubric_zero_weight = [
            GradingRubricItem(point_id="p0", description="零权重", weight=0.0, keywords=("测试",)),
            GradingRubricItem(point_id="p1", description="无关键词", weight=0.0, keywords=()),
        ]
        point_coverage, hits, _missing, _neg = evaluate_subjective_rubric(
            "包含测试内容", rubric_zero_weight
        )
        assert point_coverage == 0.0
        assert "测试" in hits

    def test_objective_grading_rule_defaults(self) -> None:
        """测试 ObjectiveGradingRule 默认参数不可变性。"""
        rule = ObjectiveGradingRule()
        assert rule.case_sensitive is False
        assert rule.ignore_whitespace is True
        assert "|" in rule.candidate_delimiters


class TestPerformanceBenchmark:
    """性能基准测试套件。"""

    def test_objective_grading_performance(self) -> None:
        """客观题批量 1000 次判分延迟应显著低于 0.1ms/次 (1000次 < 100ms)。"""
        start_time = time.perf_counter()
        for _ in range(1000):
            grade_objective_question(
                question_type=QuestionType.SINGLE_CHOICE,
                user_answer="(A)",
                reference_answer="A",
            )
        duration_ms = (time.perf_counter() - start_time) * 1000
        # 1000 次操作总耗时必须严格 < 100ms
        assert duration_ms < 100.0, f"Objective grading too slow: {duration_ms:.2f}ms"

    def test_subjective_grading_performance(self) -> None:
        """主观题批量 100 次纯文本判定耗时应低于 50ms。"""
        rubric = (
            GradingRubricItem(
                point_id="p1",
                description="desc",
                weight=1.0,
                keywords=("核心概念", "基本原理"),
            ),
        )
        start_time = time.perf_counter()
        for _ in range(100):
            match_and_grade_answer(
                question_type=QuestionType.SHORT_ANSWER,
                user_answer="本回答阐述了核心概念与基本原理的具体体现。",
                reference_answer="本回答阐述了核心概念与基本原理。",
                grading_rubric=rubric,
            )
        duration_ms = (time.perf_counter() - start_time) * 1000
        assert duration_ms < 50.0, f"Subjective grading too slow: {duration_ms:.2f}ms"
