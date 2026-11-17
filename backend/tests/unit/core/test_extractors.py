"""Unit tests for pure binary and document extractors under app.core.extractors."""

import io
import zipfile
from typing import Any

import pytest

from app.core.errors import MaterialInvalidError
from app.core.extractors import (
    _extract_paragraphs_from_docx,
    _extract_paragraphs_from_pptx,
    _extract_text_from_pdf,
    detect_image_type,
    extract_text_from_raw_content,
    validate_file_magic,
)


def _build_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return buf.getvalue()


def test_detect_image_type_recognizes_all_supported_signatures() -> None:
    """Verify magic-byte signature validation for PNG, JPEG, GIF, WEBP, and invalid headers."""
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + b"\x00" * 10
    assert detect_image_type(png) == ("image/png", ".png")

    jpeg = b"\xff\xd8\xff\xe0" + b"body" + b"\xff\xd9"
    assert detect_image_type(jpeg) == ("image/jpeg", ".jpg")

    gif = b"GIF89a" + b"data" + b";"
    assert detect_image_type(gif) == ("image/gif", ".gif")

    webp_payload = b"WEBP" + b"VP8 " + b"\x00\x00"
    webp = b"RIFF" + len(webp_payload).to_bytes(4, "little") + webp_payload
    assert detect_image_type(webp) == ("image/webp", ".webp")

    assert detect_image_type(b"not-an-image") is None
    assert detect_image_type(b"\x89PNG\r\n\x1a\nBAD!") is None


def test_validate_file_magic_handles_text_binary_and_invalid_inputs() -> None:
    """Verify magic-number and UTF-8 validation across formats and edge cases."""
    assert validate_file_magic(b"Hello Markdown\n# Heading", ".md") is True
    assert validate_file_magic(b"Binary\x00null", "txt") is False
    assert validate_file_magic(b"\xff\xfe\xfd", "txt") is False
    assert validate_file_magic(b"%PDF-1.7\n...", "pdf") is True
    assert validate_file_magic(b"PK\x03\x04...", "docx") is True
    assert validate_file_magic(b"", "pdf") is False
    assert validate_file_magic(b"content", "exe") is False


def test_extract_text_from_pdf_and_error_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify PDF text extraction, short-content rejection, and corrupt-file error mapping."""

    class _FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _ValidReader:
        def __init__(self, stream: Any) -> None:
            self.pages = [_FakePage("First page sufficient words."), _FakePage("Second page.")]

    monkeypatch.setattr("app.core.extractors.pypdf.PdfReader", _ValidReader)
    extracted = extract_text_from_raw_content(b"%PDF-1.4", "pdf")
    assert extracted == ["First page sufficient words.", "Second page."]

    class _ShortReader:
        def __init__(self, stream: Any) -> None:
            self.pages = [_FakePage("abc")]

    monkeypatch.setattr("app.core.extractors.pypdf.PdfReader", _ShortReader)
    with pytest.raises(MaterialInvalidError, match="无有效文字内容"):
        _extract_text_from_pdf(b"%PDF-1.4")

    class _BrokenReader:
        def __init__(self, stream: Any) -> None:
            raise OSError("corrupted stream")

    monkeypatch.setattr("app.core.extractors.pypdf.PdfReader", _BrokenReader)
    with pytest.raises(MaterialInvalidError, match="PDF 文件解析失败"):
        _extract_text_from_pdf(b"%PDF-broken")


def test_extract_paragraphs_from_docx_valid_and_invalid_cases() -> None:
    """Verify DOCX XML paragraph extraction and error handling for corrupt/empty archives."""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>第一章 </w:t><w:t>操作系统概论</w:t></w:r></w:p>"
        "<w:p><w:r><w:t></w:t></w:r></w:p>"
        "<w:p><w:r><w:t>进程调度机制</w:t></w:r></w:p></w:body></w:document>"
    ).encode()
    docx_bytes = _build_zip({"word/document.xml": xml})
    assert extract_text_from_raw_content(docx_bytes, "docx") == [
        "第一章 操作系统概论",
        "进程调度机制",
    ]

    with pytest.raises(MaterialInvalidError, match="OOXML ZIP 容器"):
        _extract_paragraphs_from_docx(b"not-a-zip")

    bad_xml_docx = _build_zip({"word/document.xml": b"<w:document><unclosed>"})
    with pytest.raises(MaterialInvalidError, match="XML 损坏"):
        _extract_paragraphs_from_docx(bad_xml_docx)

    empty_docx = _build_zip(
        {
            "word/document.xml": (
                b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                b"<w:body/></w:document>"
            )
        }
    )
    with pytest.raises(MaterialInvalidError, match="未包含可提取的正文文本"):
        _extract_paragraphs_from_docx(empty_docx)


def test_extract_paragraphs_from_pptx_sorted_and_error_cases() -> None:
    """Verify PPTX slide sorting, XML fragment extraction, and corrupt/empty error paths."""
    ns = (
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    )
    slide_2 = f"<p:sld {ns}><a:t>Second Slide</a:t></p:sld>".encode()
    slide_1 = f"<p:sld {ns}><a:t>First Slide</a:t></p:sld>".encode()
    pptx_bytes = _build_zip(
        {
            "ppt/slides/slide10.xml": f"<p:sld {ns}><a:t>Tenth Slide</a:t></p:sld>".encode(),
            "ppt/slides/slide2.xml": slide_2,
            "ppt/slides/slide1.xml": slide_1,
        }
    )
    assert extract_text_from_raw_content(pptx_bytes, "pptx") == [
        "First Slide",
        "Second Slide",
        "Tenth Slide",
    ]

    with pytest.raises(MaterialInvalidError, match="缺少幻灯片"):
        _extract_paragraphs_from_pptx(_build_zip({"[Content_Types].xml": b"<Types/>"}))

    with pytest.raises(MaterialInvalidError, match="OOXML ZIP 容器"):
        _extract_paragraphs_from_pptx(b"not-zip")

    with pytest.raises(MaterialInvalidError, match="XML 损坏"):
        _extract_paragraphs_from_pptx(_build_zip({"ppt/slides/slide1.xml": b"<p:sld><broken>"}))

    with pytest.raises(MaterialInvalidError, match="未包含可提取的正文文本"):
        _extract_paragraphs_from_pptx(
            _build_zip({"ppt/slides/slide1.xml": f"<p:sld {ns}/>".encode()})
        )


def test_extract_text_from_raw_content_text_and_fallback() -> None:
    """Verify txt/md paragraph splitting and unknown format fallback."""
    assert extract_text_from_raw_content(b"Paragraph A\n\nParagraph B", "txt") == [
        "Paragraph A",
        "Paragraph B",
    ]
    assert extract_text_from_raw_content(b"Line 1\nLine 2", ".MD") == ["Line 1", "Line 2"]
    assert extract_text_from_raw_content(b"data", "png") == []
