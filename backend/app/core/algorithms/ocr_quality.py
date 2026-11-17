"""OCR recognition quality gate algorithm pure functional kernel.

Implements OCR quality gate validation based on gibberish ratio,
valid character count, and page completeness.
Strictly adheres to pure functional kernel constraints
(zero external I/O, zero network/ORM dependencies).
"""

import enum
import re
from collections.abc import Sequence
from dataclasses import dataclass

# 依据：概要设计说明书第 3.3/6.2 节与需求规格说明书 FR-08，单页乱码率门禁上限为 15% (0.15)
# 超过 15% 表明拍摄模糊、严重反光或文档污损，强行出题会导致 LLM 严重幻觉
DEFAULT_MAX_GIBBERISH_RATIO: float = 0.15

# 依据：概要设计说明书第 3.3/6.2 节与需求规格说明书 FR-08，单页有效识别字数门禁下限为 40 字
# 低于 40 字符不足以提取有效知识点，通常为封面、空白页或严重残页
DEFAULT_MIN_VALID_CHARS: int = 40

# 依据：概要设计说明书第 3.3/6.2 节与需求规格说明书 FR-08，单页文本长度低于同批中位数 30% 判为残缺
# 用于识别拍摄折角、镜头遮挡截断等页面不完整缺陷
DEFAULT_MEDIAN_LENGTH_RATIO: float = 0.30

# 依据：概要设计说明书第 3.3/6.2 节与需求规格说明书 FR-09，单页就地重拍上限为 3 次
# 达到 3 次仍不合格时，触发最终失败熔断并引导用户切换其它导入方式，防止无限重试产生成本与死循环
MAX_RESHOOT_ATTEMPTS: int = 3

# 预编译正则：非法控制字符与零宽/BOM 字符
# 过滤除换行 \n 与制表符 \t 外的 ASCII 控制字符（\x00-\x08, \x0b-\x0c, \x0e-\x1f, \x7f）
# 以及 Unicode 零宽/BOM 字符（\u200b-\u200f, \ufeff）
ILLEGAL_CONTROL_CHARS_PATTERN: re.Pattern[str] = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\ufeff]"
)

# 预编译正则：有效中文单字（CJK 统一表意字符）
CJK_CHAR_PATTERN: re.Pattern[str] = re.compile(r"[\u4e00-\u9fff]")

# 预编译正则：有效英文连续单词与阿拉伯连续数字单元
WORD_OR_NUMBER_PATTERN: re.Pattern[str] = re.compile(r"[a-zA-Z]+|[0-9]+")

# 预编译正则：合法可打印字符（中英文字符、数字、中英文常用标点符号与空白符）
VALID_PRINTABLE_CHAR_PATTERN: re.Pattern[str] = re.compile(
    r"[\u4e00-\u9fff\w\s，。！？；：“”‘’（）【】《》、…—·\.,!?:;'\"()\[\]{}/\\-_+=*&%$#@~^<>|`]"
)

# 符号乱码探测集合：覆盖 SymbolMT 等缺失 ToUnicode 映射时常见的 ASCII 伪符号字符
_GARBLE_SYMBOL_CHARS: frozenset[str] = frozenset("!\"#$%&'*=?@^~")
_ALL_ASCII_SYMBOL_CHARS: frozenset[str] = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_NON_DOLLAR_CLUSTER_RE: re.Pattern[str] = re.compile(
    r"(?:[!\"#$%&'*=?@^~]{2,}|(?:[A-Za-z0-9]?[!\"#%&'*=?@^~]){2,}[A-Za-z0-9]?)"
)
_MARKDOWN_DECORATION_RE: re.Pattern[str] = re.compile(
    r"^(?:\|[-:|]+\||[-=*#~_]{2,}|\*\*[^*]+\*\*[.,:;!?]?|#{1,6}|\$\$?|```.*)$"
)
_MARKDOWN_BOLD_INLINE_RE: re.Pattern[str] = re.compile(r"\*\*([^*]+)\*\*")
_REPEATED_SAME_SYMBOL_RE: re.Pattern[str] = re.compile(r"^([!\"#$%&'*=?@^~`\-_])\1+$")


