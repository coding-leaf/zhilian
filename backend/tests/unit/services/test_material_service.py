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
from app.models.material import MaterialOCRPage, MaterialStatus, ParseStatus
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
        assert failed_ver.failed_stage == "ocr_quality_gate"
        mat_refreshed = service.get_material(material_id=mat.id, user_id=user_id)
        # OCR 门禁失败语义为「待重拍」而非终态失败；资料仍不可用于出题 (非 READY)
        assert mat_refreshed.status == MaterialStatus.RETAKE_REQUIRED.value
        assert mat_refreshed.status != MaterialStatus.READY.value

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
        # MAT-001：同哈希内容必须各自持有独立物理对象，禁止跨资料复用 storage_key
        assert v2.storage_key != v1.storage_key

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
        """Verify docx document pipeline parsing with a real OOXML ZIP container."""
        from app.cli.fixtures import build_minimal_docx

        user_id = uuid.uuid4()
        paragraphs = [
            "数据结构与算法分析：平衡二叉树、红黑树以及图的最短路径算法。",
            "栈遵循后进先出原则，队列遵循先进先出原则，二者是最基础的线性结构。",
            "二叉搜索树的中序遍历结果有序，平均查找时间复杂度为 O(log n)。",
            "Dijkstra 算法用于求解边权非负图的单源最短路径问题。",
            "归并排序与快速排序平均时间复杂度均为 O(n log n)。",
            "哈希表通过散列函数实现平均 O(1) 的查找性能，需要处理冲突。",
        ]
        docx_bytes = build_minimal_docx(paragraphs)

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

    def test_list_materials_and_versions(self, service: MaterialService) -> None:
        """Verify list_materials and list_material_versions."""
        user_id = uuid.uuid4()
        c1 = b"Sample text content 1"
        c2 = b"Sample text content 2"
        mat1, _ = service.create_material(
            user_id=user_id,
            title="Math-Analysis.txt",
            file_format="txt",
            file_size=len(c1),
            file_content=c1,
        )
        _mat2, _ = service.create_material(
            user_id=user_id,
            title="Algebra.txt",
            file_format="txt",
            file_size=len(c2),
            file_content=c2,
        )

        items, total = service.list_materials(user_id=user_id, keyword="Math")
        assert total == 1
        assert items[0].id == mat1.id
        assert getattr(items[0], "parse_status", None) == ParseStatus.QUEUED.value
        assert getattr(items[0], "progress_percentage", None) == 10

        mat_detail = service.get_material_detail(material_id=mat1.id, user_id=user_id)
        assert getattr(mat_detail, "parse_status", None) == ParseStatus.QUEUED.value
        assert getattr(mat_detail, "progress_percentage", None) == 10

        _items_all, total_all = service.list_materials(
            user_id=user_id, status=MaterialStatus.PENDING.value
        )
        assert total_all == 2

        # parsing 语义聚合 pending + parsing 两个阶段
        _items_parsing, total_parsing = service.list_materials(user_id=user_id, status="parsing")
        assert total_parsing == 2

        # completed 别名收敛到 ready，当前无 ready 资料
        _items_completed, total_completed = service.list_materials(
            user_id=user_id, status="completed"
        )
        assert total_completed == 0

        # retake_required 现已映射为真实资料状态，仅有 pending/parsing 资料时应过滤为空
        _items_retake, total_retake = service.list_materials(
            user_id=user_id, status="retake_required"
        )
        assert total_retake == 0
        assert _items_retake == []

        versions = service.list_material_versions(user_id=user_id, material_id=mat1.id)
        assert len(versions) == 1

        with pytest.raises(MaterialNotFoundError):
            service.list_material_versions(user_id=user_id, material_id=uuid.uuid4())

    def test_list_materials_resolves_parse_status_without_n_plus_one(
        self,
        service: MaterialService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """列表装配解析状态须基于预加载版本集合，禁止逐条查询版本表 (N+1 回归防护)。

        同时覆盖两条版本选择分支：
        - 非命中分支：``current_version_id`` 为空，回退取最新版本 (queued/10)；
        - 命中分支：解析完成后 ``current_version_id`` 绑定就绪版本 (ready/100)。
        """
        user_id = uuid.uuid4()
        for index in range(3):
            content = f"用于验证列表状态装配的教材内容 {index}".encode()
            service.create_material(
                user_id=user_id,
                title=f"N1-{index}.txt",
                file_format="txt",
                file_size=len(content),
                file_content=content,
            )

        # 完成其中一个资料的解析，使其绑定 current_version_id，覆盖命中分支
        created_items, created_total = service.repo.list_materials_by_user(user_id=user_id)
        assert created_total == 3
        ready_material = created_items[0]
        ready_version = service.repo.get_latest_version(ready_material.id, user_id)
        assert ready_version is not None
        service.parse_material_pipeline(
            material_id=ready_material.id,
            version_id=ready_version.id,
            user_id=user_id,
        )

        query_counts = {"by_id": 0, "latest": 0}
        original_by_id = service.repo.get_version_by_id
        original_latest = service.repo.get_latest_version

        def counting_by_id(version_id: uuid.UUID, uid: uuid.UUID) -> object:  # type: ignore[no-untyped-def]
            query_counts["by_id"] += 1
            return original_by_id(version_id, uid)

        def counting_latest(material_id: uuid.UUID, uid: uuid.UUID) -> object:  # type: ignore[no-untyped-def]
            query_counts["latest"] += 1
            return original_latest(material_id, uid)

        monkeypatch.setattr(service.repo, "get_version_by_id", counting_by_id)
        monkeypatch.setattr(service.repo, "get_latest_version", counting_latest)

        items, total = service.list_materials(user_id=user_id)

        # 断言列表路径不再逐条查询版本表
        assert total == 3
        assert query_counts["by_id"] == 0
        assert query_counts["latest"] == 0

        # 断言装配结果与逐条查询语义等价
        status_by_id = {item.id: item for item in items}
        refreshed_ready = status_by_id[ready_material.id]
        assert getattr(refreshed_ready, "parse_status", None) == ParseStatus.READY.value
        assert getattr(refreshed_ready, "progress_percentage", None) == 100

        for item in items:
            if item.id == ready_material.id:
                continue
            assert getattr(item, "parse_status", None) == ParseStatus.QUEUED.value
            assert getattr(item, "progress_percentage", None) == 10

    def test_switch_material_version_flow(self, service: MaterialService) -> None:
        """Verify switch_material_version success and error conditions."""
        user_id = uuid.uuid4()
        c = b"Text content for version testing\n\n" * 5
        mat, ver = service.create_material(
            user_id=user_id,
            title="SwitchTest.txt",
            file_format="txt",
            file_size=len(c),
            file_content=c,
        )

        # Target version not ready raises error
        with pytest.raises(MaterialInvalidError, match="尚未解析完成"):
            service.switch_material_version(
                user_id=user_id,
                material_id=mat.id,
                version_id=ver.id,
            )

        # Parse version to READY
        service.parse_material_pipeline(
            material_id=mat.id,
            version_id=ver.id,
            user_id=user_id,
        )

        # Switch version successfully
        updated_mat = service.switch_material_version(
            user_id=user_id,
            material_id=mat.id,
            version_id=ver.id,
        )
        assert updated_mat.current_version_id == ver.id

        # Not found errors
        with pytest.raises(MaterialNotFoundError):
            service.switch_material_version(
                user_id=user_id,
                material_id=uuid.uuid4(),
                version_id=ver.id,
            )
        with pytest.raises(MaterialNotFoundError):
            service.switch_material_version(
                user_id=user_id,
                material_id=mat.id,
                version_id=uuid.uuid4(),
            )

    def test_trigger_parse_sync_and_async(self, service: MaterialService) -> None:
        """Verify trigger_parse both sync and async modes."""
        user_id = uuid.uuid4()
        c = b"Sync and async parse triggering test\n\n" * 4
        mat, ver = service.create_material(
            user_id=user_id,
            title="TriggerTest.txt",
            file_format="txt",
            file_size=len(c),
            file_content=c,
        )

        # Async trigger marks queued
        ver_queued = service.trigger_parse(
            user_id=user_id,
            material_id=mat.id,
            version_id=ver.id,
            sync=False,
        )
        assert ver_queued.parse_status == ParseStatus.QUEUED.value

        # Sync trigger executes pipeline
        ver_ready = service.trigger_parse(
            user_id=user_id,
            material_id=mat.id,
            version_id=ver.id,
            sync=True,
        )
        assert ver_ready.parse_status == ParseStatus.READY.value

        # Material not found
        with pytest.raises(MaterialNotFoundError):
            service.trigger_parse(user_id=user_id, material_id=uuid.uuid4())

    def test_reshoot_material_page_service(self, service: MaterialService) -> None:
        """Verify reshoot_material_page service logic."""
        user_id = uuid.uuid4()
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"fake png data for reshoot"
        mat, ver = service.create_material(
            user_id=user_id,
            title="ReshootMat.png",
            file_format="png",
            file_size=len(png_bytes),
            file_content=png_bytes,
        )

        # Create initial OCR page record first
        ocr_page = MaterialOCRPage(
            version_id=ver.id,
            material_id=mat.id,
            user_id=user_id,
            page_number=1,
            image_storage_key="materials/test/page_1.png",
            raw_text="Initial OCR text",
            valid_char_count=16,
            gibberish_ratio=0.0,
            is_qualified=True,
        )
        service.repo.create_ocr_pages([ocr_page])

        # Reshoot page 1
        page = service.reshoot_material_page(
            user_id=user_id,
            material_id=mat.id,
            page_index=1,
            file_content=png_bytes,
            version_id=ver.id,
        )
        assert page.page_number == 1
        assert page.reshoot_count == 1

        # Reshoot errors
        with pytest.raises(MaterialNotFoundError):
            service.reshoot_material_page(
                user_id=uuid.uuid4(),
                material_id=uuid.uuid4(),
                page_index=1,
                file_content=png_bytes,
            )

    def test_same_hash_uploads_own_independent_storage_object(
        self,
        service: MaterialService,
        storage: MemoryStorageAdapter,
    ) -> None:
        """MAT-001 回归：同哈希资料必须各自持有独立物理对象，硬删源资料不损坏副本。"""
        user_id = uuid.uuid4()
        content = "秒传数据完整性回归：同哈希资料必须各自持有独立对象。".encode()

        mat_a, ver_a = service.create_material(
            user_id=user_id,
            title="Source.txt",
            file_format="txt",
            file_size=len(content),
            file_content=content,
        )
        service.parse_material_pipeline(material_id=mat_a.id, version_id=ver_a.id, user_id=user_id)
        source_key = service.repo.get_version_by_id(ver_a.id, user_id).storage_key  # type: ignore[union-attr]

        mat_b, ver_b = service.create_material(
            user_id=user_id,
            title="Copy.txt",
            file_format="txt",
            file_size=len(content),
            file_content=content,
        )
        copy_key = service.repo.get_version_by_id(ver_b.id, user_id).storage_key  # type: ignore[union-attr]

        assert mat_b.id != mat_a.id
        assert copy_key != source_key
        assert storage.object_exists("zhilian-materials", copy_key) is True

        # 硬删源资料后，副本资料的对象必须仍然存在并可被流水线取用
        assert service.hard_delete_material(material_id=mat_a.id, user_id=user_id) is True
        assert storage.object_exists("zhilian-materials", source_key) is False
        assert storage.object_exists("zhilian-materials", copy_key) is True

        ready_ver = service.parse_material_pipeline(
            material_id=mat_b.id,
            version_id=ver_b.id,
            user_id=user_id,
        )
        assert ready_ver.parse_status == ParseStatus.READY.value

    def test_retry_ocr_pages_rebuilds_knowledge_tree(
        self,
        service: MaterialService,
        ocr: FakeOCRAdapter,
        session: Session,
    ) -> None:
        """MAT-003 回归：逐页重拍全达标后须重建知识树，而非仅重建切片。"""
        from unittest.mock import MagicMock

        from app.repositories.knowledge import KnowledgeRepository

        user_id = uuid.uuid4()
        bad_text = "%&*@#"
        good_text = (
            "重拍达标后必须重建知识树：线性空间与基变换是高等代数的核心结构。"
            "当向量组线性无关且可张成整个空间时，该向量组即构成空间的一组基。"
        )
        bad_png = b"\x89PNG\r\n\x1a\nbad_rebuild_initial"
        good_png = b"\x89PNG\r\n\x1a\ngood_rebuild_ok"
        ocr.set_canned_result(
            bad_png,
            OCRResult(full_text=bad_text, blocks=(OCRTextBlock(text=bad_text, confidence=0.2),)),
        )
        ocr.set_canned_result(
            good_png,
            OCRResult(full_text=good_text, blocks=(OCRTextBlock(text=good_text, confidence=0.99),)),
        )

        mat, ver = service.create_material(
            user_id=user_id,
            title="RebuildTree.png",
            file_format="png",
            file_size=len(bad_png),
            file_content=bad_png,
        )
        service.parse_material_pipeline(material_id=mat.id, version_id=ver.id, user_id=user_id)

        knowledge_repo = KnowledgeRepository(session)
        knowledge_service = MagicMock()

        def _rebuild(
            *, material_id: uuid.UUID, version_id: uuid.UUID, user_id: uuid.UUID
        ) -> object:
            knowledge_repo.create_knowledge_point(
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                name="重拍后重建知识点",
                batch_id="rebuild-batch",
            )
            return knowledge_repo.get_knowledge_points_by_version(material_id, version_id, user_id)

        knowledge_service.extract_and_build_knowledge_tree.side_effect = _rebuild
        service.knowledge_service = knowledge_service

        ready_ver = service.retry_ocr_pages(
            material_id=mat.id,
            version_id=ver.id,
            user_id=user_id,
            page_replaces={1: good_png},
        )

        assert ready_ver.parse_status == ParseStatus.READY.value
        knowledge_service.extract_and_build_knowledge_tree.assert_called_once_with(
            material_id=mat.id,
            version_id=ver.id,
            user_id=user_id,
        )
        points = knowledge_repo.get_knowledge_points_by_version(mat.id, ver.id, user_id)
        assert len(points) >= 1

    def test_ocr_gate_failure_sets_retake_required_and_filter_returns_entry(
        self,
        service: MaterialService,
        ocr: FakeOCRAdapter,
    ) -> None:
        """MAT-004 回归：门禁失败置 retake_required；筛选返回条目；OCR 页可查；重拍未达标维持。"""
        user_id = uuid.uuid4()
        bad_text = "%&*@#"
        png_content = b"\x89PNG\r\n\x1a\n" + b"retake_gate"
        ocr.set_canned_result(
            png_content,
            OCRResult(full_text=bad_text, blocks=(OCRTextBlock(text=bad_text, confidence=0.2),)),
        )

        mat, ver = service.create_material(
            user_id=user_id,
            title="GateRetake.png",
            file_format="png",
            file_size=len(png_content),
            file_content=png_content,
        )
        service.parse_material_pipeline(material_id=mat.id, version_id=ver.id, user_id=user_id)

        refreshed = service.get_material(material_id=mat.id, user_id=user_id)
        assert refreshed.status == MaterialStatus.RETAKE_REQUIRED.value

        items, total = service.list_materials(user_id=user_id, status="retake_required")
        assert total == 1
        assert items[0].id == mat.id
        assert getattr(items[0], "progress_percentage", None) == 0

        returned_version_id, pages = service.list_ocr_pages(
            material_id=mat.id,
            user_id=user_id,
            only_unqualified=True,
        )
        assert returned_version_id == ver.id
        assert len(pages) == 1
        assert pages[0].page_number == 1
        assert pages[0].is_qualified is False
        assert pages[0].unqualified_reason is not None

        # 重拍后仍有不合格页：资料必须维持 retake_required
        service.retry_ocr_pages(
            material_id=mat.id,
            version_id=ver.id,
            user_id=user_id,
            page_replaces={1: png_content},
        )
        still_retake = service.get_material(material_id=mat.id, user_id=user_id)
        assert still_retake.status == MaterialStatus.RETAKE_REQUIRED.value

    def test_reshoot_material_page_resolves_latest_when_no_current_version(
        self,
        service: MaterialService,
        ocr: FakeOCRAdapter,
    ) -> None:
        """MAT-004 集成回归：门禁失败资料无激活版本时，重拍仍能定位版本并达标转 READY。"""
        user_id = uuid.uuid4()
        bad_text = "%&*@#"
        good_text = (
            "重拍达标文本：线性空间与基变换是高等代数的核心结构，"
            "当向量组线性无关且可张成整个空间时，该向量组即构成空间的一组基。"
        )
        bad_png = b"\x89PNG\r\n\x1a\nreshoot_no_current_bad"
        good_png = b"\x89PNG\r\n\x1a\nreshoot_no_current_good"
        ocr.set_canned_result(
            bad_png,
            OCRResult(full_text=bad_text, blocks=(OCRTextBlock(text=bad_text, confidence=0.2),)),
        )
        ocr.set_canned_result(
            good_png,
            OCRResult(full_text=good_text, blocks=(OCRTextBlock(text=good_text, confidence=0.99),)),
        )

        mat, ver = service.create_material(
            user_id=user_id,
            title="ReshootNoCurrent.png",
            file_format="png",
            file_size=len(bad_png),
            file_content=bad_png,
        )
        service.parse_material_pipeline(material_id=mat.id, version_id=ver.id, user_id=user_id)

        gate_failed = service.get_material(material_id=mat.id, user_id=user_id)
        assert gate_failed.status == MaterialStatus.RETAKE_REQUIRED.value
        assert gate_failed.current_version_id is None

        # 前端重拍不传 version_id：服务须回退最新版本，不得因 current_version_id 为空而拒绝
        page = service.reshoot_material_page(
            user_id=user_id,
            material_id=mat.id,
            page_index=1,
            file_content=good_png,
        )
        assert page.is_qualified is True

        refreshed = service.get_material(material_id=mat.id, user_id=user_id)
        assert refreshed.status == MaterialStatus.READY.value
        assert refreshed.current_version_id == ver.id

        # READY 为干净终态：门禁失败残留的错误信息必须被清空
        ready_ver = service.repo.get_version_by_id(ver.id, user_id)
        assert ready_ver is not None
        assert ready_ver.parse_status == ParseStatus.READY.value
        assert ready_ver.failed_stage is None
        assert ready_ver.error_message is None


def test_extract_text_pdf_success_and_gate() -> None:
    """验证 extract_text_from_raw_content 支持 pypdf 原生提取与门禁过滤。"""
    from app.services.material import extract_text_from_raw_content

    # 包含 "Hello ZhiLian Learning Platform" 的极简真实 PDF
    valid_pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        b"4 0 obj\n<< /Length 44 >>\nstream\n"
        b"BT\n/F1 12 Tf\n100 700 Td\n(Hello ZhiLian Learning Platform) Tj\nET\n"
        b"endstream\nendobj\n"
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        b"xref\n0 6\n0000000000 65535 f \n0000000010 00000 n \n"
        b"0000000060 00000 n \n0000000117 00000 n \n"
        b"0000000226 00000 n \n0000000320 00000 n \n"
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n393\n%%EOF\n"
    )

    paragraphs = extract_text_from_raw_content(valid_pdf_bytes, "pdf")
    assert len(paragraphs) >= 1
    assert "Hello ZhiLian Learning Platform" in paragraphs[0]

    # 空白/扫描件 PDF (有效字符不足 10) 抛出 MaterialInvalidError
    empty_pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"/Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length 0 >>\nstream\nendstream\nendobj\n"
        b"xref\n0 5\n0000000000 65535 f \n0000000010 00000 n \n"
        b"0000000060 00000 n \n0000000117 00000 n \n0000000199 00000 n \n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n249\n%%EOF\n"
    )
    with pytest.raises(MaterialInvalidError) as exc_info:
        extract_text_from_raw_content(empty_pdf_bytes, "pdf")
    assert "PDF文件无有效文字内容，扫描件请直接上传图片" in str(exc_info.value)


