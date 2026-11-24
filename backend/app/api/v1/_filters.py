"""API v1 通用查询参数解析辅助模块。

集中处理课程文件夹过滤参数 (`folder_id` / `__none__` / `unclassified`)，
消除跨路由重复解析与校验语义漂移。
"""

import uuid

from fastapi import status

from app.core.errors import MaterialInvalidError

UNCLASSIFIED_FOLDER_SENTINEL = "__none__"


def parse_folder_filter(
    folder_id: str | None,
    *,
    unclassified: bool = False,
    invalid_status_code: int = status.HTTP_422_UNPROCESSABLE_CONTENT,
) -> tuple[uuid.UUID | None, bool]:
    """解析课程过滤查询参数为 ``(folder_uuid, is_unclassified)`` 二元组。

    规则：
    - ``folder_id`` 为空或空白串时，沿用 ``unclassified`` 标志；
    - ``folder_id == "__none__"`` 时，返回 ``(None, True)``；
    - 合法 UUID 字符串时，返回 ``(uuid.UUID(val), False)``；
    - 非法 UUID 格式抛出 ``MaterialInvalidError``（默认 HTTP 422）。

    Args:
        folder_id: 原始课程过滤查询参数。
        unclassified: 向后兼容的「仅未分类」布尔查询参数。
        invalid_status_code: 参数格式非法时的 HTTP 状态码，默认 422。

    Returns:
        tuple[uuid.UUID | None, bool]: ``(课程主键或 None, 是否仅未分类)``。

    Raises:
        MaterialInvalidError: ``folder_id`` 既非 ``__none__`` 也非合法 UUID。
    """
    if folder_id is None:
        return None, bool(unclassified)

    trimmed = folder_id.strip()
    if not trimmed:
        return None, bool(unclassified)
    if trimmed == UNCLASSIFIED_FOLDER_SENTINEL:
        return None, True

    try:
        return uuid.UUID(trimmed), False
    except ValueError as exc:
        raise MaterialInvalidError(
            "课程过滤参数格式非法",
            details={"folder_id": trimmed},
            status_code=invalid_status_code,
        ) from exc


__all__ = ["UNCLASSIFIED_FOLDER_SENTINEL", "parse_folder_filter"]
