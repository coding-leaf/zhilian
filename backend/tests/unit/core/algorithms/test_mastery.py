"""Unit tests for mastery score time decay and aggregation algorithm kernel.

Verifies:
- Ebbinghaus half-life time decay exponential factor calculation (0, 3, 7, 30, 300 days)
- 4-level mastery categorization boundaries (UNLEARNED, WEAK, DEVELOPING, MASTERED)
- 0.40 and 0.70 exact threshold boundaries (0.40 DEVELOPING, 0.70 MASTERED)
- Grading source confidence weighting (OFFLINE_RULE 1.0, LLM 0.8, SELF 0.5, UNKNOWN 0.5)
- Timestamp normalization (millisecond auto-convert defense)
- Single knowledge point decay & weighted aggregation
- Multi-knowledge batch aggregation and whitelist filtering
- Zero-record short circuit, negative/overflow score clamping, divide-by-zero defense
- Benchmark performance (< 20ms for 1000 records)
- Zero external I/O, zero network, zero database, zero system clock dependency
"""

import math
import time

import pytest

from app.core.algorithms.mastery import (
    DEFAULT_AI_GRADING_WEIGHT,
    DEFAULT_DECAY_LAMBDA,
    DEFAULT_DEVELOPING_UPPER_THRESHOLD,
    DEFAULT_HALF_LIFE_DAYS,
    DEFAULT_OFFLINE_RULE_WEIGHT,
    DEFAULT_SELF_ASSESSMENT_WEIGHT,
    DEFAULT_WEAK_UPPER_THRESHOLD,
    MILLISECOND_TIMESTAMP_THRESHOLD,
    SECONDS_PER_DAY,
    THRESHOLD_DEVELOPING,
    THRESHOLD_MASTERED,
    AttemptRecord,
    GradingSourceType,
    MasteryAggregationItem,
    MasteryAlgorithmConfig,
    MasteryLevel,
    MasteryScoreResult,
    aggregate_mastery_scores,
    aggregate_single_knowledge,
    aggregate_single_knowledge_mastery,
    calculate_time_decay_factor,
    determine_mastery_level,
    normalize_timestamp,
    resolve_source_weight,
)


class TestMasteryConstantsAndEnums:
    """测试掌握度常量与枚举定义一致性。"""

    def test_constants_and_aliases(self) -> None:
        """测试核心常量与别名符合需求与教育学模型。"""
        assert DEFAULT_HALF_LIFE_DAYS == 30.0
        assert math.isclose(DEFAULT_DECAY_LAMBDA, math.log(2.0) / 30.0, rel_tol=1e-5)
        assert SECONDS_PER_DAY == 86400.0
        assert DEFAULT_WEAK_UPPER_THRESHOLD == 0.40
        assert DEFAULT_DEVELOPING_UPPER_THRESHOLD == 0.70
        assert THRESHOLD_DEVELOPING == 0.40
        assert THRESHOLD_MASTERED == 0.70
        assert DEFAULT_OFFLINE_RULE_WEIGHT == 1.0
        assert DEFAULT_AI_GRADING_WEIGHT == 0.8
        assert DEFAULT_SELF_ASSESSMENT_WEIGHT == 0.5
        assert MILLISECOND_TIMESTAMP_THRESHOLD == 1e11

    def test_mastery_level_enum_values(self) -> None:
        """测试四档掌握度枚举值。"""
        assert MasteryLevel.UNLEARNED == "UNLEARNED"
        assert MasteryLevel.WEAK == "WEAK"
        assert MasteryLevel.DEVELOPING == "DEVELOPING"
        assert MasteryLevel.MASTERED == "MASTERED"

    def test_grading_source_type_enum_values(self) -> None:
        """测试判题来源枚举值与别名支持。"""
        assert GradingSourceType.OFFLINE_RULE == "OFFLINE_RULE"
        assert GradingSourceType.LLM_GRADING == "LLM_GRADING"
        assert GradingSourceType.AI_GRADING == "AI_GRADING"
        assert GradingSourceType.SELF_ASSESSMENT == "SELF_ASSESSMENT"
        assert GradingSourceType.APPEAL_REGRADE == "APPEAL_REGRADE"
        assert GradingSourceType.USER_APPEAL == "USER_APPEAL"
        assert GradingSourceType.UNKNOWN == "UNKNOWN"


