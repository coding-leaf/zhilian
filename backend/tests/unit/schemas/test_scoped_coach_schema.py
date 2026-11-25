"""ScopedCoachRequest 契约测试：thread_id 校验、global 默认归一化与范围约束。"""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.question import AskCoachHistoryItem, ScopedCoachRequest


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
    def test_empty_ids_normalizes_to_global_and_rejects_invalid_combinations(self) -> None:
        default_req = ScopedCoachRequest(user_prompt="问题")
        assert default_req.scope == "global"
        assert default_req.history == []

        with_history = ScopedCoachRequest(
            user_prompt="追问",
            history=[AskCoachHistoryItem(role="user", content="你好")],
        )
        assert with_history.scope == "global"
        assert len(with_history.history) == 1

        for bad_kwargs in (
            {"folder_id": uuid.uuid4(), "material_id": uuid.uuid4(), "user_prompt": "问题"},
            {"scope": "global", "folder_id": uuid.uuid4(), "user_prompt": "问题"},
            {"scope": "folder", "user_prompt": "问题"},
            {"scope": "material", "user_prompt": "问题"},
            {"scope": "knowledge_point", "user_prompt": "问题"},
        ):
            with pytest.raises(ValidationError):
                ScopedCoachRequest(**bad_kwargs)  # type: ignore[arg-type]

    def test_user_prompt_bounds(self) -> None:
        with pytest.raises(ValidationError):
            make(user_prompt="")
        with pytest.raises(ValidationError):
            make(user_prompt="问" * 1001)
        assert make(user_prompt="问" * 1000).user_prompt == "问" * 1000
