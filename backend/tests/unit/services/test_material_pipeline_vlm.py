"""``app.services._material_pipeline`` 的 VLM 混合路由与 Contextual Retrieval 单元测试。

全部离线、确定性：VLM/LLM/Embedding 均为进程内桩，PDF 字节在测试内用 PyMuPDF 现场生成。
"""

import base64
import re
import threading
import uuid
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

import pymupdf
import pytest
from pydantic import BaseModel

from app.core.algorithms.material_chunking import ParagraphInput
from app.core.algorithms.ocr_quality import sanitize_symbol_garble
from app.core.errors import MaterialInvalidError
from app.core.extractors import PdfPageExtraction, extract_pdf_pages_with_diagnostics
from app.integrations.embedding.protocol import EmbeddingOptions, EmbeddingProtocol
from app.integrations.llm.protocol import (
    LLMMessage,
    LLMOptions,
    LLMProtocol,
    LLMResponse,
    LLMUsage,
)
from app.models.material import MaterialSnippet
from app.services._material_pipeline import (
    build_contextual_snippet_text,
    prepare_material_snippets,
    repair_garbled_pdf_pages,
    transcribe_dirty_pages_with_vlm,
)

# PyMuPDF 仅提供部分类型标注，与 app/core/extractors.py 一致以 Any 访问。
_pymupdf: Any = pymupdf
T = TypeVar("T", bound=BaseModel)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_DATA_URI_PREFIX = "data:image/png;base64,"
_JPEG_DATA_URI_PREFIX = "data:image/jpeg;base64,"
_PAGE_NUMBER_RE = re.compile(r"第 (\d+) 页")

# 页面 -> VLM 行为：返回文本，或抛出异常。
VlmBehavior = Callable[[int], str]


def _make_pdf(page_count: int) -> bytes:
    """现场生成 ``page_count`` 页、每页带少量 ASCII 文本的最小 PDF。"""
    doc = _pymupdf.open()
    try:
        for idx in range(page_count):
            page = doc.new_page()
            page.insert_text((72, 72), f"Hello page {idx + 1}", fontsize=14)
        data: bytes = doc.tobytes()
        return data
    finally:
        doc.close()


def _page(
    page_number: int,
    text: str = "这是一段干净的正文内容。",
    *,
    garbled: bool = False,
) -> PdfPageExtraction:
    return PdfPageExtraction(
        page_number=page_number,
        text=text,
        lacks_tounicode_symbol_font=garbled,
        has_symbol_garble=garbled,
    )


class StubVLM(LLMProtocol):
    """记录每次调用并按页码返回预设行为的 VLM 桩（线程安全、可追踪并发峰值）。"""

    def __init__(
        self,
        behavior: VlmBehavior,
        *,
        barrier: threading.Barrier | None = None,
    ) -> None:
        self._behavior = behavior
        self._barrier = barrier
        self._lock = threading.Lock()
        self._in_flight = 0
        self.peak_in_flight = 0
        self.calls: list[tuple[Sequence[LLMMessage], LLMOptions | None]] = []

    def generate(
        self,
        messages: Sequence[LLMMessage],
        options: LLMOptions | None = None,
    ) -> LLMResponse:
        with self._lock:
            self._in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
            self.calls.append((messages, options))
        try:
            if self._barrier is not None:
                self._barrier.wait(timeout=5.0)
            match = _PAGE_NUMBER_RE.search(messages[-1].content)
            assert match is not None, "user prompt must mention the page number"
            content = self._behavior(int(match.group(1)))
            return LLMResponse(content=content, usage=LLMUsage(), model="stub-vlm")
        finally:
            with self._lock:
                self._in_flight -= 1

    def generate_structured(
        self,
        messages: Sequence[LLMMessage],
        response_model: type[T],
        options: LLMOptions | None = None,
    ) -> tuple[T, LLMResponse]:
        raise NotImplementedError

    @property
    def called_pages(self) -> set[int]:
        found: set[int] = set()
        for messages, _ in self.calls:
            match = _PAGE_NUMBER_RE.search(messages[-1].content)
            assert match is not None
            found.add(int(match.group(1)))
        return found


class StubTextLLM(LLMProtocol):
    """文本修复 LLM 桩：固定返回一段文本。"""

    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.call_count = 0

    def generate(
        self,
        messages: Sequence[LLMMessage],
        options: LLMOptions | None = None,
    ) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(content=self._reply, usage=LLMUsage(), model="stub-llm")

    def generate_structured(
        self,
        messages: Sequence[LLMMessage],
        response_model: type[T],
        options: LLMOptions | None = None,
    ) -> tuple[T, LLMResponse]:
        raise NotImplementedError


class RecordingEmbedding(EmbeddingProtocol):
    """记录所有被要求向量化的文本，并返回可由文本反推的确定性小向量。"""

    def __init__(self) -> None:
        self.document_batches: list[list[str]] = []
        self.query_texts: list[str] = []

    @staticmethod
    def vector_for(text: str) -> list[float]:
        return [float(len(text)), float(sum(map(ord, text)) % 997)]

    def embed_query(self, text: str, options: EmbeddingOptions | None = None) -> list[float]:
        self.query_texts.append(text)
        return self.vector_for(text)

    def embed_documents(
        self,
        texts: Sequence[str],
        options: EmbeddingOptions | None = None,
    ) -> list[list[float]]:
        self.document_batches.append(list(texts))
        return [self.vector_for(text) for text in texts]


