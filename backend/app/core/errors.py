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


class LLMError(AppError):
    """大语言模型服务基础异常 (错误码 30011, HTTP 502)。

    当大语言模型适配器发生通用业务异常、服务端错误 (5xx) 且重试耗尽时抛出。
    """

    def __init__(
        self,
        message: str = "大模型服务异常",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 30011,
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


class LLMTimeoutError(LLMError):
    """大语言模型服务调用超时异常 (错误码 30012, HTTP 504)。

    当大语言模型服务网络连接超时或等待响应超时（超过 options.timeout / 预设阈值）时抛出。
    """

    def __init__(
        self,
        message: str = "大模型服务响应超时",
        details: dict[str, Any] | None = None,
        *,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code=30012,
            status_code=504,
            code=code,
            detail=detail,
        )


class LLMAuthError(LLMError):
    """大语言模型服务鉴权或授权失败异常 (错误码 30013, HTTP 502)。

    当 API Key 凭据缺失、无效、未授权或欠费停服 (401/403) 时抛出。
    """

    def __init__(
        self,
        message: str = "大模型服务认证或授权失败",
        details: dict[str, Any] | None = None,
        *,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code=30013,
            status_code=502,
            code=code,
            detail=detail,
        )


class LLMResponseFormatError(LLMError):
    """大语言模型响应格式校验失败异常 (错误码 30014, HTTP 502)。

    当模型输出 JSON 损坏或 Schema 校验失败且单次自愈修复后仍无法通过 Pydantic 校验时抛出。
    """

    def __init__(
        self,
        message: str = "大模型输出格式校验失败",
        details: dict[str, Any] | None = None,
        *,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code=30014,
            status_code=502,
            code=code,
            detail=detail,
        )


class QueueError(AppError):
    """异步任务队列服务基础异常 (错误码 30015, HTTP 500)。

    当任务队列发生通用操作异常、底层驱动故障或出入队失败时抛出。

    Args:
        message: 异常描述文案，默认 "异步任务队列服务异常"。
        details: 结构化附加诊断信息。
        error_code: 错误码，默认 30015。
        status_code: HTTP 状态码，默认 500。
        code: 错误码别名参数。
        detail: 附加信息别名参数。
    """

    def __init__(
        self,
        message: str = "异步任务队列服务异常",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 30015,
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


class QueueTimeoutError(QueueError):
    """异步任务调度响应超时异常 (错误码 30016, HTTP 504)。

    当任务入队等待连接超时或任务同步执行等待超时时抛出。

    Args:
        message: 异常描述文案，默认 "异步任务调度响应超时"。
        details: 结构化附加诊断信息。
        code: 错误码别名参数。
        detail: 附加信息别名参数。
    """

    def __init__(
        self,
        message: str = "异步任务调度响应超时",
        details: dict[str, Any] | None = None,
        *,
        code: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code=30016,
            status_code=504,
            code=code,
            detail=detail,
        )


class IdempotencyConflictError(AppError):
    """幂等并发冲突异常 (错误码 30017, HTTP 409)。

    当相同幂等键在当前租户下正在处理中、未生成最终结果时抛出。

    Args:
        message: 异常描述文案，默认 "请求正在并发处理中，请勿重复提交"。
        details: 结构化附加诊断信息。
        error_code: 错误码，默认 30017。
        status_code: HTTP 状态码，默认 409。
        code: 错误码别名参数。
        detail: 附加信息别名参数。
    """

    def __init__(
        self,
        message: str = "请求正在并发处理中，请勿重复提交",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 30017,
        status_code: int = 409,
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


class IdempotencyKeyInvalidError(AppError):
    """幂等键格式不合法异常 (错误码 30018, HTTP 400)。

    当请求头携带的 Idempotency-Key 为空、超长 (>128 字符) 或含非法字符时抛出。

    Args:
        message: 异常描述文案，默认 "幂等键格式不合法"。
        details: 结构化附加诊断信息。
        error_code: 错误码，默认 30018。
        status_code: HTTP 状态码，默认 400。
        code: 错误码别名参数。
        detail: 附加信息别名参数。
    """

    def __init__(
        self,
        message: str = "幂等键格式不合法",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 30018,
        status_code: int = 400,
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


class MaterialInvalidError(AppError):
    """学习资料无效或不合规异常 (错误码 40001, HTTP 400)。

    当文件大小超限、格式不支持、魔数不匹配或内容为空时抛出。

    Args:
        message: 异常描述文案，默认 "学习资料格式不合法或内容不达标"。
        details: 结构化附加诊断信息。
        error_code: 错误码，默认 40001。
        status_code: HTTP 状态码，默认 400。
        code: 错误码别名参数。
        detail: 附加信息别名参数。
    """

    def __init__(
        self,
        message: str = "学习资料格式不合法或内容不达标",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40001,
        status_code: int = 400,
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


class ReshootLimitExceededError(AppError):
    """页面重拍次数超限熔断异常 (错误码 40002, HTTP 400)。

    当单页重拍次数超过 3 次仍未达到质检合格标准时触发熔断。

    Args:
        message: 异常描述文案，默认 "页面重拍次数已达上限熔断，请重新上传清晰文件"。
        details: 结构化附加诊断信息。
        error_code: 错误码，默认 40002。
        status_code: HTTP 状态码，默认 400。
        code: 错误码别名参数。
        detail: 附加信息别名参数。
    """

    def __init__(
        self,
        message: str = "页面重拍次数已达上限熔断，请重新上传清晰文件",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40002,
        status_code: int = 400,
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


OCRReshootExceededError = ReshootLimitExceededError


class MaterialParseError(AppError):
    """学习资料解析处理失败异常 (错误码 40003, HTTP 500)。

    当文本提取、OCR 门禁未通过或切分/向量化失败时抛出。

    Args:
        message: 异常描述文案，默认 "学习资料解析处理失败"。
        details: 结构化附加诊断信息。
        error_code: 错误码，默认 40003。
        status_code: HTTP 状态码，默认 500。
        code: 错误码别名参数。
        detail: 附加信息别名参数。
    """

    def __init__(
        self,
        message: str = "学习资料解析处理失败",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40003,
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


class MaterialNotFoundError(AppError):
    """学习资料或版本不存在异常 (错误码 40004, HTTP 404)。

    当查询的学习资料或版本不存在或已被软删除时抛出。

    Args:
        message: 异常描述文案，默认 "请求的学习资料不存在或已被删除"。
        details: 结构化附加诊断信息。
        error_code: 错误码，默认 40004。
        status_code: HTTP 状态码，默认 404。
        code: 错误码别名参数。
        detail: 附加信息别名参数。
    """

    def __init__(
        self,
        message: str = "请求的学习资料不存在或已被删除",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40004,
        status_code: int = 404,
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


class KnowledgePointQualityError(AppError):
    """知识点质检门禁严重拦截异常 (错误码 40005, HTTP 400)。

    当知识点抽取结果未通过四项门禁质检且无法自愈时抛出。
    """

    def __init__(
        self,
        message: str = "知识点质检未达到合格门禁标准",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40005,
        status_code: int = 400,
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


class KnowledgeExtractionRetryExceededError(AppError):
    """知识点抽取内部异常耗尽重试 (错误码 40006, HTTP 500)。

    当知识点抽取重试次数耗尽或大模型抽取异常且无法降级恢复时抛出。
    """

    def __init__(
        self,
        message: str = "知识点抽取重试次数耗尽",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40006,
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


class KnowledgeNotFoundError(AppError):
    """请求的知识点不存在或无权访问异常 (错误码 40007, HTTP 404)。

    当查询的知识点不存在或所属租户不匹配时抛出。
    """

    def __init__(
        self,
        message: str = "请求的知识点不存在或已被删除",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40007,
        status_code: int = 404,
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


class MissingSourceSnippetError(AppError):
    """检索不到与知识点匹配的有效资料片段异常 (错误码 40003, HTTP 400)。

    当知识点绑定的切片为空或与考点检索相似度未达到门禁阈值时抛出，阻断题目生成。
    """

    def __init__(
        self,
        message: str = "检索不到与知识点匹配的有效资料片段，拒绝出题",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40003,
        status_code: int = 400,
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


class QuestionQualityCheckError(AppError):
    """题目质检未通过门禁异常 (错误码 40008, HTTP 400)。

    当题目质检四项一票否决门禁未通过且重试耗尽时抛出。
    """

    def __init__(
        self,
        message: str = "题目质检未达到合格门禁标准",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40008,
        status_code: int = 400,
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


class QuestionNotFoundError(AppError):
    """请求的题目不存在或无权访问异常 (错误码 40009, HTTP 404)。

    当查询的题目不存在或所属租户不匹配时抛出。
    """

    def __init__(
        self,
        message: str = "请求的题目不存在或无权访问",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40009,
        status_code: int = 404,
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


class PracticeNotFoundError(AppError):
    """请求的练习不存在或无权访问异常 (错误码 40010, HTTP 404)。

    当查询的练习不存在或所属租户不匹配时抛出。
    """

    def __init__(
        self,
        message: str = "请求的练习不存在或无权访问",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40010,
        status_code: int = 404,
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


PracticeSessionNotFoundError = PracticeNotFoundError


class PracticeStatusError(AppError):
    """练习状态流转不合法异常 (错误码 40011, HTTP 400)。

    当练习当前状态不允许所请求的操作或跃迁时抛出。
    """

    def __init__(
        self,
        message: str = "练习状态流转不合法，当前状态禁止该操作",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40011,
        status_code: int = 400,
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


PracticeSessionStatusError = PracticeStatusError


class PracticeEmptyQuestionsError(AppError):
    """题库可用题目不足异常 (错误码 40012, HTTP 400)。

    当可用题目数量不足以满足组卷出题配置要求时抛出。
    """

    def __init__(
        self,
        message: str = "题库可用题目不足，无法满足当前出题配置要求",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40012,
        status_code: int = 400,
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


class AttemptItemNotFoundError(AppError):
    """作答题目明细不存在异常 (错误码 40013, HTTP 404)。

    当请求的作答题目明细不存在或无权访问时抛出。
    """

    def __init__(
        self,
        message: str = "请求的作答题目明细不存在或无权访问",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40013,
        status_code: int = 404,
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


class GradingNotAllowedError(AppError):
    """判题或自评不合法异常 (错误码 40014, HTTP 400)。

    当客观题尝试自评、打分超出分值上限或练习状态不允许判题时抛出。
    """

    def __init__(
        self,
        message: str = "判题或自评操作不合法",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40014,
        status_code: int = 400,
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


class GradingExecutionError(AppError):
    """判题流水线执行严重异常 (错误码 40015, HTTP 500)。

    当判题流水线在编排或执行中发生不可恢复的系统级故障时抛出。
    """

    def __init__(
        self,
        message: str = "判题流水线执行严重异常",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40015,
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


class PracticeNotGradedError(AppError):
    """练习未完成全量判题异常 (错误码 40016, HTTP 400)。

    当练习处于 PARTIALLY_GRADED 或存在待重判题目时，阻断诊断报告生成。
    """

    def __init__(
        self,
        message: str = "练习尚未完成全量判题（存在待重判题目），无法生成诊断报告",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40016,
        status_code: int = 400,
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


class DiagnosisReportNotFoundError(AppError):
    """诊断报告不存在异常 (错误码 40017, HTTP 404)。

    当请求的学情诊断报告不存在或无权访问时抛出。
    """

    def __init__(
        self,
        message: str = "诊断报告不存在",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40017,
        status_code: int = 404,
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


class MasteryRecordNotFoundError(AppError):
    """知识点掌握度记录不存在异常 (错误码 40018, HTTP 404)。

    当请求的知识点掌握度记录不存在或无权访问时抛出。
    """

    def __init__(
        self,
        message: str = "掌握度记录不存在",
        details: dict[str, Any] | None = None,
        *,
        error_code: int = 40018,
        status_code: int = 404,
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
    "AttemptItemNotFoundError",
    "AuthenticationError",
    "DiagnosisReportNotFoundError",
    "EmbeddingAuthError",
    "EmbeddingError",
    "EmbeddingTimeoutError",
    "GradingExecutionError",
    "GradingNotAllowedError",
    "IdempotencyConflictError",
    "IdempotencyKeyInvalidError",
    "KnowledgeExtractionRetryExceededError",
    "KnowledgeNotFoundError",
    "KnowledgePointQualityError",
    "LLMAuthError",
    "LLMError",
    "LLMResponseFormatError",
    "LLMTimeoutError",
    "MasteryRecordNotFoundError",
    "MaterialInvalidError",
    "MaterialNotFoundError",
    "MaterialParseError",
    "MissingSourceSnippetError",
    "OCRAuthError",
    "OCRError",
    "OCRReshootExceededError",
    "OCRTimeoutError",
    "PermissionDeniedError",
    "PracticeEmptyQuestionsError",
    "PracticeNotFoundError",
    "PracticeNotGradedError",
    "PracticeSessionNotFoundError",
    "PracticeSessionStatusError",
    "PracticeStatusError",
    "QuestionNotFoundError",
    "QuestionQualityCheckError",
    "QueueError",
    "QueueTimeoutError",
    "ReshootLimitExceededError",
    "SearchError",
    "StorageConnectionError",
    "StorageError",
    "StorageNotFoundError",
]
