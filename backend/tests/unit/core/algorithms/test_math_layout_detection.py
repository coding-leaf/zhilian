"""Unit tests for broken-math-layout detection and Greek/Cyrillic garble handling."""

import pytest

from app.core.algorithms.ocr_quality import (
    detect_broken_math_layout,
    detect_symbol_garble,
    sanitize_symbol_garble,
)

BROKEN_PAGE = "rank σi=1\nk σpiupi ђvpi"


class TestDetectBrokenMathLayout:
    """detect_broken_math_layout：命中损坏、不误伤正常文本。"""

    def test_research_sample_is_detected(self) -> None:
        assert detect_broken_math_layout(BROKEN_PAGE) is True

    def test_cyrillic_mixed_into_latin_greek(self) -> None:
        assert detect_broken_math_layout("where ђ denotes the mean") is True
        assert detect_broken_math_layout("ђvpi") is True

    def test_greek_glued_latin_cluster(self) -> None:
        assert detect_broken_math_layout("the value σpiupi is") is True
        assert detect_broken_math_layout("αlpha fit") is True

    @pytest.mark.parametrize(
        "text",
        [
            "E=mc^2",
            "σ = 0.5",
            "令 σ = 0.5，则 E=mc^2 成立。",
            "这是一段完全正常的中文说明文字，包含若干标点；以及数字 3.14 和 2024 年。",
            "This is plain English prose. It has several sentences, commas; and numbers like 42.",
            "The stress σmax and the rate λmin were measured in μmol/L at 25 °C.",
            "Привет, мир! Это обычный русский текст с несколькими словами.",
            "Мы и я в ту ночь",
            "",
            "   \n \t ",
        ],
    )
    def test_no_false_positive(self, text: str) -> None:
        assert detect_broken_math_layout(text) is False

    def test_dense_ultra_short_formula_fragment_page(self) -> None:
        page = "\n".join(["σi", "2", "i=1", "k", "n", "x2", "Σ", "=", "1"])
        assert detect_broken_math_layout(page) is True

    def test_dense_fragments_need_min_six_lines(self) -> None:
        page = "\n".join(["σi", "2", "i=1", "x2", "3"])
        assert detect_broken_math_layout(page) is False

    def test_fragment_ratio_must_exceed_45_percent(self) -> None:
        long_line = "这是一行足够长的正常中文文本内容，用来稀释短行占比。"
        # 6 行中 2 行碎片 -> 33%
        lines = ["σi", "2"] + [long_line] * 4
        assert detect_broken_math_layout("\n".join(lines)) is False
        # 6 行中 3 行碎片 -> 50%
        lines = ["σi", "2", "i=1"] + [long_line] * 3
        assert detect_broken_math_layout("\n".join(lines)) is True

    def test_short_chinese_lines_with_digits_are_not_formula_fragments(self) -> None:
        page = "\n".join(
            ["1.1 概述", "1.2 背景", "1.3 目标", "2.1 方法", "2.2 数据", "2.3 结果", "3 结论"]
        )
        assert detect_broken_math_layout(page) is False

    def test_bare_cyrillic_prose_with_short_words_not_flagged_without_latin(self) -> None:
        assert detect_broken_math_layout("я и он") is False


class TestDetectSymbolGarbleExtended:
    """detect_symbol_garble 对希腊/西里尔混合碎片的扩展，及既有 ASCII 行为不变。"""

    def test_math_fragments_are_reported(self) -> None:
        is_garbled, ratio, frags = detect_symbol_garble(BROKEN_PAGE)
        assert is_garbled is True
        assert ratio > 0.0
        assert "σpiupi" in frags
        assert "ђvpi" in frags

    def test_single_math_fragment_low_ratio_not_garbled(self) -> None:
        text = "这是一段足够长的正常文字，用来稀释乱码占比。" * 5 + " σpiupi"
        is_garbled, _ratio, frags = detect_symbol_garble(text)
        assert is_garbled is False
        assert frags == ("σpiupi",)

    def test_existing_ascii_clusters_still_detected(self) -> None:
        is_garbled, _ratio, frags = detect_symbol_garble('AB&A& "#$ !" ! #')
        assert is_garbled is True
        assert frags

    def test_clean_text_is_not_garbled(self) -> None:
        assert detect_symbol_garble("普通文本 σ = 0.5 and E=mc^2")[0] is False


class TestSanitizeSymbolGarbleExtended:
    """sanitize_symbol_garble 同步移除数学碎片，同时保持原有行为。"""

    def test_removes_math_garble_tokens(self) -> None:
        assert sanitize_symbol_garble(BROKEN_PAGE) == "rank σi=1\nk"

    def test_keeps_legit_greek_and_prose(self) -> None:
        text = "令 σ = 0.5\nσmax 与 μmol 保持不变"
        assert sanitize_symbol_garble(text) == text

    def test_still_drops_ascii_garble(self) -> None:
        cleaned = sanitize_symbol_garble("正常文字 AB&A& 继续")
        assert "AB&A&" not in cleaned
        assert "正常文字" in cleaned
