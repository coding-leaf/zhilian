"""学习资料领域服务编排模块。

统领事务边界并跨外设（Storage, OCR, Embedding, Queue, Idempotency）
与纯函数计算核调度。
严格遵循 AGENTS.md 规范：
- app/services 是全系统唯一允许开启数据库事务的层；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)；
- 结构化脱敏日志 8 要素输出，严禁向日志记录资料全文或敏感密钥。
"""

import hashlib
import io
import logging
import uuid
import zipfile
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any
from xml.etree import ElementTree

import pypdf
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.services.knowledge import KnowledgeService

from app.core.algorithms.material_chunking import split_material_into_snippets
from app.core.algorithms.ocr_quality import (
    OCRPageInput,
    verify_ocr_quality,
)
from app.core.errors import (
    FolderNotFoundError,
    MaterialInvalidError,
    MaterialNotFoundError,
    ReshootLimitExceededError,
)
from app.core.security import generate_user_ref
from app.integrations.embedding.protocol import EmbeddingProtocol
from app.integrations.idempotency.protocol import (
    IdempotencyProtocol,
    validate_idempotency_key,
)
from app.integrations.ocr.protocol import OCRProtocol
from app.integrations.queue.protocol import QueueProtocol
from app.integrations.storage.protocol import StorageProtocol
from app.models.material import (
    Material,
    MaterialOCRPage,
    MaterialSnippet,
    MaterialStatus,
    MaterialVersion,
    ParseStatus,
    SourceType,
)
from app.repositories.folder import FolderRepository
from app.repositories.material import MaterialRepository

logger = logging.getLogger(__name__)

