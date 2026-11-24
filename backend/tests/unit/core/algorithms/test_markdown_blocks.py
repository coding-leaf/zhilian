"""Tests for structure-preserving Markdown block splitting."""

import pytest

from app.core.algorithms.markdown_blocks import (
    split_markdown_blocks,
    unwrap_pdf_visual_line_breaks,
)


class TestSplitMarkdownBlocks:
    def test_empty_and_blank_input(self) -> None:
        assert split_markdown_blocks("") == []
        assert split_markdown_blocks("   \n \n\t") == []

    def test_blank_lines_separate_paragraphs_keeping_inner_newlines(self) -> None:
        text = "第一段第一行\n第一段第二行\n\n第二段\n\n\n第三段"
        assert split_markdown_blocks(text) == ["第一段第一行\n第一段第二行", "第二段", "第三段"]

    def test_multiline_display_math_is_one_block(self) -> None:
        text = "前文说明\n\n$$\n\\sum_{i=1}^{k}\n\\sigma_i^2\n$$\n\n后文说明"
        blocks = split_markdown_blocks(text)
        assert blocks == ["前文说明", "$$\n\\sum_{i=1}^{k}\n\\sigma_i^2\n$$", "后文说明"]

    def test_display_math_without_surrounding_blank_lines(self) -> None:
        text = "引言\n$$\na+b\n$$\n结语\n\n另一段"
        blocks = split_markdown_blocks(text)
        assert blocks[0] == "引言"
        assert blocks[1] == "$$\na+b\n$$"
        assert blocks[2] == "结语"
        assert blocks[3] == "另一段"

    def test_single_line_display_math(self) -> None:
        blocks = split_markdown_blocks("文字\n\n$$E=mc^2$$\n\n结束")
        assert blocks == ["文字", "$$E=mc^2$$", "结束"]

    def test_bracket_display_math_single_and_multiline(self) -> None:
        assert split_markdown_blocks("a\n\n\\[x^2\\]\n\nb") == ["a", "\\[x^2\\]", "b"]
        multi = "a\n\n\\[\nx^2 + y^2\n\\]\n\nb"
        assert split_markdown_blocks(multi) == ["a", "\\[\nx^2 + y^2\n\\]", "b"]

    def test_pipe_table_kept_intact(self) -> None:
        table = "| 列A | 列B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
        text = "表前说明\n\n" + table + "\n\n表后说明"
        assert split_markdown_blocks(text) == ["表前说明", table, "表后说明"]

    def test_table_directly_after_paragraph_line_is_separate_block(self) -> None:
        text = "说明行\n| a | b |\n| 1 | 2 |\n\n尾部"
        assert split_markdown_blocks(text) == ["说明行", "| a | b |\n| 1 | 2 |", "尾部"]

    def test_single_pipe_is_not_a_table(self) -> None:
        assert split_markdown_blocks("| 只有一个竖线\n\n下一段") == ["| 只有一个竖线", "下一段"]

    def test_code_fence_is_atomic(self) -> None:
        text = "说明\n\n```python\nx = 1\n\ny = 2\n```\n\n后文"
        assert split_markdown_blocks(text) == ["说明", "```python\nx = 1\n\ny = 2\n```", "后文"]

    def test_unclosed_code_fence_takes_remaining_lines(self) -> None:
        blocks = split_markdown_blocks("前\n\n```\nunclosed line1\nunclosed line2")
        assert blocks[0] == "前"
        assert blocks[1] == "```\nunclosed line1\nunclosed line2"

    def test_no_blank_line_legacy_text_becomes_per_line_blocks(self) -> None:
        text = "第一行\n第二行\n第三行"
        assert split_markdown_blocks(text) == ["第一行", "第二行", "第三行"]

    def test_legacy_text_still_keeps_formula_and_table_atomic(self) -> None:
        text = "说明\n$$\na\nb\n$$\n| x | y |\n| 1 | 2 |\n结尾"
        assert split_markdown_blocks(text) == [
            "说明",
            "$$\na\nb\n$$",
            "| x | y |\n| 1 | 2 |",
            "结尾",
        ]

    def test_unclosed_display_math_does_not_swallow_page(self) -> None:
        lines = ["$$ 未闭合的公式"] + [f"后续内容第{i}行" for i in range(60)]
        blocks = split_markdown_blocks("\n".join(lines))
        assert blocks[0] == "$$ 未闭合的公式"
        assert blocks[1:] == [f"后续内容第{i}行" for i in range(60)]

    def test_display_math_closing_beyond_scan_window_is_not_swallowed(self) -> None:
        body = [f"行{i}" for i in range(50)]
        text = "\n".join(["$$", *body, "$$"])
        blocks = split_markdown_blocks(text)
        assert blocks[0] == "$$"
        assert "行0" in blocks

    def test_crlf_and_cr_normalized(self) -> None:
        assert split_markdown_blocks("甲\r\n\r\n乙\r丙") == ["甲", "乙\n丙"]
        assert split_markdown_blocks("甲\r\n乙") == ["甲", "乙"]

    def test_blocks_are_stripped_and_nonempty(self) -> None:
        blocks = split_markdown_blocks("  \n\n  内容  \n\n   \n\n")
        assert blocks == ["内容"]

    def test_inline_dollar_text_is_plain_paragraph(self) -> None:
        text = "设 $x$ 为变量，则 $x^2$ 非负。\n\n下一段"
        assert split_markdown_blocks(text) == ["设 $x$ 为变量，则 $x^2$ 非负。", "下一段"]

    @pytest.mark.parametrize("closer_line", ["$$", "  $$  "])
    def test_display_math_with_indented_delimiters(self, closer_line: str) -> None:
        text = f"  $$\nf(x)\n{closer_line}\n\n尾"
        blocks = split_markdown_blocks(text)
        assert blocks[0].startswith("$$")
        assert blocks[0].endswith("$$")
        assert blocks[-1] == "尾"


