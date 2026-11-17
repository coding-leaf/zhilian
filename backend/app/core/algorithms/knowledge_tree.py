"""Pure knowledge-tree deduplication, temp-ID normalization, and hierarchy healing algorithms.

Strictly adheres to pure functional kernel constraints (zero ORM/SQLAlchemy/network I/O).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field

from app.core.algorithms.knowledge_quality import ChapterSnippetStat
from app.core.algorithms.search import cosine_similarity


class _HasChapterTitle(Protocol):
    """Minimal snippet duck-type protocol for pure chapter stat computation."""

    @property
    def chapter_title(self) -> str | None: ...


class ExtractedKnowledgeItem(BaseModel):
    """大模型抽取的单个知识点数据传输对象。"""

    temp_id: str = Field(description="临时标识符，用于建立父子层级关系，例如 kp_1")
    parent_temp_id: str | None = Field(
        default=None,
        description="父知识点临时标识符，根节点为 None",
    )
    name: str = Field(description="知识点名称，2~30 字符，严禁数字编号与占位词")
    description: str = Field(default="", description="知识点概念简述与核心考点")
    level: int = Field(default=1, ge=1, le=5, description="知识点层级深度 1~5")
    chapter_title: str = Field(default="", description="归属章节名称")
    source_snippet_indices: list[int] = Field(
        default_factory=list,
        description="来源片段序号列表",
    )


class KnowledgeExtractionOutput(BaseModel):
    """大模型批次知识点抽取输出容器 DTO。"""

    knowledge_points: list[ExtractedKnowledgeItem] = Field(default_factory=list)


@dataclass(frozen=True)
class ResolvedKnowledgeNode:
    """纯函数拓扑自愈后的知识点层级值对象。"""

    id: uuid.UUID
    temp_id: str
    parent_id: uuid.UUID | None
    name: str
    description: str
    level: int


def compute_chapter_stats(snippets: Sequence[_HasChapterTitle]) -> list[ChapterSnippetStat]:
    """统计章节切片分布情况。

    Args:
        snippets: 含 ``chapter_title`` 属性的切片序列。

    Returns:
        list[ChapterSnippetStat]: 各章节统计信息。
    """
    total = len(snippets)
    if total == 0:
        return []
    counts: dict[str, int] = {}
    for s in snippets:
        title = s.chapter_title.strip() if s.chapter_title else "默认章节"
        counts[title] = counts.get(title, 0) + 1
    return [
        ChapterSnippetStat(
            chapter_title=title,
            snippet_count=count,
            snippet_ratio=count / total,
        )
        for title, count in counts.items()
    ]


def _find_merge_targets(
    items: Sequence[ExtractedKnowledgeItem],
    embeddings: Sequence[Sequence[float]],
    similarity_threshold: float,
) -> tuple[dict[int, int], dict[str, str]]:
    """计算语义相似度超过阈值的待合并节点索引与重定向映射。"""
    n = len(items)
    merged_into: dict[int, int] = {}
    redirect_map: dict[str, str] = {}

    for i in range(n):
        if i in merged_into:
            continue
        for j in range(i + 1, n):
            if j in merged_into:
                continue
            if cosine_similarity(embeddings[i], embeddings[j]) > similarity_threshold:
                merged_into[j] = i
                redirect_map[items[j].temp_id] = items[i].temp_id

    return merged_into, redirect_map


def deduplicate_candidate_points(
    items: Sequence[ExtractedKnowledgeItem],
    embeddings: Sequence[Sequence[float]],
    similarity_threshold: float = 0.92,
) -> list[ExtractedKnowledgeItem]:
    """对候选知识点执行基于向量相似度的语义去重并聚合来源切片。"""
    n = len(items)
    if n <= 1:
        return [
            item.model_copy(
                update={"source_snippet_indices": sorted(set(item.source_snippet_indices))}
            )
            for item in items
        ]

    merged_into, redirect_map = _find_merge_targets(items, embeddings, similarity_threshold)
    result: list[ExtractedKnowledgeItem] = []

    for i, item in enumerate(items):
        if i in merged_into:
            continue
        all_indices = set(item.source_snippet_indices)
        for j, target_i in merged_into.items():
            if target_i == i:
                all_indices.update(items[j].source_snippet_indices)

        p_ref = item.parent_temp_id
        if p_ref and p_ref in redirect_map:
            p_ref = redirect_map[p_ref]

        result.append(
            ExtractedKnowledgeItem(
                temp_id=item.temp_id,
                parent_temp_id=p_ref,
                name=item.name,
                description=item.description,
                level=item.level,
                chapter_title=item.chapter_title,
                source_snippet_indices=sorted(all_indices),
            )
        )

    return result


def normalize_extracted_temp_ids(
    items: Sequence[ExtractedKnowledgeItem],
) -> list[ExtractedKnowledgeItem]:
    """消除大模型输出中重复的 temp_id，保证每个待建实体获得独立映射。"""
    reserved_ids = {item.temp_id for item in items}
    seen: set[str] = set()
    normalized: list[ExtractedKnowledgeItem] = []
    for idx, item in enumerate(items):
        temp_id = item.temp_id
        if temp_id in seen:
            candidate = f"{temp_id}__dup_{idx}"
            while candidate in seen or candidate in reserved_ids:
                candidate = f"{candidate}_x"
            normalized.append(item.model_copy(update={"temp_id": candidate}))
            seen.add(candidate)
        else:
            seen.add(temp_id)
            normalized.append(item)
    return normalized


def _has_cycle(
    start_id: str,
    parent_map: dict[str, str | None],
) -> bool:
    """检测从指定节点向上追溯是否存在环。"""
    visited: set[str] = set()
    curr: str | None = start_id
    while curr is not None:
        if curr in visited:
            return True
        visited.add(curr)
        curr = parent_map.get(curr)
    return False


def _calc_node_depth(tid: str, safe_parents: dict[str, str | None]) -> int:
    """沿安全父节点映射计算节点层级深度（钳位至 1~5）。"""
    depth = 1
    curr = safe_parents.get(tid)
    while curr is not None and depth < 5:
        depth += 1
        curr = safe_parents.get(curr)
    return depth


def resolve_knowledge_hierarchy(
    items: Sequence[ExtractedKnowledgeItem],
) -> tuple[list[ResolvedKnowledgeNode], dict[str, uuid.UUID]]:
    """将抽取的扁平节点解析并自愈为纯拓扑值对象列表（不依赖 ORM）。"""
    normalized_items = normalize_extracted_temp_ids(items)
    temp_parents = {it.temp_id: it.parent_temp_id for it in normalized_items}
    temp_to_uuid = {it.temp_id: uuid.uuid4() for it in normalized_items}

    safe_parents: dict[str, str | None] = {}
    for it in normalized_items:
        p_id = it.parent_temp_id
        if p_id is None or p_id not in temp_to_uuid or _has_cycle(it.temp_id, temp_parents):
            safe_parents[it.temp_id] = None
        else:
            safe_parents[it.temp_id] = p_id

    nodes: list[ResolvedKnowledgeNode] = []
    for it in normalized_items:
        p_tid = safe_parents.get(it.temp_id)
        parent_uuid = temp_to_uuid[p_tid] if p_tid else None
        nodes.append(
            ResolvedKnowledgeNode(
                id=temp_to_uuid[it.temp_id],
                temp_id=it.temp_id,
                parent_id=parent_uuid,
                name=it.name,
                description=it.description,
                level=_calc_node_depth(it.temp_id, safe_parents),
            )
        )

    return nodes, temp_to_uuid


__all__ = [
    "ExtractedKnowledgeItem",
    "KnowledgeExtractionOutput",
    "ResolvedKnowledgeNode",
    "_has_cycle",
    "compute_chapter_stats",
    "deduplicate_candidate_points",
    "normalize_extracted_temp_ids",
    "resolve_knowledge_hierarchy",
]
