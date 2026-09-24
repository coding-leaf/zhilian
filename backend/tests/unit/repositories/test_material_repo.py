"""Unit tests for MaterialRepository in app/repositories/material.py.

Verifies:
1. Material CRUD operations, status transitions, soft/hard deletion.
2. MaterialVersion version increment, content hash deduplication lookup, status updates.
3. MaterialSnippet batch creation, retrieval, and cascading deletion.
4. MaterialOCRPage batch creation, page retrieval, and reshoot updates.
5. Strict multi-tenant isolation (Anti-horizontal privilege escalation) preventing
   any cross-user data leakage or modifications.
"""

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.material import (
    MaterialOCRPage,
    MaterialSnippet,
    MaterialStatus,
    ParseStatus,
)
from app.repositories.material import MaterialRepository


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """Provides an isolated in-memory SQLite database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as sess:
        yield sess
    engine.dispose()


class TestMaterialRepositoryCRUD:
    """Test suite for MaterialRepository normal operations."""

    def test_create_and_get_material(self, session: Session) -> None:
        """Verify creating and retrieving a material entity."""
        repo = MaterialRepository(session)
        user_id = uuid.uuid4()

        material = repo.create_material(
            user_id=user_id,
            title="高等数学笔记.pdf",
            file_format="pdf",
            file_size=102400,
            source_type="local",
        )
        session.commit()

        assert material.id is not None
        assert material.user_id == user_id
        assert material.title == "高等数学笔记.pdf"
        assert material.status == MaterialStatus.PENDING.value
        assert material.is_deleted is False

        fetched = repo.get_material_by_id(material.id, user_id)
        assert fetched is not None
        assert fetched.id == material.id
        assert fetched.title == material.title

    def test_list_materials_and_pagination(self, session: Session) -> None:
        """Verify listing materials with pagination and soft deletion filter."""
        repo = MaterialRepository(session)
        user_id = uuid.uuid4()

        created_ids = []
        for i in range(5):
            mat = repo.create_material(
                user_id=user_id,
                title=f"Doc_{i}.pdf",
                file_format="pdf",
                file_size=1000 + i,
            )
            created_ids.append(mat.id)
        session.commit()

        # List all
        items = repo.list_materials(user_id=user_id, limit=10, offset=0)
        assert len(items) == 5

        # Pagination
        page_items = repo.list_materials(user_id=user_id, limit=2, offset=0)
        assert len(page_items) == 2

        # List by user tuple
        items_tuple, total = repo.list_materials_by_user(user_id=user_id, limit=10, offset=0)
        assert len(items_tuple) == 5
        assert total == 5

    def test_update_material_status_and_version(self, session: Session) -> None:
        """Verify updating material status and activating current version."""
        repo = MaterialRepository(session)
        user_id = uuid.uuid4()

        mat = repo.create_material(
            user_id=user_id,
            title="English.docx",
            file_format="docx",
            file_size=2048,
        )
        session.commit()

        ver = repo.create_version(
            material_id=mat.id,
            user_id=user_id,
            version_number=1,
            storage_key="path/v1/en.docx",
            content_hash="abc123hash",
        )
        session.commit()

        success = repo.update_material_status(
            material_id=mat.id,
            user_id=user_id,
            status=MaterialStatus.READY.value,
            current_version_id=ver.id,
        )
        session.commit()

        assert success is True
        refreshed = repo.get_material_by_id(mat.id, user_id)
        assert refreshed is not None
        assert refreshed.status == MaterialStatus.READY.value
        assert refreshed.current_version_id == ver.id

    def test_soft_and_hard_delete_material(self, session: Session) -> None:
        """Verify soft deletion hides material while hard deletion purges records."""
        repo = MaterialRepository(session)
        user_id = uuid.uuid4()

        mat = repo.create_material(
            user_id=user_id,
            title="ToDelete.pdf",
            file_format="pdf",
            file_size=5000,
        )
        session.commit()

        # Soft delete
        assert repo.soft_delete_material(mat.id, user_id) is True
        session.commit()

        # By default not found
        assert repo.get_material_by_id(mat.id, user_id, include_deleted=False) is None
        # Found with include_deleted=True
        deleted_mat = repo.get_material_by_id(mat.id, user_id, include_deleted=True)
        assert deleted_mat is not None
        assert deleted_mat.is_deleted is True

        # Hard delete
        assert repo.hard_delete_material(mat.id, user_id) is True
        session.commit()
        assert repo.get_material_by_id(mat.id, user_id, include_deleted=True) is None

    def test_version_operations(self, session: Session) -> None:
        """Verify version creation, hash lookup, and status transitions."""
        repo = MaterialRepository(session)
        user_id = uuid.uuid4()

        mat = repo.create_material(
            user_id=user_id,
            title="Versioned.pdf",
            file_format="pdf",
            file_size=10000,
        )
        session.commit()

        v1 = repo.create_version(
            material_id=mat.id,
            user_id=user_id,
            version_number=1,
            storage_key="s3/v1.pdf",
            content_hash="hash_v1",
        )
        v2 = repo.create_version(
            material_id=mat.id,
            user_id=user_id,
            version_number=2,
            storage_key="s3/v2.pdf",
            content_hash="hash_v2",
        )
        session.commit()

        # Fetch by id
        fetched_v1 = repo.get_version_by_id(v1.id, user_id)
        assert fetched_v1 is not None
        assert fetched_v1.version_number == 1

        # Hash lookup
        found_ver = repo.find_version_by_hash(user_id, "hash_v2")
        assert found_ver is not None
        assert found_ver.id == v2.id

        # Update status
        repo.update_version_status(
            version_id=v2.id,
            user_id=user_id,
            status=ParseStatus.READY.value,
            raw_text_storage_key="s3/raw_v2.txt",
        )
        session.commit()

        refreshed_v2 = repo.get_version_by_id(v2.id, user_id)
        assert refreshed_v2 is not None
        assert refreshed_v2.parse_status == ParseStatus.READY.value
        assert refreshed_v2.raw_text_storage_key == "s3/raw_v2.txt"

    def test_snippets_crud(self, session: Session) -> None:
        """Verify snippet batch creation, retrieval, and deletion."""
        repo = MaterialRepository(session)
        user_id = uuid.uuid4()

        mat = repo.create_material(
            user_id=user_id,
            title="Snippets.pdf",
            file_format="pdf",
            file_size=2000,
        )
        session.commit()

        ver = repo.create_version(
            material_id=mat.id,
            user_id=user_id,
            version_number=1,
            storage_key="s3/v1.pdf",
            content_hash="snip_hash",
        )
        session.commit()

        snippets = [
            MaterialSnippet(
                user_id=user_id,
                material_id=mat.id,
                version_id=ver.id,
                snippet_index=0,
                content="第一段内容关于微积分基础概念。",
                char_length=15,
                start_offset=0,
                end_offset=15,
                chapter_title="第1章",
                source_info={"page_number": 1},
                embedding=[0.01] * 1024,
            ),
            MaterialSnippet(
                user_id=user_id,
                material_id=mat.id,
                version_id=ver.id,
                snippet_index=1,
                content="第二段内容关于极限与连续性定理。",
                char_length=16,
                start_offset=15,
                end_offset=31,
                chapter_title="第1章",
                source_info={"page_number": 1},
                embedding=[0.02] * 1024,
            ),
        ]
        repo.create_snippets(snippets)
        session.commit()

        retrieved = repo.get_snippets(ver.id, user_id)
        assert len(retrieved) == 2
        assert retrieved[0].snippet_index == 0
        assert retrieved[1].snippet_index == 1

        # Delete snippets
        del_count = repo.delete_snippets_by_version(ver.id, user_id)
        session.commit()
        assert del_count == 2
        assert len(repo.get_snippets(ver.id, user_id)) == 0

    def test_ocr_pages_crud(self, session: Session) -> None:
        """Verify OCR page batch creation, retrieval, and reshoot updates."""
        repo = MaterialRepository(session)
        user_id = uuid.uuid4()

        mat = repo.create_material(
            user_id=user_id,
            title="Scan.pdf",
            file_format="pdf",
            file_size=8000,
        )
        session.commit()

        ver = repo.create_version(
            material_id=mat.id,
            user_id=user_id,
            version_number=1,
            storage_key="s3/scan.pdf",
            content_hash="scan_hash",
        )
        session.commit()

        pages = [
            MaterialOCRPage(
                user_id=user_id,
                material_id=mat.id,
                version_id=ver.id,
                page_number=1,
                image_storage_key="pages/p1.png",
                raw_text="清晰文字",
                gibberish_ratio=0.01,
                valid_char_count=50,
                is_qualified=True,
                reshoot_count=0,
            ),
            MaterialOCRPage(
                user_id=user_id,
                material_id=mat.id,
                version_id=ver.id,
                page_number=2,
                image_storage_key="pages/p2.png",
                raw_text="模糊乱码#$%",
                gibberish_ratio=0.25,
                valid_char_count=10,
                is_qualified=False,
                unqualified_reason="乱码率超限",
                reshoot_count=0,
            ),
        ]
        repo.create_ocr_pages(pages)
        session.commit()

        fetched_pages = repo.get_ocr_pages(ver.id, user_id)
        assert len(fetched_pages) == 2
        assert fetched_pages[1].is_qualified is False

        # Update OCR page for page 2
        repo.update_ocr_page(
            page_id=fetched_pages[1].id,
            user_id=user_id,
            raw_text="重拍后清晰文字内容",
            gibberish_ratio=0.02,
            valid_char_count=60,
            is_qualified=True,
            unqualified_reason=None,
            reshoot_count=1,
            image_storage_key="pages/p2_reshoot.png",
        )
        session.commit()

        single_page = repo.get_ocr_page(ver.id, 2, user_id)
        assert single_page is not None
        assert single_page.is_qualified is True
        assert single_page.reshoot_count == 1
        assert single_page.raw_text == "重拍后清晰文字内容"


class TestMaterialRepositorySecurity:
    """Multi-tenant isolation and anti-horizontal privilege escalation test suite."""

    def test_cannot_access_or_modify_other_user_material(self, session: Session) -> None:
        """Verify User B cannot read, list, update, or delete User A's data."""
        repo = MaterialRepository(session)
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()

        # User A creates material and version
        mat_a = repo.create_material(
            user_id=user_a,
            title="UserA_Private.pdf",
            file_format="pdf",
            file_size=1000,
        )
        session.commit()

        ver_a = repo.create_version(
            material_id=mat_a.id,
            user_id=user_a,
            version_number=1,
            storage_key="a/key.pdf",
            content_hash="hash_a",
        )
        session.commit()

        # User B reads User A's material -> None
        assert repo.get_material_by_id(mat_a.id, user_b) is None
        # User B reads User A's version -> None
        assert repo.get_version_by_id(ver_a.id, user_b) is None
        # User B finds version by hash -> None
        assert repo.find_version_by_hash(user_b, "hash_a") is None

        # User B lists materials -> empty
        assert repo.list_materials(user_id=user_b) == []
        b_list, b_total = repo.list_materials_by_user(user_id=user_b)
        assert len(b_list) == 0
        assert b_total == 0

        # User B attempts to update material status -> False
        assert (
            repo.update_material_status(
                material_id=mat_a.id,
                user_id=user_b,
                status=MaterialStatus.READY.value,
            )
            is False
        )

        # User B attempts to update version status -> False
        assert (
            repo.update_version_status(
                version_id=ver_a.id,
                user_id=user_b,
                status=ParseStatus.READY.value,
            )
            is False
        )

        # User B attempts to soft delete User A's material -> False
        assert repo.soft_delete_material(mat_a.id, user_b) is False
        # Material A still active and not deleted
        assert repo.get_material_by_id(mat_a.id, user_a) is not None

        # User B attempts to hard delete User A's material -> False
        assert repo.hard_delete_material(mat_a.id, user_b) is False
        assert repo.get_material_by_id(mat_a.id, user_a) is not None

    def test_snippets_and_ocr_pages_tenant_isolation(self, session: Session) -> None:
        """Verify snippets and OCR pages cannot be accessed or deleted across users."""
        repo = MaterialRepository(session)
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()

        mat_a = repo.create_material(
            user_id=user_a,
            title="DocA.pdf",
            file_format="pdf",
            file_size=2000,
        )
        session.commit()

        ver_a = repo.create_version(
            material_id=mat_a.id,
            user_id=user_a,
            version_number=1,
            storage_key="s3/a.pdf",
            content_hash="hash_a",
        )
        session.commit()

        repo.create_snippets(
            [
                MaterialSnippet(
                    user_id=user_a,
                    material_id=mat_a.id,
                    version_id=ver_a.id,
                    snippet_index=0,
                    content="机密学习资料内容",
                    char_length=8,
                    start_offset=0,
                    end_offset=8,
                )
            ]
        )
        repo.create_ocr_pages(
            [
                MaterialOCRPage(
                    user_id=user_a,
                    material_id=mat_a.id,
                    version_id=ver_a.id,
                    page_number=1,
                    image_storage_key="a/p1.png",
                    raw_text="机密扫描文字",
                )
            ]
        )
        session.commit()

        # User B reads snippets -> empty
        assert repo.get_snippets(ver_a.id, user_b) == []
        # User B deletes snippets -> 0
        assert repo.delete_snippets_by_version(ver_a.id, user_b) == 0
        # User A still has snippets
        assert len(repo.get_snippets(ver_a.id, user_a)) == 1

        # User B reads OCR pages -> empty
        assert repo.get_ocr_pages(ver_a.id, user_b) == []
        assert repo.get_ocr_page(ver_a.id, 1, user_b) is None

        # User B attempts to update OCR page -> False
        a_page = repo.get_ocr_page(ver_a.id, 1, user_a)
        assert a_page is not None
        assert (
            repo.update_ocr_page(
                page_id=a_page.id,
                user_id=user_b,
                raw_text="Tampered",
                gibberish_ratio=0.0,
                valid_char_count=100,
                is_qualified=True,
                unqualified_reason=None,
                reshoot_count=1,
            )
            is False
        )

    def test_bulk_helpers_and_aliases(self, session: Session) -> None:
        """Verify bulk create helpers and alias query methods."""
        repo = MaterialRepository(session)
        user_id = uuid.uuid4()

        mat = repo.create_material(
            user_id=user_id,
            title="BulkDoc.pdf",
            file_format="pdf",
            file_size=5000,
        )
        session.commit()

        ver = repo.create_version(
            material_id=mat.id,
            user_id=user_id,
            version_number=1,
            storage_key="s3/bulk.pdf",
            content_hash="bulk_hash_123",
        )
        session.commit()

        # Test bulk_create_snippets & list_snippets_by_version
        snippets_payload = [
            {
                "material_id": mat.id,
                "version_id": ver.id,
                "snippet_index": 0,
                "content": "切片一",
                "char_length": 3,
                "start_offset": 0,
                "end_offset": 3,
                "chapter_title": "第一章",
                "source_info": {"page": 1},
                "embedding": [0.1] * 1024,
            },
            {
                "material_id": mat.id,
                "version_id": ver.id,
                "snippet_index": 1,
                "content": "切片二",
                "char_length": 3,
                "start_offset": 3,
                "end_offset": 6,
                "chapter_title": "第一章",
                "source_info": {"page": 1},
                "embedding": [0.2] * 1024,
            },
        ]
        created_snippets_count = repo.bulk_create_snippets(snippets_payload, user_id)
        session.commit()
        assert created_snippets_count == 2

        listed_snippets = repo.list_snippets_by_version(ver.id, user_id)
        assert len(listed_snippets) == 2

        # Test bulk_create_ocr_pages & list_ocr_pages_by_version & update_ocr_page_result
        pages_payload = [
            {
                "material_id": mat.id,
                "version_id": ver.id,
                "page_number": 1,
                "image_storage_key": "pages/p1.png",
                "raw_text": "页1",
                "gibberish_ratio": 0.0,
                "valid_char_count": 10,
                "is_qualified": True,
                "reshoot_count": 0,
            }
        ]
        created_pages_count = repo.bulk_create_ocr_pages(pages_payload, user_id)
        session.commit()
        assert created_pages_count == 1

        listed_pages = repo.list_ocr_pages_by_version(ver.id, user_id)
        assert len(listed_pages) == 1

        # Test update_ocr_page_result
        updated = repo.update_ocr_page_result(
            page_id=listed_pages[0].id,
            user_id=user_id,
            raw_text="更新后的页1",
            gibberish_ratio=0.01,
            valid_char_count=20,
            is_qualified=True,
            unqualified_reason=None,
            reshoot_count=1,
            image_storage_key="pages/p1_v2.png",
        )
        session.commit()
        assert updated is True

        # Test get_latest_version_by_hash
        latest_ver = repo.get_latest_version_by_hash(user_id, "bulk_hash_123")
        assert latest_ver is not None
        assert latest_ver.id == ver.id
