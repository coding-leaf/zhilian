"""Headless CLI 结构化输出与密钥脱敏工具。

- `Reporter` 同时支持 `--json` 结构化输出与人类可读打印；
- `redact_url` 将连接串中的密码脱敏为 `***`；
- `sanitize` 递归脱敏 `SecretStr`，杜绝任何密钥明文落入输出。

安全红线：本模块绝不调用 `SecretStr.get_secret_value()`。
"""

import json
import time
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import SecretStr

REDACTED = "***"
"""统一脱敏占位符。"""

STAGE_OK = "ok"
"""阶段执行成功状态。"""

STAGE_FAILED = "failed"
"""阶段执行失败状态。"""

STAGE_SKIPPED = "skipped"
"""阶段跳过状态。"""


@dataclass
class StageRecord:
    """单阶段执行记录（供 `smoke` 全链路编排逐阶段断言与归因）。

    Attributes:
        name: 阶段名称。
        status: 阶段状态（ok / failed / skipped）。
        elapsed_ms: 阶段耗时（毫秒）。
        ids: 阶段产出的关键实体 ID 映射（值均为字符串，严禁含密钥）。
        error: 失败时的原始错误字符串。
        details: 结构化附加信息（脱敏后输出）。
    """

    name: str
    status: str = STAGE_OK
    elapsed_ms: int = 0
    ids: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典。"""
        data: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "elapsed_ms": self.elapsed_ms,
        }
        if self.ids:
            data["ids"] = dict(self.ids)
        if self.error:
            data["error"] = self.error
        if self.details:
            data["details"] = dict(self.details)
        return data


class StageRecorder:
    """`Reporter.stage()` 返回的阶段上下文管理器。

    进入时开始计时，退出时写入耗时；若阶段内抛出异常则记录失败状态与原始错误，
    并且**不吞异常**（返回 False，交由调用方统一归因）。
    """

    def __init__(self, record: StageRecord) -> None:
        """绑定待记录的阶段实体。

        Args:
            record: 已登记到 reporter 的阶段记录对象。
        """
        self.record = record
        self.ids = record.ids
        self.details = record.details
        self._start = 0.0

    def __enter__(self) -> "StageRecorder":
        """开始计时并返回自身以暴露 `ids` / `details`。"""
        self._start = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        """结束计时；异常时标记失败并记录原始错误。

        Returns:
             Literal[False]: 恒为 False，绝不抑制异常。
        """
        self.record.elapsed_ms = int((time.perf_counter() - self._start) * 1000)
        if exc is not None:
            self.record.status = STAGE_FAILED
            self.record.error = str(exc)
        return False


def redact_url(url: str) -> str:
    """将 URL/连接串中的密码部分脱敏为 `***`。

    Args:
        url: 原始连接串。

    Returns:
        str: 密码被替换为 `***` 的连接串；无密码或无法解析时原样返回。
    """
    try:
        parts = urlsplit(url)
        password = parts.password
        port = parts.port
    except ValueError:
        return url

    if not password:
        return url

    host = parts.hostname or ""
    if port is not None:
        host = f"{host}:{port}"
    username = parts.username or ""
    netloc = f"{username}:{REDACTED}@{host}" if username else f"{REDACTED}@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def sanitize(value: Any) -> Any:
    """递归脱敏任意结构中的 `SecretStr` 字段。

    Args:
        value: 任意待输出对象。

    Returns:
        Any: 脱敏后的等价结构。
    """
    if isinstance(value, SecretStr):
        return REDACTED
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    return value


@dataclass
class Reporter:
    """CLI 输出器：`--json` 模式输出结构化 JSON，否则输出人类可读文本。

    Attributes:
        json_mode: 是否启用结构化 JSON 输出。
        stages: 已记录的阶段执行轨迹（供 `smoke` 汇总输出）。
    """

    json_mode: bool = False
    stages: list[StageRecord] = field(default_factory=list, init=False)

    def stage(self, name: str) -> StageRecorder:
        """登记并返回一个阶段上下文管理器（用于全链路逐阶段断言）。

        Args:
            name: 阶段名称。

        Returns:
            StageRecorder: 已登记阶段记录的上下文管理器。
        """
        record = StageRecord(name=name)
        self.stages.append(record)
        return StageRecorder(record)

    def stage_payloads(self) -> list[dict[str, Any]]:
        """返回全部阶段记录的可序列化列表。"""
        return [record.to_dict() for record in self.stages]

    def emit(self, data: dict[str, Any]) -> None:
        """输出结构化结果字典（自动脱敏）。

        Args:
            data: 待输出结果字典。
        """
        payload = sanitize(data)
        if self.json_mode:
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            self._print_mapping(payload, 0)

    def info(self, message: str) -> None:
        """打印人类可读提示（`--json` 模式下静默，保持 JSON 纯净）。

        Args:
            message: 提示文案。
        """
        if not self.json_mode:
            print(message)

    def _print_mapping(self, data: dict[str, Any], indent: int) -> None:
        prefix = "  " * indent
        for key, value in data.items():
            if isinstance(value, dict):
                print(f"{prefix}{key}:")
                self._print_mapping(value, indent + 1)
            elif isinstance(value, list):
                print(f"{prefix}{key}:")
                self._print_sequence(value, indent + 1)
            else:
                print(f"{prefix}{key}: {value}")

    def _print_sequence(self, items: list[Any], indent: int) -> None:
        prefix = "  " * indent
        for item in items:
            if isinstance(item, dict):
                print(f"{prefix}-")
                self._print_mapping(item, indent + 1)
            else:
                print(f"{prefix}- {item}")


__all__ = [
    "REDACTED",
    "STAGE_FAILED",
    "STAGE_OK",
    "STAGE_SKIPPED",
    "Reporter",
    "StageRecord",
    "StageRecorder",
    "redact_url",
    "sanitize",
]