def _repair(
    pages: Sequence[PdfPageExtraction],
    pdf_bytes: bytes,
    *,
    vlm: LLMProtocol | None,
    llm: LLMProtocol | None = None,
    vlm_max_concurrency: int = 3,
    vlm_image_format: str = "jpeg",
) -> tuple[list[ParagraphInput], str]:
    fmt: Any = vlm_image_format
    return repair_garbled_pdf_pages(
        pages,
        pdf_bytes,
        ocr=None,
        llm=llm,
        vlm=vlm,
        vlm_max_concurrency=vlm_max_concurrency,
        vlm_image_format=fmt,
    )


# --------------------------------------------------------------------------- #
# (a) repair_garbled_pdf_pages VLM 路由
# --------------------------------------------------------------------------- #


class TestVlmRouting:
    def test_clean_pages_never_call_vlm(self) -> None:
        pdf = _make_pdf(2)
        vlm = StubVLM(lambda _n: "SHOULD NOT BE USED")
        pages = [_page(1, "第一页干净正文。"), _page(2, "第二页干净正文。")]

        paragraphs, full_text = _repair(pages, pdf, vlm=vlm)

        assert vlm.calls == []
        assert [p.text for p in paragraphs] == ["第一页干净正文。", "第二页干净正文。"]
        assert full_text == "第一页干净正文。\n\n第二页干净正文。"

    def test_real_extracted_clean_pdf_never_calls_vlm(self) -> None:
        pdf = _make_pdf(2)
        pages = extract_pdf_pages_with_diagnostics(pdf)
        assert pages
        assert not any(p.needs_repair or not p.text.strip() for p in pages)
        vlm = StubVLM(lambda _n: "SHOULD NOT BE USED")

        paragraphs, _ = _repair(pages, pdf, vlm=vlm)

        assert vlm.calls == []
        assert paragraphs
        assert {p.page_number for p in paragraphs} == {p.page_number for p in pages}

    def test_dirty_and_empty_pages_called_with_png_data_uri(self) -> None:
        pdf = _make_pdf(3)
        vlm = StubVLM(lambda n: f"第{n}页转录结果")
        pages = [
            _page(1, "干净页"),
            _page(2, 'AB&A& "#$"$ 乱码', garbled=True),
            _page(3, ""),  # 无文字（扫描页）
        ]

        paragraphs, _ = _repair(pages, pdf, vlm=vlm)

        assert vlm.called_pages == {2, 3}
        assert len(vlm.calls) == 2
        for messages, options in vlm.calls:
            assert [m.role for m in messages] == ["system", "user"]
            assert "严禁" in messages[0].content
            assert messages[0].image_urls == ()
            urls = messages[1].image_urls
            assert len(urls) == 1
            assert urls[0].startswith(_JPEG_DATA_URI_PREFIX)
            decoded = base64.b64decode(urls[0][len(_JPEG_DATA_URI_PREFIX) :], validate=True)
            assert decoded.startswith(_JPEG_MAGIC)
            assert options is not None
            assert options.temperature == 0.0
        by_page = {p.page_number: p.text for p in paragraphs}
        assert by_page[1] == "干净页"
        assert by_page[2] == "第2页转录结果"
        assert by_page[3] == "第3页转录结果"

        # Explicit png image_format still produces PNG data URIs
        vlm_png = StubVLM(lambda n: f"第{n}页PNG")
        _repair([_page(2, "乱码", garbled=True)], pdf, vlm=vlm_png, vlm_image_format="png")
        png_url = vlm_png.calls[0][0][1].image_urls[0]
        assert png_url.startswith(_DATA_URI_PREFIX)
        assert base64.b64decode(png_url[len(_DATA_URI_PREFIX) :], validate=True).startswith(
            _PNG_MAGIC
        )

    def test_dpi_is_forwarded_to_render(self) -> None:
        pdf = _make_pdf(1)
        pages = [_page(1, "", garbled=False)]
        small = transcribe_dirty_pages_with_vlm(
            pages, pdf, StubVLM(lambda _n: "ok"), dpi=36, max_concurrency=1
        )
        assert small == {1: "ok"}

        sizes: list[int] = []
        for dpi in (36, 144):
            vlm = StubVLM(lambda _n: "ok")
            transcribe_dirty_pages_with_vlm(
                pages, pdf, vlm, dpi=dpi, max_concurrency=1, image_format="png"
            )
            url = vlm.calls[0][0][1].image_urls[0]
            sizes.append(len(base64.b64decode(url[len(_DATA_URI_PREFIX) :])))
        assert sizes[1] > sizes[0]

    def test_code_fenced_markdown_is_stripped(self) -> None:
        pdf = _make_pdf(1)
        vlm = StubVLM(lambda _n: "```markdown\n# 标题\n\n正文段落\n```")

        paragraphs, full_text = _repair([_page(1, "", garbled=True)], pdf, vlm=vlm)

        assert full_text == "# 标题\n\n正文段落"
        assert [p.text for p in paragraphs] == ["# 标题", "正文段落"]
        assert all("```" not in p.text for p in paragraphs)

    def test_vlm_exception_falls_back_to_text_without_failing_other_pages(self) -> None:
        pdf = _make_pdf(3)

        def behavior(page_number: int) -> str:
            if page_number == 2:
                raise RuntimeError("vlm down")
            return f"第{page_number}页VLM转录"

        vlm = StubVLM(behavior)
        garbled_text = "AB&A& 集合A与B的并集"
        pages = [
            _page(1, "", garbled=True),
            _page(2, garbled_text, garbled=True),
            _page(3, "", garbled=True),
        ]

        paragraphs, _ = _repair(pages, pdf, vlm=vlm)

        by_page = {p.page_number: p.text for p in paragraphs}
        assert by_page[1] == "第1页VLM转录"
        assert by_page[3] == "第3页VLM转录"
        assert by_page[2] == sanitize_symbol_garble(garbled_text)

    def test_vlm_exception_falls_back_to_text_llm_repair(self) -> None:
        pdf = _make_pdf(1)

        def behavior(_n: int) -> str:
            raise RuntimeError("vlm down")

        llm = StubTextLLM("修复后的干净文本")

        paragraphs, full_text = _repair(
            [_page(1, "AB&A& 乱码", garbled=True)], pdf, vlm=StubVLM(behavior), llm=llm
        )

        assert llm.call_count == 1
        assert full_text == "修复后的干净文本"
        assert [p.page_number for p in paragraphs] == [1]

    @pytest.mark.parametrize("reply", ["", "   \n  ", "```markdown\n\n```"])
    def test_vlm_empty_result_falls_back_to_sanitized_text(self, reply: str) -> None:
        pdf = _make_pdf(2)
        garbled_text = "AB&A& 集合A与B的交集"
        pages = [_page(1, garbled_text, garbled=True), _page(2, "第二页干净。")]
        vlm = StubVLM(lambda _n: reply)

        paragraphs, _ = _repair(pages, pdf, vlm=vlm)

        assert vlm.called_pages == {1}
        by_page = {p.page_number: p.text for p in paragraphs}
        assert by_page[1] == sanitize_symbol_garble(garbled_text)
        assert by_page[2] == "第二页干净。"

    def test_vlm_empty_on_blank_page_yields_no_paragraph(self) -> None:
        pdf = _make_pdf(2)
        pages = [_page(1, ""), _page(2, "第二页干净。")]

        paragraphs, full_text = _repair(pages, pdf, vlm=StubVLM(lambda _n: ""))

        assert [p.page_number for p in paragraphs] == [2]
        assert full_text == "第二页干净。"

    def test_render_failure_for_one_page_degrades_only_that_page(self) -> None:
        pdf = _make_pdf(1)  # 第 2 页不存在 -> 渲染越界
        vlm = StubVLM(lambda n: f"第{n}页VLM转录")
        pages = [_page(1, "", garbled=True), _page(2, "AB&A& 噪声", garbled=True)]

        paragraphs, _ = _repair(pages, pdf, vlm=vlm)

        assert vlm.called_pages == {1}
        by_page = {p.page_number: p.text for p in paragraphs}
        assert by_page[1] == "第1页VLM转录"
        assert by_page[2] == sanitize_symbol_garble("AB&A& 噪声")

    def test_without_vlm_uses_text_repair_only(self) -> None:
        pdf = _make_pdf(1)
        garbled_text = "AB&A& 集合A与B的并集"

        paragraphs, _ = _repair([_page(1, garbled_text, garbled=True)], pdf, vlm=None)

        assert [p.text for p in paragraphs] == [sanitize_symbol_garble(garbled_text)]

    def test_visual_ocr_page_with_short_heading_routes_to_vlm(self) -> None:
        pdf = _make_pdf(2)
        vlm = StubVLM(
            lambda n: f"## 基本概念\n\n第{n}页包含示意图的完整说明文字，阐述了线性降维的基本概念。"
        )
        visual_page = PdfPageExtraction(
            page_number=1,
            text="基本概念",
            lacks_tounicode_symbol_font=False,
            has_symbol_garble=False,
            needs_visual_ocr=True,
        )
        clean_page = _page(2, "第二页正常正文内容。")

        paragraphs, _ = _repair([visual_page, clean_page], pdf, vlm=vlm)

        assert vlm.called_pages == {1}
        assert paragraphs[0].text == "## 基本概念"
        assert paragraphs[0].is_title is True
        assert paragraphs[0].title_level == 2
        assert "示意图" in paragraphs[1].text

    def test_non_vlm_page_unwraps_hard_line_breaks_and_absorbs_short_heading(self) -> None:
        pdf = _make_pdf(2)
        pages = [
            _page(1, "基本概念"),
            _page(
                2,
                "降维的目的就是降低数据的维度\n从而方便后续对数据的存储、可\n视化、\n建模等操作。",
            ),
        ]

        paragraphs, _ = _repair(pages, pdf, vlm=None)

        expected_body = "降维的目的就是降低数据的维度从而方便后续对数据的存储、可视化、建模等操作。"
        assert paragraphs[0].text == "基本概念"
        assert paragraphs[0].is_title is True
        assert paragraphs[1].text == expected_body
        assert paragraphs[1].is_title is False

        snippets = prepare_material_snippets(
            embedding=RecordingEmbedding(),
            material_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            paragraphs=paragraphs,
        )
        assert len(snippets) == 1
        assert snippets[0].chapter_title == "基本概念"
        assert snippets[0].content == expected_body


