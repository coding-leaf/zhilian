"""Unit tests for material chunking algorithm.

Validates compliance with spec.md (TC-CHUNK-01 to TC-CHUNK-19).
"""

import time

import pytest

from app.core.algorithms.material_chunking import (
    ChunkingResult,
    ParagraphInput,
    Snippet,
    split_material_into_snippets,
)


def test_tc_chunk_01_empty_input() -> None:
    """TC-CHUNK-01: Empty input returns empty result."""
    result = split_material_into_snippets([])
    assert isinstance(result, ChunkingResult)
    assert result.total_count == 0
    assert result.snippets == ()
    assert not result.is_truncated
    assert result.cleaned_chars_count == 0


def test_tc_chunk_02_whitespace_only_paragraphs() -> None:
    """TC-CHUNK-02: Paragraphs with only whitespace characters."""
    paragraphs = ["   ", "\n\t", "  \n  ", "\r\n"]
    result = split_material_into_snippets(paragraphs)
    assert result.total_count == 0
    assert result.snippets == ()
    assert not result.is_truncated


def test_tc_chunk_03_single_char_boundary() -> None:
    """TC-CHUNK-03: Single character minimum boundary."""
    result = split_material_into_snippets(["A"])
    assert result.total_count == 1
    assert len(result.snippets) == 1
    snippet = result.snippets[0]
    assert isinstance(snippet, Snippet)
    assert snippet.index == 0
    assert snippet.content == "A"
    assert snippet.char_count == 1
    assert snippet.start_offset == 0
    assert snippet.end_offset == 1


def test_tc_chunk_04_exact_max_chars_limit() -> None:
    """TC-CHUNK-04: Single paragraph exactly equals max_chars."""
    content = "中" * 800
    result = split_material_into_snippets([content], max_chars=800, overlap_chars=120)
    assert result.total_count == 1
    assert len(result.snippets) == 1
    assert result.snippets[0].char_count == 800
    assert result.snippets[0].start_offset == 0
    assert result.snippets[0].end_offset == 800


def test_tc_chunk_05_max_chars_plus_one() -> None:
    """TC-CHUNK-05: Single paragraph max_chars + 1 triggers splitting."""
    sentence1 = "甲" * 400 + "。"
    sentence2 = "乙" * 400
    content = sentence1 + sentence2  # 801 chars
    result = split_material_into_snippets([content], max_chars=800, overlap_chars=0)
    assert result.total_count == 2
    assert len(result.snippets) == 2
    assert result.snippets[0].content == sentence1
    assert result.snippets[1].content == sentence2


def test_tc_chunk_06_overlap_chars_zero() -> None:
    """TC-CHUNK-06: Zero overlap lower boundary."""
    sentence1 = "第一段文本详细介绍。" * 30  # 300 chars
    sentence2 = "第二段文本深入探讨。" * 30  # 300 chars
    sentence3 = "第三段文本补充总结。" * 30  # 300 chars
    full_text = sentence1 + sentence2 + sentence3  # 900 chars
    result = split_material_into_snippets([full_text], max_chars=500, overlap_chars=0)
    assert result.overlap_chars == 0
    assert len(result.snippets) == 2
    # Ensure contiguous division without overlap
    assert result.snippets[0].end_offset == result.snippets[1].start_offset
    assert result.snippets[0].content + result.snippets[1].content == full_text


def test_tc_chunk_07_overlap_equals_max_chars() -> None:
    """TC-CHUNK-07: overlap_chars equals max_chars degrades to 0 overlap."""
    content = "段落内容测试。" * 50
    result = split_material_into_snippets([content], max_chars=100, overlap_chars=100)
    assert result.overlap_chars == 0
    assert any("degraded to 0 overlap" in warning for warning in result.warnings)


def test_tc_chunk_08_overlap_exceeds_max_chars() -> None:
    """TC-CHUNK-08: overlap_chars exceeds max_chars degrades to 0 overlap."""
    content = "段落内容测试。" * 50
    result = split_material_into_snippets([content], max_chars=100, overlap_chars=150)
    assert result.overlap_chars == 0
    assert any("degraded to 0 overlap" in warning for warning in result.warnings)


def test_tc_chunk_09_fatal_parameter_validation() -> None:
    """TC-CHUNK-09: Fatal parameter validation raises ValueError."""
    with pytest.raises(ValueError, match="max_chars"):
        split_material_into_snippets(["测试"], max_chars=0)

    with pytest.raises(ValueError, match="max_chars"):
        split_material_into_snippets(["测试"], max_chars=-10)

    with pytest.raises(ValueError, match="overlap_chars"):
        split_material_into_snippets(["测试"], max_chars=500, overlap_chars=-1)

    with pytest.raises(ValueError, match="min_chars"):
        split_material_into_snippets(["测试"], min_chars=-1)

    with pytest.raises(ValueError, match="max_snippets"):
        split_material_into_snippets(["测试"], max_snippets=0)


