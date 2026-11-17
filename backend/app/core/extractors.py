"""Pure document text and binary magic-byte extractors without database/network I/O."""

import io
import zipfile
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

import pypdf

from app.core.algorithms.ocr_quality import detect_symbol_garble
from app.core.errors import MaterialInvalidError

# 依据：文件类型二进制魔数定义
MAGIC_NUMBERS: dict[str, list[bytes]] = {
    "pdf": [b"%PDF-"],
    "docx": [b"PK\x03\x04"],
    "pptx": [b"PK\x03\x04"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
}


def detect_image_type(data: bytes) -> tuple[str, str] | None:
    """Return an image MIME type and suffix only for recognized image signatures."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        return "image/png", ".png"
    if data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
        return "image/jpeg", ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")) and data.endswith(b";"):
        return "image/gif", ".gif"
    if (
        data.startswith(b"RIFF")
        and data[8:12] == b"WEBP"
        and int.from_bytes(data[4:8], "little") + 8 == len(data)
    ):
        return "image/webp", ".webp"
    return None


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

    if normalized_format in ("txt", "md"):
        try:
            decoded = content.decode("utf-8")
            return "\x00" not in decoded
        except UnicodeDecodeError:
            return False

    if normalized_format in MAGIC_NUMBERS:
        return any(content.startswith(magic) for magic in MAGIC_NUMBERS[normalized_format])

    return False


_SYMBOL_FONT_MARKERS: tuple[str, ...] = (
    "symbol",
    "mt-extra",
    "mtex",
    "wingding",
    "webding",
    "math",
    "zapfdingbats",
)


@dataclass(frozen=True)
class PdfPageExtraction:
    """单页 PDF 解析及字体/符号乱码诊断结果。"""

    page_number: int
    text: str
    lacks_tounicode_symbol_font: bool
    has_symbol_garble: bool
    suspicious_fragments: tuple[str, ...] = ()
    embedded_images: tuple[bytes, ...] = ()

    @property
    def needs_repair(self) -> bool:
        """是否存在字体缺失 ToUnicode 或高密度 ASCII 符号乱码问题。"""
        return self.lacks_tounicode_symbol_font or self.has_symbol_garble


def _dereference(obj: Any) -> Any:
    """安全展开 pypdf IndirectObject 引用。"""
    get_obj = getattr(obj, "get_object", None)
    if callable(get_obj):
        try:
            return get_obj()
        except Exception:
            return obj
    return obj


def _inspect_page_symbol_fonts_missing_tounicode(page: Any) -> bool:
    """检测 PDF 页级 `/Resources/Font` 中是否存在缺失 `/ToUnicode` 的符号/数学字体。"""
    page_get = getattr(page, "get", None)
    if not callable(page_get):
        return False
    resources = _dereference(page_get("/Resources"))
    if not isinstance(resources, dict):
        return False
    fonts = _dereference(resources.get("/Font"))
    if not isinstance(fonts, dict):
        return False

    for raw_font in fonts.values():
        font_dict = _dereference(raw_font)
        if not isinstance(font_dict, dict):
            continue
        base_font = str(font_dict.get("/BaseFont", "")).lower()
        if any(marker in base_font for marker in _SYMBOL_FONT_MARKERS) and (
            "/ToUnicode" not in font_dict
        ):
            return True
    return False


def _extract_page_embedded_images(page: Any) -> tuple[bytes, ...]:
    """安全提取 PDF 页面内嵌位图字节序列（供可选 OCR 补识）。"""
    raw_images = getattr(page, "images", None)
    if not raw_images:
        return ()
    collected: list[bytes] = []
    try:
        for img in raw_images:
            data = getattr(img, "data", None)
            if isinstance(data, bytes) and data:
                collected.append(data)
            if len(collected) >= 3:
                break
    except Exception:
        return ()
    return tuple(collected)


def extract_pdf_pages_with_diagnostics(content: bytes) -> list[PdfPageExtraction]:
    """按页提取 PDF 文本，并检测缺失 `/ToUnicode` 符号字体及 ASCII 乱码簇。"""
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        pages_out: list[PdfPageExtraction] = []
        for idx, page in enumerate(reader.pages, start=1):
            raw_text = (page.extract_text() or "").strip()
            lacks_tounicode = _inspect_page_symbol_fonts_missing_tounicode(page)
            has_garble, _ratio, frags = detect_symbol_garble(raw_text)
            embedded_images = (
                _extract_page_embedded_images(page)
                if (lacks_tounicode or has_garble or not raw_text)
                else ()
            )
            pages_out.append(
                PdfPageExtraction(
                    page_number=idx,
                    text=raw_text,
                    lacks_tounicode_symbol_font=lacks_tounicode,
                    has_symbol_garble=has_garble,
                    suspicious_fragments=frags,
                    embedded_images=embedded_images,
                )
            )
    except Exception as exc:
        if isinstance(exc, MaterialInvalidError):
            raise
        raise MaterialInvalidError(
            f"PDF 文件解析失败: {exc}",
            details={"error": str(exc)},
        ) from exc

    total_valid_chars = sum(1 for page in pages_out for ch in page.text if not ch.isspace())
    has_embedded_images = any(bool(page.embedded_images) for page in pages_out)
    if total_valid_chars < 10 and not has_embedded_images:
        raise MaterialInvalidError(
            "PDF文件无有效文字内容，扫描件请直接上传图片",
            details={"valid_char_count": total_valid_chars},
        )

    return pages_out


def _extract_text_from_pdf(content: bytes) -> str:
    """使用 pypdf 从 PDF 二进制中抽取正文纯文本并执行有效字符门禁。"""
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        extracted_pages = [page_text for page in reader.pages if (page_text := page.extract_text())]
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


def _local_name(tag: str) -> str:
    """剥离 XML 命名空间前缀，返回标签本地名。"""
    return tag.rsplit("}", 1)[-1]


def _extract_paragraphs_from_docx(content: bytes) -> list[str]:
    """从真实 DOCX（ZIP 容器）中抽取正文段落文本。"""
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


def _read_pptx_slides(content: bytes) -> list[tuple[str, bytes]]:
    """读取 PPTX 容器内按序号排序的幻灯片 XML 成员。"""
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
            return [(name, archive.read(name)) for name in slide_names]
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise MaterialInvalidError(
            "PPTX 文件损坏或格式不支持（非有效 OOXML ZIP 容器）",
            details={"error": str(exc)},
        ) from exc


def _extract_paragraphs_from_pptx(content: bytes) -> list[str]:
    """从真实 PPTX（ZIP 容器）中抽取幻灯片文本。"""
    slide_payloads = _read_pptx_slides(content)
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
            if _local_name(node.tag) == "t" and (text := (node.text or "").strip()):
                fragments.append(text)

    if not fragments:
        raise MaterialInvalidError(
            "PPTX 文档未包含可提取的正文文本",
            details={"slide_count": len(slide_payloads)},
        )
    return fragments


def extract_text_from_raw_content(content: bytes, file_format: str) -> list[str]:
    """从原始文件二进制中提取段落文本序列。

    Args:
        content: 原生文件二进制。
        file_format: 文件格式扩展名。

    Returns:
        list[str]: 提取的段落文本列表。
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


__all__ = [
    "MAGIC_NUMBERS",
    "PdfPageExtraction",
    "_extract_paragraphs_from_docx",
    "_extract_paragraphs_from_pptx",
    "_extract_text_from_pdf",
    "detect_image_type",
    "extract_pdf_pages_with_diagnostics",
    "extract_text_from_raw_content",
    "validate_file_magic",
]
