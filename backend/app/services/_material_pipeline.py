"""Internal pipeline helpers and typed view models for MaterialService."""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.algorithms.material_chunking import (
    ParagraphInput,
    split_material_into_snippets,
)
from app.core.algorithms.ocr_quality import (
    OCRPageInput,
    detect_symbol_garble,
    sanitize_symbol_garble,
    verify_ocr_quality,
)
from app.core.errors import MaterialInvalidError
from app.core.extractors import PdfPageExtraction
from app.integrations.embedding.protocol import EmbeddingProtocol
from app.integrations.llm.protocol import LLMMessage, LLMOptions, LLMProtocol
from app.integrations.ocr.protocol import OCRProtocol
from app.integrations.storage.protocol import StorageProtocol
from app.models.material import (
    Material,
    MaterialOCRPage,
    MaterialSnippet,
    MaterialStatus,
    ParseStatus,
)
from app.repositories.material import MaterialRepository


@dataclass(frozen=True)
class MaterialDetailView:
    """资料详情与列表解析进度的强类型只读视图，替代 ORM 实例动态挂载属性。"""

    material: Material
    parse_status: str | None = None
    progress_percentage: int | None = None
    key_points_count: int | None = None
    page_count: int | None = None

    @property
    def id(self) -> uuid.UUID:
        return self.material.id

    @property
    def user_id(self) -> uuid.UUID:
        return self.material.user_id

    @property
    def title(self) -> str:
        return self.material.title

    @property
    def file_format(self) -> str:
        return self.material.file_format

    @property
    def file_size(self) -> int:
        return self.material.file_size

    @property
    def source_type(self) -> str:
        return self.material.source_type

    @property
    def status(self) -> str:
        return self.material.status

    @property
    def current_version_id(self) -> uuid.UUID | None:
        return self.material.current_version_id

    @property
    def folder_id(self) -> uuid.UUID | None:
        return self.material.folder_id

    @property
    def is_deleted(self) -> bool:
        return self.material.is_deleted

    @property
    def created_at(self) -> Any:
        return self.material.created_at

    @property
    def updated_at(self) -> Any:
        return self.material.updated_at

    @property
    def versions(self) -> list[Any]:
        return list(self.material.versions or [])

    @property
    def versions_count(self) -> int:
        return len(self.material.versions or [])

    def __getattr__(self, name: str) -> Any:
        return getattr(self.material, name)


def process_initial_ocr_page(
    *,
    storage: StorageProtocol,
    ocr: OCRProtocol,
    bucket: str,
    user_id: uuid.UUID,
    material_id: uuid.UUID,
    version_id: uuid.UUID,
    version_number: int,
    clean_format: str,
    file_bytes: bytes,
) -> tuple[MaterialOCRPage, bool, str | None]:
    """执行首轮图片 OCR 识别、质量门禁校验与页面对象上传。"""
    ocr_result = ocr.recognize_image(file_bytes)
    page_input = OCRPageInput(page_number=1, raw_text=ocr_result.full_text, reshoot_count=0)
    report = verify_ocr_quality([page_input])
    page_report = report.page_results[0]

    page_storage_key = f"users/{user_id}/materials/{material_id}/v{version_number}/pages/page_1.png"
    storage.put_object(bucket, page_storage_key, file_bytes, f"image/{clean_format}")

    ocr_page = MaterialOCRPage(
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        page_number=1,
        image_storage_key=page_storage_key,
        raw_text=ocr_result.full_text,
        gibberish_ratio=page_report.gibberish_ratio,
        valid_char_count=page_report.valid_char_count,
        is_qualified=page_report.is_qualified,
        unqualified_reason=page_report.unqualified_reason,
        reshoot_count=0,
    )
    return ocr_page, report.is_all_qualified, page_report.unqualified_reason


_GARBLE_REPAIR_SYSTEM_PROMPT: str = (
    "你是学术文档公式与符号乱码修复器。"
    "输入是从 PDF（含缺失 ToUnicode 映射的 Symbol 字体）抽取的单页文本，"
    '其中部分希腊字母、集合运算或数学符号退化为 ASCII 乱码（如 AB&A&、"#$"$、!" ! #）。\n'
    "【严格约束】:\n"
    "1. 清除无法辨认的纯乱码噪声字符，并依据前后句意与可选 OCR 识别参考，"
    "将能够确定的数学表达式或符号恢复为规范可读文本或 `$LaTeX$` 公式；\n"
    "2. 严禁凭空扩写、总结或编造原文没有出现的概念、定理、结论或数值；\n"
    "3. 保持正常段落文本与结构不变，直接输出修复后的纯文本，不要添加额外解释或标题。"
)

_pipeline_logger = logging.getLogger(__name__)


def _try_ocr_pdf_page(
    page: PdfPageExtraction,
    pdf_bytes: bytes,
    ocr: OCRProtocol | None,
) -> str:
    """当 PDF 页面存在乱码时尝试利用内嵌页面图像或适配器的 PDF OCR 能力提取辅助文本。"""
    if ocr is None:
        return ""
    texts: list[str] = []
    for img_bytes in page.embedded_images[:2]:
        try:
            res = ocr.recognize_image(img_bytes)
            if res.full_text and res.full_text.strip():
                texts.append(res.full_text.strip())
        except Exception as exc:
            _pipeline_logger.warning("pdf embedded image OCR degraded: %s", exc)
    if texts:
        return "\n".join(texts)

    recognize_pdf_page = getattr(ocr, "recognize_pdf_page", None)
    if callable(recognize_pdf_page):
        try:
            res = recognize_pdf_page(pdf_bytes, page_number=page.page_number)
            full_text = getattr(res, "full_text", "")
            if isinstance(full_text, str) and full_text.strip():
                return full_text.strip()
        except Exception as exc:
            _pipeline_logger.warning("pdf page OCR degraded: %s", exc)
    return ""


