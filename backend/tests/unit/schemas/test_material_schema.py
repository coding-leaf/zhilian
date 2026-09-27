"""Unit tests for material Pydantic schemas in app/schemas/material.py."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.material import (
    MaterialDeleteResponse,
    MaterialDetailResponse,
    MaterialListItem,
    MaterialListResponse,
    MaterialParseRequest,
    MaterialParseResponse,
    MaterialReshootResponse,
    MaterialUploadResponse,
    MaterialVersionItem,
    MaterialVersionListResponse,
    sanitize_material_title,
)


def test_sanitize_material_title_normal() -> None:
    """Tests normal title string sanitization."""
    result = sanitize_material_title("高等数学复习讲义.pdf")
    assert result == "高等数学复习讲义.pdf"


def test_sanitize_material_title_defaults() -> None:
    """Tests default fallback for None, empty and whitespace strings."""
    assert sanitize_material_title(None) == "未命名资料"
    assert sanitize_material_title("") == "未命名资料"
    assert sanitize_material_title("    ") == "未命名资料"
    assert sanitize_material_title(None, default_title="自定义默认") == "自定义默认"
    assert sanitize_material_title("   ", default_title="自定义默认") == "自定义默认"


def test_sanitize_material_title_control_chars() -> None:
    """Tests stripping of non-printable control characters."""
    raw = "第一章\x00微积分\x1f课件\x7f.pdf"
    assert sanitize_material_title(raw) == "第一章微积分课件.pdf"


def test_sanitize_material_title_max_length() -> None:
    """Tests truncation to 255 characters."""
    long_title = "A" * 300
    cleaned = sanitize_material_title(long_title)
    assert len(cleaned) == 255
    assert cleaned == "A" * 255


def test_material_upload_response_valid() -> None:
    """Tests valid instantiation and serialization of MaterialUploadResponse."""
    mat_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    now = datetime.now(UTC)

    dto = MaterialUploadResponse(
        id=mat_id,
        version_id=ver_id,
        title="大学英语词汇.pdf",
        file_format="pdf",
        file_size=10240,
        source_type="local",
        status="pending",
        created_at=now,
    )

    assert dto.id == mat_id
    assert dto.version_id == ver_id
    assert dto.title == "大学英语词汇.pdf"
    assert dto.file_format == "pdf"
    assert dto.file_size == 10240
    assert dto.source_type == "local"
    assert dto.status == "pending"
    assert dto.created_at == now

    data = dto.model_dump()
    assert data["id"] == mat_id
    assert data["version_id"] == ver_id


def test_material_upload_response_invalid() -> None:
    """Tests validation error on missing fields or negative file_size."""
    with pytest.raises(ValidationError):
        MaterialUploadResponse.model_validate({"title": "incomplete"})

    with pytest.raises(ValidationError):
        MaterialUploadResponse(
            id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            title="test.pdf",
            file_format="pdf",
            file_size=-1,
            source_type="local",
            status="pending",
            created_at=datetime.now(UTC),
        )


def test_material_detail_response_valid() -> None:
    """Tests valid instantiation of MaterialDetailResponse."""
    mat_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    now = datetime.now(UTC)

    detail = MaterialDetailResponse(
        id=mat_id,
        title="线性代数讲义.pdf",
        file_format="pdf",
        file_size=20480,
        source_type="local",
        status="ready",
        current_version_id=ver_id,
        versions_count=3,
        created_at=now,
        updated_at=now,
    )

    assert detail.id == mat_id
    assert detail.current_version_id == ver_id
    assert detail.versions_count == 3

    # current_version_id can be None
    detail_no_version = MaterialDetailResponse(
        id=mat_id,
        title="无版本资料",
        file_format="txt",
        file_size=10,
        source_type="local",
        status="pending",
        current_version_id=None,
        versions_count=0,
        created_at=now,
        updated_at=now,
    )
    assert detail_no_version.current_version_id is None
    assert detail_no_version.versions_count == 0


def test_material_detail_response_invalid() -> None:
    """Tests negative versions_count rejects with ValidationError."""
    with pytest.raises(ValidationError):
        MaterialDetailResponse(
            id=uuid.uuid4(),
            title="test",
            file_format="pdf",
            file_size=100,
            source_type="local",
            status="pending",
            current_version_id=None,
            versions_count=-1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )


def test_material_list_item_and_response() -> None:
    """Tests MaterialListItem and MaterialListResponse pagination constraints."""
    mat_id = uuid.uuid4()
    now = datetime.now(UTC)

    item = MaterialListItem(
        id=mat_id,
        title="概率论基础.pdf",
        file_format="pdf",
        file_size=5000,
        source_type="local",
        status="ready",
        current_version_id=None,
        created_at=now,
        updated_at=now,
    )

    list_response = MaterialListResponse(
        items=[item],
        total=1,
        limit=20,
        offset=0,
    )
    assert len(list_response.items) == 1
    assert list_response.total == 1
    assert list_response.limit == 20
    assert list_response.offset == 0

    # Limit must be between 1 and 100
    with pytest.raises(ValidationError):
        MaterialListResponse(items=[], total=0, limit=0, offset=0)

    with pytest.raises(ValidationError):
        MaterialListResponse(items=[], total=0, limit=101, offset=0)

    # Total must be >= 0
    with pytest.raises(ValidationError):
        MaterialListResponse(items=[], total=-1, limit=20, offset=0)


def test_material_stats_fields_are_optional_and_serialized() -> None:
    """BUG-MAT-013：列表/详情 DTO 必须承载可选考点数与页数统计字段。"""
    mat_id = uuid.uuid4()
    now = datetime.now(UTC)

    item = MaterialListItem(
        id=mat_id,
        title="统计字段资料.pdf",
        file_format="pdf",
        file_size=4096,
        source_type="local",
        status="ready",
        current_version_id=None,
        key_points_count=7,
        page_count=4,
        created_at=now,
        updated_at=now,
    )
    assert item.key_points_count == 7
    assert item.page_count == 4
    dumped = item.model_dump()
    assert dumped["key_points_count"] == 7
    assert dumped["page_count"] == 4

    detail = MaterialDetailResponse(
        id=mat_id,
        title="统计字段资料.pdf",
        file_format="pdf",
        file_size=4096,
        source_type="local",
        status="ready",
        current_version_id=None,
        versions_count=1,
        key_points_count=3,
        page_count=2,
        created_at=now,
        updated_at=now,
    )
    assert detail.key_points_count == 3
    assert detail.page_count == 2

    # 附加可选字段：旧客户端未传时默认为 None，保持向后兼容。
    item_default = MaterialListItem(
        id=mat_id,
        title="无统计资料.pdf",
        file_format="pdf",
        file_size=100,
        source_type="local",
        status="pending",
        current_version_id=None,
        created_at=now,
        updated_at=now,
    )
    assert item_default.key_points_count is None
    assert item_default.page_count is None


def test_material_parse_request_and_response() -> None:
    """Tests MaterialParseRequest defaults and MaterialParseResponse."""
    req_default = MaterialParseRequest()
    assert req_default.version_id is None
    assert req_default.sync is False

    mat_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    req_custom = MaterialParseRequest(version_id=ver_id, sync=True)
    assert req_custom.version_id == ver_id
    assert req_custom.sync is True

    resp = MaterialParseResponse(
        material_id=mat_id,
        version_id=ver_id,
        parse_status="parsing_doc",
        is_active=False,
        message="解析流水线已异步入队调度",
    )
    assert resp.material_id == mat_id
    assert resp.version_id == ver_id
    assert resp.parse_status == "parsing_doc"
    assert resp.is_active is False
    assert "调度" in resp.message


def test_material_version_item_and_list() -> None:
    """Tests MaterialVersionItem and MaterialVersionListResponse."""
    mat_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    now = datetime.now(UTC)

    ver_item = MaterialVersionItem(
        id=ver_id,
        material_id=mat_id,
        version_number=1,
        parse_status="ready",
        content_hash="abc123hash",
        is_active=True,
        created_at=now,
    )
    assert ver_item.version_number == 1

    # version_number must be >= 1
    with pytest.raises(ValidationError):
        MaterialVersionItem(
            id=ver_id,
            material_id=mat_id,
            version_number=0,
            parse_status="ready",
            content_hash="abc",
            is_active=True,
            created_at=now,
        )

    ver_list = MaterialVersionListResponse(material_id=mat_id, versions=[ver_item])
    assert len(ver_list.versions) == 1
    assert ver_list.material_id == mat_id


def test_material_reshoot_response() -> None:
    """Tests MaterialReshootResponse validation constraints."""
    mat_id = uuid.uuid4()
    ver_id = uuid.uuid4()

    reshoot = MaterialReshootResponse(
        material_id=mat_id,
        version_id=ver_id,
        page_index=1,
        is_qualified=True,
        reshoot_count=1,
        parse_status="ready",
        unqualified_reason=None,
    )
    assert reshoot.page_index == 1
    assert reshoot.reshoot_count == 1
    assert reshoot.is_qualified is True

    # page_index must be >= 1
    with pytest.raises(ValidationError):
        MaterialReshootResponse(
            material_id=mat_id,
            version_id=ver_id,
            page_index=0,
            is_qualified=False,
            reshoot_count=1,
            parse_status="failed",
        )

    # reshoot_count must be <= 3
    with pytest.raises(ValidationError):
        MaterialReshootResponse(
            material_id=mat_id,
            version_id=ver_id,
            page_index=1,
            is_qualified=False,
            reshoot_count=4,
            parse_status="failed",
        )


def test_material_delete_response() -> None:
    """Tests MaterialDeleteResponse structure."""
    mat_id = uuid.uuid4()
    resp = MaterialDeleteResponse(
        material_id=mat_id,
        is_deleted=True,
        permanent=False,
        message="学习资料已成功移入回收站",
    )
    assert resp.material_id == mat_id
    assert resp.is_deleted is True
    assert resp.permanent is False
