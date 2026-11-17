"""Internal pipeline helpers and typed view models for MaterialService."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.algorithms.material_chunking import split_material_into_snippets
from app.core.algorithms.ocr_quality import OCRPageInput, verify_ocr_quality
from app.core.errors import MaterialInvalidError
from app.integrations.embedding.protocol import EmbeddingProtocol
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


def chunk_embed_and_replace_snippets(
    *,
    repo: MaterialRepository,
    embedding: EmbeddingProtocol,
    material_id: uuid.UUID,
    version_id: uuid.UUID,
    user_id: uuid.UUID,
    paragraphs: list[str],
    require_non_empty: bool = True,
) -> None:
    """将文本段落切分为知识片段、批量向量化并幂等替换旧版本切片。"""
    chunk_result = split_material_into_snippets(paragraphs)
    if require_non_empty and not chunk_result.snippets:
        raise MaterialInvalidError("资料有效内容不足，未切分出有效知识片段")

    snippet_texts = [snip.content for snip in chunk_result.snippets]
    vectors = embedding.embed_documents(snippet_texts)
    snippets_to_save = [
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
            source_info={"source_ref": snip.source_ref},
            embedding=vectors[i] if i < len(vectors) else None,
        )
        for i, snip in enumerate(chunk_result.snippets)
    ]
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
]