def test_tc_chunk_10_primary_punctuation_split() -> None:
    """TC-CHUNK-10: Primary punctuation (sentence-ending) splitting."""
    sentence1 = "机器学习是人工智能的重要分支。" * 20  # 320 chars
    sentence2 = "深度学习在计算机视觉领域取得重大突破！" * 15  # 300 chars
    sentence3 = "强化学习如何改变决策系统？" * 10  # 140 chars
    sentence4 = "大语言模型引领新一轮技术革命。\n" * 15  # 240 chars
    content = sentence1 + sentence2 + sentence3 + sentence4  # 1000 chars

    result = split_material_into_snippets([content], max_chars=500, overlap_chars=50)
    for snippet in result.snippets:
        assert snippet.char_count <= 500
        # Should cut along primary punctuation marks
        last_char = snippet.content.rstrip()[-1]
        assert last_char in "。！？!\n?" or snippet == result.snippets[-1]


def test_tc_chunk_11_secondary_punctuation_split() -> None:
    """TC-CHUNK-11: Secondary punctuation degradation when no primary punctuation."""
    # 1000 chars without primary punctuation, but with comma and semicolon
    clause1 = "第一部分详细展开探讨" * 25 + "，"  # 251 chars
    clause2 = "第二部分深入理论证明" * 25 + "；"  # 251 chars
    clause3 = "第三部分进行实验比对" * 25 + "、"  # 251 chars
    clause4 = "第四部分归纳未来展望" * 25  # 250 chars
    content = clause1 + clause2 + clause3 + clause4

    result = split_material_into_snippets([content], max_chars=400, overlap_chars=0)
    assert len(result.snippets) >= 3
    for snippet in result.snippets[:-1]:
        assert snippet.char_count <= 400
        last_char = snippet.content[-1]
        assert last_char in "，；、,;"


def test_tc_chunk_12_hard_cut_fallback() -> None:
    """TC-CHUNK-12: Hard cut fallback when no punctuation exists."""
    content = "无标点连续字符串" * 150  # 1200 chars
    result = split_material_into_snippets([content], max_chars=500, overlap_chars=0)
    assert len(result.snippets) == 3
    assert result.snippets[0].char_count == 500
    assert result.snippets[1].char_count == 500
    assert result.snippets[2].char_count == 200


def test_tc_chunk_13_ten_times_oversized_paragraph() -> None:
    """TC-CHUNK-13: Single paragraph > 8000 characters."""
    unit = "自然语言处理系统在理解长文本时需要合理切分。"  # 22 chars
    content = unit * 400  # 8800 chars
    result = split_material_into_snippets([content], max_chars=800, overlap_chars=120)
    assert result.total_count >= 11
    for snippet in result.snippets:
        assert snippet.char_count <= 800


def test_tc_chunk_14_merge_isolated_short_snippet_forward() -> None:
    """TC-CHUNK-14: Isolated short paragraph (< 80 chars) merges backward to next."""
    para_a = "这是第一篇较为详细的系统设计文档描述。" * 20  # 400 chars
    para_b = "这是简短补充说明。"  # 9 chars (< 80)
    para_c = "这是第三篇关于核心技术架构的具体设计与说明。" * 20  # 440 chars

    result = split_material_into_snippets([para_a, para_b, para_c], max_chars=800, min_chars=80)
    # para_b should be merged forward into snippet containing para_c
    contents = [s.content for s in result.snippets]
    assert not any(s.content == para_b for s in result.snippets)
    assert any(para_b in c and (para_c in c or para_c[:50] in c) for c in contents)


def test_tc_chunk_15_merge_isolated_short_snippet_backward_at_tail() -> None:
    """TC-CHUNK-15: Isolated short paragraph (< 80 chars) at end merges forward to prev."""
    para_a = "这是第一篇较为详细的系统设计文档描述。" * 20  # 400 chars
    para_b = "尾部简短备忘录。"  # 8 chars (< 80)

    result = split_material_into_snippets([para_a, para_b], max_chars=800, min_chars=80)
    assert len(result.snippets) == 1
    assert para_b in result.snippets[0].content


