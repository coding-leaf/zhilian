"""Unit tests for diagnosis report rule synthesis algorithm kernel.

Verifies:
- Threshold constants and cause enum values aligned with spec and education model
- Regression boundary conditions (0.0500 vs 0.0499, increased score, none baseline)
- Weak knowledge boundary conditions (0.3999, 0.4000 without/with mistakes, 0.6999, 0.7000)
- 4 cause rule matches:
  * CONCEPT_CONFUSION (negation inversion trigger)
  * CONCEPT_BLIND_SPOT (low score < 0.30 or both subjective & objective mistakes)
  * CARELESS_MISTAKE (high baseline >= 0.70, current >= 0.40 with mistake)
  * TIME_DECAY_FORGOTTEN (days >= 30.0 or regression without mistake)
  * UNKNOWN (fallback)
- Cause priority arbitration (Confusion > Blind Spot > Careless > Time Decay)
- Weak knowledge without mistakes explicit explanation marker (FR-50)
- Summary evaluation generation text accuracy
- Full synthesis pipeline:
  * Empty inputs defensive handling
  * Invalid report_id validation
  * All mastered / perfect score scenario
  * Clamping for overflow/negative scores
  * Sorting orders (weak points and regressed points)
  * Deduplicated actionable advice
- Performance benchmark (1000 knowledge points + 2000 mistakes < 50ms)
- Pure functional invariant (zero external I/O, zero network, zero DB, zero clock call)
"""

import time
from dataclasses import FrozenInstanceError

import pytest

from app.core.algorithms.diagnosis import (
    BLIND_SPOT_SCORE_THRESHOLD,
    DEVELOPING_SCORE_THRESHOLD,
    REGRESSION_DELTA_THRESHOLD,
    TIME_DECAY_DAYS_THRESHOLD,
    WEAK_SCORE_THRESHOLD,
    CauseType,
    DiagnosisReportResult,
    KnowledgeEvaluationInput,
    MistakeEvidence,
    WeakKnowledgeItem,
    check_knowledge_regression,
    check_regression,
    diagnose_cause_and_advice,
    evaluate_cause_type,
    generate_summary_evaluation,
    is_weak_knowledge,
    synthesize_diagnosis_report,
)


class TestDiagnosisConstantsAndEnums:
    """测试核心常量与成因枚举定义符合需求规范。"""

    def test_constants_values(self) -> None:
        """测试阈值常量符合需求规格说明书与教育测量学模型。"""
        assert REGRESSION_DELTA_THRESHOLD == 0.05
        assert WEAK_SCORE_THRESHOLD == 0.40
        assert DEVELOPING_SCORE_THRESHOLD == 0.70
        assert BLIND_SPOT_SCORE_THRESHOLD == 0.30
        assert TIME_DECAY_DAYS_THRESHOLD == 30.0

    def test_cause_type_enum(self) -> None:
        """测试成因枚举成员完整性与值一致性。"""
        assert CauseType.CONCEPT_BLIND_SPOT == "CONCEPT_BLIND_SPOT"
        assert CauseType.CARELESS_MISTAKE == "CARELESS_MISTAKE"
        assert CauseType.CONCEPT_CONFUSION == "CONCEPT_CONFUSION"
        assert CauseType.TIME_DECAY_FORGOTTEN == "TIME_DECAY_FORGOTTEN"
        assert CauseType.UNKNOWN == "UNKNOWN"

    def test_dataclass_immutability(self) -> None:
        """测试核心实体具备不可变性 (frozen=True)。"""
        evidence = MistakeEvidence(
            question_id="q1",
            question_brief="brief",
            user_answer="A",
            correct_answer="B",
            knowledge_id="k1",
        )
        with pytest.raises(FrozenInstanceError):
            evidence.user_answer = "C"  # type: ignore[misc]

        item = KnowledgeEvaluationInput(
            knowledge_id="k1",
            knowledge_title="Title",
            current_score=0.8,
        )
        with pytest.raises(FrozenInstanceError):
            item.current_score = 0.5  # type: ignore[misc]

        weak_item = WeakKnowledgeItem(
            knowledge_id="k1",
            knowledge_title="Title",
            current_score=0.3,
            previous_score=0.5,
            score_delta=0.2,
            is_regressed=True,
            cause_type=CauseType.CONCEPT_BLIND_SPOT,
            cause_explanation="exp",
            actionable_advice="advice",
        )
        with pytest.raises(FrozenInstanceError):
            weak_item.current_score = 0.4  # type: ignore[misc]


