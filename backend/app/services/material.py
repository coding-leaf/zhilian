"""学习资料领域服务编排模块。

统领事务边界并跨外设（Storage, OCR, Embedding, Queue, Idempotency）
与纯函数计算核调度。
严格遵循 AGENTS.md 规范：
- app/services 是全系统唯一允许开启数据库事务的层；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)；
- 结构化脱敏日志 8 要素输出，严禁向日志记录资料全文或敏感密钥。
"""

import hashlib
import logging
import uuid

from sqlalchemy.orm import Session

from app.core.algorithms.material_chunking import split_material_into_snippets
from app.core.algorithms.ocr_quality import (
    OCRPageInput,
    verify_ocr_quality,
)
from app.core.errors import (
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


def extract_text_from_raw_content(content: bytes, file_format: str) -> list[str]:
    """从原始文件二进制中提取段落文本序列。

    Args:
        content: 原生文件二进制。
        file_format: 文件格式扩展名。

    Returns:
        list[str]: 提取的段落文本列表。
    """
    normalized_format = file_format.lower().lstrip(".")
    if normalized_format in ("txt", "md"):
        text = content.decode("utf-8", errors="replace")
    elif normalized_format in ("pdf", "docx", "pptx"):
        text = content.decode("utf-8", errors="ignore")
    else:
        text = ""

    raw_paragraphs = text.split("\n\n") if "\n\n" in text else text.split("\n")
    paragraphs = [p.strip() for p in raw_paragraphs if p.strip()]
    return paragraphs if paragraphs else ([text.strip()] if text.strip() else [])


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
        bucket: str = DEFAULT_MATERIAL_BUCKET,
    ) -> None:
        self.session = session
        self.storage = storage_adapter
        self.ocr = ocr_adapter
        self.embedding = embedding_adapter
        self.queue = queue_adapter
        self.idempotency = idempotency_adapter
        self.repo = material_repo or MaterialRepository(session)
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
    ) -> tuple[Material, MaterialVersion]:
        """上传创建资料：魔数校验、查重秒传、MinIO隔离写入、创建版本并调度异步解析。

        Args:
            user_id: 所属用户标识。
            title: 资料展示标题。
            file_format: 格式扩展名。
            file_size: 文件大小（字节）。
            file_content: 原文件二进制字节流。
            source_type: 导入渠道来源。
            idempotency_key: 可选的幂等键。

        Returns:
            tuple[Material, MaterialVersion]: 创建（或复用）的资料与版本实体元组。

        Raises:
            MaterialInvalidError: 文件内容为空、大小超限、魔数校验失败。
            IdempotencyConflictError: 幂等并发重复提交。
        """
        user_ref = generate_user_ref(user_id)
        clean_format = file_format.lower().lstrip(".")

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
            )

            # 秒传查重检测：检查该用户是否已有完全相同内容哈希的激活版本
            existing_ver = self.repo.find_version_by_hash(user_id, content_hash)
            if existing_ver is not None and existing_ver.parse_status == ParseStatus.READY.value:
                storage_key = existing_ver.storage_key
            else:
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
                parse_status=ParseStatus.QUEUED.value,
            )

            self.session.commit()

            # 5. 调度异步解析流水线入队
            if self.queue is not None:
                self.queue.enqueue(
                    task_name="parse_material_pipeline",
                    payload={
                        "material_id": str(material.id),
                        "version_id": str(version.id),
                        "user_id": str(user_id),
                    },
                    user_id=str(user_id),
                )

            # 6. 持久化幂等完成快照
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

        self.repo.update_material_status(material_id, user_id, MaterialStatus.PARSING.value)
        file_bytes = self.storage.get_object(self.bucket, version.storage_key)
        clean_format = material.file_format.lower().lstrip(".")

        try:
            # 阶段 A: 提取文本与 OCR 质量门禁
            if clean_format in ("png", "jpg", "jpeg", "image"):
                self.repo.update_version_status(
                    version_id, user_id, ParseStatus.OCR_PROCESSING.value
                )
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
                self.repo.create_ocr_pages([ocr_page])

                if not report.is_all_qualified:
                    self.repo.update_version_status(
                        version_id,
                        user_id,
                        ParseStatus.FAILED.value,
                        error_message=page_report.unqualified_reason,
                        failed_stage="ocr_quality_gate",
                    )
                    self.repo.update_material_status(
                        material_id, user_id, MaterialStatus.FAILED.value
                    )
                    self.session.commit()
                    return version

                extracted_text = ocr_result.full_text
                paragraphs = [p.strip() for p in extracted_text.split("\n") if p.strip()]
            else:
                self.repo.update_version_status(version_id, user_id, ParseStatus.PARSING_DOC.value)
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
            self.repo.update_version_status(
                version_id, user_id, ParseStatus.EXTRACTING_KNOWLEDGE.value
            )
            chunk_result = split_material_into_snippets(paragraphs)

            if not chunk_result.snippets:
                self.repo.update_version_status(
                    version_id,
                    user_id,
                    ParseStatus.FAILED.value,
                    failed_stage="chunking",
                    error_message="未切分出有效知识切片",
                )
                self.repo.update_material_status(material_id, user_id, MaterialStatus.FAILED.value)
                self.session.commit()
                raise MaterialInvalidError("资料有效内容不足，未切分出有效知识片段")

            # 阶段 C: 批量向量化与切片持久化
            self.repo.update_version_status(
                version_id, user_id, ParseStatus.EMBEDDING_GENERATION.value
            )
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

            self.repo.create_snippets(snippets_to_save)

            # 阶段 D: 激活并准出
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

        except Exception:
            self.session.rollback()
            raise

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

        for page_num, image_bytes in page_replaces.items():
            page = self.repo.get_ocr_page(version_id, page_num, user_id)
            if page is None:
                raise MaterialNotFoundError(f"未找到页码为 {page_num} 的 OCR 记录")

            if page.reshoot_count >= 3:
                raise ReshootLimitExceededError("页面重拍次数已达上限熔断，请重新上传清晰文件")

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
        material = self.repo.get_material_by_id(material_id, user_id, include_deleted=False)
        if material is None:
            raise MaterialNotFoundError("请求的学习资料不存在或已被删除")
        return material

    def list_materials(
        self,
        *,
        user_id: uuid.UUID,
        is_deleted: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Material], int]:
        """分页获取用户所属资料列表及符合条件总记录数。

        Args:
            user_id: 租户用户标识。
            is_deleted: 软删除状态过滤。
            limit: 单页记录数限制。
            offset: 偏移游标。

        Returns:
            tuple[list[Material], int]: (资料实体列表, 总记录数)。
        """
        return self.repo.list_materials_by_user(
            user_id=user_id,
            is_deleted=is_deleted,
            limit=limit,
            offset=offset,
        )

    def soft_delete_material(
        self,
        *,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """软删除资料：标记 is_deleted=True，不破坏历史练习记录。

        Args:
            material_id: 资料标识。
            user_id: 租户用户标识。

        Returns:
            bool: 成功删除返回 True。

        Raises:
            MaterialNotFoundError: 资料不存在或已删除。
        """
        success = self.repo.soft_delete_material(material_id, user_id)
        if not success:
            raise MaterialNotFoundError("请求的学习资料不存在或已被删除")
        self.session.commit()
        return True

    def hard_delete_material(
        self,
        *,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """物理级联销毁资料：删除切片、版本、OCR页、资料表记录及 MinIO 对象存储文件。

        Args:
            material_id: 资料标识。
            user_id: 租户用户标识。

        Returns:
            bool: 成功删除返回 True。

        Raises:
            MaterialNotFoundError: 资料不存在。
        """
        material = self.repo.get_material_by_id(material_id, user_id, include_deleted=True)
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

        self.repo.hard_delete_material(material_id, user_id)
        self.session.commit()

        # 同步清理存储文件
        for storage_key in keys_to_purge:
            try:
                self.storage.delete_object(self.bucket, storage_key)
            except Exception as exc:
                logger.warning(
                    "failed to delete storage object",
                    extra={"error_code": 0, "details": str(exc)},
                )

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