def test_tc_chunk_16_chapter_title_handling() -> None:
    """TC-CHUNK-16: Paragraph with is_title=True establishes chapter_title."""
    paragraphs = [
        ParagraphInput(
            text="第一章 绪论与背景",
            source_ref="第 1 页",
            doc_type="pdf",
            is_title=True,
            title_level=1,
        ),
        ParagraphInput(
            text="本章主要讨论分布式系统基础架构设计原理与实践路径。" * 10,
            source_ref="第 1 页",
            doc_type="pdf",
            is_title=False,
        ),
        ParagraphInput(
            text="第二章 数据一致性模型",
            source_ref="第 5 页",
            doc_type="pdf",
            is_title=True,
            title_level=1,
        ),
        ParagraphInput(
            text="本章探讨强一致性与最终一致性在实际存储中的取舍方案。" * 10,
            source_ref="第 5 页",
            doc_type="pdf",
            is_title=False,
        ),
    ]

    result = split_material_into_snippets(paragraphs, max_chars=800)
    assert len(result.snippets) == 2
    assert result.snippets[0].chapter_title == "第一章 绪论与背景"
    assert "绪论与背景" not in result.snippets[0].content
    assert result.snippets[0].source_ref == "第 1 页"
    assert result.snippets[0].doc_type == "pdf"

    assert result.snippets[1].chapter_title == "第二章 数据一致性模型"
    assert result.snippets[1].source_ref == "第 5 页"


def test_tc_chunk_17_max_snippets_safety_truncation() -> None:
    """TC-CHUNK-17: Truncates when total snippets exceed max_snippets limit."""
    # Generate 120 paragraphs, each 100 chars, with max_snippets=50 and max_chars=100
    paragraphs = [f"第{i:03d}段落核心业务数据独立描述内容。\n" * 5 for i in range(120)]
    result = split_material_into_snippets(
        paragraphs,
        max_chars=100,
        overlap_chars=0,
        max_snippets=50,
    )
    assert result.is_truncated
    assert result.total_count == 120
    assert len(result.snippets) == 50
    assert any("truncated to 50" in w for w in result.warnings)


def test_tc_chunk_18_illegal_unicode_cleaning() -> None:
    """TC-CHUNK-18: Strips control chars and zero-width spaces."""
    dirty_text = "正常文本\x00包含\u200b零宽字符\ufeff与退格\x08符号。"
    result = split_material_into_snippets([dirty_text])
    assert result.cleaned_chars_count == 4
    assert len(result.snippets) == 1
    assert result.snippets[0].content == "正常文本包含零宽字符与退格符号。"
    assert result.snippets[0].char_count == len("正常文本包含零宽字符与退格符号。")
    assert result.snippets[0].end_offset == len("正常文本包含零宽字符与退格符号。")


def test_tc_chunk_19_throughput_performance_benchmark() -> None:
    """TC-CHUNK-19: Performance benchmark: 200,000 Chinese characters <= 2.0s."""
    # 36 chars sample sentence
    sample_sentence = "在智能学习系统中，知识点与题目切分算法需要具备高度的稳定性与准确率。"
    paragraphs = [sample_sentence * 25 for _ in range(225)]  # ~202,500 chars

    start_time = time.perf_counter()
    result = split_material_into_snippets(paragraphs, max_chars=800, overlap_chars=120)
    elapsed_time = time.perf_counter() - start_time

    assert elapsed_time <= 2.0, f"Chunking took {elapsed_time:.3f}s, exceeding 2.0s threshold"
    assert result.total_count > 200


def test_align_overlap_sentence_boundary_branches() -> None:
    """Direct branch coverage for align_overlap_sentence_boundary."""
    from app.core.algorithms.material_chunking import (
        align_overlap_sentence_boundary,
        split_paragraph_into_ranges,
    )

    assert align_overlap_sentence_boundary("", 10) == ""
    assert align_overlap_sentence_boundary("文本", 0) == ""
    assert align_overlap_sentence_boundary("纯无标点文本测试", 4) == "文本测试"
    assert align_overlap_sentence_boundary("末尾句号标点测试。", 4) == "点测试。"

    # Branch when aligned_overlap covers entire slice length
    ranges = split_paragraph_into_ranges("a" * 100, max_chars=20, overlap_chars=20)
    assert len(ranges) == 5


def test_merge_isolated_short_snippets_branches() -> None:
    """Branch coverage for isolated short snippet merging limits."""
    # min_chars <= 0 directly returns snippets without merging
    result_no_merge = split_material_into_snippets(["段落一", "短段"], min_chars=0)
    assert len(result_no_merge.snippets) == 2

    # Forward merge blocked by max_chars limit
    short_first = "简短"
    long_second = "中" * 100
    res1 = split_material_into_snippets([short_first, long_second], max_chars=100, min_chars=20)
    assert len(res1.snippets) == 2

    # Backward merge blocked by max_chars limit
    long_first = "中" * 100
    short_second = "简短"
    res2 = split_material_into_snippets([long_first, short_second], max_chars=100, min_chars=20)
    assert len(res2.snippets) == 2


def test_split_paragraph_overlap_no_punctuation() -> None:
    """Coverage for overlap handling in text without punctuation."""
    pure_text = "abcdefghijklmnopqrstuvwxyz" * 10  # 260 chars
    result = split_material_into_snippets([pure_text], max_chars=100, overlap_chars=20)
    assert len(result.snippets) >= 3
    for s in result.snippets:
        assert s.char_count <= 100