class TestUnwrapPdfVisualLineBreaks:
    def test_unwraps_cjk_mid_sentence_hard_wraps(self) -> None:
        raw = (
            "降维的目的就是降低数据的维度\n"
            "从而方便后续对数据的存储、可\n视化、\n建模等操作。\n"
            "下一段从这里开始。"
        )
        unwrapped = unwrap_pdf_visual_line_breaks(raw)
        assert unwrapped == (
            "降维的目的就是降低数据的维度从而方便后续对数据的存储、可视化、建模等操作。\n"
            "下一段从这里开始。"
        )

    def test_unwraps_english_words_and_hyphenation(self) -> None:
        raw = "Principal component analy-\nsis is a linear\ntechnique.\nNext sentence here."
        assert unwrap_pdf_visual_line_breaks(raw) == (
            "Principal component analysis is a linear technique.\nNext sentence here."
        )

    def test_preserves_markdown_blocks_and_standalone_short_heading(self) -> None:
        raw = "\n".join(
            [
                "基本概念",
                "线性降维将高维数据",
                "映射到低维空间。",
                "",
                "# 章节标题",
                "- 列表第一项",
                "1. 编号列表项",
                "> 引用说明",
                "```python",
                "a = 1",
                "b = 2",
                "```",
                "| col1 | col2 |",
                "| --- | --- |",
                "| 1 | 2 |",
                "$$",
                "x = a + b",
                "y = c + d",
                "$$",
            ]
        )
        unwrapped = unwrap_pdf_visual_line_breaks(raw)
        assert "基本概念\n线性降维将高维数据映射到低维空间。" in unwrapped
        assert "# 章节标题\n- 列表第一项\n1. 编号列表项\n> 引用说明" in unwrapped
        assert "```python\na = 1\nb = 2\n```" in unwrapped
        assert "| col1 | col2 |\n| --- | --- |\n| 1 | 2 |" in unwrapped
        assert "$$\nx = a + b\ny = c + d\n$$" in unwrapped
