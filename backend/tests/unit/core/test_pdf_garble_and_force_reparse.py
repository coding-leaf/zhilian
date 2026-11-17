"""Unit tests for PDF symbol garble detection/repair, pseudo-bullet cleanup, and force re-parse."""

import io
import uuid
from collections.abc import Generator, Sequence
from typing import TypeVar
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps.auth import get_current_user
from app.api.deps.material import get_material_service
from app.api.v1 import api_v1_router
from app.core.algorithms.material_chunking import clean_pseudo_bullet_glyphs
from app.core.algorithms.ocr_quality import detect_symbol_garble, sanitize_symbol_garble
from app.core.extractors import PdfPageExtraction, extract_pdf_pages_with_diagnostics
from app.integrations.embedding.fake import FakeEmbeddingAdapter
from app.integrations.idempotency.memory import MemoryIdempotencyAdapter
from app.integrations.llm.protocol import (
    LLMMessage,
    LLMOptions,
    LLMProtocol,
    LLMResponse,
    LLMUsage,
)
from app.integrations.ocr.fake import FakeOCRAdapter
from app.integrations.ocr.protocol import OCRResult, OCRTextBlock
from app.integrations.queue.memory import MemoryQueueAdapter
from app.integrations.storage.memory import MemoryStorageAdapter
from app.models.base import Base
from app.models.knowledge import KnowledgePoint
from app.models.material import MaterialSnippet, MaterialStatus, ParseStatus
from app.models.user import User
from app.services._material_pipeline import repair_garbled_pdf_pages
from app.services.material import MaterialService

T = TypeVar("T", bound=BaseModel)