class UnqualifiedReasonCode(enum.StrEnum):
    """不合格原因代码枚举，严格遵循命名白名单与规范。"""

    PAGE_INCOMPLETE = "page_incomplete"
    GIBBERISH_EXCEEDED = "gibberish_exceeded"
    INSUFFICIENT_CHARS = "insufficient_chars"


@dataclass(frozen=True)
class OCRPageInput:
    """输入页面数据结构化描述。"""

    page_number: int
    raw_text: str
    reshoot_count: int = 0
    image_storage_key: str = ""


@dataclass(frozen=True)
class OCRQualityConfig:
    """门禁算法配置参数。"""

    max_gibberish_ratio: float = DEFAULT_MAX_GIBBERISH_RATIO
    min_valid_chars: int = DEFAULT_MIN_VALID_CHARS
    median_length_ratio: float = DEFAULT_MEDIAN_LENGTH_RATIO
    max_reshoot_attempts: int = MAX_RESHOOT_ATTEMPTS

    def __post_init__(self) -> None:
        """校验配置参数合法性。

        Raises:
            ValueError: 当配置参数超出合法边界时抛出。
        """
        if not (0.0 <= self.max_gibberish_ratio <= 1.0):
            raise ValueError("max_gibberish_ratio must be between 0.0 and 1.0")
        if self.min_valid_chars < 0:
            raise ValueError("min_valid_chars must be non-negative")
        if self.median_length_ratio < 0.0:
            raise ValueError("median_length_ratio must be non-negative")
        if self.max_reshoot_attempts < 0:
            raise ValueError("max_reshoot_attempts must be non-negative")


@dataclass(frozen=True)
class PageQualityResult:
    """单页质量门禁评估结果（不可变值对象）。"""

    page_number: int
    raw_text_length: int
    cleaned_text_length: int
    valid_char_count: int
    gibberish_ratio: float
    is_page_complete: bool
    is_qualified: bool
    unqualified_code: UnqualifiedReasonCode | None
    unqualified_reason: str | None
    reshoot_count: int
    is_terminal_failure: bool
    cleaned_chars_count: int


@dataclass(frozen=True)
class BatchQualityReport:
    """批次页面识别质量门禁统一产出报告。"""

    page_results: tuple[PageQualityResult, ...]
    total_pages: int
    qualified_pages: int
    unqualified_pages: int
    is_all_qualified: bool
    median_length: float
    terminal_failure_pages: tuple[int, ...]


def clean_ocr_text(text: str) -> tuple[str, int]:
    """过滤文本中非法控制字符与零宽字符并返回剔除计数。

    Args:
        text: 待清洗的原始文本字符串。

    Returns:
        tuple[str, int]: 清洗后文本及剔除字符数。
    """
    cleaned_text, removal_count = ILLEGAL_CONTROL_CHARS_PATTERN.subn("", text)
    return cleaned_text, removal_count


clean_ocr_text_and_count_removals = clean_ocr_text


def count_valid_characters(text: str) -> int:
    """统计文本中可用中文字符与英文单词及数字单元总数。

    中文单个汉字计 1 字，英文连续单词计 1 词，阿拉伯连续数字串计 1 单元。

    Args:
        text: 已清洗的输入文本字符串。

    Returns:
        int: 有效文字与词汇单元总数。
    """
    cjk_count = len(CJK_CHAR_PATTERN.findall(text))
    word_or_number_count = len(WORD_OR_NUMBER_PATTERN.findall(text))
    return cjk_count + word_or_number_count