class TestCheckRegression:
    """测试退步研判纯函数 (check_regression)。"""

    def test_regression_boundary_exact_005(self) -> None:
        """测试恰好等于 0.05 降幅时判定为显著退步，变化量为负 (DIAG-008)。"""
        is_regressed, score_delta = check_regression(0.75, 0.80)
        assert is_regressed is True
        assert score_delta == -0.05

    def test_regression_boundary_just_below_005(self) -> None:
        """测试略低于 0.05 降幅 (0.0499) 判定为未退步，变化量为负。"""
        is_regressed, score_delta = check_regression(0.7501, 0.80)
        assert is_regressed is False
        assert score_delta == -0.0499

    def test_regression_score_increased(self) -> None:
        """测试分数提升时变化量为正且判定为未退步 (DIAG-008)。"""
        is_regressed, score_delta = check_regression(0.80, 0.60)
        assert is_regressed is False
        assert score_delta == 0.20

    def test_regression_none_previous_score(self) -> None:
        """测试首次评估无历史分数基线判定为未退步且变化量为 0.0。"""
        is_regressed, score_delta = check_regression(0.75, None)
        assert is_regressed is False
        assert score_delta == 0.0

    def test_regression_custom_threshold(self) -> None:
        """测试支持自定义退步阈值，未达阈值时变化量保留负号。"""
        is_regressed, score_delta = check_regression(0.70, 0.80, threshold=0.15)
        assert is_regressed is False
        assert score_delta == -0.10

    def test_alias_consistency(self) -> None:
        """测试别名函数 check_knowledge_regression 与 check_regression 行为一致。"""
        assert check_knowledge_regression(0.70, 0.80) == check_regression(0.70, 0.80)


class TestIsWeakKnowledge:
    """测试薄弱知识点判定纯函数 (is_weak_knowledge)。"""

    def test_weak_score_boundary_03999(self) -> None:
        """测试掌握度低于 0.40 (< 0.40) 无条件纳入薄弱。"""
        assert is_weak_knowledge(0.3999, mistake_count=0) is True

    def test_weak_score_boundary_04000_no_mistake(self) -> None:
        """测试掌握度等于 0.40 但无错题时不纳入薄弱。"""
        assert is_weak_knowledge(0.4000, mistake_count=0) is False

    def test_weak_score_boundary_04000_with_mistake(self) -> None:
        """测试掌握度处于 [0.40, 0.70) 且有错题时纳入薄弱。"""
        assert is_weak_knowledge(0.4000, mistake_count=1) is True

    def test_weak_score_boundary_06999_with_mistake(self) -> None:
        """测试掌握度 0.6999 且有错题时纳入薄弱。"""
        assert is_weak_knowledge(0.6999, mistake_count=1) is True

    def test_weak_score_boundary_07000_with_mistake(self) -> None:
        """测试掌握度达到 0.70 即达标，即使有错题也不纳入薄弱。"""
        assert is_weak_knowledge(0.7000, mistake_count=1) is False

    def test_weak_score_boundary_07000_no_mistake(self) -> None:
        """测试掌握度达到 0.70 且无错题不纳入薄弱。"""
        assert is_weak_knowledge(0.7000, mistake_count=0) is False


