"""Unit tests for pure semantic chunking kernel under app.core.algorithms.semantic_chunking."""

import pytest

from app.core.algorithms.material_chunking import Snippet
from app.core.algorithms.semantic_chunking import (
    SEMANTIC_UNIT_MAX_CHARS,
    PageSemanticAnnotation,
    SemanticPageInput,
    aggregate_logical_units,
    build_semantic_snippets,
    normalize_topic_title,
    plan_semantic_batches,
    reindex_snippets,
    resolve_page_effective_text,
)


def test_plan_semantic_batches_respects_page_and_char_budgets() -> None:
    pages = [SemanticPageInput(page_number=i, text="A" * 2500) for i in range(1, 11)]
    batches = plan_semantic_batches(pages, max_pages=8, max_chars=8000)

    # 3 pages = 7500 <= 8000; 4th page would hit 10000 > 8000
    assert [len(b) for b in batches] == [3, 3, 3, 1]

    # Single oversized page (> max_chars) still forms a 1-page batch
    oversized = [
        SemanticPageInput(page_number=1, text="B" * 9000),
        SemanticPageInput(page_number=2, text="C" * 100),
    ]
    batches2 = plan_semantic_batches(oversized, max_pages=8, max_chars=8000)
    assert [len(b) for b in batches2] == [1, 1]

    # 8-page cap when text is short
    short_pages = [SemanticPageInput(page_number=i, text="短文") for i in range(1, 18)]
    batches3 = plan_semantic_batches(short_pages, max_pages=8, max_chars=8000)
    assert [len(b) for b in batches3] == [8, 8, 1]
    assert plan_semantic_batches([]) == []


def test_normalize_topic_title_rejects_formulas_and_non_substantive_names() -> None:
    assert normalize_topic_title("## 支持向量机") == "支持向量机"
    assert normalize_topic_title("ω^T x_i + b", fallback="硬间隔") == "硬间隔"
    assert normalize_topic_title("小结", fallback="核函数") == "核函数"
    long_title = "这是一个超过二十四个字符上限的非常长非常长的章节标题内容测试"
    assert len(normalize_topic_title(long_title)) <= 24


def test_resolve_page_effective_text_enforces_zero_rewrite_for_vlm_and_clean_pages() -> None:
    vlm_page = SemanticPageInput(page_number=1, text="VLM 原文", used_vlm=True)
    vlm_ann = PageSemanticAnnotation(
        page_number=1,
        topic_title="几何间隔",
        needs_formula_repair=True,
        repaired_markdown="不应该覆盖 VLM",
    )
    text_vlm, _ = resolve_page_effective_text(vlm_page, vlm_ann)
    assert text_vlm == "VLM 原文"

    broken_page = SemanticPageInput(page_number=2, text="散架公式\nω^T x_i + b", used_vlm=False)
    repair_ann = PageSemanticAnnotation(
        page_number=2,
        topic_title="几何间隔",
        needs_formula_repair=True,
        repaired_markdown="点到超平面的几何间隔为 $$\\frac{|\\omega^T x_i + b|}{\\|\\omega\\|}$$。",
    )
    text_repaired, _ = resolve_page_effective_text(broken_page, repair_ann)
    assert "$$\\frac{|\\omega^T x_i + b|}{\\|\\omega\\|}$$" in text_repaired