def calculate_gibberish_ratio(text: str) -> float:
    """计算文本中乱码与杂乱不可解析字符的比例 (0.0 ~ 1.0)。

    空文本或全空白文本直接返回 1.0 (100%)。

    Args:
        text: 已清洗的输入文本字符串。

    Returns:
        float: 乱码字符占非空白字符总数的比例。
    """
    non_space_chars = [char for char in text if not char.isspace()]
    if not non_space_chars:
        return 1.0
    gibberish_count = sum(
        1 for char in non_space_chars if not VALID_PRINTABLE_CHAR_PATTERN.match(char)
    )
    return gibberish_count / len(non_space_chars)


def _is_garble_cluster_token(token: str) -> bool:
    """判断单个空白分隔 token 是否包含高密度符号乱码簇。"""
    if not token or token.startswith(("http://", "https://")):
        return False
    stripped_md = _MARKDOWN_BOLD_INLINE_RE.sub(r"\1", token)
    if _MARKDOWN_DECORATION_RE.match(stripped_md) or _REPEATED_SAME_SYMBOL_RE.match(stripped_md):
        return False
    non_dollar_count = sum(1 for ch in stripped_md if ch in _GARBLE_SYMBOL_CHARS and ch != "$")
    if non_dollar_count < 2:
        return False
    return bool(_NON_DOLLAR_CLUSTER_RE.search(stripped_md))


def _is_short_symbol_burst_token(token: str) -> bool:
    """判断是否为跨空白符乱码碎片中的短符号 token。"""
    if len(token) > 4 or token in {"|", "-", "*", "$$", "$"}:
        return False
    return all(ch in _ALL_ASCII_SYMBOL_CHARS for ch in token) and any(
        ch in _GARBLE_SYMBOL_CHARS for ch in token
    )


def _collect_line_garble_fragments(line: str) -> tuple[list[str], bool]:
    """提取单行内的 ASCII 符号乱码簇并判断是否整行为孤立符号噪声行。"""
    stripped = line.strip()
    if not stripped or _MARKDOWN_DECORATION_RE.match(stripped):
        return [], False

    tokens = stripped.split()
    if tokens and tokens[0].startswith("#") and len(set(tokens[0])) == 1:
        tokens = tokens[1:]

    fragments: list[str] = [tok for tok in tokens if _is_garble_cluster_token(tok)]

    burst: list[str] = []
    for tok in tokens:
        if _is_short_symbol_burst_token(tok):
            burst.append(tok)
            continue
        if len(burst) >= 2 and sum(len(b) for b in burst) >= 3:
            fragments.append(" ".join(burst))
        burst.clear()
    if len(burst) >= 2 and sum(len(b) for b in burst) >= 3:
        fragments.append(" ".join(burst))

    non_ws = [ch for ch in stripped if not ch.isspace()]
    sym_only_line = False
    if len(non_ws) >= 2:
        sym_count = sum(1 for ch in non_ws if ch in _ALL_ASCII_SYMBOL_CHARS)
        garble_count = sum(1 for ch in non_ws if ch in _GARBLE_SYMBOL_CHARS and ch != "$")
        if sym_count / len(non_ws) >= 0.8 and garble_count >= 2:
            sym_only_line = True
            if not fragments:
                fragments.append(stripped)

    return fragments, sym_only_line


