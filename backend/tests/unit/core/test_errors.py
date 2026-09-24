"""Unit tests for the unified business exception hierarchy in app/core/errors.py."""

from app.core.errors import (
    AppError,
    AuthenticationError,
    EmbeddingAuthError,
    EmbeddingError,
    EmbeddingTimeoutError,
    IdempotencyConflictError,
    IdempotencyKeyInvalidError,
    KnowledgeExtractionRetryExceededError,
    KnowledgeNotFoundError,
    KnowledgePointQualityError,
    LLMAuthError,
    LLMError,
    LLMResponseFormatError,
    LLMTimeoutError,
    MaterialInvalidError,
    MaterialNotFoundError,
    MaterialParseError,
    MissingSourceSnippetError,
    OCRReshootExceededError,
    PermissionDeniedError,
    PracticeEmptyQuestionsError,
    PracticeNotFoundError,
    PracticeSessionNotFoundError,
    PracticeSessionStatusError,
    PracticeStatusError,
    QuestionNotFoundError,
    QuestionQualityCheckError,
    QueueError,
    QueueTimeoutError,
    ReshootLimitExceededError,
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

    def test_material_errors(self) -> None:
        """Verify Material error hierarchy, error codes, and status codes."""
        invalid_err = MaterialInvalidError()
        assert invalid_err.error_code == 40001
        assert invalid_err.status_code == 400
        assert invalid_err.message == "学习资料格式不合法或内容不达标"
        assert isinstance(invalid_err, AppError)

        custom_invalid = MaterialInvalidError(
            message="文件大小超出 20MB 上限",
            details={"file_size": 25000000},
        )
        assert custom_invalid.error_code == 40001
        assert custom_invalid.status_code == 400
        assert custom_invalid.details == {"file_size": 25000000}

        reshoot_err = ReshootLimitExceededError()
        assert reshoot_err.error_code == 40002
        assert reshoot_err.status_code == 400
        assert reshoot_err.message == "页面重拍次数已达上限熔断，请重新上传清晰文件"
        assert isinstance(reshoot_err, AppError)
        assert OCRReshootExceededError is ReshootLimitExceededError

        parse_err = MaterialParseError()
        assert parse_err.error_code == 40003
        assert parse_err.status_code == 500
        assert parse_err.message == "学习资料解析处理失败"
        assert isinstance(parse_err, AppError)

        not_found_err = MaterialNotFoundError()
        assert not_found_err.error_code == 40004
        assert not_found_err.status_code == 404
        assert not_found_err.message == "请求的学习资料不存在或已被删除"
        assert isinstance(not_found_err, AppError)

    def test_knowledge_errors(self) -> None:
        """Verify Knowledge error hierarchy, error codes, and status codes."""
        quality_err = KnowledgePointQualityError()
        assert quality_err.error_code == 40005
        assert quality_err.status_code == 400
        assert quality_err.message == "知识点质检未达到合格门禁标准"
        assert isinstance(quality_err, AppError)

        custom_quality_err = KnowledgePointQualityError(
            message="知识点过度拆分",
            details={"density": 100},
        )
        assert custom_quality_err.error_code == 40005
        assert custom_quality_err.status_code == 400
        assert custom_quality_err.details == {"density": 100}

        retry_err = KnowledgeExtractionRetryExceededError()
        assert retry_err.error_code == 40006
        assert retry_err.status_code == 500
        assert retry_err.message == "知识点抽取重试次数耗尽"
        assert isinstance(retry_err, AppError)

        not_found_err = KnowledgeNotFoundError()
        assert not_found_err.error_code == 40007
        assert not_found_err.status_code == 404
        assert not_found_err.message == "请求的知识点不存在或已被删除"
        assert isinstance(not_found_err, AppError)

    def test_question_errors(self) -> None:
        """Verify Question error hierarchy, error codes, and status codes."""
        missing_snippet_err = MissingSourceSnippetError()
        assert missing_snippet_err.error_code == 40003
        assert missing_snippet_err.status_code == 400
        assert missing_snippet_err.message == "检索不到与知识点匹配的有效资料片段，拒绝出题"
        assert isinstance(missing_snippet_err, AppError)

        custom_missing = MissingSourceSnippetError(
            message="自定义检索不到片段",
            details={"similarity": 0.2},
        )
        assert custom_missing.error_code == 40003
        assert custom_missing.status_code == 400
        assert custom_missing.details == {"similarity": 0.2}

        qc_err = QuestionQualityCheckError()
        assert qc_err.error_code == 40008
        assert qc_err.status_code == 400
        assert qc_err.message == "题目质检未达到合格门禁标准"
        assert isinstance(qc_err, AppError)

        custom_qc = QuestionQualityCheckError(
            message="重复题目超限",
            details={"check_type": "DUPLICATE"},
        )
        assert custom_qc.error_code == 40008
        assert custom_qc.status_code == 400
        assert custom_qc.details == {"check_type": "DUPLICATE"}

        not_found_err = QuestionNotFoundError()
        assert not_found_err.error_code == 40009
        assert not_found_err.status_code == 404
        assert not_found_err.message == "请求的题目不存在或无权访问"
        assert isinstance(not_found_err, AppError)

        custom_not_found = QuestionNotFoundError(
            message="题目不存在",
            details={"question_id": "123"},
        )
        assert custom_not_found.error_code == 40009
        assert custom_not_found.status_code == 404
        assert custom_not_found.details == {"question_id": "123"}

    def test_practice_errors(self) -> None:
        """Verify Practice domain errors codes, messages, and aliases."""
        not_found = PracticeNotFoundError()
        assert not_found.error_code == 40010
        assert not_found.status_code == 404
        assert not_found.message == "请求的练习不存在或无权访问"
        assert isinstance(not_found, AppError)
        assert PracticeSessionNotFoundError is PracticeNotFoundError

        custom_nf = PracticeNotFoundError(
            message="练习会话不存在",
            details={"practice_id": "p1"},
        )
        assert custom_nf.error_code == 40010
        assert custom_nf.status_code == 404
        assert custom_nf.details == {"practice_id": "p1"}

        status_err = PracticeStatusError()
        assert status_err.error_code == 40011
        assert status_err.status_code == 400
        assert status_err.message == "练习状态流转不合法，当前状态禁止该操作"
        assert isinstance(status_err, AppError)
        assert PracticeSessionStatusError is PracticeStatusError

        custom_status = PracticeStatusError(
            message="状态非法",
            details={"current_status": "completed"},
        )
        assert custom_status.error_code == 40011
        assert custom_status.status_code == 400
        assert custom_status.details == {"current_status": "completed"}

        empty_q_err = PracticeEmptyQuestionsError()
        assert empty_q_err.error_code == 40012
        assert empty_q_err.status_code == 400
        assert empty_q_err.message == "题库可用题目不足，无法满足当前出题配置要求"
        assert isinstance(empty_q_err, AppError)

        custom_empty = PracticeEmptyQuestionsError(
            message="题目不足",
            details={"required": 10, "available": 3},
        )
        assert custom_empty.error_code == 40012
        assert custom_empty.status_code == 400
        assert custom_empty.details == {"required": 10, "available": 3}