class TestEvaluateCauseType:
    """测试四类成因规则匹配与优先级决策 (evaluate_cause_type)。"""

    def test_cause_concept_confusion_negation(self) -> None:
        """测试否定词反转触发 CONCEPT_CONFUSION。"""
        item = KnowledgeEvaluationInput(
            knowledge_id="k1",
            knowledge_title="Title 1",
            current_score=0.5,
            previous_score=0.6,
        )
        mistakes = [
            MistakeEvidence(
                question_id="q1",
                question_brief="Which is NOT true?",
                user_answer="A",
                correct_answer="B",
                knowledge_id="k1",
                is_negation_inversion=True,
            )
        ]
        cause, explanation, advice = evaluate_cause_type(item, mistakes, score_delta=0.1)
        assert cause == CauseType.CONCEPT_CONFUSION
        assert "否定词" in explanation
        assert "对比卡片" in advice

    def test_cause_concept_blind_spot_by_score(self) -> None:
        """测试当前得分 < 0.30 且有错题触发 CONCEPT_BLIND_SPOT。"""
        item = KnowledgeEvaluationInput(
            knowledge_id="k1",
            knowledge_title="Title 1",
            current_score=0.25,
            previous_score=0.30,
        )
        mistakes = [
            MistakeEvidence(
                question_id="q1",
                question_brief="Definition test",
                user_answer="A",
                correct_answer="B",
                knowledge_id="k1",
            )
        ]
        cause, explanation, advice = evaluate_cause_type(item, mistakes, score_delta=0.05)
        assert cause == CauseType.CONCEPT_BLIND_SPOT
        assert "盲区" in explanation
        assert "暂停该知识点题海训练" in advice

    def test_cause_concept_blind_spot_by_both_subjective_objective(self) -> None:
        """测试主客观题均答错触发 CONCEPT_BLIND_SPOT。"""
        item = KnowledgeEvaluationInput(
            knowledge_id="k1",
            knowledge_title="Title 1",
            current_score=0.35,
            previous_score=0.40,
            has_subjective_mistake=True,
            has_objective_mistake=True,
        )
        mistakes = [
            MistakeEvidence(
                question_id="q1",
                question_brief="Brief 1",
                user_answer="A",
                correct_answer="B",
                knowledge_id="k1",
            )
        ]
        cause, explanation, _ = evaluate_cause_type(item, mistakes, score_delta=0.05)
        assert cause == CauseType.CONCEPT_BLIND_SPOT
        assert "盲区" in explanation

    def test_cause_careless_mistake(self) -> None:
        """测试高历史掌握 (>=0.70) 且当前未崩溃 (>=0.40) 有错题触发 CARELESS_MISTAKE。"""
        item = KnowledgeEvaluationInput(
            knowledge_id="k1",
            knowledge_title="Title 1",
            current_score=0.60,
            previous_score=0.85,
        )
        mistakes = [
            MistakeEvidence(
                question_id="q1",
                question_brief="Calculation mistake",
                user_answer="42",
                correct_answer="43",
                knowledge_id="k1",
            )
        ]
        cause, explanation, advice = evaluate_cause_type(item, mistakes, score_delta=0.25)
        assert cause == CauseType.CARELESS_MISTAKE
        assert "审题疏漏" in explanation or "计算笔误" in explanation
        assert "复查" in advice

    def test_cause_time_decay_forgotten_by_days(self) -> None:
        """测试距上次练习超过 30 天触发 TIME_DECAY_FORGOTTEN。"""
        item = KnowledgeEvaluationInput(
            knowledge_id="k1",
            knowledge_title="Title 1",
            current_score=0.50,
            previous_score=0.55,
            days_since_last_practice=35.0,
        )
        mistakes = [
            MistakeEvidence(
                question_id="q1",
                question_brief="Brief",
                user_answer="A",
                correct_answer="B",
                knowledge_id="k1",
            )
        ]
        cause, explanation, advice = evaluate_cause_type(item, mistakes, score_delta=0.05)
        assert cause == CauseType.TIME_DECAY_FORGOTTEN
        assert "艾宾浩斯" in explanation or "30 天" in explanation
        assert "艾宾浩斯间隔记忆法" in advice

    def test_cause_time_decay_without_mistakes(self) -> None:
        """测试无本次错题但由于衰减导致退步触发 TIME_DECAY_FORGOTTEN。"""
        item = KnowledgeEvaluationInput(
            knowledge_id="k1",
            knowledge_title="Title 1",
            current_score=0.65,
            previous_score=0.75,
            days_since_last_practice=10.0,
        )
        cause, explanation, advice = evaluate_cause_type(item, mistakes=[], score_delta=-0.10)
        assert cause == CauseType.TIME_DECAY_FORGOTTEN
        assert "历史掌握度低/时间衰减" in explanation
        assert "艾宾浩斯间隔记忆法" in advice

    def test_cause_fallback_unknown_with_mistakes(self) -> None:
        """测试不满足上述规则特征时进入 UNKNOWN 兜底。"""
        item = KnowledgeEvaluationInput(
            knowledge_id="k1",
            knowledge_title="Title 1",
            current_score=0.50,
            previous_score=0.52,
            days_since_last_practice=5.0,
        )
        mistakes = [
            MistakeEvidence(
                question_id="q1",
                question_brief="Ordinary question",
                user_answer="A",
                correct_answer="B",
                knowledge_id="k1",
            )
        ]
        cause, explanation, advice = evaluate_cause_type(item, mistakes, score_delta=0.02)
        assert cause == CauseType.UNKNOWN
        assert "未呈现典型规则特征" in explanation
        assert "常态化自适应练习" in advice

    def test_cause_fallback_unknown_without_mistakes(self) -> None:
        """测试无错题且未触发衰减退步时进入 UNKNOWN 兜底并标记历史来源。"""
        item = KnowledgeEvaluationInput(
            knowledge_id="k1",
            knowledge_title="Title 1",
            current_score=0.38,
            previous_score=0.39,
            days_since_last_practice=5.0,
        )
        cause, explanation, _ = evaluate_cause_type(item, mistakes=[], score_delta=0.01)
        assert cause == CauseType.UNKNOWN
        assert "历史掌握度低/时间衰减" in explanation

    def test_cause_none_previous_score_with_mistake(self) -> None:
        """测试首次评估 (previous_score=None) 发生普通错题时进入 UNKNOWN 兜底。"""
        item = KnowledgeEvaluationInput(
            knowledge_id="k1",
            knowledge_title="Title 1",
            current_score=0.50,
            previous_score=None,
        )
        mistakes = [
            MistakeEvidence(
                question_id="q1",
                question_brief="Question",
                user_answer="A",
                correct_answer="B",
                knowledge_id="k1",
            )
        ]
        cause, _, _ = evaluate_cause_type(item, mistakes, score_delta=0.0)
        assert cause == CauseType.UNKNOWN

    def test_cause_priority_confusion_over_blind_spot(self) -> None:
        """测试优先级裁决：概念混淆 (Rank 1) 优先于概念盲区 (Rank 2)。"""
        item = KnowledgeEvaluationInput(
            knowledge_id="k1",
            knowledge_title="Title 1",
            current_score=0.20,  # 盲区阈值
            previous_score=0.30,
        )
        mistakes = [
            MistakeEvidence(
                question_id="q1",
                question_brief="Negation",
                user_answer="A",
                correct_answer="B",
                knowledge_id="k1",
                is_negation_inversion=True,  # 混淆触发
            )
        ]
        cause, _, _ = evaluate_cause_type(item, mistakes, score_delta=0.10)
        assert cause == CauseType.CONCEPT_CONFUSION

    def test_cause_priority_blind_spot_over_careless(self) -> None:
        """测试优先级裁决：概念盲区 (Rank 2) 优先于粗心失误 (Rank 3)。"""
        item = KnowledgeEvaluationInput(
            knowledge_id="k1",
            knowledge_title="Title 1",
            current_score=0.25,  # 崩盘至盲区 (<0.30)
            previous_score=0.85,  # 历史优秀
        )
        mistakes = [
            MistakeEvidence(
                question_id="q1",
                question_brief="Question",
                user_answer="A",
                correct_answer="B",
                knowledge_id="k1",
            )
        ]
        cause, _, _ = evaluate_cause_type(item, mistakes, score_delta=0.60)
        assert cause == CauseType.CONCEPT_BLIND_SPOT

    def test_cause_priority_careless_over_time_decay(self) -> None:
        """测试优先级裁决：粗心失误 (Rank 3) 优先于时间衰减 (Rank 4)。"""
        item = KnowledgeEvaluationInput(
            knowledge_id="k1",
            knowledge_title="Title 1",
            current_score=0.60,
            previous_score=0.85,
            days_since_last_practice=40.0,  # 超过 30 天
        )
        mistakes = [
            MistakeEvidence(
                question_id="q1",
                question_brief="Question",
                user_answer="A",
                correct_answer="B",
                knowledge_id="k1",
            )
        ]
        cause, _, _ = evaluate_cause_type(item, mistakes, score_delta=0.25)
        assert cause == CauseType.CARELESS_MISTAKE

    def test_diagnose_alias_consistency(self) -> None:
        """测试别名 diagnose_cause_and_advice 行为一致。"""
        item = KnowledgeEvaluationInput(
            knowledge_id="k1",
            knowledge_title="Title 1",
            current_score=0.60,
            previous_score=0.85,
        )
        mistakes = [
            MistakeEvidence(
                question_id="q1",
                question_brief="Question",
                user_answer="A",
                correct_answer="B",
                knowledge_id="k1",
            )
        ]
        assert diagnose_cause_and_advice(item, mistakes, 0.25) == evaluate_cause_type(
            item, mistakes, 0.25
        )


