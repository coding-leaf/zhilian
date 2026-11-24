"""Pure document text and binary magic-byte extractors without database/network I/O."""

import io
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any
from xml.etree import ElementTree

import pymupdf
import pypdf

from app.core.algorithms.ocr_quality import detect_broken_math_layout, detect_symbol_garble
from app.core.errors import MaterialInvalidError

# PyMuPDF 仅提供部分类型标注，统一以 Any 访问以满足 mypy --strict。
_pymupdf: Any = pymupdf

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
    "cmr",
    "cmmi",
    "cmsy",
    "cmex",
    "msam",
    "msbm",
    "cambria",
    "stix",
    "latinmodern",
    "eusm",
    "euex",
    "wasy",
)

_VISUAL_OCR_MAX_VALID_CHARS: int = 60
_VISUAL_OCR_MIN_DRAWINGS: int = 8


@dataclass(frozen=True)
class PdfPageExtraction:
    """单页 PDF 解析及字体/符号乱码诊断结果。"""

    page_number: int
    text: str
    lacks_tounicode_symbol_font: bool
    has_symbol_garble: bool
    suspicious_fragments: tuple[str, ...] = ()
    embedded_images: tuple[bytes, ...] = ()
    has_broken_math_layout: bool = False
    needs_visual_ocr: bool = False

    @property
    def needs_repair(self) -> bool:
        """是否存在字体缺失 ToUnicode、ASCII/希腊西里尔符号乱码或公式版面破碎问题。"""
        return (
            self.lacks_tounicode_symbol_font
            or self.has_symbol_garble
            or self.has_broken_math_layout
        )


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


def _build_page_extraction(
    *,
    page_number: int,
    raw_text: str,
    lacks_tounicode: bool,
    image_loader: Callable[[], tuple[bytes, ...]],
    has_visual_content: bool = False,
) -> PdfPageExtraction:
    """基于单页文本与字体诊断构造 PdfPageExtraction（pypdf / PyMuPDF 共用）。"""
    has_garble, _ratio, frags = detect_symbol_garble(raw_text)
    broken_math = detect_broken_math_layout(raw_text)
    non_ws_count = sum(1 for ch in raw_text if not ch.isspace())
    needs_visual_ocr = has_visual_content and non_ws_count < _VISUAL_OCR_MAX_VALID_CHARS
    dirty = lacks_tounicode or has_garble or broken_math or needs_visual_ocr
    embedded_images = image_loader() if (dirty or not raw_text) else ()
    return PdfPageExtraction(
        page_number=page_number,
        text=raw_text,
        lacks_tounicode_symbol_font=lacks_tounicode,
        has_symbol_garble=has_garble,
        suspicious_fragments=frags,
        embedded_images=embedded_images,
        has_broken_math_layout=broken_math,
        needs_visual_ocr=needs_visual_ocr,
    )


def _enforce_valid_text_gate(pages_out: Sequence[PdfPageExtraction]) -> None:
    """全文有效字符门禁：既无文字又无内嵌图片的 PDF 视为无效扫描件。"""
    total_valid_chars = sum(1 for page in pages_out for ch in page.text if not ch.isspace())
    has_embedded_images = any(bool(page.embedded_images) for page in pages_out)
    if total_valid_chars < 10 and not has_embedded_images:
        raise MaterialInvalidError(
            "PDF文件无有效文字内容，扫描件请直接上传图片",
            details={"valid_char_count": total_valid_chars},
        )


