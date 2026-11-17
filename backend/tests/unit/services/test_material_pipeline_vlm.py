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
_DATA_URI_PREFIX = "data:image/png;base64,"
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
) -> tuple[list[ParagraphInput], str]:
    return repair_garbled_pdf_pages(
        pages,
        pdf_bytes,
        ocr=None,
        llm=llm,
        vlm=vlm,
        vlm_max_concurrency=vlm_max_concurrency,
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
            assert urls[0].startswith(_DATA_URI_PREFIX)
            decoded = base64.b64decode(urls[0][len(_DATA_URI_PREFIX) :], validate=True)
            assert decoded.startswith(_PNG_MAGIC)
            assert options is not None
            assert options.temperature == 0.0
        by_page = {p.page_number: p.text for p in paragraphs}
        assert by_page[1] == "干净页"
        assert by_page[2] == "第2页转录结果"
        assert by_page[3] == "第3页转录结果"

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
            transcribe_dirty_pages_with_vlm(pages, pdf, vlm, dpi=dpi, max_concurrency=1)
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