# 依据：文件类型二进制魔数定义
MAGIC_NUMBERS: dict[str, list[bytes]] = {
    "pdf": [b"%PDF-"],
    "docx": [b"PK\x03\x04"],
    "pptx": [b"PK\x03\x04"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
}

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


def validate_file_magic(content: bytes, declared_format: str) -> bool:
    """校验给定二进制前缀是否与声明格式魔数严格匹配。

    纯函数计算核，无任何外部 I/O。

    Args:
        content: 文件二进制数据流。
        declared_format: 声明的文件格式扩展名。

    Returns:
        bool: 匹配成功返回 True，否则返回 False。
    """
    if not isinstance(content, (bytes, bytearray)) or len(content) == 0:
        return False

    normalized_format = declared_format.lower().lstrip(".")

    # 纯文本类型
    if normalized_format in ("txt", "md"):
        try:
            decoded = content.decode("utf-8")
            # 二进制控制空字符通常代表假冒文本文件
            return "\x00" not in decoded
        except UnicodeDecodeError:
            return False

    # 二进制魔数对比
    if normalized_format in MAGIC_NUMBERS:
        return any(content.startswith(magic) for magic in MAGIC_NUMBERS[normalized_format])

    return False


def _extract_text_from_pdf(content: bytes) -> str:
    """使用 pypdf 从 PDF 二进制中抽取正文纯文本。

    纯函数计算，执行页文本抽取与有效字符门禁。

    Args:
        content: PDF 原生二进制字节流。

    Returns:
        str: 规整后的全部页面文本。

    Raises:
        MaterialInvalidError: PDF 损坏或无有效文本内容。
    """
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        extracted_pages: list[str] = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                extracted_pages.append(page_text)
        full_text = "\n\n".join(extracted_pages).strip()
    except Exception as exc:
        if isinstance(exc, MaterialInvalidError):
            raise
        raise MaterialInvalidError(
            f"PDF 文件解析失败: {exc}",
            details={"error": str(exc)},
        ) from exc

    valid_chars = [c for c in full_text if not c.isspace()]
    if len(valid_chars) < 10:
        raise MaterialInvalidError(
            "PDF文件无有效文字内容，扫描件请直接上传图片",
            details={"valid_char_count": len(valid_chars)},
        )

    return full_text


def extract_text_from_raw_content(content: bytes, file_format: str) -> list[str]:
    """从原始文件二进制中提取段落文本序列。

    支持格式：
    - `txt` / `md`：UTF-8 文本按空行或换行切段；
    - `pdf`：pypdf 页文本抽取；
    - `docx` / `pptx`：OOXML（ZIP 容器）正文 XML 文本抽取；
    - 其他格式：返回空列表。

    Args:
        content: 原生文件二进制。
        file_format: 文件格式扩展名。

    Returns:
        list[str]: 提取的段落文本列表。

    Raises:
        MaterialInvalidError: docx/pptx 文件损坏、非 ZIP 容器或缺关键成员。
    """
    normalized_format = file_format.lower().lstrip(".")
    if normalized_format == "docx":
        return _extract_paragraphs_from_docx(content)
    if normalized_format == "pptx":
        return _extract_paragraphs_from_pptx(content)

    if normalized_format in ("txt", "md"):
        text = content.decode("utf-8", errors="replace")
    elif normalized_format == "pdf":
        text = _extract_text_from_pdf(content)
    else:
        text = ""

    raw_paragraphs = text.split("\n\n") if "\n\n" in text else text.split("\n")
    paragraphs = [p.strip() for p in raw_paragraphs if p.strip()]
    return paragraphs if paragraphs else ([text.strip()] if text.strip() else [])


def _local_name(tag: str) -> str:
    """剥离 XML 命名空间前缀，返回标签本地名。"""
    return tag.rsplit("}", 1)[-1]


def _extract_paragraphs_from_docx(content: bytes) -> list[str]:
    """从真实 DOCX（ZIP 容器）中抽取正文段落文本。

    读取 `word/document.xml`，以纯函数方式按 `w:p` 段落聚合所有 `w:t` 文本节点。

    Args:
        content: DOCX 原生二进制字节流。

    Returns:
        list[str]: 按文档顺序排列的非空段落文本。

    Raises:
        MaterialInvalidError: 非有效 ZIP 容器、缺少 `word/document.xml`、
            正文 XML 损坏或未包含可提取文本。
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            document_xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise MaterialInvalidError(
            "DOCX 文档损坏或格式不支持（非有效 OOXML ZIP 容器）",
            details={"error": str(exc)},
        ) from exc

    try:
        root = ElementTree.fromstring(document_xml)  # noqa: S314 - 标准库解析受控 OOXML，禁新增生产依赖
    except ElementTree.ParseError as exc:
        raise MaterialInvalidError(
            "DOCX 正文 XML 损坏，无法解析",
            details={"error": str(exc)},
        ) from exc

    paragraphs: list[str] = []
    for node in root.iter():
        if _local_name(node.tag) != "p":
            continue
        merged = "".join(
            child.text or "" for child in node.iter() if _local_name(child.tag) == "t"
        ).strip()
        if merged:
            paragraphs.append(merged)

    if not paragraphs:
        raise MaterialInvalidError(
            "DOCX 文档未包含可提取的正文文本",
            details={"paragraph_count": 0},
        )
    return paragraphs


def _slide_sort_key(name: str) -> int:
    """从幻灯片成员路径中提取数字序号用于稳定排序。"""
    stem = name.rsplit("/", 1)[-1]
    digits = "".join(char for char in stem if char.isdigit())
    return int(digits) if digits else 0


def _extract_paragraphs_from_pptx(content: bytes) -> list[str]:
    """从真实 PPTX（ZIP 容器）中抽取幻灯片文本。

    读取 `ppt/slides/slide*.xml`（按幻灯片序号排序），抽取全部 `a:t` 文本节点。

    Args:
        content: PPTX 原生二进制字节流。

    Returns:
        list[str]: 按幻灯片顺序排列的非空文本片段。

    Raises:
        MaterialInvalidError: 非有效 ZIP 容器、缺失幻灯片成员、XML 损坏或无文本。
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            slide_names = sorted(
                (
                    name
                    for name in archive.namelist()
                    if name.startswith("ppt/slides/slide") and name.endswith(".xml")
                ),
                key=_slide_sort_key,
            )
            if not slide_names:
                raise MaterialInvalidError(
                    "PPTX 文件缺少幻灯片内容",
                    details={"slide_count": 0},
                )
            slide_payloads = [(name, archive.read(name)) for name in slide_names]
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise MaterialInvalidError(
            "PPTX 文件损坏或格式不支持（非有效 OOXML ZIP 容器）",
            details={"error": str(exc)},
        ) from exc

    fragments: list[str] = []
    for name, payload in slide_payloads:
        try:
            slide_root = ElementTree.fromstring(payload)  # noqa: S314 - 标准库解析受控 OOXML
        except ElementTree.ParseError as exc:
            raise MaterialInvalidError(
                f"PPTX 幻灯片 XML 损坏: {name}",
                details={"error": str(exc)},
            ) from exc
        for node in slide_root.iter():
            if _local_name(node.tag) == "t":
                text = (node.text or "").strip()
                if text:
                    fragments.append(text)

    if not fragments:
        raise MaterialInvalidError(
            "PPTX 文档未包含可提取的正文文本",
            details={"slide_count": len(slide_names)},
        )
    return fragments


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
        bucket: str = DEFAULT_MATERIAL_BUCKET,
    ) -> None:
        self.session = session
        self.storage = storage_adapter
        self.ocr = ocr_adapter
        self.embedding = embedding_adapter
        self.queue = queue_adapter
        self.idempotency = idempotency_adapter
        self.repo = material_repo or MaterialRepository(session)
        self.folder_repo = folder_repo or FolderRepository(session)
        self.knowledge_service = knowledge_service
        self.bucket = bucket

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

        # 4. 事务内持久化 Material 与 Version 记录
        try:
            material = self.repo.create_material(
                user_id=user_id,
                title=title,
                file_format=clean_format,
                file_size=len(file_content),
                source_type=source_type,
                status=MaterialStatus.PENDING.value,
                folder_id=folder_id,
            )

            # 内容哈希仅用于记录与去重语义，物理对象必须为本资料独占副本。
            # 禁止复用其它资料的 storage_key：否则源资料硬删会连带 purge 本资料对象。
            storage_key = build_material_storage_key(
                user_id, material.id, 1, content_hash, clean_format
            )
            self.storage.put_object(
                bucket=self.bucket,
                key=storage_key,
                data=file_content,
                content_type=f"application/{clean_format}",
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

    def parse_material_pipeline(
        self,
        *,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> MaterialVersion:
        """异步/同步资料解析调度流水线主入口。

        Args:
            material_id: 资料标识。
            version_id: 版本标识。
            user_id: 租户用户标识。

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
        if version.parse_status == ParseStatus.READY.value:
            return version

        clean_format = material.file_format.lower().lstrip(".")
        current_stage = (
            "ocr_processing" if clean_format in ("png", "jpg", "jpeg", "image") else "parsing_doc"
        )

        try:
            self.repo.update_material_status(material_id, user_id, MaterialStatus.PARSING.value)
            self.repo.update_version_status(version_id, user_id, current_stage)
            self.session.commit()
            file_bytes = self.storage.get_object(self.bucket, version.storage_key)

            # 阶段 A: 提取文本与 OCR 质量门禁
            if clean_format in ("png", "jpg", "jpeg", "image"):
                ocr_result = self.ocr.recognize_image(file_bytes)

                # 逐页门禁评估
                page_input = OCRPageInput(
                    page_number=1,
                    raw_text=ocr_result.full_text,
                    reshoot_count=0,
                )
                report = verify_ocr_quality([page_input])
                page_report = report.page_results[0]

                page_storage_key = (
                    f"users/{user_id}/materials/{material_id}/v{version.version_number}/"
                    "pages/page_1.png"
                )
                self.storage.put_object(
                    self.bucket, page_storage_key, file_bytes, f"image/{clean_format}"
                )

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
                for previous_page in self.repo.get_ocr_pages(version_id, user_id):
                    self.session.delete(previous_page)
                self.session.flush()
                self.repo.create_ocr_pages([ocr_page])

                if not report.is_all_qualified:
                    current_stage = "ocr_quality_gate"
                    self.repo.update_version_status(
                        version_id,
                        user_id,
                        ParseStatus.FAILED.value,
                        error_message=page_report.unqualified_reason,
                        failed_stage=current_stage,
                    )
                    # 质检未达标并非终态失败，而是进入「待重拍」链路供逐页重拍修复
                    self.repo.update_material_status(
                        material_id, user_id, MaterialStatus.RETAKE_REQUIRED.value
                    )
                    self.session.commit()
                    return version

                extracted_text = ocr_result.full_text
                paragraphs = [p.strip() for p in extracted_text.split("\n") if p.strip()]
            else:
                paragraphs = extract_text_from_raw_content(file_bytes, clean_format)
                extracted_text = "\n\n".join(paragraphs)

            # 持久化提取文本到对象存储
            raw_text_key = (
                f"users/{user_id}/materials/{material_id}/v{version.version_number}/raw_text.txt"
            )
            self.storage.put_object(
                self.bucket, raw_text_key, extracted_text.encode("utf-8"), "text/plain"
            )

            # 阶段 B: 纯函数知识切分
            current_stage = "chunking"
            self.repo.update_version_status(
                version_id, user_id, ParseStatus.EXTRACTING_KNOWLEDGE.value
            )
            self.session.commit()
            chunk_result = split_material_into_snippets(paragraphs)

            if not chunk_result.snippets:
                raise MaterialInvalidError("资料有效内容不足，未切分出有效知识片段")

            # 阶段 C: 批量向量化与切片持久化
            current_stage = "embedding_generation"
            self.repo.update_version_status(
                version_id, user_id, ParseStatus.EMBEDDING_GENERATION.value
            )
            self.session.commit()
            snippet_texts = [snip.content for snip in chunk_result.snippets]
            vectors = self.embedding.embed_documents(snippet_texts)

            snippets_to_save: list[MaterialSnippet] = []
            for i, snip in enumerate(chunk_result.snippets):
                vector = vectors[i] if i < len(vectors) else None
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
                        source_info={"source_ref": snip.source_ref},
                        embedding=vector,
                    )
                )

            self.repo.delete_snippets_by_version(version_id, user_id)
            self.repo.create_snippets(snippets_to_save)

            # 阶段 D: 自动串联知识树抽取与落库 (若注入了 KnowledgeService)
            if self.knowledge_service is not None:
                current_stage = "knowledge_extraction"
                self.repo.update_version_status(
                    version_id, user_id, ParseStatus.EXTRACTING_KNOWLEDGE.value
                )
                self.session.commit()
                self.knowledge_service.extract_and_build_knowledge_tree(
                    material_id=material_id,
                    version_id=version_id,
                    user_id=user_id,
                )

            # 阶段 E: 激活并准出
            current_stage = "ready"
            self.repo.update_version_status(
                version_id,
                user_id,
                ParseStatus.READY.value,
                raw_text_storage_key=raw_text_key,
                is_active=True,
            )
            self.repo.update_material_status(
                material_id,
                user_id,
                MaterialStatus.READY.value,
                current_version_id=version_id,
            )
            self.session.commit()

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
            self.session.rollback()
            try:
                error_msg = getattr(exc, "message", str(exc))
                self.repo.update_version_status(
                    version_id=version_id,
                    user_id=user_id,
                    status=ParseStatus.FAILED.value,
                    failed_stage=current_stage,
                    error_message=str(error_msg)[:500],
                )
                self.repo.update_material_status(
                    material_id=material_id,
                    user_id=user_id,
                    status=MaterialStatus.FAILED.value,
                )
                self.session.commit()
            except Exception:
                self.session.rollback()
            raise

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
            chunk_result = split_material_into_snippets(paragraphs)

            self.repo.delete_snippets_by_version(version_id, user_id)
            texts = [s.content for s in chunk_result.snippets]
            vectors = self.embedding.embed_documents(texts)

            new_snippets = [
                MaterialSnippet(
                    user_id=user_id,
                    material_id=material_id,
                    version_id=version_id,
                    snippet_index=s.index,
                    content=s.content,
                    char_length=s.char_count,
                    start_offset=s.start_offset,
                    end_offset=s.end_offset,
                    chapter_title=s.chapter_title,
                    source_info={"source_ref": s.source_ref},
                    embedding=vectors[i] if i < len(vectors) else None,
                )
                for i, s in enumerate(chunk_result.snippets)
            ]
            self.repo.create_snippets(new_snippets)

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
    ) -> int | None:
        """根据细粒度解析流水线状态或资料主状态计算进度百分比 (0-100)。"""
        if parse_status is not None:
            status_map: dict[str, int] = {
                ParseStatus.NOT_STARTED.value: 0,
                ParseStatus.QUEUED.value: 10,
                ParseStatus.PARSING_DOC.value: 30,
                ParseStatus.OCR_PROCESSING.value: 30,
                ParseStatus.EXTRACTING_KNOWLEDGE.value: 60,
                ParseStatus.AUDITING_KNOWLEDGE.value: 75,
                ParseStatus.EMBEDDING_GENERATION.value: 85,
                ParseStatus.READY.value: 100,
                ParseStatus.FAILED.value: 0,
            }
            if parse_status in status_map:
                return status_map[parse_status]

        if material_status == MaterialStatus.READY.value:
            return 100
        if material_status == MaterialStatus.PENDING.value:
            return 0
        if material_status == MaterialStatus.FAILED.value:
            return 0
        if material_status == MaterialStatus.RETAKE_REQUIRED.value:
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
        return self._compose_parse_status(material, version)

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
    ) -> tuple[str | None, int | None]:
        """根据目标版本与资料主状态合成细粒度解析状态与进度百分比。"""
        parse_status: str | None = version.parse_status if version is not None else None
        progress_percentage = MaterialService._calculate_progress_percentage(
            parse_status, material.status
        )
        return parse_status, progress_percentage

    def get_material_detail(
        self,
        *,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Material:
        """获取资料详情（包含历史版本与解析阶段进度），阻断跨租户越权。

        Args:
            material_id: 资料标识。
            user_id: 租户用户标识。

        Returns:
            Material: 包含历史版本与解析阶段进度的资料实体。

        Raises:
            MaterialNotFoundError: 资料不存在或已软删除。
        """
        material = self.get_material(material_id=material_id, user_id=user_id)
        version = self._resolve_material_version(material, user_id)
        parse_status, progress_pct = self._compose_parse_status(material, version)
        material.parse_status = parse_status  # type: ignore[attr-defined]
        material.progress_percentage = progress_pct  # type: ignore[attr-defined]
        key_points_count, page_count = self._compose_version_counts(version, user_id)
        material.key_points_count = key_points_count  # type: ignore[attr-defined]
        material.page_count = page_count  # type: ignore[attr-defined]
        return material

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
    ) -> tuple[list[Material], int]:
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
            tuple[list[Material], int]: (资料实体列表, 总记录数)。
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
        for item in items:
            version = self._pick_loaded_version(item)
            parse_status, progress_pct = self._compose_parse_status(item, version)
            item.parse_status = parse_status  # type: ignore[attr-defined]
            item.progress_percentage = progress_pct  # type: ignore[attr-defined]

        # 批量统计各激活版本考点数（单次分组查询，杜绝列表内逐条 N+1）
        version_ids = [
            version.id for item in items if (version := self._pick_loaded_version(item)) is not None
        ]
        kp_counts = self.repo.count_knowledge_points_by_version_ids(version_ids, resolved_user_id)
        for item in items:
            version = self._pick_loaded_version(item)
            if version is None:
                item.key_points_count = None  # type: ignore[attr-defined]
                item.page_count = None  # type: ignore[attr-defined]
                continue
            item.key_points_count = kp_counts.get(version.id, 0)  # type: ignore[attr-defined]
            item.page_count = len(version.ocr_pages)  # type: ignore[attr-defined]
        return items, total

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

    def trigger_parse(
        self,
        user_id: uuid.UUID,
        material_id: uuid.UUID,
        version_id: uuid.UUID | None = None,
        *,
        sync: bool = False,
    ) -> MaterialVersion:
        """触发或重新调度资料解析流水线。

        Args:
            user_id: 租户用户标识。
            material_id: 资料主键。
            version_id: 可选指定版本标识，默认当前激活版本或最新版本。
            sync: 是否同步阻塞执行。

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
            )

        if target_version.parse_status in {
            ParseStatus.QUEUED.value,
            ParseStatus.PARSING_DOC.value,
            ParseStatus.OCR_PROCESSING.value,
            ParseStatus.EXTRACTING_KNOWLEDGE.value,
            ParseStatus.AUDITING_KNOWLEDGE.value,
            ParseStatus.EMBEDDING_GENERATION.value,
            ParseStatus.READY.value,
        }:
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
        ):
            return target_version

        self.repo.update_material_status(
            material_id,
            user_id,
            MaterialStatus.PARSING.value,
        )
        self.session.commit()

        self._enqueue_parse(material_id, target_version.id, user_id)
        return target_version

    def _enqueue_parse(
        self, material_id: uuid.UUID, version_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        """Dispatch one explicit parse request and expose dispatch failure in DB."""
        try:
            self.queue.enqueue(
                task_name="parse_material_pipeline",
                payload={
                    "material_id": str(material_id),
                    "version_id": str(version_id),
                    "user_id": str(user_id),
                },
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
    "MaterialService",
    "build_material_storage_key",
    "extract_text_from_raw_content",
    "validate_file_magic",
]
