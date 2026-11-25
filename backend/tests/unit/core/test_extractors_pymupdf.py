"""Tests for the PyMuPDF-first PDF extraction path, reading order and page rendering."""

from types import SimpleNamespace
from typing import Any

import pymupdf
import pytest

from app.core import extractors
from app.core.errors import MaterialInvalidError
from app.core.extractors import (
    PdfPageExtraction,
    _build_page_extraction,
    _extract_pages_with_pymupdf,
    _order_blocks_reading_order,
    _pymupdf_page_images,
    _pymupdf_page_lacks_tounicode,
    _pymupdf_page_text,
    extract_pdf_pages_with_diagnostics,
    render_pdf_page_png,
)

CLEAN_TEXT = "This is a perfectly clean page with ordinary English prose for the gate."


def _tiny_png() -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8))
    pix.set_rect(pix.irect, (255, 0, 0))
    data: bytes = pix.tobytes("png")
    return data


def _build_pdf(pages: list[list[tuple[tuple[float, float], str, str]]]) -> bytes:
    """每页是 [(坐标, 文本, 字体名)] 列表；字体名 helv/symb 为 PDF 内置字体。"""
    doc = pymupdf.open()
    for items in pages:
        page = doc.new_page()
        for point, text, fontname in items:
            page.insert_text(point, text, fontname=fontname, fontsize=11)
    data: bytes = doc.tobytes()
    doc.close()
    return data


def _block(x0: float, y0: float, x1: float, y1: float, text: str, kind: int = 0) -> tuple[Any, ...]:
    return (x0, y0, x1, y1, text, 0, kind)


