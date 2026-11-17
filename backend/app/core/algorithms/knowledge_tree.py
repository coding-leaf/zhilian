"""Pure knowledge-tree deduplication, temp-ID normalization, and hierarchy healing algorithms.

Strictly adheres to pure functional kernel constraints (zero ORM/SQLAlchemy/network I/O).
"""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.core.algorithms.knowledge_quality import ChapterSnippetStat
from app.core.algorithms.search import cosine_similarity

_KP_NAME_NORMALIZE_RE: re.Pattern[str] = re.compile(r"[\s\-_（）()【】\[\]：:·.,，、/]+")


def normalize_kp_name(name: str) -> str:
    """将知识点名称规范化为大小写与标点无关的匹配键，用于确定性同名去重合并。"""
    return _KP_NAME_NORMALIZE_RE.sub("", name.strip()).lower()


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
    core_summary: str = Field(
        default="",
        description="严格基于原文提炼的一句话核心摘要（<=60字符），严禁杜撰考频标签",
    )
    key_takeaways: list[str] = Field(
        default_factory=list,
        description="基于资料原文的核心要点短句列表",
    )
    key_formulas: list[str] = Field(
        default_factory=list,
        description="基于资料原文的关键公式或核心符号定义列表",
    )
    boundary_notes: list[str] = Field(
        default_factory=list,
        description="基于资料原文的易错边界与适用条件说明列表",
    )
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
    structured_content: dict[str, Any] | None = None
    sort_order: int = 0


def build_structured_content(item: ExtractedKnowledgeItem) -> dict[str, Any]:
    """将抽取的知识点条目规范化为严格受控的四字段结构化内容字典。"""
    raw_summary = (item.core_summary or item.description or "").strip()
    core_summary = raw_summary[:60]
    return {
        "core_summary": core_summary,
        "key_takeaways": _dedup_clean_strings(item.key_takeaways),
        "key_formulas": _dedup_clean_strings(item.key_formulas),
        "boundary_notes": _dedup_clean_strings(item.boundary_notes),
    }


def _dedup_clean_strings(values: Sequence[str]) -> list[str]:
    """保序去重并清理空白字符串列表。"""
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in values:
        text = raw.strip()
        if text and text not in seen:
            seen.add(text)
            cleaned.append(text)
    return cleaned


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


def _merge_item_cluster(
    primary: ExtractedKnowledgeItem,
    merged_children: Sequence[ExtractedKnowledgeItem],
    parent_redirect: dict[str, str],
) -> ExtractedKnowledgeItem:
    """将同组被合并节点的来源索引及结构化要素聚合到主节点，并重定向父指针。"""
    all_indices = set(primary.source_snippet_indices)
    takeaways = list(primary.key_takeaways)
    formulas = list(primary.key_formulas)
    boundaries = list(primary.boundary_notes)
    best_summary = (primary.core_summary or "").strip()
    best_desc = (primary.description or "").strip()

    for dup in merged_children:
        all_indices.update(dup.source_snippet_indices)
        takeaways.extend(dup.key_takeaways)
        formulas.extend(dup.key_formulas)
        boundaries.extend(dup.boundary_notes)
        dup_summary = (dup.core_summary or "").strip()
        if len(dup_summary) > len(best_summary):
            best_summary = dup_summary
        dup_desc = (dup.description or "").strip()
        if len(dup_desc) > len(best_desc):
            best_desc = dup_desc

    p_ref = primary.parent_temp_id
    visited: set[str] = set()
    while p_ref and p_ref in parent_redirect and p_ref not in visited:
        visited.add(p_ref)
        nxt = parent_redirect[p_ref]
        if nxt == p_ref:
            break
        p_ref = nxt
    if p_ref == primary.temp_id:
        p_ref = None

    effective_summary = (best_summary or best_desc)[:60]
    effective_desc = best_desc or effective_summary

    return ExtractedKnowledgeItem(
        temp_id=primary.temp_id,
        parent_temp_id=p_ref,
        name=primary.name,
        description=effective_desc,
        core_summary=effective_summary,
        key_takeaways=_dedup_clean_strings(takeaways),
        key_formulas=_dedup_clean_strings(formulas),
        boundary_notes=_dedup_clean_strings(boundaries),
        level=primary.level,
        chapter_title=primary.chapter_title,
        source_snippet_indices=sorted(all_indices),
    )