class TestTimestampNormalization:
    """时间戳防御归一化测试套件。"""

    def test_normalize_seconds_timestamp(self) -> None:
        """秒级时间戳保持不变。"""
        timestamp_seconds = 1774350000.0
        assert normalize_timestamp(timestamp_seconds) == timestamp_seconds

    def test_normalize_millisecond_timestamp(self) -> None:
        """13位毫秒时间戳自动除以1000转换为秒级。"""
        timestamp_milliseconds = 1774350000000.0
        expected_seconds = 1774350000.0
        assert normalize_timestamp(timestamp_milliseconds) == expected_seconds


class TestTimeDecayCalculation:
    """时间衰减因子指数计算测试套件 (TC-TIME-01 到 TC-TIME-06)。"""

    def test_decay_zero_days_returns_one(self) -> None:
        """TC-TIME-01: 0天未闲置，衰减因子严格为 1.0。"""
        base_timestamp = 1774350000.0
        decay = calculate_time_decay_factor(
            answered_at=base_timestamp,
            evaluated_at=base_timestamp,
        )
        assert math.isclose(decay, 1.0, abs_tol=1e-6)

    def test_decay_three_days(self) -> None:
        """TC-TIME-02: 闲置 3 天，衰减因子约为 0.9330。"""
        base_timestamp = 1774350000.0
        answered_timestamp = base_timestamp - 3.0 * SECONDS_PER_DAY
        decay = calculate_time_decay_factor(
            answered_at=answered_timestamp,
            evaluated_at=base_timestamp,
        )
        expected_decay = math.pow(2.0, -3.0 / 30.0)
        assert math.isclose(decay, expected_decay, abs_tol=1e-4)
        assert math.isclose(decay, 0.933033, abs_tol=1e-4)

    def test_decay_seven_days(self) -> None:
        """TC-TIME-03: 闲置 7 天，衰减因子约为 0.8503。"""
        base_timestamp = 1774350000.0
        answered_timestamp = base_timestamp - 7.0 * SECONDS_PER_DAY
        decay = calculate_time_decay_factor(
            answered_at=answered_timestamp,
            evaluated_at=base_timestamp,
        )
        expected_decay = math.pow(2.0, -7.0 / 30.0)
        assert math.isclose(decay, expected_decay, abs_tol=1e-6)
        assert math.isclose(decay, 0.8507, abs_tol=1e-3)

    def test_decay_thirty_days_half_life(self) -> None:
        """TC-TIME-04: 闲置 30 天恰好等于半衰期，衰减因子严格等于 0.5000。"""
        base_timestamp = 1774350000.0
        answered_timestamp = base_timestamp - 30.0 * SECONDS_PER_DAY
        decay = calculate_time_decay_factor(
            answered_at=answered_timestamp,
            evaluated_at=base_timestamp,
        )
        assert math.isclose(decay, 0.500000, abs_tol=1e-6)

    def test_decay_three_hundred_days(self) -> None:
        """TC-TIME-05: 闲置 300 天经历 10 个半衰期，衰减因子约为 2**(-10)。"""
        base_timestamp = 1774350000.0
        answered_timestamp = base_timestamp - 300.0 * SECONDS_PER_DAY
        decay = calculate_time_decay_factor(
            answered_at=answered_timestamp,
            evaluated_at=base_timestamp,
        )
        expected_decay = math.pow(2.0, -10.0)
        assert math.isclose(decay, expected_decay, abs_tol=1e-6)
        assert math.isclose(decay, 0.0009765625, abs_tol=1e-6)

    def test_decay_future_timestamp_clamped(self) -> None:
        """TC-TIME-06: 作答时间晚于评估时间（未来作答），防御性钳制为 0 天衰减因子 1.0。"""
        base_timestamp = 1774350000.0
        future_timestamp = base_timestamp + 86400.0
        decay = calculate_time_decay_factor(
            answered_at=future_timestamp,
            evaluated_at=base_timestamp,
        )
        assert math.isclose(decay, 1.0, abs_tol=1e-6)

    def test_decay_non_positive_half_life_fallback(self) -> None:
        """TC-DEF-05: 半衰期传入非正数时防御性回退至默认 30 天。"""
        base_timestamp = 1774350000.0
        answered_timestamp = base_timestamp - 30.0 * SECONDS_PER_DAY
        decay_zero = calculate_time_decay_factor(
            answered_at=answered_timestamp,
            evaluated_at=base_timestamp,
            half_life_days=0.0,
        )
        assert math.isclose(decay_zero, 0.5, abs_tol=1e-6)

        decay_negative = calculate_time_decay_factor(
            answered_at=answered_timestamp,
            evaluated_at=base_timestamp,
            half_life_days=-10.0,
        )
        assert math.isclose(decay_negative, 0.5, abs_tol=1e-6)

    def test_decay_with_millisecond_timestamps(self) -> None:
        """测试毫秒时间戳与秒级时间戳混用时自动纠偏。"""
        base_ms = 1774350000000.0
        answered_ms = base_ms - 30.0 * SECONDS_PER_DAY * 1000.0
        decay = calculate_time_decay_factor(
            answered_at=answered_ms,
            evaluated_at=base_ms,
        )
        assert math.isclose(decay, 0.5, abs_tol=1e-6)

    def test_decay_custom_half_life(self) -> None:
        """测试自定义半衰期（如 10 天）。"""
        base_timestamp = 1774350000.0
        answered_timestamp = base_timestamp - 10.0 * SECONDS_PER_DAY
        decay = calculate_time_decay_factor(
            answered_at=answered_timestamp,
            evaluated_at=base_timestamp,
            half_life_days=10.0,
        )
        assert math.isclose(decay, 0.5, abs_tol=1e-6)

    def test_decay_keyword_aliases(self) -> None:
        """测试时间衰减函数关键字别名入参。"""
        now = 1774350000.0
        decay = calculate_time_decay_factor(
            answered_at_timestamp=now,
            evaluated_at_timestamp=now,
        )
        assert decay == 1.0


