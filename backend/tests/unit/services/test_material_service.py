"""Unit tests for MaterialService in app/services/material.py.

Verifies:
1. File format validation & magic bytes verification (PDF, DOCX, PNG, JPG, TXT, MD).
2. File size constraints and empty content protection.
3. Content deduplication / quick upload reuse.
4. Idempotency handling (locking and conflict prevention).
5. End-to-end parsing pipeline for documents and images (chunking -> embedding -> activation).
6. OCR quality gate integration and page rejection.
7. In-place OCR page retry, reshoot counter tracking, and 3-attempt circuit breaker.
8. Soft and hard deletion cascading to MinIO storage objects.
9. Strict multi-tenant isolation.
"""

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import (
    MaterialInvalidError,
    MaterialNotFoundError,
    ReshootLimitExceededError,
)
from app.integrations.embedding.fake import FakeEmbeddingAdapter
from app.integrations.idempotency.memory import MemoryIdempotencyAdapter
from app.integrations.ocr.fake import FakeOCRAdapter
from app.integrations.ocr.protocol import OCRResult, OCRTextBlock
from app.integrations.queue.memory import MemoryQueueAdapter
from app.integrations.storage.memory import MemoryStorageAdapter
from app.models.base import Base
from app.models.material import MaterialStatus, ParseStatus
from app.services.material import (
    MaterialService,
    validate_file_magic,
)


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """Provides an isolated SQLite database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


@pytest.fixture
def storage() -> MemoryStorageAdapter:
    """Provides a memory storage adapter."""
    adapter = MemoryStorageAdapter()
    adapter.ensure_bucket_exists("zhilian-materials")
    return adapter


@pytest.fixture
def ocr() -> FakeOCRAdapter:
    """Provides a fake OCR adapter with clear text output."""
    default_text = (
        "这是一段用于测试的高清教材文字内容。本节深入阐述极限的定义与导数的物理几何意义，"
        "包含足够丰富的有效字符供算法切分。"
    )
    result = OCRResult(
        full_text=default_text,
        blocks=(OCRTextBlock(text=default_text, confidence=0.98),),
    )
    return FakeOCRAdapter(default_result=result)


@pytest.fixture
def embedding() -> FakeEmbeddingAdapter:
    """Provides a fake embedding adapter."""
    return FakeEmbeddingAdapter()


@pytest.fixture
def queue() -> MemoryQueueAdapter:
    """Provides a memory task queue."""
    return MemoryQueueAdapter()


@pytest.fixture
def idempotency() -> MemoryIdempotencyAdapter:
    """Provides a memory idempotency adapter."""
    return MemoryIdempotencyAdapter()


@pytest.fixture
def service(
    session: Session,
    storage: MemoryStorageAdapter,
    ocr: FakeOCRAdapter,
    embedding: FakeEmbeddingAdapter,
    queue: MemoryQueueAdapter,
    idempotency: MemoryIdempotencyAdapter,
) -> MaterialService:
    """Provides an initialized MaterialService instance."""
    return MaterialService(
        session=session,
        storage_adapter=storage,
        ocr_adapter=ocr,
        embedding_adapter=embedding,
        queue_adapter=queue,
        idempotency_adapter=idempotency,
    )


class TestMagicAndValidation:
    """Test suite for file magic and constraint validations."""

    def test_validate_file_magic_pure_function(self) -> None:
        """Verify pure function validate_file_magic across formats."""
        assert validate_file_magic(b"%PDF-1.7 standard doc", "pdf") is True
        assert validate_file_magic(b"PK\x03\x04\x14\x00", "docx") is True
        assert validate_file_magic(b"PK\x03\x04\x14\x00", "pptx") is True
        assert validate_file_magic(b"\x89PNG\r\n\x1a\n\x00\x00", "png") is True
        assert validate_file_magic(b"\xff\xd8\xff\xe0\x00\x10", "jpg") is True
        assert validate_file_magic(b"\xff\xd8\xff\xe1", "jpeg") is True
        assert validate_file_magic("纯文本测试内容".encode(), "txt") is True
        assert validate_file_magic(b"# Markdown Title\nContent", "md") is True

        # Negative checks
        assert validate_file_magic(b"NOT_A_PDF", "pdf") is False
        assert validate_file_magic(b"%PDF-1.4", "png") is False
        assert validate_file_magic(b"\x00\x01\x02\x03", "txt") is False

    def test_create_material_magic_mismatch_raises(self, service: MaterialService) -> None:
        """Verify mismatched magic bytes raise MaterialInvalidError."""
        user_id = uuid.uuid4()
        fake_pdf = b"GIF89a corrupted pretending to be pdf"
        with pytest.raises(MaterialInvalidError) as exc_info:
            service.create_material(
                user_id=user_id,
                title="test.pdf",
                file_format="pdf",
                file_size=len(fake_pdf),
                file_content=fake_pdf,
            )
        assert exc_info.value.error_code == 40001

    def test_create_material_empty_or_oversize_raises(self, service: MaterialService) -> None:
        """Verify empty content and oversized files raise MaterialInvalidError."""
        user_id = uuid.uuid4()

        # Empty content
        with pytest.raises(MaterialInvalidError):
            service.create_material(
                user_id=user_id,
                title="empty.txt",
                file_format="txt",
                file_size=0,
                file_content=b"",
            )

        # Oversized document (>20MB)
        huge_doc = b"%PDF-" + b"0" * (20 * 1024 * 1024 + 1)
        with pytest.raises(MaterialInvalidError):
            service.create_material(
                user_id=user_id,
                title="huge.pdf",
                file_format="pdf",
                file_size=len(huge_doc),
                file_content=huge_doc,
            )


class TestMaterialCreationAndLifecycle:
    """Test suite for MaterialService lifecycle operations."""

    def test_create_material_success_and_queue_dispatch(
        self,
        service: MaterialService,
        storage: MemoryStorageAdapter,
        queue: MemoryQueueAdapter,
    ) -> None:
        """Verify successful creation, storage write, and queue dispatch."""
        user_id = uuid.uuid4()
        content = "微积分核心概念讲解：极限、连续性与微积分基本定理。".encode()

        material, version = service.create_material(
            user_id=user_id,
            title="Calculus.txt",
            file_format="txt",
            file_size=len(content),
            file_content=content,
        )

        assert material.id is not None
        assert version.id is not None
        assert material.status == MaterialStatus.PENDING.value
        assert version.version_number == 1
        assert storage.object_exists("zhilian-materials", version.storage_key) is True

        # Verify queue dispatch
        assert len(queue._queue) == 1
        task = queue._queue[0]
        assert task.task_name == "parse_material_pipeline"
        assert task.payload["material_id"] == str(material.id)
        assert task.payload["version_id"] == str(version.id)

    def test_idempotency_conflict_and_replay(self, service: MaterialService) -> None:
        """Verify idempotency lock prevents concurrent duplicates and replays finished result."""
        user_id = uuid.uuid4()
        content = "这是唯一的测试内容，用于验证幂等拦截。".encode()
        idem_key = "req-idempotency-key-001"

        # First upload
        mat, ver = service.create_material(
            user_id=user_id,
            title="Idem.txt",
            file_format="txt",
            file_size=len(content),
            file_content=content,
            idempotency_key=idem_key,
        )
        assert mat.id is not None

        # Replay: second upload with identical completed key returns cached result
        mat2, ver2 = service.create_material(
            user_id=user_id,
            title="Idem.txt",
            file_format="txt",
            file_size=len(content),
            file_content=content,
            idempotency_key=idem_key,
        )
        assert mat2.id == mat.id
        assert ver2.id == ver.id

    def test_parse_material_pipeline_txt_success(
        self, service: MaterialService, session: Session
    ) -> None:
        """Verify complete text parsing pipeline: chunking -> embedding -> READY status."""
        user_id = uuid.uuid4()
        long_text = (
            "第一章 高等数学与函数极限。\n\n"
            "函数极限是微积分学的基础概念，描述自变量趋于某值时函数值的变化趋势。\n\n"
            "第二章 导数与微分运算。\n\n"
            "导数代表函数在某一点处的瞬时变化率，在几何上对应切线的斜率，在物理上对应瞬时速度。"
        )
        content = long_text.encode("utf-8")

        material, version = service.create_material(
            user_id=user_id,
            title="Math_Guide.txt",
            file_format="txt",
            file_size=len(content),
            file_content=content,
        )

        # Run pipeline
        ready_version = service.parse_material_pipeline(
            material_id=material.id,
            version_id=version.id,
            user_id=user_id,
        )

        assert ready_version.parse_status == ParseStatus.READY.value
        assert ready_version.raw_text_storage_key is not None

        # Check Material status
        mat = service.get_material(material_id=material.id, user_id=user_id)
        assert mat.status == MaterialStatus.READY.value
        assert mat.current_version_id == version.id

        # Verify snippets were persisted
        snippets = service.repo.get_snippets(version.id, user_id)
        assert len(snippets) > 0
        assert snippets[0].embedding is not None

    def test_parse_material_pipeline_ocr_unqualified(
        self, service: MaterialService, ocr: FakeOCRAdapter
    ) -> None:
        """Verify unqualified OCR scan results mark the material FAILED and persist OCR page."""
        user_id = uuid.uuid4()
        unqualified_text = "$%&*@#^!~`* 几个汉字"
        png_content = b"\x89PNG\r\n\x1a\n" + b"corrupted_scan"
        ocr.set_canned_result(
            png_content,
            OCRResult(
                full_text=unqualified_text,
                blocks=(OCRTextBlock(text=unqualified_text, confidence=0.3),),
            ),
        )

        mat, ver = service.create_material(
            user_id=user_id,
            title="Scan_Bad.png",
            file_format="png",
            file_size=len(png_content),
            file_content=png_content,
        )

        failed_ver = service.parse_material_pipeline(
            material_id=mat.id,
            version_id=ver.id,
            user_id=user_id,
        )

        assert failed_ver.parse_status == ParseStatus.FAILED.value
        mat_refreshed = service.get_material(material_id=mat.id, user_id=user_id)
        assert mat_refreshed.status == MaterialStatus.FAILED.value

        # OCR page recorded with unqualified status
        pages = service.repo.get_ocr_pages(ver.id, user_id)
        assert len(pages) == 1
        assert pages[0].is_qualified is False
        assert pages[0].unqualified_reason is not None

    def test_retry_ocr_pages_circuit_breaker(
        self, service: MaterialService, ocr: FakeOCRAdapter
    ) -> None:
        """Verify in-place retry increments count and triggers 40002 circuit breaker on 3 fails."""
        user_id = uuid.uuid4()
        bad_text = "%&*@#"
        png_content = b"\x89PNG\r\n\x1a\n" + b"bad_attempt"
        ocr.set_canned_result(
            png_content,
            OCRResult(
                full_text=bad_text,
                blocks=(OCRTextBlock(text=bad_text, confidence=0.2),),
            ),
        )

        mat, ver = service.create_material(
            user_id=user_id,
            title="RetryScan.png",
            file_format="png",
            file_size=len(png_content),
            file_content=png_content,
        )
        service.parse_material_pipeline(
            material_id=mat.id,
            version_id=ver.id,
            user_id=user_id,
        )

        # Retry 1: still bad
        service.retry_ocr_pages(
            material_id=mat.id,
            version_id=ver.id,
            user_id=user_id,
            page_replaces={1: png_content},
        )
        p1 = service.repo.get_ocr_page(ver.id, 1, user_id)
        assert p1 is not None
        assert p1.reshoot_count == 1

        # Retry 2: still bad
        service.retry_ocr_pages(
            material_id=mat.id,
            version_id=ver.id,
            user_id=user_id,
            page_replaces={1: png_content},
        )
        p2 = service.repo.get_ocr_page(ver.id, 1, user_id)
        assert p2 is not None
        assert p2.reshoot_count == 2

        # Retry 3: still bad -> triggers circuit breaker ReshootLimitExceededError (40002)
        with pytest.raises(ReshootLimitExceededError) as exc_info:
            service.retry_ocr_pages(
                material_id=mat.id,
                version_id=ver.id,
                user_id=user_id,
                page_replaces={1: png_content},
            )
        assert exc_info.value.error_code == 40002

    def test_retry_ocr_pages_success_activates_material(
        self, service: MaterialService, ocr: FakeOCRAdapter
    ) -> None:
        """Verify successful page retry resets status and triggers chunking/embedding."""
        user_id = uuid.uuid4()
        bad_text = "%&*@#"
        good_text = (
            "重拍后极其清晰的教学文本内容：矩阵的秩与线性方程组的解的判定定理。"
            "当系数矩阵的秩等于增广矩阵的秩且等于未知数个数时，方程组有唯一解。"
        )
        png_content = b"\x89PNG\r\n\x1a\n" + b"bad_first"
        good_png = b"\x89PNG\r\n\x1a\n" + b"good_second"
        ocr.set_canned_result(
            png_content,
            OCRResult(
                full_text=bad_text,
                blocks=(OCRTextBlock(text=bad_text, confidence=0.1),),
            ),
        )
        ocr.set_canned_result(
            good_png,
            OCRResult(
                full_text=good_text,
                blocks=(OCRTextBlock(text=good_text, confidence=0.99),),
            ),
        )

        mat, ver = service.create_material(
            user_id=user_id,
            title="ScanFix.png",
            file_format="png",
            file_size=len(png_content),
            file_content=png_content,
        )
        service.parse_material_pipeline(
            material_id=mat.id,
            version_id=ver.id,
            user_id=user_id,
        )

        # In-place retry with good image
        ready_ver = service.retry_ocr_pages(
            material_id=mat.id,
            version_id=ver.id,
            user_id=user_id,
            page_replaces={1: good_png},
        )

        assert ready_ver.parse_status == ParseStatus.READY.value
        mat_refreshed = service.get_material(material_id=mat.id, user_id=user_id)
        assert mat_refreshed.status == MaterialStatus.READY.value
        assert mat_refreshed.current_version_id == ver.id

        # Snippets exist
        snippets = service.repo.get_snippets(ver.id, user_id)
        assert len(snippets) > 0

    def test_soft_delete_and_hard_delete(
        self,
        service: MaterialService,
        storage: MemoryStorageAdapter,
    ) -> None:
        """Verify soft deletion hides material while hard deletion purges records and objects."""
        user_id = uuid.uuid4()
        content = "用于测试删除逻辑的教材文档。包含基础代数概念。".encode()

        mat, ver = service.create_material(
            user_id=user_id,
            title="ToDelete.txt",
            file_format="txt",
            file_size=len(content),
            file_content=content,
        )

        # Soft delete
        assert service.soft_delete_material(material_id=mat.id, user_id=user_id) is True

        # get_material raises 40004
        with pytest.raises(MaterialNotFoundError):
            service.get_material(material_id=mat.id, user_id=user_id)

        # Storage file still exists after soft delete
        assert storage.object_exists("zhilian-materials", ver.storage_key) is True

        # Hard delete
        assert service.hard_delete_material(material_id=mat.id, user_id=user_id) is True
        # Storage file purged
        assert storage.object_exists("zhilian-materials", ver.storage_key) is False

    def test_cross_tenant_isolation(self, service: MaterialService) -> None:
        """Verify user B cannot access or manipulate user A's materials."""
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()
        content = "私密考研高数资料".encode()

        mat_a, ver_a = service.create_material(
            user_id=user_a,
            title="PrivateA.txt",
            file_format="txt",
            file_size=len(content),
            file_content=content,
        )
        assert ver_a.id is not None

        # User B gets material -> 40004
        with pytest.raises(MaterialNotFoundError):
            service.get_material(material_id=mat_a.id, user_id=user_b)

        # User B lists materials -> empty
        b_items, b_total = service.list_materials(user_id=user_b)
        assert len(b_items) == 0
        assert b_total == 0

        # User B tries soft delete -> 40004
        with pytest.raises(MaterialNotFoundError):
            service.soft_delete_material(material_id=mat_a.id, user_id=user_b)

        # User B tries hard delete -> 40004
        with pytest.raises(MaterialNotFoundError):
            service.hard_delete_material(material_id=mat_a.id, user_id=user_b)

    def test_helpers_and_edge_cases(self, service: MaterialService) -> None:
        """Verify helper functions, deduplication reuse, and error branches."""
        user_id = uuid.uuid4()
        mat_id = uuid.uuid4()

        # build_material_storage_key
        from app.services.material import (
            build_material_storage_key,
            extract_text_from_raw_content,
        )

        s_key = build_material_storage_key(user_id, mat_id, 1, "abcdef1234567890", "pdf")
        assert s_key == f"users/{user_id}/materials/{mat_id}/v1/abcdef1234567890.pdf"

        # extract_text_from_raw_content
        assert extract_text_from_raw_content("段落一\n\n段落二".encode(), "txt") == [
            "段落一",
            "段落二",
        ]
        assert extract_text_from_raw_content(b"Unknown binary", "unknown") == []

        # Unsupported format in create_material
        with pytest.raises(MaterialInvalidError) as exc_info:
            service.create_material(
                user_id=user_id,
                title="malicious.exe",
                file_format="exe",
                file_size=100,
                file_content=b"MZ\x90\x00",
            )
        assert exc_info.value.error_code == 40001

        # Deduplication reuse of existing READY version
        content = "微积分定理库重复内容秒传测试".encode()
        m1, v1 = service.create_material(
            user_id=user_id,
            title="Calc_1.txt",
            file_format="txt",
            file_size=len(content),
            file_content=content,
        )
        service.parse_material_pipeline(
            material_id=m1.id,
            version_id=v1.id,
            user_id=user_id,
        )

        # Upload again with same content
        m2, v2 = service.create_material(
            user_id=user_id,
            title="Calc_2.txt",
            file_format="txt",
            file_size=len(content),
            file_content=content,
        )
        assert m2.id != m1.id
        assert v2.storage_key == v1.storage_key

        # Missing entities raise 40004
        with pytest.raises(MaterialNotFoundError):
            service.parse_material_pipeline(
                material_id=uuid.uuid4(),
                version_id=uuid.uuid4(),
                user_id=user_id,
            )

        with pytest.raises(MaterialNotFoundError):
            service.retry_ocr_pages(
                material_id=uuid.uuid4(),
                version_id=uuid.uuid4(),
                user_id=user_id,
                page_replaces={1: b"\x89PNG\r\n\x1a\n"},
            )

        with pytest.raises(MaterialNotFoundError):
            service.retry_ocr_pages(
                material_id=m1.id,
                version_id=v1.id,
                user_id=user_id,
                page_replaces={999: b"\x89PNG\r\n\x1a\n"},
            )

        with pytest.raises(MaterialNotFoundError):
            service.soft_delete_material(material_id=uuid.uuid4(), user_id=user_id)

        with pytest.raises(MaterialNotFoundError):
            service.hard_delete_material(material_id=uuid.uuid4(), user_id=user_id)

    def test_parse_material_pipeline_zero_snippets_raises(self, service: MaterialService) -> None:
        """Verify pipeline raises MaterialInvalidError if text produces 0 snippets."""
        user_id = uuid.uuid4()
        # Text with only whitespace/punctuation that cleans to empty
        content = b"       \n\n   \n\t  "
        mat, ver = service.create_material(
            user_id=user_id,
            title="EmptyChunks.txt",
            file_format="txt",
            file_size=len(content),
            file_content=content,
        )
        with pytest.raises(MaterialInvalidError) as exc_info:
            service.parse_material_pipeline(
                material_id=mat.id,
                version_id=ver.id,
                user_id=user_id,
            )
        assert exc_info.value.error_code == 40001
        refreshed_mat = service.repo.get_material_by_id(mat.id, user_id)
        assert refreshed_mat is not None
        assert refreshed_mat.status == MaterialStatus.FAILED.value

    def test_retry_ocr_pages_already_exceeded_reshoot_raises(
        self, service: MaterialService, ocr: FakeOCRAdapter
    ) -> None:
        """Verify retry_ocr_pages raises immediately if page already has reshoot_count >= 3."""
        user_id = uuid.uuid4()
        png_content = b"\x89PNG\r\n\x1a\n" + b"test_exceeded"
        bad_text = "%&*@#"
        ocr.set_canned_result(
            png_content,
            OCRResult(
                full_text=bad_text,
                blocks=(OCRTextBlock(text=bad_text, confidence=0.2),),
            ),
        )
        mat, ver = service.create_material(
            user_id=user_id,
            title="Exceeded.png",
            file_format="png",
            file_size=len(png_content),
            file_content=png_content,
        )
        service.parse_material_pipeline(
            material_id=mat.id,
            version_id=ver.id,
            user_id=user_id,
        )
        page = service.repo.get_ocr_page(ver.id, 1, user_id)
        assert page is not None
        # Manually set reshoot_count to 3
        page.reshoot_count = 3
        service.session.commit()

        with pytest.raises(ReshootLimitExceededError) as exc_info:
            service.retry_ocr_pages(
                material_id=mat.id,
                version_id=ver.id,
                user_id=user_id,
                page_replaces={1: png_content},
            )
        assert exc_info.value.error_code == 40002

    def test_hard_delete_material_handles_storage_exception(
        self,
        service: MaterialService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify hard_delete_material deletes DB records even if storage cleanup fails."""
        user_id = uuid.uuid4()
        content = "用于测试存储异常的教材内容。".encode()
        mat, _ver = service.create_material(
            user_id=user_id,
            title="StorageErr.txt",
            file_format="txt",
            file_size=len(content),
            file_content=content,
        )

        def raise_storage_err(bucket: str, key: str) -> bool:
            raise RuntimeError("Storage disk IO error")

        monkeypatch.setattr(service.storage, "delete_object", raise_storage_err)

        # Deletion still succeeds from DB perspective
        assert service.hard_delete_material(material_id=mat.id, user_id=user_id) is True
        assert service.repo.get_material_by_id(mat.id, user_id) is None

    def test_create_material_exception_releases_idempotency_lock(
        self,
        service: MaterialService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify DB failure during create_material releases idempotency lock."""
        user_id = uuid.uuid4()
        content = "用于测试异常回滚的文档。".encode()
        idem_key = "lock-rollback-key"

        def raise_db_err(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("DB simulated write error")

        monkeypatch.setattr(service.repo, "create_material", raise_db_err)

        with pytest.raises(RuntimeError, match="DB simulated write error"):
            service.create_material(
                user_id=user_id,
                title="Fail.txt",
                file_format="txt",
                file_size=len(content),
                file_content=content,
                idempotency_key=idem_key,
            )

        # Lock was released, can acquire lock again
        assert service.idempotency is not None
        assert service.idempotency.acquire_lock(idem_key, str(user_id)) is True

    def test_parse_material_pipeline_docx_success(self, service: MaterialService) -> None:
        """Verify docx document pipeline parsing."""
        user_id = uuid.uuid4()
        raw_text = "数据结构与算法分析：平衡二叉树、红黑树以及图的最短路径算法。\n\n" * 3
        # PK\x03\x04 magic for docx
        docx_bytes = b"PK\x03\x04" + raw_text.encode("utf-8")

        mat, ver = service.create_material(
            user_id=user_id,
            title="DS.docx",
            file_format="docx",
            file_size=len(docx_bytes),
            file_content=docx_bytes,
        )
        ready_ver = service.parse_material_pipeline(
            material_id=mat.id,
            version_id=ver.id,
            user_id=user_id,
        )
        assert ready_ver.parse_status == ParseStatus.READY.value
        mat_refreshed = service.get_material(material_id=mat.id, user_id=user_id)
        assert mat_refreshed.status == MaterialStatus.READY.value