def _repair_pdf_page_text(
    page: PdfPageExtraction,
    pdf_bytes: bytes,
    ocr: OCRProtocol | None,
    llm: LLMProtocol | None,
) -> str:
    """对标记为符号字体乱码/缺失 ToUnicode 的单页 PDF 文本执行 OCR+LLM 定向修复。"""
    if not page.needs_repair and page.text.strip():
        return page.text

    ocr_hint = _try_ocr_pdf_page(page, pdf_bytes, ocr)
    base_text = page.text.strip()
    if not page.needs_repair:
        return ocr_hint or base_text

    still_garbled_ocr = False
    if ocr_hint:
        still_garbled_ocr, _, _ = detect_symbol_garble(ocr_hint)
        if not still_garbled_ocr and (not base_text or page.has_symbol_garble) and llm is None:
            return ocr_hint

    if llm is not None and (base_text or ocr_hint):
        user_parts = [f"【原始抽取文本（第 {page.page_number} 页）】:\n{base_text or '(空)'}"]
        if ocr_hint:
            user_parts.append(f"【OCR 识别辅助参考】:\n{ocr_hint}")
        if page.suspicious_fragments:
            user_parts.append(f"【疑似乱码片段】: {' | '.join(page.suspicious_fragments[:5])}")
        try:
            resp = llm.generate(
                messages=[
                    LLMMessage(role="system", content=_GARBLE_REPAIR_SYSTEM_PROMPT),
                    LLMMessage(role="user", content="\n\n".join(user_parts)),
                ],
                options=LLMOptions(temperature=0.1),
            )
            repaired = resp.content.strip() if resp and resp.content else ""
            if repaired:
                still_bad, _, _ = detect_symbol_garble(repaired)
                return sanitize_symbol_garble(repaired) if still_bad else repaired
        except Exception as exc:
            _pipeline_logger.warning("pdf garble LLM repair degraded: %s", exc)

    if ocr_hint and not still_garbled_ocr:
        return ocr_hint
    return sanitize_symbol_garble(ocr_hint or base_text)


def repair_garbled_pdf_pages(
    pages: Sequence[PdfPageExtraction],
    pdf_bytes: bytes,
    *,
    ocr: OCRProtocol | None,
    llm: LLMProtocol | None,
) -> tuple[list[ParagraphInput], str]:
    """逐页检测修复 PDF 符号乱码，产出保留页码溯源的段落列表与合并全文。"""
    paragraphs: list[ParagraphInput] = []
    page_texts: list[str] = []
    for page in pages:
        repaired_text = _repair_pdf_page_text(page, pdf_bytes, ocr, llm).strip()
        if not repaired_text:
            continue
        page_texts.append(repaired_text)
        chunks = (
            repaired_text.split("\n\n") if "\n\n" in repaired_text else repaired_text.split("\n")
        )
        for para in chunks:
            stripped = para.strip()
            if stripped:
                paragraphs.append(
                    ParagraphInput(
                        text=stripped,
                        source_ref=f"第 {page.page_number} 页",
                        doc_type="pdf",
                        page_number=page.page_number,
                    )
                )
    return paragraphs, "\n\n".join(page_texts)


def chunk_embed_and_replace_snippets(
    *,
    repo: MaterialRepository,
    embedding: EmbeddingProtocol,
    material_id: uuid.UUID,
    version_id: uuid.UUID,
    user_id: uuid.UUID,
    paragraphs: Sequence[str | ParagraphInput],
    require_non_empty: bool = True,
) -> None:
    """将文本段落切分为知识片段、批量向量化并幂等替换旧版本切片。"""
    chunk_result = split_material_into_snippets(paragraphs)
    if require_non_empty and not chunk_result.snippets:
        raise MaterialInvalidError("资料有效内容不足，未切分出有效知识片段")

    snippet_texts = [snip.content for snip in chunk_result.snippets]
    vectors = embedding.embed_documents(snippet_texts)
    snippets_to_save = []
    for i, snip in enumerate(chunk_result.snippets):
        info: dict[str, Any] = {"source_ref": snip.source_ref}
        if snip.page_number is not None:
            info["page_number"] = snip.page_number
        snippets_to_save.append(
            MaterialSnippet(
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                snippet_index=snip.index,
                content=snip.content,
                char_length=snip.char_count,
                start_offset=snip.start_offset,
                end_offset=snip.end_offset,
                chapter_title=snip.chapter_title,
                source_info=info,
                embedding=vectors[i] if i < len(vectors) else None,
            )
        )
    repo.delete_snippets_by_version(version_id, user_id)
    repo.create_snippets(snippets_to_save)


def mark_pipeline_failed(
    *,
    repo: MaterialRepository,
    session: Session,
    material_id: uuid.UUID,
    version_id: uuid.UUID,
    user_id: uuid.UUID,
    failed_stage: str,
    exc: Exception,
) -> None:
    """回滚当前事务并将资料与版本状态原子置为 FAILED。"""
    session.rollback()
    try:
        error_msg = getattr(exc, "message", str(exc))
        repo.update_version_status(
            version_id=version_id,
            user_id=user_id,
            status=ParseStatus.FAILED.value,
            failed_stage=failed_stage,
            error_message=str(error_msg)[:500],
        )
        repo.update_material_status(
            material_id=material_id,
            user_id=user_id,
            status=MaterialStatus.FAILED.value,
        )
        session.commit()
    except Exception:
        session.rollback()


__all__ = [
    "MaterialDetailView",
    "chunk_embed_and_replace_snippets",
    "mark_pipeline_failed",
    "process_initial_ocr_page",
    "repair_garbled_pdf_pages",
]