class TestGradingSourceWeights:
    """判题来源权重置信度合成测试套件 (TC-SRC-01 到 TC-SRC-06)。"""

    def test_source_weight_offline_rule(self) -> None:
        """TC-SRC-01: 离线规则客观题基础权重为 1.0。"""
        assert resolve_source_weight(GradingSourceType.OFFLINE_RULE) == 1.0
        assert resolve_source_weight("OFFLINE_RULE") == 1.0
        assert resolve_source_weight("offline_rule") == 1.0

    def test_source_weight_llm_grading(self) -> None:
        """TC-SRC-02: AI 大模型判题基础权重为 0.8。"""
        assert resolve_source_weight(GradingSourceType.LLM_GRADING) == 0.8
        assert resolve_source_weight(GradingSourceType.AI_GRADING) == 0.8
        assert resolve_source_weight("LLM_GRADING") == 0.8
        assert resolve_source_weight("AI_GRADING") == 0.8

    def test_source_weight_self_assessment(self) -> None:
        """TC-SRC-03: 用户自评与申诉复核基础权重为 0.5。"""
        assert resolve_source_weight(GradingSourceType.SELF_ASSESSMENT) == 0.5
        assert resolve_source_weight(GradingSourceType.APPEAL_REGRADE) == 0.5
        assert resolve_source_weight(GradingSourceType.USER_APPEAL) == 0.5
        assert resolve_source_weight("SELF_ASSESSMENT") == 0.5
        assert resolve_source_weight("USER_APPEAL") == 0.5

    def test_source_weight_unknown_fallback(self) -> None:
        """TC-SRC-06: 未知渠道字符串回退至保底权重 0.5。"""
        assert resolve_source_weight("UNKNOWN_CHANNEL") == 0.5
        assert resolve_source_weight(GradingSourceType.UNKNOWN) == 0.5

    def test_source_weight_custom_dictionary(self) -> None:
        """测试注入自定义权重字典覆盖默认值。"""
        custom = {"CUSTOM_EXAM": 1.2, "LLM_GRADING": 0.9}
        assert resolve_source_weight("CUSTOM_EXAM", custom_weights=custom) == 1.2
        assert resolve_source_weight(GradingSourceType.LLM_GRADING, custom_weights=custom) == 0.9
        # 未在自定义字典中的回退到默认
        assert resolve_source_weight(GradingSourceType.OFFLINE_RULE, custom_weights=custom) == 1.0

    def test_source_weight_custom_dictionary_case_insensitive(self) -> None:
        """测试自定义权重字典支持大小写归一化匹配。"""
        custom = {"CUSTOM_EXAM": 1.5}
        assert resolve_source_weight("custom_exam", custom_weights=custom) == 1.5