class TestPyMuPdfExtraction:
    def test_clean_page_needs_no_repair(self) -> None:
        pdf = _build_pdf([[((72, 72), CLEAN_TEXT, "helv")]])
        pages = extract_pdf_pages_with_diagnostics(pdf)
        assert len(pages) == 1
        page = pages[0]
        assert page.page_number == 1
        assert "clean page" in page.text
        assert page.lacks_tounicode_symbol_font is False
        assert page.has_symbol_garble is False
        assert page.has_broken_math_layout is False
        assert page.needs_repair is False
        assert page.embedded_images == ()

    def test_symbol_font_without_tounicode_is_flagged(self) -> None:
        pdf = _build_pdf(
            [
                [((72, 72), "abc sym", "symb"), ((72, 120), CLEAN_TEXT, "helv")],
                [((72, 72), CLEAN_TEXT, "helv")],
            ]
        )
        pages = extract_pdf_pages_with_diagnostics(pdf)
        assert [p.lacks_tounicode_symbol_font for p in pages] == [True, False]
        assert pages[0].needs_repair is True
        assert pages[1].needs_repair is False

    def test_dense_formula_fragment_page_has_broken_math_layout(self) -> None:
        lines = ["x2", "2", "i=1", "k", "n", "y2", "+", "=", "1", "z3"]
        pdf = _build_pdf(
            [
                [((72, 72 + 20 * i), line, "helv") for i, line in enumerate(lines)],
                [((72, 72), CLEAN_TEXT, "helv")],
            ]
        )
        pages = extract_pdf_pages_with_diagnostics(pdf)
        assert pages[0].has_broken_math_layout is True
        assert pages[0].needs_repair is True
        assert pages[1].has_broken_math_layout is False

    def test_broken_math_detector_result_is_propagated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(extractors, "detect_broken_math_layout", lambda _text: True)
        pdf = _build_pdf([[((72, 72), CLEAN_TEXT, "helv")]])
        page = extract_pdf_pages_with_diagnostics(pdf)[0]
        assert page.has_broken_math_layout is True
        assert page.needs_repair is True

    def test_blank_pdf_rejected_by_valid_text_gate(self) -> None:
        doc = pymupdf.open()
        doc.new_page()
        pdf = doc.tobytes()
        doc.close()
        with pytest.raises(MaterialInvalidError, match="无有效文字"):
            extract_pdf_pages_with_diagnostics(pdf)

    def test_fewer_than_ten_valid_chars_rejected(self) -> None:
        pdf = _build_pdf([[((72, 72), "hi there", "helv")]])
        with pytest.raises(MaterialInvalidError) as exc_info:
            extract_pdf_pages_with_diagnostics(pdf)
        assert exc_info.value.details["valid_char_count"] == 7

    def test_exactly_ten_valid_chars_accepted(self) -> None:
        pdf = _build_pdf([[((72, 72), "abcde fghij", "helv")]])
        assert extract_pdf_pages_with_diagnostics(pdf)[0].text == "abcde fghij"

    def test_invalid_bytes_raise_material_invalid(self) -> None:
        with pytest.raises(MaterialInvalidError, match="PDF 文件解析失败"):
            extract_pdf_pages_with_diagnostics(b"definitely not a pdf")

    def test_pymupdf_failure_falls_back_to_pypdf(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("pymupdf unavailable")

        stub = SimpleNamespace(
            TOOLS=SimpleNamespace(mupdf_display_errors=lambda _flag: None), open=boom
        )
        monkeypatch.setattr(extractors, "_pymupdf", stub)
        pdf = _build_pdf([[((72, 72), CLEAN_TEXT, "helv")]])
        pages = extract_pdf_pages_with_diagnostics(pdf)
        assert len(pages) == 1
        assert "clean page" in pages[0].text

    def test_pymupdf_returning_no_text_falls_back_to_pypdf(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(extractors, "_extract_pages_with_pymupdf", lambda _content: None)
        pdf = _build_pdf([[((72, 72), CLEAN_TEXT, "helv")]])
        pages = extract_pdf_pages_with_diagnostics(pdf)
        assert "clean page" in pages[0].text

    def test_multi_page_numbering_is_one_based(self) -> None:
        pdf = _build_pdf([[((72, 72), CLEAN_TEXT, "helv")], [((72, 72), CLEAN_TEXT, "helv")]])
        assert [p.page_number for p in extract_pdf_pages_with_diagnostics(pdf)] == [1, 2]

    def test_two_column_page_is_read_left_column_first(self) -> None:
        filler = (
            " that wraps across several lines because the box is narrow enough"
            " to force wrapping here."
        )
        texts = {
            "right1": "Right column first paragraph text" + filler,
            "left1": "Left column first paragraph text" + filler,
            "right2": "Right column second paragraph text" + filler,
            "left2": "Left column second paragraph text" + filler,
        }
        doc = pymupdf.open()
        page = doc.new_page()
        # 先写右栏再写左栏，验证排序不依赖内容流顺序
        for key, rect in (
            ("right1", pymupdf.Rect(300, 60, 545, 160)),
            ("left1", pymupdf.Rect(50, 60, 270, 160)),
            ("right2", pymupdf.Rect(300, 260, 545, 360)),
            ("left2", pymupdf.Rect(50, 260, 270, 360)),
        ):
            page.insert_textbox(rect, texts[key], fontname="helv", fontsize=11)
        pdf = doc.tobytes()
        doc.close()
        text = extract_pdf_pages_with_diagnostics(pdf)[0].text
        flat = " ".join(text.split())
        order = [
            flat.index(s)
            for s in (
                "Left column first",
                "Left column second",
                "Right column first",
                "Right column second",
            )
        ]
        assert order == sorted(order)
        assert "\n\n" in text  # 块之间以空行分隔

    def test_dirty_page_with_embedded_image_loads_images(self) -> None:
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "abc sym", fontname="symb")
        page.insert_text((72, 120), CLEAN_TEXT, fontname="helv")
        page.insert_image(pymupdf.Rect(50, 200, 150, 300), stream=_tiny_png())
        pdf = doc.tobytes()
        doc.close()
        page_result = extract_pdf_pages_with_diagnostics(pdf)[0]
        assert page_result.needs_repair is True
        assert page_result.embedded_images
        assert page_result.embedded_images[0].startswith(b"\x89PNG")


class TestPdfPageExtractionNeedsRepair:
    @pytest.mark.parametrize(
        ("lacks", "garble", "broken", "expected"),
        [
            (False, False, False, False),
            (True, False, False, True),
            (False, True, False, True),
            (False, False, True, True),
        ],
    )
    def test_needs_repair_flags(
        self, lacks: bool, garble: bool, broken: bool, expected: bool
    ) -> None:
        page = PdfPageExtraction(
            page_number=1,
            text="x",
            lacks_tounicode_symbol_font=lacks,
            has_symbol_garble=garble,
            has_broken_math_layout=broken,
        )
        assert page.needs_repair is expected


class TestBuildPageExtraction:
    def test_images_loaded_only_when_dirty_or_empty(self) -> None:
        calls: list[int] = []

        def loader() -> tuple[bytes, ...]:
            calls.append(1)
            return (b"img",)

        clean = _build_page_extraction(
            page_number=1, raw_text=CLEAN_TEXT, lacks_tounicode=False, image_loader=loader
        )
        assert clean.embedded_images == () and calls == []

        empty = _build_page_extraction(
            page_number=2, raw_text="", lacks_tounicode=False, image_loader=loader
        )
        assert empty.embedded_images == (b"img",) and len(calls) == 1

        dirty = _build_page_extraction(
            page_number=3, raw_text=CLEAN_TEXT, lacks_tounicode=True, image_loader=loader
        )
        assert dirty.embedded_images == (b"img",) and len(calls) == 2

    def test_garble_fragments_are_reported(self) -> None:
        page = _build_page_extraction(
            page_number=1,
            raw_text="rank σi=1\nk σpiupi ђvpi",
            lacks_tounicode=False,
            image_loader=lambda: (),
        )
        assert page.has_symbol_garble is True
        assert page.has_broken_math_layout is True
        assert "σpiupi" in page.suspicious_fragments


class TestReadingOrder:
    def test_single_column_sorted_top_to_bottom(self) -> None:
        blocks = [
            _block(50, 300, 500, 320, "third"),
            _block(50, 100, 500, 120, "first"),
            _block(50, 200, 500, 220, "second"),
        ]
        ordered = _order_blocks_reading_order(blocks, 600.0)
        assert [b[4] for b in ordered] == ["first", "second", "third"]

    def test_two_columns_left_then_right_with_full_width_separators(self) -> None:
        header = _block(50, 10, 550, 30, "header")
        footer = _block(50, 700, 550, 720, "footer")
        blocks = [
            _block(350, 200, 550, 220, "R2"),
            footer,
            _block(50, 100, 250, 120, "L1"),
            _block(350, 100, 550, 120, "R1"),
            header,
            _block(50, 200, 250, 220, "L2"),
        ]
        ordered = _order_blocks_reading_order(blocks, 600.0)
        assert [b[4] for b in ordered] == ["header", "L1", "L2", "R1", "R2", "footer"]

    def test_two_columns_with_trailing_band_after_last_separator(self) -> None:
        blocks = [
            _block(50, 100, 250, 120, "L1"),
            _block(350, 100, 550, 120, "R1"),
            _block(50, 200, 550, 220, "section title"),
            _block(50, 300, 250, 320, "L2"),
            _block(350, 300, 550, 320, "R2"),
            _block(50, 400, 250, 420, "L3"),
            _block(350, 400, 550, 420, "R3"),
        ]
        ordered = _order_blocks_reading_order(blocks, 600.0)
        assert [b[4] for b in ordered] == ["L1", "R1", "section title", "L2", "L3", "R2", "R3"]

    def test_mostly_full_width_blocks_are_not_two_columns(self) -> None:
        blocks = [
            _block(50, 100, 250, 120, "L1"),
            _block(350, 100, 550, 120, "R1"),
            _block(50, 200, 550, 220, "wide-a"),
            _block(50, 300, 550, 320, "wide-b"),
            _block(50, 400, 550, 420, "wide-c"),
        ]
        ordered = _order_blocks_reading_order(blocks, 600.0)
        assert [b[4] for b in ordered] == ["L1", "R1", "wide-a", "wide-b", "wide-c"]

    def test_empty_and_malformed_blocks_filtered_and_zero_width_page(self) -> None:
        blocks = [_block(0, 0, 10, 10, "   "), (1, 2, 3), _block(0, 5, 10, 10, "keep")]
        assert [b[4] for b in _order_blocks_reading_order(blocks, 600.0)] == ["keep"]
        # 页宽非法：保持输入顺序，不排序
        unsorted = [_block(0, 50, 10, 60, "b"), _block(0, 10, 10, 20, "a")]
        assert [b[4] for b in _order_blocks_reading_order(unsorted, 0.0)] == ["b", "a"]
        assert _order_blocks_reading_order([], 600.0) == []


class TestPageTextAndFontHelpers:
    def test_pymupdf_page_text_skips_non_text_blocks(self) -> None:
        page = SimpleNamespace(
            rect=SimpleNamespace(width=600.0),
            get_text=lambda _mode: [
                _block(50, 100, 500, 120, " first "),
                _block(50, 150, 500, 170, "<image>", kind=1),
                (50, 200, 500, 220, "legacy short tuple"),
                _block(50, 300, 500, 320, "second"),
            ],
        )
        assert _pymupdf_page_text(page) == "first\n\nlegacy short tuple\n\nsecond"

    def test_lacks_tounicode_variants(self) -> None:
        def make(fonts: list[tuple[Any, ...]], key: Any) -> tuple[Any, Any]:
            doc = SimpleNamespace(xref_get_key=key)
            page = SimpleNamespace(get_fonts=lambda full=True: fonts)
            return doc, page

        symbol_font = (7, "ttf", "TrueType", "ABCDEF+SymbolMT", "F1", "WinAnsi")
        normal_font = (8, "ttf", "TrueType", "ABCDEF+Arial", "F2", "WinAnsi")

        assert (
            _pymupdf_page_lacks_tounicode(*make([symbol_font], lambda x, k: ("null", "null")))
            is True
        )
        assert (
            _pymupdf_page_lacks_tounicode(*make([symbol_font], lambda x, k: ("xref", "9 0 R")))
            is False
        )
        assert (
            _pymupdf_page_lacks_tounicode(*make([normal_font], lambda x, k: ("null", "null")))
            is False
        )

        assert (
            _pymupdf_page_lacks_tounicode(
                *make(
                    [(10, "Type1", "Type1", "ABCDEF+CMMI10", "F3", "Custom")],
                    lambda x, k: ("null", "null"),
                )
            )
            is True
        )
        assert (
            _pymupdf_page_lacks_tounicode(
                *make(
                    [(11, "ttf", "TrueType", "CambriaMath", "F4", "Identity-H")],
                    lambda x, k: ("xref", "12 0 R"),
                )
            )
            is False
        )

        def raising(_xref: int, _key: str) -> Any:
            raise RuntimeError("bad xref")

        assert _pymupdf_page_lacks_tounicode(*make([symbol_font], raising)) is False

        def broken_get_fonts(full: bool = True) -> Any:
            raise RuntimeError("no fonts")

        doc = SimpleNamespace(xref_get_key=lambda x, k: ("null", "null"))
        assert (
            _pymupdf_page_lacks_tounicode(doc, SimpleNamespace(get_fonts=broken_get_fonts)) is False
        )

    def test_page_images_capped_at_three_and_tolerant(self) -> None:
        images = [(i,) for i in range(5)]
        doc = SimpleNamespace(extract_image=lambda xref: {"image": bytes([xref + 1])})
        page = SimpleNamespace(get_images=lambda full=True: images)
        assert _pymupdf_page_images(doc, page) == (b"\x01", b"\x02", b"\x03")

        doc_empty = SimpleNamespace(extract_image=lambda xref: {"image": b""})
        assert _pymupdf_page_images(doc_empty, page) == ()

        doc_non_dict = SimpleNamespace(extract_image=lambda xref: None)
        assert _pymupdf_page_images(doc_non_dict, page) == ()

        def explode(_xref: int) -> Any:
            raise RuntimeError("corrupt image")

        calls = {"n": 0}

        def flaky(xref: int) -> Any:
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("corrupt image")
            return {"image": b"ok"}

        assert _pymupdf_page_images(SimpleNamespace(extract_image=flaky), page) == (b"ok",)
        assert _pymupdf_page_images(SimpleNamespace(extract_image=explode), page) == ()


class _FakeDoc:
    def __init__(
        self, *, needs_pass: bool = False, page_count: int = 1, fail: bool = False
    ) -> None:
        self.needs_pass = needs_pass
        self.page_count = page_count
        self.fail = fail
        self.closed = False

    def load_page(self, _idx: int) -> Any:
        if self.fail:
            raise RuntimeError("page load failed")
        return SimpleNamespace(
            rect=SimpleNamespace(width=600.0),
            get_text=lambda _mode: [],
            get_fonts=lambda full=True: [],
            get_images=lambda full=True: [],
        )

    def close(self) -> None:
        self.closed = True


class TestExtractPagesWithPyMuPdfNoneContract:
    def _install(self, monkeypatch: pytest.MonkeyPatch, doc: _FakeDoc) -> None:
        stub = SimpleNamespace(
            TOOLS=SimpleNamespace(mupdf_display_errors=lambda _flag: None),
            open=lambda **_kwargs: doc,
        )
        monkeypatch.setattr(extractors, "_pymupdf", stub)

    def test_password_protected_returns_none_and_closes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        doc = _FakeDoc(needs_pass=True)
        self._install(monkeypatch, doc)
        assert _extract_pages_with_pymupdf(b"x") is None
        assert doc.closed is True

    def test_zero_pages_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._install(monkeypatch, _FakeDoc(page_count=0))
        assert _extract_pages_with_pymupdf(b"x") is None

    def test_page_exception_returns_none_and_closes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        doc = _FakeDoc(fail=True)
        self._install(monkeypatch, doc)
        assert _extract_pages_with_pymupdf(b"x") is None
        assert doc.closed is True

    def test_no_text_anywhere_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._install(monkeypatch, _FakeDoc(page_count=2))
        assert _extract_pages_with_pymupdf(b"x") is None

    def test_image_only_scanned_pdf_keeps_pymupdf_pages_for_vlm(self) -> None:
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_image(pymupdf.Rect(50, 50, 200, 200), stream=_tiny_png())
        pdf_bytes = doc.tobytes()
        doc.close()

        pages = extract_pdf_pages_with_diagnostics(pdf_bytes)
        assert len(pages) == 1
        assert pages[0].text == ""
        assert len(pages[0].embedded_images) == 1
        assert pages[0].embedded_images[0].startswith(b"\x89PNG")


class TestRenderPdfPagePng:
    def _pdf(self) -> bytes:
        return _build_pdf([[((72, 72), CLEAN_TEXT, "helv")], [((72, 72), CLEAN_TEXT, "helv")]])

    def test_renders_png_with_magic_bytes(self) -> None:
        png = render_pdf_page_png(self._pdf(), 1)
        assert png.startswith(b"\x89PNG\r\n\x1a\n")

    def test_dpi_affects_output_size(self) -> None:
        pdf = self._pdf()
        low = render_pdf_page_png(pdf, 1, dpi=72)
        high = render_pdf_page_png(pdf, 1, dpi=200)
        assert len(high) > len(low)

    def test_second_page_renders(self) -> None:
        assert render_pdf_page_png(self._pdf(), 2).startswith(b"\x89PNG")

    @pytest.mark.parametrize("page_number", [0, -1, 3, 99])
    def test_out_of_range_page_rejected(self, page_number: int) -> None:
        with pytest.raises(MaterialInvalidError, match="页码越界") as exc_info:
            render_pdf_page_png(self._pdf(), page_number)
        assert exc_info.value.details["page_count"] == 2

    def test_garbage_bytes_rejected(self) -> None:
        with pytest.raises(MaterialInvalidError, match="无法打开"):
            render_pdf_page_png(b"garbage bytes that are not a pdf", 1)

    def test_render_failure_is_wrapped_and_doc_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Doc:
            page_count = 1
            closed = False

            def load_page(self, _idx: int) -> Any:
                raise RuntimeError("renderer exploded")

            def close(self) -> None:
                _Doc.closed = True

        monkeypatch.setattr(extractors, "_pymupdf", SimpleNamespace(open=lambda **_kw: _Doc()))
        with pytest.raises(MaterialInvalidError, match="渲染失败") as exc_info:
            render_pdf_page_png(b"x", 1)
        assert exc_info.value.details["error"] == "RuntimeError"
        assert _Doc.closed is True


class TestNeedsVisualOcrGate:
    def test_short_heading_page_with_embedded_image_sets_needs_visual_ocr(self) -> None:
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Basic Concept", fontname="helv")
        page.insert_image(pymupdf.Rect(50, 120, 300, 320), stream=_tiny_png())
        pdf_bytes = doc.tobytes()
        doc.close()

        extracted = extract_pdf_pages_with_diagnostics(pdf_bytes)
        assert len(extracted) == 1
        assert extracted[0].needs_visual_ocr is True
        assert extracted[0].embedded_images

    def test_short_heading_page_with_complex_drawings_sets_needs_visual_ocr(self) -> None:
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Basic Concept", fontname="helv")
        for idx in range(10):
            page.draw_line((50, 120 + idx * 10), (250, 120 + idx * 10))
        pdf_bytes = doc.tobytes()
        doc.close()

        extracted = extract_pdf_pages_with_diagnostics(pdf_bytes)
        assert len(extracted) == 1
        assert extracted[0].needs_visual_ocr is True

    def test_dense_text_page_with_embedded_image_does_not_trigger_visual_ocr(self) -> None:
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), CLEAN_TEXT + " Extra prose words here.", fontname="helv")
        page.insert_image(pymupdf.Rect(50, 120, 150, 220), stream=_tiny_png())
        pdf_bytes = doc.tobytes()
        doc.close()

        extracted = extract_pdf_pages_with_diagnostics(pdf_bytes)
        assert len(extracted) == 1
        assert extracted[0].needs_visual_ocr is False


