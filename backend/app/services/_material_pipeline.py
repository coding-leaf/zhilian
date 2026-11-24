"""Internal pipeline helpers and typed view models for MaterialService."""

import base64
import logging
import re
import threading
import time
import uuid
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.algorithms.document_denoising import (
    PageRole,
    PageTextInput,
    classify_pages_with_fallback,
    is_non_substantive_chapter,
    strip_repeated_headers_footers,
)
from app.core.algorithms.markdown_blocks import (
    split_markdown_blocks,
    unwrap_pdf_visual_line_breaks,
)
from app.core.algorithms.material_chunking import (
    ParagraphInput,
    split_material_into_snippets,
)
from app.core.algorithms.ocr_quality import (
    OCRPageInput,
    detect_symbol_garble,
    sanitize_symbol_garble,
    verify_ocr_quality,
)
from app.core.errors import MaterialInvalidError
from app.core.extractors import PdfPageExtraction, render_pdf_page_png
from app.integrations.embedding.protocol import EmbeddingProtocol
from app.integrations.llm.protocol import LLMMessage, LLMOptions, LLMProtocol
from app.integrations.ocr.protocol import OCRProtocol
from app.integrations.storage.protocol import StorageProtocol
from app.models.material import (
    Material,
    MaterialOCRPage,
    MaterialSnippet,
    MaterialStatus,
    ParseStatus,
)
from app.repositories.material import MaterialRepository

ACTIVE_PARSE_STATUSES: frozenset[str] = frozenset(
    {
        ParseStatus.QUEUED.value,
        ParseStatus.PARSING_DOC.value,
        ParseStatus.OCR_PROCESSING.value,
        ParseStatus.EXTRACTING_KNOWLEDGE.value,
        ParseStatus.AUDITING_KNOWLEDGE.value,
        ParseStatus.EMBEDDING_GENERATION.value,
    }
)

_PARSE_PROGRESS_KEY_PREFIX: str = "zhilian:parse_progress:"
_PARSE_PROGRESS_TTL_SECONDS: int = 3600
_LOCAL_PROGRESS_LOCK = threading.Lock()
_LOCAL_PROGRESS_CACHE: dict[uuid.UUID, tuple[int, float]] = {}


def resolve_progress_redis_client(queue: Any, idempotency: Any = None) -> Any | None:
    """从队列或幂等适配器中提取可用的 Redis 客户端（Duck-typed，无网络回落）。"""
    for adapter in (queue, idempotency):
        client = getattr(adapter, "_client", None)
        if (
            client is not None
            and callable(getattr(client, "get", None))
            and callable(getattr(client, "set", None))
        ):
            return client
    return None


def _progress_cache_key(version_id: uuid.UUID) -> str:
    return f"{_PARSE_PROGRESS_KEY_PREFIX}{version_id}"