def _merge_by_indices(
    items: Sequence[ExtractedKnowledgeItem],
    embeddings: Sequence[Sequence[float]],
    merged_into: dict[int, int],
    redirect_map: dict[str, str],
) -> tuple[list[ExtractedKnowledgeItem], list[Sequence[float]]]:
    """依据下标合并映射聚合节点列表并同步对齐向量列表。"""
    grouped: dict[int, list[ExtractedKnowledgeItem]] = {}
    for dup_idx, target_idx in merged_into.items():
        grouped.setdefault(target_idx, []).append(items[dup_idx])

    out_items: list[ExtractedKnowledgeItem] = []
    out_embeddings: list[Sequence[float]] = []
    for idx, item in enumerate(items):
        if idx in merged_into:
            continue
        out_items.append(_merge_item_cluster(item, grouped.get(idx, ()), redirect_map))
        if idx < len(embeddings):
            out_embeddings.append(embeddings[idx])
    return out_items, out_embeddings


def _find_name_merge_targets(
    items: Sequence[ExtractedKnowledgeItem],
) -> tuple[dict[int, int], dict[str, str]]:
    """阶段 1：基于规范化名称的确定性同名合并。"""
    first_index_by_norm: dict[str, int] = {}
    merged_into: dict[int, int] = {}
    redirect_map: dict[str, str] = {}

    for idx, item in enumerate(items):
        norm = normalize_kp_name(item.name)
        if not norm:
            continue
        if norm in first_index_by_norm:
            target_idx = first_index_by_norm[norm]
            merged_into[idx] = target_idx
            redirect_map[item.temp_id] = items[target_idx].temp_id
        else:
            first_index_by_norm[norm] = idx

    return merged_into, redirect_map


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
        if i in merged_into or i >= len(embeddings):
            continue
        for j in range(i + 1, n):
            if j in merged_into or j >= len(embeddings):
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
    """对候选知识点依次执行确定性同名合并与向量余弦相似度去重，聚合溯源与结构化字段。"""
    n = len(items)
    if n <= 1:
        return [
            item.model_copy(
                update={"source_snippet_indices": sorted(set(item.source_snippet_indices))}
            )
            for item in items
        ]

    # 阶段 1：先按规范化名称确定性合并，解决分批抽取中同一考点因向量阈值未命中导致的重复
    name_merged_into, name_redirects = _find_name_merge_targets(items)
    stage1_items, stage1_embeddings = _merge_by_indices(
        items, embeddings, name_merged_into, name_redirects
    )
    if len(stage1_items) <= 1:
        return stage1_items

    # 阶段 2：再按向量余弦相似度合并语义近似节点
    vec_merged_into, vec_redirects = _find_merge_targets(
        stage1_items, stage1_embeddings, similarity_threshold
    )
    stage2_items, _ = _merge_by_indices(
        stage1_items, stage1_embeddings, vec_merged_into, vec_redirects
    )
    return stage2_items


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
    for sort_idx, it in enumerate(normalized_items):
        p_tid = safe_parents.get(it.temp_id)
        parent_uuid = temp_to_uuid[p_tid] if p_tid else None
        structured = build_structured_content(it)
        desc = structured["core_summary"] or it.description
        nodes.append(
            ResolvedKnowledgeNode(
                id=temp_to_uuid[it.temp_id],
                temp_id=it.temp_id,
                parent_id=parent_uuid,
                name=it.name,
                description=desc,
                level=_calc_node_depth(it.temp_id, safe_parents),
                structured_content=structured,
                sort_order=sort_idx,
            )
        )

    return nodes, temp_to_uuid


__all__ = [
    "ExtractedKnowledgeItem",
    "KnowledgeExtractionOutput",
    "ResolvedKnowledgeNode",
    "_has_cycle",
    "build_structured_content",
    "compute_chapter_stats",
    "deduplicate_candidate_points",
    "normalize_extracted_temp_ids",
    "normalize_kp_name",
    "resolve_knowledge_hierarchy",
]