class TestVlmConcurrency:
    def test_peak_in_flight_does_not_exceed_max_concurrency(self) -> None:
        pdf = _make_pdf(6)
        # 两两栅栏：既证明确有并行（>1），又保证确定性；超限则峰值断言失败。
        vlm = StubVLM(lambda n: f"第{n}页转录", barrier=threading.Barrier(2))
        pages = [_page(n, "", garbled=True) for n in range(1, 7)]

        paragraphs, _ = _repair(pages, pdf, vlm=vlm, vlm_max_concurrency=2)

        assert vlm.called_pages == set(range(1, 7))
        assert 1 < vlm.peak_in_flight <= 2
        assert [p.page_number for p in paragraphs] == [1, 2, 3, 4, 5, 6]

    def test_default_concurrency_runs_pages_in_parallel(self) -> None:
        pdf = _make_pdf(3)
        vlm = StubVLM(lambda n: f"第{n}页转录", barrier=threading.Barrier(3))
        pages = [_page(n, "", garbled=True) for n in range(1, 4)]

        result = transcribe_dirty_pages_with_vlm(pages, pdf, vlm)

        assert result == {1: "第1页转录", 2: "第2页转录", 3: "第3页转录"}
        assert vlm.peak_in_flight == 3

    def test_concurrency_one_is_serial(self) -> None:
        pdf = _make_pdf(4)
        vlm = StubVLM(lambda n: f"第{n}页转录")
        pages = [_page(n, "", garbled=True) for n in range(1, 5)]

        result = transcribe_dirty_pages_with_vlm(pages, pdf, vlm, max_concurrency=1)

        assert len(result) == 4
        assert vlm.peak_in_flight == 1

    def test_non_positive_concurrency_is_clamped_to_one(self) -> None:
        pdf = _make_pdf(2)
        vlm = StubVLM(lambda n: f"第{n}页转录")
        pages = [_page(n, "", garbled=True) for n in range(1, 3)]

        result = transcribe_dirty_pages_with_vlm(pages, pdf, vlm, max_concurrency=0)

        assert len(result) == 2
        assert vlm.peak_in_flight == 1

    def test_no_dirty_pages_returns_empty_without_calls(self) -> None:
        pdf = _make_pdf(1)
        vlm = StubVLM(lambda _n: "x")

        assert transcribe_dirty_pages_with_vlm([_page(1)], pdf, vlm) == {}
        assert vlm.calls == []


