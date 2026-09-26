"""DOCX/PPTX OOXML 文本抽取单元测试（真实 ZIP 容器，离线）。

覆盖：
- UT-DOCX-01: 真实最小 DOCX（ZIP 容器）-> 正确抽取段落文本；
- UT-DOCX-02: 损坏 DOCX（非 ZIP）-> 抛 MaterialInvalidError；
- UT-DOCX-03: 合法 ZIP 但缺失 word/document.xml -> 抛 MaterialInvalidError；
- UT-PPTX-01: 真实最小 PPTX -> 按幻灯片序号抽取文本；
- UT-PPTX-02: 损坏 PPTX -> 抛 MaterialInvalidError。
"""

import io
import zipfile

import pytest

from app.cli.fixtures import build_minimal_docx
from app.core.errors import MaterialInvalidError
from app.services.material import extract_text_from_raw_content

_PPTX_SLIDE_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
    "<p:cSld><p:spTree><p:sp><p:txBody>"
    "{body}"
    "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
)


def _build_pptx(slides: list[list[str]]) -> bytes:
    """构造真实最小 PPTX（仅包含 slide 成员，供文本抽取测试）。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, paragraphs in enumerate(slides, start=1):
            body = "".join(f"<a:p><a:r><a:t>{text}</a:t></a:r></a:p>" for text in paragraphs)
            archive.writestr(
                f"ppt/slides/slide{index}.xml",
                _PPTX_SLIDE_TEMPLATE.format(body=body),
            )
    return buffer.getvalue()


def test_extract_docx_real_zip_returns_paragraphs() -> None:
    """真实 DOCX（ZIP 容器）应正确抽取段落文本并保留特殊字符。"""
    paragraphs = [
        "第一章 线性表与顺序存储结构。",
        "第二章 栈与队列：LIFO 与 FIFO & <特殊字符>。",
        "第三章 二叉树的前序、中序与后序遍历。",
    ]
    content = build_minimal_docx(paragraphs)

    extracted = extract_text_from_raw_content(content, "docx")

    assert extracted == paragraphs


def test_extract_docx_corrupt_raises() -> None:
    """非 ZIP 容器的 docx 二进制应抛出 MaterialInvalidError。"""
    with pytest.raises(MaterialInvalidError):
        extract_text_from_raw_content(b"PK\x03\x04not-a-real-zip-container", "docx")


def test_extract_docx_valid_zip_missing_member_raises() -> None:
    """合法 ZIP 但缺失 word/document.xml 时应抛出 MaterialInvalidError。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/other.xml", "<root/>")

    with pytest.raises(MaterialInvalidError):
        extract_text_from_raw_content(buffer.getvalue(), "docx")


def test_extract_docx_empty_body_raises() -> None:
    """合法 DOCX（ZIP）但正文无任何文本节点时应抛出 MaterialInvalidError。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body></w:body></w:document>",
        )

    with pytest.raises(MaterialInvalidError):
        extract_text_from_raw_content(buffer.getvalue(), "docx")


def test_extract_docx_corrupt_xml_raises() -> None:
    """word/document.xml 非法 XML 时应抛出 MaterialInvalidError（而非静默空文本）。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document><w:body>")

    with pytest.raises(MaterialInvalidError):
        extract_text_from_raw_content(buffer.getvalue(), "docx")


def test_extract_pptx_real_zip_returns_slide_text_in_order() -> None:
    """真实 PPTX 应按幻灯片序号抽取文本。"""
    content = _build_pptx(
        [
            ["第一张幻灯片标题", "第一张幻灯片要点"],
            ["第二张幻灯片标题"],
        ]
    )

    extracted = extract_text_from_raw_content(content, "pptx")

    assert extracted == [
        "第一张幻灯片标题",
        "第一张幻灯片要点",
        "第二张幻灯片标题",
    ]


def test_extract_pptx_corrupt_raises() -> None:
    """非 ZIP 容器的 pptx 二进制应抛出 MaterialInvalidError。"""
    with pytest.raises(MaterialInvalidError):
        extract_text_from_raw_content(b"PK\x03\x04corrupted", "pptx")


def test_extract_pptx_no_text_raises() -> None:
    """合法 PPTX 但幻灯片无任何文本节点时应抛出 MaterialInvalidError。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "ppt/slides/slide1.xml",
            '<?xml version="1.0"?>'
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            "<p:cSld/></p:sld>",
        )

    with pytest.raises(MaterialInvalidError):
        extract_text_from_raw_content(buffer.getvalue(), "pptx")
