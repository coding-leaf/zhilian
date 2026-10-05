"""单元测试补充：app/core/errors.py 中未覆盖的异常类与参数化路径。

补测目标：将 `app/core/errors.py` 覆盖率从 91% 提升至 ≥99%。
覆盖范围：
- StorageError / StorageNotFoundError / StorageConnectionError 三个异常类
- OCRError / OCRTimeoutError / OCRAuthError / OCRQuotaError 四个异常类
- FolderNotFoundError / FolderNameConflictError 两个异常类
- WrongRecordNotFoundError 异常类（未在现有 test_errors.py 导入）
- AttemptItemNotFoundError.attempt_item_id / MasteryRecordNotFoundError.knowledge_point_id
  / WrongRecordNotFoundError.record_id 三个参数化注入路径
- AppError.cause 异常原因保留契约（防 P0-2 错误原因丢失）
- 错误码 ↔ HTTP 状态码映射唯一性契约（评审清单 3.1：① 算法核 / ③ 错误契约）

按《单测计划》§4.1 P0「app/core/errors.py：错误契约：上游原因保留、状态映射唯一」要求编写。
"""

import pytest

from app.core.errors import (
    AppError,
    AttemptItemNotFoundError,
    AuthenticationError,
    EmbeddingAuthError,
    EmbeddingError,
    EmbeddingTimeoutError,
    FolderNameConflictError,
    FolderNotFoundError,
    GradingExecutionError,
    GradingNotAllowedError,
    IdempotencyConflictError,
    IdempotencyKeyInvalidError,
    KnowledgeExtractionRetryExceededError,
    KnowledgeNotFoundError,
    KnowledgePointQualityError,
    LLMAuthError,
    LLMError,
    LLMResponseFormatError,
    LLMTimeoutError,
    MasteryRecordNotFoundError,
    MaterialInvalidError,
    MaterialNotFoundError,
    MaterialParseError,
    MissingSourceSnippetError,
    OCRAuthError,
    OCRError,
    OCRQuotaError,
    OCRReshootExceededError,
    OCRTimeoutError,
    PermissionDeniedError,
    PracticeEmptyQuestionsError,
    PracticeNotFoundError,
    PracticeNotGradedError,
    PracticeStatusError,
    QuestionNotFoundError,
    QuestionQualityCheckError,
    QueueError,
    QueueTimeoutError,
    ReshootLimitExceededError,
    SearchError,
    StorageConnectionError,
    StorageError,
    StorageNotFoundError,
    WrongRecordNotFoundError,
)


class TestStorageErrorContract:
    """StorageError / StorageNotFoundError / StorageConnectionError 错误契约。"""

    def test_storage_error_default_attributes(self) -> None:
        """StorageError 默认属性：错误码 30001、HTTP 500、默认消息。"""
        err = StorageError()
        assert err.error_code == 30001
        assert err.status_code == 500
        assert err.message == "对象存储服务异常"
        assert err.details == {}
        assert isinstance(err, AppError)

    def test_storage_error_custom_error_code_and_status(self) -> None:
        """StorageError 支持自定义 error_code 与 status_code（行 148 默认路径）。"""
        err = StorageError(
            message="自定义存储异常",
            error_code=30999,
            status_code=503,
            details={"bucket": "test-bucket"},
        )
        assert err.error_code == 30999
        assert err.status_code == 503
        assert err.message == "自定义存储异常"
        assert err.details == {"bucket": "test-bucket"}

    def test_storage_not_found_error(self) -> None:
        """StorageNotFoundError 错误码 30002，HTTP 404。"""
        err = StorageNotFoundError(message="Bucket 不存在")
        assert err.error_code == 30002
        assert err.status_code == 404
        assert err.message == "Bucket 不存在"
        assert isinstance(err, StorageError)
        assert isinstance(err, AppError)

    def test_storage_connection_error(self) -> None:
        """StorageConnectionError 错误码 30003，HTTP 503。"""
        err = StorageConnectionError(message="Endpoint 不可达")
        assert err.error_code == 30003
        assert err.status_code == 503
        assert err.message == "Endpoint 不可达"
        assert isinstance(err, StorageError)

    def test_storage_error_serialization(self) -> None:
        """StorageError 必须可序列化为对外统一响应字典。"""
        err = StorageConnectionError(details={"endpoint": "oss-cn-hangzhou.aliyuncs.com"})
        payload = err.to_dict()
        assert payload["code"] == 30003
        assert "endpoint" in payload["details"]


