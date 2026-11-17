"""Unit tests for shared metric logging and idempotency key validation."""

import json
import logging
import uuid
from typing import Any

import pytest

from app.core.errors import IdempotencyKeyInvalidError
from app.core.idempotency import validate_idempotency_key
from app.core.logging import build_metric_payload, log_structured_metric


def test_build_metric_payload_flat_and_nested_modes() -> None:
    """Verify metric payload construction for both flat and nested extra modes."""
    user_id = uuid.uuid4()
    nested = build_metric_payload(
        action="GRADE",
        request_id="req-1",
        user_id=user_id,
        target_id="target-1",
        duration_ms=12.3456,
        logger_name="test.logger",
        error_code=0,
        extra={"count": 3},
        nest_extra=True,
    )
    assert nested["level"] == "INFO"
    assert nested["duration_ms"] == 12.35
    assert nested["details"] == {"count": 3}

    flat = build_metric_payload(
        action="FAIL",
        request_id="req-2",
        user_id=user_id,
        target_id=uuid.uuid4(),
        duration_ms=1.0,
        logger_name="test.logger",
        error_code=40010,
        extra={"reason": "timeout"},
        nest_extra=False,
    )
    assert flat["level"] == "ERROR"
    assert flat["reason"] == "timeout"
    assert "details" not in flat


def test_log_structured_metric_emits_expected_records(caplog: pytest.LogCaptureFixture) -> None:
    """Verify json_mode METRIC output and standard info/error service log formats."""
    test_logger = logging.getLogger("tests.core.logging")
    user_id = uuid.uuid4()
    target_id = uuid.uuid4()

    with caplog.at_level(logging.INFO, logger=test_logger.name):
        log_structured_metric(
            test_logger,
            action="grade_practice",
            request_id="",
            user_id=user_id,
            target_id=target_id,
            duration_ms=5.5,
            extra={"ok": True},
            json_mode=True,
        )
        log_structured_metric(
            test_logger,
            action="create_practice",
            request_id="req-ok",
            user_id=user_id,
            target_id=target_id,
            duration_ms=3.2,
            service_label="PracticeService",
        )
        log_structured_metric(
            test_logger,
            action="submit_failed",
            request_id="req-err",
            user_id=user_id,
            target_id=target_id,
            duration_ms=4.1,
            error_code=40015,
            service_label="DiagnosisService",
        )

    assert len(caplog.records) == 3
    first_msg = caplog.records[0].getMessage()
    assert first_msg.startswith("METRIC ")
    parsed = json.loads(first_msg.removeprefix("METRIC "))
    assert parsed["request_id"] == "-"
    assert parsed["details"] == {"ok": True}

    assert "PracticeService execution completed:" in caplog.records[1].getMessage()
    assert "DiagnosisService execution error:" in caplog.records[2].getMessage()


def test_validate_idempotency_key_accepts_valid_and_rejects_invalid() -> None:
    """Verify idempotency key trimming, length cap, type guard, and character allowlist."""
    assert validate_idempotency_key("  req_123:abc-xyz.1  ") == "req_123:abc-xyz.1"

    invalid_non_str: Any = 123
    with pytest.raises(IdempotencyKeyInvalidError, match="必须为字符串"):
        validate_idempotency_key(invalid_non_str)

    with pytest.raises(IdempotencyKeyInvalidError, match="不能为空"):
        validate_idempotency_key("   ")

    with pytest.raises(IdempotencyKeyInvalidError, match="不能超过"):
        validate_idempotency_key("a" * 129)

    with pytest.raises(IdempotencyKeyInvalidError, match="非法字符"):
        validate_idempotency_key("bad key!")
