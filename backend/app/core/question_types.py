"""Canonical question type enumeration shared across core algorithms and ORM models."""

import enum


class QuestionType(enum.StrEnum):
    """题目类型枚举 (覆盖需求 FR-20 规定的七大题型)。"""

    SINGLE_CHOICE = "single_choice"  # 单项选择题
    MULTIPLE_CHOICE = "multiple_choice"  # 多项选择题 (>=3选项, >=2正确项)
    TRUE_FALSE = "true_false"  # 判断题 (二值答案)
    FILL_IN_BLANK = "fill_in_blank"  # 填空题
    TERM_EXPLANATION = "term_explanation"  # 名词解释 (主观题)
    SHORT_ANSWER = "short_answer"  # 简答题 (主观题)
    CASE_ANALYSIS = "case_analysis"  # 案例分析 (主观题)


__all__ = ["QuestionType"]