class TestMasteryLevelDetermination:
    """四档掌握度等级判定临界值测试套件 (TC-LEVEL-01 到 TC-LEVEL-08)。"""

    def test_level_unlearned_no_records(self) -> None:
        """TC-LEVEL-01: 无任何作答记录，固定返回 UNLEARNED。"""
        assert determine_mastery_level(0.0, has_records=False) == MasteryLevel.UNLEARNED
        assert determine_mastery_level(0.8, has_records=False) == MasteryLevel.UNLEARNED

    def test_level_weak_zero_score(self) -> None:
        """TC-LEVEL-02: 有作答但得分为 0.0，判定为 WEAK。"""
        assert determine_mastery_level(0.0, has_records=True) == MasteryLevel.WEAK

    def test_level_weak_near_threshold(self) -> None:
        """TC-LEVEL-03: 0.3999 处于薄弱上限临界下侧，判定为 WEAK。"""
        assert determine_mastery_level(0.3999, has_records=True) == MasteryLevel.WEAK

    def test_level_developing_exact_threshold(self) -> None:
        """TC-LEVEL-04: 0.4000 严格归属于进阶中 (DEVELOPING)。"""
        assert determine_mastery_level(0.4000, has_records=True) == MasteryLevel.DEVELOPING

    def test_level_developing_near_threshold(self) -> None:
        """TC-LEVEL-05: 0.6999 处于进阶中上限临界下侧，判定为 DEVELOPING。"""
        assert determine_mastery_level(0.6999, has_records=True) == MasteryLevel.DEVELOPING

    def test_level_mastered_exact_threshold(self) -> None:
        """TC-LEVEL-06: 0.7000 严格归属于掌握 (MASTERED)。"""
        assert determine_mastery_level(0.7000, has_records=True) == MasteryLevel.MASTERED

    def test_level_mastered_full_score(self) -> None:
        """TC-LEVEL-07: 1.0000 满分，判定为 MASTERED。"""
        assert determine_mastery_level(1.0000, has_records=True) == MasteryLevel.MASTERED

    def test_level_developing_normal_score(self) -> None:
        """TC-LEVEL-08: 0.5500 正常居中进阶得分，判定为 DEVELOPING。"""
        assert determine_mastery_level(0.5500, has_records=True) == MasteryLevel.DEVELOPING

    def test_level_keyword_alias(self) -> None:
        """测试等级判定函数关键字别名入参。"""
        assert determine_mastery_level(mastery_score=0.85) == MasteryLevel.MASTERED


