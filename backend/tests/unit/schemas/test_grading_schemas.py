"""Unit tests for grading Pydantic schemas in app/schemas/grading.py.

Covers:
- SelfEvaluateRequest score validation (ge 0) and feedback field constraints;
- SelfEvaluateResponse mapping and is_final flag;
- RegradeRequest & RegradeResponse validation;
- GradingRecordDTO channel, score, feedback, error_type, and serialization;
- AttemptGradingDetailResponse record list and latest record sync.
"""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.grading import (
    AttemptGradingDetailResponse,
    GradingRecordDTO,
    GradingRecordResponse,
    RegradeAttemptRequest,
    RegradeRequest,
    RegradeResponse,
    SelfEvaluateRequest,
    SelfEvaluateResponse,
)


def test_self_evaluate_request_and_response() -> None:
    """测试用户自主评分请求与响应。"""
    item_id = uuid.uuid4()
    record_id = uuid.uuid4()
    now = datetime.now(UTC)

    req = SelfEvaluateRequest(
        attempt_item_id=item_id,
        score=4.5,
        feedback="答出了三次握手关键流程，缺少标志位",
    )
    assert req.attempt_item_id == item_id
    assert req.score == 4.5
    assert req.feedback == "答出了三次握手关键流程，缺少标志位"

    with pytest.raises(ValidationError):
        SelfEvaluateRequest(
            attempt_item_id=item_id,
            score=-0.5,
        )

    resp = SelfEvaluateResponse(
        grading_record_id=record_id,
        attempt_item_id=item_id,
        score=4.5,
        is_final=True,
        evaluated_at=now,
    )
    assert resp.grading_record_id == record_id
    assert resp.id == record_id
    assert resp.attempt_item_id == item_id
    assert resp.score == 4.5
    assert resp.is_final is True
    assert resp.evaluated_at == now
    assert resp.created_at == now

    resp_reverse = SelfEvaluateResponse.model_validate(
        {
            "id": record_id,
            "attempt_item_id": item_id,
            "score": 3.0,
            "created_at": now,
        }
    )
    assert resp_reverse.grading_record_id == record_id
    assert resp_reverse.evaluated_at == now


def test_regrade_request_and_response() -> None:
    """测试重判申请请求与响应。"""
    item_id = uuid.uuid4()

    req = RegradeRequest(
        attempt_item_id=item_id,
        reason="我认为我的简答题阐述符合标准答案要点",
    )
    assert req.attempt_item_id == item_id
    assert req.reason == "我认为我的简答题阐述符合标准答案要点"

    resp = RegradeResponse(
        attempt_item_id=item_id,
        status="pending_regrade",
        message="已受理重判申请，进入异步大模型判题流水线",
    )
    assert resp.attempt_item_id == item_id
    assert resp.status == "pending_regrade"
    assert resp.message == "已受理重判申请，进入异步大模型判题流水线"

    assert RegradeAttemptRequest is RegradeRequest


def test_grading_record_dto_and_detail_response() -> None:
    """测试判题记录模型与明细响应列表。"""
    record_id = uuid.uuid4()
    item_id = uuid.uuid4()
    now = datetime.now(UTC)

    record = GradingRecordDTO(
        id=record_id,
        attempt_item_id=item_id,
        channel="ai",
        score=4.0,
        feedback="回答较完整，扣除1分格式分",
        is_final=True,
        error_type=None,
        created_at=now,
    )
    assert record.id == record_id
    assert record.attempt_item_id == item_id
    assert record.channel == "ai"
    assert record.score == 4.0
    assert record.is_final is True
    assert record.status == "success"
    assert GradingRecordResponse is GradingRecordDTO

    detail_resp = AttemptGradingDetailResponse(
        attempt_item_id=item_id,
        latest_grading=record,
        records=[record],
    )
    assert detail_resp.attempt_item_id == item_id
    assert detail_resp.latest_grading == record
    assert detail_resp.current_record == record
    assert len(detail_resp.records) == 1
    assert detail_resp.history == [record]

    detail_reverse = AttemptGradingDetailResponse.model_validate(
        {
            "attempt_item_id": item_id,
            "current_record": record.model_dump(),
            "history": [record.model_dump()],
        }
    )
    assert detail_reverse.latest_grading is not None
    assert detail_reverse.latest_grading.id == record_id
    assert len(detail_reverse.records) == 1