def _order_blocks_reading_order(blocks: Sequence[Any], page_width: float) -> list[Any]:
    """将 PyMuPDF 文本块按阅读顺序排序：双栏页先左栏后右栏，其余自上而下、自左而右。"""
    text_blocks = [b for b in blocks if len(b) >= 5 and str(b[4]).strip()]
    if not text_blocks or page_width <= 0:
        return list(text_blocks)

    mid = page_width / 2.0
    narrow = [b for b in text_blocks if (float(b[2]) - float(b[0])) < page_width * 0.55]
    left = [b for b in narrow if float(b[2]) <= mid * 1.08]
    right = [b for b in narrow if float(b[0]) >= mid * 0.92]
    is_two_column = (
        len(left) >= 2 and len(right) >= 2 and len(left) + len(right) >= len(text_blocks) * 0.6
    )
    if not is_two_column:
        return sorted(text_blocks, key=lambda b: (round(float(b[1]), 1), float(b[0])))

    left_ids = {id(b) for b in left}
    right_ids = {id(b) for b in right}
    full_width = [b for b in text_blocks if id(b) not in left_ids and id(b) not in right_ids]
    # 跨栏块（标题/页眉/页脚）作为分隔，把页面切成上下带，带内先左后右。
    ordered: list[Any] = []
    cursor_y = float("-inf")
    for separator in [*sorted(full_width, key=lambda b: float(b[1])), None]:
        limit_y = float("inf") if separator is None else float(separator[1])
        for column in (left, right):
            ordered.extend(
                sorted(
                    (b for b in column if cursor_y <= float(b[1]) < limit_y),
                    key=lambda b: float(b[1]),
                )
            )
        if separator is not None:
            ordered.append(separator)
            cursor_y = float(separator[1]) + 0.01
    return ordered


def _pymupdf_page_text(page: Any) -> str:
    """用 PyMuPDF 块级坐标抽取单页文本，按阅读顺序以空行分隔段落块。"""
    blocks = page.get_text("blocks")
    ordered = _order_blocks_reading_order(
        [b for b in blocks if len(b) < 7 or int(b[6]) == 0], float(page.rect.width)
    )
    parts = [str(b[4]).strip() for b in ordered]
    return "\n\n".join(part for part in parts if part).strip()


def _pymupdf_page_lacks_tounicode(doc: Any, page: Any) -> bool:
    """检测页内是否存在缺失 /ToUnicode 的符号/数学字体（PyMuPDF 版）。"""
    try:
        fonts = page.get_fonts(full=True)
    except Exception:
        return False
    for font in fonts:
        xref = int(font[0])
        base_font = str(font[3]).lower()
        if not any(marker in base_font for marker in _SYMBOL_FONT_MARKERS):
            continue
        try:
            key_type = doc.xref_get_key(xref, "ToUnicode")[0]
        except Exception:
            key_type = "unknown"
        if key_type == "null":
            return True
    return False


def _pymupdf_page_images(doc: Any, page: Any) -> tuple[bytes, ...]:
    """提取 PyMuPDF 页面内嵌位图（至多 3 张）。"""
    collected: list[bytes] = []
    try:
        for img in page.get_images(full=True):
            extracted = doc.extract_image(int(img[0]))
            data = extracted.get("image") if isinstance(extracted, dict) else None
            if isinstance(data, bytes) and data:
                collected.append(data)
            if len(collected) >= 3:
                break
    except Exception:
        return tuple(collected)
    return tuple(collected)


def _pymupdf_page_has_visual_content(page: Any) -> bool:
    """判断 PyMuPDF 单页是否包含内嵌位图或复杂矢量绘图（>= 8 条路径）。"""
    has_images = False
    try:
        get_images = getattr(page, "get_images", None)
        if callable(get_images):
            has_images = len(get_images(full=True)) > 0
    except Exception:
        has_images = False
    if has_images:
        return True
    try:
        get_drawings = getattr(page, "get_drawings", None)
        if callable(get_drawings):
            return len(get_drawings()) >= _VISUAL_OCR_MIN_DRAWINGS
    except Exception:
        return False
    return False


def _pypdf_page_has_visual_content(page: Any) -> bool:
    """判断 pypdf 单页是否包含内嵌图片对象。"""
    try:
        return bool(getattr(page, "images", None))
    except Exception:
        return False