class TestMasteryConfigValidation:
    """算法配置对象边界校验测试套件。"""

    def test_config_defaults(self) -> None:
        """测试默认配置。"""
        config = MasteryAlgorithmConfig()
        assert config.half_life_days == 30.0
        assert config.weak_upper_threshold == 0.40
        assert config.developing_upper_threshold == 0.70
        assert config.source_weights is None

    def test_config_negative_half_life_raises(self) -> None:
        """非正数半衰期抛出 ValueError。"""
        with pytest.raises(ValueError, match="half_life_days must be positive"):
            MasteryAlgorithmConfig(half_life_days=0.0)
        with pytest.raises(ValueError, match="half_life_days must be positive"):
            MasteryAlgorithmConfig(half_life_days=-5.0)

    def test_config_invalid_thresholds_order_raises(self) -> None:
        """阈值顺序颠倒抛出 ValueError。"""
        with pytest.raises(ValueError, match="Must satisfy"):
            MasteryAlgorithmConfig(weak_upper_threshold=0.8, developing_upper_threshold=0.6)
        with pytest.raises(ValueError, match="Must satisfy"):
            MasteryAlgorithmConfig(weak_upper_threshold=0.5, developing_upper_threshold=0.5)

    def test_config_thresholds_out_of_range_raises(self) -> None:
        """阈值超出 [0.0, 1.0] 抛出 ValueError。"""
        with pytest.raises(ValueError, match="Must satisfy"):
            MasteryAlgorithmConfig(weak_upper_threshold=-0.1, developing_upper_threshold=0.7)
        with pytest.raises(ValueError, match="Must satisfy"):
            MasteryAlgorithmConfig(weak_upper_threshold=0.4, developing_upper_threshold=1.2)