class _RepairStubLLM(LLMProtocol):
    def __init__(self, repaired_text: str = "", *, should_fail: bool = False) -> None:
        self.repaired_text = repaired_text
        self.should_fail = should_fail
        self.calls: list[list[LLMMessage]] = []

    def generate(
        self,
        messages: Sequence[LLMMessage],
        options: LLMOptions | None = None,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        if self.should_fail:
            raise RuntimeError("llm unavailable")
        return LLMResponse(content=self.repaired_text, model="stub", usage=LLMUsage())

    def generate_structured(
        self,
        messages: Sequence[LLMMessage],
        response_model: type[T],
        options: LLMOptions | None = None,
    ) -> tuple[T, LLMResponse]:
        raise NotImplementedError


def _make_symbolmt_pdf_bytes() -> bytes:
    """Create a valid minimal 1-page PDF whose Font dict uses SymbolMT without /ToUnicode."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    symbol_font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/SymbolMT"),
        }
    )
    fonts = DictionaryObject({NameObject("/F1"): writer._add_object(symbol_font)})
    resources = DictionaryObject({NameObject("/Font"): fonts})
    page[NameObject("/Resources")] = resources
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 100 Td (Linear system AB&A& equation) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


def test_detect_symbol_garble_catches_noise_clusters_and_ignores_valid_latex_and_md() -> None:
    """detect_symbol_garble flags symbol-garbled math runs while preserving valid LaTeX & MD."""
    garbled = '若条件成立，则向量满足 AB&A& 且矩阵 "#$"$ 与 !" ! #\n!@#$%^&*'
    has_garble, _ratio, fragments = detect_symbol_garble(garbled)
    assert has_garble is True
    assert len(fragments) >= 1

    sanitized = sanitize_symbol_garble(garbled)
    assert "AB&A&" not in sanitized
    assert '"#$"$' not in sanitized

    clean_latex_and_md = (
        "### 定理一\n"
        "**核心性质**：设向量满足 $x^2 + y^2 = r^2$，能量关系式为 $$E = mc^2$$。\n"
        "参考链接 https://example.com/docs?a=1&b=2\n"
        "| 变量 | 含义 |\n|---|---|\n| $x$ | 自变量 |\n"
    )
    clean_flagged, _clean_ratio, clean_frags = detect_symbol_garble(clean_latex_and_md)
    assert clean_flagged is False
    assert clean_frags == ()


def test_clean_pseudo_bullet_glyphs_normalizes_wingdings_prefixes() -> None:
    """Wingdings l / n / ü and private-use bullet glyphs convert cleanly to Markdown list items."""
    raw = "l 第一条定义\nn 第二条性质\nü 第三条结论\n\uf0b7 第四条补充\n普通正文行"
    cleaned = clean_pseudo_bullet_glyphs(raw)
    lines = cleaned.splitlines()
    assert lines[0] == "- 第一条定义"
    assert lines[1] == "- 第二条性质"
    assert lines[2] == "- 第三条结论"
    assert lines[3] == "- 第四条补充"
    assert lines[4] == "普通正文行"


def test_extract_pdf_pages_with_diagnostics_flags_symbol_font_without_tounicode() -> None:
    """PDF page referencing SymbolMT without /ToUnicode is flagged for repair."""
    pdf_bytes = _make_symbolmt_pdf_bytes()
    pages = extract_pdf_pages_with_diagnostics(pdf_bytes)
    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert pages[0].lacks_tounicode_symbol_font is True
    assert pages[0].needs_repair is True


def test_repair_garbled_pdf_pages_uses_llm_repair_and_sanitizes_on_failure() -> None:
    """repair_garbled_pdf_pages invokes zero-fabrication LLM prompt and falls back cleanly."""
    pages = [
        PdfPageExtraction(
            page_number=1,
            text='线性方程组 AX = b 的解满足 AB&A& 且 "#$"$ 约束。',
            lacks_tounicode_symbol_font=True,
            has_symbol_garble=True,
            suspicious_fragments=("AB&A&", '"#$"$'),
        )
    ]
    llm = _RepairStubLLM("线性方程组 $AX = b$ 的解满足 $A^T A$ 约束。")
    paragraphs, merged = repair_garbled_pdf_pages(pages, b"", ocr=None, llm=llm)
    assert len(llm.calls) == 1
    assert "严禁" in llm.calls[0][0].content
    assert "$A^T A$" in merged
    assert len(paragraphs) == 1
    assert paragraphs[0].page_number == 1

    # Fallback when LLM errors
    failing_llm = _RepairStubLLM(should_fail=True)
    _, fallback_merged = repair_garbled_pdf_pages(pages, b"", ocr=None, llm=failing_llm)
    assert "AB&A&" not in fallback_merged
    assert '"#$"$' not in fallback_merged
    assert "线性方程组" in fallback_merged


def test_force_reparse_cleans_stale_kps_and_snippets_on_ready_material(session: Session) -> None:
    """parse_material_pipeline(..., force=True) replaces stale KPs/snippets on READY materials."""
    storage = MemoryStorageAdapter()
    storage.ensure_bucket_exists("zhilian-materials")
    ocr_text = "微积分基本定理揭示定积分与原函数之间的关系。"
    ocr = FakeOCRAdapter(
        default_result=OCRResult(
            full_text=ocr_text,
            blocks=(OCRTextBlock(text=ocr_text, confidence=0.98),),
        )
    )
    service = MaterialService(
        session=session,
        storage_adapter=storage,
        ocr_adapter=ocr,
        embedding_adapter=FakeEmbeddingAdapter(),
        queue_adapter=MemoryQueueAdapter(),
        idempotency_adapter=MemoryIdempotencyAdapter(),
    )

    user_id = uuid.uuid4()
    initial_md = b"# Title\n\nOld garbled AB&A& content line for first parse version." * 3
    material, version = service.create_material(
        user_id=user_id,
        title="微积分讲义.md",
        file_format="md",
        file_size=len(initial_md),
        file_content=initial_md,
    )
    service.parse_material_pipeline(material_id=material.id, version_id=version.id, user_id=user_id)
    stale_kp = KnowledgePoint(
        user_id=user_id,
        material_id=material.id,
        version_id=version.id,
        name="陈旧乱码知识点",
        description="stale",
        batch_id="old",
    )
    session.add(stale_kp)
    session.commit()

    # Replace stored content to verify force=True actually re-reads and re-extracts
    fresh_md = b"# Fresh\n\nClean integral calculus theorem and continuous function properties." * 3
    storage.put_object(
        "zhilian-materials", version.storage_key, fresh_md, content_type="text/markdown"
    )

    # Without force=True, already-READY version returns early keeping stale KP
    service.parse_material_pipeline(
        material_id=material.id, version_id=version.id, user_id=user_id, force=False
    )
    assert session.query(KnowledgePoint).filter_by(version_id=version.id).count() == 1

    # With force=True, stale KPs & snippets are removed and new snippets persisted
    service.parse_material_pipeline(
        material_id=material.id, version_id=version.id, user_id=user_id, force=True
    )
    assert session.query(KnowledgePoint).filter_by(version_id=version.id).count() == 0
    fresh_snippets = session.query(MaterialSnippet).filter_by(version_id=version.id).all()
    assert len(fresh_snippets) >= 1
    assert any("Clean integral calculus theorem" in s.content for s in fresh_snippets)
    assert version.parse_status == ParseStatus.READY.value
    assert material.status == MaterialStatus.READY.value


@pytest.mark.asyncio
async def test_parse_material_route_passes_force_query_flag() -> None:
    """POST /api/v1/materials/{material_id}/parse?force=true forwards force=True to service."""
    app = FastAPI()
    app.include_router(api_v1_router)
    user = User(id=uuid.uuid4(), nickname="tester", is_active=True, token_version=1)
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()

    mock_service = MagicMock()
    mock_service.trigger_parse.return_value = SimpleParseStub(material_id, version_id)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_material_service] = lambda: mock_service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/materials/{material_id}/parse?force=true",
            json={"version_id": str(version_id), "sync": True},
        )

    assert resp.status_code == 200
    mock_service.trigger_parse.assert_called_once_with(
        material_id=material_id,
        user_id=user.id,
        version_id=version_id,
        sync=True,
        force=True,
    )


class SimpleParseStub:
    """Minimal MaterialVersion-like return stub matching MaterialParseResponse."""

    def __init__(self, material_id: uuid.UUID, version_id: uuid.UUID) -> None:
        self.id = version_id
        self.version_id = version_id
        self.material_id = material_id
        self.parse_status = ParseStatus.READY.value
        self.is_active = True
        self.failed_stage = None
        self.error_message = None
        self.progress_percentage = 100
