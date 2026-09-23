"""智练系统统一业务异常与错误码定义模块。

严格遵循 AGENTS.md 规范：
- 错误码采用 5 位数字体系：
  - 10xxx: 参数校验与请求格式问题
  - 20xxx: 鉴权与权限越权问题 (20001 未登录/认证失效, 20002 无权访问)
  - 30xxx: 外部能力与网络问题
  - 40xxx: 算法与质量门禁阻断
  - 50xxx: 内部系统与数据库问题
"""

from typing import Any


class AppError(Exception):
    """智练全系统统一业务异常基类。

    所有业务逻辑异常必须继承此类，携带标准错误码、HTTP 状态码及用户提示文案。

    Args:
        error_code: 5 位标准业务错误码。
        message: 面向调用方的用户友好提示文案。
        status_code: 对应 HTTP 响应状态码，默认为 400。
        details: 结构化错误辅助诊断信息字典，严禁包含敏感机密。
        code: 错误码别名参数，兼容 code 命名。
        detail: 详情别名参数，兼容 detail 命名。
    """

    def __init__(
        self,
        error_code: int = 40000,
        message: str = "系统业务处理异常",
        status_code: int = 400,
        details: dict[str, Any] | None = None,
        *,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        actual_code = code if code is not None else error_code
        actual_details = detail if detail is not None else (details or {})
        super().__init__(message)
        self.error_code = actual_code
        self.message = message
        self.status_code = status_code
        self.details = actual_details

    @property
    def code(self) -> int:
        """错误码别名属性。"""
        return self.error_code

    @property
    def detail(self) -> dict[str, Any]:
        """错误详情别名属性。"""
        return self.details

    def to_dict(self) -> dict[str, Any]:
        """将异常转换为符合对外统一响应规范的字典。

        Returns:
            dict[str, Any]: 结构化错误字典。
        """
        return {
            "code": self.error_code,
            "message": self.message,
            "details": self.details,
        }


class AuthenticationError(AppError):
    """身份认证异常 (错误码 20001, HTTP 401)。

    当请求未携带凭证、凭证签名损坏、已过期或用户版本失效时抛出。

    Args:
        message: 异常描述文案，默认 "身份认证失败或凭证已过期"。
        details: 结构化附加诊断信息。
        detail: 附加信息别名参数。
    """

    def __init__(
        self,
        message: str = "身份认证失败或凭证已过期",
        details: dict[str, Any] | None = None,
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            error_code=20001,
            message=message,
            status_code=401,
            details=details,
            detail=detail,
        )


class PermissionDeniedError(AppError):
    """权限越权拒绝异常 (错误码 20002, HTTP 403)。

    当用户尝试跨租户访问非本人归属资源或执行未授权操作时抛出。

    Args:
        message: 异常描述文案，默认 "无权访问此资源"。
        details: 结构化附加诊断信息。
        detail: 附加信息别名参数。
    """

    def __init__(
        self,
        message: str = "无权访问此资源",
        details: dict[str, Any] | None = None,
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            error_code=20002,
            message=message,
            status_code=403,
            details=details,
            detail=detail,
        )


class StorageError(AppError):
    """对象存储基础业务异常 (错误码 30001, HTTP 500)。

    当对象存储服务发生通用读写失败、配置缺失或底层异常时抛出。

    Args:
        message: 异常描述文案，默认 "对象存储服务异常"。
        details: 结构化附加诊断信息。
        error_code: 错误码，默认 30001。
        status_code: HTTP 状态码，默认 500。
        code: 错误码别名参数。
        detail: 附加信息别名参数。
    """

    def __init__(
        self,
        message: str = "对象存储服务异常",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 30001,
        status_code: int = 500,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            error_code=error_code,
            message=message,
            status_code=status_code,
            details=details,
            code=code,
            detail=detail,
        )


class StorageNotFoundError(StorageError):
    """请求的存储对象不存在异常 (错误码 30002, HTTP 404)。

    当请求的存储桶或对象键不存在时抛出。

    Args:
        message: 异常描述文案，默认 "请求的存储对象不存在"。
        details: 结构化附加诊断信息。
        code: 错误码别名参数。
        detail: 附加信息别名参数。
    """

    def __init__(
        self,
        message: str = "请求的存储对象不存在",
        details: dict[str, Any] | None = None,
        *,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code=30002,
            status_code=404,
            code=code,
            detail=detail,
        )


class StorageConnectionError(StorageError):
    """对象存储服务连接失败异常 (错误码 30003, HTTP 503)。

    当对象存储服务网络连接超时、Endpoint 无法解析或第三方驱动缺失时抛出。

    Args:
        message: 异常描述文案，默认 "对象存储服务连接失败"。
        details: 结构化附加诊断信息。
        code: 错误码别名参数。
        detail: 附加信息别名参数。
    """

    def __init__(
        self,
        message: str = "对象存储服务连接失败",
        details: dict[str, Any] | None = None,
        *,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code=30003,
            status_code=503,
            code=code,
            detail=detail,
        )


class OCRError(AppError):
    """OCR 识别服务基础异常 (错误码 30004, HTTP 502)。

    当 OCR 服务发生通用识别失败、图像解码异常或底层第三方 SDK 故障时抛出。
    """

    def __init__(
        self,
        message: str = "OCR服务异常",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 30004,
        status_code: int = 502,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            error_code=error_code,
            message=message,
            status_code=status_code,
            details=details,
            code=code,
            detail=detail,
        )


class OCRTimeoutError(OCRError):
    """OCR 识别服务调用超时异常 (错误码 30005, HTTP 504)。

    当 OCR 服务网络连接超时、等待响应超时（超过预设 timeout 阈值）时抛出。
    """

    def __init__(
        self,
        message: str = "OCR服务响应超时",
        details: dict[str, Any] | None = None,
        *,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code=30005,
            status_code=504,
            code=code,
            detail=detail,
        )


class OCRAuthError(OCRError):
    """OCR 识别服务鉴权或授权失败异常 (错误码 30006, HTTP 502)。

    当腾讯云或第三方 OCR 凭证密钥失效、权限不足或未开通服务时抛出。
    """

    def __init__(
        self,
        message: str = "OCR服务认证或授权失败",
        details: dict[str, Any] | None = None,
        *,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code=30006,
            status_code=502,
            code=code,
            detail=detail,
        )


class EmbeddingError(AppError):
    """向量化服务基础异常 (错误码 30007, HTTP 502)。

    当向量化服务发生通用失败、第三方 API 异常响应或数据反序列化错误时抛出。
    """

    def __init__(
        self,
        message: str = "向量化服务异常",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 30007,
        status_code: int = 502,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            error_code=error_code,
            message=message,
            status_code=status_code,
            details=details,
            code=code,
            detail=detail,
        )


class EmbeddingTimeoutError(EmbeddingError):
    """向量化服务调用超时异常 (错误码 30008, HTTP 504)。

    当向量化服务网络连接超时或等待响应超时（超过预设 timeout 阈值）时抛出。
    """

    def __init__(
        self,
        message: str = "向量化服务响应超时",
        details: dict[str, Any] | None = None,
        *,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code=30008,
            status_code=504,
            code=code,
            detail=detail,
        )


class EmbeddingAuthError(EmbeddingError):
    """向量化服务鉴权或授权失败异常 (错误码 30009, HTTP 502)。

    当通义千问或 OpenAI 兼容 API 凭据失效、权限不足或配额耗尽时抛出。
    """

    def __init__(
        self,
        message: str = "向量化服务认证或授权失败",
        details: dict[str, Any] | None = None,
        *,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code=30009,
            status_code=502,
            code=code,
            detail=detail,
        )


class SearchError(AppError):
    """检索服务基础业务异常 (错误码 30010, HTTP 500)。

    当混合检索流水线执行出现未预期的数据库异常、维度不匹配或排序融合失败时抛出。
    """

    def __init__(
        self,
        message: str = "检索服务执行异常",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 30010,
        status_code: int = 500,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            error_code=error_code,
            message=message,
            status_code=status_code,
            details=details,
            code=code,
            detail=detail,
        )


__all__ = [
    "AppError",
    "AuthenticationError",
    "EmbeddingAuthError",
    "EmbeddingError",
    "EmbeddingTimeoutError",
    "OCRAuthError",
    "OCRError",
    "OCRTimeoutError",
    "PermissionDeniedError",
    "SearchError",
    "StorageConnectionError",
    "StorageError",
    "StorageNotFoundError",
]