def test_aggregate_logical_units_merges_continuations_and_keeps_all_empty_fallback() -> None:
    pages = [
        SemanticPageInput(page_number=1, text="封面标题"),
        SemanticPageInput(page_number=2, text="第一页推导内容。"),
        SemanticPageInput(page_number=3, text="接续上一页的对偶推导。"),
        SemanticPageInput(page_number=4, text="新的章节主题：核技巧。"),
        SemanticPageInput(page_number=5, text="谢谢！"),
    ]
    anns = [
        PageSemanticAnnotation(page_number=1, topic_title="封面", is_substantive=False),
        PageSemanticAnnotation(page_number=2, topic_title="拉格朗日对偶", merge_with_prev=False),
        PageSemanticAnnotation(page_number=3, topic_title="拉格朗日对偶", merge_with_prev=True),
        PageSemanticAnnotation(page_number=4, topic_title="核技巧", merge_with_prev=False),
        PageSemanticAnnotation(page_number=5, topic_title="致谢", is_substantive=False),
    ]
    units, _ = aggregate_logical_units(pages, anns, doc_type="pdf")
    assert len(units) == 2
    assert units[0].topic_title == "拉格朗日对偶"
    assert units[0].page_number == 2
    assert units[0].page_end == 3
    assert units[0].source_ref == "第 2-3 页"
    assert "接续上一页的对偶推导。" in units[0].content
    assert units[1].topic_title == "核技巧"
    assert units[1].source_ref == "第 4 页"

    # All-empty fallback guard: if every page is marked non-substantive, preserve them
    all_false = [
        PageSemanticAnnotation(page_number=p.page_number, topic_title="", is_substantive=False)
        for p in pages
    ]
    fallback_units, _ = aggregate_logical_units(pages, all_false)
    assert len(fallback_units) == len(pages)


def test_build_semantic_snippets_protects_math_and_tables_at_1400_limit() -> None:
    formula_block = (
        "$$\n\\gamma_i = y_i \\left(\\frac{\\omega^T x_i + b}{\\|\\omega\\|}\\right)\n$$"
    )
    table_block = "| 符号 | 含义 |\n| --- | --- |\n| $\\omega$ | 法向量 |"
    body_a = "线性可分支持向量机通过最大化几何间隔求解最优分类超平面。" * 25
    body_b = "由拉格朗日乘子法与 KKT 对偶互补条件可推导出支持向量特性。" * 25
    text = f"{body_a}\n\n{formula_block}\n\n{table_block}\n\n{body_b}"

    pages = [SemanticPageInput(page_number=6, text=text)]
    anns = [PageSemanticAnnotation(page_number=6, topic_title="硬间隔与几何间隔")]

    result = build_semantic_snippets(pages, anns)
    assert result.max_chars == SEMANTIC_UNIT_MAX_CHARS == 1400
    assert result.total_count >= 2
    assert all(s.char_count <= 1400 for s in result.snippets)
    assert all(s.chapter_title == "硬间隔与几何间隔" for s in result.snippets)
    assert all(s.page_number == 6 for s in result.snippets)
    # Protected blocks must not be split in half
    assert any(formula_block in s.content for s in result.snippets)
    assert any(table_block in s.content for s in result.snippets)


def test_build_semantic_snippets_validation_and_reindex() -> None:
    pages = [SemanticPageInput(page_number=1, text="A" * 200)]
    anns = [PageSemanticAnnotation(page_number=1, topic_title="主题")]

    with pytest.raises(ValueError, match="max_chars"):
        build_semantic_snippets(pages, anns, max_chars=0)
    with pytest.raises(ValueError, match="overlap_chars"):
        build_semantic_snippets(pages, anns, overlap_chars=-1)
    with pytest.raises(ValueError, match="max_snippets"):
        build_semantic_snippets(pages, anns, max_snippets=0)

    degraded = build_semantic_snippets(pages, anns, max_chars=100, overlap_chars=100)
    assert degraded.overlap_chars == 0
    assert degraded.warnings

    raw_snippets = [
        Snippet(
            index=9,
            content="第一块",
            char_count=3,
            start_offset=0,
            end_offset=3,
            chapter_title="章一",
            source_ref="第 1 页",
            doc_type="pdf",
            page_number=1,
        ),
        Snippet(
            index=20,
            content="第二块内容",
            char_count=5,
            start_offset=0,
            end_offset=5,
            chapter_title="章二",
            source_ref="第 2 页",
            doc_type="pdf",
            page_number=2,
        ),
    ]
    reindexed = reindex_snippets(raw_snippets, max_snippets=1)
    assert reindexed.is_truncated is True
    assert len(reindexed.snippets) == 1
    assert reindexed.snippets[0].index == 0
