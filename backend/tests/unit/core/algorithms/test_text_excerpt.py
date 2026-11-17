"""Unit tests for clean excerpt trimming and neighbor snippet merging."""

import pytest

from app.core.algorithms.text_excerpt import (
    ELLIPSIS,
    merge_adjacent_snippet_texts,
    trim_excerpt_cleanly,
)


class TestTrimExcerptCleanly:
    def test_short_text_unchanged(self) -> None:
        assert trim_excerpt_cleanly("短文本。", 480) == "短文本。"
        text = "x" * 480
        assert trim_excerpt_cleanly(text, 480) == text

    def test_invalid_max_chars(self) -> None:
        with pytest.raises(ValueError, match="max_chars"):
            trim_excerpt_cleanly("abc", 0)

    def test_cuts_at_last_sentence_end_and_appends_ellipsis(self) -> None:
        sentence = "这是一个完整的句子用来测试摘录。"
        text = sentence * 40
        result = trim_excerpt_cleanly(text, 100)
        assert result.endswith("。" + ELLIPSIS)
        assert len(result) <= 100
        assert result[:-1] == sentence * (len(result[:-1]) // len(sentence))

    def test_english_sentence_boundaries(self) -> None:
        text = "Machine learning is a field of study. " * 20
        result = trim_excerpt_cleanly(text, 100)
        assert result.endswith("study." + ELLIPSIS)
        assert len(result) <= 100

    def test_decimal_is_not_a_sentence_end(self) -> None:
        text = "圆周率约等于3.14159" + "，" + "数" * 100
        result = trim_excerpt_cleanly(text, 40)
        assert "3.14159" in result or not result.startswith("圆周率约等于3.")
        assert "3." not in result.replace("3.14159", "")

    def test_abbreviation_is_not_a_sentence_end(self) -> None:
        text = "Many methods exist, e.g. SVM and trees are common ones " + "word " * 40
        result = trim_excerpt_cleanly(text, 60)
        assert not result.removesuffix(ELLIPSIS).endswith("e.g.")

    def test_newline_counts_as_sentence_end(self) -> None:
        text = "第一行内容比较长一些用来填充空间" + "\n" + "第二行" * 60
        result = trim_excerpt_cleanly(text, 50)
        assert result == "第一行内容比较长一些用来填充空间" + ELLIPSIS

    def test_never_cuts_inside_inline_math(self) -> None:
        prefix = "已知条件如下，我们需要计算结果并给出完整的推导过程。"
        formula = "$\\sum_{i=1}^{k} \\sigma_i^2 + \\alpha \\beta$"
        text = prefix + "其中" + formula + "是关键量。" + "后续内容" * 30
        # 让截断点恰好落在公式内部
        cut_inside = len(prefix) + 2 + len(formula) // 2
        result = trim_excerpt_cleanly(text, cut_inside + 1)
        body = result.removesuffix(ELLIPSIS)
        assert body.count("$") % 2 == 0
        assert "\\sum" not in body or body.count("$") >= 2

    def test_never_cuts_inside_display_math(self) -> None:
        intro = "公式如下所示，请仔细阅读后继续往下看。"
        block = "$$\n\\sum_{i=1}^{k}\\sigma_i^2 = \\frac{1}{n}\\sum x_i\n$$"
        text = intro + block + "结束。" + "尾" * 200
        result = trim_excerpt_cleanly(text, len(intro) + 20)
        body = result.removesuffix(ELLIPSIS)
        assert "$$" not in body
        assert body.startswith(intro[:10])

    def test_unclosed_math_opener_backs_up(self) -> None:
        text = "前面是一整句完整的话。接着出现公式 $\\sum_{i=1}^{k} x_i 然后没有结束符" + "字" * 100
        result = trim_excerpt_cleanly(text, 60)
        assert "$" not in result
        assert result.endswith(ELLIPSIS)

    def test_never_cuts_in_the_middle_of_a_table_row(self) -> None:
        rows = "\n".join(f"| 列{i} | 数值{i}.5 | 说明文字 |" for i in range(30))
        text = "表格说明如下。\n" + rows
        result = trim_excerpt_cleanly(text, 120)
        body = result.removesuffix(ELLIPSIS)
        for line in body.splitlines():
            if line.startswith("|"):
                assert line.endswith("|")

    def test_prefers_clause_boundary_over_tiny_sentence(self) -> None:
        # 40% 之后没有句末，只有逗号 -> 选逗号而不是开头的短句
        text = "短句。" + ("较长的从句内容用于填充，" * 30)
        result = trim_excerpt_cleanly(text, 100)
        assert result.removesuffix(ELLIPSIS).endswith("，")
        assert len(result) > 60

    def test_falls_back_to_early_sentence_when_nothing_later(self) -> None:
        text = "开头一句话。" + "无" * 300
        result = trim_excerpt_cleanly(text, 100)
        assert result == "开头一句话。" + ELLIPSIS

    def test_hard_cut_when_no_punctuation(self) -> None:
        result = trim_excerpt_cleanly("无标点" * 100, 50)
        assert len(result) == 50
        assert result.endswith(ELLIPSIS)

    def test_hard_cut_backs_up_before_math_span(self) -> None:
        text = "前缀文字没有任何标点" + "$" + "x" * 80 + "$" + "后" * 50
        result = trim_excerpt_cleanly(text, 40)
        assert result == "前缀文字没有任何标点" + ELLIPSIS

    def test_math_from_the_start_is_hard_cut_unavoidably(self) -> None:
        text = "$" + "x" * 200 + "$"
        result = trim_excerpt_cleanly(text, 30)
        assert result
        assert len(result) <= 30

    def test_never_empty_for_whitespace_prefixed_input(self) -> None:
        text = " \n" * 100 + "正文内容" + "文" * 100
        result = trim_excerpt_cleanly(text, 50)
        assert result.strip()
        text2 = " " * 100
        assert trim_excerpt_cleanly(text2, 10) == " " * 10

    def test_tiny_max_chars(self) -> None:
        assert trim_excerpt_cleanly("abcdef", 1) == "a" + ELLIPSIS

    def test_no_ellipsis_when_not_truncated(self) -> None:
        assert ELLIPSIS not in trim_excerpt_cleanly("完整句子。" * 3, 480)


class TestMergeAdjacentSnippetTexts:
    def test_empty_inputs(self) -> None:
        assert merge_adjacent_snippet_texts([]) == ""
        assert merge_adjacent_snippet_texts(["", "  \n"]) == ""

    def test_single_text(self) -> None:
        assert merge_adjacent_snippet_texts(["只有一段"]) == "只有一段"

    def test_joins_without_overlap_by_newline(self) -> None:
        assert (
            merge_adjacent_snippet_texts(["第一段内容", "第二段内容"]) == "第一段内容\n第二段内容"
        )

    def test_removes_seam_overlap(self) -> None:
        overlap = "这是两个相邻片段之间共享的滑动窗口重叠内容部分。"
        assert len(overlap) >= 20
        first = "前文内容。" + overlap
        second = overlap + "后文内容。"
        assert (
            merge_adjacent_snippet_texts([first, second]) == "前文内容。" + overlap + "后文内容。"
        )

    def test_short_overlap_below_threshold_is_kept(self) -> None:
        first = "前文abc。短重叠"
        second = "短重叠后文"
        assert merge_adjacent_snippet_texts([first, second]) == first + "\n" + second

    def test_three_way_chain(self) -> None:
        o1 = "第一处重叠的内容需要足够长才会被识别为滑动窗口重叠。"
        o2 = "第二处重叠的内容同样需要足够长才会被识别为滑动窗口重叠。"
        a = "A开头。" + o1
        b = o1 + "B中间。" + o2
        c = o2 + "C结尾。"
        assert (
            merge_adjacent_snippet_texts([a, b, c]) == "A开头。" + o1 + "B中间。" + o2 + "C结尾。"
        )

    def test_fully_contained_suffix_not_duplicated(self) -> None:
        tail = "这是一段至少二十个字符长度的尾部内容，用于测试包含关系。"
        first = "开头。" + tail
        assert merge_adjacent_snippet_texts([first, tail]) == first

    def test_skips_blank_entries_between(self) -> None:
        assert merge_adjacent_snippet_texts(["甲", "", "乙"]) == "甲\n乙"

    def test_probe_matches_but_not_a_real_suffix_overlap(self) -> None:
        probe = "二十个字符以上的公共开头文本用来触发探测匹配逻辑"
        first = probe + "中间不同的内容" + "结尾X"
        second = probe + "后续"
        merged = merge_adjacent_snippet_texts([first, second])
        assert merged == first + "\n" + second


class TestExcerptEdgeBranches:
    def test_double_dollar_opener_without_closer_backs_up_to_opener(self) -> None:
        text = "前缀文字没有标点" + "$$" + "x+" * 60
        assert trim_excerpt_cleanly(text, 30) == "前缀文字没有标点" + ELLIPSIS

    def test_unclosed_dollar_at_text_start_hard_cuts(self) -> None:
        result = trim_excerpt_cleanly("$" + "x+" * 60, 20)
        assert result and len(result) <= 20

    def test_leading_whitespace_shrinks_to_fit(self) -> None:
        assert trim_excerpt_cleanly("   短文", 4) == "短文"

    def test_repeated_probe_occurrences_then_real_overlap(self) -> None:
        probe = "重复出现的二十个字符以上开头文本用来测试多次探测"
        first = probe + "甲" * 5 + probe + "乙"
        second = probe + "乙" + "继续"
        merged = merge_adjacent_snippet_texts([first, second])
        assert merged == probe + "甲" * 5 + probe + "乙" + "继续"


class TestUnclosedMathOpener:
    def test_states(self) -> None:
        from app.core.algorithms.text_excerpt import _unclosed_math_opener as opener

        assert opener("无公式") is None
        assert opener("$a$ 已闭合") is None
        assert opener("$$a$$ 已闭合") is None
        assert opener("前$a") == 1
        assert opener("前$$a+b") == 1
        assert opener("$$a $x$ b") == 0  # 块内的 $ 不是新的行内开启符
        assert opener("价格 \\$5 元") is None  # 转义的美元符
        assert opener("$$a$$ 再 $b") == 8