class TestVlmParagraphProvenance:
    def test_paragraphs_keep_page_number_and_source_ref(self) -> None:
        pdf = _make_pdf(3)
        vlm = StubVLM(lambda n: f"# 标题{n}\n\n正文{n}")
        pages = [
            _page(1, "第一页干净。"),
            _page(2, "", garbled=True),
            _page(3, "第三页干净。"),
        ]

        paragraphs, full_text = _repair(pages, pdf, vlm=vlm)

        triples = [(p.page_number, p.source_ref, p.text) for p in paragraphs]
        assert triples == [
            (1, "第 1 页", "第一页干净。"),
            (2, "第 2 页", "# 标题2"),
            (2, "第 2 页", "正文2"),
            (3, "第 3 页", "第三页干净。"),
        ]
        assert all(p.doc_type == "pdf" for p in paragraphs)
        assert full_text == "第一页干净。\n\n# 标题2\n\n正文2\n\n第三页干净。"

    def test_multiline_display_math_block_stays_one_paragraph(self) -> None:
        pdf = _make_pdf(1)
        transcript = (
            "矩阵如下：\n\n"
            "$$\n\\begin{pmatrix}\n1 & 0 \\\\\n0 & 1\n\\end{pmatrix}\n$$\n\n"
            "以上为单位矩阵。"
        )
        vlm = StubVLM(lambda _n: transcript)

        paragraphs, _ = _repair([_page(1, "", garbled=True)], pdf, vlm=vlm)

        assert len(paragraphs) == 3
        math_blocks = [p for p in paragraphs if p.text.startswith("$$")]
        assert len(math_blocks) == 1
        block = math_blocks[0]
        assert block.text.endswith("$$")
        assert "\\begin{pmatrix}" in block.text
        assert "\\end{pmatrix}" in block.text
        assert block.text.count("\n") >= 4
        assert (block.page_number, block.source_ref) == (1, "第 1 页")
        assert paragraphs[0].text == "矩阵如下："
        assert paragraphs[2].text == "以上为单位矩阵。"


# --------------------------------------------------------------------------- #
# (b) build_contextual_snippet_text
# --------------------------------------------------------------------------- #


class TestBuildContextualSnippetText:
    def test_chapter_and_ref_are_combined(self) -> None:
        assert (
            build_contextual_snippet_text(
                chapter_title="第一章 集合", source_ref="第 3 页", content="正文"
            )
            == "[第一章 集合 · 第 3 页]\n正文"
        )

    @pytest.mark.parametrize("generic_ref", ["段落", " 段落 ", "\t段落\n"])
    def test_generic_ref_is_dropped(self, generic_ref: str) -> None:
        assert (
            build_contextual_snippet_text(
                chapter_title="第一章 集合", source_ref=generic_ref, content="正文"
            )
            == "[第一章 集合]\n正文"
        )

    def test_ref_only_when_chapter_empty(self) -> None:
        assert (
            build_contextual_snippet_text(chapter_title="", source_ref="第 7 页", content="正文")
            == "[第 7 页]\n正文"
        )

    def test_parts_are_stripped(self) -> None:
        assert (
            build_contextual_snippet_text(
                chapter_title="  第二章  ", source_ref="  第 1 页 ", content="正文"
            )
            == "[第二章 · 第 1 页]\n正文"
        )

    @pytest.mark.parametrize(
        ("chapter", "ref"),
        [("", ""), ("", "段落"), ("   ", " 段落 "), ("  ", "   ")],
    )
    def test_no_label_returns_content_only(self, chapter: str, ref: str) -> None:
        assert (
            build_contextual_snippet_text(chapter_title=chapter, source_ref=ref, content="正文内容")
            == "正文内容"
        )


# --------------------------------------------------------------------------- #
# (c) prepare_material_snippets: 嵌入文本带上下文，落库 content 保持干净
# --------------------------------------------------------------------------- #


_BODY = "集合是具有某种共同性质的对象的全体，集合中的每个对象称为该集合的元素。" * 6