class TestSingleKnowledgeAggregation:
    """单知识点掌握度加权聚合测试套件。"""

    def test_single_empty_records_returns_unlearned(self) -> None:
        """空记录列表返回 UNLEARNED 且得分 0.0。"""
        item = aggregate_single_knowledge(
            knowledge_id="kp_math_001",
            records=[],
            evaluated_at_timestamp=1774350000.0,
        )
        assert item.knowledge_id == "kp_math_001"
        assert item.mastery_score == 0.0
        assert item.mastery_level == MasteryLevel.UNLEARNED
        assert item.effective_attempts_count == 0
        assert item.raw_average_score == 0.0
        assert item.decayed_weight_sum == 0.0
        assert item.last_practiced_timestamp is None

    def test_single_record_fresh_offline(self) -> None:
        """单次当天满分离线作答，掌握度 1.0，MASTERED。"""
        now = 1774350000.0
        records = [
            AttemptRecord(
                record_id="rec_01",
                knowledge_id="kp_math_001",
                score=1.0,
                source=GradingSourceType.OFFLINE_RULE,
                answered_at_timestamp=now,
            )
        ]
        item = aggregate_single_knowledge(
            knowledge_id="kp_math_001",
            records=records,
            evaluated_at_timestamp=now,
        )
        assert isinstance(item, MasteryAggregationItem)
        assert item.mastery_score == 1.0
        assert item.mastery_level == MasteryLevel.MASTERED
        assert item.effective_attempts_count == 1
        assert item.raw_average_score == 1.0
        assert math.isclose(item.decayed_weight_sum, 1.0, abs_tol=1e-6)
        assert item.last_practiced_timestamp == now

    def test_single_composite_offline_and_self(self) -> None:
        """TC-SRC-04: 同天 1 次离线满分(1.0) + 1 次自评零分(0.0)。

        有效权重: 离线 1.0, 自评 0.5。加权得分: 1.0 / (1.0 + 0.5) = 0.6667 (DEVELOPING)。
        算术平均分: (1.0 + 0.0) / 2 = 0.5000。
        """
        now = 1774350000.0
        records = [
            AttemptRecord(
                record_id="rec_01",
                knowledge_id="kp_math_001",
                score=1.0,
                source=GradingSourceType.OFFLINE_RULE,
                answered_at_timestamp=now,
            ),
            AttemptRecord(
                record_id="rec_02",
                knowledge_id="kp_math_001",
                score=0.0,
                source=GradingSourceType.SELF_ASSESSMENT,
                answered_at_timestamp=now,
            ),
        ]
        item = aggregate_single_knowledge(
            knowledge_id="kp_math_001",
            records=records,
            evaluated_at_timestamp=now,
        )
        assert item.mastery_score == 0.6667
        assert item.mastery_level == MasteryLevel.DEVELOPING
        assert item.effective_attempts_count == 2
        assert item.raw_average_score == 0.5000
        assert math.isclose(item.decayed_weight_sum, 1.5, abs_tol=1e-6)
        assert item.last_practiced_timestamp == now

    def test_single_decay_weighting_tradeoff(self) -> None:
        """TC-SRC-05: 30天前离线满分 + 当天 AI 零分。

        - 30天前离线满分: score=1.0, w = 1.0 * 0.5 = 0.5
        - 当天 AI 零分: score=0.0, w = 0.8 * 1.0 = 0.8
        - 总权重 = 1.3
        - 加权得分 = (1.0 * 0.5 + 0.0 * 0.8) / 1.3 = 0.5 / 1.3 ≈ 0.3846 (WEAK)
        """
        now = 1774350000.0
        thirty_days_ago = now - 30.0 * SECONDS_PER_DAY
        records = [
            AttemptRecord(
                record_id="rec_01",
                knowledge_id="kp_math_001",
                score=1.0,
                source=GradingSourceType.OFFLINE_RULE,
                answered_at_timestamp=thirty_days_ago,
            ),
            AttemptRecord(
                record_id="rec_02",
                knowledge_id="kp_math_001",
                score=0.0,
                source=GradingSourceType.LLM_GRADING,
                answered_at_timestamp=now,
            ),
        ]
        item = aggregate_single_knowledge(
            knowledge_id="kp_math_001",
            records=records,
            evaluated_at_timestamp=now,
        )
        assert item.mastery_score == 0.3846
        assert item.mastery_level == MasteryLevel.WEAK
        assert item.effective_attempts_count == 2
        assert item.raw_average_score == 0.5000
        assert math.isclose(item.decayed_weight_sum, 1.3, abs_tol=1e-6)
        assert item.last_practiced_timestamp == now

    def test_single_raw_score_clamping(self) -> None:
        """TC-DEF-02 & TC-DEF-03: 得分负数钳制为 0.0，超分钳制为 1.0。"""
        now = 1774350000.0
        records = [
            AttemptRecord(
                record_id="rec_01",
                knowledge_id="kp_math_001",
                score=-0.8,
                source=GradingSourceType.OFFLINE_RULE,
                answered_at_timestamp=now,
            ),
            AttemptRecord(
                record_id="rec_02",
                knowledge_id="kp_math_001",
                score=1.5,
                source=GradingSourceType.OFFLINE_RULE,
                answered_at_timestamp=now,
            ),
        ]
        item = aggregate_single_knowledge(
            knowledge_id="kp_math_001",
            records=records,
            evaluated_at_timestamp=now,
        )
        # 钳制后为 0.0 与 1.0，加权得分 (0.0*1.0 + 1.0*1.0) / 2.0 = 0.5000
        assert item.mastery_score == 0.5000
        assert item.mastery_level == MasteryLevel.DEVELOPING
        assert item.raw_average_score == 0.5000

    def test_single_alias_function(self) -> None:
        """测试 aggregate_single_knowledge_mastery 别名一致性。"""
        assert aggregate_single_knowledge_mastery is aggregate_single_knowledge

    def test_single_zero_decayed_weight_defense(self) -> None:
        """测试有效权重和为0时的防御保护。"""
        now = 1774350000.0
        records = [
            AttemptRecord(
                record_id="rec_01",
                knowledge_id="kp_math_001",
                score=1.0,
                source="ZERO_SOURCE",
                answered_at_timestamp=now,
            )
        ]
        config = MasteryAlgorithmConfig(source_weights={"ZERO_SOURCE": 0.0})
        item = aggregate_single_knowledge(
            knowledge_id="kp_math_001",
            records=records,
            evaluated_at_timestamp=now,
            config=config,
        )
        assert item.mastery_score == 0.0
        assert item.mastery_level == MasteryLevel.UNLEARNED

    def test_single_knowledge_custom_config_thresholds(self) -> None:
        """测试单知识点聚合使用自定义配置阈值。"""
        now = 1774350000.0
        records = [
            AttemptRecord(
                record_id="rec_01",
                knowledge_id="kp_math_001",
                score=0.5,
                source=GradingSourceType.OFFLINE_RULE,
                answered_at_timestamp=now,
            )
        ]
        config = MasteryAlgorithmConfig(weak_upper_threshold=0.6, developing_upper_threshold=0.8)
        item = aggregate_single_knowledge(
            knowledge_id="kp_math_001",
            records=records,
            evaluated_at_timestamp=now,
            config=config,
        )
        assert item.mastery_score == 0.5000
        assert item.mastery_level == MasteryLevel.WEAK