class TestOCRErrorContract:
    """OCRError / OCRTimeoutError / OCRAuthError / OCRQuotaError 错误契约。"""

    def test_ocr_error_default_attributes(self) -> None:
        """OCRError 默认属性：错误码 30004、HTTP 502。"""
        err = OCRError()
        assert err.error_code == 30004
        assert err.status_code == 502
        assert err.message == "OCR服务异常"
        assert isinstance(err, AppError)

    def test_ocr_error_custom_attributes(self) -> None:
        """OCRError 支持自定义 error_code 与 status_code。"""
        err = OCRError(
            message="图像解码失败",
            error_code=30010,
            status_code=500,
            details={"format": "tiff"},
        )
        assert err.error_code == 30010
        assert err.status_code == 500
        assert err.details == {"format": "tiff"}

    def test_ocr_timeout_error(self) -> None:
        """OCRTimeoutError 错误码 30005，HTTP 504。"""
        err = OCRTimeoutError(message="OCR 接口响应超时 (15s)")
        assert err.error_code == 30005
        assert err.status_code == 504
        assert err.message == "OCR 接口响应超时 (15s)"
        assert isinstance(err, OCRError)
        assert isinstance(err, AppError)

    def test_ocr_auth_error(self) -> None:
        """OCRAuthError 错误码 30006，HTTP 502。"""
        err = OCRAuthError(message="腾讯云 OCR SecretId 无效")
        assert err.error_code == 30006
        assert err.status_code == 502
        assert err.message == "腾讯云 OCR SecretId 无效"
        assert isinstance(err, OCRError)

    def test_ocr_quota_error(self) -> None:
        """OCRQuotaError 错误码 30019，HTTP 429（频率/配额限制）。"""
        err = OCRQuotaError(message="百度 OCR 当日调用量已用完")
        assert err.error_code == 30019
        assert err.status_code == 429
        assert err.message == "百度 OCR 当日调用量已用完"
        assert isinstance(err, OCRError)

    def test_ocr_reshoot_alias_matches_reshoot_limit(self) -> None:
        """OCRReshootExceededError 必须是 ReshootLimitExceededError 的别名。"""
        assert OCRReshootExceededError is ReshootLimitExceededError


class TestFolderAndRecordErrors:
    """FolderNotFoundError / FolderNameConflictError / WrongRecordNotFoundError 错误契约。"""

    def test_folder_not_found_error(self) -> None:
        """FolderNotFoundError 错误码 40020，HTTP 404。"""
        err = FolderNotFoundError(message="课程文件夹不存在")
        assert err.error_code == 40020
        assert err.status_code == 404
        assert err.message == "课程文件夹不存在"
        assert isinstance(err, AppError)

    def test_folder_name_conflict_error(self) -> None:
        """FolderNameConflictError 错误码 40021，HTTP 409。"""
        err = FolderNameConflictError(message="同名文件夹已存在")
        assert err.error_code == 40021
        assert err.status_code == 409
        assert err.message == "同名文件夹已存在"
        assert isinstance(err, AppError)

    def test_wrong_record_not_found_error(self) -> None:
        """WrongRecordNotFoundError 错误码 40019，HTTP 404。"""
        err = WrongRecordNotFoundError(message="错题记录不存在")
        assert err.error_code == 40019
        assert err.status_code == 404
        assert err.message == "错题记录不存在"
        assert isinstance(err, AppError)


