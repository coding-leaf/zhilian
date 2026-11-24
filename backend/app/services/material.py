"""学习资料领域服务编排模块。

统领事务边界并跨外设（Storage, OCR, Embedding, Queue, Idempotency）
与纯函数计算核调度。
严格遵循 AGENTS.md 规范：
- app/services 是全系统唯一允许开启数据库事务的层；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)；
- 结构化脱敏日志 8 要素输出，严禁向日志记录资料全文或敏感密钥。
"""

import contextlib
import hashlib
import logging
import uuid
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.services.knowledge import KnowledgeService

from app.core.algorithms.ocr_quality import (
    OCRPageInput,
    verify_ocr_quality,
)
from app.core.errors import (
    EmbeddingAuthError,
    EmbeddingError,
    EmbeddingTimeoutError,
    FolderNotFoundError,
    LLMAuthError,
    LLMError,
    LLMResponseFormatError,
    LLMTimeoutError,
    MaterialInvalidError,
    MaterialNotFoundError,
    OCRAuthError,
    OCRError,
    OCRQuotaError,
    OCRTimeoutError,
    QueueTimeoutError,
    ReshootLimitExceededError,
    StorageConnectionError,
)
from app.core.extractors import (
    MAGIC_NUMBERS as MAGIC_NUMBERS,
)
from app.core.extractors import (
    _extract_paragraphs_from_docx as _extract_paragraphs_from_docx,
)
from app.core.extractors import (
    _extract_paragraphs_from_pptx as _extract_paragraphs_from_pptx,
)
from app.core.extractors import (
    _extract_text_from_pdf as _extract_text_from_pdf,
)
from app.core.extractors import (
    extract_pdf_pages_with_diagnostics,
    extract_pptx_slides,
)
from app.core.extractors import (
    extract_text_from_raw_content as extract_text_from_raw_content,
)
from app.core.extractors import (
    validate_file_magic as validate_file_magic,
)
from app.core.idempotency import validate_idempotency_key
from app.core.security import generate_user_ref
from app.integrations.embedding.protocol import EmbeddingProtocol
from app.integrations.idempotency.protocol import IdempotencyProtocol
from app.integrations.llm.protocol import LLMProtocol
from app.integrations.ocr.protocol import OCRProtocol
from app.integrations.queue.protocol import QueueProtocol
from app.integrations.storage.protocol import StorageProtocol
from app.models.material import (
    Material,
    MaterialOCRPage,
    MaterialStatus,
    MaterialVersion,
    ParseStatus,
    SourceType,
)
from app.repositories.folder import FolderRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.material import MaterialRepository
from app.services._material_pipeline import (
    ACTIVE_PARSE_STATUSES,
    MaterialDetailView,
    chunk_embed_and_replace_snippets,
    clear_cached_parse_progress,
    denoise_pptx_slides,
    get_cached_parse_progress,
    get_cached_parse_progress_batch,
    mark_pipeline_failed,
    prepare_material_snippets,
    process_initial_ocr_page,
    repair_garbled_pdf_pages,
    resolve_progress_redis_client,
    set_cached_parse_progress,
)

logger = logging.getLogger(__name__)

STALE_PARSE_TIMEOUT: timedelta = timedelta(minutes=20)
ORPHAN_QUEUED_GRACE_PERIOD: timedelta = timedelta(seconds=30)

# 依据：系统架构设计文档与 NFR 规定，单文件最大字节数限制
MAX_FILE_SIZES: dict[str, int] = {
    "pdf": 20 * 1024 * 1024,
    "docx": 20 * 1024 * 1024,
    "pptx": 20 * 1024 * 1024,
    "png": 10 * 1024 * 1024,
    "jpg": 10 * 1024 * 1024,
    "jpeg": 10 * 1024 * 1024,
    "txt": 5 * 1024 * 1024,
    "md": 5 * 1024 * 1024,
}

# 依据：MinIO 对象存储多租户隔离默认存储桶名称
DEFAULT_MATERIAL_BUCKET: str = "zhilian-materials"


def build_material_storage_key(
    user_id: uuid.UUID,
    material_id: uuid.UUID,
    version_number: int,
    content_hash: str,
    ext: str,
) -> str:
    """确定性生成多租户对象存储 Key 路径。

    Args:
        user_id: 租户用户主键。
        material_id: 资料实体主键。
        version_number: 递增版本号。
        content_hash: SHA-256 摘要。
        ext: 文件扩展名。

    Returns:
        str: 规整的存储对象键路径。
    """
    clean_ext = ext.lower().lstrip(".")
    return (
        f"users/{user_id}/materials/{material_id}/v{version_number}/{content_hash[:16]}.{clean_ext}"
    )


