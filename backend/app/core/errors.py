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
