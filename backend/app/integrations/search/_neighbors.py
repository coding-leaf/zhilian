"""邻接切片扩展的纯函数辅助（Fake 与 Pgvector 适配器共享，无 I/O）。"""

import dataclasses
import uuid
from collections.abc import Sequence
from typing import Any

from app.integrations.search.protocol import SearchSnippetCandidate

PAGE_NUMBER_KEY = "page_number"


def page_of(source_info: dict[str, Any] | None) -> int | None:
    """读取 source_info 中的页码；缺失或非整数时返回 None。"""
    if not source_info:
        return None
    value = source_info.get(PAGE_NUMBER_KEY)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def pages_compatible(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    """双方页码均已知时必须相等；任一方未知则视为兼容。"""
    left_page = page_of(left)
    right_page = page_of(right)
    if left_page is None or right_page is None:
        return True
    return left_page == right_page


def neighbor_targets(
    candidates: Sequence[SearchSnippetCandidate],
    window: int,
) -> dict[tuple[uuid.UUID, int], list[SearchSnippetCandidate]]:
    """计算待取邻居的 (version_id, snippet_index) 目标及其相邻来源候选。

    已在输入中的 (version_id, snippet_index) / snippet_id 不会成为目标。
    """
    if window <= 0:
        return {}
    present_keys = {
        (c.version_id, c.snippet_index) for c in candidates if c.snippet_index is not None
    }
    targets: dict[tuple[uuid.UUID, int], list[SearchSnippetCandidate]] = {}
    for cand in candidates:
        if cand.snippet_index is None:
            continue  # 无序号则无法定位邻居
        for delta in range(1, window + 1):
            for index in (cand.snippet_index - delta, cand.snippet_index + delta):
                if index < 0:
                    continue
                key = (cand.version_id, index)
                if key in present_keys:
                    continue
                targets.setdefault(key, []).append(cand)
    return targets


def as_neighbor(candidate: SearchSnippetCandidate) -> SearchSnippetCandidate:
    """将切片标准化为邻居候选：分数与名次清零。"""
    return dataclasses.replace(
        candidate,
        vector_score=0.0,
        bm25_score=0.0,
        final_score=0.0,
        vector_rank=None,
        bm25_rank=None,
    )


def select_neighbors(
    targets: dict[tuple[uuid.UUID, int], list[SearchSnippetCandidate]],
    pool: Sequence[SearchSnippetCandidate],
    existing_ids: set[uuid.UUID],
) -> list[SearchSnippetCandidate]:
    """从 pool 中按目标与页码兼容性筛选邻居，去重并按 (version_id, snippet_index) 排序。"""
    chosen: dict[uuid.UUID, SearchSnippetCandidate] = {}
    for item in pool:
        if item.snippet_id in existing_ids or item.snippet_index is None:
            continue
        sources = targets.get((item.version_id, item.snippet_index))
        if not sources:
            continue
        if not any(pages_compatible(src.source_info, item.source_info) for src in sources):
            continue
        chosen.setdefault(item.snippet_id, as_neighbor(item))
    return sorted(
        chosen.values(),
        key=lambda c: (str(c.version_id), c.snippet_index if c.snippet_index is not None else -1),
    )