class TestPrepareMaterialSnippets:
    def _prepare(
        self,
        embedding: EmbeddingProtocol,
        paragraphs: Sequence[str | ParagraphInput],
    ) -> list[MaterialSnippet]:
        return prepare_material_snippets(
            embedding=embedding,
            material_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            paragraphs=paragraphs,
        )

    def test_embeds_contextual_text_but_content_stays_clean(self) -> None:
        embedding = RecordingEmbedding()
        paragraphs = [
            ParagraphInput(text="第一章 集合", is_title=True, doc_type="pdf", page_number=1),
            ParagraphInput(text=_BODY, source_ref="第 2 页", doc_type="pdf", page_number=2),
        ]

        snippets = self._prepare(embedding, paragraphs)

        assert len(embedding.document_batches) == 1
        embedded = embedding.document_batches[0]
        assert len(embedded) == len(snippets) >= 1
        for snippet, text in zip(snippets, embedded, strict=True):
            assert text == f"[第一章 集合 · 第 2 页]\n{snippet.content}"
            assert snippet.content in text
            assert not snippet.content.startswith("[")
            assert "第一章 集合 · 第 2 页" not in snippet.content
            assert snippet.chapter_title == "第一章 集合"
            assert snippet.source_info == {"source_ref": "第 2 页", "page_number": 2}
            assert snippet.char_length == len(snippet.content)
            assert snippet.embedding is not None
            assert list(snippet.embedding) == RecordingEmbedding.vector_for(text)
        assert embedding.query_texts == []

    def test_plain_string_paragraphs_embed_content_only(self) -> None:
        embedding = RecordingEmbedding()

        snippets = self._prepare(embedding, [_BODY])

        assert len(snippets) >= 1
        embedded = embedding.document_batches[0]
        for snippet, text in zip(snippets, embedded, strict=True):
            assert text == snippet.content  # 无章节 + 通用 '段落' 来源 -> 无前缀
            assert snippet.chapter_title == ""
            assert snippet.source_info == {"source_ref": "段落"}

    def test_empty_input_raises_when_required(self) -> None:
        embedding = RecordingEmbedding()

        with pytest.raises(MaterialInvalidError):
            self._prepare(embedding, ["   "])

        assert embedding.document_batches == []

    def test_prepare_persists_page_end_for_merged_same_chapter_slides(self) -> None:
        embedding = RecordingEmbedding()
        paragraphs = [
            ParagraphInput(text="第五章 软间隔", is_title=True, doc_type="pptx", page_number=11),
            ParagraphInput(
                text="软间隔允许少量训练样本落入间隔带中并通过松弛变量度量其损失。",
                source_ref="第 12 页",
                doc_type="pptx",
                page_number=12,
            ),
            ParagraphInput(
                text="惩罚系数 $C>0$ 控制分类准确率与最大几何间隔之间的平衡。",
                source_ref="第 13 页",
                doc_type="pptx",
                page_number=13,
            ),
        ]
        snippets = self._prepare(embedding, paragraphs)
        assert len(snippets) == 1
        assert snippets[0].source_info == {
            "source_ref": "第 12-13 页",
            "page_number": 12,
            "page_end": 13,
        }


class TestDenoisingAndRenderedOcrFallback:
    def test_repair_strips_watermarks_drops_toc_and_thank_you_pages(self) -> None:
        from app.core.algorithms.document_denoising import PageTextBlock

        pdf = _make_pdf(5)
        wm = PageTextBlock("福建師範大學\nFUJIAN NORMAL UNIVERSITY", 40, 520, 400, 580, 800, 600)
        pages = [
            PdfPageExtraction(
                1,
                "第五章 支持向量机\n主讲教师：王老师\n福建師範大學\nFUJIAN NORMAL UNIVERSITY",
                False,
                False,
                blocks=(wm,),
            ),
            PdfPageExtraction(
                2,
                "二、线性可分支持向量机\n福建師範大學",
                False,
                False,
                blocks=(wm,),
            ),
            PdfPageExtraction(
                3,
                (
                    "线性可分支持向量机通过最大化几何间隔构建最优分离超平面，"
                    "并由支持向量决定决策边界。\n"
                    "福建師範大學\n"
                    "FUJIAN NORMAL UNIVERSITY"
                ),
                False,
                False,
                blocks=(wm,),
            ),
            PdfPageExtraction(
                4,
                "小结\n1. 基本概念\n2. 线性可分\n3. 软间隔\n福建師範大學",
                False,
                False,
                blocks=(wm,),
            ),
            PdfPageExtraction(
                5,
                "谢谢！\n福建師範大學\nFUJIAN NORMAL UNIVERSITY",
                False,
                False,
                blocks=(wm,),
            ),
        ]
        paragraphs, full_text = _repair(pages, pdf, vlm=None)
        assert "福建師範大學" not in full_text
        assert "FUJIAN NORMAL UNIVERSITY" not in full_text
        assert "谢谢" not in full_text
        assert "小结" not in full_text
        assert [p.text for p in paragraphs] == [
            "二、线性可分支持向量机",
            "线性可分支持向量机通过最大化几何间隔构建最优分离超平面，并由支持向量决定决策边界。",
        ]
        assert paragraphs[0].is_title is True
        assert paragraphs[1].is_title is False

    def test_dirty_page_without_vlm_renders_png_for_ocr_fallback(self) -> None:
        from app.integrations.ocr.protocol import OCRProtocol, OCRResult, OCRTextBlock

        class _ImageOnlyOCR(OCRProtocol):
            def __init__(self) -> None:
                self.image_calls = 0

            def recognize_image(self, image_bytes: bytes) -> OCRResult:
                self.image_calls += 1
                assert image_bytes.startswith(_PNG_MAGIC)
                text = "目标函数为 $\\min \\frac{1}{2}\\|w\\|^2 + C \\sum_{i=1}^n \\xi_i$。"
                return OCRResult(full_text=text, blocks=(OCRTextBlock(text=text, confidence=0.95),))

        pdf = _make_pdf(1)
        ocr = _ImageOnlyOCR()
        dirty = PdfPageExtraction(
            page_number=1,
            text="目标函数：min 1/2 ||w||^2 + C ☒ ξ_i",
            lacks_tounicode_symbol_font=False,
            has_symbol_garble=True,
            suspicious_fragments=("C ☒ ξ",),
        )
        paragraphs, full_text = repair_garbled_pdf_pages(
            [dirty],
            pdf,
            ocr=ocr,
            llm=None,
            vlm=None,
        )
        assert ocr.image_calls == 1
        assert "\\sum_{i=1}^n" in full_text
        assert "☒" not in full_text
        assert len(paragraphs) == 1

    def test_denoise_pptx_slides_filters_template_slides(self) -> None:
        from app.services._material_pipeline import denoise_pptx_slides

        raw = [
            ParagraphInput(
                "机器学习\n主讲人：李老师", "第 1 页", "pptx", is_title=True, page_number=1
            ),
            ParagraphInput("目录", "第 2 页", "pptx", is_title=True, page_number=2),
            ParagraphInput(
                "1. 概念\n2. 推导\n3. 总结", "第 2 页", "pptx", is_title=False, page_number=2
            ),
            ParagraphInput("核心定理", "第 3 页", "pptx", is_title=True, page_number=3),
            ParagraphInput(
                "拉格朗日对偶将原始带约束凸优化转化为对偶变量的无约束最大化问题，满足 KKT 条件。",
                "第 3 页",
                "pptx",
                is_title=False,
                page_number=3,
            ),
            ParagraphInput("谢谢！", "第 4 页", "pptx", is_title=False, page_number=4),
        ]
        denoised, text = denoise_pptx_slides(raw)
        assert "谢谢" not in text
        assert "目录" not in text
        assert [(p.page_number, p.is_title, p.text) for p in denoised] == [
            (3, True, "核心定理"),
            (
                3,
                False,
                "拉格朗日对偶将原始带约束凸优化转化为对偶变量的无约束最大化问题，满足 KKT 条件。",
            ),
        ]


