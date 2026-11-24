"""Unit tests for formula/table-safe chunking, decimal-safe sentence splits and merging."""

import pytest

from app.core.algorithms.material_chunking import (
    PRIMARY_PUNCTUATION_CHARS,
    ParagraphInput,
    Snippet,
    align_overlap_sentence_boundary,
    enclosing_span,
    find_best_split_point,
    find_protected_spans,
    is_sentence_boundary,
    merge_isolated_short_snippets,
    split_material_into_snippets,
    split_paragraph_into_ranges,
)


def _snip(
    content: str,
    *,
    page: int | None = 1,
    chapter: str = "",
    start: int = 0,
    source_ref: str = "p",
) -> Snippet:
    return Snippet(
        index=0,
        content=content,
        char_count=len(content),
        start_offset=start,
        end_offset=start + len(content),
        chapter_title=chapter,
        source_ref=source_ref,
        doc_type="pdf",
        page_number=page,
    )


def _chain(*specs: tuple[str, int | None, str]) -> list[Snippet]:
    """按顺序生成偏移连续的片段。"""
    result: list[Snippet] = []
    offset = 0
    for content, page, chapter in specs:
        result.append(_snip(content, page=page, chapter=chapter, start=offset))
        offset += len(content)
    return result


class TestSentenceBoundary:
    def test_period_in_primary_chars(self) -> None:
        assert "." in PRIMARY_PUNCTUATION_CHARS

    @pytest.mark.parametrize(
        ("text", "idx", "expected"),
        [
            ("pi is 3.14 ok", 6, False),  # 小数
            ("version v1.2.3 now", 8, False),  # 版本号
            ("version v1.2.3 now", 10, False),
            ("e.g. this", 1, False),  # 缩写内部
            ("e.g. this", 3, False),  # 缩写末尾
            ("i.e. that", 3, False),
            ("See Fig. 3 here", 7, False),
            ("A done. Next", 6, True),
            ("In 2020. Next", 7, True),  # 数字后接空格的真句号
            ("end.", 3, True),
            ("a...b", 1, False),  # 省略号
            ("file.txt", 4, False),
            ("结束了.然后", 3, True),  # 句号后接汉字
            ("。", 0, True),
            ("a\nb", 1, True),
            ("a,b", 1, False),
        ],
    )
    def test_is_sentence_boundary(self, text: str, idx: int, expected: bool) -> None:
        assert is_sentence_boundary(text, idx) is expected

    def test_split_prefers_real_sentence_end_over_decimal(self) -> None:
        text = "结果为3.14159是圆周率" + "的近似值，" * 10 + "结束了. 下一句话" + "字" * 30
        end = text.index("结束了.") + len("结束了.")
        pos = find_best_split_point(text, 0, end + 3)
        assert pos == end

    def test_split_does_not_cut_decimal(self) -> None:
        text = "a" * 10 + "3.14" + "b" * 10
        pos = find_best_split_point(text, 0, 12)  # 窗口末尾落在 3.1 之间
        assert pos == 12  # 无合法标点 -> 硬切，而不是在小数点后切


class TestProtectedSpans:
    def test_inline_and_display_math(self) -> None:
        text = "前 $a+b$ 中 $$x^2$$ 后"
        spans = find_protected_spans(text)
        assert [text[s:e] for s, e in spans] == ["$a+b$", "$$x^2$$"]

    def test_currency_is_not_math(self) -> None:
        assert find_protected_spans("价格 $5 and then $ 10 元") == []

    def test_markdown_table_block(self) -> None:
        text = "说明\n| a | b |\n|---|---|\n| 1 | 2 |\n结尾"
        spans = find_protected_spans(text)
        assert len(spans) == 1
        start, end = spans[0]
        assert text[start:end] == "| a | b |\n|---|---|\n| 1 | 2 |"

    def test_flags_can_disable_kinds(self) -> None:
        text = "$a$\n| x |"
        assert find_protected_spans(text, math=False) == [(4, 9)]
        assert find_protected_spans(text, tables=False) == [(0, 3)]
        assert find_protected_spans("") == []

    def test_overlapping_spans_are_merged(self) -> None:
        text = "| $a | b$ |\n| c | d |"
        spans = find_protected_spans(text)
        assert len(spans) == 1

    def test_enclosing_span_is_strict(self) -> None:
        spans = [(5, 10), (20, 30)]
        assert enclosing_span(spans, 5) is None
        assert enclosing_span(spans, 6) == (5, 10)
        assert enclosing_span(spans, 10) is None
        assert enclosing_span(spans, 3) is None
        assert enclosing_span([], 3) is None