class TestRenderPdfPageImageJpegAndBatch:
    def test_render_pdf_page_image_jpeg_and_max_edge_scaling(self) -> None:
        from app.core.extractors import render_pdf_page_image, render_pdf_pages_batch

        doc = pymupdf.open()
        p1 = doc.new_page(width=1600, height=900)
        p1.insert_text((80, 80), "Wide Slide Page One", fontsize=18)
        p2 = doc.new_page(width=1600, height=900)
        p2.insert_text((80, 80), "Wide Slide Page Two", fontsize=18)
        pdf_bytes: bytes = doc.tobytes()
        doc.close()

        jpeg_bytes, mime = render_pdf_page_image(
            pdf_bytes, 1, dpi=200, image_format="jpeg", jpeg_quality=85, max_image_edge=1440
        )
        assert mime == "image/jpeg"
        assert jpeg_bytes.startswith(b"\xff\xd8\xff")
        pix = pymupdf.Pixmap(jpeg_bytes)
        assert max(pix.width, pix.height) <= 1440

        batch, batch_mime = render_pdf_pages_batch(
            pdf_bytes, [1, 2, 99], dpi=150, image_format="jpeg", max_image_edge=1440
        )
        assert batch_mime == "image/jpeg"
        assert set(batch.keys()) == {1, 2}
        assert all(val.startswith(b"\xff\xd8\xff") for val in batch.values())