class TestBatchMasteryScoresAggregation:
    """批量与多知识点聚合总控测试套件。"""

    def test_batch_empty_records_short_circuit(self) -> None:
        """TC-DEF-01: 空作答列表短路返回 items 为空，总分 0.0。"""
        now = 1774350000.0
        result = aggregate_mastery_scores(
            records=[],
            evaluated_at_timestamp=now,
        )
        assert isinstance(result, MasteryScoreResult)
        assert result.items == {}
        assert result.knowledge_mastery_map == {}
        assert result.overall_mastery_score == 0.0
        assert result.overall_score == 0.0
        assert result.evaluated_at_timestamp == now
        assert result.total_records_processed == 0

    def test_batch_multi_knowledge_grouping(self) -> None:
        """TC-DEF-07: 多知识点混杂作答正确隔离聚合与汇总。"""
        now = 1774350000.0
        records = [
            AttemptRecord(
                record_id="r1",
                knowledge_id="kp_a",
                score=1.0,
                source=GradingSourceType.OFFLINE_RULE,
                answered_at_timestamp=now,
            ),
            AttemptRecord(
                record_id="r2",
                knowledge_id="kp_b",
                score=0.4,
                source=GradingSourceType.LLM_GRADING,
                answered_at_timestamp=now,
            ),
            AttemptRecord(
                record_id="r3",
                knowledge_id="kp_a",
                score=0.8,
                source=GradingSourceType.OFFLINE_RULE,
                answered_at_timestamp=now,
            ),
        ]
        result = aggregate_mastery_scores(
            records=records,
            evaluated_at_timestamp=now,
        )
        assert result.total_records_processed == 3
        assert len(result.items) == 2
        # kp_a: 2条记录 (1.0*1.0 + 0.8*1.0) / 2.0 = 0.9000 -> MASTERED
        assert result.items["kp_a"].mastery_score == 0.9000
        assert result.items["kp_a"].mastery_level == MasteryLevel.MASTERED
        assert result.items["kp_a"].effective_attempts_count == 2
        # kp_b: 1条记录 0.4000 -> DEVELOPING
        assert result.items["kp_b"].mastery_score == 0.4000
        assert result.items["kp_b"].mastery_level == MasteryLevel.DEVELOPING
        assert result.items["kp_b"].effective_attempts_count == 1
        # overall_score: (0.9000 + 0.4000) / 2 = 0.6500
        assert result.overall_mastery_score == 0.6500
        assert result.overall_score == 0.6500

    def test_batch_knowledge_ids_whitelist_filtering(self) -> None:
        """测试知识点白名单过滤与未作答补全 UNLEARNED。"""
        now = 1774350000.0
        records = [
            AttemptRecord(
                record_id="r1",
                knowledge_id="kp_target",
                score=1.0,
                source=GradingSourceType.OFFLINE_RULE,
                answered_at_timestamp=now,
            ),
            AttemptRecord(
                record_id="r2",
                knowledge_id="kp_ignored",
                score=0.2,
                source=GradingSourceType.OFFLINE_RULE,
                answered_at_timestamp=now,
            ),
        ]
        # 白名单包含 kp_target 与未作答的 kp_unlearned
        whitelist = ["kp_target", "kp_unlearned"]
        result = aggregate_mastery_scores(
            records=records,
            evaluated_at_timestamp=now,
            knowledge_ids=whitelist,
        )
        assert result.total_records_processed == 2
        assert set(result.items.keys()) == {"kp_target", "kp_unlearned"}
        assert "kp_ignored" not in result.items
        assert result.items["kp_target"].mastery_score == 1.0000
        assert result.items["kp_target"].mastery_level == MasteryLevel.MASTERED
        assert result.items["kp_unlearned"].mastery_score == 0.0000
        assert result.items["kp_unlearned"].mastery_level == MasteryLevel.UNLEARNED
        assert result.items["kp_unlearned"].effective_attempts_count == 0
        # 整体分: (1.0 + 0.0) / 2 = 0.5000
        assert result.overall_mastery_score == 0.5000

    def test_batch_timestamp_millisecond_conversion(self) -> None:
        """批量聚合支持毫秒时间戳基准。"""
        now_ms = 1774350000000.0
        record_ms = now_ms
        records = [
            AttemptRecord(
                record_id="r1",
                knowledge_id="kp_a",
                score=1.0,
                source=GradingSourceType.OFFLINE_RULE,
                answered_at_timestamp=record_ms,
            )
        ]
        result = aggregate_mastery_scores(
            records=records,
            evaluated_at_timestamp=now_ms,
        )
        assert result.evaluated_at_timestamp == 1774350000.0
        assert result.items["kp_a"].mastery_score == 1.0000

    def test_batch_empty_whitelist_returns_empty_items(self) -> None:
        """测试传入空白名单时返回空字典且总分 0.0。"""
        now = 1774350000.0
        records = [
            AttemptRecord(
                record_id="r1",
                knowledge_id="kp_a",
                score=1.0,
                source=GradingSourceType.OFFLINE_RULE,
                answered_at_timestamp=now,
            )
        ]
        result = aggregate_mastery_scores(
            records=records,
            evaluated_at_timestamp=now,
            knowledge_ids=[],
        )
        assert result.items == {}
        assert result.overall_mastery_score == 0.0
        assert result.total_records_processed == 1

    def test_result_constructor_aliases(self) -> None:
        """测试结果对象使用旧别名参数构造。"""
        result = MasteryScoreResult(
            knowledge_mastery_map={},
            overall_score=0.75,
            evaluated_at_timestamp=1774350000.0,
        )
        assert result.items == {}
        assert result.overall_mastery_score == 0.75


class TestMasteryPerformanceBenchmark:
    """性能基准测试套件。"""

    def test_performance_thousand_records_benchmark(self) -> None:
        """1000条记录批量聚合耗时必须小于 20ms。"""
        now = 1774350000.0
        records = [
            AttemptRecord(
                record_id=f"rec_{i}",
                knowledge_id=f"kp_{i % 20}",  # 20个知识点
                score=(i % 10) / 10.0,
                source=GradingSourceType.OFFLINE_RULE
                if i % 2 == 0
                else GradingSourceType.LLM_GRADING,
                answered_at_timestamp=now - (i % 60) * SECONDS_PER_DAY,
            )
            for i in range(1000)
        ]

        start_time = time.perf_counter()
        result = aggregate_mastery_scores(records, evaluated_at_timestamp=now)
        elapsed_seconds = time.perf_counter() - start_time

        assert result.total_records_processed == 1000
        assert len(result.items) == 20
        # 验证时间小于 20 毫秒 (0.02s)
        assert elapsed_seconds < 0.02, f"Execution took {elapsed_seconds * 1000:.2f}ms >= 20ms"