class TestPaddleOcrVlProtocolAndResilience:
    def test_openai_adapter_image_first_serialization(self) -> None:
        from unittest.mock import MagicMock

        from app.integrations.llm.openai import OpenAICompatibleLLMAdapter

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "OCR text"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        client = MagicMock()
        client.post.return_value = resp
        adapter = OpenAICompatibleLLMAdapter(
            api_key="sk-test", model="PaddlePaddle/PaddleOCR-VL-1.5", client=client
        )
        adapter.generate(
            [
                LLMMessage(
                    role="user",
                    content="OCR:",
                    image_urls=("data:image/jpeg;base64,AAAA",),
                    image_first=True,
                )
            ]
        )
        sent = client.post.call_args.kwargs["json"]["messages"]
        assert sent == [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}},
                    {"type": "text", "text": "OCR:"},
                ],
            }
        ]

    def test_paddleocr_vl_auto_style_sends_single_image_first_user_message(self) -> None:
        pdf = _make_pdf(1)

        class _PaddleStubVLM(LLMProtocol):
            def __init__(self) -> None:
                self.model = "PaddlePaddle/PaddleOCR-VL-1.5"
                self.calls: list[Sequence[LLMMessage]] = []

            def generate(
                self,
                messages: Sequence[LLMMessage],
                options: LLMOptions | None = None,
            ) -> LLMResponse:
                self.calls.append(messages)
                return LLMResponse(
                    content="$$\\frac{|\\omega^T x_i + b|}{\\|\\omega\\|}$$",
                    usage=LLMUsage(),
                    model=self.model,
                )

            def generate_structured(
                self,
                messages: Sequence[LLMMessage],
                response_model: type[T],
                options: LLMOptions | None = None,
            ) -> tuple[T, LLMResponse]:
                raise NotImplementedError

        vlm = _PaddleStubVLM()
        out = transcribe_dirty_pages_with_vlm(
            [PdfPageExtraction(1, "ω^T x_i + b", False, False, has_math_expression_layout=True)],
            pdf,
            vlm,
            prompt_style="auto",
        )
        assert 1 in out
        assert len(vlm.calls) == 1
        msgs = vlm.calls[0]
        assert len(msgs) == 1
        assert msgs[0].role == "user"
        assert msgs[0].content == "OCR:"
        assert msgs[0].image_first is True
        assert msgs[0].image_urls[0].startswith(_JPEG_DATA_URI_PREFIX)

    def test_skips_clean_cover_toc_and_thank_you_pages_in_vlm_routing(self) -> None:
        from app.services._material_pipeline import _page_needs_vlm

        cover = PdfPageExtraction(
            1,
            "第五章 支持向量机\n主讲教师：王老师",
            False,
            False,
            needs_visual_ocr=True,
            is_slide_layout=True,
        )
        toc = PdfPageExtraction(
            2,
            "目录\n1. 基本概念\n2. 硬间隔\n3. 核函数",
            False,
            False,
            needs_visual_ocr=True,
            is_slide_layout=True,
        )
        math_slide = PdfPageExtraction(
            3,
            "几何间隔\nω^T x_i + b\n||ω||",
            False,
            False,
            is_slide_layout=True,
            has_math_expression_layout=True,
        )
        thanks = PdfPageExtraction(
            4,
            "谢谢！",
            False,
            False,
            needs_visual_ocr=True,
            has_formula_visual_risk=True,
            is_slide_layout=True,
        )
        assert _page_needs_vlm(cover, total_pages=4) is False
        assert _page_needs_vlm(toc, total_pages=4) is False
        assert _page_needs_vlm(math_slide, total_pages=4) is True
        assert _page_needs_vlm(thanks, total_pages=4) is False

    def test_vlm_circuit_breaker_trips_after_three_consecutive_timeouts(self) -> None:
        pdf = _make_pdf(8)
        attempted_pages: list[int] = []

        class _TimeoutVLM(LLMProtocol):
            def generate(
                self,
                messages: Sequence[LLMMessage],
                options: LLMOptions | None = None,
            ) -> LLMResponse:
                match = _PAGE_NUMBER_RE.search(messages[-1].content)
                if match:
                    attempted_pages.append(int(match.group(1)))
                raise TimeoutError("SiliconFlow PaddleOCR-VL ReadTimeout")

            def generate_structured(
                self,
                messages: Sequence[LLMMessage],
                response_model: type[T],
                options: LLMOptions | None = None,
            ) -> tuple[T, LLMResponse]:
                raise NotImplementedError

        pages = [_page(n, "", garbled=True) for n in range(1, 9)]
        # max_concurrency=1 -> batch_size=2; trips after 3rd timeout, skipping pages 5-8
        result = transcribe_dirty_pages_with_vlm(
            pages, pdf, _TimeoutVLM(), max_concurrency=1, max_pages_per_doc=40
        )
        assert result == {}
        assert len(attempted_pages) <= 4
        assert set(attempted_pages).isdisjoint({5, 6, 7, 8})

    def test_max_pages_per_doc_caps_dirty_vlm_calls(self) -> None:
        pdf = _make_pdf(6)
        vlm = StubVLM(lambda n: f"第{n}页转录")
        pages = [_page(n, "", garbled=True) for n in range(1, 7)]
        result = transcribe_dirty_pages_with_vlm(
            pages, pdf, vlm, max_concurrency=2, max_pages_per_doc=3
        )
        assert len(result) == 3
        assert len(vlm.called_pages) == 3