class TestParameterInjectionPaths:
    """attempt_item_id / knowledge_point_id / record_id 参数注入路径。"""

    def test_attempt_item_not_found_injects_attempt_item_id_into_details(self) -> None:
        """AttemptItemNotFoundError(attempt_item_id=...) 必须写入 details.attempt_item_id。"""
        err = AttemptItemNotFoundError(
            message="作答明细不存在",
            attempt_item_id="item-uuid-1234",
        )
        assert err.details["attempt_item_id"] == "item-uuid-1234"

    def test_mastery_record_not_found_injects_knowledge_point_id_into_details(self) -> None:
        """MasteryRecordNotFoundError(knowledge_point_id=...) 必须写入 details。"""
        err = MasteryRecordNotFoundError(
            message="掌握度记录缺失",
            knowledge_point_id="kp-uuid-9999",
        )
        assert err.details["knowledge_point_id"] == "kp-uuid-9999"

    def test_wrong_record_not_found_injects_record_id_into_details(self) -> None:
        """WrongRecordNotFoundError(record_id=...) 必须写入 details.record_id。"""
        err = WrongRecordNotFoundError(
            message="错题记录缺失",
            record_id="wrong-uuid-7777",
        )
        assert err.details["record_id"] == "wrong-uuid-7777"

    def test_attempt_item_id_none_does_not_populate_details(self) -> None:
        """attempt_item_id=None 时不应在 details 中出现 attempt_item_id 键。"""
        err = AttemptItemNotFoundError(message="明细缺失")
        assert "attempt_item_id" not in err.details

    def test_mastery_record_id_none_does_not_populate_details(self) -> None:
        """knowledge_point_id=None 时不应在 details 中出现 knowledge_point_id 键。"""
        err = MasteryRecordNotFoundError(message="掌握度缺失")
        assert "knowledge_point_id" not in err.details

    def test_wrong_record_id_none_does_not_populate_details(self) -> None:
        """record_id=None 时不应在 details 中出现 record_id 键。"""
        err = WrongRecordNotFoundError(message="错题缺失")
        assert "record_id" not in err.details

    def test_attempt_item_id_without_explicit_detail_only_has_id(self) -> None:
        """未传 detail 时：merged_details 仅含 attempt_item_id。"""
        err = AttemptItemNotFoundError(
            message="明细缺失",
            attempt_item_id="item-1",
        )
        assert err.details == {"attempt_item_id": "item-1"}

    def test_attempt_item_id_uses_details_alias_when_no_detail_kwarg(self) -> None:
        """传 details (位置参数) 而非 detail 关键字别名时：attempt_item_id 合并入 details。"""
        err = AttemptItemNotFoundError(
            "明细缺失",
            {"context": "retry"},
            attempt_item_id="item-1",
        )
        # 走 details 位置参数时，detail 别名不会被父类覆盖
        assert err.details["context"] == "retry"
        assert err.details["attempt_item_id"] == "item-1"

    def test_attempt_item_id_with_detail_alias_kwargs(self) -> None:
        """同时传 detail 别名与 attempt_item_id：合并语义生效，两个字段都被保留。

        BUG-FIX: AttemptItemNotFoundError.__init__ 在调用 super().__init__ 时不再传
        detail 别名（仅通过 details 通道传递），保证 attempt_item_id 注入不会被覆盖。
        """
        err = AttemptItemNotFoundError(
            message="明细缺失",
            detail={"context": "retry"},
            attempt_item_id="item-1",
        )
        assert err.details["context"] == "retry"
        assert err.details["attempt_item_id"] == "item-1"