class TestFormulaSafeSplitting:
    def test_formula_straddling_limit_moves_to_next_chunk(self) -> None:
        intro = "已知量满足如下关系，请看下面的推导。"
        formula = "$$\\sum_{i=1}^{k}\\sigma_i^2=\\frac{1}{n}\\sum_{j}x_j$$"
        text = intro + formula + "因此结论成立。" + "后续说明内容" * 20
        limit = len(intro) + len(formula) // 2
        pos = find_best_split_point(text, 0, limit)
        assert pos == len(intro)  # 回退到句末（公式起点之前）
        assert enclosing_span(find_protected_spans(text), pos) is None

    def test_inline_formula_never_cut(self) -> None:
        text = "设" + "文" * 20 + "$\\alpha+\\beta+\\gamma$" + "文" * 40
        start = text.index("$")
        for target in range(start + 1, start + len("$\\alpha+\\beta+\\gamma$")):
            pos = find_best_split_point(text, 0, target)
            assert not (start < pos < start + len("$\\alpha+\\beta+\\gamma$"))

    def test_all_split_ranges_keep_math_intact(self) -> None:
        formula = "$x_{i}^{2}+y_{i}^{2}$"
        text = ("这是一个带有行内公式" + formula + "的句子。") * 60
        ranges = split_paragraph_into_ranges(text, 100, 30)
        assert len(ranges) > 3
        for start, end in ranges:
            piece = text[start:end]
            assert piece.count("$") % 2 == 0
            assert len(piece) <= 100

    def test_oversize_display_block_splits_at_line_boundaries(self) -> None:
        lines = [f"a_{i} + b_{i} = c_{i} \\\\" for i in range(60)]
        block = "$$\n" + "\n".join(lines) + "\n$$"
        assert len(block) > 300
        ranges = split_paragraph_into_ranges(block, 200, 0)
        assert len(ranges) >= 2
        for start, end in ranges[:-1]:
            assert block[end - 1] == "\n"  # 行边界
            assert end - start <= 200
        assert ranges[-1][1] == len(block)

    def test_oversize_block_without_newline_hard_cuts_within_limit(self) -> None:
        block = "$" + "x" * 500 + "$"
        ranges = split_paragraph_into_ranges(block, 200, 0)
        assert all(end - start <= 200 for start, end in ranges)
        assert ranges[0] == (0, 200)

    def test_table_never_cut_mid_row(self) -> None:
        rows = [f"| 项目{i} | 数值 {i}.5 | 备注。说明 |" for i in range(40)]
        text = "表格如下：\n" + "\n".join(rows) + "\n以上。"
        ranges = split_paragraph_into_ranges(text, 220, 0)
        assert len(ranges) >= 2
        for start, end in ranges:
            piece = text[start:end]
            assert end - start <= 220
            for line in piece.splitlines():
                if line.startswith("|"):
                    assert line.endswith("|"), line

    def test_small_table_kept_whole_in_next_chunk(self) -> None:
        table = "\n".join(["| a | b |", "|---|---|", "| 1 | 2 |"])
        text = "前文" * 60 + "。\n" + table + "\n" + "后文" * 10
        limit = text.index(table) + 15
        pos = find_best_split_point(text, 0, limit)
        assert pos <= text.index(table)

    def test_split_material_blocks_stay_whole_end_to_end(self) -> None:
        formula = "$$\\int_0^1 f(x)\\,dx = F(1)-F(0)$$"
        para = (
            ("这一段说明牛顿莱布尼茨公式的意义，请注意。" * 8)
            + formula
            + ("随后给出若干例子。" * 8)
        )
        result = split_material_into_snippets([para], max_chars=200, overlap_chars=40, min_chars=0)
        assert all(s.char_count <= 200 for s in result.snippets)
        joined = "\n".join(s.content for s in result.snippets)
        assert formula in joined
        assert any(formula in s.content for s in result.snippets)