class MaterialService:
    """学习资料领域服务编排。

    全系统唯一允许开启数据库事务的层，负责编排各外设与纯函数计算核。
    """

    def __init__(
        self,
        session: Session,
        storage_adapter: StorageProtocol,
        ocr_adapter: OCRProtocol,
        embedding_adapter: EmbeddingProtocol,
        queue_adapter: QueueProtocol,
        idempotency_adapter: IdempotencyProtocol | None = None,
        material_repo: MaterialRepository | None = None,
        knowledge_service: "KnowledgeService | None" = None,
        folder_repo: FolderRepository | None = None,
        llm_adapter: LLMProtocol | None = None,
        bucket: str = DEFAULT_MATERIAL_BUCKET,
        vlm_adapter: LLMProtocol | None = None,
        vlm_dpi: int = 150,
        vlm_max_concurrency: int = 3,
        vlm_timeout: float = 45.0,
    ) -> None:
        self.session = session
        self.storage = storage_adapter
        self.ocr = ocr_adapter
        self.embedding = embedding_adapter
        self.queue = queue_adapter
        self.idempotency = idempotency_adapter
        self.repo = material_repo or MaterialRepository(session)
        self.folder_repo = folder_repo or FolderRepository(session)
        self.knowledge_repo = KnowledgeRepository(session)
        self.knowledge_service = knowledge_service
        self.llm = llm_adapter
        self.vlm = vlm_adapter
        self.vlm_dpi = vlm_dpi
        self.vlm_max_concurrency = vlm_max_concurrency
        self.vlm_timeout = vlm_timeout
        self.bucket = bucket
        self._progress_redis = resolve_progress_redis_client(queue_adapter, idempotency_adapter)

    def create_material(
        self,
        *,
        user_id: uuid.UUID,
        title: str,
        file_format: str,
        file_size: int,
        file_content: bytes,
        source_type: str = SourceType.LOCAL.value,
        idempotency_key: str | None = None,
        folder_id: uuid.UUID | None = None,
    ) -> tuple[Material, MaterialVersion]:
        """上传创建资料：校验文件并持久化独占对象与待解析版本。

        Args:
            user_id: 所属用户标识。
            title: 资料展示标题。
            file_format: 格式扩展名。
            file_size: 文件大小（字节）。
            file_content: 原文件二进制字节流。
            source_type: 导入渠道来源。
            idempotency_key: 可选的幂等键。
            folder_id: 可选归属课程文件夹标识（None=未分类）。

        Returns:
            tuple[Material, MaterialVersion]: 创建（或复用）的资料与版本实体元组。

        Raises:
            MaterialInvalidError: 文件内容为空、大小超限、魔数校验失败。
            FolderNotFoundError: 指定课程文件夹不存在、已归档或越权。
            IdempotencyConflictError: 幂等并发重复提交。
        """
        user_ref = generate_user_ref(user_id)
        clean_format = file_format.lower().lstrip(".")

        if folder_id is not None:
            folder = self.folder_repo.get_by_id(folder_id, user_id, include_archived=False)
            if folder is None:
                raise FolderNotFoundError("目标课程文件夹不存在或无权访问")

        # 1. 幂等拦截检查与回放
        if idempotency_key is not None and self.idempotency is not None:
            normalized_key = validate_idempotency_key(idempotency_key)
            cached_result = self.idempotency.get_result(normalized_key, str(user_id))
            if cached_result is not None:
                cached_material_id = uuid.UUID(cached_result["material_id"])
                cached_version_id = uuid.UUID(cached_result["version_id"])
                cached_mat = self.repo.get_material_by_id(cached_material_id, user_id)
                cached_ver = self.repo.get_version_by_id(cached_version_id, user_id)
                if cached_mat is not None and cached_ver is not None:
                    return cached_mat, cached_ver

            self.idempotency.acquire_lock(normalized_key, str(user_id))

        # 2. 基础合法性与大小门禁校验
        if not file_content or len(file_content) == 0:
            raise MaterialInvalidError(
                "学习资料内容不能为空",
                details={"file_size": file_size},
            )

        max_allowed_size = MAX_FILE_SIZES.get(clean_format)
        if max_allowed_size is None:
            raise MaterialInvalidError(
                f"不支持的文件格式: '{clean_format}'",
                details={"supported_formats": list(MAX_FILE_SIZES.keys())},
            )

        if len(file_content) > max_allowed_size:
            raise MaterialInvalidError(
                f"文件大小超出限制 (当前: {len(file_content)} 字节, 最大: {max_allowed_size} 字节)",
                details={"actual_size": len(file_content), "max_size": max_allowed_size},
            )

        # 3. 魔数纯函数校验
        if not validate_file_magic(file_content, clean_format):
            raise MaterialInvalidError(
                f"文件内容魔数与声明格式 '{clean_format}' 不匹配",
                details={"declared_format": clean_format},
            )

        content_hash = hashlib.sha256(file_content).hexdigest()

        # 4. 释放前置只读事务后先上传对象存储，再开启短事务写库（避免 S3 I/O 占用 DB 连接）
        if not self.session.new and not self.session.dirty and not self.session.deleted:
            self.session.rollback()

        # 内容哈希仅用于记录与去重语义，物理对象必须为本资料独占副本。
        # 禁止复用其它资料的 storage_key：否则源资料硬删会连带 purge 本资料对象。
        storage_object_id = uuid.uuid4()
        storage_key = build_material_storage_key(
            user_id, storage_object_id, 1, content_hash, clean_format
        )
        uploaded_to_storage = False
        try:
            self.storage.put_object(
                bucket=self.bucket,
                key=storage_key,
                data=file_content,
                content_type=f"application/{clean_format}",
            )
            uploaded_to_storage = True

            material = self.repo.create_material(
                user_id=user_id,
                title=title,
                file_format=clean_format,
                file_size=len(file_content),
                source_type=source_type,
                status=MaterialStatus.PENDING.value,
                folder_id=folder_id,
            )

            version = self.repo.create_version(
                material_id=material.id,
                user_id=user_id,
                version_number=1,
                storage_key=storage_key,
                content_hash=content_hash,
                parse_status=ParseStatus.NOT_STARTED.value,
            )

            self.session.commit()

            # 5. 持久化幂等完成快照；解析只由用户显式触发。
            if idempotency_key is not None and self.idempotency is not None:
                self.idempotency.set_result(
                    key=idempotency_key,
                    user_id=str(user_id),
                    response_data={
                        "material_id": str(material.id),
                        "version_id": str(version.id),
                    },
                )

            logger.info(
                "material created",
                extra={
                    "user_ref": user_ref,
                    "target_id": str(material.id),
                    "error_code": 0,
                },
            )
            return material, version

        except Exception:
            self.session.rollback()
            if uploaded_to_storage:
                with contextlib.suppress(Exception):
                    self.storage.delete_object(self.bucket, storage_key)
            if idempotency_key is not None and self.idempotency is not None:
                self.idempotency.release_lock(idempotency_key, str(user_id))
            raise

    def import_material_file(
        self,
        *,
        user_id: uuid.UUID,
        file_content: bytes,
        filename: str | None = None,
        title: str | None = None,
        source_type: str = SourceType.LOCAL.value,
        idempotency_key: str | None = None,
        folder_id: uuid.UUID | None = None,
    ) -> tuple[Material, MaterialVersion]:
        """上传导入资料文件高阶入口。

        清洗提取标题并推断文件扩展名，调用 create_material 执行完整魔数校验、查重与持久化。

        Args:
            user_id: 租户用户主键。
            file_content: 原始文件二进制内容。
            filename: 上传的文件名（用于推导扩展名与清洗默认标题）。
            title: 用户显式传入的自定义标题（可选）。
            source_type: 导入渠道来源（local/wechat）。
            idempotency_key: 幂等键（可选）。
            folder_id: 可选归属课程文件夹标识（None=未分类）。

        Returns:
            tuple[Material, MaterialVersion]: 创建（或复用）的资料与版本实体。
        """
        file_format = ""
        if filename and "." in filename:
            file_format = filename.rsplit(".", 1)[-1].lower()

        resolved_title = title
        if not resolved_title or not resolved_title.strip():
            resolved_title = filename.strip() if filename else ""
            if not resolved_title:
                resolved_title = "未命名资料"

        return self.create_material(
            user_id=user_id,
            title=resolved_title,
            file_format=file_format,
            file_size=len(file_content),
            file_content=file_content,
            source_type=source_type,
            idempotency_key=idempotency_key,
            folder_id=folder_id,
        )

    def _extract_source_content(
        self,
        *,
        material_id: uuid.UUID,
        version: MaterialVersion,
        user_id: uuid.UUID,
        clean_format: str,
        file_bytes: bytes,
    ) -> tuple[Any, str, MaterialVersion | None]:
        """抽取图片 OCR 或文档正文；图片未达标门禁时返回待重拍版本。"""
        if clean_format in ("png", "jpg", "jpeg", "image"):
            ocr_page, is_all_qualified, unqualified_reason = process_initial_ocr_page(
                storage=self.storage,
                ocr=self.ocr,
                bucket=self.bucket,
                user_id=user_id,
                material_id=material_id,
                version_id=version.id,
                version_number=version.version_number,
                clean_format=clean_format,
                file_bytes=file_bytes,
            )
            self.repo.delete_ocr_pages_by_version(version.id, user_id)
            self.repo.create_ocr_pages([ocr_page])

            if not is_all_qualified:
                self.repo.update_version_status(
                    version.id,
                    user_id,
                    ParseStatus.FAILED.value,
                    error_message=unqualified_reason,
                    failed_stage="ocr_quality_gate",
                )
                # 质检未达标并非终态失败，而是进入「待重拍」链路供逐页重拍修复
                self.repo.update_material_status(
                    material_id, user_id, MaterialStatus.RETAKE_REQUIRED.value
                )
                self.session.commit()
                clear_cached_parse_progress(version.id, redis_client=self._progress_redis)
                return [], "", version

            extracted_text = ocr_page.raw_text
            paragraphs: Any = [p.strip() for p in extracted_text.split("\n") if p.strip()]
            return paragraphs, extracted_text, None

        if clean_format == "pdf":
            pdf_pages = extract_pdf_pages_with_diagnostics(file_bytes)
            paragraphs, extracted_text = repair_garbled_pdf_pages(
                pdf_pages,
                file_bytes,
                ocr=self.ocr,
                llm=self.llm,
                vlm=self.vlm,
                vlm_dpi=self.vlm_dpi,
                vlm_max_concurrency=self.vlm_max_concurrency,
                vlm_timeout=self.vlm_timeout,
            )
            return paragraphs, extracted_text, None

        if clean_format == "pptx":
            raw_slides = extract_pptx_slides(file_bytes)
            paragraphs, extracted_text = denoise_pptx_slides(raw_slides)
            return paragraphs, extracted_text, None

        paragraphs = extract_text_from_raw_content(file_bytes, clean_format)
        return paragraphs, "\n\n".join(paragraphs), None

    def _build_extraction_progress_callback(
        self, version_id: uuid.UUID
    ) -> Callable[[int, int, str], None]:
        """构建知识抽取实时进度回调，保证同一轮内百分比单调不回退。"""
        highest_progress = 55

        def _on_progress(completed: int, total: int, stage: str) -> None:
            nonlocal highest_progress
            if stage == ParseStatus.AUDITING_KNOWLEDGE.value:
                computed = 90
            else:
                safe_total = max(total, 1)
                ratio = max(0.0, min(1.0, completed / safe_total))
                computed = 55 + round(30 * ratio)
            if computed > highest_progress:
                highest_progress = computed
            set_cached_parse_progress(
                version_id, highest_progress, redis_client=self._progress_redis
            )

        return _on_progress

    def _snippets_already_staged(self, snippets: Sequence[Any]) -> bool:
        if not snippets:
            return False
        state = sa_inspect(snippets[0], raiseerr=False)
        return bool(state is not None and (state.persistent or state.pending))

    @staticmethod
    def _is_retryable_infra_error(exc: Exception) -> bool:
        """判定异常是否属于可交由 RQ 退避重试的瞬时基础设施错误。"""
        if isinstance(
            exc,
            (
                TimeoutError,
                ConnectionError,
                httpx.TimeoutException,
                httpx.RequestError,
                LLMTimeoutError,
                EmbeddingTimeoutError,
                OCRTimeoutError,
                StorageConnectionError,
                QueueTimeoutError,
            ),
        ):
            return True
        if isinstance(exc, LLMError) and not isinstance(
            exc, (LLMAuthError, LLMResponseFormatError)
        ):
            return True
        if isinstance(exc, EmbeddingError) and not isinstance(exc, EmbeddingAuthError):
            return True
        return isinstance(exc, OCRError) and not isinstance(exc, (OCRAuthError, OCRQuotaError))

    def parse_material_pipeline(
        self,
        *,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
        force: bool = False,
    ) -> MaterialVersion:
        """异步/同步资料解析调度流水线主入口。

        Args:
            material_id: 资料标识。
            version_id: 版本标识。
            user_id: 租户用户标识。
            force: 为 True 时在所有提取与校验均成功后原子替换该版本旧知识点与切片。

        Returns:
            MaterialVersion: 完成或失败后的版本状态实体。

        Raises:
            MaterialNotFoundError: 资料或版本不存在。
            MaterialInvalidError: 切分有效内容为 0。
        """
        user_ref = generate_user_ref(user_id)
        material = self.repo.get_material_by_id(material_id, user_id)
        version = self.repo.get_version_by_id(version_id, user_id)
        if material is None or version is None:
            raise MaterialNotFoundError("学习资料或对应版本不存在")
        if version.material_id != material_id:
            raise MaterialNotFoundError("资料版本不属于指定资料")
        if not force and version.parse_status == ParseStatus.READY.value:
            return version

        clean_format = material.file_format.lower().lstrip(".")
        current_stage = (
            "ocr_processing" if clean_format in ("png", "jpg", "jpeg", "image") else "parsing_doc"
        )

        try:
            # 注意：force=True 重解析期间不提前删除旧知识点与切片，确保下载/OCR/LLM 失败时保留旧数据
            self.repo.update_material_status(material_id, user_id, MaterialStatus.PARSING.value)
            self.repo.update_version_status(
                version_id,
                user_id,
                current_stage,
                failed_stage=None,
                error_message=None,
            )
            self.session.commit()
            set_cached_parse_progress(version_id, 30, redis_client=self._progress_redis)

            file_bytes = self.storage.get_object(self.bucket, version.storage_key)

            # 阶段 A: 提取文本与 OCR 质量门禁
            paragraphs, extracted_text, early_version = self._extract_source_content(
                material_id=material_id,
                version=version,
                user_id=user_id,
                clean_format=clean_format,
                file_bytes=file_bytes,
            )
            if early_version is not None:
                return early_version

            # 阶段 B: 纯函数知识切分与批量向量化（仅内存准备，待全链路成功后原子替换）
            current_stage = ParseStatus.EMBEDDING_GENERATION.value
            self.repo.update_version_status(
                version_id, user_id, ParseStatus.EMBEDDING_GENERATION.value
            )
            self.session.commit()
            set_cached_parse_progress(version_id, 45, redis_client=self._progress_redis)

            # 在无未提交 DB 事务状态下提前上传提取文本，避免后续在写锁事务内执行 S3 网络 I/O
            raw_text_key = (
                f"users/{user_id}/materials/{material_id}/v{version.version_number}/raw_text.txt"
            )
            self.storage.put_object(
                self.bucket, raw_text_key, extracted_text.encode("utf-8"), "text/plain"
            )

            snippets_to_save = prepare_material_snippets(
                embedding=self.embedding,
                material_id=material_id,
                version_id=version_id,
                user_id=user_id,
                paragraphs=paragraphs,
                require_non_empty=True,
            )

            # 阶段 C: 自动串联知识树抽取（抽取与质检全通过后同事务原子替换旧知识点与切片）
            if self.knowledge_service is not None:
                current_stage = "knowledge_extraction"
                self.repo.update_version_status(
                    version_id, user_id, ParseStatus.EXTRACTING_KNOWLEDGE.value
                )
                self.session.commit()
                set_cached_parse_progress(version_id, 55, redis_client=self._progress_redis)
                self.knowledge_service.extract_and_build_knowledge_tree(
                    material_id=material_id,
                    version_id=version_id,
                    user_id=user_id,
                    snippets=snippets_to_save,
                    replace_snippets=True,
                    defer_commit=True,
                    on_progress=self._build_extraction_progress_callback(version_id),
                )
                if not self._snippets_already_staged(snippets_to_save):
                    self.repo.delete_snippets_by_version(version_id, user_id)
                    self.repo.create_snippets(snippets_to_save)
            else:
                if force:
                    self.knowledge_repo.delete_knowledge_points_by_version(
                        material_id, version_id, user_id
                    )
                self.repo.delete_snippets_by_version(version_id, user_id)
                self.repo.create_snippets(snippets_to_save)

            # 阶段 D: 短事务激活 READY 终态（仅含轻量 DB 写入，无外部网络 I/O）
            current_stage = "ready"
            self.repo.update_version_status(
                version_id,
                user_id,
                ParseStatus.READY.value,
                raw_text_storage_key=raw_text_key,
                is_active=True,
                reset_errors=True,
            )
            self.repo.update_material_status(
                material_id,
                user_id,
                MaterialStatus.READY.value,
                current_version_id=version_id,
            )
            self.session.commit()
            clear_cached_parse_progress(version_id, redis_client=self._progress_redis)

            logger.info(
                "material pipeline ready",
                extra={
                    "user_ref": user_ref,
                    "target_id": str(material_id),
                    "error_code": 0,
                },
            )
            return version

        except Exception as exc:
            if self._is_retryable_infra_error(exc):
                self.session.rollback()
                logger.warning(
                    "material pipeline retryable infra error; deferring terminal failure to worker",
                    extra={
                        "user_ref": user_ref,
                        "target_id": str(material_id),
                        "failed_stage": current_stage,
                        "exception_type": type(exc).__name__,
                    },
                )
                raise
            mark_pipeline_failed(
                repo=self.repo,
                session=self.session,
                material_id=material_id,
                version_id=version_id,
                user_id=user_id,
                failed_stage=current_stage,
                exc=exc,
                redis_client=self._progress_redis,
            )
            raise

    def mark_orphaned_parse_failed(
        self,
        *,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
        failed_stage: str = "worker_terminated",
        error_message: str = "后台解析任务异常终止，请重新解析",
    ) -> bool:
        """兜底回收异常终止的后台解析任务，仅对仍处于活跃解析态的版本回写 FAILED。"""
        material = self.repo.get_material_by_id(material_id, user_id)
        version = self.repo.get_version_by_id(version_id, user_id)
        if material is None or version is None or version.material_id != material_id:
            return False
        if version.parse_status not in ACTIVE_PARSE_STATUSES:
            return False
        mark_pipeline_failed(
            repo=self.repo,
            session=self.session,
            material_id=material_id,
            version_id=version_id,
            user_id=user_id,
            failed_stage=failed_stage,
            exc=RuntimeError(error_message),
            redis_client=self._progress_redis,
        )
        return True

    def retry_material_pipeline(
        self,
        *,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> tuple[Material, MaterialVersion]:
        """就地重试资料解析流水线。

        校验租户归属，获取最新版本，将版本状态重置为 QUEUED，清空 error_message 与 failed_stage，
        将资料主表状态重置为 PENDING，并触发异步队列入队调度。

        Args:
            material_id: 资料标识。
            user_id: 租户用户标识。

        Returns:
            tuple[Material, MaterialVersion]: 重置就绪的资料与版本实体。

        Raises:
            MaterialNotFoundError: 资料或对应版本不存在。
        """
        user_ref = generate_user_ref(user_id)
        material = self.repo.get_material_by_id(material_id, user_id)
        if material is None:
            raise MaterialNotFoundError("学习资料不存在")

        version = self.repo.get_latest_version(material_id, user_id)
        if version is None:
            raise MaterialNotFoundError("资料对应版本不存在")

        if version.parse_status != ParseStatus.FAILED.value:
            raise MaterialInvalidError("只有解析失败的资料可以重试")

        # 与 trigger_parse 同理：重试派发也必须原子，避免并发重试重复入队同一版本。
        if not self.repo.try_transition_version_status(
            version.id,
            material_id,
            from_status=ParseStatus.FAILED.value,
            to_status=ParseStatus.QUEUED.value,
            reset_errors=True,
        ):
            raise MaterialInvalidError("解析重试已在处理中，请勿重复提交")

        self.repo.update_material_status(
            material_id=material_id,
            user_id=user_id,
            status=MaterialStatus.PENDING.value,
            current_version_id=version.id,
        )
        self.session.commit()
        clear_cached_parse_progress(version.id, redis_client=self._progress_redis)

        self._enqueue_parse(material_id, version.id, user_id)

        logger.info(
            "material pipeline retry scheduled",
            extra={
                "user_ref": user_ref,
                "target_id": str(material_id),
                "error_code": 0,
            },
        )
        self.session.refresh(material)
        self.session.refresh(version)
        return material, version

    def _purge_storage_objects(self, keys: Iterable[str]) -> None:
        """幂等清理对象存储中的指定键，单键失败不阻断主流程。

        Args:
            keys: 待物理删除的对象存储键集合。
        """
        for storage_key in keys:
            if not storage_key:
                continue
            try:
                self.storage.delete_object(self.bucket, storage_key)
            except Exception as exc:
                logger.warning(
                    "failed to delete storage object",
                    extra={"error_code": 0, "details": str(exc)},
                )

    def retry_ocr_pages(
        self,
        *,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
        page_replaces: dict[int, bytes],
    ) -> MaterialVersion:
        """逐页重拍替换：单页重识、门禁评估、递增重拍计数、超3次熔断保护。

        Args:
            material_id: 资料标识。
            version_id: 版本标识。
            user_id: 租户用户标识。
            page_replaces: 待替换的页码与新拍摄图片字节映射。

        Returns:
            MaterialVersion: 更新后的版本实体。

        Raises:
            MaterialNotFoundError: 资料或页面不存在。
            ReshootLimitExceededError: 单页重拍次数超过 3 次触发熔断。
        """
        version = self.repo.get_version_by_id(version_id, user_id)
        if version is None:
            raise MaterialNotFoundError("请求的资料版本不存在")

        # BUG-MAT-017：记录每次重拍被替换的旧图片键，提交后统一物理清理，
        # 避免历次重拍产生永久孤儿对象（仅当前 key 会被硬删引用）。
        purge_keys: list[str] = []

        for page_num, image_bytes in page_replaces.items():
            page = self.repo.get_ocr_page(version_id, page_num, user_id)
            if page is None:
                raise MaterialNotFoundError(f"未找到页码为 {page_num} 的 OCR 记录")

            if page.reshoot_count >= 3:
                raise ReshootLimitExceededError("页面重拍次数已达上限熔断，请重新上传清晰文件")

            old_storage_key = page.image_storage_key
            next_reshoot_count = page.reshoot_count + 1
            ocr_result = self.ocr.recognize_image(image_bytes)

            page_input = OCRPageInput(
                page_number=page_num,
                raw_text=ocr_result.full_text,
                reshoot_count=next_reshoot_count,
            )
            report = verify_ocr_quality([page_input])
            page_rep = report.page_results[0]

            new_storage_key = (
                f"users/{user_id}/materials/{material_id}/v{version.version_number}/"
                f"pages/page_{page_num}_reshoot_{next_reshoot_count}.png"
            )
            self.storage.put_object(self.bucket, new_storage_key, image_bytes, "image/png")

            self.repo.update_ocr_page(
                page_id=page.id,
                user_id=user_id,
                raw_text=ocr_result.full_text,
                gibberish_ratio=page_rep.gibberish_ratio,
                valid_char_count=page_rep.valid_char_count,
                is_qualified=page_rep.is_qualified,
                unqualified_reason=page_rep.unqualified_reason,
                reshoot_count=next_reshoot_count,
                image_storage_key=new_storage_key,
            )
            if old_storage_key and old_storage_key != new_storage_key:
                purge_keys.append(old_storage_key)

            # 熔断检测
            if not page_rep.is_qualified and next_reshoot_count >= 3:
                self.repo.update_version_status(
                    version_id,
                    user_id,
                    ParseStatus.FAILED.value,
                    failed_stage="ocr_reshoot_limit",
                    error_message="页面重拍次数已达上限熔断",
                )
                self.repo.update_material_status(material_id, user_id, MaterialStatus.FAILED.value)
                self.session.commit()
                self._purge_storage_objects(purge_keys)
                raise ReshootLimitExceededError("页面重拍次数已达上限熔断，请重新上传清晰文件")

        # 检查是否全部页面已达标
        all_pages = self.repo.get_ocr_pages(version_id, user_id)
        if all_pages and all(p.is_qualified for p in all_pages):
            combined_text = "\n\n".join(p.raw_text for p in all_pages)
            raw_text_key = (
                f"users/{user_id}/materials/{material_id}/v{version.version_number}/raw_text.txt"
            )
            self.storage.put_object(
                self.bucket, raw_text_key, combined_text.encode("utf-8"), "text/plain"
            )

            paragraphs = [p.strip() for p in combined_text.split("\n\n") if p.strip()]
            chunk_embed_and_replace_snippets(
                repo=self.repo,
                embedding=self.embedding,
                material_id=material_id,
                version_id=version_id,
                user_id=user_id,
                paragraphs=paragraphs,
                require_non_empty=False,
            )

            # 与阶段 D 对齐：全部达标后必须重建知识树（内部会先清理旧知识点），
            # 否则版本虽置 READY，知识树仍为空或陈旧。
            if self.knowledge_service is not None:
                self.repo.update_version_status(
                    version_id,
                    user_id,
                    ParseStatus.EXTRACTING_KNOWLEDGE.value,
                )
                self.knowledge_service.extract_and_build_knowledge_tree(
                    material_id=material_id,
                    version_id=version_id,
                    user_id=user_id,
                )

            self.repo.update_version_status(
                version_id,
                user_id,
                ParseStatus.READY.value,
                raw_text_storage_key=raw_text_key,
                is_active=True,
                # 重拍达标是干净终态：清空门禁失败阶段残留的 error_message/failed_stage
                reset_errors=True,
            )
            self.repo.update_material_status(
                material_id,
                user_id,
                MaterialStatus.READY.value,
                current_version_id=version_id,
            )
        elif all_pages:
            # 仍有不合格页：资料维持「待重拍」，等待用户继续逐页修复
            self.repo.update_material_status(
                material_id,
                user_id,
                MaterialStatus.RETAKE_REQUIRED.value,
            )

        self.session.commit()
        self._purge_storage_objects(purge_keys)
        return version

    def get_material(
        self,
        *,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Material:
        """查询资料及激活版本详情（阻断跨租户越权）。

        Args:
            material_id: 资料标识。
            user_id: 租户用户标识。

        Returns:
            Material: 资料实体。

        Raises:
            MaterialNotFoundError: 资料不存在或已软删除。
        """
        material = self.repo.get_material_by_id(
            material_id, user_id, include_deleted=False, exclude_archived_folder=True
        )
        if material is None:
            raise MaterialNotFoundError("请求的学习资料不存在或已被删除")
        return material

    @staticmethod
    def _resolve_status_filter(status: str | None) -> list[str] | None:
        """将前端筛选语义解析为后端可用的生命周期状态集合。

        - ``parsing``（解析中）聚合 ``pending`` 与 ``parsing`` 两个阶段；
        - ``ready`` / ``completed``（已完成）统一映射为 ``ready``；
        - ``retake_required``（待重拍）映射为资料主表的真实待重拍状态；
        - 其余合法状态保持单值过滤。

        Args:
            status: 前端传入的状态筛选值，可为空。

        Returns:
            list[str] | None: 目标状态集合；``None`` 表示不做状态过滤。
        """
        if status is None:
            return None
        normalized = status.strip().lower()
        if not normalized:
            return None
        if normalized == "parsing":
            return [MaterialStatus.PENDING.value, MaterialStatus.PARSING.value]
        if normalized in ("ready", "completed"):
            return [MaterialStatus.READY.value]
        if normalized == "retake_required":
            return [MaterialStatus.RETAKE_REQUIRED.value]
        return [normalized]

    @staticmethod
    def _calculate_progress_percentage(
        parse_status: str | None,
        material_status: str | None = None,
        cached_progress: int | None = None,
    ) -> int | None:
        """根据细粒度解析流水线状态、实时缓存或资料主状态计算进度百分比 (0-100)。"""
        if parse_status == ParseStatus.READY.value or material_status == MaterialStatus.READY.value:
            return 100
        if parse_status == ParseStatus.FAILED.value or material_status in (
            MaterialStatus.FAILED.value,
            MaterialStatus.RETAKE_REQUIRED.value,
        ):
            return 0

        if parse_status is not None:
            status_map: dict[str, int] = {
                ParseStatus.NOT_STARTED.value: 0,
                ParseStatus.QUEUED.value: 10,
                ParseStatus.PARSING_DOC.value: 30,
                ParseStatus.OCR_PROCESSING.value: 30,
                ParseStatus.EMBEDDING_GENERATION.value: 45,
                ParseStatus.EXTRACTING_KNOWLEDGE.value: 55,
                ParseStatus.AUDITING_KNOWLEDGE.value: 90,
                ParseStatus.READY.value: 100,
                ParseStatus.FAILED.value: 0,
            }
            if parse_status in status_map:
                base_pct = status_map[parse_status]
                if parse_status in ACTIVE_PARSE_STATUSES and cached_progress is not None:
                    return max(base_pct, min(99, cached_progress))
                return base_pct

        if material_status == MaterialStatus.PENDING.value:
            return 0
        if material_status == MaterialStatus.PARSING.value:
            return 30
        return None

    def _resolve_version_parse_status(
        self,
        material: Material,
        user_id: uuid.UUID,
    ) -> tuple[str | None, int | None]:
        """关联装配当前激活版本（或最新版本）的细粒度解析状态与进度百分比。

        适用于单条详情路径（逐条查询版本）。列表路径请改用
        ``_pick_loaded_version`` + ``_compose_parse_status`` 以避免 N+1 查询。
        """
        version = self._resolve_material_version(material, user_id)
        cached_progress = (
            get_cached_parse_progress(version.id, redis_client=self._progress_redis)
            if version is not None and version.parse_status in ACTIVE_PARSE_STATUSES
            else None
        )
        return self._compose_parse_status(material, version, cached_progress=cached_progress)

    def _resolve_material_version(
        self,
        material: Material,
        user_id: uuid.UUID,
    ) -> MaterialVersion | None:
        """解析资料当前激活版本，缺省回退至最新版本（逐条查询）。"""
        version: MaterialVersion | None = None
        if material.current_version_id is not None:
            version = self.repo.get_version_by_id(material.current_version_id, user_id)
        if version is None:
            version = self.repo.get_latest_version(material.id, user_id)
        return version

    def _compose_version_counts(
        self,
        version: MaterialVersion | None,
        user_id: uuid.UUID,
    ) -> tuple[int | None, int | None]:
        """装配指定版本的考点总数与 OCR 页数（(key_points_count, page_count)）。"""
        if version is None:
            return None, None
        counts = self.repo.count_knowledge_points_by_version_ids([version.id], user_id)
        page_count = len(self.repo.get_ocr_pages(version.id, user_id))
        return counts.get(version.id, 0), page_count

    @staticmethod
    def _pick_loaded_version(material: Material) -> MaterialVersion | None:
        """从已预加载的 ``material.versions`` 内存集合中挑选目标版本。

        选择语义与逐条查询完全等价：
        1. 若 ``current_version_id`` 非空且命中已加载版本集合，取该版本；
        2. 否则取 ``version_number`` 最大者（``versions`` 关系已按版本号降序排列，
           首元素即为最新版本）。

        调用方须确保 ``material.versions`` 已通过仓储层 ``selectinload`` 预加载，
        从而以固定 1 次批量查询替代逐条版本查询。
        """
        versions = list(material.versions or [])
        if not versions:
            return None
        if material.current_version_id is not None:
            for version in versions:
                if version.id == material.current_version_id:
                    return version
        return versions[0]

    @staticmethod
    def _compose_parse_status(
        material: Material,
        version: MaterialVersion | None,
        *,
        cached_progress: int | None = None,
    ) -> tuple[str | None, int | None]:
        """根据目标版本与资料主状态合成细粒度解析状态与进度百分比。"""
        parse_status: str | None = version.parse_status if version is not None else None
        progress_percentage = MaterialService._calculate_progress_percentage(
            parse_status,
            material.status,
            cached_progress=cached_progress,
        )
        return parse_status, progress_percentage

    def get_material_detail(
        self,
        *,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> MaterialDetailView:
        """获取资料详情（包含历史版本与解析阶段进度），阻断跨租户越权。

        Args:
            material_id: 资料标识。
            user_id: 租户用户标识。

        Returns:
            MaterialDetailView: 包含历史版本与解析阶段进度的资料强类型视图。

        Raises:
            MaterialNotFoundError: 资料不存在或已软删除。
        """
        material = self.get_material(material_id=material_id, user_id=user_id)
        version = self._resolve_material_version(material, user_id)
        cached_progress = (
            get_cached_parse_progress(version.id, redis_client=self._progress_redis)
            if version is not None and version.parse_status in ACTIVE_PARSE_STATUSES
            else None
        )
        parse_status, progress_pct = self._compose_parse_status(
            material, version, cached_progress=cached_progress
        )
        key_points_count, page_count = self._compose_version_counts(version, user_id)
        return MaterialDetailView(
            material=material,
            parse_status=parse_status,
            progress_percentage=progress_pct,
            key_points_count=key_points_count,
            page_count=page_count,
            error_message=version.error_message if version is not None else None,
            failed_stage=version.failed_stage if version is not None else None,
        )

    def get_statistics(self, *, user_id: uuid.UUID) -> tuple[int, int]:
        """获取当前用户学习足迹的就绪资料数与考点数。

        Args:
            user_id: 租户用户标识。

        Returns:
            tuple[int, int]: (就绪资料数, 考点数)。
        """
        return self.repo.get_statistics(user_id=user_id)

    def list_materials(
        self,
        user_id: uuid.UUID | None = None,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
        limit: int | None = None,
        offset: int | None = None,
        is_deleted: bool = False,
        folder_id: uuid.UUID | None = None,
        unclassified: bool = False,
        **kwargs: Any,
    ) -> tuple[list[MaterialDetailView], int]:
        """分页获取用户所属资料列表及符合条件总记录数，并装配解析进度信息。

        Args:
            user_id: 租户用户标识。
            keyword: 可选标题模糊搜索词。
            status: 可选资料生命周期状态过滤。
            page: 当前页码 (从 1 开始)。
            page_size: 单页容量限制。
            limit: 可选的单页数量限制（优先于 page_size）。
            offset: 可选的分页游标偏移量（优先于 page 计算）。
            is_deleted: 软删除状态过滤。
            folder_id: 可选课程文件夹过滤（归属该课程的资料）。
            unclassified: 是否仅返回未分类资料。
            kwargs: 兼容其他调用传参。

        Returns:
            tuple[list[MaterialDetailView], int]: (资料详情强类型视图列表, 总记录数)。
        """
        resolved_user_id = user_id or kwargs.get("user_id")
        if resolved_user_id is None:
            raise ValueError("user_id 必须指定")

        calc_limit = limit if limit is not None else page_size
        calc_offset = offset if offset is not None else (max(page - 1, 0) * calc_limit)
        resolved_statuses = self._resolve_status_filter(status)

        items, total = self.repo.list_materials_by_user(
            user_id=resolved_user_id,
            is_deleted=is_deleted,
            limit=calc_limit,
            offset=calc_offset,
            keyword=keyword,
            status=None,
            statuses=resolved_statuses,
            folder_id=folder_id,
            unclassified=unclassified,
        )
        # 批量统计各激活版本考点数与实时进度（单次分组查询，杜绝列表内逐条 N+1）
        picked_versions = [self._pick_loaded_version(item) for item in items]
        version_ids = [version.id for version in picked_versions if version is not None]
        active_version_ids = [
            version.id
            for version in picked_versions
            if version is not None and version.parse_status in ACTIVE_PARSE_STATUSES
        ]
        kp_counts = self.repo.count_knowledge_points_by_version_ids(version_ids, resolved_user_id)
        cached_progress_map = get_cached_parse_progress_batch(
            active_version_ids, redis_client=self._progress_redis
        )
        views: list[MaterialDetailView] = []
        for item, version in zip(items, picked_versions, strict=True):
            cached_progress = cached_progress_map.get(version.id) if version is not None else None
            parse_status, progress_pct = self._compose_parse_status(
                item, version, cached_progress=cached_progress
            )
            key_points_count = kp_counts.get(version.id, 0) if version is not None else None
            page_count = len(version.ocr_pages) if version is not None else None
            views.append(
                MaterialDetailView(
                    material=item,
                    parse_status=parse_status,
                    progress_percentage=progress_pct,
                    key_points_count=key_points_count,
                    page_count=page_count,
                    error_message=version.error_message if version is not None else None,
                    failed_stage=version.failed_stage if version is not None else None,
                )
            )
        return views, total

    def list_material_versions(
        self,
        user_id: uuid.UUID,
        material_id: uuid.UUID,
    ) -> list[MaterialVersion]:
        """查询指定资料所属的所有历史版本列表 (按版本号降序)。

        Args:
            user_id: 租户用户标识。
            material_id: 资料主键。

        Returns:
            list[MaterialVersion]: 历史版本实体列表。

        Raises:
            MaterialNotFoundError: 资料不存在或已软删除。
        """
        material = self.repo.get_material_by_id(material_id, user_id)
        if material is None:
            raise MaterialNotFoundError("请求的学习资料不存在")
        return self.repo.list_versions_by_material(material_id, user_id)

    def list_ocr_pages(
        self,
        *,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
        only_unqualified: bool = False,
    ) -> tuple[uuid.UUID | None, list[MaterialOCRPage]]:
        """查询资料当前激活（或最新）版本的页级 OCR 质检记录。

        用于「待重拍」链路：前端据此获取真实的不合格页面清单并驱动逐页重拍。

        Args:
            material_id: 资料标识。
            user_id: 租户用户标识。
            only_unqualified: 是否仅返回未达标页面。

        Returns:
            tuple[uuid.UUID | None, list[MaterialOCRPage]]: (版本标识, 页级记录列表)。

        Raises:
            MaterialNotFoundError: 资料不存在或已软删除。
        """
        material = self.repo.get_material_by_id(material_id, user_id, include_deleted=False)
        if material is None:
            raise MaterialNotFoundError("请求的学习资料不存在或已被删除")

        version: MaterialVersion | None = None
        if material.current_version_id is not None:
            version = self.repo.get_version_by_id(material.current_version_id, user_id)
        if version is None:
            version = self.repo.get_latest_version(material_id, user_id)
        if version is None:
            return None, []

        pages = self.repo.get_ocr_pages(version.id, user_id)
        if only_unqualified:
            pages = [page for page in pages if not page.is_qualified]
        return version.id, pages

    def switch_material_version(
        self,
        user_id: uuid.UUID,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> Material:
        """切换资料激活版本，必须处于 ready 状态。

        Args:
            user_id: 租户用户标识。
            material_id: 资料主键。
            version_id: 目标版本主键。

        Returns:
            Material: 切换后的资料实体。

        Raises:
            MaterialNotFoundError: 资料或版本不存在。
            MaterialInvalidError: 目标版本未解析完成无法切换。
        """
        material = self.repo.get_material_by_id(material_id, user_id)
        if material is None:
            raise MaterialNotFoundError("请求的学习资料不存在")

        version = self.repo.get_version_by_id(version_id, user_id)
        if version is None or version.material_id != material_id:
            raise MaterialNotFoundError("请求的资料版本不存在")

        if version.parse_status != ParseStatus.READY.value:
            raise MaterialInvalidError(
                "该版本尚未解析完成，无法切换为当前激活版本",
                details={"version_id": str(version_id), "parse_status": version.parse_status},
            )

        versions = self.repo.list_versions_by_material(material_id, user_id)
        for v in versions:
            v.is_active = v.id == version_id

        self.repo.update_material_status(
            material_id=material_id,
            user_id=user_id,
            status=MaterialStatus.READY.value,
            current_version_id=version_id,
        )
        self.session.commit()

        updated_material = self.repo.get_material_by_id(material_id, user_id)
        return updated_material if updated_material is not None else material

    def _check_stale_or_orphaned_parse(
        self, version: MaterialVersion
    ) -> tuple[bool, datetime | None]:
        """判定处于活跃解析态的版本是否已超时僵死或成为队列孤儿。

        Returns:
            tuple[bool, datetime | None]: (是否允许强制重置恢复, 并发防重入所需的陈旧时间上限)。
        """
        now = datetime.now(UTC)
        age: timedelta | None = None
        if version.updated_at is not None:
            aware_updated = (
                version.updated_at
                if version.updated_at.tzinfo is not None
                else version.updated_at.replace(tzinfo=UTC)
            )
            age = now - aware_updated

        if age is not None and age >= STALE_PARSE_TIMEOUT:
            stale_before = (
                now - STALE_PARSE_TIMEOUT
                if version.parse_status == ParseStatus.QUEUED.value
                else None
            )
            return True, stale_before

        has_active_fn = getattr(self.queue, "has_active_job", None)
        if callable(has_active_fn):
            active_in_queue = has_active_fn(
                "parse_material_pipeline",
                {"version_id": str(version.id)},
            )
            if active_in_queue is False:
                if version.parse_status != ParseStatus.QUEUED.value:
                    return True, None
                if age is None or age >= ORPHAN_QUEUED_GRACE_PERIOD:
                    return True, (now - ORPHAN_QUEUED_GRACE_PERIOD if age is not None else None)
        return False, None

    def trigger_parse(
        self,
        user_id: uuid.UUID,
        material_id: uuid.UUID,
        version_id: uuid.UUID | None = None,
        *,
        sync: bool = False,
        force: bool = False,
    ) -> MaterialVersion:
        """触发或重新调度资料解析流水线。

        Args:
            user_id: 租户用户标识。
            material_id: 资料主键。
            version_id: 可选指定版本标识，默认当前激活版本或最新版本。
            sync: 是否同步阻塞执行。
            force: 为 True 时允许强制重新解析已就绪版本或恢复僵死/孤儿活跃解析任务。

        Returns:
            MaterialVersion: 目标版本实体。

        Raises:
            MaterialNotFoundError: 资料或指定版本不存在。
        """
        material = self.repo.get_material_by_id(material_id, user_id)
        if material is None:
            raise MaterialNotFoundError("请求的学习资料不存在")

        if version_id is not None:
            target_version = self.repo.get_version_by_id(version_id, user_id)
            if target_version is None or target_version.material_id != material_id:
                raise MaterialNotFoundError("请求的资料版本不存在")
        else:
            if material.current_version_id is not None:
                target_version = self.repo.get_version_by_id(material.current_version_id, user_id)
            else:
                target_version = None

            if target_version is None:
                versions = self.repo.list_versions_by_material(material_id, user_id)
                if not versions:
                    raise MaterialNotFoundError("该资料未关联有效版本")
                target_version = versions[0]

        if sync:
            return self.parse_material_pipeline(
                material_id=material_id,
                version_id=target_version.id,
                user_id=user_id,
                force=force,
            )

        stale_before: datetime | None = None
        if target_version.parse_status in ACTIVE_PARSE_STATUSES:
            if not force:
                return target_version
            can_recover, stale_before = self._check_stale_or_orphaned_parse(target_version)
            if not can_recover:
                return target_version
        elif target_version.parse_status == ParseStatus.READY.value and not force:
            return target_version

        # 派发必须是原子的：两个并发请求不能凭同一次陈旧读各入队一次，否则同一版本
        # 会被两个 worker 同时解析（重复 OCR/LLM 开销与重复切片）。条件更新未命中
        # 说明该版本已被其他请求推进，本次不再重复派发。
        if not self.repo.try_transition_version_status(
            target_version.id,
            material_id,
            from_status=target_version.parse_status,
            to_status=ParseStatus.QUEUED.value,
            reset_errors=True,
            stale_before=stale_before,
        ):
            return target_version

        clear_cached_parse_progress(target_version.id, redis_client=self._progress_redis)
        self.repo.update_material_status(
            material_id,
            user_id,
            MaterialStatus.PARSING.value,
        )
        self.session.commit()

        self._enqueue_parse(material_id, target_version.id, user_id, force=force)
        return target_version

    def _enqueue_parse(
        self,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        force: bool = False,
    ) -> None:
        """Dispatch one explicit parse request and expose dispatch failure in DB."""
        payload: dict[str, str] = {
            "material_id": str(material_id),
            "version_id": str(version_id),
            "user_id": str(user_id),
        }
        if force:
            payload["force"] = "true"
        try:
            self.queue.enqueue(
                task_name="parse_material_pipeline",
                payload=payload,
                user_id=str(user_id),
            )
        except Exception:
            self.repo.update_version_status(
                version_id,
                user_id,
                ParseStatus.FAILED.value,
                failed_stage="queue_dispatch",
                error_message="解析任务提交失败，请重试",
            )
            self.repo.update_material_status(material_id, user_id, MaterialStatus.FAILED.value)
            self.session.commit()
            raise

    def reshoot_material_page(
        self,
        user_id: uuid.UUID,
        material_id: uuid.UUID,
        page_index: int,
        file_content: bytes,
        version_id: uuid.UUID | None = None,
    ) -> MaterialOCRPage:
        """单页就地重拍替换：重新识别、更新质量评级与重拍熔断控制。

        Args:
            user_id: 租户用户标识。
            material_id: 资料主键。
            page_index: 目标重拍页码序号 (从 1 开始)。
            file_content: 新拍摄的图片二进制字节流。
            version_id: 可选指定版本标识，默认当前激活版本。

        Returns:
            MaterialOCRPage: 更新后的页级质检记录。

        Raises:
            MaterialNotFoundError: 资料或对应页面不存在。
            MaterialInvalidError: 上传图片内容为空。
            ReshootLimitExceededError: 单页重拍次数达 3 次触发熔断。
        """
        if not file_content:
            raise MaterialInvalidError("重拍上传的图片内容不能为空")

        material = self.repo.get_material_by_id(material_id, user_id)
        if material is None:
            raise MaterialNotFoundError("请求的学习资料不存在")

        if version_id is not None:
            target_ver_id: uuid.UUID = version_id
        else:
            resolved_version_id = material.current_version_id
            if resolved_version_id is None:
                # OCR 门禁失败时资料尚未激活任何版本，重拍须回退到最新版本
                latest = self.repo.get_latest_version(material_id, user_id)
                if latest is None:
                    raise MaterialNotFoundError("该资料未关联有效版本")
                resolved_version_id = latest.id
            target_ver_id = resolved_version_id

        version = self.repo.get_version_by_id(target_ver_id, user_id)
        if version is None or version.material_id != material_id:
            raise MaterialNotFoundError("请求的资料版本不存在")

        self.retry_ocr_pages(
            material_id=material_id,
            version_id=target_ver_id,
            user_id=user_id,
            page_replaces={page_index: file_content},
        )

        page = self.repo.get_ocr_page(target_ver_id, page_index, user_id)
        if page is None:
            raise MaterialNotFoundError(f"未找到页码为 {page_index} 的 OCR 记录")
        return page

    def soft_delete_material(
        self,
        user_id: uuid.UUID | None = None,
        material_id: uuid.UUID | None = None,
        *,
        user_id_kw: uuid.UUID | None = None,
        material_id_kw: uuid.UUID | None = None,
        **kwargs: Any,
    ) -> bool:
        """软删除资料：标记 is_deleted=True，不破坏历史练习记录。

        Args:
            user_id: 租户用户标识。
            material_id: 资料标识。
            user_id_kw: 兼容关键字参数。
            material_id_kw: 兼容关键字参数。
            kwargs: 兼容其他调用。

        Returns:
            bool: 成功删除返回 True。

        Raises:
            MaterialNotFoundError: 资料不存在或已删除。
        """
        resolved_user_id = user_id or kwargs.get("user_id") or user_id_kw
        resolved_material_id = material_id or kwargs.get("material_id") or material_id_kw
        if resolved_user_id is None or resolved_material_id is None:
            raise ValueError("user_id 与 material_id 均必须指定")

        success = self.repo.soft_delete_material(resolved_material_id, resolved_user_id)
        if not success:
            raise MaterialNotFoundError("请求的学习资料不存在或已被删除")
        self.session.commit()
        return True

    def hard_delete_material(
        self,
        user_id: uuid.UUID | None = None,
        material_id: uuid.UUID | None = None,
        *,
        user_id_kw: uuid.UUID | None = None,
        material_id_kw: uuid.UUID | None = None,
        **kwargs: Any,
    ) -> bool:
        """物理级联销毁资料：删除切片、版本、OCR页、资料表记录及 MinIO 对象存储文件。

        Args:
            user_id: 租户用户标识。
            material_id: 资料标识。
            user_id_kw: 兼容关键字参数。
            material_id_kw: 兼容关键字参数。
            kwargs: 兼容其他调用。

        Returns:
            bool: 成功删除返回 True。

        Raises:
            MaterialNotFoundError: 资料不存在。
        """
        resolved_user_id = user_id or kwargs.get("user_id") or user_id_kw
        resolved_material_id = material_id or kwargs.get("material_id") or material_id_kw
        if resolved_user_id is None or resolved_material_id is None:
            raise ValueError("user_id 与 material_id 均必须指定")

        material = self.repo.get_material_by_id(
            resolved_material_id, resolved_user_id, include_deleted=True
        )
        if material is None:
            raise MaterialNotFoundError("请求的学习资料不存在")

        # 收集所有关联 MinIO 存储键
        keys_to_purge: list[str] = []
        for ver in material.versions:
            if ver.storage_key:
                keys_to_purge.append(ver.storage_key)
            if ver.raw_text_storage_key:
                keys_to_purge.append(ver.raw_text_storage_key)
            for page in ver.ocr_pages:
                if page.image_storage_key:
                    keys_to_purge.append(page.image_storage_key)

        self.repo.hard_delete_material(resolved_material_id, resolved_user_id)
        self.session.commit()

        # 同步清理存储文件
        self._purge_storage_objects(keys_to_purge)

        return True


__all__ = [
    "DEFAULT_MATERIAL_BUCKET",
    "MAGIC_NUMBERS",
    "MAX_FILE_SIZES",
    "MaterialDetailView",
    "MaterialService",
    "build_material_storage_key",
    "extract_text_from_raw_content",
    "validate_file_magic",
]
