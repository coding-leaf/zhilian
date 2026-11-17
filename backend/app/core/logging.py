"""Shared structured and desensitized metric logging helpers."""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.security import generate_user_ref


def build_metric_payload(
    *,
    action: str,
    request_id: str,
    user_id: uuid.UUID,
    target_id: uuid.UUID | str,
    duration_ms: float,
    logger_name: str,
    error_code: int = 0,
    level_name: str | None = None,
    extra: dict[str, Any] | None = None,
    nest_extra: bool = False,
) -> dict[str, Any]:
    """构建符合 8 要素规范的脱敏结构化指标日志载荷。

    绝密脱敏红线：调用方严禁在 extra 中传入题干、选项、标准答案、用户作答原文或密钥。
    """
    resolved_level = level_name or ("INFO" if error_code == 0 else "ERROR")
    payload: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": resolved_level,
        "logger_name": logger_name,
        "request_id": request_id,
        "user_ref": generate_user_ref(user_id),
        "target_id": str(target_id),
        "duration_ms": round(duration_ms, 2),
        "error_code": error_code,
        "action": action,
    }
    if extra:
        if nest_extra:
            payload["details"] = extra
        else:
            payload.update(extra)
    return payload


def log_structured_metric(
    target_logger: logging.Logger,
    *,
    action: str,
    request_id: str,
    user_id: uuid.UUID,
    target_id: uuid.UUID | str,
    duration_ms: float,
    error_code: int = 0,
    level: int | None = None,
    extra: dict[str, Any] | None = None,
    json_mode: bool = False,
    service_label: str = "Service",
) -> None:
    """输出脱敏 8 要素结构化度量日志，统一复用载荷构造与脱敏摘要规则。"""
    if json_mode:
        resolved_level = level if level is not None else logging.INFO
        payload = build_metric_payload(
            action=action,
            request_id=request_id or "-",
            user_id=user_id,
            target_id=target_id,
            duration_ms=duration_ms,
            logger_name=target_logger.name,
            error_code=error_code,
            level_name=logging.getLevelName(resolved_level),
            extra=extra,
            nest_extra=True,
        )
        target_logger.log(resolved_level, "METRIC %s", json.dumps(payload, ensure_ascii=False))
        return

    payload = build_metric_payload(
        action=action,
        request_id=request_id,
        user_id=user_id,
        target_id=target_id,
        duration_ms=duration_ms,
        logger_name=target_logger.name,
        error_code=error_code,
        extra=extra,
        nest_extra=False,
    )
    if error_code == 0:
        target_logger.info("%s execution completed: %s", service_label, payload)
    else:
        target_logger.error("%s execution error: %s", service_label, payload)


__all__ = ["build_metric_payload", "log_structured_metric"]