class TestOverlapAlignment:
    def test_overlap_starts_at_full_sentence(self) -> None:
        prev = "第一句话比较长。第二句话也很长，带有逗号；以及分号。"
        overlap = align_overlap_sentence_boundary(prev, 20)
        assert overlap == "第二句话也很长，带有逗号；以及分号。"[-len(overlap) :]
        assert overlap.startswith("第二句话")

    def test_never_starts_after_comma_or_semicolon(self) -> None:
        prev = "没有句号的很长一段内容，后半部分在这里；末尾继续写下去"
        assert align_overlap_sentence_boundary(prev, 12) == ""

    def test_decimal_period_is_not_an_overlap_start(self) -> None:
        prev = "圆周率是3.14159265358979323846264338327950288 近似值继续继续继续"
        assert align_overlap_sentence_boundary(prev, 40) == ""

    def test_overlap_equal_to_whole_text_when_window_covers_start(self) -> None:
        assert align_overlap_sentence_boundary("整句文本。", 50) == "整句文本。"

    def test_overlap_skips_leading_whitespace(self) -> None:
        prev = "前文。\n\n  新的一句话。结尾"
        assert align_overlap_sentence_boundary(prev, 14) == "新的一句话。结尾"

    def test_overlap_never_starts_inside_formula(self) -> None:
        prev = "说明。设 $a. b$ 为变量而且更多更多内容"
        spans = find_protected_spans(prev)
        # 窗口只覆盖公式内部的句点之后：该句点在公式内，不能作为句首
        inner = prev.index("a.") + 2
        assert align_overlap_sentence_boundary(prev, len(prev) - inner, spans) == ""
        # 窗口覆盖到真正的句首时，从句首开始并保留完整公式
        full = align_overlap_sentence_boundary(prev, len(prev) - 3, spans)
        assert full == "设 $a. b$ 为变量而且更多更多内容"

    def test_overlap_not_inside_table(self) -> None:
        prev = "| a。 | b |\n| c | d |"
        assert align_overlap_sentence_boundary(prev, len(prev) - 2) == ""

    def test_overlap_only_whitespace_after_boundary_returns_empty(self) -> None:
        assert align_overlap_sentence_boundary("前文内容。   ", 5) == ""

    def test_sliding_chunks_overlap_on_sentence_starts(self) -> None:
        sentence = "这是用于测试滑动窗口重叠的一个完整句子。"
        text = sentence * 40
        ranges = split_paragraph_into_ranges(text, 200, 60)
        assert len(ranges) > 2
        for start, _end in ranges[1:]:
            assert start % len(sentence) == 0  # 每个后续切片都从句首开始