def test_parse_pipeline_knowledge_chaining(
    service: MaterialService,
    session: Session,
) -> None:
    """验证 parse_material_pipeline 自动串联知识树抽取及异常状态回滚联动。"""
    from unittest.mock import MagicMock

    from app.models.material import MaterialStatus, ParseStatus

    user_id = uuid.uuid4()
    content = "第一章 极限与连续\n\n函数的极限是高等数学的核心基础概念之一。".encode()
    mat, ver = service.create_material(
        user_id=user_id,
        title="高等数学讲义.txt",
        file_format="txt",
        file_size=len(content),
        file_content=content,
    )

    mock_knowledge_service = MagicMock()
    service.knowledge_service = mock_knowledge_service

    # 1. 成功流水线执行验证
    res_version = service.parse_material_pipeline(
        material_id=mat.id,
        version_id=ver.id,
        user_id=user_id,
    )

    mock_knowledge_service.extract_and_build_knowledge_tree.assert_called_once_with(
        material_id=mat.id,
        version_id=ver.id,
        user_id=user_id,
    )
    assert res_version.parse_status == ParseStatus.READY.value
    updated_mat = service.repo.get_material_by_id(mat.id, user_id)
    assert updated_mat is not None
    assert updated_mat.status == MaterialStatus.READY.value

    # 2. 异常场景回滚与状态标记验证
    mat2, ver2 = service.create_material(
        user_id=user_id,
        title="线性代数讲义.txt",
        file_format="txt",
        file_size=len(content),
        file_content=content,
    )
    mock_knowledge_service.extract_and_build_knowledge_tree.side_effect = RuntimeError(
        "LLM抽取网络异常"
    )

    with pytest.raises(RuntimeError):
        service.parse_material_pipeline(
            material_id=mat2.id,
            version_id=ver2.id,
            user_id=user_id,
        )

    failed_ver = service.repo.get_version_by_id(ver2.id, user_id)
    assert failed_ver is not None
    assert failed_ver.parse_status == ParseStatus.FAILED.value
    assert failed_ver.failed_stage == "knowledge_extraction"
    assert "LLM抽取网络异常" in (failed_ver.error_message or "")

    failed_mat = service.repo.get_material_by_id(mat2.id, user_id)
    assert failed_mat is not None
    assert failed_mat.status == MaterialStatus.FAILED.value

    # 3. 验证就地重试：调用 retry_material_pipeline 后状态重置为 PENDING / QUEUED 且错误清空
    retried_mat, retried_ver = service.retry_material_pipeline(
        material_id=mat2.id,
        user_id=user_id,
    )
    assert retried_mat.status == MaterialStatus.PENDING.value
    assert retried_ver.parse_status == ParseStatus.QUEUED.value
    assert retried_ver.error_message is None
    assert retried_ver.failed_stage is None

    # 4. 验证同哈希文件历史版本为 FAILED 时重新上传：各自持有独立对象并重新调度
    # 先将 ver2 重新标为 FAILED 模拟先前失败
    service.repo.update_version_status(
        version_id=ver2.id,
        user_id=user_id,
        status=ParseStatus.FAILED.value,
        error_message="previous failure",
        failed_stage="chunking",
    )
    service.session.commit()

    mat3, ver3 = service.create_material(
        user_id=user_id,
        title="线性代数讲义_重传.txt",
        file_format="txt",
        file_size=len(content),
        file_content=content,
    )
    assert mat3.id != mat2.id
    # MAT-001：重新上传同哈希失败文件也不得复用其它资料的物理存储对象
    assert ver3.storage_key != ver2.storage_key
    assert ver3.parse_status == ParseStatus.QUEUED.value
    assert mat3.status == MaterialStatus.PENDING.value