def _extract_pages_with_pymupdf(content: bytes) -> list[PdfPageExtraction] | None:
    """PyMuPDF 优先通道：坐标/块感知阅读顺序抽取。无法打开或无任何文本时返回 None 让调用方降级。"""
    try:
        _pymupdf.TOOLS.mupdf_display_errors(False)
        doc = _pymupdf.open(stream=content, filetype="pdf")
    except Exception:
        return None
    try:
        if doc.needs_pass or doc.page_count == 0:
            return None
        pages_out: list[PdfPageExtraction] = []
        for idx in range(doc.page_count):
            page = doc.load_page(idx)
            raw_text = _pymupdf_page_text(page)
            pages_out.append(
                _build_page_extraction(
                    page_number=idx + 1,
                    raw_text=raw_text,
                    lacks_tounicode=_pymupdf_page_lacks_tounicode(doc, page),
                    image_loader=partial(_pymupdf_page_images, doc, page),
                    has_visual_content=_pymupdf_page_has_visual_content(page),
                )
            )
    except Exception:
        return None
    finally:
        doc.close()
    if not any(p.text.strip() or p.embedded_images for p in pages_out):
        return None
    return pages_out


def _extract_pages_with_pypdf(content: bytes) -> list[PdfPageExtraction]:
    """pypdf 降级通道（PyMuPDF 无法解析时使用）。"""
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        return [
            _build_page_extraction(
                page_number=idx,
                raw_text=(page.extract_text() or "").strip(),
                lacks_tounicode=_inspect_page_symbol_fonts_missing_tounicode(page),
                image_loader=partial(_extract_page_embedded_images, page),
                has_visual_content=_pypdf_page_has_visual_content(page),
            )
            for idx, page in enumerate(reader.pages, start=1)
        ]
    except Exception as exc:
        if isinstance(exc, MaterialInvalidError):
            raise
        raise MaterialInvalidError(
            f"PDF 文件解析失败: {exc}",
            details={"error": str(exc)},
        ) from exc


def extract_pdf_pages_with_diagnostics(content: bytes) -> list[PdfPageExtraction]:
    """按页提取 PDF 文本，并检测缺失 `/ToUnicode` 符号字体、ASCII 乱码簇与公式版面破碎。

    优先使用 PyMuPDF 的块级坐标阅读顺序抽取；PyMuPDF 无法解析（或未取得任何文本，
    例如纯扫描件）时降级为 pypdf，保证既有兼容性。
    """
    pages_out = _extract_pages_with_pymupdf(content)
    if pages_out is None:
        pages_out = _extract_pages_with_pypdf(content)
    _enforce_valid_text_gate(pages_out)
    return pages_out


def render_pdf_page_png(pdf_bytes: bytes, page_number: int, dpi: int = 150) -> bytes:
    """将 PDF 指定页（1 起始）渲染为 PNG 字节流，供云端 VLM 转录脏页。

    Args:
        pdf_bytes: PDF 原始二进制。
        page_number: 页码（从 1 开始）。
        dpi: 渲染分辨率，缺省 150。

    Returns:
        bytes: PNG 图片二进制。

    Raises:
        MaterialInvalidError: PDF 无法打开、页码越界或渲染失败。
    """
    try:
        doc = _pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise MaterialInvalidError(
            "PDF 页面渲染失败：文件无法打开",
            details={"error": type(exc).__name__},
        ) from exc
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise MaterialInvalidError(
                "PDF 页面渲染失败：页码越界",
                details={"page_number": page_number, "page_count": doc.page_count},
            )
        pixmap = doc.load_page(page_number - 1).get_pixmap(dpi=dpi)
        png_bytes: bytes = pixmap.tobytes("png")
        return png_bytes
    except MaterialInvalidError:
        raise
    except Exception as exc:
        raise MaterialInvalidError(
            "PDF 页面渲染失败",
            details={"page_number": page_number, "error": type(exc).__name__},
        ) from exc
    finally:
        doc.close()


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
    "render_pdf_page_png",
    "validate_file_magic",
]