class TestMergeShortSnippets:
    def test_three_consecutive_shorts_accumulate_until_min(self) -> None:
        pieces = [("甲" * 50, 1, ""), ("乙" * 50, 1, ""), ("丙" * 50, 1, ""), ("丁" * 50, 1, "")]
        merged = merge_isolated_short_snippets(_chain(*pieces), 120, 800, 500)
        assert len(merged) == 1
        assert merged[0].char_count == 4 * 50 + 3
        assert merged[0].index == 0

    def test_not_stopping_after_one_pairwise_merge(self) -> None:
        shorts = [(f"短{i}" * 10, 1, "") for i in range(6)]  # 每个 ~30 字
        merged = merge_isolated_short_snippets(_chain(*shorts), 120, 800, 500)
        assert len(merged) < 3
        assert all(m.char_count >= 120 for m in merged)

    def test_never_merges_across_pages(self) -> None:
        snippets = _chain(("甲" * 30, 1, ""), ("乙" * 30, 2, ""), ("丙" * 30, 2, ""))
        merged = merge_isolated_short_snippets(snippets, 120, 800, 500)
        assert [m.page_number for m in merged] == [1, 2]
        assert merged[0].content == "甲" * 30
        assert merged[1].content == "乙" * 30 + "\n" + "丙" * 30

    def test_never_merges_across_chapters(self) -> None:
        snippets = _chain(("甲" * 30, 1, "第一章"), ("乙" * 30, 1, "第二章"))
        merged = merge_isolated_short_snippets(snippets, 120, 800, 500)
        assert len(merged) == 2
        assert [m.chapter_title for m in merged] == ["第一章", "第二章"]

    def test_none_page_not_merged_with_numbered_page(self) -> None:
        snippets = _chain(("甲" * 30, None, ""), ("乙" * 30, 3, ""))
        assert len(merge_isolated_short_snippets(snippets, 120, 800, 500)) == 2

    def test_different_source_ref_not_merged(self) -> None:
        a = _snip("甲" * 30, source_ref="幻灯片 1", page=None)
        b = _snip("乙" * 30, source_ref="幻灯片 2", page=None, start=30)
        assert len(merge_isolated_short_snippets([a, b], 120, 800, 500)) == 2

    def test_groups_medium_paragraphs_toward_target(self) -> None:
        paras = [("段" * 150, 1, "") for _ in range(7)]
        merged = merge_isolated_short_snippets(_chain(*paras), 120, 800, 500)
        assert all(m.char_count <= 500 for m in merged)
        assert [m.char_count for m in merged] == [452, 452, 150]

    def test_never_exceeds_max_chars(self) -> None:
        paras = [("段" * 90, 1, "") for _ in range(40)]
        merged = merge_isolated_short_snippets(_chain(*paras), 120, 300, 250)
        assert all(m.char_count <= 300 for m in merged)

    def test_short_leads_next_group_when_previous_is_long_enough(self) -> None:
        a = ("甲" * 200, 1, "")
        b = ("标题行", 1, "")
        c = ("丙" * 200, 1, "")
        merged = merge_isolated_short_snippets(_chain(a, b, c), 120, 800, 500)
        assert len(merged) == 2
        assert merged[0].content == "甲" * 200
        assert merged[1].content == "标题行\n" + "丙" * 200

    def test_trailing_short_backfills_into_previous_same_segment(self) -> None:
        snippets = _chain(("甲" * 300, 1, ""), ("尾", 1, ""))
        merged = merge_isolated_short_snippets(snippets, 120, 800, 500)
        assert len(merged) == 1
        assert merged[0].content == "甲" * 300 + "\n尾"

    def test_short_before_page_break_backfills_into_previous(self) -> None:
        snippets = _chain(("甲" * 300, 1, ""), ("尾", 1, ""), ("乙" * 300, 2, ""))
        merged = merge_isolated_short_snippets(snippets, 120, 800, 500)
        assert [m.page_number for m in merged] == [1, 2]
        assert merged[0].content.endswith("\n尾")

    def test_backfill_blocked_by_max_chars_keeps_short_alone(self) -> None:
        snippets = _chain(("甲" * 795, 1, ""), ("尾" * 10, 1, ""))
        merged = merge_isolated_short_snippets(snippets, 120, 800, 500)
        assert len(merged) == 2

    def test_overlapping_same_paragraph_windows_are_deduplicated(self) -> None:
        first = _snip("甲" * 90 + "共享重叠", start=0)
        # 第二个窗口从 first 末尾 4 个字符处开始（滑动重叠）
        second = Snippet(
            index=1,
            content="共享重叠" + "乙" * 20,
            char_count=24,
            start_offset=first.end_offset - 4,
            end_offset=first.end_offset - 4 + 24,
            chapter_title="",
            source_ref="p",
            doc_type="pdf",
            page_number=1,
        )
        merged = merge_isolated_short_snippets([first, second], 120, 800, 500)
        assert len(merged) == 1
        assert merged[0].content == "甲" * 90 + "共享重叠" + "乙" * 20
        assert merged[0].start_offset == first.start_offset
        assert merged[0].end_offset == second.end_offset

    def test_fully_covered_window_adds_nothing(self) -> None:
        first = _snip("甲" * 50)
        covered = Snippet(1, "甲" * 10, 10, 20, 30, "", "p", "pdf", 1)
        merged = merge_isolated_short_snippets([first, covered], 120, 800, 500)
        assert len(merged) == 1
        assert merged[0].content == "甲" * 50
        assert merged[0].end_offset == first.end_offset

    def test_min_chars_zero_disables_merging_and_empty_input(self) -> None:
        snippets = _chain(("甲", 1, ""), ("乙", 1, ""))
        assert merge_isolated_short_snippets(snippets, 0) is snippets
        assert merge_isolated_short_snippets([], 120) == []

    def test_target_below_min_is_clamped(self) -> None:
        snippets = _chain(("甲" * 130, 1, ""), ("乙" * 130, 1, ""))
        merged = merge_isolated_short_snippets(snippets, 120, 800, 10)
        assert len(merged) == 2  # 130 + 131 > clamped target 120

    def test_default_signature_backwards_compatible(self) -> None:
        snippets = _chain(("甲" * 30, 1, ""), ("乙" * 30, 1, ""))
        merged = merge_isolated_short_snippets(snippets, 80)
        assert len(merged) == 1


