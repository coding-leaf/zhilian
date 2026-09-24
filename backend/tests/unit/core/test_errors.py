"""Unit tests for the unified business exception hierarchy in app/core/errors.py."""

from app.core.errors import (
    AppError,
    AuthenticationError,
    EmbeddingAuthError,
    EmbeddingError,
    EmbeddingTimeoutError,
    IdempotencyConflictError,
    IdempotencyKeyInvalidError,
    LLMAuthError,
    LLMError,
    LLMResponseFormatError,
    LLMTimeoutError,
    PermissionDeniedError,
    QueueError,
    QueueTimeoutError,
    SearchError,
)


class TestAppErrors:
    """Test suite for AppError and derived domain exceptions."""

    def test_app_error_defaults(self) -> None:
        """Verify AppError default attributes."""
        error = AppError()
        assert error.error_code == 40000
        assert error.code == 40000
        assert error.status_code == 400
        assert error.message == "系统业务处理异常"
        assert error.details == {}
        assert error.detail == {}
        assert error.to_dict() == {
            "code": 40000,
            "message": "系统业务处理异常",
            "details": {},
        }

    def test_app_error_custom_fields(self) -> None:
        """Verify AppError custom initialization with alias parameters."""
        error = AppError(
            code=40005,
            message="自定义验证错误",
            status_code=422,
            detail={"field": "username"},
        )
        assert error.error_code == 40005
        assert error.code == 40005
        assert error.status_code == 422
        assert error.details == {"field": "username"}
        assert error.detail == {"field": "username"}
        assert error.to_dict() == {
            "code": 40005,
            "message": "自定义验证错误",
            "details": {"field": "username"},
        }

    def test_authentication_error(self) -> None:
        """Verify AuthenticationError code and default status."""
        error = AuthenticationError(message="Token expired", detail={"sub": "123"})
        assert error.error_code == 20001
        assert error.code == 20001
        assert error.status_code == 401
        assert error.message == "Token expired"
        assert error.details == {"sub": "123"}
        assert error.detail == {"sub": "123"}

    def test_permission_denied_error(self) -> None:
        """Verify PermissionDeniedError code and default status."""
        error = PermissionDeniedError(message="Access denied", detail={"resource": "notes"})
        assert error.error_code == 20002
        assert error.code == 20002
        assert error.status_code == 403
        assert error.message == "Access denied"
        assert error.details == {"resource": "notes"}
        assert error.detail == {"resource": "notes"}

    def test_embedding_errors(self) -> None:
        """Verify Embedding error hierarchy, error codes, and status codes."""
        base_err = EmbeddingError()
        assert base_err.error_code == 30007
        assert base_err.status_code == 502

        timeout_err = EmbeddingTimeoutError(message="Timeout calling embedding")
        assert timeout_err.error_code == 30008
        assert timeout_err.status_code == 504
        assert timeout_err.message == "Timeout calling embedding"
        assert isinstance(timeout_err, EmbeddingError)

        auth_err = EmbeddingAuthError(message="Invalid API Key")
        assert auth_err.error_code == 30009
        assert auth_err.status_code == 502
        assert auth_err.message == "Invalid API Key"
        assert isinstance(auth_err, EmbeddingError)

    def test_search_error(self) -> None:
        """Verify SearchError default attributes and custom fields."""
        err = SearchError()
        assert err.error_code == 30010
        assert err.status_code == 500
        assert err.message == "检索服务执行异常"

        custom_err = SearchError(
            message="Query syntax invalid",
            details={"cause": "bad_syntax"},
            status_code=400,
        )
        assert custom_err.error_code == 30010
        assert custom_err.status_code == 400
        assert custom_err.details == {"cause": "bad_syntax"}

    def test_llm_errors(self) -> None:
        """Verify LLM error hierarchy, error codes, and status codes."""
        base_err = LLMError()
        assert base_err.error_code == 30011
        assert base_err.status_code == 502
        assert base_err.message == "大模型服务异常"
        assert isinstance(base_err, AppError)

        timeout_err = LLMTimeoutError(message="Timeout calling LLM")
        assert timeout_err.error_code == 30012
        assert timeout_err.status_code == 504
        assert timeout_err.message == "Timeout calling LLM"
        assert isinstance(timeout_err, LLMError)

        auth_err = LLMAuthError(message="Invalid API Key")
        assert auth_err.error_code == 30013
        assert auth_err.status_code == 502
        assert auth_err.message == "Invalid API Key"
        assert isinstance(auth_err, LLMError)

        format_err = LLMResponseFormatError(message="Schema validation failed")
        assert format_err.error_code == 30014
        assert format_err.status_code == 502
        assert format_err.message == "Schema validation failed"
        assert isinstance(format_err, LLMError)

    def test_queue_errors(self) -> None:
        """Verify Queue error hierarchy, error codes, and status codes."""
        base_err = QueueError()
        assert base_err.error_code == 30015
        assert base_err.status_code == 500
        assert base_err.message == "异步任务队列服务异常"
        assert isinstance(base_err, AppError)

        custom_err = QueueError(
            message="Redis connection dropped",
            details={"broker": "redis"},
            status_code=503,
        )
        assert custom_err.error_code == 30015
        assert custom_err.status_code == 503
        assert custom_err.details == {"broker": "redis"}

        timeout_err = QueueTimeoutError(message="Task wait timeout")
        assert timeout_err.error_code == 30016
        assert timeout_err.status_code == 504
        assert timeout_err.message == "Task wait timeout"
        assert isinstance(timeout_err, QueueError)

    def test_idempotency_errors(self) -> None:
        """Verify Idempotency error hierarchy, error codes, and status codes."""
        conflict_err = IdempotencyConflictError()
        assert conflict_err.error_code == 30017
        assert conflict_err.status_code == 409
        assert conflict_err.message == "请求正在并发处理中，请勿重复提交"
        assert isinstance(conflict_err, AppError)

        custom_conflict = IdempotencyConflictError(
            message="Duplicate submission in progress",
            details={"key": "k-123"},
        )
        assert custom_conflict.error_code == 30017
        assert custom_conflict.status_code == 409
        assert custom_conflict.details == {"key": "k-123"}

        invalid_key_err = IdempotencyKeyInvalidError()
        assert invalid_key_err.error_code == 30018
        assert invalid_key_err.status_code == 400
        assert invalid_key_err.message == "幂等键格式不合法"
        assert isinstance(invalid_key_err, AppError)

        custom_invalid = IdempotencyKeyInvalidError(
            message="Idempotency-Key too long",
            details={"length": 256},
        )
        assert custom_invalid.error_code == 30018
        assert custom_invalid.status_code == 400
        assert custom_invalid.details == {"length": 256}