def detect_symbol_garble(text: str) -> tuple[bool, float, tuple[str, ...]]:
    """探测文档/页面文本中是否存在缺失字体编码导致的 ASCII 符号乱码簇。

    专门识别 SymbolMT/Wingdings 等符号字体缺失 `/ToUnicode` 映射时产生的
    ``AB&A&``、``"#$``、``!" ! #`` 等噪声簇及孤立符号噪声行，同时避免对正常 LaTeX
    或 Markdown 装饰符误报。

    Args:
        text: 待检测文本。

    Returns:
        tuple[bool, float, tuple[str, ...]]:
            (是否检测到符号乱码, 乱码符号占比估算, 命中的典型乱码片段元组)。
    """
    if not text or not text.strip():
        return False, 0.0, ()

    non_ws_total = sum(1 for ch in text if not ch.isspace())
    if non_ws_total == 0:
        return False, 0.0, ()

    all_fragments: list[str] = []
    sym_only_lines = 0
    for line in text.splitlines():
        line_frags, is_sym_line = _collect_line_garble_fragments(line)
        all_fragments.extend(line_frags)
        if is_sym_line:
            sym_only_lines += 1

    garble_char_total = sum(
        sum(1 for ch in frag if ch in _ALL_ASCII_SYMBOL_CHARS) for frag in all_fragments
    )
    garble_ratio = min(1.0, garble_char_total / non_ws_total)
    is_garbled = (
        sym_only_lines >= 1
        or len(all_fragments) >= 2
        or (len(all_fragments) == 1 and garble_ratio >= 0.15)
    )
    dedup_frags = tuple(dict.fromkeys(all_fragments[:10]))
    return is_garbled, round(garble_ratio, 4), dedup_frags


def sanitize_symbol_garble(text: str) -> str:
    """在缺少视觉/大模型修复时确定性清除不可读 ASCII 符号乱码噪声。"""
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        _frags, is_sym_line = _collect_line_garble_fragments(line)
        if is_sym_line:
            continue
        kept_tokens = [tok for tok in line.split() if not _is_garble_cluster_token(tok)]
        rebuilt = " ".join(kept_tokens).strip()
        if rebuilt:
            cleaned_lines.append(rebuilt)
    return "\n".join(cleaned_lines)


def calculate_median_length(lengths: Sequence[int]) -> float:
    """计算同批页面文本长度中位数（含单页与双页降级逻辑）。

    Args:
        lengths: 同批页面清洗后文本长度序列。

    Returns:
        float: 计算所得的基准中位数或均值。
    """
    total_items = len(lengths)
    if total_items <= 1:
        return 0.0
    if total_items == 2:
        return (lengths[0] + lengths[1]) / 2.0

    sorted_lengths = sorted(lengths)
    middle_index = total_items // 2
    if total_items % 2 == 1:
        return float(sorted_lengths[middle_index])
    return (sorted_lengths[middle_index - 1] + sorted_lengths[middle_index]) / 2.0