def _parse_cached_progress_value(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        value = int(text.strip())
    except (ValueError, UnicodeDecodeError):
        return None
    return max(0, min(100, value))


def set_cached_parse_progress(
    version_id: uuid.UUID,
    percentage: int,
    *,
    redis_client: Any | None = None,
) -> None:
    """写入版本级实时解析进度缓存（优先 Redis，降级进程内内存缓存）。"""
    clamped = max(0, min(100, int(percentage)))
    if redis_client is not None:
        try:
            redis_client.set(
                _progress_cache_key(version_id),
                str(clamped),
                ex=_PARSE_PROGRESS_TTL_SECONDS,
            )
            return
        except Exception as exc:
            _pipeline_logger.warning("set parse progress redis failed: %s", exc)
    expires_at = time.monotonic() + _PARSE_PROGRESS_TTL_SECONDS
    with _LOCAL_PROGRESS_LOCK:
        _LOCAL_PROGRESS_CACHE[version_id] = (clamped, expires_at)


def get_cached_parse_progress(
    version_id: uuid.UUID,
    *,
    redis_client: Any | None = None,
) -> int | None:
    """读取版本级实时解析进度缓存；不存在或过期返回 None。"""
    if redis_client is not None:
        try:
            return _parse_cached_progress_value(redis_client.get(_progress_cache_key(version_id)))
        except Exception as exc:
            _pipeline_logger.warning("get parse progress redis failed: %s", exc)
    now = time.monotonic()
    with _LOCAL_PROGRESS_LOCK:
        entry = _LOCAL_PROGRESS_CACHE.get(version_id)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at <= now:
            _LOCAL_PROGRESS_CACHE.pop(version_id, None)
            return None
        return value


def get_cached_parse_progress_batch(
    version_ids: Sequence[uuid.UUID],
    *,
    redis_client: Any | None = None,
) -> dict[uuid.UUID, int]:
    """批量读取多个活跃版本的实时解析进度缓存，避免列表接口产生 N+1 往返。"""
    unique_ids = list(dict.fromkeys(version_ids))
    if not unique_ids:
        return {}
    if redis_client is not None and callable(getattr(redis_client, "mget", None)):
        try:
            keys = [_progress_cache_key(vid) for vid in unique_ids]
            raw_values = redis_client.mget(keys)
            results: dict[uuid.UUID, int] = {}
            for vid, raw in zip(unique_ids, raw_values, strict=False):
                parsed = _parse_cached_progress_value(raw)
                if parsed is not None:
                    results[vid] = parsed
            return results
        except Exception as exc:
            _pipeline_logger.warning("batch get parse progress redis failed: %s", exc)

    results = {}
    for vid in unique_ids:
        cached = get_cached_parse_progress(vid, redis_client=redis_client)
        if cached is not None:
            results[vid] = cached
    return results


def clear_cached_parse_progress(
    version_id: uuid.UUID,
    *,
    redis_client: Any | None = None,
) -> None:
    """清理指定版本的实时解析进度缓存。"""
    with _LOCAL_PROGRESS_LOCK:
        _LOCAL_PROGRESS_CACHE.pop(version_id, None)
    if redis_client is not None and callable(getattr(redis_client, "delete", None)):
        try:
            redis_client.delete(_progress_cache_key(version_id))
        except Exception as exc:
            _pipeline_logger.warning("clear parse progress redis failed: %s", exc)


@dataclass(frozen=True)
class MaterialDetailView:
    """资料详情与列表解析进度的强类型只读视图，替代 ORM 实例动态挂载属性。"""

    material: Material
    parse_status: str | None = None
    progress_percentage: int | None = None
    key_points_count: int | None = None
    page_count: int | None = None
    error_message: str | None = None
    failed_stage: str | None = None

    @property
    def id(self) -> uuid.UUID:
        return self.material.id

    @property
    def user_id(self) -> uuid.UUID:
        return self.material.user_id

    @property
    def title(self) -> str:
        return self.material.title

    @property
    def file_format(self) -> str:
        return self.material.file_format

    @property
    def file_size(self) -> int:
        return self.material.file_size

    @property
    def source_type(self) -> str:
        return self.material.source_type

    @property
    def status(self) -> str:
        return self.material.status

    @property
    def current_version_id(self) -> uuid.UUID | None:
        return self.material.current_version_id

    @property
    def folder_id(self) -> uuid.UUID | None:
        return self.material.folder_id

    @property
    def is_deleted(self) -> bool:
        return self.material.is_deleted

    @property
    def created_at(self) -> Any:
        return self.material.created_at

    @property
    def updated_at(self) -> Any:
        return self.material.updated_at

    @property
    def versions(self) -> list[Any]:
        return list(self.material.versions or [])

    @property
    def versions_count(self) -> int:
        return len(self.material.versions or [])

    def __getattr__(self, name: str) -> Any:
        return getattr(self.material, name)


def process_initial_ocr_page(
    *,
    storage: StorageProtocol,
    ocr: OCRProtocol,
    bucket: str,
    user_id: uuid.UUID,
    material_id: uuid.UUID,
    version_id: uuid.UUID,
    version_number: int,
    clean_format: str,
    file_bytes: bytes,
) -> tuple[MaterialOCRPage, bool, str | None]:
    """执行首轮图片 OCR 识别、质量门禁校验与页面对象上传。"""
    ocr_result = ocr.recognize_image(file_bytes)
    page_input = OCRPageInput(page_number=1, raw_text=ocr_result.full_text, reshoot_count=0)
    report = verify_ocr_quality([page_input])
    page_report = report.page_results[0]

    page_storage_key = f"users/{user_id}/materials/{material_id}/v{version_number}/pages/page_1.png"
    storage.put_object(bucket, page_storage_key, file_bytes, f"image/{clean_format}")

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
    return ocr_page, report.is_all_qualified, page_report.unqualified_reason


_GARBLE_REPAIR_SYSTEM_PROMPT: str = (
    "你是学术文档公式与符号乱码修复器。"
    "输入是从 PDF（含缺失 ToUnicode 映射的 Symbol 字体）抽取的单页文本，"
    '其中部分希腊字母、集合运算或数学符号退化为 ASCII 乱码（如 AB&A&、"#$"$、!" ! #）。\n'
    "【严格约束】:\n"
    "1. 清除无法辨认的纯乱码噪声字符，并依据前后句意与可选 OCR 识别参考，"
    "将能够确定的数学表达式或符号恢复为规范可读文本或 `$LaTeX$` 公式；\n"
    "2. 严禁凭空扩写、总结或编造原文没有出现的概念、定理、结论或数值；\n"
    "3. 保持正常段落文本与结构不变，直接输出修复后的纯文本，不要添加额外解释或标题。"
)

_pipeline_logger = logging.getLogger(__name__)


def _try_ocr_pdf_page(
    page: PdfPageExtraction,
    pdf_bytes: bytes,
    ocr: OCRProtocol | None,
) -> str:
    """当 PDF 页面存在乱码时尝试利用内嵌页面图像或适配器的 PDF OCR 能力提取辅助文本。"""
    if ocr is None:
        return ""
    texts: list[str] = []
    for img_bytes in page.embedded_images[:2]:
        try:
            res = ocr.recognize_image(img_bytes)
            if res.full_text and res.full_text.strip():
                texts.append(res.full_text.strip())
        except Exception as exc:
            _pipeline_logger.warning("pdf embedded image OCR degraded: %s", exc)
    if texts:
        return "\n".join(texts)

    recognize_pdf_page = getattr(ocr, "recognize_pdf_page", None)
    if callable(recognize_pdf_page):
        try:
            res = recognize_pdf_page(pdf_bytes, page_number=page.page_number)
            full_text = getattr(res, "full_text", "")
            if isinstance(full_text, str) and full_text.strip():
                return full_text.strip()
        except Exception as exc:
            _pipeline_logger.warning("pdf page OCR degraded: %s", exc)

    if pdf_bytes and (page.needs_repair or page.needs_visual_ocr or not page.text.strip()):
        try:
            png_bytes = render_pdf_page_png(pdf_bytes, page.page_number, dpi=150)
            res = ocr.recognize_image(png_bytes)
            if res.full_text and res.full_text.strip():
                return res.full_text.strip()
        except Exception as exc:
            _pipeline_logger.warning("pdf rendered-page image OCR degraded: %s", exc)
    return ""


def _repair_pdf_page_text(
    page: PdfPageExtraction,
    pdf_bytes: bytes,
    ocr: OCRProtocol | None,
    llm: LLMProtocol | None,
) -> str:
    """对标记为符号字体乱码/缺失 ToUnicode/图文少字页的单页 PDF 文本执行 OCR+LLM 定向修复。"""
    if not page.needs_repair and page.text.strip():
        if page.needs_visual_ocr:
            ocr_hint = _try_ocr_pdf_page(page, pdf_bytes, ocr)
            if ocr_hint:
                base = page.text.strip()
                return ocr_hint if base in ocr_hint else f"{base}\n\n{ocr_hint}"
        return page.text

    ocr_hint = _try_ocr_pdf_page(page, pdf_bytes, ocr)
    base_text = page.text.strip()
    if not page.needs_repair:
        return ocr_hint or base_text

    still_garbled_ocr = False
    if ocr_hint:
        still_garbled_ocr, _, _ = detect_symbol_garble(ocr_hint)
        if not still_garbled_ocr and (not base_text or page.has_symbol_garble) and llm is None:
            return ocr_hint

    if llm is not None and (base_text or ocr_hint):
        user_parts = [f"【原始抽取文本（第 {page.page_number} 页）】:\n{base_text or '(空)'}"]
        if ocr_hint:
            user_parts.append(f"【OCR 识别辅助参考】:\n{ocr_hint}")
        if page.suspicious_fragments:
            user_parts.append(f"【疑似乱码片段】: {' | '.join(page.suspicious_fragments[:5])}")
        try:
            resp = llm.generate(
                messages=[
                    LLMMessage(role="system", content=_GARBLE_REPAIR_SYSTEM_PROMPT),
                    LLMMessage(role="user", content="\n\n".join(user_parts)),
                ],
                options=LLMOptions(temperature=0.1),
            )
            repaired = resp.content.strip() if resp and resp.content else ""
            if repaired:
                still_bad, _, _ = detect_symbol_garble(repaired)
                return sanitize_symbol_garble(repaired) if still_bad else repaired
        except Exception as exc:
            _pipeline_logger.warning("pdf garble LLM repair degraded: %s", exc)

    if ocr_hint and not still_garbled_ocr:
        return ocr_hint
    return sanitize_symbol_garble(ocr_hint or base_text)


_VLM_TRANSCRIBE_SYSTEM_PROMPT: str = (
    "你是学术文档页面转录器。输入是一页 PDF 的截图，请逐字转录页面上的全部可见内容。\n"
    "【严格约束】:\n"
    "1. 只做忠实转录：保持原文语言、顺序与段落结构，输出 Markdown；\n"
    "2. 行内公式用 `$...$`，独立成行的展示公式用 `$$...$$`，"
    "矩阵/分段函数使用标准 LaTeX 环境；\n"
    "3. 表格输出为 Markdown 管道表格（| a | b |）；标题用 # 标记；\n"
    "4. 严禁总结、改写、翻译、扩写或补充页面上没有出现的任何概念、结论、数值或公式；\n"
    "5. 看不清的内容宁可省略，也不要猜测；不要输出页码、水印或任何额外解释，"
    "不要用代码块包裹结果。"
)

_VLM_TRANSCRIBE_USER_PROMPT: str = "请严格按要求转录第 {page_number} 页的全部内容。"

_CODE_FENCE_WRAPPER = re.compile(r"^\s*```(?:markdown|md|latex|text)?\s*\n(.*?)\n\s*```\s*$", re.S)


def _strip_vlm_code_fence(text: str) -> str:
    """去除 VLM 偶发包裹整页输出的 Markdown 代码围栏。"""
    stripped = text.strip()
    match = _CODE_FENCE_WRAPPER.match(stripped)
    return match.group(1).strip() if match else stripped


def _transcribe_page_with_vlm(
    vlm: LLMProtocol,
    png_bytes: bytes,
    page_number: int,
    *,
    timeout: float,
) -> str:
    """把单页 PNG 编码为 data URI 送 VLM 转录；返回 Markdown+LaTeX 文本（空串表示无结果）。"""
    data_uri = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    resp = vlm.generate(
        messages=[
            LLMMessage(role="system", content=_VLM_TRANSCRIBE_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=_VLM_TRANSCRIBE_USER_PROMPT.format(page_number=page_number),
                image_urls=(data_uri,),
            ),
        ],
        options=LLMOptions(temperature=0.0, max_tokens=4096, timeout=timeout),
    )
    transcript = _strip_vlm_code_fence(resp.content) if resp and resp.content else ""
    if not transcript:
        return ""
    still_garbled, _, _ = detect_symbol_garble(transcript)
    return sanitize_symbol_garble(transcript) if still_garbled else transcript


def _page_needs_vlm(page: PdfPageExtraction) -> bool:
    """仅公式乱码 / 缺字库 / 图文少字页 / 高密度公式风险 / 无文字的脏页才送 VLM；干净页零成本。"""
    return (
        page.needs_repair
        or page.needs_visual_ocr
        or page.has_formula_visual_risk
        or not page.text.strip()
    )


def transcribe_dirty_pages_with_vlm(
    pages: Sequence[PdfPageExtraction],
    pdf_bytes: bytes,
    vlm: LLMProtocol,
    *,
    dpi: int = 150,
    max_concurrency: int = 3,
    timeout: float = 45.0,
) -> dict[int, str]:
    """并发把脏页渲染为 PNG 并交 VLM 转录；单页失败只记录告警并从结果中缺席。

    渲染在调用线程内串行完成（PyMuPDF 非线程安全），HTTP 调用在受限线程池内并发。

    Returns:
        dict[int, str]: 页码 -> 转录 Markdown（仅包含成功且非空的页）。
    """
    rendered: dict[int, bytes] = {}
    for page in pages:
        if not _page_needs_vlm(page):
            continue
        try:
            rendered[page.page_number] = render_pdf_page_png(pdf_bytes, page.page_number, dpi=dpi)
        except Exception as exc:
            _pipeline_logger.warning(
                "pdf page render for VLM degraded: page=%s error=%s",
                page.page_number,
                type(exc).__name__,
            )
    if not rendered:
        return {}

    results: dict[int, str] = {}
    workers = max(1, min(max_concurrency, len(rendered)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="vlm-page") as pool:
        futures = {
            pool.submit(_transcribe_page_with_vlm, vlm, png, page_number, timeout=timeout): (
                page_number
            )
            for page_number, png in rendered.items()
        }
        for future, page_number in futures.items():
            try:
                transcript = future.result()
            except Exception as exc:
                _pipeline_logger.warning(
                    "pdf page VLM transcription degraded: page=%s error=%s",
                    page_number,
                    type(exc).__name__,
                )
                continue
            if transcript.strip():
                results[page_number] = transcript
    return results


_MD_HEADING_BLOCK_RE: re.Pattern[str] = re.compile(r"^(#{1,6})\s+.+$")
_PLAIN_HEADING_FORBIDDEN_CHARS: frozenset[str] = frozenset("。！？!?;:，,=$\\|`")
_PLAIN_LIST_OR_QUOTE_RE: re.Pattern[str] = re.compile(r"^(?:[-*•]\s+|\d+[.)]\s+|>\s?|```|\|)")
_DOTTED_WORD_RE: re.Pattern[str] = re.compile(r"[A-Za-z]\.[A-Za-z]")
_PLAIN_HEADING_TRAILING_STOP: tuple[str, ...] = (
    ".",
    "。",
    "！",
    "？",
    "!",
    "?",
    "：",
    ":",
    "的",
    "了",
    "和",
    "与",
    "或",
    "在",
    "对",
    "将",
    "把",
    "被",
)


def is_heading_block(block: str) -> bool:
    """判断单个文本块是否为 Markdown 标题或独立短小节标题（如“基本概念”）。"""
    stripped = block.strip()
    if not stripped or "\n" in stripped:
        return False
    if _MD_HEADING_BLOCK_RE.match(stripped):
        return True
    if not (2 <= len(stripped) <= 20):
        return False
    if stripped.isdigit() or _PLAIN_LIST_OR_QUOTE_RE.match(stripped):
        return False
    if any(ch in _PLAIN_HEADING_FORBIDDEN_CHARS for ch in stripped):
        return False
    if _DOTTED_WORD_RE.search(stripped):
        return False
    return not stripped.endswith(_PLAIN_HEADING_TRAILING_STOP)


def _build_pdf_paragraphs_from_classified(
    non_empty_pages: Sequence[tuple[int, str]],
    roles: Sequence[PageRole],
) -> tuple[list[ParagraphInput], str]:
    """根据页面角色分类结果，把去噪后的 PDF 页面转为带章节标记的段落序列。"""
    content_entries: list[tuple[int, str, list[str]]] = []
    section_dividers: dict[int, str] = {}
    for (pn, txt), role in zip(non_empty_pages, roles, strict=True):
        if role in {
            PageRole.COVER,
            PageRole.TOC,
            PageRole.THANK_YOU,
            PageRole.REFERENCES,
            PageRole.CHAPTER_SUMMARY,
            PageRole.LOW_INFO,
        }:
            continue
        if role == PageRole.SECTION_DIVIDER:
            section_dividers[pn] = " ".join(ln.strip() for ln in txt.splitlines() if ln.strip())
            continue
        content_entries.append((pn, txt, split_markdown_blocks(txt)))

    has_substantive_body = any(
        not is_heading_block(blk) for _pn, _txt, blks in content_entries for blk in blks
    )
    paragraphs: list[ParagraphInput] = []
    page_texts: list[str] = []
    content_by_page = {pn: (txt, blks) for pn, txt, blks in content_entries}
    for pn, _txt in non_empty_pages:
        if pn in section_dividers:
            divider_title = section_dividers[pn]
            page_texts.append(divider_title)
            paragraphs.append(
                ParagraphInput(
                    text=divider_title,
                    source_ref=f"第 {pn} 页",
                    doc_type="pdf",
                    is_title=True,
                    title_level=1,
                    page_number=pn,
                )
            )
            continue
        if pn not in content_by_page:
            continue
        repaired_text, blocks = content_by_page[pn]
        page_texts.append(repaired_text)
        page_has_body = any(not is_heading_block(blk) for blk in blocks)
        for block in blocks:
            paragraphs.append(
                _build_pdf_block_paragraph(
                    block,
                    pn,
                    has_body_context=page_has_body or has_substantive_body,
                )
            )
    return paragraphs, "\n\n".join(page_texts)


def _build_pdf_block_paragraph(
    block: str,
    page_number: int,
    *,
    has_body_context: bool,
) -> ParagraphInput:
    """构造单块 PDF ParagraphInput（非实质章节标题如「小结」不覆盖当前章节状态）。"""
    md_match = _MD_HEADING_BLOCK_RE.match(block.strip())
    if md_match:
        heading_text = _MD_HEADING_BLOCK_RE.sub("", block.strip()).lstrip("#").strip()
        is_title = not is_non_substantive_chapter(heading_text)
        title_level = len(md_match.group(1)) if is_title else 0
    elif is_heading_block(block) and has_body_context and not is_non_substantive_chapter(block):
        is_title = True
        title_level = 1
    else:
        is_title = False
        title_level = 0
    return ParagraphInput(
        text=block,
        source_ref=f"第 {page_number} 页",
        doc_type="pdf",
        is_title=is_title,
        title_level=title_level,
        page_number=page_number,
    )


def repair_garbled_pdf_pages(
    pages: Sequence[PdfPageExtraction],
    pdf_bytes: bytes,
    *,
    ocr: OCRProtocol | None,
    llm: LLMProtocol | None,
    vlm: LLMProtocol | None = None,
    vlm_dpi: int = 150,
    vlm_max_concurrency: int = 3,
    vlm_timeout: float = 45.0,
) -> tuple[list[ParagraphInput], str]:
    """逐页检测修复 PDF 乱码，执行跨页去噪与模板页过滤，产出保留页码溯源的段落列表与全文。"""
    vlm_transcripts: dict[int, str] = {}
    if vlm is not None:
        vlm_transcripts = transcribe_dirty_pages_with_vlm(
            pages,
            pdf_bytes,
            vlm,
            dpi=vlm_dpi,
            max_concurrency=vlm_max_concurrency,
            timeout=vlm_timeout,
        )

    repaired_pages: list[tuple[int, str, PdfPageExtraction, bool]] = []
    for page in pages:
        vlm_text = vlm_transcripts.get(page.page_number)
        if vlm_text is not None:
            repaired_text = vlm_text.strip()
            used_vlm = True
        else:
            repaired_text = _repair_pdf_page_text(page, pdf_bytes, ocr, llm).strip()
            used_vlm = False
        if not repaired_text:
            continue
        repaired_pages.append((page.page_number, repaired_text, page, used_vlm))

    if not repaired_pages:
        return [], ""

    denoised_texts = strip_repeated_headers_footers(
        [
            PageTextInput(
                page_number=pn,
                text=txt,
                blocks=() if used_vlm else pg.blocks,
            )
            for pn, txt, pg, used_vlm in repaired_pages
        ]
    )
    non_empty_pages: list[tuple[int, str]] = []
    for (pn, _raw, _pg, used_vlm), txt in zip(repaired_pages, denoised_texts, strict=True):
        stripped = txt.strip()
        if not stripped:
            continue
        final_txt = stripped if used_vlm else unwrap_pdf_visual_line_breaks(stripped)
        if final_txt.strip():
            non_empty_pages.append((pn, final_txt.strip()))
    if not non_empty_pages:
        return [], ""

    roles = classify_pages_with_fallback(non_empty_pages, is_slide_like=True)
    return _build_pdf_paragraphs_from_classified(non_empty_pages, roles)


def denoise_pptx_slides(
    raw_paragraphs: Sequence[ParagraphInput],
) -> tuple[list[ParagraphInput], str]:
    """对按页抽取的 PPTX 幻灯片段落执行 Stage 2 跨页去噪与 Stage 4 模板页过滤。"""
    if not raw_paragraphs:
        return [], ""

    slides_order: list[int] = []
    grouped: dict[int, list[ParagraphInput]] = {}
    for idx, para in enumerate(raw_paragraphs, start=1):
        pn = para.page_number if para.page_number is not None else idx
        if pn not in grouped:
            slides_order.append(pn)
            grouped[pn] = []
        grouped[pn].append(para)

    page_inputs = [
        PageTextInput(
            page_number=pn,
            text="\n".join(p.text for p in grouped[pn]),
        )
        for pn in slides_order
    ]
    denoised_slide_texts = strip_repeated_headers_footers(page_inputs)
    non_empty_slides = [
        (pn, txt.strip())
        for pn, txt in zip(slides_order, denoised_slide_texts, strict=True)
        if txt.strip()
    ]
    if not non_empty_slides:
        return [], ""

    roles = classify_pages_with_fallback(non_empty_slides, is_slide_like=True)
    paragraphs: list[ParagraphInput] = []
    slide_texts: list[str] = []

    for (pn, denoised_txt), role in zip(non_empty_slides, roles, strict=True):
        if role in {
            PageRole.COVER,
            PageRole.TOC,
            PageRole.THANK_YOU,
            PageRole.REFERENCES,
            PageRole.CHAPTER_SUMMARY,
            PageRole.LOW_INFO,
        }:
            continue
        slide_texts.append(denoised_txt)
        if role == PageRole.SECTION_DIVIDER:
            divider = " ".join(ln.strip() for ln in denoised_txt.splitlines() if ln.strip())
            paragraphs.append(
                ParagraphInput(
                    text=divider,
                    source_ref=f"第 {pn} 页",
                    doc_type="pptx",
                    is_title=True,
                    title_level=1,
                    page_number=pn,
                )
            )
            continue

        allowed_lines = {ln.strip() for ln in denoised_txt.splitlines() if ln.strip()}
        for para in grouped[pn]:
            kept_lines = [
                ln.strip() for ln in para.text.splitlines() if ln.strip() in allowed_lines
            ]
            if not kept_lines:
                continue
            merged_para = "\n".join(kept_lines)
            is_title = para.is_title and not is_non_substantive_chapter(merged_para)
            paragraphs.append(
                ParagraphInput(
                    text=merged_para,
                    source_ref=para.source_ref,
                    doc_type="pptx",
                    is_title=is_title,
                    title_level=para.title_level if is_title else 0,
                    page_number=pn,
                )
            )
    return paragraphs, "\n\n".join(slide_texts)


_GENERIC_SOURCE_REF: str = "段落"


def build_contextual_snippet_text(*, chapter_title: str, source_ref: str, content: str) -> str:
    """生成仅用于向量化的 Contextual Retrieval 文本：``[章节 · 页码]\\n正文``。

    数据库存储的 ``MaterialSnippet.content`` 保持原文干净，前缀只参与 embedding。
    """
    ref = "" if source_ref.strip() == _GENERIC_SOURCE_REF else source_ref
    label = " · ".join(part.strip() for part in (chapter_title, ref) if part and part.strip())
    return f"[{label}]\n{content}" if label else content


def prepare_material_snippets(
    *,
    embedding: EmbeddingProtocol,
    material_id: uuid.UUID,
    version_id: uuid.UUID,
    user_id: uuid.UUID,
    paragraphs: Sequence[str | ParagraphInput],
    require_non_empty: bool = True,
) -> list[MaterialSnippet]:
    """纯内存切分段落并批量向量化，返回带预分配主键的切片实体列表（不写库）。"""
    chunk_result = split_material_into_snippets(paragraphs, allow_cross_page_merge=True)
    if require_non_empty and not chunk_result.snippets:
        raise MaterialInvalidError("资料有效内容不足，未切分出有效知识片段")

    snippet_texts = [
        build_contextual_snippet_text(
            chapter_title=snip.chapter_title,
            source_ref=snip.source_ref,
            content=snip.content,
        )
        for snip in chunk_result.snippets
    ]
    vectors = embedding.embed_documents(snippet_texts)
    snippets_to_save: list[MaterialSnippet] = []
    for i, snip in enumerate(chunk_result.snippets):
        info: dict[str, Any] = {"source_ref": snip.source_ref}
        if snip.page_number is not None:
            info["page_number"] = snip.page_number
        if snip.page_end is not None:
            info["page_end"] = snip.page_end
        snippets_to_save.append(
            MaterialSnippet(
                id=uuid.uuid4(),
                user_id=user_id,
                material_id=material_id,
                version_id=version_id,
                snippet_index=snip.index,
                content=snip.content,
                char_length=snip.char_count,
                start_offset=snip.start_offset,
                end_offset=snip.end_offset,
                chapter_title=snip.chapter_title,
                source_info=info,
                embedding=vectors[i] if i < len(vectors) else None,
            )
        )
    return snippets_to_save


def chunk_embed_and_replace_snippets(
    *,
    repo: MaterialRepository,
    embedding: EmbeddingProtocol,
    material_id: uuid.UUID,
    version_id: uuid.UUID,
    user_id: uuid.UUID,
    paragraphs: Sequence[str | ParagraphInput],
    require_non_empty: bool = True,
) -> None:
    """将文本段落切分为知识片段、批量向量化并幂等替换旧版本切片。"""
    snippets_to_save = prepare_material_snippets(
        embedding=embedding,
        material_id=material_id,
        version_id=version_id,
        user_id=user_id,
        paragraphs=paragraphs,
        require_non_empty=require_non_empty,
    )
    repo.delete_snippets_by_version(version_id, user_id)
    repo.create_snippets(snippets_to_save)


def mark_pipeline_failed(
    *,
    repo: MaterialRepository,
    session: Session,
    material_id: uuid.UUID,
    version_id: uuid.UUID,
    user_id: uuid.UUID,
    failed_stage: str,
    exc: Exception,
    redis_client: Any | None = None,
) -> None:
    """回滚当前事务并将资料与版本状态原子置为 FAILED。"""
    clear_cached_parse_progress(version_id, redis_client=redis_client)
    session.rollback()
    try:
        error_msg = getattr(exc, "message", str(exc))
        repo.update_version_status(
            version_id=version_id,
            user_id=user_id,
            status=ParseStatus.FAILED.value,
            failed_stage=failed_stage,
            error_message=str(error_msg)[:500],
        )
        repo.update_material_status(
            material_id=material_id,
            user_id=user_id,
            status=MaterialStatus.FAILED.value,
        )
        session.commit()
    except Exception:
        session.rollback()


__all__ = [
    "ACTIVE_PARSE_STATUSES",
    "MaterialDetailView",
    "build_contextual_snippet_text",
    "chunk_embed_and_replace_snippets",
    "clear_cached_parse_progress",
    "denoise_pptx_slides",
    "get_cached_parse_progress",
    "get_cached_parse_progress_batch",
    "is_heading_block",
    "mark_pipeline_failed",
    "prepare_material_snippets",
    "process_initial_ocr_page",
    "repair_garbled_pdf_pages",
    "resolve_progress_redis_client",
    "set_cached_parse_progress",
    "transcribe_dirty_pages_with_vlm",
]
