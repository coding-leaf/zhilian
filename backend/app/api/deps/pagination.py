"""Shared FastAPI pagination normalization dependency."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Query


@dataclass(frozen=True)
class PaginationParams:
    """归一化后的分页查询参数，同时支持 page/page_size 与 limit/offset。"""

    page: int
    page_size: int
    limit: int
    offset: int
    raw_page: int


def get_pagination_params(
    page: Annotated[int, Query(ge=1, description="当前页码，从 1 开始")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页记录数")] = 20,
    limit: Annotated[int | None, Query(ge=1, le=100, description="单页容量限制 (兼容)")] = None,
    offset: Annotated[int | None, Query(ge=0, description="分页游标偏移量 (兼容)")] = None,
) -> PaginationParams:
    """将 page/page_size 与 limit/offset 两种分页协议参数归一化。"""
    effective_limit = limit if limit is not None else page_size
    effective_offset = offset if offset is not None else (max(page - 1, 0) * effective_limit)
    effective_page = (effective_offset // effective_limit) + 1 if limit is not None else page
    return PaginationParams(
        page=effective_page,
        page_size=page_size,
        limit=effective_limit,
        offset=effective_offset,
        raw_page=page,
    )


__all__ = ["PaginationParams", "get_pagination_params"]