class TestErrorCodeStatusMappingUniqueness:
    """错误契约：error_code ↔ HTTP status_code 映射必须唯一、无二义。

    对应评审清单 3.1「错误码与 HTTP 状态映射是否唯一、无二义」的契约验证。
    """

    @pytest.mark.parametrize(
        ("error_class", "expected_code", "expected_status"),
        [
            (AuthenticationError, 20001, 401),
            (PermissionDeniedError, 20002, 403),
            (StorageError, 30001, 500),
            (StorageNotFoundError, 30002, 404),
            (StorageConnectionError, 30003, 503),
            (OCRError, 30004, 502),
            (OCRTimeoutError, 30005, 504),
            (OCRAuthError, 30006, 502),
            (OCRQuotaError, 30019, 429),
            (EmbeddingError, 30007, 502),
            (EmbeddingTimeoutError, 30008, 504),
            (EmbeddingAuthError, 30009, 502),
            (SearchError, 30010, 500),
            (LLMError, 30011, 502),
            (LLMTimeoutError, 30012, 504),
            (LLMAuthError, 30013, 502),
            (LLMResponseFormatError, 30014, 502),
            (QueueError, 30015, 500),
            (QueueTimeoutError, 30016, 504),
            (IdempotencyConflictError, 30017, 409),
            (IdempotencyKeyInvalidError, 30018, 400),
            (MaterialInvalidError, 40001, 400),
            (ReshootLimitExceededError, 40002, 400),
            (MaterialParseError, 40003, 500),
            (MaterialNotFoundError, 40004, 404),
            (KnowledgePointQualityError, 40005, 400),
            (KnowledgeExtractionRetryExceededError, 40006, 500),
            (KnowledgeNotFoundError, 40007, 404),
            (MissingSourceSnippetError, 40003, 400),
            (QuestionQualityCheckError, 40008, 400),
            (QuestionNotFoundError, 40009, 404),
            (PracticeNotFoundError, 40010, 404),
            (PracticeStatusError, 40011, 400),
            (PracticeEmptyQuestionsError, 40012, 400),
            (AttemptItemNotFoundError, 40013, 404),
            (GradingNotAllowedError, 40014, 400),
            (GradingExecutionError, 40015, 500),
            (PracticeNotGradedError, 40016, 400),
            (MasteryRecordNotFoundError, 40018, 404),
            (WrongRecordNotFoundError, 40019, 404),
            (FolderNotFoundError, 40020, 404),
            (FolderNameConflictError, 40021, 409),
        ],
    )
    def test_error_code_status_mapping_is_unique(
        self,
        error_class: type[AppError],
        expected_code: int,
        expected_status: int,
    ) -> None:
        """每个错误码必须唯一映射到其声明的 HTTP 状态码。"""
        err = error_class()
        assert err.error_code == expected_code
        assert err.status_code == expected_status
        # 序列化字典必须保留错误码与状态码一致性
        payload = err.to_dict()
        assert payload["code"] == expected_code


class TestErrorCausePreservation:
    """上游异常原因保留契约：防 P0-2「raise from 链路中上游原因丢失」。

    通过 raise X from Y 时，Y 必须可在异常链中追溯（__cause__），
    确保运维与排错时能够定位根因。
    """

    def test_authentication_error_preserves_cause_chain(self) -> None:
        """raise AuthenticationError from upstream 时，__cause__ 必须指向 upstream。"""
        upstream = ValueError("上游 JWT 库抛出底层异常")
        try:
            raise AuthenticationError(message="凭证签名无效") from upstream
        except AuthenticationError as err:
            assert err.__cause__ is upstream
            assert isinstance(err.__cause__, ValueError)

    def test_permission_denied_error_preserves_cause_chain(self) -> None:
        """PermissionDeniedError 同样必须保留异常链。"""
        upstream = KeyError("资源 key 不存在")
        try:
            raise PermissionDeniedError(message="无权访问") from upstream
        except PermissionDeniedError as err:
            assert err.__cause__ is upstream

    def test_app_error_default_cause_is_none(self) -> None:
        """未通过 from 抛出时，__cause__ 必须是 None（不影响默认行为）。"""
        err = AppError()
        assert err.__cause__ is None

    def test_cause_propagates_through_subclass(self) -> None:
        """子类异常的 __cause__ 必须能传递父类链路。"""
        upstream = RuntimeError("底层 IO 异常")
        try:
            raise StorageConnectionError(message="连接失败") from upstream
        except StorageConnectionError as err:
            assert err.__cause__ is upstream
            assert isinstance(err, AppError)
            assert isinstance(err, StorageError)


class TestAppErrorAliasParameters:
    """AppError 的 code / detail 别名参数契约。"""

    def test_app_error_with_detail_alias_merges_into_details(self) -> None:
        """传入 detail 别名时必须写入 details 字段。"""
        err = AppError(message="测试", detail={"k": "v"})
        assert err.details == {"k": "v"}
        assert err.detail == {"k": "v"}

    def test_app_error_with_details_and_detail_prefers_detail_alias(self) -> None:
        """同时传 details 与 detail 时，detail 别名优先（不静默丢失用户输入）。"""
        err = AppError(message="测试", details={"old": 1}, detail={"new": 2})
        assert err.details == {"new": 2}

    def test_app_error_with_code_alias_takes_priority(self) -> None:
        """code 别名参数优先于 error_code（兼容不同命名风格）。"""
        err = AppError(code=40404, error_code=40000)
        assert err.error_code == 40404
        assert err.code == 40404