class TestHeadingFixAndSemanticChunkerIntegration:
    def test_is_heading_block_rejects_math_expressions_and_mid_page_prose(self) -> None:
        from app.services._material_pipeline import is_heading_block

        for bad in (
            "ω^T x_i + b",
            "-ω^T x_i + b",
            "||ω||",
            "# ω^T x_i + b",
            "y_i (w^T x_i + b) >= 1",
            "f(x) = a + b",
        ):
            assert is_heading_block(bad) is False
            assert is_heading_block(bad, y_ratio=0.05) is False

        assert is_heading_block("# 标题") is True
        assert is_heading_block("## 支持向量机 (SVM)") is True
        assert is_heading_block("3.2 线性可分支持向量机") is True
        assert is_heading_block("第五章 核方法") is True
        assert is_heading_block("基本概念", y_ratio=0.12) is True
        assert is_heading_block("基本概念", y_ratio=0.55) is False

    def test_semantic_chunker_repairs_broken_2d_math_and_falls_back_per_batch(self) -> None:
        from app.core.algorithms.semantic_chunking import SemanticPageInput
        from app.integrations.llm.fake import FakeLLMAdapter
        from app.services._semantic_chunker import (
            PageAnnotationSchema,
            SemanticBatchAnnotationResponse,
            chunk_pages_semantically,
        )

        pages = [
            SemanticPageInput(page_number=1, text="封面：机器学习讲义"),
            SemanticPageInput(page_number=2, text="几何间隔基础定义与超平面说明。"),
            SemanticPageInput(
                page_number=3,
                text="点到超平面距离公式：\n\n|ω^T x_i + b|\n\n||ω||",
                used_vlm=False,
            ),
            SemanticPageInput(page_number=4, text="下一批页面一：核函数引入。"),
            SemanticPageInput(page_number=5, text="下一批页面二：常用高斯核。"),
        ]
        fallback_paras = [
            ParagraphInput(p.text, f"第 {p.page_number} 页", "pdf", page_number=p.page_number)
            for p in pages
        ]

        # Bypassed for FakeLLMAdapter or <3 pages or disabled
        assert (
            chunk_pages_semantically(
                pages=pages, fallback_paragraphs=fallback_paras, llm=FakeLLMAdapter()
            )
            is None
        )
        assert (
            chunk_pages_semantically(
                pages=pages[:2], fallback_paragraphs=fallback_paras[:2], llm=StubTextLLM("x")
            )
            is None
        )
        assert (
            chunk_pages_semantically(
                pages=pages,
                fallback_paragraphs=fallback_paras,
                llm=StubTextLLM("x"),
                enabled=False,
            )
            is None
        )

        class _PartialFailingSemanticLLM(LLMProtocol):
            def __init__(self) -> None:
                self.batch_calls = 0

            def generate(
                self,
                messages: Sequence[LLMMessage],
                options: LLMOptions | None = None,
            ) -> LLMResponse:
                raise NotImplementedError

            def generate_structured(
                self,
                messages: Sequence[LLMMessage],
                response_model: type[T],
                options: LLMOptions | None = None,
            ) -> tuple[T, LLMResponse]:
                self.batch_calls += 1
                if "[PAGE 4" in messages[-1].content:
                    raise TimeoutError("batch 2 timeout")
                data = SemanticBatchAnnotationResponse(
                    pages=[
                        PageAnnotationSchema(
                            page_number=1, topic_title="封面", is_substantive=False
                        ),
                        PageAnnotationSchema(
                            page_number=2,
                            topic_title="几何间隔",
                            is_substantive=True,
                            merge_with_prev=False,
                        ),
                        PageAnnotationSchema(
                            page_number=3,
                            topic_title="几何间隔",
                            is_substantive=True,
                            merge_with_prev=True,
                            needs_formula_repair=True,
                            repaired_markdown=(
                                "点到超平面距离公式为 "
                                "$$d = \\frac{|\\omega^T x_i + b|}{\\|\\omega\\|}$$。"
                            ),
                        ),
                    ]
                )
                return data, LLMResponse(content="ok", usage=LLMUsage(), model="deepseek-flash")  # type: ignore[return-value]

        outcome = chunk_pages_semantically(
            pages=pages,
            fallback_paragraphs=fallback_paras,
            llm=_PartialFailingSemanticLLM(),
            batch_max_pages=3,
        )
        assert outcome is not None
        snippets = outcome.chunk_result.snippets
        assert len(snippets) == 3
        assert snippets[0].chapter_title == "几何间隔"
        assert snippets[0].page_number == 2
        assert snippets[0].page_end == 3
        assert snippets[0].source_ref == "第 2-3 页"
        assert "$$d = \\frac{|\\omega^T x_i + b|}{\\|\\omega\\|}$$" in snippets[0].content
        assert 3 in outcome.repaired_page_texts
        # Batch 2 fell back deterministically and survived
        assert [s.page_number for s in snippets[1:]] == [4, 5]

    def test_deepseek_ocr_auto_prompt_style_image_first_and_drops_tiny_junk(self) -> None:
        pdf = _make_pdf(2)
        captured: list[list[LLMMessage]] = []

        class _DeepSeekOCRStub(LLMProtocol):
            model = "deepseek-ai/DeepSeek-OCR"

            def generate(
                self,
                messages: Sequence[LLMMessage],
                options: LLMOptions | None = None,
            ) -> LLMResponse:
                captured.append(list(messages))
                content = "}" if len(captured) == 1 else "Distance $r_i = |w^T x_i + b|/\\|w\\|$"
                return LLMResponse(content=content, usage=LLMUsage(), model=self.model)

            def generate_structured(
                self,
                messages: Sequence[LLMMessage],
                response_model: type[T],
                options: LLMOptions | None = None,
            ) -> tuple[T, LLMResponse]:
                raise NotImplementedError

        pages = [_page(1, "", garbled=True), _page(2, "", garbled=True)]
        result = transcribe_dirty_pages_with_vlm(
            pages, pdf, _DeepSeekOCRStub(), max_concurrency=1, prompt_style="auto"
        )
        assert len(captured) == 2
        for msgs in captured:
            assert len(msgs) == 1
            assert msgs[0].role == "user"
            assert msgs[0].image_first is True
            assert "Markdown" in msgs[0].content
        # 1-char degenerate '}' on page 1 must be discarded; page 2 survives
        assert 1 not in result
        assert 2 in result and "$r_i" in result[2]

    def test_semantic_chunker_runs_batches_concurrently_and_preserves_order(self) -> None:
        from app.core.algorithms.semantic_chunking import SemanticPageInput
        from app.services._semantic_chunker import (
            PageAnnotationSchema,
            SemanticBatchAnnotationResponse,
            chunk_pages_semantically,
        )

        pages = [
            SemanticPageInput(
                page_number=n, text=f"第{n}页关于支持向量机推导的实质内容说明。", used_vlm=True
            )
            for n in range(1, 7)
        ]
        fallback_paras = [
            ParagraphInput(
                text=p.text, source_ref=f"第 {p.page_number} 页", page_number=p.page_number
            )
            for p in pages
        ]
        barrier = threading.Barrier(2)

        class _ConcurrentSemanticLLM(LLMProtocol):
            def generate(
                self,
                messages: Sequence[LLMMessage],
                options: LLMOptions | None = None,
            ) -> LLMResponse:
                raise NotImplementedError

            def generate_structured(
                self,
                messages: Sequence[LLMMessage],
                response_model: type[T],
                options: LLMOptions | None = None,
            ) -> tuple[T, LLMResponse]:
                barrier.wait(timeout=5.0)
                prompt = messages[-1].content
                batch_pages = [1, 2, 3] if "[PAGE 1" in prompt else [4, 5, 6]
                topic = "线性可分" if batch_pages[0] == 1 else "核技巧"
                data = SemanticBatchAnnotationResponse(
                    pages=[
                        PageAnnotationSchema(
                            page_number=p,
                            topic_title=topic,
                            is_substantive=True,
                            merge_with_prev=(p != batch_pages[0]),
                        )
                        for p in batch_pages
                    ]
                )
                return data, LLMResponse(content="ok", usage=LLMUsage(), model="deepseek-flash")  # type: ignore[return-value]

        outcome = chunk_pages_semantically(
            pages=pages,
            fallback_paragraphs=fallback_paras,
            llm=_ConcurrentSemanticLLM(),
            batch_max_pages=3,
            max_concurrency=3,
        )
        assert outcome is not None
        snippets = outcome.chunk_result.snippets
        assert len(snippets) == 2
        assert snippets[0].chapter_title == "线性可分"
        assert snippets[0].page_number == 1 and snippets[0].page_end == 3
        assert snippets[1].chapter_title == "核技巧"
        assert snippets[1].page_number == 4 and snippets[1].page_end == 6
