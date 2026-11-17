"""ScopedCoachRequest 契约测试：thread_id 校验与单范围约束。"""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.question import ScopedCoachRequest


def make(**kwargs: object) -> ScopedCoachRequest:
    data: dict[str, object] = {"material_id": uuid.uuid4(), "user_prompt": "什么是 PCA？"}
    data.update(kwargs)
    return ScopedCoachRequest(**data)  # type: ignore[arg-type]


class TestThreadIdValidation:
    def test_optional_defaults_to_none(self) -> None:
        assert make().thread_id is None

    def test_accepts_valid_and_max_length(self) -> None:
        assert make(thread_id="kp:abc").thread_id == "kp:abc"
        assert make(thread_id="x" * 128).thread_id == "x" * 128

    def test_rejects_empty_and_too_long(self) -> None:
        with pytest.raises(ValidationError):
            make(thread_id="")
        with pytest.raises(ValidationError):
            make(thread_id="x" * 129)

    def test_rejects_non_string(self) -> None:
        with pytest.raises(ValidationError):
            make(thread_id=123)


class TestOtherConstraints:
    def test_exactly_one_scope_required(self) -> None:
        with pytest.raises(ValidationError):
            ScopedCoachRequest(user_prompt="问题")
        with pytest.raises(ValidationError):
            ScopedCoachRequest(folder_id=uuid.uuid4(), material_id=uuid.uuid4(), user_prompt="问题")

    def test_user_prompt_bounds(self) -> None:
        with pytest.raises(ValidationError):
            make(user_prompt="")
        with pytest.raises(ValidationError):
            make(user_prompt="问" * 1001)
        assert make(user_prompt="问" * 1000).user_prompt == "问" * 1000
