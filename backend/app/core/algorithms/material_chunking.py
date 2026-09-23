"""Material chunking algorithm module.

Implements pure functional text chunking with multi-level punctuation degradation,
semantic overlap alignment, isolated short snippet merging, and safety truncation.
Complies with pure functional kernel constraints (zero external I/O, zero network/ORM dependencies).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

# 决策基线条目与依据常量注释：
# 依据：概要设计说明书第 3.2 节知识片段切分标准，单个检索单元适配嵌入向量模型最佳窗口
DEFAULT_MAX_CHARS: int = 800

# 依据：概要设计说明书与需求规格说明书第 3.2.1 节，相邻片段保留约 15% 上下文语义重叠
DEFAULT_OVERLAP_CHARS: int = 120

# 依据：软件需求规格说明书第 3.1.2 节资料清洗规范
# 低于 80 字符的片段语义信息过少，需合并提升检索质量
DEFAULT_MIN_CHARS: int = 80

# 依据：系统防护基线与 NFR-22 限制，单份资料切片上限 3000 片段，防范超大恶意文档引发拒绝服务
DEFAULT_MAX_SNIPPETS: int = 3000

# 正则匹配非法控制字符（除 \n 与 \t 外）与零宽/BOM 字符
# ASCII \x00-\x08, \x0b-\x0c, \x0e-\x1f, \x7f 以及 Unicode 零宽字符 \u200b-\u200f, \ufeff
ILLEGAL_CONTROL_CHARS_PATTERN: re.Pattern[str] = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\ufeff]"
)

# 一级句末标点（中文 。！？ 与英文 .!? 以及换行符 \n）
PRIMARY_PUNCTUATION_CHARS: str = "。！？!?\n"

# 二级次级标点（中文 ，；、 与英文 ,;）
SECONDARY_PUNCTUATION_CHARS: str = "，；、,;"


@dataclass(frozen=True)
class ParagraphInput:
    """输入段落结构化描述（可选扩展格式）。"""

    text: str
    source_ref: str = "段落"
    doc_type: str = "txt"
    is_title: bool = False
    title_level: int = 0


@dataclass(frozen=True)
class Snippet:
    """输出的不可变知识片段。"""

    index: int
    content: str
    char_count: int
    start_offset: int
    end_offset: int
    chapter_title: str
    source_ref: str
    doc_type: str


@dataclass(frozen=True)
class ChunkingResult:
    """资料分块算法统一输出包装对象。"""

    snippets: tuple[Snippet, ...]
    total_count: int
    is_truncated: bool
    max_chars: int
    overlap_chars: int
    cleaned_chars_count: int
    warnings: tuple[str, ...]


def clean_text_and_count_removals(text: str) -> tuple[str, int]:
    """过滤非法控制字符与零宽字符并返回剔除计数。

    Args:
        text: 待清洗的原始文本字符串。

    Returns:
        tuple[str, int]: 清洗后的文本以及剔除的非法字符总数。
    """
    cleaned_text, count = ILLEGAL_CONTROL_CHARS_PATTERN.subn("", text)
    return cleaned_text, count


def align_overlap_sentence_boundary(prev_text: str, overlap_chars: int) -> str:
    """提取上一个片段末尾的重叠子串并向分句语义首部对齐。

    Args:
        prev_text: 上一个切片的完整正文。
        overlap_chars: 允许的最大重叠字符数。

    Returns:
        str: 对齐到分句首部的重叠文本。
    """
    if overlap_chars <= 0 or not prev_text:
        return ""

    candidate = prev_text[-overlap_chars:]
    # 在候选重叠区中寻找首个标点（包含句末标点与次级标点），向前对齐到分句首部
    match = re.search(r"[。！？!?\n，；、,;]", candidate)
    if match and match.end() < len(candidate):
        return candidate[match.end() :]
    return candidate


def find_best_split_point(text: str, start_index: int, target_end_index: int) -> int:
    """在指定窗口内按多级标点降级策略寻找最佳断句位置。

    Args:
        text: 目标段落正文。
        start_index: 当前切片在段落内的起始字符索引。
        target_end_index: 当前切片在段落内的理想结束字符索引。

    Returns:
        int: 决策出的最佳切分位置索引。
    """
    window = text[start_index:target_end_index]

    # 一级降级：在窗口内从右向左寻找句末标点
    for offset in range(len(window) - 1, -1, -1):
        if window[offset] in PRIMARY_PUNCTUATION_CHARS:
            return start_index + offset + 1

    # 二级降级：在窗口内从右向左寻找次级标点
    for offset in range(len(window) - 1, -1, -1):
        if window[offset] in SECONDARY_PUNCTUATION_CHARS:
            return start_index + offset + 1

    # 三级降级：无任何标点，强制在窗口末尾硬切
    return target_end_index


def split_paragraph_into_ranges(
    text: str, max_chars: int, overlap_chars: int
) -> list[tuple[int, int]]:
    """将单段超长文本基于标点降级与重叠步进切分为多个字符范围。

    Args:
        text: 待切分段落文本。
        max_chars: 单切片字符上限。
        overlap_chars: 实际生效的重叠字符数。

    Returns:
        list[tuple[int, int]]: 各切片在段落内的 (start_index, end_index) 范围列表。
    """
    total_len = len(text)
    if total_len <= max_chars:
        return [(0, total_len)]

    ranges: list[tuple[int, int]] = []
    current_start = 0

    while True:
        if total_len - current_start <= max_chars:
            ranges.append((current_start, total_len))
            break

        target_end = current_start + max_chars
        split_end = find_best_split_point(text, current_start, target_end)
        ranges.append((current_start, split_end))

        if overlap_chars > 0:
            slice_text = text[current_start:split_end]
            aligned_overlap = align_overlap_sentence_boundary(slice_text, overlap_chars)

            if aligned_overlap and len(aligned_overlap) < (split_end - current_start):
                current_start = split_end - len(aligned_overlap)
            else:
                current_start = split_end
        else:
            current_start = split_end

    return ranges


def merge_isolated_short_snippets(
    snippets: list[Snippet], min_chars: int, max_chars: int = DEFAULT_MAX_CHARS
) -> list[Snippet]:
    """对字符数低于下限的孤立片段执行向后/向前双向合并。

    Args:
        snippets: 初步生成的切片列表。
        min_chars: 短片段判断阈值。
        max_chars: 单片段字符上限约束。

    Returns:
        list[Snippet]: 合并优化后的切片列表。
    """
    if min_chars <= 0:
        return snippets

    merged: list[Snippet] = []
    pending_short: Snippet | None = None

    for snippet in snippets:
        if pending_short is not None:
            combined_len = pending_short.char_count + 1 + snippet.char_count
            if combined_len <= max_chars:
                # 将前一个短片段向后合并到当前片段首部
                new_content = pending_short.content + "\n" + snippet.content
                merged_snippet = Snippet(
                    index=len(merged),
                    content=new_content,
                    char_count=len(new_content),
                    start_offset=pending_short.start_offset,
                    end_offset=snippet.end_offset,
                    chapter_title=pending_short.chapter_title or snippet.chapter_title,
                    source_ref=pending_short.source_ref,
                    doc_type=pending_short.doc_type,
                )
                merged.append(merged_snippet)
                pending_short = None
                continue

            # 超过 max_chars 则无法向后合并，保留独立
            merged.append(pending_short)
            pending_short = None

        if snippet.char_count < min_chars:
            pending_short = snippet
        else:
            merged.append(snippet)

    # 若末尾残留未合并的孤立短片段，尝试向前合并至前一个切片
    if pending_short is not None:
        if merged:
            prev = merged[-1]
            combined_len = prev.char_count + 1 + pending_short.char_count
            if combined_len <= max_chars:
                merged.pop()
                new_content = prev.content + "\n" + pending_short.content
                tail_merged = Snippet(
                    index=prev.index,
                    content=new_content,
                    char_count=len(new_content),
                    start_offset=prev.start_offset,
                    end_offset=pending_short.end_offset,
                    chapter_title=prev.chapter_title or pending_short.chapter_title,
                    source_ref=prev.source_ref,
                    doc_type=prev.doc_type,
                )
                merged.append(tail_merged)
            else:
                merged.append(pending_short)
        else:
            merged.append(pending_short)

    # 重新规格化 index 序号
    reindexed: list[Snippet] = []
    for idx, item in enumerate(merged):
        reindexed.append(
            Snippet(
                index=idx,
                content=item.content,
                char_count=item.char_count,
                start_offset=item.start_offset,
                end_offset=item.end_offset,
                chapter_title=item.chapter_title,
                source_ref=item.source_ref,
                doc_type=item.doc_type,
            )
        )
    return reindexed


def split_material_into_snippets(
    paragraphs: Sequence[str | ParagraphInput],
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
    max_snippets: int = DEFAULT_MAX_SNIPPETS,
    default_doc_type: str = "txt",
    default_source_ref: str = "段落",
) -> ChunkingResult:
    """把解析后的段落序列切分为可检索的知识片段。

    Args:
        paragraphs: 段落序列，支持原生字符串或 ParagraphInput 结构体。
        max_chars: 单个片段字符数上限，默认 800。
        overlap_chars: 相邻片段字符重叠量，默认 120。
        min_chars: 孤立短片段合并下限字符数，默认 80。
        max_snippets: 单份资料切片上限安全门槛，默认 3000。
        default_doc_type: 字符串段落默认的资料类型标记。
        default_source_ref: 字符串段落默认的来源标记。

    Returns:
        ChunkingResult: 包含只读知识片段列表、截断状态与审计元数据的包装对象。

    Raises:
        ValueError: 当 max_chars <= 0、overlap_chars < 0、min_chars < 0
            或 max_snippets <= 0 时抛出。
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must be a non-negative integer")
    if min_chars < 0:
        raise ValueError("min_chars must be a non-negative integer")
    if max_snippets <= 0:
        raise ValueError("max_snippets must be a positive integer")

    warnings_list: list[str] = []
    effective_overlap = overlap_chars
    if overlap_chars >= max_chars:
        effective_overlap = 0
        warnings_list.append(
            f"overlap_chars ({overlap_chars}) >= max_chars ({max_chars}), degraded to 0 overlap"
        )

    # 阶段 1: 文本预清洗与段落标准化
    total_cleaned_chars = 0
    current_chapter_title = ""
    raw_snippets: list[Snippet] = []
    global_char_offset = 0

    for item in paragraphs:
        if isinstance(item, ParagraphInput):
            raw_text = item.text
            source_ref = item.source_ref
            doc_type = item.doc_type
            is_title = item.is_title
        else:
            raw_text = item
            source_ref = default_source_ref
            doc_type = default_doc_type
            is_title = False

        cleaned_text, removed_count = clean_text_and_count_removals(raw_text)
        total_cleaned_chars += removed_count

        if not cleaned_text.strip():
            continue

        if is_title:
            current_chapter_title = cleaned_text.strip()
            continue

        para_start_offset = global_char_offset
        ranges = split_paragraph_into_ranges(cleaned_text, max_chars, effective_overlap)

        for start_idx, end_idx in ranges:
            snippet_content = cleaned_text[start_idx:end_idx]
            raw_snippets.append(
                Snippet(
                    index=len(raw_snippets),
                    content=snippet_content,
                    char_count=len(snippet_content),
                    start_offset=para_start_offset + start_idx,
                    end_offset=para_start_offset + end_idx,
                    chapter_title=current_chapter_title,
                    source_ref=source_ref,
                    doc_type=doc_type,
                )
            )

        global_char_offset += len(cleaned_text)

    # 阶段 2: 孤立短段双向合并
    optimized_snippets = merge_isolated_short_snippets(raw_snippets, min_chars, max_chars)
    total_count = len(optimized_snippets)

    # 阶段 3: 3000 上限安全截断
    is_truncated = False
    if total_count > max_snippets:
        is_truncated = True
        warnings_list.append(
            f"Total snippets ({total_count}) exceeded max_snippets ({max_snippets}), "
            f"truncated to {max_snippets}"
        )
        final_snippets = tuple(optimized_snippets[:max_snippets])
    else:
        final_snippets = tuple(optimized_snippets)

    return ChunkingResult(
        snippets=final_snippets,
        total_count=total_count,
        is_truncated=is_truncated,
        max_chars=max_chars,
        overlap_chars=effective_overlap,
        cleaned_chars_count=total_cleaned_chars,
        warnings=tuple(warnings_list),
    )
