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


def test_review_card_fields_safe_200_trim_and_non_substantive_chapter_skip() -> None:
    """Verify 200-char safe summary trim, optional fields, and non-substantive chapter skip."""
    from app.core.algorithms.knowledge_tree import build_structured_content

    stats = compute_chapter_stats(
        [
            _SnippetStub("第一章 支持向量机"),
            _SnippetStub("第一章 支持向量机"),
            _SnippetStub("小结"),
            _SnippetStub("目录"),
        ]
    )
    assert [s.chapter_title for s in stats] == ["第一章 支持向量机"]
    assert stats[0].snippet_ratio == 1.0

    long_summary = (
        "支持向量机（SVM）旨在寻找最大几何间隔超平面以提升泛化能力。"
        "其核心目标函数为 $\\min_{w,b}\\frac{1}{2}\\|w\\|^2 + C\\sum_{i=1}^n \\xi_i$，"
        "其中法向量 $w$ 决定超平面方向，$C>0$ 控制对误分类松弛变量 $\\xi_i$ 的惩罚权重，"
        "同时通过拉格朗日对偶将问题转化为只依赖样本内积的凸二次规划。"
        "进一步引入核函数即可处理非线性分类边界。"
    )
    item = ExtractedKnowledgeItem(
        temp_id="kp_svm",
        name="软间隔支持向量机",
        core_summary=long_summary,
        key_takeaways=["引入松弛变量允许少量样本落入间隔带内。"],
        key_formulas=["$\\min \\frac{1}{2}\\|w\\|^2 + C\\sum \\xi_i$（$C$ 为惩罚系数）"],
        derivation_steps=["1. 构造拉格朗日函数", "2. 求偏导得对偶问题"],
        common_mistakes=["误区：增大 C 必然提高泛化能力；正解：C 过大易过拟合"],
    )
    sc = build_structured_content(item)
    assert 60 < len(sc["core_summary"]) <= 200
    assert sc["core_summary"].count("$") % 2 == 0
    assert sc["derivation_steps"] == ["1. 构造拉格朗日函数", "2. 求偏导得对偶问题"]
    assert sc["common_mistakes"] == ["误区：增大 C 必然提高泛化能力；正解：C 过大易过拟合"]

    # Deduplication drops bare nouns subsumed by longer takeaway sentences and merges new fields
    dup = ExtractedKnowledgeItem(
        temp_id="kp_svm_dup",
        name="软间隔支持向量机",
        key_takeaways=["松弛变量", "引入松弛变量允许少量样本落入间隔带内。"],
        derivation_steps=["3. KKT 条件判定支持向量"],
        common_mistakes=["误区：松弛变量可为负；正解：必须满足 ξ_i >= 0"],
        source_snippet_indices=[2],
    )
    merged = deduplicate_candidate_points([item, dup], [[1.0, 0.0], [1.0, 0.0]])
    assert len(merged) == 1
    assert merged[0].key_takeaways == ["引入松弛变量允许少量样本落入间隔带内。"]
    assert len(merged[0].derivation_steps) == 3
    assert len(merged[0].common_mistakes) == 2
