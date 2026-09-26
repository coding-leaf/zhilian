"""Headless CLI 统一错误类型与标准退出码常量。

退出码契约（与 design.md 第 3.2 节一致）：
- 0 成功：命令与断言全部通过；
- 1 运行时错误：未预期异常或命令执行失败；
- 2 断言失败：smoke 某阶段断言不成立；
- 3 配置缺失 / 非真实 Provider：检测到 fake/memory/sqlite 或缺失密钥；
- 4 基础设施不可达：DB/Redis/MinIO 端口或鉴权失败。
"""

from typing import Any

EXIT_OK = 0
"""成功退出码。"""

EXIT_RUNTIME = 1
"""未预期运行时错误退出码。"""

EXIT_ASSERTION = 2
"""断言失败退出码（供 smoke 阶段使用）。"""

EXIT_CONFIG = 3
"""配置缺失或非真实 Provider 退出码。"""

EXIT_INFRA = 4
"""基础设施不可达退出码。"""


class CliError(Exception):
    """CLI 可预期错误，携带退出码与修复指引。

    Args:
        message: 面向使用者的错误描述。
        exit_code: 进程退出码，默认 EXIT_RUNTIME。
        remediation: 修复建议或下一步操作指引。
        details: 结构化附加诊断信息（严禁包含密钥明文）。
    """

    def __init__(
        self,
        message: str,
        *,
        exit_code: int = EXIT_RUNTIME,
        remediation: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.remediation = remediation
        self.details: dict[str, Any] = details or {}


__all__ = [
    "EXIT_ASSERTION",
    "EXIT_CONFIG",
    "EXIT_INFRA",
    "EXIT_OK",
    "EXIT_RUNTIME",
    "CliError",
]