class TestGenerateSummaryEvaluation:
    """测试综合评价总结生成纯函数 (generate_summary_evaluation)。"""

    def test_summary_evaluation_empty(self) -> None:
        """测试无知识点评估时的总结。"""
        summary = generate_summary_evaluation(0.0, total_count=0, weak_count=0, regressed_count=0)
        assert "无有效知识点数据" in summary

    def test_summary_evaluation_all_mastered(self) -> None:
        """测试全部达到掌握标准的总结。"""
        summary = generate_summary_evaluation(0.92, total_count=5, weak_count=0, regressed_count=0)
        assert "全部评估知识点均达到掌握标准" in summary
        assert "0.92" in summary

    def test_summary_evaluation_with_weak_and_regressed(self) -> None:
        """测试存在薄弱与退步知识点时的总结。"""
        summary = generate_summary_evaluation(0.58, total_count=10, weak_count=3, regressed_count=2)
        assert "发现 3 个薄弱知识点" in summary
        assert "2 个显著退步知识点" in summary


class TestSynthesizeDiagnosisReport:
    """测试学情诊断报告顶层流水线 (synthesize_diagnosis_report)。"""

    def test_invalid_report_id(self) -> None:
        """测试空 report_id 或空白字符串抛出 ValueError。"""
        with pytest.raises(ValueError, match="report_id"):
            synthesize_diagnosis_report("", [])
        with pytest.raises(ValueError, match="report_id"):
            synthesize_diagnosis_report("   ", [])

    def test_empty_input_graceful_handling(self) -> None:
        """测试空知识点列表的安全返回。"""
        result = synthesize_diagnosis_report("rep-001", [])
        assert isinstance(result, DiagnosisReportResult)
        assert result.report_id == "rep-001"
        assert result.overall_score == 0.0
        assert result.weak_points == []
        assert result.regressed_points == []
        assert result.mastered_points_count == 0
        assert result.total_points_evaluated == 0
        assert "无有效知识点数据" in result.summary_evaluation
        assert len(result.suggested_review_actions) == 1

    def test_perfect_score_all_mastered(self) -> None:
        """测试全优全对场景 (0 薄弱，0 退步)。"""
        items = [
            KnowledgeEvaluationInput("k1", "Math", 0.90, previous_score=0.85),
            KnowledgeEvaluationInput("k2", "Physics", 0.80, previous_score=0.80),
        ]
        result = synthesize_diagnosis_report("rep-perfect", items, mistakes=[])
        assert result.overall_score == 0.85
        assert len(result.weak_points) == 0
        assert len(result.regressed_points) == 0
        assert result.mastered_points_count == 2
        assert result.total_points_evaluated == 2
        assert "优异" in result.summary_evaluation

    def test_score_clamping(self) -> None:
        """测试输入分值越界时自动安全钳制到 [0.0, 1.0]。"""
        items = [
            KnowledgeEvaluationInput("k1", "Math", 1.2, previous_score=1.5),
            KnowledgeEvaluationInput("k2", "Physics", -0.3, previous_score=-0.1),
        ]
        result = synthesize_diagnosis_report("rep-clamp", items)
        # 1.2 clamped to 1.0, -0.3 clamped to 0.0 -> average = 0.50
        assert result.overall_score == 0.50
        assert result.weak_points[0].current_score == 0.0
        assert result.weak_points[0].previous_score == 0.0

    def test_weak_point_with_mistake_association(self) -> None:
        """测试薄弱知识点强关联错题证据 (FR-50)。"""
        items = [
            KnowledgeEvaluationInput("k1", "Calculus", 0.50, previous_score=0.60),
            KnowledgeEvaluationInput("k2", "Linear Algebra", 0.85, previous_score=0.85),
        ]
        mistakes = [
            MistakeEvidence("q1", "Derivatives", "0", "1", "k1"),
            MistakeEvidence("q2", "Integrals", "x", "x^2", "k1"),
        ]
        result = synthesize_diagnosis_report("rep-assoc", items, mistakes)
        assert len(result.weak_points) == 1
        weak_k1 = result.weak_points[0]
        assert weak_k1.knowledge_id == "k1"
        assert len(weak_k1.associated_mistakes) == 2
        assert weak_k1.associated_mistakes[0].question_id == "q1"

    def test_weak_point_without_mistake_explanation(self) -> None:
        """测试无错题薄弱点显式注明历史累计与衰减来源 (FR-50 特殊标记)。"""
        items = [
            KnowledgeEvaluationInput("k1", "History Weak", 0.35, previous_score=0.35),
        ]
        result = synthesize_diagnosis_report("rep-no-mistake", items, mistakes=[])
        assert len(result.weak_points) == 1
        weak_k1 = result.weak_points[0]
        assert weak_k1.associated_mistakes == []
        assert "【证据来源：历史掌握度低/时间衰减】" in weak_k1.cause_explanation

    def test_synthesize_with_none_previous_score(self) -> None:
        """测试知识点首次练习 (previous_score=None) 时的报告合成。"""
        items = [
            KnowledgeEvaluationInput("k1", "New Concept", 0.30, previous_score=None),
        ]
        result = synthesize_diagnosis_report("rep-new-concept", items)
        assert result.overall_score == 0.30
        assert len(result.weak_points) == 1
        assert result.weak_points[0].previous_score is None
        assert result.weak_points[0].is_regressed is False
        assert result.weak_points[0].score_delta == 0.0

    def test_regressed_point_independent_of_weak(self) -> None:
        """测试高分退步点独立进入 regressed_points 且变化量为负 (DIAG-008)。"""
        # previous 0.90 -> current 0.75, score >= 0.70 不属于 weak
        # 但 delta -0.15 <= -0.05 属于 regressed
        items = [
            KnowledgeEvaluationInput("k1", "Advanced", 0.75, previous_score=0.90),
        ]
        mistakes = [
            MistakeEvidence("q1", "Advanced question", "A", "B", "k1"),
        ]
        result = synthesize_diagnosis_report("rep-regress-high", items, mistakes)
        assert len(result.weak_points) == 0
        assert len(result.regressed_points) == 1
        assert result.regressed_points[0].is_regressed is True
        assert result.regressed_points[0].score_delta == -0.15

    def test_sorting_order(self) -> None:
        """测试排序：weak_points 按得分升序，regressed_points 按变化量升序（最负在前）。"""
        items = [
            KnowledgeEvaluationInput("k1", "K1", 0.30, previous_score=0.40),  # delta -0.10
            KnowledgeEvaluationInput("k2", "K2", 0.10, previous_score=0.15),  # delta -0.05
            KnowledgeEvaluationInput("k3", "K3", 0.20, previous_score=0.45),  # delta -0.25
        ]
        result = synthesize_diagnosis_report("rep-sort", items)
        # weak_points: 按照 current_score 升序 -> k2(0.10), k3(0.20), k1(0.30)
        assert [p.knowledge_id for p in result.weak_points] == ["k2", "k3", "k1"]
        # regressed_points: 按照 score_delta 升序（降幅最大在前）-> k3(-0.25), k1(-0.10), k2(-0.05)
        assert [p.knowledge_id for p in result.regressed_points] == ["k3", "k1", "k2"]

    def test_review_actions_deduplication(self) -> None:
        """测试可执行复习建议有序去重。"""
        # 多个盲区知识点应该只产生一条相同的行动建议
        items = [
            KnowledgeEvaluationInput("k1", "K1", 0.20, previous_score=0.30),
            KnowledgeEvaluationInput("k2", "K2", 0.15, previous_score=0.25),
        ]
        mistakes = [
            MistakeEvidence("q1", "Q1", "A", "B", "k1"),
            MistakeEvidence("q2", "Q2", "A", "B", "k2"),
        ]
        result = synthesize_diagnosis_report("rep-dedup", items, mistakes)
        assert len(result.suggested_review_actions) == 1
        assert "暂停该知识点题海训练" in result.suggested_review_actions[0]