class TestSplitMaterialIntegration:
    def test_default_min_chars_is_120(self) -> None:
        from app.core.algorithms.material_chunking import DEFAULT_MIN_CHARS, DEFAULT_TARGET_CHARS

        assert DEFAULT_MIN_CHARS == 120
        assert DEFAULT_TARGET_CHARS == 500

    def test_pdf_fragment_lines_are_aggregated_per_page(self) -> None:
        def para(text: str, page: int) -> ParagraphInput:
            return ParagraphInput(
                text=text, source_ref=f"第 {page} 页", doc_type="pdf", page_number=page
            )

        fragments = ["σi", "2", "rank σi=1", "k", "正文说明文字" * 5, "n"]
        items = [para(t, 1) for t in fragments] + [para(t, 2) for t in fragments]
        result = split_material_into_snippets(items)
        pages = [s.page_number for s in result.snippets]
        assert pages == [1, 2]
        for snippet in result.snippets:
            assert snippet.char_count >= 120 or snippet.char_count == len("\n".join(fragments))
            assert snippet.source_ref == f"第 {snippet.page_number} 页"
            assert snippet.doc_type == "pdf"

    def test_chapter_boundary_respected_end_to_end(self) -> None:
        items = [
            ParagraphInput(text="第一章", is_title=True),
            ParagraphInput(text="短句甲。"),
            ParagraphInput(text="第二章", is_title=True),
            ParagraphInput(text="短句乙。"),
        ]
        result = split_material_into_snippets(items)
        assert [s.chapter_title for s in result.snippets] == ["第一章", "第二章"]

    def test_markdown_title_strips_hashes_and_filters_ultra_short_noise_fragments(self) -> None:
        body = "主成分分析是一种常用的线性降维方法，它通过正交变换提取主方向。" * 3
        items = [
            ParagraphInput(text="## 基本概念", is_title=True, doc_type="pdf", page_number=1),
            ParagraphInput(text="m", doc_type="pdf", page_number=1),
            ParagraphInput(text=body, doc_type="pdf", page_number=2),
            ParagraphInput(text="基本概念", doc_type="pdf", page_number=3),
        ]
        result = split_material_into_snippets(items)
        assert len(result.snippets) == 1
        assert result.snippets[0].chapter_title == "基本概念"
        assert "主成分分析" in result.snippets[0].content
        assert result.snippets[0].index == 0

    def test_target_chars_validation(self) -> None:
        with pytest.raises(ValueError, match="target_chars"):
            split_material_into_snippets(["测试"], target_chars=-1)

    def test_hard_limit_with_mixed_content(self) -> None:
        formula = "$$" + "x+" * 120 + "y$$"
        table = "\n".join(f"| {i} | {i * 2} |" for i in range(80))
        paras = [
            "引言段落。" * 40,
            formula,
            "圆周率3.14159与版本v1.2.3均不应被截断。" * 30,
            table,
            "结尾。",
        ]
        result = split_material_into_snippets(paras, max_chars=300, overlap_chars=60)
        assert result.snippets
        assert all(s.char_count <= 300 for s in result.snippets)
        for s in result.snippets:
            assert s.char_count == len(s.content)
            assert "3.\n" not in s.content


class TestEdgeBranches:
    def test_clean_pseudo_bullet_empty(self) -> None:
        from app.core.algorithms.material_chunking import clean_pseudo_bullet_glyphs

        assert clean_pseudo_bullet_glyphs("") == ""

    def test_period_without_left_context_is_not_boundary(self) -> None:
        assert is_sentence_boundary(". x", 0) is False
        assert is_sentence_boundary("a . b", 2) is False

    def test_abbreviation_suffix_inside_longer_word_is_a_real_end(self) -> None:
        assert is_sentence_boundary("canvs. Next", 5) is True

    def test_comma_secondary_split_and_thousands_separator(self) -> None:
        text = "x" * 5 + "1,000" + "y" * 5 + ", " + "z" * 20
        # 窗口内最靠右的真逗号在 "y..y," 之后，而不是千分位逗号
        pos = find_best_split_point(text, 0, len(text) - 5)
        assert text[pos - 1] == ","
        assert pos == text.index(", ") + 1
        # 窗口只含千分位逗号 -> 硬切
        assert find_best_split_point("a1,000b", 0, 5) == 5
        assert find_best_split_point(",x", 0, 2) == 1  # 行首逗号无前驱数字
