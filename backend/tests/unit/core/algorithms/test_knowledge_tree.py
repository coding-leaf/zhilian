"""Unit tests for pure knowledge-tree algorithms in app.core.algorithms.knowledge_tree."""

from dataclasses import dataclass

from app.core.algorithms.knowledge_tree import (
    ExtractedKnowledgeItem,
    compute_chapter_stats,
    deduplicate_candidate_points,
    normalize_extracted_temp_ids,
    resolve_knowledge_hierarchy,
)


@dataclass
class _SnippetStub:
    chapter_title: str | None


def test_compute_chapter_stats_empty_and_non_empty() -> None:
    """Verify chapter distribution counts and default title fallback."""
    assert compute_chapter_stats([]) == []
    stats = compute_chapter_stats(
        [_SnippetStub("第一章"), _SnippetStub("第一章"), _SnippetStub(None)]
    )
    assert len(stats) == 2
    assert stats[0].chapter_title == "第一章"
    assert stats[0].snippet_count == 2
    assert stats[1].chapter_title == "默认章节"
    assert stats[1].snippet_count == 1


def test_deduplicate_candidate_points_merges_similar_and_normalizes_single() -> None:
    """Verify semantic merging, parent redirection, and single-item snippet deduplication."""
    single = [
        ExtractedKnowledgeItem(
            temp_id="k1",
            name="单例节点",
            source_snippet_indices=[3, 1, 3],
        )
    ]
    normalized_single = deduplicate_candidate_points(single, [[1.0, 0.0]])
    assert normalized_single[0].source_snippet_indices == [1, 3]

    items = [
        ExtractedKnowledgeItem(
            temp_id="k1",
            name="进程同步",
            source_snippet_indices=[0],
        ),
        ExtractedKnowledgeItem(
            temp_id="k2",
            name="进程同步机制",
            source_snippet_indices=[2],
        ),
        ExtractedKnowledgeItem(
            temp_id="k3",
            parent_temp_id="k2",
            name="信号量 PV",
            source_snippet_indices=[4],
        ),
    ]
    embeddings = [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    merged = deduplicate_candidate_points(items, embeddings, similarity_threshold=0.92)
    assert [item.temp_id for item in merged] == ["k1", "k3"]
    assert merged[0].source_snippet_indices == [0, 2]
    assert merged[1].parent_temp_id == "k1"


def test_normalize_extracted_temp_ids_disambiguates_collisions() -> None:
    """Verify duplicate temp_id disambiguation avoids colliding with reserved IDs."""
    items = [
        ExtractedKnowledgeItem(temp_id="kp_1", name="节点一"),
        ExtractedKnowledgeItem(temp_id="kp_1__dup_1", name="节点占坑"),
        ExtractedKnowledgeItem(temp_id="kp_1", name="节点重复"),
    ]
    normalized = normalize_extracted_temp_ids(items)
    temp_ids = [item.temp_id for item in normalized]
    assert len(temp_ids) == len(set(temp_ids))
    assert temp_ids[0] == "kp_1"
    assert temp_ids[1] == "kp_1__dup_1"
    assert temp_ids[2] == "kp_1__dup_2"


def test_resolve_knowledge_hierarchy_heals_cycles_orphans_and_depth() -> None:
    """Verify cycle breaking, orphan parent healing, and max depth clamping at level 5."""
    items = [
        ExtractedKnowledgeItem(temp_id="c1", parent_temp_id="c2", name="环A"),
        ExtractedKnowledgeItem(temp_id="c2", parent_temp_id="c1", name="环B"),
        ExtractedKnowledgeItem(temp_id="orphan", parent_temp_id="missing", name="孤儿"),
        ExtractedKnowledgeItem(temp_id="r1", parent_temp_id=None, name="根"),
        ExtractedKnowledgeItem(temp_id="r2", parent_temp_id="r1", name="二层"),
        ExtractedKnowledgeItem(temp_id="r3", parent_temp_id="r2", name="三层"),
        ExtractedKnowledgeItem(temp_id="r4", parent_temp_id="r3", name="四层"),
        ExtractedKnowledgeItem(temp_id="r5", parent_temp_id="r4", name="五层"),
        ExtractedKnowledgeItem(temp_id="r6", parent_temp_id="r5", name="六层截断"),
    ]
    nodes, temp_to_uuid = resolve_knowledge_hierarchy(items)
    by_temp = {node.temp_id: node for node in nodes}

    assert by_temp["c1"].parent_id is None
    assert by_temp["c2"].parent_id is None
    assert by_temp["orphan"].parent_id is None
    assert by_temp["r2"].parent_id == temp_to_uuid["r1"]
    assert by_temp["r5"].level == 5
    assert by_temp["r6"].level == 5