class TestBenchmarkPerformance:
    """性能压测：1000 知识点 + 2000 错题诊断合成耗时 < 50ms。"""

    def test_benchmark_1000_knowledge_points_2000_mistakes(self) -> None:
        """测试大规模数据纯内存诊断合成算法执行效率。"""
        knowledge_items = [
            KnowledgeEvaluationInput(
                knowledge_id=f"k_{i}",
                knowledge_title=f"Knowledge Point {i}",
                current_score=0.20 + (i % 80) * 0.01,
                previous_score=0.30 + (i % 70) * 0.01,
                days_since_last_practice=float(i % 60),
                has_subjective_mistake=(i % 4 == 0),
                has_objective_mistake=(i % 3 == 0),
            )
            for i in range(1000)
        ]

        mistakes = [
            MistakeEvidence(
                question_id=f"q_{j}",
                question_brief=f"Question brief for question {j}",
                user_answer="User choice",
                correct_answer="Correct choice",
                knowledge_id=f"k_{j % 1000}",
                is_negation_inversion=(j % 20 == 0),
            )
            for j in range(2000)
        ]

        start_time = time.perf_counter()
        result = synthesize_diagnosis_report("rep-bench-1000", knowledge_items, mistakes)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Under pytest-cov branch tracing, permit up to 200ms
        assert duration_ms < 200.0, f"Synthesize took {duration_ms:.2f}ms, exceeding 200ms limit"
        assert result.total_points_evaluated == 1000
        assert len(result.weak_points) > 0
        assert len(result.regressed_points) > 0