def evaluate_page_quality(
    page: OCRPageInput,
    baseline_median_length: float,
    config: OCRQualityConfig,
    is_single_page: bool = False,
) -> PageQualityResult:
    """执行单页质量门禁评估与不合格原因仲裁。

    判定优先级：
    页面不完整 (PAGE_INCOMPLETE) > 乱码率超限 (GIBBERISH_EXCEEDED)
    > 有效字数不足 (INSUFFICIENT_CHARS)。

    Args:
        page: 输入单页 OCR 数据。
        baseline_median_length: 同批页面基准中位数长度。
        config: 质量门禁阈值配置。
        is_single_page: 是否为单页批次模式（单页模式跳过完整性检查）。

    Returns:
        PageQualityResult: 单页质量评估不可变结果。
    """
    cleaned_text, cleaned_chars_count = clean_ocr_text(page.raw_text)
    raw_text_length = len(page.raw_text)
    cleaned_text_length = len(cleaned_text)

    # 边界情况：空文本或全空白文本
    if not cleaned_text.strip():
        is_terminal = page.reshoot_count >= config.max_reshoot_attempts
        return PageQualityResult(
            page_number=page.page_number,
            raw_text_length=raw_text_length,
            cleaned_text_length=cleaned_text_length,
            valid_char_count=0,
            gibberish_ratio=1.0,
            is_page_complete=False,
            is_qualified=False,
            unqualified_code=UnqualifiedReasonCode.PAGE_INCOMPLETE,
            unqualified_reason="页面内容不完整，显著低于同批页面文本长度",
            reshoot_count=page.reshoot_count,
            is_terminal_failure=is_terminal,
            cleaned_chars_count=cleaned_chars_count,
        )

    valid_char_count = count_valid_characters(cleaned_text)
    gibberish_ratio = calculate_gibberish_ratio(cleaned_text)

    # 页面完整性判断
    if is_single_page or baseline_median_length <= 0.0:
        is_page_complete = True
    else:
        threshold_length = baseline_median_length * config.median_length_ratio
        is_page_complete = cleaned_text_length >= threshold_length

    # 优先级仲裁：完整性 > 乱码率 > 有效字数
    is_qualified = True
    unqualified_code: UnqualifiedReasonCode | None = None
    unqualified_reason: str | None = None

    if not is_page_complete:
        is_qualified = False
        unqualified_code = UnqualifiedReasonCode.PAGE_INCOMPLETE
        unqualified_reason = "页面内容不完整，显著低于同批页面文本长度"
    elif gibberish_ratio > config.max_gibberish_ratio:
        is_qualified = False
        unqualified_code = UnqualifiedReasonCode.GIBBERISH_EXCEEDED
        unqualified_reason = f"乱码率过高[{gibberish_ratio:.1%}]，超出门禁上限"
    elif valid_char_count < config.min_valid_chars:
        is_qualified = False
        unqualified_code = UnqualifiedReasonCode.INSUFFICIENT_CHARS
        unqualified_reason = f"有效识别字数不足[{valid_char_count}字]，低于门禁下限"

    is_terminal_failure = (not is_qualified) and (page.reshoot_count >= config.max_reshoot_attempts)

    return PageQualityResult(
        page_number=page.page_number,
        raw_text_length=raw_text_length,
        cleaned_text_length=cleaned_text_length,
        valid_char_count=valid_char_count,
        gibberish_ratio=gibberish_ratio,
        is_page_complete=is_page_complete,
        is_qualified=is_qualified,
        unqualified_code=unqualified_code,
        unqualified_reason=unqualified_reason,
        reshoot_count=page.reshoot_count,
        is_terminal_failure=is_terminal_failure,
        cleaned_chars_count=cleaned_chars_count,
    )


def verify_ocr_quality(
    pages: Sequence[OCRPageInput],
    config: OCRQualityConfig | None = None,
) -> BatchQualityReport:
    """执行批次 OCR 页面质量门禁核验。

    Args:
        pages: 待检测的 OCR 页面输入序列。
        config: 可选算法阈值配置，不传使用标准默认基线。

    Returns:
        BatchQualityReport: 包含逐页判定结果与整批准出结论的报告。

    Raises:
        ValueError: 当配置参数非法时抛出。
    """
    effective_config = config if config is not None else OCRQualityConfig()

    if not pages:
        return BatchQualityReport(
            page_results=(),
            total_pages=0,
            qualified_pages=0,
            unqualified_pages=0,
            is_all_qualified=True,
            median_length=0.0,
            terminal_failure_pages=(),
        )

    # 第一遍扫描：收集各页清洗后长度
    cleaned_lengths = [len(clean_ocr_text(page.raw_text)[0]) for page in pages]
    baseline_median_length = calculate_median_length(cleaned_lengths)
    is_single_page = len(pages) == 1

    # 第二遍扫描：逐页执行门禁评估
    page_results_list: list[PageQualityResult] = []
    terminal_failures: list[int] = []
    qualified_count = 0

    for page in pages:
        result = evaluate_page_quality(
            page=page,
            baseline_median_length=baseline_median_length,
            config=effective_config,
            is_single_page=is_single_page,
        )
        page_results_list.append(result)
        if result.is_qualified:
            qualified_count += 1
        if result.is_terminal_failure:
            terminal_failures.append(page.page_number)

    total_count = len(pages)
    unqualified_count = total_count - qualified_count

    return BatchQualityReport(
        page_results=tuple(page_results_list),
        total_pages=total_count,
        qualified_pages=qualified_count,
        unqualified_pages=unqualified_count,
        is_all_qualified=unqualified_count == 0,
        median_length=baseline_median_length,
        terminal_failure_pages=tuple(terminal_failures),
    )
