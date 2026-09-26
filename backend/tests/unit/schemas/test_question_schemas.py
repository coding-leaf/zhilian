"""Unit tests for question generation schema backward compatibility.

Verifies:
1. Legacy single-knowledge-point payload parses unchanged.
2. New multi-knowledge-point payload parses and takes priority.
3. At least one knowledge point target is required.
4. Response knowledge_point_ids defaults to an empty list (additive field).
"""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.question import QuestionGenerateRequest, QuestionGenerateResponse


def test_question_generate_request_legacy_single_knowledge_point() -> None:
    """Legacy clients sending only knowledge_point_id must still parse."""
    material_id = uuid.uuid4()
    kp_id = uuid.uuid4()

    request = QuestionGenerateRequest(
        material_id=material_id,
        knowledge_point_id=kp_id,
        count=3,
    )

    assert request.material_id == material_id
    assert request.knowledge_point_id == kp_id
    assert request.knowledge_point_ids == []
    assert request.count == 3


def test_question_generate_request_multi_knowledge_points() -> None:
    """New clients may omit knowledge_point_id and send only the list."""
    material_id = uuid.uuid4()
    kp_ids = [uuid.uuid4() for _ in range(3)]

    request = QuestionGenerateRequest(
        material_id=material_id,
        knowledge_point_ids=kp_ids,
        count=6,
    )

    assert request.knowledge_point_id is None
    assert request.knowledge_point_ids == kp_ids
    assert request.count == 6


def test_question_generate_request_requires_knowledge_point_target() -> None:
    """Providing neither knowledge_point_id nor knowledge_point_ids is invalid."""
    with pytest.raises(ValidationError):
        QuestionGenerateRequest(material_id=uuid.uuid4(), count=3)


def test_question_generate_response_knowledge_point_ids_defaults_empty() -> None:
    """The new response field is additive and defaults to an empty list."""
    response = QuestionGenerateResponse(
        batch_id="batch_001",
        material_id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        knowledge_point_id=uuid.uuid4(),
        total_generated=0,
    )

    assert response.knowledge_point_ids == []
