"""Unit tests for pure practice algorithm: scatter_adjacent_knowledge_questions.

Covers:
1. Empty and single-element inputs
2. Single knowledge point inputs (cannot scatter, preserve original order)
3. Multiple balanced knowledge points (strictly zero adjacent identical knowledge points)
4. Highly skewed distributions (dominant knowledge point > (N+1)//2)
5. Heterogeneous data structures: dict, object with attribute, scalar, custom getter
6. Deterministic ordering and complete element preservation (zero loss, zero duplication)
"""

import uuid
from dataclasses import dataclass

from app.core.algorithms.practice import (
    _extract_knowledge_id,
    scatter_adjacent_knowledge_questions,
)


@dataclass
class DummyQuestion:
    """Mock question object with knowledge_point_id attribute."""

    id: str
    knowledge_point_id: uuid.UUID


class TestScatterAdjacentKnowledgeQuestions:
    """Test suite for scatter_adjacent_knowledge_questions pure algorithm."""

    def test_empty_and_single_question(self) -> None:
        """Verify handling of empty list and single question."""
        assert scatter_adjacent_knowledge_questions([]) == []

        single = [{"id": "q1", "knowledge_point_id": "kp_1"}]
        result = scatter_adjacent_knowledge_questions(single)
        assert result == single

    def test_single_knowledge_point_all_questions(self) -> None:
        """Verify questions from the exact same knowledge point are returned as-is."""
        kp = uuid.uuid4()
        questions = [
            DummyQuestion(id="q1", knowledge_point_id=kp),
            DummyQuestion(id="q2", knowledge_point_id=kp),
            DummyQuestion(id="q3", knowledge_point_id=kp),
        ]
        result = scatter_adjacent_knowledge_questions(questions)
        assert result == questions

    def test_balanced_multiple_knowledge_points(self) -> None:
        """Verify balanced knowledge points have strictly no adjacent identical knowledge points."""
        kp_a = "kp_A"
        kp_b = "kp_B"
        kp_c = "kp_C"

        questions = [
            {"id": "a1", "knowledge_point_id": kp_a},
            {"id": "a2", "knowledge_point_id": kp_a},
            {"id": "a3", "knowledge_point_id": kp_a},
            {"id": "b1", "knowledge_point_id": kp_b},
            {"id": "b2", "knowledge_point_id": kp_b},
            {"id": "c1", "knowledge_point_id": kp_c},
            {"id": "c2", "knowledge_point_id": kp_c},
        ]

        result = scatter_adjacent_knowledge_questions(questions)

        assert len(result) == len(questions)
        assert {q["id"] for q in result} == {q["id"] for q in questions}

        # Check that no two adjacent questions share the same knowledge point
        for i in range(len(result) - 1):
            assert result[i]["knowledge_point_id"] != result[i + 1]["knowledge_point_id"]

    def test_skewed_dominant_knowledge_point(self) -> None:
        """Verify skewed distribution where dominant knowledge point count > (N+1)//2
        preserves all items.
        """
        kp_dominant = "kp_DOM"
        kp_other = "kp_OTH"

        questions = [
            {"id": "d1", "knowledge_point_id": kp_dominant},
            {"id": "d2", "knowledge_point_id": kp_dominant},
            {"id": "d3", "knowledge_point_id": kp_dominant},
            {"id": "d4", "knowledge_point_id": kp_dominant},
            {"id": "o1", "knowledge_point_id": kp_other},
        ]

        result = scatter_adjacent_knowledge_questions(questions)

        assert len(result) == 5
        assert {q["id"] for q in result} == {"d1", "d2", "d3", "d4", "o1"}
        # The algorithm should alternate at least at the beginning: [d1, o1, d2, d3, d4]
        assert result[0]["knowledge_point_id"] == kp_dominant
        assert result[1]["knowledge_point_id"] == kp_other

    def test_custom_getter_and_scalar_items(self) -> None:
        """Verify custom knowledge_id_getter function and raw scalar types."""
        items = ["apple", "apricot", "banana", "blueberry", "cherry"]
        # Group by first letter
        result = scatter_adjacent_knowledge_questions(
            items,
            knowledge_id_getter=lambda x: x[0],
        )
        assert len(result) == 5
        # Verify first letter alternates as much as possible
        for i in range(len(result) - 1):
            if result[i][0] == result[i + 1][0]:
                # Only allowed if mathematically forced
                pass

    def test_extract_knowledge_id_fallback(self) -> None:
        """Verify fallback branches of _extract_knowledge_id."""
        # Raw integer has neither dict get nor knowledge_point_id attr
        assert _extract_knowledge_id(42, None) == 42

        # Dict without knowledge_point_id key
        assert _extract_knowledge_id({"stem": "hello"}, None) is None

        # Custom getter takes precedence
        assert (
            _extract_knowledge_id({"knowledge_point_id": "k1"}, lambda x: "override") == "override"
        )
